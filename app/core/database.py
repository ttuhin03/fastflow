"""
Database Module.

Dieses Modul verwaltet die Datenbankverbindung und Session-Erstellung
für SQLModel. Unterstützt SQLite (Standard) und PostgreSQL.

Features:
- SQLite WAL-Mode für bessere Concurrency
- WAL-Checkpointing für SQLite
- Unterstützung für PostgreSQL
- Alembic-Integration für Migrationen (manuelle Ausführung)

Hinweis: Migrationen werden nicht automatisch ausgeführt.
Siehe docs/DATABASE_MIGRATIONS.md für Anleitung zur manuellen Ausführung.
"""

import logging
import time
from typing import Any, Callable, Generator, Optional, TypeVar

import sqlalchemy.exc
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, text

from app.core.config import config
from app.models import (
    Invitation,
    OrchestratorSettings,
    Pipeline,
    PipelineRun,
    ScheduledJob,
    Secret,
    Session as SessionModel,
    SystemSettings,
    User,
)

logger = logging.getLogger(__name__)

# SQLite Standard-URL wenn keine DATABASE_URL gesetzt
if config.DATABASE_URL is None:
    # SQLite mit WAL-Mode für bessere Concurrency
    database_url = f"sqlite:///{config.DATA_DIR}/fastflow.db"
else:
    database_url = config.DATABASE_URL

# Engine erstellen
# Hinweis: Bei Docker mit Volume-Mounts (v.a. Mac/Windows) können bei SQLite
# disk I/O-Fehler auftreten. busy_timeout und retry_on_sqlite_io fangen
# viele transiente Fälle ab. Produktion: DATABASE_URL=postgresql://... empfohlen.
if database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
else:
    engine = create_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=300,
    )


_T = TypeVar("_T")


def retry_on_sqlite_io(
    fn: Callable[[], _T],
    *,
    max_attempts: int = 3,
    delay_ms: int = 100,
    session: Optional[Session] = None,
) -> _T:
    """
    Führt fn() aus. Bei SQLite-OperationalError (disk I/O, locked) Rollback,
    kurze Pause und Wiederholung. Nur für SQLite; bei PostgreSQL wird fn() 1x aufgerufen.
    """
    if not database_url.startswith("sqlite"):
        return fn()
    for attempt in range(max_attempts):
        try:
            return fn()
        except sqlalchemy.exc.OperationalError as e:
            if attempt == max_attempts - 1:
                raise
            err = getattr(e, "orig", e)
            msg = str(err).lower()
            if "disk i/o error" in msg or "database is locked" in msg:
                if session is not None:
                    try:
                        session.rollback()
                    except Exception:
                        pass
                logger.debug(
                    "SQLite I/O/lock, Retry %s/%s: %s", attempt + 1, max_attempts, e
                )
                time.sleep(delay_ms / 1000.0)
            else:
                raise
    return fn()  # type: ignore[return-value]  # unreachable


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


def run_wal_checkpoint_job() -> None:
    """
    Job-Funktion für periodischen WAL-Checkpoint.
    Wird vom APScheduler aufgerufen (synchrone Funktion).
    Nur für SQLite relevant; bei PostgreSQL wird nichts ausgeführt.
    """
    if not database_url.startswith("sqlite"):
        return
    try:
        wal_checkpoint()
    except RuntimeError:
        pass  # Nicht SQLite
    except Exception as e:
        logger.warning(f"WAL-Checkpoint-Job fehlgeschlagen: {e}")


def schedule_wal_checkpoint_job() -> None:
    """
    Plant periodischen WAL-Checkpoint-Job im Scheduler.
    
    Nur für SQLite: Führt alle 10 Minuten einen WAL-Checkpoint durch,
    um zu verhindern, dass die WAL-Datei unbegrenzt wächst.
    Bei PostgreSQL wird kein Job angelegt.
    """
    if not database_url.startswith("sqlite"):
        logger.debug("WAL-Checkpoint-Job übersprungen (PostgreSQL)")
        return
    try:
        from app.services.scheduler import get_scheduler
        from apscheduler.triggers.interval import IntervalTrigger

        scheduler = get_scheduler()
        if scheduler is None or not scheduler.running:
            logger.warning("Scheduler nicht verfügbar, WAL-Checkpoint-Job nicht geplant")
            return

        scheduler.add_job(
            func="app.core.database:run_wal_checkpoint_job",
            trigger=IntervalTrigger(minutes=10),
            id="wal_checkpoint_job",
            name="SQLite WAL Checkpoint",
            replace_existing=True,
        )
        logger.info("WAL-Checkpoint-Job geplant: alle 10 Minuten")
    except Exception as e:
        logger.error(f"Fehler beim Planen des WAL-Checkpoint-Jobs: {e}", exc_info=True)


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


# Migrationen werden nicht automatisch ausgeführt
# Siehe docs/DATABASE_MIGRATIONS.md für Anleitung zur manuellen Ausführung


def init_db() -> None:
    """
    Initialisiert die Datenbank und erstellt alle Tabellen.
    
    Wird beim App-Start aufgerufen, um sicherzustellen, dass alle
    Datenbank-Tabellen existieren. Aktiviert WAL-Mode für SQLite.
    
    Hinweis: Migrationen werden nicht automatisch ausgeführt.
    Siehe docs/DATABASE_MIGRATIONS.md für Anleitung zur manuellen Ausführung.
    """
    # SQLite WAL-Mode aktivieren (für bessere Concurrency)
    if database_url.startswith("sqlite"):
        with Session(engine) as session:
            session.execute(text("PRAGMA journal_mode=WAL"))
            session.commit()
        logger.info("SQLite WAL-Mode aktiviert")
    
    # Erstelle Tabellen (für neue Datenbanken)
    SQLModel.metadata.create_all(engine)
    
    # Stelle sicher, dass is_parameter-Spalte existiert (für bestehende DBs)
    # Diese Funktion wird in Zukunft durch Migrationen ersetzt
    _ensure_secret_is_parameter_column()
    
    # Migrationen werden nicht automatisch ausgeführt
    # Siehe docs/DATABASE_MIGRATIONS.md für Anleitung zur manuellen Ausführung


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
