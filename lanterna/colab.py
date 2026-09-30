"""Colab (o qualunque notebook): token di accesso, firma dei risultati rimandati, notebook pronto.

- Il **token** si crea in console, si vede una volta sola e si incolla nel notebook; nel database ne
  resta solo l'impronta sha256. Ha una scadenza, degli ambiti (`esporta`, `importa`) e si revoca.
- L'**export** per il notebook dà solo aggregati con la soglia k (decide l'applicazione cosa).
- L'**import** accetta risultati (titolo, colonne, righe) firmati con HMAC-SHA256 del corpo, usando
  il token come chiave: un token rubato in transito non basta ad alterare un risultato firmato da
  un altro, e un corpo modificato dopo la firma si rifiuta.
- Il **notebook** è generato qui, già con l'indirizzo dell'API e la collezione scelta; il token
  lo chiede con `getpass` e non finisce mai nel file.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from .schema import Tabelle

AMBITI = ("esporta", "importa")
MAX_RIGHE = 5000
MAX_COLONNE = 50


def impronta(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def firma(token: str, corpo: bytes) -> str:
    return hmac.new(token.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def firma_valida(token: str, corpo: bytes, fornita: str) -> bool:
    return hmac.compare_digest(firma(token, corpo), (fornita or "").strip().lower())


async def crea_token(sessione, tabelle: Tabelle, *, nome: str, giorni: int, ambiti: List[str],
                     autore_id: Optional[int] = None) -> Dict[str, Any]:
    ambiti = sorted({a for a in ambiti if a in AMBITI}) or ["esporta"]
    token = "lnt_" + secrets.token_urlsafe(32)
    riga = {
        "id": uuid.uuid4(), "nome": nome.strip()[:120] or "notebook", "impronta": impronta(token), "ambiti": ambiti,
        "scade_il": datetime.now(timezone.utc) + timedelta(days=max(1, min(giorni, 365))), "creato_da": autore_id,
    }
    await sessione.execute(insert(tabelle.token).values(**riga))
    return {"token": token, "id": str(riga["id"]), "nome": riga["nome"], "ambiti": ambiti, "scade_il": riga["scade_il"].isoformat()}


async def verifica_token(sessione, tabelle: Tabelle, token: Optional[str], ambito: str):
    """La riga del token se valido per l'ambito, altrimenti None. Aggiorna l'ultimo uso."""
    if not token:
        return None
    t = tabelle.token
    riga = (await sessione.execute(select(t).where(t.c.impronta == impronta(token)))).mappings().first()
    adesso = datetime.now(timezone.utc)
    if riga is None or riga["revocato_il"] is not None or riga["scade_il"] <= adesso or ambito not in (riga["ambiti"] or []):
        return None
    await sessione.execute(update(t).where(t.c.id == riga["id"]).values(ultimo_uso=adesso))
    return riga


async def revoca(sessione, tabelle: Tabelle, token_id: uuid.UUID) -> bool:
    t = tabelle.token
    esito = await sessione.execute(
        update(t).where(t.c.id == token_id, t.c.revocato_il.is_(None)).values(revocato_il=datetime.now(timezone.utc))
    )
    return bool(esito.rowcount)


def valida_import(dati: Any) -> Dict[str, Any]:
    """Il corpo di un import: {"titolo", "descrizione"?, "colonne": [str], "righe": [[scalari]]}."""
    if not isinstance(dati, dict):
        raise ValueError("il corpo deve essere un oggetto JSON")
    titolo = str(dati.get("titolo") or "").strip()[:200]
    colonne = dati.get("colonne")
    righe = dati.get("righe")
    if not titolo:
        raise ValueError("manca il titolo")
    if not isinstance(colonne, list) or not colonne or len(colonne) > MAX_COLONNE:
        raise ValueError(f"colonne: da 1 a {MAX_COLONNE}")
    if not isinstance(righe, list) or len(righe) > MAX_RIGHE:
        raise ValueError(f"righe: al massimo {MAX_RIGHE}")
    pulite = []
    for r in righe:
        if not isinstance(r, list) or len(r) != len(colonne):
            raise ValueError("ogni riga deve avere un valore per colonna")
        pulite.append([v if isinstance(v, (int, float, bool)) or v is None else str(v)[:500] for v in r])
    return {"titolo": titolo, "descrizione": str(dati.get("descrizione") or "")[:4000] or None,
            "colonne": [str(c)[:100] for c in colonne], "righe": pulite}


# ---- il notebook -------------------------------------------------------------------------------------


def _cella(tipo: str, testo: str) -> Dict[str, Any]:
    cella: Dict[str, Any] = {"cell_type": tipo, "metadata": {}, "source": testo.strip("\n").splitlines(keepends=True)}
    if tipo == "code":
        cella.update(execution_count=None, outputs=[])
    return cella


def notebook(*, api: str, collezione: str, titolo: str, giorni: int = 90) -> str:
    """Un notebook .ipynb pronto per Colab: scarica la collezione, esempi di analisi, reimport firmato."""
    celle = [
        _cella("markdown", f"""
