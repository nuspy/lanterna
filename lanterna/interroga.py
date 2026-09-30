"""Interrogazioni dichiarate: niente SQL libero, solo combinazioni di un catalogo.

L'applicazione descrive le proprie **sorgenti** (una tabella o un join), ciascuna con le **misure**
(aggregati: conteggi, somme, medie) e le **dimensioni** (per cui raggruppare e filtrare) che ha senso
chiederle. La console, l'AI e gli export compongono un'`Interrogazione` scegliendo nomi dal catalogo;
qui si valida ogni nome e si costruisce la query con SQLAlchemy, con i valori sempre legati come
parametri. Un nome sconosciuto è un errore (`ErroreInterrogazione`, per la console un 422), mai un
pezzo di SQL.

Due tutele:
- un tempo massimo per query (`statement_timeout`), perché un incrocio largo su mesi di eventi non
  deve bloccare il database dell'applicazione;
- la **soglia k** (facoltativa, obbligatoria per AI ed export): se fra le dimensioni ce n'è una
  «personale» (età, genere...), le celle con meno di k persone spariscono e si contano a parte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, FromClause, String, and_, cast, func, literal_column, not_, or_, select, text

Formato = Literal["intero", "decimale", "euro", "percento", "secondi"]


class ErroreInterrogazione(ValueError):
    """Un'interrogazione non valida per il catalogo: un nome sconosciuto, un intervallo assurdo."""


@dataclass(frozen=True)
class Misura:
    etichetta: str
    sql: Callable[[], ColumnElement]
    formato: Formato = "intero"
    descrizione: str = ""


@dataclass(frozen=True)
class Dimensione:
    etichetta: str
    sql: Callable[[], ColumnElement]
    #: Descrive una persona (età, genere, città...): con la soglia k attiva le celle piccole spariscono.
    personale: bool = False
    descrizione: str = ""


@dataclass(frozen=True)
class Sorgente:
    etichetta: str
    da: Callable[[], FromClause]
    tempo: Callable[[], ColumnElement]
    misure: Dict[str, Misura]
    dimensioni: Dict[str, Dimensione]
    #: Quante persone distinte stanno in una cella (per la soglia k).
    persone: Optional[Callable[[], ColumnElement]] = None
    #: Un filtro sempre applicato (es. solo pagamenti conclusi).
    dove: Optional[Callable[[], ColumnElement]] = None
    #: Dimensioni dinamiche `prop:<chiave>` sulle proprietà JSON (solo sorgenti di eventi).
    proprieta: Optional[Callable[[str], ColumnElement]] = None
    descrizione: str = ""


Catalogo = Dict[str, Sorgente]

_PROP = re.compile(r"^prop:([a-zA-Z][a-zA-Z0-9_]{0,39})$")
GRANULARITA = {"giorno": "day", "settimana": "week", "mese": "month"}


class Filtro(BaseModel):
    dimensione: str = Field(max_length=60)
    operatore: Literal["uguale", "diverso", "in", "non_in", "contiene", "vuoto", "non_vuoto"] = "uguale"
    valori: List[Any] = Field(default_factory=list, max_length=50)


class Ordine(BaseModel):
    campo: str = Field(max_length=60)
    discendente: bool = True


class Interrogazione(BaseModel):
    sorgente: str = Field(max_length=40)
    misure: List[str] = Field(min_length=1, max_length=6)
    dimensioni: List[str] = Field(default_factory=list, max_length=3)
    filtri: List[Filtro] = Field(default_factory=list, max_length=10)
    da: date
    a: date
    granularita: Optional[Literal["giorno", "settimana", "mese"]] = None
    confronto: Optional[Literal["precedente", "anno_prima"]] = None
    ordine: Optional[Ordine] = None
    limite: int = Field(default=200, ge=1, le=1000)


@dataclass
class Risultato:
    colonne: List[Dict[str, Any]]
    righe: List[Dict[str, Any]]
    totali: Dict[str, Any]
    da: date
    a: date
    confronto: Optional[Dict[str, Any]] = None
    soppresse: int = 0
    troncato: bool = False

    def json(self) -> Dict[str, Any]:
        return {
            "colonne": self.colonne,
            "righe": self.righe,
            "totali": self.totali,
            "da": self.da.isoformat(),
            "a": self.a.isoformat(),
            "confronto": self.confronto,
            "soppresse": self.soppresse,
            "troncato": self.troncato,
        }


# ---- validazione --------------------------------------------------------------------------


