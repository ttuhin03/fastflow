"""
Database Module.

Dieses Modul verwaltet die Datenbankverbindung und Session-Erstellung
für SQLModel. Unterstützt SQLite (Standard) und PostgreSQL.
"""

from typing import Generator
from sqlmodel import SQLModel, create_engine, Session, text
from app.config import config
import logging

logger = logging.getLogger(__name__)

# SQLite Standard-URL wenn keine DATABASE_URL gesetzt
if config.DATABASE_URL is None:
    # SQLite mit WAL-Mode für bessere Concurrency
    database_url = f"sqlite:///{config.DATA_DIR}/fastflow.db"
else:
    database_url = config.DATABASE_URL

# Engine erstellen
if database_url.startswith("sqlite"):
    # SQLite-spezifische Konfiguration
    connect_args = {"check_same_thread": False}
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=False  # Setze auf True für SQL-Debugging
    )
else:
    # PostgreSQL oder andere Datenbanken
    engine = create_engine(database_url, echo=False)


def init_db() -> None:
    """
    Initialisiert die Datenbank und erstellt alle Tabellen.
    
    Wird beim App-Start aufgerufen, um sicherzustellen, dass alle
    Datenbank-Tabellen existieren.
    """
    SQLModel.metadata.create_all(engine)
    
    # SQLite WAL-Mode aktivieren (für bessere Concurrency)
    if database_url.startswith("sqlite"):
        with Session(engine) as session:
            session.execute(text("PRAGMA journal_mode=WAL"))
            session.commit()
        logger.info("SQLite WAL-Mode aktiviert")


def get_session() -> Generator[Session, None, None]:
    """
    Dependency für FastAPI-Endpoints zur Session-Erstellung.
    
    Yields:
        Session: SQLModel Session für Datenbankzugriffe
        
    Example:
        @app.get("/pipelines")
        def get_pipelines(session: Session = Depends(get_session)):
            return session.query(Pipeline).all()
    """
    with Session(engine) as session:
        yield session
