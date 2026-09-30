"""Obiettivi (conversioni) configurabili: «cosa conta come risultato» senza toccare il codice.

Un obiettivo è un evento (con eventuali proprietà da rispettare) oppure una pagina (uno o più prefissi
di percorso, separati da virgola, per le pagine che esistono in più lingue). Per un periodo si
contano i completamenti, le sessioni che l'hanno raggiunto e la quota sulle sessioni del periodo.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import and_, func, or_, select

from .schema import Tabelle

TIPI = ("evento", "pagina")


def condizione(tabelle: Tabelle, obiettivo: Dict[str, Any]):
    e = tabelle.eventi
    if obiettivo["tipo"] == "pagina":
        prefissi = [p.strip() for p in str(obiettivo["valore"]).split(",") if p.strip()]
        return and_(e.c.nome == "page_view", or_(*[
            or_(e.c.percorso == p, e.c.percorso.startswith(p.rstrip("/") + "/")) for p in prefissi
        ]))
    parti = [e.c.nome == obiettivo["valore"]]
    for chiave, valore in (obiettivo.get("proprieta") or {}).items():
        parti.append(e.c.proprieta[chiave].astext == str(valore))
    return and_(*parti)


async def conversioni(sessione, tabelle: Tabelle, obiettivi: List[Dict[str, Any]],
                      inizio: datetime, fine: datetime) -> List[Dict[str, Any]]:
    e, s = tabelle.eventi, tabelle.sessioni
    totale = (await sessione.execute(
        select(func.count()).select_from(s).where(s.c.inizio >= inizio, s.c.inizio < fine)
    )).scalar_one()
    uscita = []
    for o in obiettivi:
        completamenti, sessioni, utenti = (await sessione.execute(
            select(func.count(), func.count(func.distinct(e.c.sessione_id)), func.count(func.distinct(e.c.utente_id)))
            .where(e.c.ts >= inizio, e.c.ts < fine, condizione(tabelle, o))
        )).one()
        uscita.append({
            "id": o["id"], "nome": o["nome"], "tipo": o["tipo"], "valore": o["valore"],
            "completamenti": int(completamenti), "sessioni": int(sessioni), "utenti": int(utenti),
            "tasso": round(sessioni / totale, 4) if totale else None, "sessioni_totali": int(totale),
        })
    return uscita
