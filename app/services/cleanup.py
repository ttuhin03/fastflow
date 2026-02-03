"""
Log-Management & Cleanup Module.

Dieses Modul verwaltet die automatische Bereinigung von Log-Dateien,
Metrics-Dateien und Docker-Ressourcen:
- Log-Rotation & Cleanup (LOG_RETENTION_RUNS, LOG_RETENTION_DAYS, LOG_MAX_SIZE_MB)
- Metrics-Cleanup (zusammen mit Log-Cleanup)
- Datenbank-Cleanup (log_file/metrics_file auf NULL setzen)
- Docker Garbage Collection (Janitor-Service für verwaiste Container/Volumes)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import UUID

import docker
from docker.errors import DockerException, APIError
from sqlmodel import Session, select, update, func

from app.core.config import config
from app.core.database import get_session
from app.models import PipelineRun, Pipeline
from app.services.s3_backup import _s3_backup, append_backup_failure
from app.services.notifications import notify_s3_backup_failed

logger = logging.getLogger(__name__)

# Docker Client (wird beim App-Start initialisiert)
_docker_client: Optional[docker.DockerClient] = None


def init_docker_client_for_cleanup() -> None:
    """
    Initialisiert den Docker-Client für Cleanup-Operationen.
    
    Wird beim App-Start aufgerufen, um sicherzustellen, dass Docker
    für Garbage Collection verfügbar ist.
    
    Raises:
        RuntimeError: Wenn Docker-Daemon nicht erreichbar ist
    """
    global _docker_client
    
    try:
        from app.executor import _get_docker_client
        _docker_client = _get_docker_client()
        logger.info("Docker-Client für Cleanup initialisiert")
    except Exception as e:
        logger.warning(f"Docker-Client für Cleanup nicht verfügbar: {e}")
        # Nicht kritisch, Cleanup kann trotzdem ohne Docker laufen
        _docker_client = None


async def cleanup_logs(session: Session) -> Dict[str, Any]:
    """
    Führt Log-Cleanup basierend auf Retention-Policies durch.
    
    Implementiert:
    - LOG_RETENTION_RUNS: Älteste Runs pro Pipeline löschen
    - LOG_RETENTION_DAYS: Logs älter als X Tage löschen
    - LOG_MAX_SIZE_MB: Log-Dateien größer als X MB kürzen/löschen
    
    Args:
        session: SQLModel Session
    
    Returns:
        Dictionary mit Cleanup-Statistiken (deleted_runs, deleted_logs, deleted_metrics)
    """
    stats = {
        "deleted_runs": 0,
        "deleted_logs": 0,
        "deleted_metrics": 0,
        "truncated_logs": 0
    }
    
    try:
        # 1. LOG_RETENTION_RUNS: Älteste Runs pro Pipeline löschen
        if config.LOG_RETENTION_RUNS:
            deleted_runs = await _cleanup_by_retention_runs(session, config.LOG_RETENTION_RUNS)
            stats["deleted_runs"] = deleted_runs
            stats["deleted_logs"] += deleted_runs
            stats["deleted_metrics"] += deleted_runs
        
        # 2. LOG_RETENTION_DAYS: Logs älter als X Tage löschen
        if config.LOG_RETENTION_DAYS:
            deleted_runs = await _cleanup_by_retention_days(session, config.LOG_RETENTION_DAYS)
            stats["deleted_runs"] += deleted_runs
            stats["deleted_logs"] += deleted_runs
            stats["deleted_metrics"] += deleted_runs
        
        # 3. LOG_MAX_SIZE_MB: Log-Dateien größer als X MB kürzen/löschen
        if config.LOG_MAX_SIZE_MB:
            truncated_logs = await _cleanup_oversized_logs(session, config.LOG_MAX_SIZE_MB)
            stats["truncated_logs"] = truncated_logs
        
        logger.info(
            f"Log-Cleanup abgeschlossen: "
            f"{stats['deleted_runs']} Runs gelöscht, "
            f"{stats['deleted_logs']} Log-Dateien gelöscht, "
            f"{stats['deleted_metrics']} Metrics-Dateien gelöscht, "
            f"{stats['truncated_logs']} Log-Dateien gekürzt"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Fehler beim Log-Cleanup: {e}", exc_info=True)
        return stats


async def _cleanup_by_retention_runs(session: Session, max_runs: int) -> int:
    """
    Löscht älteste Runs pro Pipeline, wenn LOG_RETENTION_RUNS überschritten wird.
    
    Args:
        session: SQLModel Session
        max_runs: Maximale Anzahl Runs pro Pipeline
    
    Returns:
        Anzahl gelöschter Runs
    """
    deleted_count = 0
    
    try:
        # Alle Pipelines abrufen
        pipelines = session.exec(select(Pipeline)).all()
        
        for pipeline in pipelines:
            # Anzahl Runs für diese Pipeline zählen
            run_count = session.exec(
                select(func.count(PipelineRun.id))
                .where(PipelineRun.pipeline_name == pipeline.pipeline_name)
            ).one()
            
            if run_count <= max_runs:
                continue
            
            # Älteste Runs finden (mehr als max_runs)
            excess_count = run_count - max_runs
            
            # Älteste Runs abrufen (sortiert nach started_at)
            old_runs = session.exec(
                select(PipelineRun)
                .where(PipelineRun.pipeline_name == pipeline.pipeline_name)
                .order_by(PipelineRun.started_at.asc())
                .limit(excess_count)
            ).all()
            
            # Runs löschen (Logs, Metrics und DB-Einträge)
            for run in old_runs:
                ok, err = await _s3_backup.upload_run_logs(run)
                if not ok:
                    append_backup_failure(str(run.id), run.pipeline_name, err or "Unbekannt")
                    asyncio.create_task(notify_s3_backup_failed(run, err or "Unbekannt"))
                    continue
                await _delete_run_files(run)
                # Datenbank-Eintrag löschen
                session.delete(run)
                deleted_count += 1
            
            session.commit()
            logger.debug(
                f"Pipeline {pipeline.pipeline_name}: "
                f"{excess_count} älteste Runs gelöscht (Retention: {max_runs})"
            )
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Fehler beim Cleanup nach Retention-Runs: {e}", exc_info=True)
        session.rollback()
        return deleted_count


async def _cleanup_by_retention_days(session: Session, max_days: int) -> int:
    """
    Löscht Runs, deren Logs älter als max_days Tage sind.
    
    Args:
        session: SQLModel Session
        max_days: Maximale Alter von Logs in Tagen
    
    Returns:
        Anzahl gelöschter Runs
    """
    deleted_count = 0
    
    try:
        # Cutoff-Datum berechnen
        cutoff_date = datetime.utcnow() - timedelta(days=max_days)
        
        # Alle Runs finden, die älter als cutoff_date sind
        old_runs = session.exec(
            select(PipelineRun)
            .where(PipelineRun.started_at < cutoff_date)
        ).all()
        
        # Runs löschen (Logs, Metrics und DB-Einträge)
        for run in old_runs:
            ok, err = await _s3_backup.upload_run_logs(run)
            if not ok:
                append_backup_failure(str(run.id), run.pipeline_name, err or "Unbekannt")
                asyncio.create_task(notify_s3_backup_failed(run, err or "Unbekannt"))
                continue
            await _delete_run_files(run)
            # Datenbank-Eintrag löschen
            session.delete(run)
            deleted_count += 1
        
        session.commit()
        logger.debug(f"{deleted_count} Runs gelöscht (älter als {max_days} Tage)")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Fehler beim Cleanup nach Retention-Days: {e}", exc_info=True)
        session.rollback()
        return deleted_count


async def _cleanup_oversized_logs(session: Session, max_size_mb: int) -> int:
    """
    Kürzt oder löscht Log-Dateien, die größer als max_size_mb sind.
    
    Args:
        session: SQLModel Session
        max_size_mb: Maximale Größe einer Log-Datei in MB
    
    Returns:
        Anzahl gekürzter/gelöschter Log-Dateien
    """
    truncated_count = 0
    max_size_bytes = max_size_mb * 1024 * 1024
    
    try:
        # Alle Runs mit Log-Dateien abrufen
        runs = session.exec(
            select(PipelineRun)
            .where(PipelineRun.log_file.isnot(None))
        ).all()
        
        for run in runs:
            log_file_path = Path(run.log_file)
            
            if not log_file_path.exists():
                # Log-Datei existiert nicht mehr, DB-Eintrag bereinigen
                run.log_file = None
                session.add(run)
                continue
            
            file_size = log_file_path.stat().st_size
            
            if file_size > max_size_bytes:
                # Log-Datei kürzen (behalte letzte 50% oder löschen wenn zu groß)
                try:
                    # Strategie: Datei auf max_size_bytes kürzen (behalte Ende)
                    await _truncate_log_file(log_file_path, max_size_bytes)
                    truncated_count += 1
                    logger.debug(
                        f"Log-Datei gekürzt: {run.log_file} "
                        f"(von {file_size / (1024*1024):.2f} MB auf {max_size_bytes / (1024*1024):.2f} MB)"
                    )
                except Exception as e:
                    logger.warning(f"Fehler beim Kürzen von Log-Datei {run.log_file}: {e}")
                    # Bei Fehler: S3-Backup, dann Datei löschen und DB-Eintrag bereinigen
                    ok, err = await _s3_backup.upload_run_logs(run)
                    if not ok:
                        append_backup_failure(str(run.id), run.pipeline_name, err or "Unbekannt")
                        asyncio.create_task(notify_s3_backup_failed(run, err or "Unbekannt"))
                        continue
                    await _delete_run_files(run)
                    run.log_file = None
                    run.metrics_file = None
                    session.add(run)
        
        session.commit()
        return truncated_count
        
    except Exception as e:
        logger.error(f"Fehler beim Cleanup von oversized Logs: {e}", exc_info=True)
        session.rollback()
        return truncated_count


async def _truncate_log_file(log_file_path: Path, max_size_bytes: int) -> None:
    """
    Kürzt eine Log-Datei auf max_size_bytes (behält Ende der Datei).
    
    Args:
        log_file_path: Pfad zur Log-Datei
        max_size_bytes: Maximale Größe in Bytes
    """
    import aiofiles
    
    try:
        # Datei lesen (asynchron)
        async with aiofiles.open(log_file_path, "rb") as f:
            file_size = log_file_path.stat().st_size
            
            if file_size <= max_size_bytes:
                return
            
            # Springe zum Ende minus max_size_bytes
            offset = file_size - max_size_bytes
            await f.seek(offset)
            
            # Lese Rest der Datei
            content = await f.read()
            
            # Schreibe gekürzten Inhalt zurück (behält Ende)
            async with aiofiles.open(log_file_path, "wb") as f_write:
                await f_write.write(content)
        
        logger.debug(f"Log-Datei gekürzt: {log_file_path} (auf {max_size_bytes} Bytes)")
        
    except Exception as e:
        logger.error(f"Fehler beim Kürzen von Log-Datei {log_file_path}: {e}")
        raise


async def _delete_run_files(run: PipelineRun) -> None:
    """
    Löscht Log- und Metrics-Dateien für einen Run.
    
    Args:
        run: PipelineRun-Objekt
    """
    deleted_logs = 0
    deleted_metrics = 0
    
    # Log-Datei löschen
    if run.log_file:
        log_path = Path(run.log_file)
        if log_path.exists():
            try:
                log_path.unlink()
                deleted_logs += 1
            except Exception as e:
                logger.warning(f"Fehler beim Löschen von Log-Datei {run.log_file}: {e}")
    
    # Metrics-Datei löschen
    if run.metrics_file:
        metrics_path = Path(run.metrics_file)
        if metrics_path.exists():
            try:
                metrics_path.unlink()
                deleted_metrics += 1
            except Exception as e:
                logger.warning(f"Fehler beim Löschen von Metrics-Datei {run.metrics_file}: {e}")
    
    if deleted_logs > 0 or deleted_metrics > 0:
        logger.debug(
            f"Dateien gelöscht für Run {run.id}: "
            f"{deleted_logs} Log-Dateien, {deleted_metrics} Metrics-Dateien"
        )


async def cleanup_docker_resources() -> Dict[str, Any]:
    """
    Führt Docker Garbage Collection durch (Janitor-Service).
    
    Bereinigt verwaiste Docker-Ressourcen mit Label-basierter Strategie:
    - Container: Nur Container mit Label `fastflow-run-id` aufräumen
    - Volumes: Nur Volumes mit `fastflow-run-id` Label löschen
    - Images: Ungenutzte Images aufräumen (optional)
    
    Returns:
        Dictionary mit Cleanup-Statistiken (deleted_containers, deleted_volumes, freed_space_mb)
    """
    stats = {
        "deleted_containers": 0,
        "deleted_volumes": 0,
        "freed_space_mb": 0
    }
    
    if _docker_client is None:
        logger.warning("Docker-Client nicht verfügbar, überspringe Docker-Cleanup")
        return stats
    
    try:
        # 1. Verwaiste Container mit fastflow-run-id Label aufräumen
        deleted_containers = await _cleanup_orphaned_containers()
        stats["deleted_containers"] = deleted_containers
        
        # 2. Verwaiste Volumes mit fastflow-run-id Label aufräumen
        deleted_volumes = await _cleanup_orphaned_volumes()
        stats["deleted_volumes"] = deleted_volumes
        
        # 3. Optional: Ungenutzte Images aufräumen (nur wenn explizit konfiguriert)
        # (Nicht implementiert, da zu riskant - könnte wichtige Images löschen)
        
        logger.info(
            f"Docker-Cleanup abgeschlossen: "
            f"{stats['deleted_containers']} Container gelöscht, "
            f"{stats['deleted_volumes']} Volumes gelöscht"
        )
        
        return stats
        
    except Exception as e:
        logger.error(f"Fehler beim Docker-Cleanup: {e}", exc_info=True)
        return stats


async def _cleanup_orphaned_containers() -> int:
    """
    Bereinigt verwaiste Container mit fastflow-run-id Label.
    
    Findet Container, die nicht mehr in der Datenbank existieren
    oder bereits beendet sind.
    
    Returns:
        Anzahl gelöschter Container
    """
    deleted_count = 0
    
    if _docker_client is None:
        return deleted_count
    
    try:
        # Alle Container mit fastflow-run-id Label finden
        containers = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _docker_client.containers.list(
                filters={"label": "fastflow-run-id"},
                all=True  # Auch beendete Container
            )
        )
        
        # Session für DB-Abfragen
        session_gen = get_session()
        session = next(session_gen)
        
        try:
            for container in containers:
                run_id_str = container.labels.get("fastflow-run-id")
                if not run_id_str:
                    continue
                
                try:
                    run_id = UUID(run_id_str)
                except ValueError:
                    logger.warning(f"Ungültige Run-ID in Container-Label: {run_id_str}")
                    # Container ohne gültige Run-ID löschen
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: container.remove(force=True)
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von Container {container.id}: {e}")
                    continue
                
                # Prüfe ob Run in DB existiert
                run = session.get(PipelineRun, run_id)
                
                if run is None:
                    # Run existiert nicht in DB (orphaned Container)
                    logger.debug(f"Orphaned Container gefunden: {run_id}")
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: container.remove(force=True)
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von orphaned Container {run_id}: {e}")
                elif container.status in ["exited", "stopped"]:
                    # Container ist beendet, aber noch nicht entfernt
                    # (sollte normalerweise von executor.py entfernt werden, aber sicherheitshalber hier auch)
                    logger.debug(f"Beendeter Container gefunden: {run_id}")
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: container.remove(force=True)
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von beendetem Container {run_id}: {e}")
        
        finally:
            session.close()
        
        return deleted_count
        
    except DockerException as e:
        logger.error(f"Docker-Fehler beim Container-Cleanup: {e}")
        return deleted_count
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Container-Cleanup: {e}", exc_info=True)
        return deleted_count


async def _cleanup_orphaned_volumes() -> int:
    """
    Bereinigt verwaiste Volumes mit fastflow-run-id Label.
    
    Returns:
        Anzahl gelöschter Volumes
    """
    deleted_count = 0
    
    if _docker_client is None:
        return deleted_count
    
    try:
        # Alle Volumes mit fastflow-run-id Label finden
        volumes = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _docker_client.volumes.list(
                filters={"label": "fastflow-run-id"}
            )
        )
        
        # Session für DB-Abfragen
        session_gen = get_session()
        session = next(session_gen)
        
        try:
            for volume in volumes:
                run_id_str = volume.attrs.get("Labels", {}).get("fastflow-run-id")
                if not run_id_str:
                    continue
                
                try:
                    run_id = UUID(run_id_str)
                except ValueError:
                    logger.warning(f"Ungültige Run-ID in Volume-Label: {run_id_str}")
                    # Volume ohne gültige Run-ID löschen
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: volume.remove()
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von Volume {volume.id}: {e}")
                    continue
                
                # Prüfe ob Run in DB existiert
                run = session.get(PipelineRun, run_id)
                
                if run is None:
                    # Run existiert nicht in DB (orphaned Volume)
                    logger.debug(f"Orphaned Volume gefunden: {run_id}")
                    try:
                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: volume.remove()
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von orphaned Volume {run_id}: {e}")
        
        finally:
            session.close()
        
        return deleted_count
        
    except DockerException as e:
        logger.error(f"Docker-Fehler beim Volume-Cleanup: {e}")
        return deleted_count
    except Exception as e:
        logger.error(f"Unerwarteter Fehler beim Volume-Cleanup: {e}", exc_info=True)
        return deleted_count


async def run_cleanup_job() -> Dict[str, Any]:
    """
    Führt vollständigen Cleanup-Job aus (Logs + Docker).
    
    Wird periodisch vom Scheduler aufgerufen (z.B. täglich oder wöchentlich).
    
    Returns:
        Dictionary mit kombinierten Cleanup-Statistiken
    """
    logger.info("Starte Cleanup-Job...")
    
    # Session für Log-Cleanup
    session_gen = get_session()
    session = next(session_gen)
    
    try:
        # Log-Cleanup
        log_stats = await cleanup_logs(session)
        
        # Docker-Cleanup
        docker_stats = await cleanup_docker_resources()
        
        # Kombinierte Statistiken
        combined_stats = {
            **log_stats,
            **docker_stats
        }
        
        logger.info(f"Cleanup-Job abgeschlossen: {combined_stats}")
        
        return combined_stats
        
    finally:
        session.close()


def run_cleanup_job_sync() -> Dict[str, Any]:
    """
    Synchroner Wrapper für run_cleanup_job().
    
    Wird vom Scheduler aufgerufen (APScheduler benötigt synchrone Funktionen).
    Führt asyncio.run() intern aus.
    
    Returns:
        Dictionary mit kombinierten Cleanup-Statistiken
    """
    return asyncio.run(run_cleanup_job())


def schedule_cleanup_job() -> None:
    """
    Plant periodischen Cleanup-Job im Scheduler.
    
    Wird beim App-Start aufgerufen, um automatische Cleanup-Jobs
    zu registrieren. Standard: Täglich um 2 Uhr morgens.
    """
    try:
        from app.services.scheduler import get_scheduler
        from apscheduler.triggers.cron import CronTrigger
        
        scheduler = get_scheduler()
        if scheduler is None:
            logger.warning("Scheduler nicht verfügbar, Cleanup-Job nicht geplant")
            return
        
        if not scheduler.running:
            logger.warning("Scheduler läuft nicht, Cleanup-Job nicht geplant")
            return
        
        # Cleanup-Job planen (täglich um 2 Uhr morgens)
        # Verwende String-Referenz statt Lambda, damit Job serialisiert werden kann
        scheduler.add_job(
            func="app.services.cleanup:run_cleanup_job_sync",
            trigger=CronTrigger(hour=2, minute=0),
            id="cleanup_job",
            name="Log & Docker Cleanup Job",
            replace_existing=True
        )
        
        logger.info("Cleanup-Job geplant: Täglich um 2:00 Uhr")
        
    except Exception as e:
        logger.error(f"Fehler beim Planen des Cleanup-Jobs: {e}", exc_info=True)
