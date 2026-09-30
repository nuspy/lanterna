"""Avvisi automatici: quando una metrica di ieri esce dal suo normale.

Il «normale» è la storia recente della stessa metrica (per esempio gli ultimi 28 giorni): mediana e
scarto assoluto mediano (MAD), robusti a un giorno strano nel passato. Tre regole, dalla più grave:

- **zero**: la metrica è a zero ma di solito non lo è (mediana ≥ `minimo`): spesso un guasto;
- **picco/crollo**: z robusto oltre `soglia` (3,5 di default) in una delle due direzioni;
- per le metriche «cattive» (errori) conta solo la salita, e basta superare `soglia_cattiva` volte la
  mediana con almeno `minimo_cattivo` casi.

Con poca storia (meno di 7 giorni) o numeri troppo piccoli non si avvisa: meglio un avviso perso che
dieci falsi.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Avviso:
    metrica: str
    etichetta: str
    valore: float
    mediana: float
    tipo: str  # zero | picco | crollo | errori
    z: Optional[float] = None

    def testo(self) -> str:
        if self.tipo == "zero":
            return f"{self.etichetta}: 0 ieri, di solito {self.mediana:g}. Possibile guasto."
        if self.tipo == "errori":
            return f"{self.etichetta}: {self.valore:g} ieri, di solito {self.mediana:g}."
        verso = "molto sopra" if self.tipo == "picco" else "molto sotto"
        return f"{self.etichetta}: {self.valore:g} ieri, {verso} il normale ({self.mediana:g})."


def valuta(metrica: str, etichetta: str, storia: List[float], ieri: float, *, cattiva: bool = False,
           minimo: float = 5, soglia: float = 3.5, soglia_cattiva: float = 2.0, minimo_cattivo: float = 3) -> Optional[Avviso]:
    if len(storia) < 7:
        return None
    mediana = statistics.median(storia)
    if cattiva:
        if ieri >= minimo_cattivo and ieri > soglia_cattiva * max(mediana, 1):
            return Avviso(metrica, etichetta, ieri, mediana, "errori")
        return None
    if ieri == 0 and mediana >= minimo:
        return Avviso(metrica, etichetta, ieri, mediana, "zero")
    if mediana < minimo and ieri < minimo:
        return None
    mad = statistics.median([abs(v - mediana) for v in storia])
    scala = mad / 0.6745 if mad else max(1.0, 0.25 * mediana)
    z = (ieri - mediana) / scala
    if abs(z) > soglia:
        return Avviso(metrica, etichetta, ieri, mediana, "picco" if z > 0 else "crollo", round(z, 1))
    return None