def _dimensione(src: Sorgente, nome: str) -> Dimensione:
    if nome in src.dimensioni:
        return src.dimensioni[nome]
    m = _PROP.match(nome)
    if m and src.proprieta is not None:
        chiave = m.group(1)
        return Dimensione(etichetta=chiave, sql=lambda: src.proprieta(chiave))
    raise ErroreInterrogazione(f"dimensione sconosciuta: {nome}")


def valida(catalogo: Catalogo, q: Interrogazione) -> Sorgente:
    src = catalogo.get(q.sorgente)
    if src is None:
        raise ErroreInterrogazione(f"sorgente sconosciuta: {q.sorgente}")
    for m in q.misure:
        if m not in src.misure:
            raise ErroreInterrogazione(f"misura sconosciuta: {m}")
    if len(set(q.misure)) != len(q.misure) or len(set(q.dimensioni)) != len(q.dimensioni):
        raise ErroreInterrogazione("misure o dimensioni ripetute")
    for d in q.dimensioni:
        _dimensione(src, d)
    for f in q.filtri:
        _dimensione(src, f.dimensione)
        if f.operatore not in ("vuoto", "non_vuoto") and not f.valori:
            raise ErroreInterrogazione(f"filtro senza valori: {f.dimensione}")
        for v in f.valori:
            if not isinstance(v, (str, int, float, bool)) or (isinstance(v, str) and len(v) > 200):
                raise ErroreInterrogazione(f"valore di filtro non ammesso: {f.dimensione}")
    if q.a < q.da:
        raise ErroreInterrogazione("l'intervallo finisce prima di cominciare")
    if (q.a - q.da).days > 3 * 366:
        raise ErroreInterrogazione("intervallo troppo lungo (massimo tre anni)")
    if q.ordine and q.ordine.campo not in set(q.misure) | set(q.dimensioni) | {"periodo"}:
        raise ErroreInterrogazione(f"ordine su un campo non richiesto: {q.ordine.campo}")
    return src


# ---- compilazione ---------------------------------------------------------------------------


def limiti(da: date, a: date, fuso: str) -> Tuple[datetime, datetime]:
    """Da mezzanotte di `da` a mezzanotte dopo `a`, nel fuso del sito."""
    z = ZoneInfo(fuso)
    return datetime.combine(da, time(0), z), datetime.combine(a + timedelta(days=1), time(0), z)


