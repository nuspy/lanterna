"""Tempo reale: chi c'è adesso (sessioni attive negli ultimi minuti) e cosa sta guardando.

Solo conteggi per pagina, canale, paese e dispositivo: niente città, niente singole sessioni.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, literal_column, select

from .schema import Tabelle


async def adesso(sessione, tabelle: Tabelle, *, minuti: int = 5, adesso_: Optional[datetime] = None) -> Dict[str, Any]:
    s, e = tabelle.sessioni, tabelle.eventi
    ora = adesso_ or datetime.now(timezone.utc)
    attive = s.c.ultimo >= ora - timedelta(minutes=minuti)

    async def per(colonna, quante: int = 8):
        righe = (await sessione.execute(
            select(func.coalesce(colonna, "(n.d.)").label("v"), func.count().label("n"))
            .where(attive).group_by(literal_column("1")).order_by(literal_column("2").desc()).limit(quante)
        )).all()
        return [{"valore": str(v), "sessioni": int(n)} for v, n in righe]

    totale = (await sessione.execute(select(func.count()).select_from(s).where(attive))).scalar_one()
    minuto = func.date_trunc("minute", e.c.ts)
    serie = (await sessione.execute(
        select(minuto.label("m"), func.count().label("n"))
        .where(e.c.ts >= ora - timedelta(minutes=30), e.c.nome == "page_view")
        .group_by(literal_column("1")).order_by(literal_column("1"))
    )).all()
    return {
        "minuti": minuti,
        "sessioni_attive": int(totale),
        "pagine": await per(s.c.uscita),
        "canali": await per(s.c.canale),
        "paesi": await per(s.c.paese),
        "dispositivi": await per(s.c.dispositivo, 4),
        "pagine_per_minuto": [{"minuto": m.isoformat(), "pagine": int(n)} for m, n in serie],
    }
