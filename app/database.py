"""
Database Module.

Dieses Modul verwaltet die Datenbankverbindung und Session-Erstellung
für SQLModel. Unterstützt SQLite (Standard) und PostgreSQL.

Features:
- SQLite WAL-Mode für bessere Concurrency
- WAL-Checkpointing für SQLite
- Unterstützung für PostgreSQL
- Alembic-Integration für Migrationen
"""

from typing import Generator
from sqlmodel import SQLModel, create_engine, Session, text
from app.config import config
from app.models import Pipeline, PipelineRun, ScheduledJob, Secret, User, Session as SessionModel  # Import Models für Metadaten-Registrierung
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


def wal_checkpoint() -> None:
    """
    Führt einen WAL-Checkpoint für SQLite-Datenbanken durch.
    
    WAL-Dateien können unbegrenzt wachsen ohne Checkpoint.
    Diese Funktion führt einen TRUNCATE-Checkpoint durch, der
    die WAL-Datei auf eine minimale Größe reduziert.
    
    Wird periodisch aufgerufen (z.B. alle 100 Transaktionen oder
    alle 10 Minuten) um zu verhindern, dass WAL-Dateien zu groß werden.
    
    Raises:
        RuntimeError: Wenn Datenbank keine SQLite-Datenbank ist
    """
    if not database_url.startswith("sqlite"):
        raise RuntimeError("WAL-Checkpointing ist nur für SQLite verfügbar")
    
    try:
        with Session(engine) as session:
            # TRUNCATE-Checkpoint: Reduziert WAL-Datei auf minimale Größe
            session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            session.commit()
        logger.debug("SQLite WAL-Checkpoint durchgeführt")
    except Exception as e:
        logger.warning(f"Fehler beim WAL-Checkpoint: {e}")


def _ensure_secret_is_parameter_column() -> None:
    """
    Stellt sicher, dass die is_parameter Spalte in der secrets Tabelle existiert.
    
    Fügt die Spalte hinzu, falls sie fehlt (für bestehende Datenbanken ohne Migration).
    """
    try:
        with Session(engine) as session:
            # Prüfe ob Spalte existiert (SQLite-spezifisch)
            if database_url.startswith("sqlite"):
                result = session.execute(text(
                    "SELECT COUNT(*) FROM pragma_table_info('secrets') WHERE name='is_parameter'"
                ))
                count = result.scalar()
                if count == 0:
                    # Spalte hinzufügen
                    session.execute(text(
                        "ALTER TABLE secrets ADD COLUMN is_parameter BOOLEAN NOT NULL DEFAULT 0"
                    ))
                    session.commit()
                    logger.info("Spalte 'is_parameter' zur secrets-Tabelle hinzugefügt")
            else:
                # PostgreSQL: Prüfe ob Spalte existiert
                result = session.execute(text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name='secrets' AND column_name='is_parameter'"
                ))
                count = result.scalar()
                if count == 0:
                    # Spalte hinzufügen
                    session.execute(text(
                        "ALTER TABLE secrets ADD COLUMN is_parameter BOOLEAN NOT NULL DEFAULT FALSE"
                    ))
                    session.commit()
                    logger.info("Spalte 'is_parameter' zur secrets-Tabelle hinzugefügt")
    except Exception as e:
        logger.warning(f"Fehler beim Hinzufügen der is_parameter-Spalte: {e}")
        # Nicht kritisch, Migration kann später ausgeführt werden


def init_db() -> None:
    """
    Initialisiert die Datenbank und erstellt alle Tabellen.
    
    Wird beim App-Start aufgerufen, um sicherzustellen, dass alle
    Datenbank-Tabellen existieren. Aktiviert WAL-Mode für SQLite.
    """
    SQLModel.metadata.create_all(engine)
    
    # SQLite WAL-Mode aktivieren (für bessere Concurrency)
    if database_url.startswith("sqlite"):
        with Session(engine) as session:
            session.execute(text("PRAGMA journal_mode=WAL"))
            session.commit()
        logger.info("SQLite WAL-Mode aktiviert")
    
    # Stelle sicher, dass is_parameter-Spalte existiert (für bestehende DBs)
    _ensure_secret_is_parameter_column()


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
