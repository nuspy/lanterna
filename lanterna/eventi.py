"""Gli eventi di business emessi dall'applicazione (registrazione, acquisto, lettura completata...).

Lato server e non dal browser perché sono la verità: un pagamento confermato dal webhook esiste
anche se il browser ha chiuso la scheda, e un adblock non lo nasconde.

**Non rompono mai il business.** L'emissione gira in un SAVEPOINT: se fallisce (tabella assente,
vincolo, qualunque cosa) si annulla solo il savepoint, si scrive un avviso nel log e la transazione
di chi chiama prosegue come se nulla fosse. Un checkout non deve fallire perché le statistiche hanno
un problema.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert

from .raccolta import _proprieta, utente_escluso
from .schema import Tabelle

logger = logging.getLogger(__name__)

#: Entro quanti minuti dall'ultima attività un evento di server si lega alla sessione dell'utente.
FINESTRA_SESSIONE = timedelta(minutes=30)


async def emetti_evento(
    sessione,
    tabelle: Tabelle,
    nome: str,
    *,
    utente_id: Optional[int] = None,
    valore_centesimi: Optional[int] = None,
    valuta: Optional[str] = None,
    percorso: Optional[str] = None,
    proprieta: Optional[Dict[str, Any]] = None,
    adesso: Optional[datetime] = None,
) -> bool:
    """Registra un evento lato server. Vero se scritto, falso se scartato o fallito.

    Con `utente_id` l'evento si lega all'ultima sessione dell'utente attiva negli ultimi 30 minuti
    (così un acquisto eredita canale e campagna della visita che l'ha portato). Se l'utente si è
    opposto al legame, l'evento si registra comunque, ma anonimo e senza sessione.
    """
    adesso = adesso or datetime.now(timezone.utc)
    try:
        async with sessione.begin_nested():
            sessione_id = None
            if utente_id is not None:
                if await utente_escluso(sessione, tabelle, utente_id):
                    utente_id = None
                else:
                    s = tabelle.sessioni
                    sessione_id = (
                        await sessione.execute(
                            select(s.c.id)
                            .where(and_(s.c.utente_id == utente_id, s.c.ultimo > adesso - FINESTRA_SESSIONE))
                            .order_by(s.c.ultimo.desc())
                            .limit(1)
                        )
                    ).scalar()
            await sessione.execute(
                insert(tabelle.eventi).values(
                    ts=adesso,
                    sessione_id=sessione_id,
                    utente_id=utente_id,
                    origine="server",
                    nome=nome[:64],
                    percorso=percorso[:512] if percorso else None,
                    valore_centesimi=valore_centesimi,
                    valuta=valuta.upper()[:3] if valuta else None,
                    proprieta=_proprieta(proprieta or {}, 2_048),
                )
            )
            if sessione_id is not None:
                s = tabelle.sessioni
                await sessione.execute(
                    update(s).where(s.c.id == sessione_id).values(eventi=s.c.eventi + 1, coinvolta=True)
                )
        return True
    except Exception:  # noqa: BLE001 — per contratto nessun errore delle statistiche esce di qui
        logger.warning("lanterna: evento %r non registrato", nome, exc_info=True)
        return False


async def segna_registrazione(sessione, tabelle: Tabelle, utente_id: int, adesso: Optional[datetime] = None) -> bool:
    """La riga di attribuzione dell'utente appena iscritto (il primo contatto arriva con la prima
    visita identificata). Stesse garanzie di `emetti_evento`."""
    adesso = adesso or datetime.now(timezone.utc)
    u = tabelle.utenti
    try:
        async with sessione.begin_nested():
            await sessione.execute(
                insert(u)
                .values(utente_id=utente_id, registrato_il=adesso)
                .on_conflict_do_update(index_elements=[u.c.utente_id], set_={"registrato_il": adesso})
            )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("lanterna: registrazione dell'utente %s non segnata", utente_id, exc_info=True)
        return False


async def imposta_opposizione(sessione, tabelle: Tabelle, utente_id: int, escluso: bool) -> None:
    """L'utente si oppone (o torna ad acconsentire) al legame fra visite e account.

    Con l'opposizione le sessioni e gli eventi passati perdono il legame con l'account (restano
    anonimi nei conteggi) e il primo contatto si cancella. Questa invece può fallire: è una
    richiesta dell'utente, e deve sapere se non è andata a buon fine.
    """
    u, s, e = tabelle.utenti, tabelle.sessioni, tabelle.eventi
    valori: Dict[str, Any] = {"escluso": escluso}
    if escluso:
        valori.update(
            primo_canale=None, primo_referrer_dominio=None, prima_sorgente=None, primo_mezzo=None,
            prima_campagna=None, prima_pagina=None, primo_contatto_il=None, visite_prima_registrazione=None,
        )
    await sessione.execute(
        insert(u).values(utente_id=utente_id, **valori).on_conflict_do_update(index_elements=[u.c.utente_id], set_=valori)
    )
    if escluso:
        await sessione.execute(update(s).where(s.c.utente_id == utente_id).values(utente_id=None))
        await sessione.execute(update(e).where(e.c.utente_id == utente_id).values(utente_id=None))


async def opposizione(sessione, tabelle: Tabelle, utente_id: int) -> bool:
    return await utente_escluso(sessione, tabelle, utente_id)
