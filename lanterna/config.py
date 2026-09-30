"""La configurazione di un sito che usa lanterna.

Un solo oggetto immutabile, costruito dall'applicazione all'avvio e passato a chi ne ha bisogno
(il router di raccolta, il job notturno, il motore delle interrogazioni). Nessuna variabile
d'ambiente letta qui: da dove arrivano i valori lo decide l'applicazione.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class ConfigLanterna:
    #: Nome breve del sito: entra nell'impronta del visitatore, così lo stesso browser su due siti
    #: diversi che condividono il database non risulta la stessa persona.
    sito: str
    #: Il dominio del sito (senza schema), per riconoscere i referrer interni.
    dominio: str = ""
    #: Segreto dell'applicazione per l'identificativo esteso (HMAC dell'id del browser, solo con
    #: consenso). Senza segreto il livello esteso resta spento.
    segreto: str = ""
    #: Quanti mesi si tengono sessioni ed eventi grezzi; dopo resta solo il riepilogo giornaliero.
    ritenzione_mesi: int = 25
    #: Minuti di inattività oltre i quali la visita successiva apre una sessione nuova.
    sessione_minuti: int = 30
    #: File .mmdb con paese/regione/città (DB-IP City Lite o MaxMind GeoLite2-City). Assente → niente
    #: geolocalizzazione, tutto il resto funziona.
    percorso_geo: Optional[str] = None
    #: Prefissi di percorso che non si misurano mai (console di amministrazione, API interne).
    esclusi: Tuple[str, ...] = field(default_factory=lambda: ("/admin",))
    #: Eventi al minuto oltre i quali un'impronta viene ignorata per il resto del minuto.
    limite_al_minuto: int = 60
    #: Byte massimi di un corpo inviato dal browser e numero massimo di eventi in un lotto.
    corpo_max: int = 16_384
    eventi_per_lotto: int = 20
    #: Byte massimi delle proprietà di un evento (JSON serializzato).
    proprieta_max: int = 2_048

    def escluso(self, percorso: str) -> bool:
        return any(percorso == p or percorso.startswith(p.rstrip("/") + "/") for p in self.esclusi)
