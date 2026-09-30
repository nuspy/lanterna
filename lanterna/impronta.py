"""L'impronta giornaliera di un visitatore, senza cookie.

`sha256(sale del giorno ‖ sito ‖ ip ‖ user agent)`, troncata a 128 bit. Lo stesso browser dalla
stessa rete dà la stessa impronta per tutto il giorno (UTC), quindi visite e sessioni si contano;
il giorno dopo il sale è un altro e l'impronta non è più collegabile alla precedente. Il sale sta nel
database (condiviso da tutte le repliche) e si distrugge dopo due giorni: da allora nemmeno chi ha il
database può ricalcolare un'impronta partendo da un IP.

L'identificativo **esteso** è diverso: è l'HMAC di un id generato dal browser e salvato solo dopo
il consenso. Vive quanto il consenso e permette di riconoscere i ritorni nei giorni successivi.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from .schema import Tabelle

_cache: Dict[date, str] = {}


def oggi_utc(adesso: Optional[datetime] = None) -> date:
    return (adesso or datetime.now(timezone.utc)).astimezone(timezone.utc).date()


async def sale_del_giorno(sessione, tabelle: Tabelle, giorno: date) -> str:
    """Il sale di `giorno`, creato alla prima richiesta. Tutte le repliche vedono lo stesso."""
    if giorno in _cache:
        return _cache[giorno]
    t = tabelle.sali
    await sessione.execute(
        insert(t).values(giorno=giorno, sale=secrets.token_hex(32)).on_conflict_do_nothing(index_elements=["giorno"])
    )
    sale = (await sessione.execute(select(t.c.sale).where(t.c.giorno == giorno))).scalar_one()
    _cache.clear()  # un solo giorno in memoria: quello vecchio non serve più
    _cache[giorno] = sale
    return sale


def impronta(sale: str, sito: str, ip: Optional[str], agente: str) -> str:
    materiale = "\x1f".join((sale, sito, ip or "", agente or "")).encode("utf-8")
    return hashlib.sha256(materiale).hexdigest()[:32]


def identificativo_esteso(segreto: str, sito: str, id_browser: str) -> Optional[str]:
    """HMAC dell'id del browser. Senza segreto il livello esteso è spento (None)."""
    if not segreto or not id_browser:
        return None
    return hmac.new(segreto.encode("utf-8"), f"{sito}\x1f{id_browser}".encode("utf-8"), hashlib.sha256).hexdigest()


async def distruggi_sali_vecchi(sessione, tabelle: Tabelle, adesso: Optional[datetime] = None) -> int:
    """Cancella i sali più vecchi di ieri. Restituisce quanti ne ha tolti."""
    limite = oggi_utc(adesso) - timedelta(days=1)
    esito = await sessione.execute(delete(tabelle.sali).where(tabelle.sali.c.giorno < limite))
    _cache.clear()
    return esito.rowcount or 0


def dimentica_cache() -> None:
    """Per i test."""
    _cache.clear()
