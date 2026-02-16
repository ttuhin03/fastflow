"""
Scheduler Module.

Dieses Modul verwaltet geplante Pipeline-Ausführungen mit APScheduler:
- Cron- und Interval-Trigger
- Job-Persistenz in Datenbank (SQLAlchemyJobStore)
- Job-Enable/Disable-Funktionalität
- Automatisches Nachladen von Jobs aus Datenbank beim Start
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple, Union
from datetime import datetime, timezone
from uuid import UUID

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from sqlmodel import Session, select

from app.core.config import config
from app.models import ScheduledJob, TriggerType
from app.executor import run_pipeline
from app.services.pipeline_discovery import get_pipeline, discover_pipelines
from app.core.database import get_session

logger = logging.getLogger(__name__)

# Sentinel: run_config_id in update_job nicht aendern
_UPDATE_RUN_CONFIG_ID_OMIT = object()


def _parse_schedule_datetime(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    """Parse ISO date/datetime string to UTC datetime. Date-only => start or end of day UTC."""
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    try:
        if "T" in s or " " in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            # date only: start or end of day UTC
            dt = datetime.fromisoformat(s + "T00:00:00+00:00") if not end_of_day else datetime.fromisoformat(s + "T23:59:59.999999+00:00")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        logger.warning("Ungültiges Datumsformat für Schedule: %s", value)
        return None

# Globale Scheduler-Instanz
_scheduler: Optional[BackgroundScheduler] = None

# Zeitpunkt des Scheduler-Starts (API-Start). Geplante Runs werden in den ersten 2 Min übersprungen,
# damit die alte Instanz noch sauber runterfahren kann; manuelle Starts sind unverändert erlaubt.
_scheduler_started_at: Optional[datetime] = None
SCHEDULER_GRACE_SECONDS = 120  # 2 Minuten

# Haupt-Event-Loop der App (wird beim Start gesetzt). Scheduler-Jobs führen run_pipeline
# auf dieser Loop aus, damit der create_task(run_container_task) nicht beim Loop-Ende abbricht.
_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Setzt die Haupt-Event-Loop für Scheduler-Jobs (von Startup aufgerufen)."""
    global _main_loop
    _main_loop = loop
    logger.debug("Haupt-Event-Loop für Scheduler gesetzt")


def get_database_url() -> str:
    """
    Gibt die Datenbank-URL für SQLAlchemyJobStore zurück.
    
    Konvertiert SQLite-URLs in das Format, das APScheduler erwartet.
    PostgreSQL-URLs werden direkt verwendet.
    
    Returns:
        str: Datenbank-URL für APScheduler JobStore
    """
    if config.DATABASE_URL is None:
        # SQLite Standard-URL
        return f"sqlite:///{config.DATA_DIR}/fastflow.db"
    else:
        # PostgreSQL oder andere Datenbanken
        return config.DATABASE_URL


