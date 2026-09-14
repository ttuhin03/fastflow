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
from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, create_engine, text

from app.core.config import config
from app.models import (
    Invitation,
    NotificationApiKey,
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

SQLITE_FALLBACK_ACTIVE: bool = False
"""
True, wenn keine DATABASE_URL gesetzt war und die App auf lokales SQLite
zurückgefallen ist. Wird vom Degraded-Banner in der UI ausgewertet, damit ein
solcher Start nicht unbemerkt bleibt (siehe app.core.readiness.get_public_status).
"""

# SQLite Standard-URL wenn keine DATABASE_URL gesetzt
if config.DATABASE_URL is None:
    # In Produktion ist der stille Fallback gefährlich: Fehlt DATABASE_URL (z. B.
    # weil ein Secret-Injector den Wert noch nicht geschrieben hat), käme die App
    # auf einer frisch gestempelten, leeren SQLite-DB hoch, meldete sich über
    # /ready als gesund und verarbeitete Runs gegen den falschen Datenbestand.
    # Lieber hart abbrechen und den Pod crashen lassen.
    if config.ENVIRONMENT == "production" and not config.TESTING:
        raise RuntimeError(
            "DATABASE_URL ist nicht gesetzt, ENVIRONMENT=production. "
            "Start abgebrochen, um einen stillen Fallback auf lokales SQLite zu "
            "verhindern. Bitte DATABASE_URL setzen (oder ENVIRONMENT umstellen, "
            "falls SQLite hier wirklich gewollt ist)."
        )
    # SQLite mit WAL-Mode für bessere Concurrency
    database_url = f"sqlite:///{config.DATA_DIR}/fastflow.db"
    SQLITE_FALLBACK_ACTIVE = True
    logger.warning(
        "DATABASE_URL nicht gesetzt – Fallback auf lokales SQLite (%s). "
        "Das ist nur für Entwicklung und Tests vorgesehen.",
        database_url,
    )
else:
    database_url = config.DATABASE_URL

BACKGROUND_CONNECTION_HEADROOM = 8
"""
Verbindungen, die über die API-Threads hinaus für Hintergrund-Arbeit reserviert
werden: Scheduler-Jobs, Cleanup, WAL-Checkpoint und die Executor-Tasks, die
Run-Status und Zell-Logs schreiben. Ohne diese Reserve können API-Requests unter
Last den Pool vollständig belegen und ein Run-Abschluss käme nicht mehr in die DB.
"""


def resolved_pool_size() -> int:
    """
    Ermittelt die Größe des Verbindungspools.

    Ist DB_POOL_SIZE gesetzt, gilt dieser Wert unverändert. Andernfalls wird er aus
    API_THREADPOOL_WORKERS plus BACKGROUND_CONNECTION_HEADROOM hergeleitet.

    Hintergrund: Synchrone Endpoints laufen in AnyIOs Threadpool, und jeder dieser
    Threads hält für die Dauer seines Requests eine Verbindung. Ist der Pool kleiner
    als der Threadpool, wartet ein Teil der Threads nur auf Verbindungen — die
    Parallelität wäre dann nicht durch die Datenbank begrenzt, sondern durch eine
    unpassend gewählte Zahl.

    Returns:
        int: Anzahl dauerhaft gehaltener Verbindungen (ohne DB_MAX_OVERFLOW).
    """
    if config.DB_POOL_SIZE > 0:
        return config.DB_POOL_SIZE
    return config.API_THREADPOOL_WORKERS + BACKGROUND_CONNECTION_HEADROOM


def _is_memory_sqlite(url: str) -> bool:
    """
    Prüft, ob die URL auf eine In-Memory-SQLite-Datenbank zeigt.

    Für solche Datenbanken wählt SQLAlchemy einen Pool ohne Überlauf
    (SingletonThreadPool bzw. StaticPool). Pool-Argumente wie max_overflow sind
    dort nicht zulässig und würden den Start mit einem TypeError abbrechen.

    Die Prüfung spiegelt bewusst die Regel des SQLite-Dialekts selbst
    (``_is_url_file_db``): kein Datenbankname, ``:memory:`` oder ``mode=memory``
    in der Query. Ein eigener Test auf Teilstrings würde die dritte Form
    übersehen — und genau dann bräche der Start mit dem TypeError ab, den diese
    Funktion verhindern soll.
    """
    if not url.startswith("sqlite"):
        return False
    try:
        parsed = make_url(url)
    except sqlalchemy.exc.ArgumentError:
        # Unlesbare URL: create_engine scheitert gleich selbst und mit der
        # besseren Meldung. Hier nicht raten, sondern wie eine Datei behandeln.
        return False
    if not parsed.database or parsed.database == ":memory:":
        return True
    return parsed.query.get("mode") == "memory"


# Pool-Argumente. Bewusst für beide Backends identisch: Auch SQLite bekommt hier
# einen QueuePool (Default für dateibasierte SQLite-DBs), dessen Standardgröße von
# 5 sonst deutlich unter der Zahl paralleler API-Threads läge.
_POOL_KWARGS: dict = {
    "pool_size": resolved_pool_size(),
    "max_overflow": config.DB_MAX_OVERFLOW,
    "pool_timeout": config.DB_POOL_TIMEOUT_SECONDS,
}

# Engine erstellen
# Hinweis: Bei Docker mit Volume-Mounts (v.a. Mac/Windows) können bei SQLite
# disk I/O-Fehler auftreten. busy_timeout und retry_on_sqlite_io fangen
# viele transiente Fälle ab. Produktion: DATABASE_URL=postgresql://... empfohlen.
if database_url.startswith("sqlite"):
    # check_same_thread=False ist Pflicht, weil Endpoints in wechselnden
    # Threadpool-Threads laufen und eine gepoolte Verbindung dabei den Thread
    # wechselt. Die Serialisierung übernimmt SQLite selbst (busy_timeout).
    connect_args = {"check_same_thread": False}
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=False,
        **({} if _is_memory_sqlite(database_url) else _POOL_KWARGS),
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute(f"PRAGMA busy_timeout={config.SQLITE_BUSY_TIMEOUT_MS}")
        cursor.close()
else:
    engine = create_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        **_POOL_KWARGS,
    )

