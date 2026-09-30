"""Dall'analisi dei numeri alla loro interpretazione, senza lasciare che il modello inventi.

Il modello linguistico non riceve tabelle da leggere: riceve **fatti** già calcolati qui, in modo
deterministico, ciascuno con un identificativo (M1, M2, …): totali col periodo precedente e la
significatività della variazione, quote e contributi dei segmenti, andamenti e anomalie delle serie,
passi degli imbuti. Il suo lavoro è metterli in relazione, spiegarli e proporre cosa fare, citando gli
identificativi dei fatti su cui si appoggia.

Poi si **verifica**: ogni numero scritto nella risposta deve comparire (con una piccola tolleranza)
fra i valori dei fatti; ogni citazione deve esistere. Ciò che non passa resta, ma segnato come «non
verificato», e non finisce nei rapporti automatici.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .interroga import Risultato

ADDITIVI = {"intero", "euro"}
MAX_FATTI = 90


@dataclass
class Fatto:
    id: str
    sezione: str
    testo: str
    valori: List[float] = field(default_factory=list)

    def json(self) -> Dict[str, Any]:
        return {"id": self.id, "sezione": self.sezione, "testo": self.testo, "valori": self.valori}


class Fatti:
    """Il quaderno dei fatti: numerazione progressiva, tetto massimo."""

    def __init__(self) -> None:
        self.elenco: List[Fatto] = []

    def aggiungi(self, sezione: str, testo: str, *valori: Optional[float]) -> None:
        if len(self.elenco) >= MAX_FATTI:
            return
        numeri = [float(v) for v in valori if v is not None and not (isinstance(v, float) and math.isnan(v))]
        self.elenco.append(Fatto(f"M{len(self.elenco) + 1}", sezione, testo, numeri))

    def json(self) -> List[Dict[str, Any]]:
        return [f.json() for f in self.elenco]


# ---- formattazione ---------------------------------------------------------------------------


def scrivi(v: Optional[float], formato: str = "intero") -> str:
    if v is None:
        return "n.d."
    if formato == "percento":
        return f"{v * 100:.1f}%"
    if formato == "euro":
        return f"{v:.2f} €"
    if formato == "secondi":
        return f"{v:.1f} s"
    if formato == "decimale":
        return f"{v:.2f}"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _variazione(ora: Optional[float], prima: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
    if ora is None or prima is None:
        return None, None
    delta = ora - prima
    return delta, (delta / prima if prima else None)


def significativita(ora: float, prima: float) -> str:
    """Per conteggi: approssimazione di Poisson del confronto fra due periodi di pari durata."""
    if ora + prima < 30:
        return "pochi dati: la variazione può essere casuale"
    z = (ora - prima) / math.sqrt(ora + prima)
    if abs(z) >= 3:
        return "variazione nettamente oltre il caso"
    if abs(z) >= 2:
        return "variazione probabilmente reale"
    return "variazione compatibile col caso"


def anomalie(valori: List[float], soglia: float = 3.5) -> List[int]:
    """Indici dei punti anomali (z robusto con mediana e MAD)."""
    if len(valori) < 7:
        return []
    mediana = statistics.median(valori)
    mad = statistics.median([abs(v - mediana) for v in valori])
    if mad == 0:
        return [i for i, v in enumerate(valori) if v != mediana and abs(v - mediana) > max(3, 0.5 * abs(mediana))]
    return [i for i, v in enumerate(valori) if abs(0.6745 * (v - mediana) / mad) > soglia]


def pendenza(valori: List[float]) -> Optional[float]:
    """Variazione relativa per punto (retta dei minimi quadrati diviso la media)."""
    n = len(valori)
    if n < 4:
        return None
    media_x = (n - 1) / 2
    media_y = sum(valori) / n
    den = sum((i - media_x) ** 2 for i in range(n))
    if not den or not media_y:
        return None
    b = sum((i - media_x) * (v - media_y) for i, v in enumerate(valori)) / den
    return b / media_y


# ---- dai risultati ai fatti ----------------------------------------------------------------------


def da_risultato(fatti: Fatti, titolo: str, r: Risultato, *, righe_max: int = 6) -> None:
    misure = [c for c in r.colonne if c["tipo"] == "misura"]
    dimensioni = [c for c in r.colonne if c["tipo"] == "dimensione"]
    periodo = any(c["tipo"] == "periodo" for c in r.colonne)
    prima_tot = (r.confronto or {}).get("totali") or {}

    # Totali, col periodo precedente.
    for m in misure:
        ora = _num(r.totali.get(m["nome"]))
        prima = _num(prima_tot.get(m["nome"])) if r.confronto else None
        formato = m.get("formato", "intero")
        if ora is None:
            continue
        if prima is None:
            fatti.aggiungi(titolo, f"{m['etichetta']}: {scrivi(ora, formato)} nel periodo.", ora)
            continue
        delta, rel = _variazione(ora, prima)
        testo = f"{m['etichetta']}: {scrivi(ora, formato)} (periodo precedente {scrivi(prima, formato)}"
        if rel is not None:
            testo += f", {rel * 100:+.1f}%"
        testo += ")"
        if formato == "intero":
            testo += f" — {significativita(ora, prima)}"
        fatti.aggiungi(titolo, testo + ".", ora, prima, delta, rel * 100 if rel is not None else None)

    if not misure:
        return
    principale = misure[0]
    formato = principale.get("formato", "intero")
    nome = principale["nome"]

    # Serie nel tempo.
    if periodo and not dimensioni:
        valori = [_num(x.get(nome)) or 0.0 for x in r.righe]
        if len(valori) >= 2:
            massimo = max(range(len(valori)), key=lambda i: valori[i])
            minimo = min(range(len(valori)), key=lambda i: valori[i])
            giorno = lambda i: str(r.righe[i].get("periodo"))[:10]  # noqa: E731
            fatti.aggiungi(titolo, f"{principale['etichetta']} per periodo: massimo {scrivi(valori[massimo], formato)} il "
                           f"{giorno(massimo)}, minimo {scrivi(valori[minimo], formato)} il {giorno(minimo)}, media "
                           f"{scrivi(sum(valori) / len(valori), 'decimale')}.", valori[massimo], valori[minimo], sum(valori) / len(valori))
            p = pendenza(valori)
            if p is not None and abs(p) >= 0.01:
                fatti.aggiungi(titolo, f"Tendenza di {principale['etichetta'].lower()}: {'in crescita' if p > 0 else 'in calo'} di "
                               f"circa {abs(p) * 100:.1f}% per periodo sulla media.", abs(p) * 100)
            for i in anomalie(valori)[:3]:
                fatti.aggiungi(titolo, f"Valore anomalo di {principale['etichetta'].lower()} il {giorno(i)}: "
                               f"{scrivi(valori[i], formato)} contro una mediana di {scrivi(statistics.median(valori), formato)}.",
                               valori[i], statistics.median(valori))
        return

    if not dimensioni:
        return
    chiave = lambda riga: tuple(str(riga.get(d["nome"])) for d in dimensioni)  # noqa: E731
    precedenti = {chiave(x): x for x in ((r.confronto or {}).get("righe") or [])}
    totale = _num(r.totali.get(nome))
    totale_prima = _num(prima_tot.get(nome))
    delta_totale = (totale - totale_prima) if (totale is not None and totale_prima is not None) else None
    etichetta_dim = " × ".join(d["etichetta"] for d in dimensioni)
    for riga in r.righe[:righe_max]:
        valore = _num(riga.get(nome))
        if valore is None:
            continue
        nome_riga = " / ".join(chiave(riga))
        parti = [f"{etichetta_dim} «{nome_riga}»: {principale['etichetta'].lower()} {scrivi(valore, formato)}"]
        valori: List[Optional[float]] = [valore]
        if formato in ADDITIVI and totale:
            quota = valore / totale
            parti.append(f"quota {quota * 100:.1f}% del totale")
            valori.append(quota * 100)
        prima_riga = precedenti.get(chiave(riga))
        if prima_riga is not None:
            vp = _num(prima_riga.get(nome))
            delta, rel = _variazione(valore, vp)
            if delta is not None:
                parti.append(f"prima {scrivi(vp, formato)}" + (f" ({rel * 100:+.1f}%)" if rel is not None else ""))
                valori += [vp, delta, rel * 100 if rel is not None else None]
                if delta_totale and formato in ADDITIVI:
                    contributo = delta / delta_totale
                    parti.append(f"spiega il {contributo * 100:.0f}% della variazione totale")
                    valori.append(contributo * 100)
        elif r.confronto:
            parti.append("assente nel periodo precedente")
        for m in misure[1:3]:
            altro = _num(riga.get(m["nome"]))
            if altro is not None:
                parti.append(f"{m['etichetta'].lower()} {scrivi(altro, m.get('formato', 'intero'))}")
                valori.append(altro * 100 if m.get("formato") == "percento" else altro)
        fatti.aggiungi(titolo, "; ".join(parti) + ".", *valori)
    if len(r.righe) > righe_max and formato in ADDITIVI and totale:
        resto = sum(_num(x.get(nome)) or 0 for x in r.righe[righe_max:])
        fatti.aggiungi(titolo, f"Gli altri {len(r.righe) - righe_max} valori di {etichetta_dim.lower()} insieme: "
                       f"{scrivi(resto, formato)} ({resto / totale * 100:.1f}%).", resto, resto / totale * 100)
    if r.soppresse:
        fatti.aggiungi(titolo, f"{r.soppresse} gruppi con meno di 5 persone non sono mostrati per riservatezza.")


def da_imbuto(fatti: Fatti, titolo: str, esito: Dict[str, Any]) -> None:
    passi = esito.get("passi") or []
    if not passi:
        return
    for i, p in enumerate(passi):
        if i == 0:
            fatti.aggiungi(titolo, f"Passo 1 «{p['etichetta']}»: {p['n']}.", p["n"])
            continue
        fatti.aggiungi(titolo, f"Passo {i + 1} «{p['etichetta']}»: {p['n']} ({(p['dal_precedente'] or 0) * 100:.1f}% dal passo "
                       f"precedente, {(p['dal_primo'] or 0) * 100:.1f}% dal primo).",
                       p["n"], (p["dal_precedente"] or 0) * 100, (p["dal_primo"] or 0) * 100)
    cali = [(1 - (p["dal_precedente"] or 0), i) for i, p in enumerate(passi) if i and passi[i - 1]["n"]]
    if cali:
        calo, i = max(cali)
        fatti.aggiungi(titolo, f"La perdita più grande è fra «{passi[i - 1]['etichetta']}» e «{passi[i]['etichetta']}»: "
                       f"{calo * 100:.1f}%.", calo * 100)
    for s in (esito.get("segmenti") or [])[:6]:
        fondo = s["passi"][-1]
        fatti.aggiungi(titolo, f"Segmento «{s['valore']}»: {s['passi'][0]['n']} al primo passo, "
                       f"{(fondo['dal_primo'] or 0) * 100:.1f}% arriva in fondo.", s["passi"][0]["n"], (fondo["dal_primo"] or 0) * 100)


def da_coorti(fatti: Fatti, titolo: str, coorti: List[Dict[str, Any]], somma: bool) -> None:
    righe = [c for c in coorti if c["dimensione"] >= 5]
    for periodo in (1, 3, 6):
        quote = [c["valori"][periodo] / c["dimensione"] for c in righe if len(c["valori"]) > periodo and c["dimensione"]]
        if len(quote) >= 2:
            media = sum(quote) / len(quote)
            testo = (f"Spesa media per iscritto al mese +{periodo}: {media:.2f} €" if somma
                     else f"Quota media di iscritti ancora attivi al mese +{periodo}: {media * 100:.1f}%")
            fatti.aggiungi(titolo, f"{testo} (su {len(quote)} coorti).", media if somma else media * 100)


# ---- il prompt ------------------------------------------------------------------------------------

SCHEMA = {
    "sintesi": "3-5 frasi: cosa è successo e cosa conta di più",
    "osservazioni": [{"titolo": "...", "testo": "...", "importanza": "alta|media|bassa", "fatti": ["M1"]}],
    "collegamenti": [{"testo": "come due o più fatti si spiegano a vicenda", "fatti": ["M2", "M7"]}],
    "ipotesi": [{"testo": "...", "confidenza": "alta|media|bassa", "verifica": "come verificarla con i dati", "fatti": ["M3"]}],
    "azioni": [{"testo": "cosa fare", "impatto": "alto|medio|basso", "sforzo": "alto|medio|basso",
                "metrica": "quale numero guardare per capire se ha funzionato", "fatti": ["M4"]}],
    "dati_mancanti": ["cosa servirebbe sapere per decidere meglio"],
    "avvertenze": ["limiti dei dati da tenere presenti"],
}

ISTRUZIONI = """Sei un analista di business intelligence per un piccolo servizio online. Ricevi dei FATTI
numerati (M1, M2, …), già calcolati: sono l'unica fonte di numeri. Il tuo lavoro:

