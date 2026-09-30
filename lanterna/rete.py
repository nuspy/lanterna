"""L'indirizzo di chi chiama, anche dietro i proxy.

Dietro un reverse proxy il socket è quello del proxy. `X-Real-IP` lo scrive il proxy (sovrascrivendo
ciò che manda il client) ed è la fonte più fidata; in mancanza si prende l'**ultimo** indirizzo di
`X-Forwarded-For`, quello aggiunto dal proxy più vicino, non il primo, che può essere scritto da chi
chiama. Senza proxy le intestazioni sono falsificabili: vale solo in sviluppo.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


def ip_da_intestazioni(intestazioni: Mapping[str, str], host: Optional[str]) -> Optional[str]:
    reale = (intestazioni.get("x-real-ip") or "").strip()
    if reale:
        return reale
    inoltrato = intestazioni.get("x-forwarded-for") or ""
    if inoltrato.strip():
        return inoltrato.split(",")[-1].strip()
    return host or None


def ip_client(request: Any) -> Optional[str]:
    """Per una richiesta Starlette/FastAPI."""
    host = request.client.host if getattr(request, "client", None) else None
    return ip_da_intestazioni(request.headers, host)
