"""Paese, regione e città dall'indirizzo IP, con un file .mmdb locale.

Nessuna chiamata a servizi esterni: l'IP non esce mai dal server. Il file (DB-IP «IP to City Lite»,
licenza CC BY 4.0, oppure MaxMind GeoLite2-City) si scarica a parte; se manca, la geolocalizzazione
è semplicemente assente. La città da IP è spesso quella del fornitore di connessione, non quella
del visitatore: va letta come indicazione, non come dato preciso.
"""
from __future__ import annotations

import gzip
import logging
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Luogo:
    paese: Optional[str] = None
    regione: Optional[str] = None
    citta: Optional[str] = None


NESSUNO = Luogo()


@lru_cache(maxsize=4)
def _lettore(percorso: str) -> Any:
    try:
        import maxminddb
    except ImportError:
        logger.warning("lanterna: maxminddb non installato, geolocalizzazione spenta")
        return None
    try:
        return maxminddb.open_database(percorso)
    except (OSError, ValueError) as errore:
        logger.warning("lanterna: file di geolocalizzazione %s non leggibile (%s)", percorso, errore)
        return None


def _nome(nodo: Any) -> Optional[str]:
    if not isinstance(nodo, dict):
        return None
    nomi = nodo.get("names") or {}
    valore = nomi.get("en") or next(iter(nomi.values()), None)
    return str(valore)[:100] if valore else None


URL_DBIP = "https://download.db-ip.com/free/dbip-city-lite-{mese}.mmdb.gz"


def scarica_dbip(destinazione: str, *, oggi: Optional[date] = None, timeout: float = 120) -> str:
    """Scarica DB-IP City Lite (CC BY 4.0) del mese corrente, o del precedente se non è ancora
    uscito, e lo decomprime in `destinazione`. Restituisce il mese usato. Solleva se nessuno dei due
    è disponibile: chi chiama decide se è fatale."""
    oggi = oggi or date.today()
    precedente = (oggi.replace(day=1) - timedelta(days=1))
    errori = []
    for giorno in (oggi, precedente):
        mese = giorno.strftime("%Y-%m")
        url = URL_DBIP.format(mese=mese)
        try:
            # Il server di DB-IP rifiuta (403) lo user agent predefinito di urllib.
            richiesta = urllib.request.Request(url, headers={"User-Agent": "lanterna-geo/0.1 (+https://db-ip.com)"})
            with urllib.request.urlopen(richiesta, timeout=timeout) as risposta:
                dati = gzip.decompress(risposta.read())
        except (OSError, EOFError) as errore:
            errori.append(f"{url}: {errore}")
            continue
        cartella = os.path.dirname(destinazione)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        with open(destinazione, "wb") as f:
            f.write(dati)
        return mese
    raise RuntimeError("DB-IP non scaricabile: " + "; ".join(errori))


def luogo(percorso: Optional[str], ip: Optional[str]) -> Luogo:
    if not percorso or not ip:
        return NESSUNO
    lettore = _lettore(percorso)
    if lettore is None:
        return NESSUNO
    try:
        dati = lettore.get(ip)
    except ValueError:  # indirizzo non valido
        return NESSUNO
    if not isinstance(dati, dict):
        return NESSUNO
    paese = (dati.get("country") or {}).get("iso_code")
    suddivisioni = dati.get("subdivisions") or []
    return Luogo(
        paese=str(paese)[:2].upper() if paese else None,
        regione=_nome(suddivisioni[0]) if suddivisioni else None,
        citta=_nome(dati.get("city")),
    )


if __name__ == "__main__":
    # python -m lanterna.geo <destinazione.mmdb>: usato nella build dell'immagine. Non fatale: senza
    # file l'applicazione funziona, solo senza paese e città.
    try:
        print("DB-IP City Lite", scarica_dbip(sys.argv[1]), "->", sys.argv[1])
    except RuntimeError as errore:
        print("ATTENZIONE:", errore, file=sys.stderr)