# {titolo}

Dati aggregati dell'API ({api}), collezione **{collezione}**. Nessun dato personale: gruppi di meno
di 5 persone sono esclusi. Il token (creato in console → Analytics → Studi) si incolla quando richiesto
e non viene salvato nel notebook.
"""),
        _cella("code", f"""
import getpass, json, hmac, hashlib, urllib.request
import pandas as pd

API = {json.dumps(api)}
COLLEZIONE = {json.dumps(collezione)}
GIORNI = {int(giorni)}
TOKEN = getpass.getpass("Token di Colab: ")

def scarica(collezione=COLLEZIONE, giorni=GIORNI):
    richiesta = urllib.request.Request(f"{{API}}/analytics/export/{{collezione}}?giorni={{giorni}}",
                                       headers={{"Authorization": f"Bearer {{TOKEN}}"}})
    with urllib.request.urlopen(richiesta, timeout=120) as r:
        dati = json.load(r)
    return {{f["titolo"]: pd.DataFrame(f["righe"], columns=[c["etichetta"] for c in f["colonne"]]) for f in dati["fogli"]}}

tabelle = scarica()
for nome, df in tabelle.items():
    print(nome, df.shape)
"""),
        _cella("markdown", "## Uno sguardo a ogni tabella"),
        _cella("code", """
for nome, df in tabelle.items():
    print("\\n==", nome)
    display(df.head(10))
"""),
        _cella("markdown", """
## Esempio: andamento e media mobile

Prende la prima tabella con una colonna «Periodo» e ne traccia la prima misura con la media a 7 giorni.
"""),
        _cella("code", """
import matplotlib.pyplot as plt

serie = next((df for df in tabelle.values() if "Periodo" in df.columns), None)
if serie is not None and len(serie.columns) > 1:
    s = serie.set_index(pd.to_datetime(serie["Periodo"]))[serie.columns[1]].astype(float)
    ax = s.plot(figsize=(10, 4), alpha=0.4, label=serie.columns[1])
    s.rolling(7, min_periods=1).mean().plot(ax=ax, label="media a 7 giorni")
    ax.legend(); plt.show()
"""),
        _cella("markdown", """
## Rimandare un risultato alla console

Qualunque DataFrame (per esempio una segmentazione o una previsione) si può rimandare: comparirà in
console → Analytics → Studi, e potrà entrare nell'interpretazione AI. Il corpo è firmato col token.
"""),
        _cella("code", """
def rimanda(df, titolo, descrizione=""):
    corpo = json.dumps({"titolo": titolo, "descrizione": descrizione, "colonne": [str(c) for c in df.columns],
                        "righe": json.loads(df.head(5000).to_json(orient="values", date_format="iso"))}).encode()
    firma = hmac.new(TOKEN.encode(), corpo, hashlib.sha256).hexdigest()
    richiesta = urllib.request.Request(f"{API}/analytics/importa", data=corpo, method="POST",
                                       headers={"Authorization": f"Bearer {TOKEN}", "X-Firma": firma,
                                                "Content-Type": "application/json"})
    with urllib.request.urlopen(richiesta, timeout=60) as r:
        return json.load(r)

# Esempio (togliere il commento):
# rimanda(next(iter(tabelle.values())).describe().reset_index(), "Statistiche descrittive", "prima tabella")
"""),
    ]
    documento = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"colab": {"name": f"{titolo}.ipynb"}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
                     "language_info": {"name": "python"}},
        "cells": celle,
    }
    return json.dumps(documento, ensure_ascii=False, indent=1)
