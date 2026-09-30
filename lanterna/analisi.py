"""Imbuti e coorti: le due analisi che un'interrogazione a gruppi non sa fare.

**Imbuto**: quante sessioni (o utenti) compiono il passo 1, quante di queste poi il passo 2, e così
via, in ordine di tempo. Ogni passo è un evento (con eventuali proprietà da rispettare); un passo
conta solo se avviene dopo il precedente, e facoltativamente entro N ore dal primo.

**Coorti**: le entità si raggruppano per il periodo del loro primo momento (iscrizione, primo
acquisto...) e si segue quante restano attive — o quanto spendono — nei periodi successivi.
Generiche: l'applicazione passa due SELECT, `(k, t0)` e `(k, t[, v])`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import and_, func, literal, literal_column, or_, select, text
from sqlalchemy.sql import Select

from .schema import Tabelle

DIMENSIONI_IMBUTO = ("canale", "dispositivo", "paese", "utm_campagna", "lingua", "so", "browser")


@dataclass(frozen=True)
class Passo:
    evento: str
    etichetta: str = ""
    proprieta: Dict[str, str] = field(default_factory=dict)
    #: Prefissi di percorso ammessi (uno qualunque): una pagina che esiste in più lingue
    #: (`/pricing`, `/it/piano`) è un passo solo.
    percorsi: tuple = ()


async def imbuto(
    sessione,
    tabelle: Tabelle,
    passi: List[Passo],
    inizio: datetime,
    fine: datetime,
    *,
    per: Literal["sessione", "utente"] = "sessione",
    entro_ore: Optional[int] = None,
    segmento: Optional[str] = None,
    timeout_ms: int = 10_000,
) -> Dict[str, Any]:
    """Conteggi per passo, totali e (con `segmento`, solo per sessione) per valore del segmento."""
    if not 2 <= len(passi) <= 8:
        raise ValueError("un imbuto ha da 2 a 8 passi")
    if segmento is not None and (per != "sessione" or segmento not in DIMENSIONI_IMBUTO):
        raise ValueError(f"segmento non ammesso: {segmento}")
    await sessione.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    e, s = tabelle.eventi, tabelle.sessioni
    chiave = e.c.sessione_id if per == "sessione" else e.c.utente_id

    def condizioni(p: Passo):
        c = [e.c.nome == p.evento, e.c.ts >= inizio, e.c.ts < fine, chiave.is_not(None)]
        for k, v in p.proprieta.items():
            c.append(e.c.proprieta[k].astext == str(v))
        if p.percorsi:
            c.append(or_(*[or_(e.c.percorso == x, e.c.percorso.startswith(x.rstrip("/") + "/")) for x in p.percorsi]))
        return c

    fasi = []
    precedente = None
    for i, p in enumerate(passi):
        if precedente is None:
            q = select(chiave.label("k"), func.min(e.c.ts).label("t"), func.min(e.c.ts).label("t0")).where(
                *condizioni(p)
            ).group_by(chiave)
        else:
            unione = [chiave == precedente.c.k, e.c.ts >= precedente.c.t]
            if entro_ore:
                unione.append(e.c.ts <= precedente.c.t0 + text(f"interval '{int(entro_ore)} hours'"))
            q = (
                select(precedente.c.k, func.min(e.c.ts).label("t"), precedente.c.t0)
                .select_from(precedente.join(e, and_(*unione)))
                .where(*condizioni(p))
                .group_by(precedente.c.k, precedente.c.t0)
            )
        precedente = q.cte(f"passo_{i}")
        fasi.append(precedente)

    if segmento is None:
        stmt = select(*[select(func.count()).select_from(f).scalar_subquery().label(f"p{i}") for i, f in enumerate(fasi)])
        riga = (await sessione.execute(stmt)).mappings().one()
        conteggi = [int(riga[f"p{i}"]) for i in range(len(fasi))]
        return {"passi": _passi(passi, conteggi), "segmenti": None}

    colonna = s.c[segmento]
    segmenti: Dict[str, List[int]] = {}
    for i, f in enumerate(fasi):
        stmt = (
            select(func.coalesce(colonna, literal("(n.d.)")).label("v"), func.count().label("n"))
            .select_from(f.join(s, s.c.id == f.c.k))
            .group_by(literal_column("1"))
        )
        for v, n in (await sessione.execute(stmt)).all():
            segmenti.setdefault(str(v), [0] * len(fasi))[i] = int(n)
    totali = [sum(v[i] for v in segmenti.values()) for i in range(len(fasi))]
    ordinati = sorted(segmenti.items(), key=lambda kv: -kv[1][0])[:20]
    return {
        "passi": _passi(passi, totali),
        "segmenti": [{"valore": v, "passi": _passi(passi, c)} for v, c in ordinati],
    }


def _passi(passi: List[Passo], conteggi: List[int]) -> List[Dict[str, Any]]:
    primo = conteggi[0] if conteggi else 0
    uscita = []
    for i, (p, n) in enumerate(zip(passi, conteggi)):
        prima = conteggi[i - 1] if i else n
        uscita.append({
            "evento": p.evento,
            "etichetta": p.etichetta or p.evento,
            "n": n,
            "dal_primo": round(n / primo, 4) if primo else None,
            "dal_precedente": round(n / prima, 4) if prima else None,
        })
    return uscita


async def coorti(
    sessione,
    primo: Select,
    attivita: Select,
    *,
    granularita: Literal["settimana", "mese"] = "mese",
    periodi: int = 12,
    somma: bool = False,
    fuso: str = "Europe/Rome",
    timeout_ms: int = 10_000,
) -> List[Dict[str, Any]]:
    """`primo`: SELECT con colonne `k`, `t0`. `attivita`: SELECT con `k`, `t` (e `v` se `somma`).

    Per ogni coorte: dimensione e, per ogni periodo 0..`periodi`, entità attive (o somma di `v`)."""
    await sessione.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
    unita = {"settimana": "week", "mese": "month"}[granularita]
    p = primo.cte("coorte_primo")
    a = attivita.cte("coorte_attivita")
    inizio_p = func.date_trunc(unita, func.timezone(fuso, p.c.t0))
    inizio_a = func.date_trunc(unita, func.timezone(fuso, a.c.t))
    if unita == "month":
        scarto = (func.date_part("year", inizio_a) - func.date_part("year", inizio_p)) * 12 + (
            func.date_part("month", inizio_a) - func.date_part("month", inizio_p)
        )
    else:
        scarto = func.floor((func.extract("epoch", inizio_a) - func.extract("epoch", inizio_p)) / 604800)
    valore = func.coalesce(func.sum(a.c.v), 0) if somma else func.count(func.distinct(a.c.k))
    dettaglio = (
        select(inizio_p.label("coorte"), scarto.label("periodo"), valore.label("valore"))
        .select_from(p.join(a, a.c.k == p.c.k))
        .where(and_(scarto >= 0, scarto <= periodi))
        .group_by(text("1"), text("2"))
    )
    grandezze = select(inizio_p.label("coorte"), func.count().label("n")).select_from(p).group_by(text("1"))
    righe: Dict[Any, Dict[str, Any]] = {}
    for coorte, n in (await sessione.execute(grandezze)).all():
        righe[coorte] = {"coorte": coorte.date().isoformat(), "dimensione": int(n), "valori": [0] * (periodi + 1)}
    for coorte, periodo, v in (await sessione.execute(dettaglio)).all():
        if coorte in righe:
            righe[coorte]["valori"][int(periodo)] = float(v) if somma else int(v)
    return [righe[k] for k in sorted(righe)]
