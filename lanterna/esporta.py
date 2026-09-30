"""Export dei risultati: CSV (UTF-8 con BOM, separatore «;» per Excel italiano) e XLSX.

L'export è sempre di un `Risultato` già calcolato: esattamente ciò che la console mostra, con le
stesse etichette e gli stessi totali, e nient'altro. Un foglio per risultato; un file può contenerne
più d'uno (le «collezioni» e il rapporto settimanale).
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Sequence, Tuple

from .interroga import Risultato

FORMATO_EXCEL = {
    "euro": '#,##0.00 "€"',
    "percento": "0.0%",
    "decimale": "0.00",
    "secondi": "0.0",
    "intero": "#,##0",
}


def _intestazioni(r: Risultato) -> List[str]:
    return ["Periodo" if c["tipo"] == "periodo" else c["etichetta"] for c in r.colonne]


def _riga(r: Risultato, riga: Dict[str, Any]) -> List[Any]:
    return [riga.get(c["nome"]) for c in r.colonne]


def _totale(r: Risultato) -> List[Any]:
    uscita: List[Any] = []
    for i, c in enumerate(r.colonne):
        if c["tipo"] == "misura":
            uscita.append(r.totali.get(c["nome"]))
        else:
            uscita.append("Totale" if i == 0 else "")
    return uscita


def csv_da(r: Risultato) -> bytes:
    buffer = io.StringIO()
    scrittore = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    scrittore.writerow(_intestazioni(r))
    for riga in r.righe:
        scrittore.writerow(["" if v is None else v for v in _riga(r, riga)])
    scrittore.writerow(["" if v is None else v for v in _totale(r)])
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _nome_foglio(nome: str, usati: set) -> str:
    pulito = "".join(ch for ch in nome if ch not in "[]:*?/\\")[:31] or "Foglio"
    candidato, n = pulito, 2
    while candidato in usati:
        suffisso = f" ({n})"
        candidato = pulito[: 31 - len(suffisso)] + suffisso
        n += 1
    usati.add(candidato)
    return candidato


def xlsx_da(fogli: Sequence[Tuple[str, Risultato, str]]) -> bytes:
    """`fogli`: (nome del foglio, risultato, descrizione). Richiede l'extra `xlsx` (openpyxl)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    libro = Workbook()
    libro.remove(libro.active)
    usati: set = set()
    grassetto = Font(bold=True)
    for nome, r, descrizione in fogli:
        foglio = libro.create_sheet(_nome_foglio(nome, usati))
        foglio.append([nome])
        foglio["A1"].font = Font(bold=True, size=13)
        foglio.append([f"Dal {r.da.isoformat()} al {r.a.isoformat()}" + (f" — {descrizione}" if descrizione else "")])
        foglio.append([])
        foglio.append(_intestazioni(r))
        for cella in foglio[4]:
            cella.font = grassetto
        for riga in r.righe:
            foglio.append(_riga(r, riga))
        foglio.append(_totale(r))
        for cella in foglio[foglio.max_row]:
            cella.font = grassetto
        if r.soppresse:
            foglio.append([f"{r.soppresse} righe nascoste: meno di 5 persone (tutela della riservatezza)."])
        for i, c in enumerate(r.colonne, start=1):
            lettera = get_column_letter(i)
            foglio.column_dimensions[lettera].width = max(12, min(40, len(str(c["etichetta"])) + 4))
            if c["tipo"] == "misura":
                for (cella,) in foglio.iter_rows(min_row=5, max_row=5 + len(r.righe), min_col=i, max_col=i):
                    cella.number_format = FORMATO_EXCEL.get(c.get("formato", "intero"), "General")
        foglio.freeze_panes = "A5"
    if not libro.worksheets:
        libro.create_sheet("Vuoto")
    uscita = io.BytesIO()
    libro.save(uscita)
    return uscita.getvalue()