1. mettere in relazione i fatti fra loro — traffico, iscrizioni, uso, ricavi — e spiegare cosa
   probabilmente li lega (i «collegamenti» sono la parte più utile: non descrivere un numero isolato);
2. distinguere ciò che è certo da ciò che è un'ipotesi, e dire come verificarla;
3. proporre azioni concrete, ordinate per impatto atteso, ciascuna con la metrica per giudicarla;
4. dire cosa manca nei dati per decidere meglio.

Regole ferree:
- usa SOLO numeri presenti nei fatti, scritti come li trovi (o arrotondati); non calcolarne di nuovi
  a meno che siano una semplice differenza o somma di numeri citati;
- cita sempre gli identificativi dei fatti su cui si basa ogni voce (campo "fatti");
- una variazione indicata come «compatibile col caso» o con «pochi dati» non è una tendenza;
- niente frasi generiche valide per qualunque sito: ogni voce deve dipendere da questi dati;
- scrivi in italiano, frasi brevi.

Rispondi solo con un oggetto JSON con questa forma:
"""


def prompt(sezione: str, periodo: str, contesto: str, definizioni: str, fatti: Fatti,
           precedente: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """(sistema, utente) per il modello."""
    sistema = "# Compito: analisi_dati\n\n" + ISTRUZIONI + json.dumps(SCHEMA, ensure_ascii=False, indent=1)
    parti = [f"Sezione analizzata: {sezione}. Periodo: {periodo}."]
    if contesto.strip():
        parti.append("Contesto del business (dal responsabile):\n" + contesto.strip())
    if definizioni.strip():
        parti.append("Definizioni e limiti dei dati:\n" + definizioni.strip())
    if precedente:
        parti.append("Analisi precedente della stessa sezione (" + str(precedente.get("quando", "")) + "): "
                     + str(precedente.get("sintesi", ""))
                     + (f"\nAzione adottata dopo quell'analisi: {precedente['azione']}" if precedente.get("azione") else ""))
    parti.append("FATTI:\n" + "\n".join(f"[{f.id}] ({f.sezione}) {f.testo}" for f in fatti.elenco))
    return sistema, "\n\n".join(parti)


# ---- la verifica ------------------------------------------------------------------------------------

_NUMERO = re.compile(r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\w])|(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?![\w])")
_CITAZIONE = re.compile(r"\bM\d{1,3}\b")


_DATA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b")


def numeri_nel_testo(testo: str) -> List[float]:
    """I numeri di un testo, escluse le citazioni (M12) e le date (2026-09-20, 20/09): una data non è
    un dato da verificare."""
    uscita = []
    for m in _NUMERO.finditer(_DATA.sub(" ", _CITAZIONE.sub(" ", testo))):
        grezzo = m.group(0).lstrip("+")
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?", grezzo):
            grezzo = grezzo.replace(".", "").replace(",", ".")
        else:
            grezzo = grezzo.replace(",", ".")
        try:
            uscita.append(float(grezzo))
        except ValueError:
            continue
    return uscita


def _noto(n: float, noti: Iterable[float]) -> bool:
    for v in noti:
        for candidato in (v, abs(v), round(v), round(v, 1), round(v, 2)):
            if abs(n - candidato) <= max(0.051, abs(candidato) * 0.015):
                return True
    return False


def _banale(n: float) -> bool:
    """Numeri che non sono dati: ordinali, conteggi piccoli, anni, «+1 mese»."""
    return (float(n).is_integer() and 0 <= abs(n) <= 12) or (1990 <= n <= 2100 and float(n).is_integer())


def valida(risposta: Dict[str, Any], fatti: Fatti) -> Dict[str, Any]:
    """La risposta con, per ogni voce, `fatti` ripuliti, `verificato` e `numeri_non_trovati`."""
    ids = {f.id for f in fatti.elenco}
    noti = [v for f in fatti.elenco for v in f.valori]

    def controlla(voce: Dict[str, Any], campi: Tuple[str, ...], serve_citazione: bool) -> Dict[str, Any]:
        citati = [x for x in (voce.get("fatti") or []) if isinstance(x, str) and x in ids]
        testo = " ".join(str(voce.get(c, "")) for c in campi)
        mancanti = [n for n in numeri_nel_testo(testo) if not _banale(n) and not _noto(n, noti)]
        return {**voce, "fatti": citati, "numeri_non_trovati": mancanti,
                "verificato": not mancanti and (bool(citati) or not serve_citazione)}

    def lista(nome: str, campi: Tuple[str, ...], serve: bool) -> List[Dict[str, Any]]:
        voci = risposta.get(nome) or []
        return [controlla(v, campi, serve) for v in voci if isinstance(v, dict)][:12]

    sintesi = str(risposta.get("sintesi") or "")
    mancanti_sintesi = [n for n in numeri_nel_testo(sintesi) if not _banale(n) and not _noto(n, noti)]
    uscita = {
        "sintesi": sintesi,
        "sintesi_verificata": not mancanti_sintesi,
        "osservazioni": lista("osservazioni", ("titolo", "testo"), True),
        "collegamenti": lista("collegamenti", ("testo",), True),
        "ipotesi": lista("ipotesi", ("testo", "verifica"), False),
        "azioni": lista("azioni", ("testo", "metrica"), False),
        "dati_mancanti": [str(x) for x in (risposta.get("dati_mancanti") or [])][:10],
        "avvertenze": [str(x) for x in (risposta.get("avvertenze") or [])][:10],
    }
    voci = uscita["osservazioni"] + uscita["collegamenti"] + uscita["ipotesi"] + uscita["azioni"]
    uscita["verifica"] = {
        "voci": len(voci),
        "verificate": sum(1 for v in voci if v["verificato"]),
        "citazioni_inesistenti": sum(
            1 for nome in ("osservazioni", "collegamenti", "ipotesi", "azioni")
            for v in (risposta.get(nome) or []) if isinstance(v, dict)
            for x in (v.get("fatti") or []) if x not in ids
        ),
    }
    return uscita