def init_scheduler() -> BackgroundScheduler:
    """
    Initialisiert den APScheduler mit SQLAlchemyJobStore.
    
    Der Scheduler verwendet die gleiche Datenbank wie SQLModel,
    sodass Jobs über Orchestrator-Neustarts hinweg erhalten bleiben.
    Jobs werden automatisch aus der Datenbank geladen.
    
    Returns:
        BackgroundScheduler: Initialisierter Scheduler
    
    Raises:
        RuntimeError: Wenn Scheduler-Initialisierung fehlschlägt
    """
    global _scheduler
    
    if _scheduler is not None:
        logger.warning("Scheduler bereits initialisiert")
        return _scheduler
    
    try:
        # Job-Store konfigurieren
        database_url = get_database_url()
        jobstores = {
            'default': SQLAlchemyJobStore(url=database_url)
        }
        
        # Scheduler initialisieren
        _scheduler = BackgroundScheduler(jobstores=jobstores)
        
        # Event-Listener für Job-Ausführung
        _scheduler.add_listener(_job_executed_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        logger.info(f"Scheduler initialisiert mit JobStore: {database_url}")
        return _scheduler
        
    except Exception as e:
        error_msg = f"Fehler bei Scheduler-Initialisierung: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def start_scheduler() -> None:
    """
    Startet den Scheduler.
    
    Wird beim App-Start aufgerufen. Jobs werden automatisch aus
    der Datenbank geladen (via SQLAlchemyJobStore).
    
    Raises:
        RuntimeError: Wenn Scheduler nicht initialisiert ist oder Start fehlschlägt
    """
    global _scheduler
    
    if _scheduler is None:
        init_scheduler()
    
    if _scheduler.running:
        logger.warning("Scheduler läuft bereits")
        return
    
    global _scheduler_started_at
    try:
        _scheduler.start()
        _scheduler_started_at = datetime.now(timezone.utc)
        logger.info("Scheduler gestartet (geplante Runs in den ersten %s Sekunden übersprungen)", SCHEDULER_GRACE_SECONDS)
        
        # Jobs aus Datenbank laden und synchronisieren
        _sync_jobs_from_database()
        
    except Exception as e:
        error_msg = f"Fehler beim Scheduler-Start: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def stop_scheduler() -> None:
    """
    Stoppt den Scheduler.
    
    Wird beim App-Shutdown aufgerufen. Jobs bleiben in der Datenbank
    erhalten und werden beim nächsten Start automatisch geladen.
    """
    global _scheduler
    
    if _scheduler is None:
        return
    
    if not _scheduler.running:
        return
    
    try:
        _scheduler.shutdown(wait=True)
        logger.info("Scheduler gestoppt")
    except Exception as e:
        logger.error(f"Fehler beim Scheduler-Stop: {e}")


def _sync_jobs_from_database() -> None:
    """
    Synchronisiert Jobs aus der Datenbank mit dem Scheduler.
    
    Lädt alle ScheduledJob-Einträge aus der Datenbank und stellt sicher,
    dass sie im Scheduler registriert sind. Jobs, die in der DB deaktiviert
    sind, werden aus dem Scheduler entfernt.
    
    Hinweis: SQLAlchemyJobStore lädt Jobs automatisch, aber wir müssen
    sicherstellen, dass die Job-IDs mit unseren ScheduledJob-IDs übereinstimmen.
    """
    if _scheduler is None or not _scheduler.running:
        return
    
    try:
        session_gen = get_session()
        session = next(session_gen)
        
        try:
            # Alle Jobs aus Datenbank laden
            statement = select(ScheduledJob)
            db_jobs = session.exec(statement).all()
            
            # Aktuelle Jobs im Scheduler
            scheduler_job_ids = {job.id for job in _scheduler.get_jobs()}
            
            for db_job in db_jobs:
                job_id = str(db_job.id)
                
                if db_job.enabled:
                    # Job sollte im Scheduler sein
                    if job_id not in scheduler_job_ids:
                        # Job fehlt im Scheduler, neu hinzufügen
                        _add_job_to_scheduler(db_job)
                else:
                    # Job ist deaktiviert, aus Scheduler entfernen
                    if job_id in scheduler_job_ids:
                        try:
                            _scheduler.remove_job(job_id)
                            logger.info(f"Deaktivierten Job aus Scheduler entfernt: {job_id}")
                        except Exception as e:
                            logger.warning(f"Fehler beim Entfernen von Job {job_id}: {e}")
            
            logger.info(f"Job-Synchronisation abgeschlossen: {len(db_jobs)} Jobs geprüft")
            
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Fehler bei Job-Synchronisation: {e}")


def _add_job_to_scheduler(job: ScheduledJob) -> None:
    """
    Fügt einen Job zum Scheduler hinzu.
    
    Args:
        job: ScheduledJob aus Datenbank
    """
    if _scheduler is None or not _scheduler.running:
        return
    
    try:
        # Trigger erstellen (mit optionalem Zeitraum)
        trigger = _create_trigger(
            job.trigger_type,
            job.trigger_value,
            start_date=job.start_date,
            end_date=job.end_date
        )
        
        if trigger is None:
            logger.error(f"Ungültiger Trigger für Job {job.id}: {job.trigger_type} = {job.trigger_value}")
            return
        
        # Textuelle Referenz (modul:funktion), damit der Job mit SQLAlchemyJobStore serialisiert werden kann
        if getattr(job, "source", "api") == "daemon_restart":
            func_ref = "app.services.scheduler:run_daemon_restart"
            job_args: list = [job.pipeline_name]
        else:
            func_ref = "app.services.scheduler:run_scheduled_pipeline"
            job_args = [job.pipeline_name, getattr(job, "run_config_id", None)]

        _scheduler.add_job(
            func_ref,
            trigger=trigger,
            id=str(job.id),
            replace_existing=True,
            max_instances=1,  # Verhindert gleichzeitige Ausführungen desselben Jobs
            args=job_args,
        )
        
        logger.info(f"Job zum Scheduler hinzugefügt: {job.id} (Pipeline: {job.pipeline_name})")
        
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen von Job {job.id} zum Scheduler: {e}")


def _create_trigger(
    trigger_type: TriggerType,
    trigger_value: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    """
    Erstellt einen APScheduler-Trigger aus TriggerType und TriggerValue.
    
    Args:
        trigger_type: CRON oder INTERVAL
        trigger_value: Cron-Expression (z.B. "0 0 * * *") oder Interval-String (z.B. "3600" für Sekunden)
        start_date: Optionaler Start des Zeitraums (UTC)
        end_date: Optionales Ende des Zeitraums (UTC)
    
    Returns:
        Trigger-Objekt (CronTrigger oder IntervalTrigger) oder None bei Fehler
    """
    try:
        kwargs = {}
        if start_date is not None:
            kwargs["start_date"] = start_date
        if end_date is not None:
            kwargs["end_date"] = end_date
        # Immer UTC verwenden, damit Cron/Interval unabhängig von Server-Zeitzone laufen
        kwargs["timezone"] = timezone.utc

        if trigger_type == TriggerType.CRON:
            # Cron-Expression parsen (Format: "minute hour day month day_of_week")
            # Beispiel: "0 0 * * *" = täglich um Mitternacht UTC, "0 * * * *" = stündlich
            parts = trigger_value.strip().split()
            if len(parts) != 5:
                logger.error(f"Ungültige Cron-Expression: {trigger_value} (erwartet 5 Teile)")
                return None
            
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                **kwargs
            )
        
        elif trigger_type == TriggerType.INTERVAL:
            # Interval-String parsen (Sekunden als Integer)
            try:
                seconds = int(trigger_value)
                if seconds <= 0:
                    logger.error(f"Ungültiges Interval: {trigger_value} (muss > 0)")
                    return None
                
                return IntervalTrigger(seconds=seconds, **kwargs)
            except ValueError:
                logger.error(f"Ungültiges Interval-Format: {trigger_value} (erwartet Integer)")
                return None

        elif trigger_type == TriggerType.DATE:
            # ISO-Datetime-String parsen für einmalige Ausführung
            try:
                run_date = datetime.fromisoformat(trigger_value.strip().replace("Z", "+00:00"))
                if run_date.tzinfo is None:
                    run_date = run_date.replace(tzinfo=timezone.utc)
                else:
                    run_date = run_date.astimezone(timezone.utc)
                return DateTrigger(run_date=run_date)
            except (ValueError, TypeError) as e:
                logger.error(f"Ungültiges Datum für DATE-Trigger: {trigger_value} – {e}")
                return None
        
        else:
            logger.error(f"Unbekannter Trigger-Typ: {trigger_type}")
            return None
            
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Triggers: {e}")
        return None


def run_scheduled_pipeline(pipeline_name: str, run_config_id: Optional[str] = None) -> None:
    """
    Wird vom APScheduler aufgerufen (per textueller Referenz).
    Führt die angegebene Pipeline aus. Muss Modul-Level sein, damit der Job
    mit SQLAlchemyJobStore serialisiert werden kann (keine Closures).

    In den ersten SCHEDULER_GRACE_SECONDS nach API-Start werden geplante Runs
    übersprungen (alte Instanz kann noch herunterfahren). Manuelle Starts
    laufen weiterhin sofort (API ruft run_pipeline direkt auf).

    run_pipeline wird auf der Haupt-Event-Loop der App ausgeführt (run_coroutine_threadsafe),
    damit der von run_pipeline gestartete Hintergrund-Task (K8s-Job starten) nicht abbricht,
    wenn die Loop endet (asyncio.run() würde die Loop beenden und Tasks abbrechen).
    """
    if _scheduler_started_at is not None:
        elapsed = (datetime.now(timezone.utc) - _scheduler_started_at).total_seconds()
        if elapsed < SCHEDULER_GRACE_SECONDS:
            logger.info(
                "Geplanten Run übersprungen (Grace-Period nach Start): %s (noch %.0fs von %ss)",
                pipeline_name,
                SCHEDULER_GRACE_SECONDS - elapsed,
                SCHEDULER_GRACE_SECONDS,
            )
            return
    pipeline = get_pipeline(pipeline_name)
    if pipeline is None:
        logger.error("Pipeline nicht gefunden für Job: %s", pipeline_name)
        return
    if not pipeline.is_enabled():
        logger.warning("Pipeline ist deaktiviert für Job: %s", pipeline_name)
        return
    try:
        if _main_loop is not None and _main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                run_pipeline(pipeline_name, triggered_by="scheduler", run_config_id=run_config_id),
                _main_loop,
            )
            future.result(timeout=60)  # Warten bis Run erstellt und an Executor übergeben wurde
        else:
            asyncio.run(run_pipeline(pipeline_name, triggered_by="scheduler", run_config_id=run_config_id))
        logger.info(
            "Geplante Pipeline ausgeführt: %s%s",
            pipeline_name,
            f" (run_config_id={run_config_id})" if run_config_id else "",
        )
    except Exception as e:
        logger.error("Fehler bei geplanter Pipeline-Ausführung %s: %s", pipeline_name, e)
        try:
            from app.services.notifications import send_scheduler_error_notification
            if _main_loop is not None and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    send_scheduler_error_notification(pipeline_name, str(e)), _main_loop
                ).result(timeout=10)
            else:
                asyncio.run(send_scheduler_error_notification(pipeline_name, str(e)))
        except Exception as notif_error:
            logger.error("Fehler beim Senden der Scheduler-Notification: %s", notif_error)


