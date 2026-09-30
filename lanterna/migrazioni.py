"""Le migrazioni dello schema, da chiamare dentro le revisioni Alembic dell'applicazione.

lanterna non ha una propria catena Alembic: l'applicazione ne ha già una e due catene sullo stesso
database si pestano i piedi. La revisione dell'applicazione chiama `crea_v1(op)` in `upgrade` e
`elimina_v1(op)` in `downgrade`. Le funzioni sono congelate per versione (vedi `schema.py`).
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Column, MetaData, Table

from .schema import _tabelle_v1, _tabelle_v2_nuove, _tabelle_v3_nuove


def _v1(prefisso: str, fk_utenti: str) -> list[Table]:
    metadata = MetaData()
    # La tabella degli utenti serve solo perché le chiavi esterne si risolvano durante la CREATE:
    # esiste già nel database, e non si crea né si tocca.
    nome, colonna = fk_utenti.split(".")
    Table(nome, metadata, Column(colonna, BigInteger, primary_key=True))
    t = _tabelle_v1(metadata, prefisso, fk_utenti)
    # In ordine di dipendenza: le sessioni prima degli eventi.
    return [t.sali, t.sessioni, t.eventi, t.utenti, t.giornaliero, t.impostazioni]


def _v2_nuove(prefisso: str, fk_utenti: str) -> list[Table]:
    metadata = MetaData()
    nome, colonna = fk_utenti.split(".")
    Table(nome, metadata, Column(colonna, BigInteger, primary_key=True))
    t = _tabelle_v2_nuove(metadata, prefisso, fk_utenti)
    return [t["analisi"], t["destinatari"], t["invii"], t["token"], t["importati"]]


def crea_v2(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    """Da v1 a v2: le tabelle di analisi AI, rapporti, token e risultati importati."""
    connessione = op.get_bind()
    for tabella in _v2_nuove(prefisso, fk_utenti):
        tabella.create(connessione)


def elimina_v2(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    """Da v2 a v1."""
    connessione = op.get_bind()
    for tabella in reversed(_v2_nuove(prefisso, fk_utenti)):
        tabella.drop(connessione)


def _v3_nuove(prefisso: str, fk_utenti: str) -> list[Table]:
    metadata = MetaData()
    nome, colonna = fk_utenti.split(".")
    Table(nome, metadata, Column(colonna, BigInteger, primary_key=True))
    t = _tabelle_v3_nuove(metadata, prefisso, fk_utenti)
    return [t["annotazioni"], t["obiettivi"]]


def crea_v3(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    """Da v2 a v3: annotazioni e obiettivi."""
    connessione = op.get_bind()
    for tabella in _v3_nuove(prefisso, fk_utenti):
        tabella.create(connessione)


def elimina_v3(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    connessione = op.get_bind()
    for tabella in reversed(_v3_nuove(prefisso, fk_utenti)):
        tabella.drop(connessione)


def crea_v1(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    connessione = op.get_bind()
    for tabella in _v1(prefisso, fk_utenti):
        tabella.create(connessione)


def elimina_v1(op, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> None:
    connessione = op.get_bind()
    for tabella in reversed(_v1(prefisso, fk_utenti)):
        tabella.drop(connessione)
