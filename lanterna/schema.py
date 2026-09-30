"""Le tabelle di lanterna, registrate nel `MetaData` dell'applicazione.

lanterna non ha una propria base dichiarativa: le tabelle sono SQLAlchemy Core e finiscono nello
stesso `MetaData` dei modelli dell'applicazione. Così `create_all` dei test, l'autogenerate di
Alembic e il confronto fra migrazioni e modelli le vedono senza fare nulla di speciale, e le chiavi
esterne verso la tabella degli utenti dell'applicazione si risolvono normalmente.

Ogni versione dello schema è una funzione **congelata** (`_tabelle_v1`, poi `_tabelle_v2`...):
`registra_tabelle` usa l'ultima, `migrazioni.crea_v1` usa la v1 per sempre. Una colonna nuova
non si aggiunge a `_tabelle_v1`: si scrive `_tabelle_v2` e una migrazione `v1 → v2`.

**Cosa non c'è mai**: l'indirizzo IP, lo user agent completo, l'email. L'IP serve solo in memoria,
per paese/città e per l'impronta giornaliera, e poi si scarta.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

ADESSO = text("now()")


@dataclass(frozen=True)
class Tabelle:
    sali: Table
    sessioni: Table
    eventi: Table
    utenti: Table
    giornaliero: Table
    impostazioni: Table


def _tabelle_v1(metadata: MetaData, prefisso: str, fk_utenti: str) -> Tabelle:
    p = prefisso

    def utente(nullable: bool = True, **opzioni) -> Column:
        # SET NULL sugli eventi e sulle sessioni: la cancellazione di un account toglie il legame,
        # i conteggi anonimi restano. an_utenti invece segue l'account (CASCADE).
        return Column(
            "utente_id",
            BigInteger,
            ForeignKey(fk_utenti, ondelete=opzioni.pop("ondelete", "SET NULL")),
            nullable=nullable,
            **opzioni,
        )

    sali = Table(
        f"{p}sali",
        metadata,
        Column("giorno", Date, primary_key=True),
        # 32 byte casuali in esadecimale. Si distruggono dopo due giorni: da quel momento
        # l'impronta di quel giorno non è più ricostruibile, nemmeno da chi ha il database.
        Column("sale", String(64), nullable=False),
        Column("created_at", DateTime(timezone=True), server_default=ADESSO, nullable=False),
    )

    sessioni = Table(
        f"{p}sessioni",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("sito", String(64), nullable=False),
        #: Impronta del giorno: sha256(sale del giorno ‖ sito ‖ ip ‖ user agent), troncata.
        Column("visitatore_giorno", String(32), nullable=False),
        #: HMAC dell'identificativo del browser, solo se il visitatore ha acconsentito.
        Column("visitatore_esteso", String(64), nullable=True, index=True),
        utente(index=True),
        Column("inizio", DateTime(timezone=True), nullable=False),
        Column("ultimo", DateTime(timezone=True), nullable=False),
        Column("pagine", Integer, nullable=False, server_default=text("0")),
        Column("eventi", Integer, nullable=False, server_default=text("0")),
        Column("tempo_attivo_ms", BigInteger, nullable=False, server_default=text("0")),
        #: Coinvolta: più di una pagina, o almeno 10 secondi attivi, o un evento di business.
        Column("coinvolta", Boolean, nullable=False, server_default=text("false")),
        Column("ingresso", String(512), nullable=True),
        Column("uscita", String(512), nullable=True),
        Column("referrer_dominio", String(255), nullable=True),
        Column("canale", String(32), nullable=False),
        Column("utm_sorgente", String(200), nullable=True),
        Column("utm_mezzo", String(200), nullable=True),
        Column("utm_campagna", String(200), nullable=True),
        Column("utm_contenuto", String(200), nullable=True),
        Column("utm_termine", String(200), nullable=True),
        Column("paese", String(2), nullable=True),
        Column("regione", String(100), nullable=True),
        Column("citta", String(100), nullable=True),
        Column("dispositivo", String(16), nullable=False),
        Column("browser", String(32), nullable=False),
        Column("so", String(32), nullable=False),
        Column("lingua", String(16), nullable=True),
        Index(f"ix_{p}sessioni_visitatore_ultimo", "visitatore_giorno", "ultimo"),
        Index(f"ix_{p}sessioni_inizio", "inizio"),
    )

    eventi = Table(
        f"{p}eventi",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("ts", DateTime(timezone=True), nullable=False),
        # Un evento lato server può arrivare senza sessione (webhook di pagamento, job).
        Column(
            "sessione_id",
            Uuid,
            ForeignKey(f"{p}sessioni.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        utente(index=True),
        #: `client` (dal browser) o `server` (dall'applicazione).
        Column("origine", String(8), nullable=False),
        Column("nome", String(64), nullable=False),
        Column("percorso", String(512), nullable=True),
        Column("lingua", String(16), nullable=True),
        Column("durata_ms", Integer, nullable=True),
        Column("valore_centesimi", BigInteger, nullable=True),
        Column("valuta", String(3), nullable=True),
        Column("proprieta", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
        # BRIN: gli eventi arrivano in ordine di tempo, l'indice è minuscolo e basta per i filtri
        # per intervallo, che sono quasi tutte le interrogazioni.
        Index(f"ix_{p}eventi_ts_brin", "ts", postgresql_using="brin"),
        Index(f"ix_{p}eventi_nome_ts", "nome", "ts"),
    )

    utenti = Table(
        f"{p}utenti",
        metadata,
        utente(nullable=False, primary_key=True, ondelete="CASCADE"),
        #: Il primo contatto conosciuto: la sessione più vecchia legata all'utente, o la sessione
        #: in cui si è registrato.
        Column("primo_canale", String(32), nullable=True),
        Column("primo_referrer_dominio", String(255), nullable=True),
        Column("prima_sorgente", String(200), nullable=True),
        Column("primo_mezzo", String(200), nullable=True),
        Column("prima_campagna", String(200), nullable=True),
        Column("prima_pagina", String(512), nullable=True),
        Column("primo_contatto_il", DateTime(timezone=True), nullable=True),
        Column("registrato_il", DateTime(timezone=True), nullable=True),
        #: Solo col livello esteso (consenso): altrimenti le visite anonime precedenti non sono
        #: collegabili e il campo resta vuoto.
        Column("visite_prima_registrazione", Integer, nullable=True),
        Column("ultimo_accesso", DateTime(timezone=True), nullable=True),
        Column("ultimo_giorno_attivo", Date, nullable=True),
        Column("giorni_attivi", Integer, nullable=False, server_default=text("0")),
        #: L'utente si è opposto: le sue visite non si legano più all'account.
        Column("escluso", Boolean, nullable=False, server_default=text("false")),
        Column("created_at", DateTime(timezone=True), server_default=ADESSO, nullable=False),
        Column("updated_at", DateTime(timezone=True), server_default=ADESSO, nullable=False),
    )

    # Il riepilogo anonimo: nessuna colonna identifica una persona. Le dimensioni vuote sono ''
    # e non NULL, perché entrano nella chiave primaria.
    vuoto = text("''")
    giornaliero = Table(
        f"{p}giornaliero",
        metadata,
        Column("giorno", Date, primary_key=True),
        Column("nome", String(64), primary_key=True),
        Column("percorso", String(512), primary_key=True, server_default=vuoto),
        Column("canale", String(32), primary_key=True, server_default=vuoto),
        Column("campagna", String(200), primary_key=True, server_default=vuoto),
        Column("paese", String(2), primary_key=True, server_default=vuoto),
        Column("dispositivo", String(16), primary_key=True, server_default=vuoto),
        Column("lingua", String(16), primary_key=True, server_default=vuoto),
        Column("registrato", Boolean, primary_key=True, server_default=text("false")),
        Column("eventi", Integer, nullable=False, server_default=text("0")),
        Column("sessioni", Integer, nullable=False, server_default=text("0")),
        Column("visitatori", Integer, nullable=False, server_default=text("0")),
        Column("valore_centesimi", BigInteger, nullable=False, server_default=text("0")),
    )

    impostazioni = Table(
        f"{p}impostazioni",
        metadata,
        Column("chiave", String(64), primary_key=True),
        Column("valore", JSONB, nullable=False),
        Column("updated_at", DateTime(timezone=True), server_default=ADESSO, nullable=False),
    )

    return Tabelle(sali, sessioni, eventi, utenti, giornaliero, impostazioni)


def registra_tabelle(metadata: MetaData, *, prefisso: str = "an_", fk_utenti: str = "users.id") -> Tabelle:
    """Aggiunge le tabelle (versione corrente) al `MetaData` dell'applicazione e le restituisce.

    `fk_utenti` è la colonna a cui puntano i riferimenti agli utenti (`tabella.colonna`, intera).
    """
    return _tabelle_v1(metadata, prefisso, fk_utenti)