def run_daemon_restart(pipeline_name: str) -> None:
    """
    Wird vom APScheduler für Dauerläufer-Restart aufgerufen (per textueller Referenz).
    Muss Modul-Level sein für Serialisierung im JobStore.
    """
    if _scheduler_started_at is not None:
        elapsed = (datetime.now(timezone.utc) - _scheduler_started_at).total_seconds()
        if elapsed < SCHEDULER_GRACE_SECONDS:
            logger.info(
                "Daemon-Restart übersprungen (Grace-Period nach Start): %s (noch %.0fs von %ss)",
                pipeline_name,
                SCHEDULER_GRACE_SECONDS - elapsed,
                SCHEDULER_GRACE_SECONDS,
            )
            return
    try:
        from app.services.daemon_watcher import perform_daemon_restart
        if _main_loop is not None and _main_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                perform_daemon_restart(pipeline_name), _main_loop
            )
            future.result(timeout=120)
        else:
            asyncio.run(perform_daemon_restart(pipeline_name))
    except Exception as e:
        logger.error("Fehler bei Daemon-Restart für %s: %s", pipeline_name, e, exc_info=True)


def _job_executed_listener(event) -> None:
    """
    Event-Listener für Job-Ausführungen.
    
    Wird aufgerufen, wenn ein Job erfolgreich ausgeführt wurde oder
    einen Fehler hatte. Loggt die Ergebnisse und sendet Notifications.
    
    Args:
        event: APScheduler Event-Objekt
    """
    if event.exception:
        logger.error(f"Job {event.job_id} fehlgeschlagen: {event.exception}")
        # Notification für Scheduler-Fehler (asynchron im Hintergrund)
        try:
            import asyncio
            from app.services.notifications import send_scheduler_error_notification
            # Versuche Pipeline-Name aus Job-ID zu extrahieren (falls Job-ID = Pipeline-Name)
            pipeline_name = event.job_id
            asyncio.create_task(send_scheduler_error_notification(pipeline_name, str(event.exception)))
        except Exception as notif_error:
            logger.error(f"Fehler beim Senden der Scheduler-Notification: {notif_error}")
    else:
        logger.debug(f"Job {event.job_id} erfolgreich ausgeführt")