def _condizione(espressione: ColumnElement, f: Filtro) -> ColumnElement:
    v = f.valori
    if f.operatore == "uguale":
        return espressione == v[0]
    if f.operatore == "diverso":
        return or_(espressione != v[0], espressione.is_(None))
    if f.operatore == "in":
        return espressione.in_(v)
    if f.operatore == "non_in":
        return or_(not_(espressione.in_(v)), espressione.is_(None))
    if f.operatore == "contiene":
        # I caratteri jolly dell'utente valgono alla lettera.
        testo = str(v[0]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return cast(espressione, String).ilike(f"%{testo}%", escape="\\")
    if f.operatore == "vuoto":
        return espressione.is_(None)
    return espressione.is_not(None)


def compila(
    src: Sorgente,
    q: Interrogazione,
    da: date,
    a: date,
    fuso: str,
    *,
    con_dimensioni: bool = True,
    persone: bool = False,
):
    inizio, fine = limiti(da, a, fuso)
    tempo = src.tempo()
    colonne: List[Any] = []
    nomi: List[str] = []
    if con_dimensioni and q.granularita:
        colonne.append(func.date_trunc(GRANULARITA[q.granularita], func.timezone(fuso, tempo)).label("periodo"))
        nomi.append("periodo")
    if con_dimensioni:
        for nome in q.dimensioni:
            colonne.append(_dimensione(src, nome).sql().label(nome))
            nomi.append(nome)
    n_gruppi = len(nomi)
    for nome in q.misure:
        colonne.append(src.misure[nome].sql().label(nome))
        nomi.append(nome)
    if persone and src.persone is not None:
        colonne.append(src.persone().label("_persone"))

    condizioni = [tempo >= inizio, tempo < fine]
    if src.dove is not None:
        condizioni.append(src.dove())
    for f in q.filtri:
        condizioni.append(_condizione(_dimensione(src, f.dimensione).sql(), f))

    stmt = select(*colonne).select_from(src.da()).where(and_(*condizioni))
    if n_gruppi:
        # Per posizione e non per alias: un alias uguale a una colonna di una delle tabelle (`lingua`
        # in un join fra eventi e sessioni) in GROUP BY vincerebbe la colonna, o sarebbe ambiguo.
        posizione = lambda nome: literal_column(str(nomi.index(nome) + 1))  # noqa: E731
        stmt = stmt.group_by(*[literal_column(str(i + 1)) for i in range(n_gruppi)])
        if q.ordine:
            campo = posizione(q.ordine.campo)
            stmt = stmt.order_by(campo.desc().nulls_last() if q.ordine.discendente else campo.asc().nulls_last())
        elif q.granularita:
            stmt = stmt.order_by(posizione("periodo"), posizione(q.misure[0]).desc().nulls_last())
        else:
            stmt = stmt.order_by(posizione(q.misure[0]).desc().nulls_last())
        stmt = stmt.limit(q.limite + 1)
    return stmt


def _valore(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def periodo_di_confronto(da: date, a: date, tipo: str) -> Tuple[date, date]:
    if tipo == "precedente":
        durata = (a - da).days + 1
        return da - timedelta(days=durata), da - timedelta(days=1)
    try:
        return da.replace(year=da.year - 1), a.replace(year=a.year - 1)
    except ValueError:  # 29 febbraio
        return da - timedelta(days=365), a - timedelta(days=365)


async def esegui(
    sessione,
    catalogo: Catalogo,
    q: Interrogazione,
    *,
    fuso: str = "Europe/Rome",
    k_minimo: Optional[int] = None,
    timeout_ms: int = 10_000,
) -> Risultato:
    src = valida(catalogo, q)
    await sessione.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    personali = any(_dimensione(src, d).personale for d in q.dimensioni)
    applica_k = bool(k_minimo) and personali and src.persone is not None

    async def righe_di(da: date, a: date) -> Tuple[List[Dict[str, Any]], int, bool]:
        stmt = compila(src, q, da, a, fuso, persone=applica_k)
        grezze = [dict(r) for r in (await sessione.execute(stmt)).mappings().all()]
        troncato = len(grezze) > q.limite if (q.dimensioni or q.granularita) else False
        grezze = grezze[: q.limite]
        soppresse = 0
        if applica_k:
            tenute = []
            for r in grezze:
                if (r.pop("_persone") or 0) < k_minimo:
                    soppresse += 1
                else:
                    tenute.append(r)
            grezze = tenute
        return [{k: _valore(v) for k, v in r.items()} for r in grezze], soppresse, troncato

    async def totali_di(da: date, a: date) -> Dict[str, Any]:
        stmt = compila(src, q, da, a, fuso, con_dimensioni=False)
        riga = (await sessione.execute(stmt)).mappings().first() or {}
        return {k: _valore(v) for k, v in dict(riga).items()}

    righe, soppresse, troncato = await righe_di(q.da, q.a)
    totali = await totali_di(q.da, q.a)
    confronto = None
    if q.confronto:
        cda, ca = periodo_di_confronto(q.da, q.a, q.confronto)
        crighe, csoppresse, _ = await righe_di(cda, ca)
        confronto = {
            "tipo": q.confronto, "da": cda.isoformat(), "a": ca.isoformat(),
            "righe": crighe, "totali": await totali_di(cda, ca), "soppresse": csoppresse,
        }

    colonne: List[Dict[str, Any]] = []
    if q.granularita:
        colonne.append({"nome": "periodo", "etichetta": q.granularita, "tipo": "periodo"})
    for d in q.dimensioni:
        dim = _dimensione(src, d)
        colonne.append({"nome": d, "etichetta": dim.etichetta, "tipo": "dimensione", "personale": dim.personale})
    for m in q.misure:
        mis = src.misure[m]
        colonne.append({"nome": m, "etichetta": mis.etichetta, "tipo": "misura", "formato": mis.formato})
    return Risultato(colonne, righe, totali, q.da, q.a, confronto, soppresse, troncato)


def descrivi(catalogo: Catalogo) -> Dict[str, Any]:
    """Il catalogo per la console: nomi, etichette, formati. Nessuna espressione SQL."""
    return {
        nome: {
            "etichetta": s.etichetta,
            "descrizione": s.descrizione,
            "proprieta": s.proprieta is not None,
            "misure": {k: {"etichetta": m.etichetta, "formato": m.formato, "descrizione": m.descrizione} for k, m in s.misure.items()},
            "dimensioni": {
                k: {"etichetta": d.etichetta, "personale": d.personale, "descrizione": d.descrizione}
                for k, d in s.dimensioni.items()
            },
        }
        for nome, s in catalogo.items()
    }
