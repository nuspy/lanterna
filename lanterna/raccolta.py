"""Dal lotto di eventi inviato dal browser alle righe di sessioni ed eventi.

Il corpo che arriva dal browser (JSON, anche come `text/plain` per `sendBeacon`):

    {"v": 1, "id": "<id del browser, solo col consenso>", "lingua": "it",
     "eventi": [{"n": "page_view", "p": "/leggi", "r": "https://www.google.com/",
                 "u": {"utm_source": "..."}, "dt": 1200, "d": 5300, "x": {...}}]}

- `n` nome (minuscole, cifre, `_`), `p` percorso **senza query** (la query può contenere dati
  personali: si scarta anche se il browser la manda), `r` referrer (se ne tiene solo il dominio),
  `u` parametri UTM, `dt` millisecondi trascorsi dall'evento all'invio (l'orologio del browser non
  è affidabile: il tempo è quello del server meno `dt`), `d` durata attiva in ms (per
  `engagement`), `x` proprietà libere, scalari, piccole.

Nessuna eccezione esce di qui per un corpo malformato: si scarta e basta. Chi chiama risponde 204 in
ogni caso, per non dare a un client ostile nessun segnale utile.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.dialects.postgresql import insert

from . import agente as ua_
from . import geo, sorgenti
from .config import ConfigLanterna
from .impronta import identificativo_esteso, impronta, oggi_utc, sale_del_giorno
from .schema import Tabelle

logger = logging.getLogger(__name__)

_NOME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CHIAVE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,39}$")
_LINGUA = re.compile(r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$")

#: Eventi che contano come «pagina vista» e che possono aprire una sessione con una provenienza.
PAGINA = "page_view"
#: Il tempo attivo su una pagina, mandato all'uscita o al cambio di pagina.
COINVOLGIMENTO = "engagement"


@dataclass
class Evento:
    nome: str
    ts: datetime
    percorso: Optional[str] = None
    referrer: Optional[str] = None
    utm: Dict[str, str] = field(default_factory=dict)
    durata_ms: Optional[int] = None
    proprieta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Lotto:
    eventi: List[Evento]
    id_browser: Optional[str] = None
    lingua: Optional[str] = None


@dataclass(frozen=True)
class Contesto:
    ip: Optional[str]
    agente: str
    utente_id: Optional[int] = None
    adesso: Optional[datetime] = None


# ---- validazione --------------------------------------------------------------------------


def percorso_pulito(valore: Any) -> Optional[str]:
    if not isinstance(valore, str) or not valore.startswith("/"):
        return None
    valore = valore.split("?", 1)[0].split("#", 1)[0]
    return valore[:512] or "/"


def _proprieta(valore: Any, massimo: int) -> Dict[str, Any]:
    if not isinstance(valore, dict):
        return {}
    pulite: Dict[str, Any] = {}
    for k, v in list(valore.items())[:20]:
        if not isinstance(k, str) or not _CHIAVE.match(k):
            continue
        if isinstance(v, bool) or v is None or isinstance(v, int):
            pulite[k] = v
        elif isinstance(v, float):
            pulite[k] = round(v, 4)
        elif isinstance(v, str):
            pulite[k] = v[:200]
    if len(json.dumps(pulite, ensure_ascii=False)) > massimo:
        return {}
    return pulite


def _intero(valore: Any, minimo: int, massimo: int) -> Optional[int]:
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return None
    return int(min(max(valore, minimo), massimo))


def interpreta(corpo: bytes, config: ConfigLanterna, adesso: datetime) -> Optional[Lotto]:
    """Il corpo grezzo come `Lotto`, o None se non è accettabile."""
    if not corpo or len(corpo) > config.corpo_max:
        return None
    try:
        dati = json.loads(corpo)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(dati, dict) or not isinstance(dati.get("eventi"), list):
        return None
    eventi: List[Evento] = []
    for grezzo in dati["eventi"][: config.eventi_per_lotto]:
        if not isinstance(grezzo, dict):
            continue
        nome = grezzo.get("n")
        if not isinstance(nome, str) or not _NOME.match(nome):
            continue
        percorso = percorso_pulito(grezzo.get("p"))
        if percorso and config.escluso(percorso):
            continue
        ritardo = _intero(grezzo.get("dt"), 0, 600_000) or 0
        utm = grezzo.get("u") if isinstance(grezzo.get("u"), dict) else {}
        eventi.append(
            Evento(
                nome=nome,
                ts=adesso - timedelta(milliseconds=ritardo),
                percorso=percorso,
                referrer=grezzo.get("r") if isinstance(grezzo.get("r"), str) else None,
                utm={k: str(v)[:200] for k, v in utm.items() if isinstance(k, str) and k.startswith("utm_") and v},
                durata_ms=_intero(grezzo.get("d"), 0, 3_600_000),
                proprieta=_proprieta(grezzo.get("x"), config.proprieta_max),
            )
        )
    if not eventi:
        return None
    id_browser = dati.get("id")
    lingua = dati.get("lingua")
    return Lotto(
        eventi=sorted(eventi, key=lambda e: e.ts),
        id_browser=id_browser[:128] if isinstance(id_browser, str) and id_browser else None,
        lingua=lingua[:16] if isinstance(lingua, str) and _LINGUA.match(lingua) else None,
    )


# ---- limite di frequenza ----------------------------------------------------------------------

_frequenza: Dict[str, tuple] = {}


def _entro_il_limite(chiave: str, quanti: int, limite: int) -> bool:
    """Per processo, in memoria: con più repliche il limite reale è moltiplicato per le repliche.
    Basta a fermare un client impazzito, non un attacco distribuito (per quello c'è il proxy)."""
    minuto = int(time.time() // 60)
    if len(_frequenza) > 50_000:
        _frequenza.clear()
    precedente_minuto, contati = _frequenza.get(chiave, (minuto, 0))
    if precedente_minuto != minuto:
        contati = 0
    contati += quanti
    _frequenza[chiave] = (minuto, contati)
    return contati <= limite


def azzera_limiti() -> None:
    """Per i test."""
    _frequenza.clear()


# ---- scrittura -----------------------------------------------------------------------------


async def utente_escluso(sessione, tabelle: Tabelle, utente_id: int) -> bool:
    t = tabelle.utenti
    return bool((await sessione.execute(select(t.c.escluso).where(t.c.utente_id == utente_id))).scalar())


def _nuova_provenienza(evento: Evento, config: ConfigLanterna) -> Optional[sorgenti.Provenienza]:
    """La provenienza di una pagina vista, se dice qualcosa (non «diretto»)."""
    if evento.nome != PAGINA:
        return None
    p = sorgenti.classifica(evento.referrer, evento.utm, config.dominio)
    return None if p.canale == "diretto" else p


async def registra(sessione, tabelle: Tabelle, config: ConfigLanterna, lotto: Lotto, ctx: Contesto) -> Optional[uuid.UUID]:
    """Scrive il lotto. Restituisce l'id della sessione, o None se il lotto è stato scartato.

    Non fa commit: la transazione è di chi chiama.
    """
    if ua_.e_bot(ctx.agente):
        return None
    adesso = ctx.adesso or datetime.now(timezone.utc)
    sale = await sale_del_giorno(sessione, tabelle, oggi_utc(adesso))
    visitatore = impronta(sale, config.sito, ctx.ip, ctx.agente)
    if not _entro_il_limite(visitatore, len(lotto.eventi), config.limite_al_minuto):
        return None

    utente_id = ctx.utente_id
    if utente_id is not None and await utente_escluso(sessione, tabelle, utente_id):
        utente_id = None
    esteso = identificativo_esteso(config.segreto, config.sito, lotto.id_browser) if lotto.id_browser else None

    s = tabelle.sessioni
    aperta = (
        await sessione.execute(
            select(s)
            .where(and_(s.c.visitatore_giorno == visitatore, s.c.ultimo > adesso - timedelta(minutes=config.sessione_minuti)))
            .order_by(s.c.ultimo.desc())
            .limit(1)
            .with_for_update()
        )
    ).mappings().first()

    primo = lotto.eventi[0]
    provenienza = _nuova_provenienza(primo, config)
    # Una campagna o un referrer esterno diversi da quelli della sessione aperta ne aprono una nuova
    # (come GA4): chi torna da un'altra fonte è una visita diversa ai fini dell'attribuzione.
    if aperta is not None and provenienza is not None and (
        provenienza.canale,
        provenienza.utm_campagna,
        provenienza.referrer_dominio,
    ) != (aperta["canale"], aperta["utm_campagna"], aperta["referrer_dominio"]):
        aperta = None

    if aperta is None:
        if provenienza is None:
            provenienza = sorgenti.classifica(primo.referrer if primo.nome == PAGINA else None, primo.utm, config.dominio)
        luogo = geo.luogo(config.percorso_geo, ctx.ip)
        agente = ua_.analizza(ctx.agente)
        sessione_id = uuid.uuid4()
        await sessione.execute(
            insert(s).values(
                id=sessione_id,
                sito=config.sito,
                visitatore_giorno=visitatore,
                visitatore_esteso=esteso,
                utente_id=utente_id,
                inizio=primo.ts,
                ultimo=primo.ts,
                ingresso=next((e.percorso for e in lotto.eventi if e.nome == PAGINA and e.percorso), primo.percorso),
                referrer_dominio=provenienza.referrer_dominio,
                canale=provenienza.canale,
                utm_sorgente=provenienza.utm_sorgente,
                utm_mezzo=provenienza.utm_mezzo,
                utm_campagna=provenienza.utm_campagna,
                utm_contenuto=provenienza.utm_contenuto,
                utm_termine=provenienza.utm_termine,
                paese=luogo.paese,
                regione=luogo.regione,
                citta=luogo.citta,
                dispositivo=agente.dispositivo,
                browser=agente.browser,
                so=agente.so,
                lingua=lotto.lingua,
            )
        )
        pagine_prima, tempo_prima = 0, 0
    else:
        sessione_id = aperta["id"]
        pagine_prima, tempo_prima = aperta["pagine"], aperta["tempo_attivo_ms"]

    e = tabelle.eventi
    await sessione.execute(
        insert(e),
        [
            {
                "ts": ev.ts,
                "sessione_id": sessione_id,
                "utente_id": utente_id,
                "origine": "client",
                "nome": ev.nome,
                "percorso": ev.percorso,
                "lingua": lotto.lingua,
                "durata_ms": ev.durata_ms,
                "proprieta": ev.proprieta,
            }
            for ev in lotto.eventi
        ],
    )

    pagine = sum(1 for ev in lotto.eventi if ev.nome == PAGINA)
    tempo = sum(ev.durata_ms or 0 for ev in lotto.eventi if ev.nome == COINVOLGIMENTO)
    altri = sum(1 for ev in lotto.eventi if ev.nome not in (PAGINA, COINVOLGIMENTO))
    ultima_pagina = next((ev.percorso for ev in reversed(lotto.eventi) if ev.nome == PAGINA and ev.percorso), None)
    valori: Dict[str, Any] = {
        "ultimo": func.greatest(s.c.ultimo, lotto.eventi[-1].ts),
        "pagine": s.c.pagine + pagine,
        "eventi": s.c.eventi + len(lotto.eventi),
        "tempo_attivo_ms": s.c.tempo_attivo_ms + tempo,
        "coinvolta": s.c.coinvolta | (pagine_prima + pagine > 1) | (tempo_prima + tempo >= 10_000) | (altri > 0),
    }
    if ultima_pagina:
        valori["uscita"] = ultima_pagina
    if utente_id is not None:
        valori["utente_id"] = utente_id
    if esteso:
        valori["visitatore_esteso"] = esteso
    await sessione.execute(update(s).where(s.c.id == sessione_id).values(**valori))

    if utente_id is not None:
        await tocca_utente(sessione, tabelle, utente_id, adesso, esteso)
    return sessione_id


async def tocca_utente(sessione, tabelle: Tabelle, utente_id: int, adesso: datetime, esteso: Optional[str] = None) -> None:
    """Ultimo accesso e giorni attivi dell'utente; alla prima volta anche il primo contatto."""
    u = tabelle.utenti
    oggi = oggi_utc(adesso)
    await sessione.execute(
        insert(u)
        .values(utente_id=utente_id, ultimo_accesso=adesso, ultimo_giorno_attivo=oggi, giorni_attivi=1)
        .on_conflict_do_update(
            index_elements=[u.c.utente_id],
            set_={
                "ultimo_accesso": adesso,
                "giorni_attivi": u.c.giorni_attivi + case((u.c.ultimo_giorno_attivo == oggi, 0), else_=1),
                "ultimo_giorno_attivo": oggi,
                "updated_at": adesso,
            },
            where=u.c.escluso.is_(False),
        )
    )
    await completa_primo_contatto(sessione, tabelle, utente_id, esteso)


async def completa_primo_contatto(sessione, tabelle: Tabelle, utente_id: int, esteso: Optional[str] = None) -> None:
    """Se l'utente non ha ancora un primo contatto, lo prende dalla sua sessione più vecchia.

    Col livello esteso (`esteso`, solo col consenso) contano anche le sessioni anonime dello stesso
    browser precedenti all'iscrizione: il primo contatto è davvero il primo, e si sa quante visite
    ci sono volute prima di registrarsi. Senza, il primo contatto è la sessione dell'iscrizione.
    """
    u, s = tabelle.utenti, tabelle.sessioni
    riga = (
        await sessione.execute(
            select(u.c.primo_contatto_il, u.c.registrato_il, u.c.visite_prima_registrazione).where(u.c.utente_id == utente_id)
        )
    ).first()
    if riga is None:
        return
    gia, registrato_il, visite_prima = riga
    sue = s.c.utente_id == utente_id
    if esteso:
        sue = sue | (s.c.visitatore_esteso == esteso)
    if esteso and registrato_il is not None and visite_prima is None:
        quante = (
            await sessione.execute(select(func.count()).select_from(s).where(and_(s.c.visitatore_esteso == esteso, s.c.inizio < registrato_il)))
        ).scalar_one()
        await sessione.execute(update(u).where(u.c.utente_id == utente_id).values(visite_prima_registrazione=quante))
    if gia is not None:
        return
    prima = (await sessione.execute(select(s).where(sue).order_by(s.c.inizio).limit(1))).mappings().first()
    if prima is None:
        return
    await sessione.execute(
        update(u)
        .where(and_(u.c.utente_id == utente_id, u.c.primo_contatto_il.is_(None)))
        .values(
            primo_canale=prima["canale"],
            primo_referrer_dominio=prima["referrer_dominio"],
            prima_sorgente=prima["utm_sorgente"],
            primo_mezzo=prima["utm_mezzo"],
            prima_campagna=prima["utm_campagna"],
            prima_pagina=prima["ingresso"],
            primo_contatto_il=prima["inizio"],
        )
    )


async def dimentica(sessione, tabelle: Tabelle, config: ConfigLanterna, id_browser: str) -> int:
    """Revoca del consenso: l'identificativo esteso sparisce da tutte le sessioni."""
    esteso = identificativo_esteso(config.segreto, config.sito, id_browser)
    if not esteso:
        return 0
    s = tabelle.sessioni
    esito = await sessione.execute(update(s).where(s.c.visitatore_esteso == esteso).values(visitatore_esteso=None))
    return esito.rowcount or 0