logger.info(
    "Datenbank-Pool: pool_size=%s max_overflow=%s timeout=%ss (API-Threads: %s)",
    _POOL_KWARGS["pool_size"],
    _POOL_KWARGS["max_overflow"],
    _POOL_KWARGS["pool_timeout"],
    config.API_THREADPOOL_WORKERS,
)


def release_connection(session: Session) -> None:
    """
    Gibt die Verbindung einer Session vorzeitig an den Pool zurück.

    Gedacht für Endpoints, die nach ihrem letzten Datenbankzugriff noch lange
    laufen — allen voran die SSE-Streams für Logs und Metriken. Deren Session
    stammt aus der Dependency ``get_session``, und FastAPI schließt Dependencies
    mit ``yield`` erst, wenn die Response vollständig gesendet ist. Bei einem
    Stream ist das erst beim Verbindungsabbruch des Clients der Fall: Ohne diesen
    Aufruf belegt jeder offene Stream eine Poolverbindung über seine gesamte
    Laufzeit, und genügend gleichzeitige Streams legen die ganze App lahm.

    Die Session bleibt benutzbar — ein späterer Zugriff holt sich einfach eine neue
    Verbindung. Achtung: ``close()`` löst alle geladenen ORM-Objekte von der
    Session. Bereits geladene Attribute bleiben lesbar, noch nicht geladene oder
    durch ein Commit invalidierte nicht. Aufrufer lesen deshalb vorher aus, was sie
    danach noch brauchen.

    Args:
        session: Die freizugebende Session.
    """
    session.close()


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
