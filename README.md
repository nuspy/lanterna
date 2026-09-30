# lanterna

Analytics di prima parte per siti web, nel **proprio PostgreSQL**: niente servizi terzi, niente
cookie per la misura di base, eventi di business registrati lato server.

## Cosa fa (0.1)

- **Raccolta dal browser** (`lanterna-osservatore`, in `js/`): pagine viste, tempo attivo, profondità
  di scorrimento, click e viste dichiarati nel markup (`data-an`, `data-an-vista`), link esterni,
  eventi dell'applicazione. Invio a lotti con `fetch(keepalive)`.
- **Senza cookie**: il visitatore si conta con un'impronta giornaliera
  `sha256(sale ‖ sito ‖ ip ‖ user agent)`; il sale sta nel database e si distrugge dopo due giorni.
  L'IP non si conserva mai: serve solo in memoria per l'impronta e per paese/città.
- **Livello esteso** (solo col consenso): HMAC di un id casuale del browser, per riconoscere i
  ritorni e le visite prima dell'iscrizione. Revocabile (`POST /e/dimentica`).
- **Utenti**: le visite si legano all'account quando l'applicazione passa l'id dell'utente; primo
  contatto (canale, referrer, UTM, pagina di ingresso), ultimo accesso, giorni attivi; opposizione.
- **Canali**: referrer e UTM → diretto, ricerca, ricerca a pagamento, social, social a pagamento,
  assistenti AI, email, referral, affiliati, display, campagna.
- **Eventi di server** (`emetti_evento`): in un SAVEPOINT, non rompono mai la transazione di chi li
  emette.
- **Geolocalizzazione** con DB-IP City Lite (CC BY 4.0) in locale: `python -m lanterna.geo <file>`.

## Uso (FastAPI + SQLAlchemy async)

```python
from lanterna import ConfigLanterna, registra_tabelle
from lanterna.fastapi import crea_router_raccolta

TABELLE = registra_tabelle(Base.metadata, prefisso="an_", fk_utenti="users.id")
app.include_router(crea_router_raccolta(
    config=lambda: ConfigLanterna(sito="miosito", dominio="miosito.com", segreto=SEGRETO, percorso_geo="/opt/geo/citta.mmdb"),
    tabelle=TABELLE, sessione=get_db, utente=utente_id_opzionale,
))
```

Migrazione Alembic dell'applicazione:

```python
from lanterna.migrazioni import crea_v1, elimina_v1
def upgrade(): crea_v1(op)
def downgrade(): elimina_v1(op)
```

Browser:

```js
import { avvia } from "lanterna-osservatore";
const o = avvia({ endpoint: "/api/e", token: () => tokenCorrente, idBrowser: () => (consenso ? id : null) });
o.pagina(location.pathname);          // a ogni cambio di percorso
o.traccia("lettura_fase", { fase });  // eventi dell'applicazione
```

## Test

```
pip install -e ".[geo,xlsx,dev]"
pytest -q
```

## Prossimi passi

Motore di interrogazioni dichiarate (nessun SQL libero), riepilogo giornaliero e pulizia, export
CSV/XLSX, interpretazione dei dati con fatti numerati e validazione, rapporto email, Colab.