def add_job(
    pipeline_name: str,
    trigger_type: TriggerType,
    trigger_value: str,
    enabled: bool = True,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    source: str = "api",
    run_config_id: Optional[str] = None,
    session: Optional[Session] = None
) -> ScheduledJob:
    """
    Erstellt einen neuen geplanten Job.
    
    Args:
        pipeline_name: Name der Pipeline
        trigger_type: CRON oder INTERVAL
        trigger_value: Cron-Expression oder Interval-String
        enabled: Job aktiviert/deaktiviert (Standard: True)
        start_date: Optionaler Start des Zeitraums (UTC)
        end_date: Optionales Ende des Zeitraums (UTC)
        source: "api" oder "pipeline_json"
        run_config_id: Optionale Run-Konfiguration aus pipeline.json schedules
        session: SQLModel Session (optional)
    
    Returns:
        ScheduledJob: Erstellter Job-Datensatz
    
    Raises:
        ValueError: Wenn Pipeline nicht existiert oder Trigger ungültig ist
        RuntimeError: Wenn Scheduler nicht läuft
    """
    # Pipeline-Validierung
    pipeline = get_pipeline(pipeline_name)
    if pipeline is None:
        raise ValueError(f"Pipeline nicht gefunden: {pipeline_name}")
    
    # Trigger-Validierung (mit Zeitraum)
    trigger = _create_trigger(trigger_type, trigger_value, start_date=start_date, end_date=end_date)
    if trigger is None:
        raise ValueError(f"Ungültiger Trigger: {trigger_type} = {trigger_value}")
    
    # Session verwenden oder neue erstellen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # ScheduledJob in Datenbank erstellen
        job = ScheduledJob(
            pipeline_name=pipeline_name,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            enabled=enabled,
            start_date=start_date,
            end_date=end_date,
            source=source if source in ("api", "pipeline_json", "daemon_restart") else "api",
            run_config_id=run_config_id
        )
        
        session.add(job)
        session.commit()
        session.refresh(job)
        
        # Job zum Scheduler hinzufügen (wenn aktiviert)
        if enabled and _scheduler is not None and _scheduler.running:
            _add_job_to_scheduler(job)
        
        logger.info(f"Job erstellt: {job.id} (Pipeline: {pipeline_name})")
        return job
        
    finally:
        if close_session:
            session.close()


