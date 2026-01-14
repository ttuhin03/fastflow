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
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from sqlmodel import Session, select

from app.config import config
from app.models import ScheduledJob, TriggerType
from app.executor import run_pipeline
from app.pipeline_discovery import get_pipeline
from app.database import get_session

logger = logging.getLogger(__name__)

# Globale Scheduler-Instanz
_scheduler: Optional[BackgroundScheduler] = None


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
    
    try:
        _scheduler.start()
        logger.info("Scheduler gestartet")
        
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
        # Trigger erstellen
        trigger = _create_trigger(job.trigger_type, job.trigger_value)
        
        if trigger is None:
            logger.error(f"Ungültiger Trigger für Job {job.id}: {job.trigger_type} = {job.trigger_value}")
            return
        
        # Job-Funktion: Pipeline ausführen
        job_func = _create_job_function(job.pipeline_name)
        
        # Job zum Scheduler hinzufügen
        _scheduler.add_job(
            job_func,
            trigger=trigger,
            id=str(job.id),
            replace_existing=True,
            max_instances=1  # Verhindert gleichzeitige Ausführungen desselben Jobs
        )
        
        logger.info(f"Job zum Scheduler hinzugefügt: {job.id} (Pipeline: {job.pipeline_name})")
        
    except Exception as e:
        logger.error(f"Fehler beim Hinzufügen von Job {job.id} zum Scheduler: {e}")


def _create_trigger(trigger_type: TriggerType, trigger_value: str):
    """
    Erstellt einen APScheduler-Trigger aus TriggerType und TriggerValue.
    
    Args:
        trigger_type: CRON oder INTERVAL
        trigger_value: Cron-Expression (z.B. "0 0 * * *") oder Interval-String (z.B. "3600" für Sekunden)
    
    Returns:
        Trigger-Objekt (CronTrigger oder IntervalTrigger) oder None bei Fehler
    """
    try:
        if trigger_type == TriggerType.CRON:
            # Cron-Expression parsen (Format: "minute hour day month day_of_week")
            # Beispiel: "0 0 * * *" = täglich um Mitternacht
            parts = trigger_value.strip().split()
            if len(parts) != 5:
                logger.error(f"Ungültige Cron-Expression: {trigger_value} (erwartet 5 Teile)")
                return None
            
            return CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4]
            )
        
        elif trigger_type == TriggerType.INTERVAL:
            # Interval-String parsen (Sekunden als Integer)
            try:
                seconds = int(trigger_value)
                if seconds <= 0:
                    logger.error(f"Ungültiges Interval: {trigger_value} (muss > 0)")
                    return None
                
                return IntervalTrigger(seconds=seconds)
            except ValueError:
                logger.error(f"Ungültiges Interval-Format: {trigger_value} (erwartet Integer)")
                return None
        
        else:
            logger.error(f"Unbekannter Trigger-Typ: {trigger_type}")
            return None
            
    except Exception as e:
        logger.error(f"Fehler beim Erstellen des Triggers: {e}")
        return None


def _create_job_function(pipeline_name: str):
    """
    Erstellt eine Job-Funktion für Pipeline-Ausführung.
    
    Args:
        pipeline_name: Name der Pipeline
    
    Returns:
        Callable: Job-Funktion
    """
    def job_function():
        """
        Job-Funktion, die die Pipeline ausführt.
        
        Wird vom Scheduler aufgerufen. Führt die Pipeline asynchron aus.
        """
        # Pipeline-Validierung: Prüfe ob Pipeline existiert
        pipeline = get_pipeline(pipeline_name)
        if pipeline is None:
            logger.error(f"Pipeline nicht gefunden für Job: {pipeline_name}")
            return
        
        # Pipeline-Validierung: Prüfe ob Pipeline aktiviert ist
        if not pipeline.is_enabled():
            logger.warning(f"Pipeline ist deaktiviert für Job: {pipeline_name}")
            return
        
        # Pipeline asynchron ausführen
        # Hinweis: APScheduler ruft synchrone Funktionen auf, daher müssen wir
        # asyncio.run() verwenden, um die async run_pipeline-Funktion aufzurufen
        # run_pipeline erstellt intern eine Session wenn keine übergeben wird
        try:
            asyncio.run(run_pipeline(pipeline_name))
            logger.info(f"Geplante Pipeline ausgeführt: {pipeline_name}")
        except Exception as e:
            logger.error(f"Fehler bei geplanter Pipeline-Ausführung {pipeline_name}: {e}")
    
    return job_function


def _job_executed_listener(event) -> None:
    """
    Event-Listener für Job-Ausführungen.
    
    Wird aufgerufen, wenn ein Job erfolgreich ausgeführt wurde oder
    einen Fehler hatte. Loggt die Ergebnisse.
    
    Args:
        event: APScheduler Event-Objekt
    """
    if event.exception:
        logger.error(f"Job {event.job_id} fehlgeschlagen: {event.exception}")
    else:
        logger.debug(f"Job {event.job_id} erfolgreich ausgeführt")


def add_job(
    pipeline_name: str,
    trigger_type: TriggerType,
    trigger_value: str,
    enabled: bool = True,
    session: Optional[Session] = None
) -> ScheduledJob:
    """
    Erstellt einen neuen geplanten Job.
    
    Args:
        pipeline_name: Name der Pipeline
        trigger_type: CRON oder INTERVAL
        trigger_value: Cron-Expression oder Interval-String
        enabled: Job aktiviert/deaktiviert (Standard: True)
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
    
    # Trigger-Validierung
    trigger = _create_trigger(trigger_type, trigger_value)
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
            enabled=enabled
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
        
        # Trigger-Validierung
        trigger = _create_trigger(job.trigger_type, job.trigger_value)
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
        "run_count": 0
    }
    
    # APScheduler-Job-Details abrufen
    if _scheduler is not None and _scheduler.running:
        try:
            scheduler_job = _scheduler.get_job(str(job_id))
            if scheduler_job:
                if scheduler_job.next_run_time:
                    details["next_run_time"] = scheduler_job.next_run_time.isoformat()
        except Exception as e:
            logger.warning(f"Fehler beim Abrufen von Scheduler-Job-Details für {job_id}: {e}")
    
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
        run_count_stmt = (
            select(func.count(PipelineRun.id))
            .where(PipelineRun.pipeline_name == job.pipeline_name)
        )
        run_count = session.exec(run_count_stmt).one()
        details["run_count"] = run_count
        
        # Letzte Ausführung finden
        last_run_stmt = (
            select(PipelineRun)
            .where(PipelineRun.pipeline_name == job.pipeline_name)
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        )
        last_run = session.exec(last_run_stmt).first()
        if last_run:
            details["last_run_time"] = last_run.started_at.isoformat()
    finally:
        if close_session:
            session.close()
    
    return details


def get_scheduler() -> Optional[BackgroundScheduler]:
    """
    Gibt die globale Scheduler-Instanz zurück.
    
    Returns:
        BackgroundScheduler oder None wenn nicht initialisiert
    """
    return _scheduler
