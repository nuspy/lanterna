"""Il router di raccolta per FastAPI.

    router = crea_router_raccolta(config=..., tabelle=..., sessione=get_db, utente=utente_opzionale)
    app.include_router(router)

- `POST /e` riceve un lotto dal browser (JSON, anche `text/plain` per `sendBeacon`) e risponde
  **sempre 204**: un corpo malformato, un bot o un limite superato non si distinguono da un successo,
  così un client ostile non impara nulla.
- `POST /e/dimentica` (corpo `{"id": "<id del browser>"}`) revoca il livello esteso.

Il nome breve e neutro del percorso serve a non finire nelle liste dei blocchi degli adblock.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request, Response

from .config import ConfigLanterna
from .raccolta import Contesto, dimentica, interpreta, registra
from .rete import ip_client
from .schema import Tabelle

logger = logging.getLogger(__name__)


def crea_router_raccolta(
    *,
    config: Callable[[], ConfigLanterna],
    tabelle: Tabelle,
    sessione: Callable[..., Any],
    utente: Callable[..., Any],
    attivi: Callable[[], bool] = lambda: True,
    prefisso: str = "",
) -> APIRouter:
    """`sessione`: dipendenza FastAPI che fornisce una `AsyncSession`. `utente`: dipendenza che
    restituisce l'id intero dell'utente autenticato o None (non deve mai sollevare né creare utenti).
    """
    router = APIRouter(prefix=prefisso, tags=["analytics"])

    async def _corpo(request: Request, massimo: int) -> Optional[bytes]:
        dichiarata = request.headers.get("content-length")
        if dichiarata and dichiarata.isdigit() and int(dichiarata) > massimo:
            return None
        corpo = await request.body()
        return corpo if len(corpo) <= massimo else None

    @router.post("/e", status_code=204, include_in_schema=False)
    async def raccogli(request: Request, db=Depends(sessione), utente_id=Depends(utente)) -> Response:
        if not attivi():
            return Response(status_code=204)
        cfg = config()
        adesso = datetime.now(timezone.utc)
        corpo = await _corpo(request, cfg.corpo_max)
        lotto = interpreta(corpo, cfg, adesso) if corpo else None
        if lotto is not None:
            try:
                await registra(
                    db, tabelle, cfg, lotto,
                    Contesto(ip=ip_client(request), agente=request.headers.get("user-agent", ""), utente_id=utente_id, adesso=adesso),
                )
                await db.commit()
            except Exception:  # noqa: BLE001 — le statistiche non restituiscono mai un errore al browser
                logger.warning("lanterna: lotto non registrato", exc_info=True)
                await db.rollback()
        return Response(status_code=204)

    @router.post("/e/dimentica", status_code=204, include_in_schema=False)
    async def revoca(request: Request, db=Depends(sessione)) -> Response:
        cfg = config()
        corpo = await _corpo(request, 1024)
        try:
            id_browser = json.loads(corpo or b"{}").get("id")
        except (ValueError, AttributeError):
            id_browser = None
        if isinstance(id_browser, str) and id_browser:
            try:
                await dimentica(db, tabelle, cfg, id_browser[:128])
                await db.commit()
            except Exception:  # noqa: BLE001
                logger.warning("lanterna: revoca non registrata", exc_info=True)
                await db.rollback()
        return Response(status_code=204)

    return router