def update_job(
    job_id: UUID,
    pipeline_name: Optional[str] = None,
    trigger_type: Optional[TriggerType] = None,
    trigger_value: Optional[str] = None,
    enabled: Optional[bool] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    run_config_id: Union[Optional[str], object] = _UPDATE_RUN_CONFIG_ID_OMIT,
    session: Optional[Session] = None
) -> ScheduledJob:
    """
    Aktualisiert einen bestehenden Job.
    
    Args:
        job_id: Job-ID
        pipeline_name: Neuer Pipeline-Name (optional)
        trigger_type: Neuer Trigger-Typ (optional)
        trigger_value: Neuer Trigger-Wert (optional)
        enabled: Neuer Enabled-Status (optional)
        start_date: Neuer Start des Zeitraums (optional)
        end_date: Neues Ende des Zeitraums (optional)
        run_config_id: Optionale Run-Konfiguration (None = leeren; nicht uebergeben = nicht aendern)
        session: SQLModel Session (optional)
    
    Returns:
        ScheduledJob: Aktualisierter Job-Datensatz
    
    Raises:
        ValueError: Wenn Job nicht gefunden oder Parameter ungültig sind
        RuntimeError: Wenn Scheduler nicht läuft
    """
    # Session verwenden oder neue erstellen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # Job aus Datenbank laden
        job = session.get(ScheduledJob, job_id)
        if not job:
            raise ValueError(f"Job nicht gefunden: {job_id}")
        
        # Pipeline-Validierung (wenn Pipeline-Name geändert wird)
        if pipeline_name is not None and pipeline_name != job.pipeline_name:
            pipeline = get_pipeline(pipeline_name)
            if pipeline is None:
                raise ValueError(f"Pipeline nicht gefunden: {pipeline_name}")
            job.pipeline_name = pipeline_name
        
        # Trigger aktualisieren
        if trigger_type is not None:
            job.trigger_type = trigger_type
        if trigger_value is not None:
            job.trigger_value = trigger_value
        
        # Zeitraum aktualisieren
        if start_date is not None:
            job.start_date = start_date
        if end_date is not None:
            job.end_date = end_date
        if run_config_id is not _UPDATE_RUN_CONFIG_ID_OMIT:
            job.run_config_id = run_config_id
        
        # Trigger-Validierung (mit Zeitraum)
        trigger = _create_trigger(
            job.trigger_type,
            job.trigger_value,
            start_date=job.start_date,
            end_date=job.end_date
        )
        if trigger is None:
            raise ValueError(f"Ungültiger Trigger: {job.trigger_type} = {job.trigger_value}")
        
        # Enabled-Status aktualisieren
        if enabled is not None:
            job.enabled = enabled
        
        session.add(job)
        session.commit()
        session.refresh(job)
        
        # Job im Scheduler aktualisieren
        if _scheduler is not None and _scheduler.running:
            job_id_str = str(job_id)
            
            if job.enabled:
                # Job im Scheduler aktualisieren oder hinzufügen
                _add_job_to_scheduler(job)
            else:
                # Job aus Scheduler entfernen (wenn deaktiviert)
                try:
                    _scheduler.remove_job(job_id_str)
                    logger.info(f"Deaktivierten Job aus Scheduler entfernt: {job_id_str}")
                except Exception as e:
                    logger.warning(f"Fehler beim Entfernen von Job {job_id_str}: {e}")
        
        logger.info(f"Job aktualisiert: {job_id}")
        return job
        
    finally:
        if close_session:
            session.close()


def delete_job(job_id: UUID, session: Optional[Session] = None) -> None:
    """
    Löscht einen Job aus Datenbank und Scheduler.
    
    Args:
        job_id: Job-ID
        session: SQLModel Session (optional)
    
    Raises:
        ValueError: Wenn Job nicht gefunden ist
    """
    # Session verwenden oder neue erstellen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # Job aus Datenbank laden
        job = session.get(ScheduledJob, job_id)
        if not job:
            raise ValueError(f"Job nicht gefunden: {job_id}")
        
        # Job aus Scheduler entfernen
        if _scheduler is not None and _scheduler.running:
            try:
                _scheduler.remove_job(str(job_id))
            except Exception as e:
                logger.warning(f"Fehler beim Entfernen von Job {job_id} aus Scheduler: {e}")
        
        # Job aus Datenbank löschen
        session.delete(job)
        session.commit()
        
        logger.info(f"Job gelöscht: {job_id}")
        
    finally:
        if close_session:
            session.close()


