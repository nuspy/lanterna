"""Il lavoro notturno: riepilogo giornaliero anonimo e pulizia di ciò che è scaduto.

**Riepilogo** (`riepiloga`): per un giorno (nel fuso del sito), gli eventi raggruppati per nome,
percorso, canale, campagna, paese, dispositivo, lingua e «registrato sì/no», con conteggi di eventi,
sessioni e visitatori, e la somma dei valori. Idempotente: il giorno si cancella e si riscrive, quindi
rilanciarlo (anche su giorni vecchi) non duplica nulla. Il riepilogo non identifica nessuno e resta
per sempre: è ciò che rimane quando il dettaglio scade.

**Pulizia** (`pulisci`): sessioni ed eventi più vecchi della conservazione, a lotti (un DELETE
enorme bloccherebbe la tabella); i sali più vecchi di ieri.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import Boolean, and_, cast, delete, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import insert

from .config import ConfigLanterna
from .impronta import distruggi_sali_vecchi
from .interroga import limiti
from .schema import Tabelle


async def riepiloga(sessione, tabelle: Tabelle, giorno: date, fuso: str = "Europe/Rome") -> int:
    """Riscrive il riepilogo di `giorno`. Restituisce le righe scritte."""
    e, s, g = tabelle.eventi, tabelle.sessioni, tabelle.giornaliero
    inizio, fine = limiti(giorno, giorno, fuso)
    vuoto = literal("")
    campi = {
        "nome": e.c.nome,
        "percorso": func.coalesce(e.c.percorso, vuoto),
        "canale": func.coalesce(s.c.canale, vuoto),
        "campagna": func.coalesce(s.c.utm_campagna, vuoto),
        "paese": func.coalesce(s.c.paese, vuoto),
        "dispositivo": func.coalesce(s.c.dispositivo, vuoto),
        "lingua": func.coalesce(e.c.lingua, s.c.lingua, vuoto),
        "registrato": cast(e.c.utente_id.is_not(None), Boolean),
    }
    sorgente = (
        select(
            literal(giorno).label("giorno"),
            *[v.label(k) for k, v in campi.items()],
            func.count().label("eventi"),
            func.count(func.distinct(e.c.sessione_id)).label("sessioni"),
            func.count(func.distinct(s.c.visitatore_giorno)).label("visitatori"),
            func.coalesce(func.sum(e.c.valore_centesimi), 0).label("valore_centesimi"),
        )
        .select_from(e.outerjoin(s, s.c.id == e.c.sessione_id))
        .where(and_(e.c.ts >= inizio, e.c.ts < fine))
        # Per posizione (la 1 è il giorno, costante): gli alias coincidono con colonne delle tabelle.
        .group_by(*[literal_column(str(i)) for i in range(2, len(campi) + 2)])
    )
    await sessione.execute(delete(g).where(g.c.giorno == giorno))
    await sessione.execute(
        insert(g).from_select(
            ["giorno", *campi.keys(), "eventi", "sessioni", "visitatori", "valore_centesimi"], sorgente
        )
    )
    # Il rowcount di un INSERT … SELECT non è affidabile con tutti i driver (psycopg dà -1).
    return (await sessione.execute(select(func.count()).select_from(g).where(g.c.giorno == giorno))).scalar_one()


async def _a_lotti(sessione, tabella, colonna_id, condizione, lotto: int) -> int:
    totale = 0
    while True:
        ids = select(colonna_id).where(condizione).limit(lotto).scalar_subquery()
        esito = await sessione.execute(delete(tabella).where(colonna_id.in_(ids)))
        n = esito.rowcount or 0
        totale += n
        await sessione.commit()
        if n < lotto:
            return totale


async def pulisci(
    sessione, tabelle: Tabelle, config: ConfigLanterna, *, adesso: Optional[datetime] = None, lotto: int = 5_000
) -> Dict[str, int]:
    """Cancella il dettaglio scaduto. Fa commit a ogni lotto: va chiamata fuori da altre transazioni."""
    adesso = adesso or datetime.now(timezone.utc)
    limite = adesso - timedelta(days=round(config.ritenzione_mesi * 30.44))
    e, s = tabelle.eventi, tabelle.sessioni
    eventi = await _a_lotti(sessione, e, e.c.id, e.c.ts < limite, lotto)
    sessioni = await _a_lotti(sessione, s, s.c.id, s.c.ultimo < limite, lotto)
    sali = await distruggi_sali_vecchi(sessione, tabelle, adesso)
    await sessione.commit()
    return {"eventi": eventi, "sessioni": sessioni, "sali": sali}


async def notte(
    sessione, tabelle: Tabelle, config: ConfigLanterna, *, fuso: str = "Europe/Rome", giorni: int = 3,
    adesso: Optional[datetime] = None,
) -> Dict[str, int]:
    """Il giro notturno: riepiloga gli ultimi `giorni` giorni conclusi (un giro saltato si recupera
    da solo la notte dopo) e pulisce. Restituisce un piccolo resoconto."""
    from zoneinfo import ZoneInfo

    adesso = adesso or datetime.now(timezone.utc)
    oggi = adesso.astimezone(ZoneInfo(fuso)).date()
    resoconto: Dict[str, int] = {}
    for n in range(giorni, 0, -1):
        giorno = oggi - timedelta(days=n)
        resoconto[f"riepilogo_{giorno.isoformat()}"] = await riepiloga(sessione, tabelle, giorno, fuso)
        await sessione.commit()
    resoconto.update(await pulisci(sessione, tabelle, config, adesso=adesso))
    return resoconto
