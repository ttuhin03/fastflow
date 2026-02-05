"""
Daemon Watcher Service.

Unterstützt Dauerläufer-Pipelines (timeout: 0) mit:
- restart_on_crash: Automatischer Neustart bei FAILED nach Cooldown
- restart_interval: Regelmäßiger Neustart via Scheduler-Jobs
"""

import asyncio
import logging
from typing import Optional

from sqlmodel import Session, select

from app.core.database import get_session
from app.executor import cancel_run, run_pipeline
from app.models import PipelineRun, RunStatus
from app.services.pipeline_discovery import get_pipeline

logger = logging.getLogger(__name__)


async def perform_daemon_restart(pipeline_name: str) -> None:
    """
    Führt einen regulären Dauerläufer-Neustart durch (für restart_interval).

    Bricht einen laufenden Run ab, wartet restart_cooldown Sekunden, startet die
    Pipeline neu. Wird vom Scheduler aufgerufen.

    Args:
        pipeline_name: Name der Pipeline
    """
    pipeline = get_pipeline(pipeline_name)
    if pipeline is None:
        logger.warning("Pipeline %s nicht gefunden, Daemon-Restart abgebrochen", pipeline_name)
        return
    if not pipeline.is_enabled():
        logger.info("Pipeline %s ist deaktiviert, Daemon-Restart übersprungen", pipeline_name)
        return
    cooldown = getattr(pipeline.metadata, "restart_cooldown", 60) or 60
    session_gen = get_session()
    session = next(session_gen)
    try:
        run = session.exec(
            select(PipelineRun)
            .where(PipelineRun.pipeline_name == pipeline_name)
            .where(PipelineRun.status == RunStatus.RUNNING)
            .limit(1)
        ).first()
        if run:
            logger.info("Daemon-Restart: Breche laufenden Run %s für %s ab", run.id, pipeline_name)
            await cancel_run(run.id, session)
        await asyncio.sleep(cooldown)
        await run_pipeline(pipeline_name, triggered_by="daemon_restart")
        logger.info("Daemon-Restart ausgeführt: %s", pipeline_name)
    except Exception as e:
        logger.error("Fehler beim Daemon-Restart für %s: %s", pipeline_name, e, exc_info=True)
    finally:
        session.close()


async def schedule_restart_on_crash(pipeline_name: str, restart_cooldown: int) -> None:
    """
    Startet die Pipeline nach restart_cooldown Sekunden neu (für restart_on_crash).

    Wird vom Executor aufgerufen, wenn ein Run mit FAILED endet und die Pipeline
    restart_on_crash=true hat. Läuft asynchron im Hintergrund.

    Args:
        pipeline_name: Name der Pipeline
        restart_cooldown: Wartezeit in Sekunden vor dem Neustart
    """
    if restart_cooldown < 0:
        restart_cooldown = 60
    logger.info(
        "Dauerläufer-Restart geplant: %s in %d Sekunden (restart_on_crash)",
        pipeline_name,
        restart_cooldown,
    )
    await asyncio.sleep(restart_cooldown)
    pipeline = get_pipeline(pipeline_name)
    if pipeline is None:
        logger.warning("Pipeline %s nicht mehr gefunden, Restart abgebrochen", pipeline_name)
        return
    if not pipeline.is_enabled():
        logger.info("Pipeline %s ist deaktiviert, Restart übersprungen", pipeline_name)
        return
    if not getattr(pipeline.metadata, "restart_on_crash", False):
        logger.debug("restart_on_crash für %s wurde deaktiviert, Restart übersprungen", pipeline_name)
        return
    try:
        await run_pipeline(pipeline_name, triggered_by="daemon_restart")
        logger.info("Dauerläufer-Restart ausgeführt: %s", pipeline_name)
    except Exception as e:
        logger.error("Fehler beim Dauerläufer-Restart für %s: %s", pipeline_name, e, exc_info=True)
