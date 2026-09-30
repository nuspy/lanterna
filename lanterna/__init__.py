"""lanterna — analytics di prima parte, nel proprio PostgreSQL.

Raccoglie visite ed eventi senza cookie (impronta giornaliera con sale distrutto), lega le visite
agli account quando l'applicazione lo decide, registra gli eventi di business lato server, e offre
interrogazioni dichiarate, riepiloghi giornalieri, export e interpretazione dei dati.

Il modulo non legge variabili d'ambiente e non ha una propria base dichiarativa: l'applicazione
registra le tabelle nel proprio `MetaData` (`registra_tabelle`) e chiama le migrazioni dalla propria
catena Alembic (`lanterna.migrazioni`).
"""
from .config import ConfigLanterna
from .schema import Tabelle, registra_tabelle

__all__ = ["ConfigLanterna", "Tabelle", "registra_tabelle"]
__version__ = "0.1.0"