def get_all_jobs(session: Optional[Session] = None) -> List[ScheduledJob]:
    """
    Gibt alle Jobs aus der Datenbank zurück.
    
    Args:
        session: SQLModel Session (optional)
    
    Returns:
        Liste aller ScheduledJob-Datensätze
    """
    # Session verwenden oder neue erstellen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        statement = select(ScheduledJob)
        jobs = list(session.exec(statement).all())
        return jobs
    finally:
        if close_session:
            session.close()


def get_job(job_id: UUID, session: Optional[Session] = None) -> Optional[ScheduledJob]:
    """
    Gibt einen Job anhand der ID zurück.
    
    Args:
        job_id: Job-ID
        session: SQLModel Session (optional)
    
    Returns:
        ScheduledJob oder None wenn nicht gefunden
    """
    # Session verwenden oder neue erstellen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        return session.get(ScheduledJob, job_id)
    finally:
        if close_session:
            session.close()


def get_job_details(job_id: UUID, session: Optional[Session] = None) -> Dict[str, Any]:
    """
    Gibt erweiterte Job-Details zurück (inkl. next_run_time, last_run_time, run_count).
    
    Args:
        job_id: Job-ID
        session: SQLModel Session (optional)
    
    Returns:
        Dictionary mit Job-Details oder None wenn nicht gefunden
    """
    job = get_job(job_id, session)
    if job is None:
        return None
    
    details = {
        "id": job.id,
        "pipeline_name": job.pipeline_name,
        "trigger_type": job.trigger_type,
        "trigger_value": job.trigger_value,
        "enabled": job.enabled,
        "created_at": job.created_at.isoformat(),
        "next_run_time": None,
        "last_run_time": None,
        "run_count": 0,
        "source": getattr(job, "source", "api"),
        "run_config_id": getattr(job, "run_config_id", None)
    }
    if getattr(job, "start_date", None) is not None:
        details["start_date"] = job.start_date.isoformat()
    if getattr(job, "end_date", None) is not None:
        details["end_date"] = job.end_date.isoformat()
    
    # APScheduler-Job-Details abrufen
    if _scheduler is not None and _scheduler.running:
        try:
            scheduler_job = _scheduler.get_job(str(job_id))
            if scheduler_job and scheduler_job.next_run_time:
                details["next_run_time"] = scheduler_job.next_run_time.isoformat()
        except Exception as e:
            logger.warning(f"Fehler beim Abrufen von Scheduler-Job-Details für {job_id}: {e}")

    # Fallback: next_run_time aus Trigger berechnen, falls Scheduler keinen liefert
    if details.get("next_run_time") is None and job.trigger_type != TriggerType.DATE:
        try:
            trigger = _create_trigger(
                job.trigger_type,
                job.trigger_value,
                start_date=getattr(job, "start_date", None),
                end_date=getattr(job, "end_date", None),
            )
            if trigger is not None:
                next_fire = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
                if next_fire is not None:
                    details["next_run_time"] = next_fire.isoformat()
        except Exception as e:
            logger.debug("Fallback next_run_time für Job %s: %s", job_id, e)
    
    # Run-Count aus Datenbank abrufen
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        from app.models import PipelineRun
        from sqlmodel import select, func
        job_rcid = getattr(job, "run_config_id", None)
        run_count_stmt = (
            select(func.count(PipelineRun.id))
            .where(PipelineRun.pipeline_name == job.pipeline_name)
        )
        if job_rcid is not None:
            run_count_stmt = run_count_stmt.where(PipelineRun.run_config_id == job_rcid)
        run_count = session.exec(run_count_stmt).one()
        details["run_count"] = run_count

        last_run_stmt = (
            select(PipelineRun)
            .where(PipelineRun.pipeline_name == job.pipeline_name)
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        if job_rcid is not None:
            last_run_stmt = last_run_stmt.where(PipelineRun.run_config_id == job_rcid)
        last_run = session.exec(last_run_stmt).first()
        if last_run:
            details["last_run_time"] = last_run.started_at.isoformat()
    finally:
        if close_session:
            session.close()
    
    return details


def sync_scheduler_jobs_from_pipeline_json(session: Optional[Session] = None) -> None:
    """
    Synchronisiert Scheduler-Jobs aus pipeline.json: Pipelines mit schedule_cron oder
    schedule_interval_seconds bekommen einen Job (source=pipeline_json); Pipelines mit
    run_once_at (in der Zukunft) bekommen einen einmaligen DATE-Job. Bestehende
    JSON-Jobs werden aktualisiert oder entfernt, wenn der Schedule aus der JSON
    entfernt wurde oder die Pipeline nicht mehr existiert.
    """
    if session is None:
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    try:
        discovered = discover_pipelines(force_refresh=True)
        now_utc = datetime.now(timezone.utc)
        # (pipeline_name, run_config_id) -> opts; run_config_id None = Top-Level-Schedule
        pipelines_with_schedule: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        pipelines_with_run_once: Dict[str, str] = {}
        pipelines_with_restart_interval: Dict[str, Dict[str, Any]] = {}
        for p in discovered:
            meta = p.metadata
            schedules = getattr(meta, "schedules", None) or []
            restart_interval = getattr(meta, "restart_interval", None)
            if restart_interval:
                parts = str(restart_interval).strip().split()
                if len(parts) == 5:
                    trigger_type = TriggerType.CRON
                    trigger_value = restart_interval
                else:
                    try:
                        secs = int(restart_interval)
                        if secs > 0:
                            trigger_type = TriggerType.INTERVAL
                            trigger_value = str(secs)
                        else:
                            trigger_type = None
                            trigger_value = None
                    except (TypeError, ValueError):
                        trigger_type = None
                        trigger_value = None
                if trigger_type and trigger_value:
                    pipelines_with_restart_interval[p.name] = {
                        "trigger_type": trigger_type,
                        "trigger_value": trigger_value,
                        "enabled": p.is_enabled()
                    }
            # Variante A: Wenn schedules gesetzt, nur Einträge aus schedules; sonst Top-Level
            if schedules:
                for s in schedules:
                    sid = s.get("id")
                    cron = s.get("schedule_cron")
                    interval = s.get("schedule_interval_seconds")
                    if not cron and interval is None:
                        continue
                    trigger_type = TriggerType.CRON if cron else TriggerType.INTERVAL
                    trigger_value = cron if cron else str(interval)
                    start_dt = _parse_schedule_datetime(s.get("schedule_start"), end_of_day=False)
                    end_dt = _parse_schedule_datetime(s.get("schedule_end"), end_of_day=True)
                    key = (p.name, sid)
                    schedule_enabled = s.get("enabled", True)
                    pipelines_with_schedule[key] = {
                        "trigger_type": trigger_type,
                        "trigger_value": trigger_value,
                        "start_date": start_dt,
                        "end_date": end_dt,
                        "enabled": p.is_enabled() and schedule_enabled
                    }
            else:
                cron = getattr(meta, "schedule_cron", None)
                interval = getattr(meta, "schedule_interval_seconds", None)
                if cron or interval is not None:
                    trigger_type = TriggerType.CRON if cron else TriggerType.INTERVAL
                    trigger_value = cron if cron else str(interval)
                    start_dt = _parse_schedule_datetime(getattr(meta, "schedule_start", None), end_of_day=False)
                    end_dt = _parse_schedule_datetime(getattr(meta, "schedule_end", None), end_of_day=True)
                    key = (p.name, None)
                    pipelines_with_schedule[key] = {
                        "trigger_type": trigger_type,
                        "trigger_value": trigger_value,
                        "start_date": start_dt,
                        "end_date": end_dt,
                        "enabled": p.is_enabled()
                    }
            run_once_at = getattr(meta, "run_once_at", None)
            if run_once_at:
                run_dt = _parse_schedule_datetime(run_once_at, end_of_day=False)
                if run_dt and run_dt > now_utc:
                    pipelines_with_run_once[p.name] = run_once_at
        existing_json_jobs = list(
            session.exec(select(ScheduledJob).where(ScheduledJob.source == "pipeline_json")).all()
        )
        existing_daemon_restart_jobs = list(
            session.exec(select(ScheduledJob).where(ScheduledJob.source == "daemon_restart")).all()
        )
        seen_schedule_keys = set(pipelines_with_schedule.keys())
        seen_names = set(pipelines_with_run_once.keys())
        seen_restart_names = set(pipelines_with_restart_interval.keys())
        for (pname, run_config_id), opts in pipelines_with_schedule.items():
            existing = next(
                (j for j in existing_json_jobs if j.pipeline_name == pname and getattr(j, "run_config_id", None) == run_config_id and j.trigger_type in (TriggerType.CRON, TriggerType.INTERVAL)),
                None
            )
            try:
                if existing:
                    update_job(
                        existing.id,
                        trigger_type=opts["trigger_type"],
                        trigger_value=opts["trigger_value"],
                        enabled=opts["enabled"],
                        start_date=opts["start_date"],
                        end_date=opts["end_date"],
                        run_config_id=run_config_id,
                        session=session
                    )
                    logger.info("Scheduler-Job aus pipeline.json aktualisiert: %s%s", pname, f" (run_config_id={run_config_id})" if run_config_id else "")
                else:
                    add_job(
                        pipeline_name=pname,
                        trigger_type=opts["trigger_type"],
                        trigger_value=opts["trigger_value"],
                        enabled=opts["enabled"],
                        start_date=opts["start_date"],
                        end_date=opts["end_date"],
                        source="pipeline_json",
                        run_config_id=run_config_id,
                        session=session
                    )
                    logger.info("Scheduler-Job aus pipeline.json angelegt: %s%s", pname, f" (run_config_id={run_config_id})" if run_config_id else "")
            except Exception as e:
                logger.warning("Fehler beim Sync des Scheduler-Jobs für %s: %s", pname, e)
        for pname, run_once_at_str in pipelines_with_run_once.items():
            existing = next(
                (j for j in existing_json_jobs if j.pipeline_name == pname and j.trigger_type == TriggerType.DATE),
                None
            )
            try:
                if existing:
                    if existing.trigger_value != run_once_at_str:
                        update_job(
                            existing.id,
                            trigger_type=TriggerType.DATE,
                            trigger_value=run_once_at_str,
                            enabled=True,
                            session=session
                        )
                        logger.info("Run-Once-Job aus pipeline.json aktualisiert: %s", pname)
                else:
                    add_job(
                        pipeline_name=pname,
                        trigger_type=TriggerType.DATE,
                        trigger_value=run_once_at_str,
                        enabled=True,
                        source="pipeline_json",
                        session=session
                    )
                    logger.info("Run-Once-Job aus pipeline.json angelegt: %s", pname)
            except Exception as e:
                logger.warning("Fehler beim Sync des Run-Once-Jobs für %s: %s", pname, e)
        for pname, opts in pipelines_with_restart_interval.items():
            existing = next(
                (j for j in existing_daemon_restart_jobs if j.pipeline_name == pname),
                None
            )
            try:
                if existing:
                    update_job(
                        existing.id,
                        trigger_type=opts["trigger_type"],
                        trigger_value=opts["trigger_value"],
                        enabled=opts["enabled"],
                        session=session
                    )
                    logger.info("Daemon-Restart-Job aus pipeline.json aktualisiert: %s", pname)
                else:
                    add_job(
                        pipeline_name=pname,
                        trigger_type=opts["trigger_type"],
                        trigger_value=opts["trigger_value"],
                        enabled=opts["enabled"],
                        source="daemon_restart",
                        session=session
                    )
                    logger.info("Daemon-Restart-Job aus pipeline.json angelegt: %s", pname)
            except Exception as e:
                logger.warning("Fehler beim Sync des Daemon-Restart-Jobs für %s: %s", pname, e)
        for job in existing_daemon_restart_jobs:
            if job.pipeline_name not in seen_restart_names:
                try:
                    delete_job(job.id, session=session)
                    logger.info("Daemon-Restart-Job entfernt (restart_interval nicht mehr in JSON): %s", job.pipeline_name)
                except Exception as e:
                    logger.warning("Fehler beim Löschen des Daemon-Restart-Jobs %s: %s", job.id, e)
        for job in existing_json_jobs:
            job_rcid = getattr(job, "run_config_id", None)
            if job.trigger_type == TriggerType.DATE:
                if job.pipeline_name not in seen_names:
                    try:
                        delete_job(job.id, session=session)
                        logger.info("Scheduler-Job aus pipeline.json entfernt (nicht mehr in JSON): %s", job.pipeline_name)
                    except Exception as e:
                        logger.warning("Fehler beim Löschen des Scheduler-Jobs %s: %s", job.id, e)
            elif (job.pipeline_name, job_rcid) not in seen_schedule_keys:
                try:
                    delete_job(job.id, session=session)
                    logger.info("Scheduler-Job aus pipeline.json entfernt (nicht mehr in JSON): %s%s", job.pipeline_name, f" run_config_id={job_rcid}" if job_rcid else "")
                except Exception as e:
                    logger.warning("Fehler beim Löschen des Scheduler-Jobs %s: %s", job.id, e)
    finally:
        if close_session:
            session.close()


def get_scheduler() -> Optional[BackgroundScheduler]:
    """
    Gibt die globale Scheduler-Instanz zurück.
    
    Returns:
        BackgroundScheduler oder None wenn nicht initialisiert
    """
    return _scheduler
