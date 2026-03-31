"""
Periodischer Git-Sync (AUTO_SYNC_ENABLED / AUTO_SYNC_INTERVAL).

Registriert einen APScheduler-Intervall-Job, der sync_pipelines ausführt,
wenn Auto-Sync aktiv ist, ein gültiges Intervall gesetzt und ein Repo konfiguriert ist.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import config

logger = logging.getLogger(__name__)

GIT_AUTO_SYNC_JOB_ID = "git_auto_sync"

# Git-Operationen können bei großen Repos lange dauern
_GIT_AUTO_SYNC_TIMEOUT_SEC = 3600


def run_git_auto_sync() -> None:
    """
    Wird vom APScheduler aufgerufen (Modul-Level für JobStore-Serialisierung).
    Führt sync_pipelines auf der Haupt-Event-Loop der App aus.
    """
    if not config.AUTO_SYNC_ENABLED:
        return
    interval = config.AUTO_SYNC_INTERVAL
    if interval is None or interval < 60:
        return

    from app.core.database import get_session
    from app.services.git_sync_repo_config import get_sync_repo_config

    session_gen = get_session()
    session = next(session_gen)
    try:
        repo = get_sync_repo_config(session)
        if not repo or not repo.get("repo_url"):
            logger.debug("Git Auto-Sync übersprungen: kein Repository konfiguriert")
            return
    finally:
        session.close()

    async def _do_sync() -> None:
        from app.core.database import get_session
        from app.git_sync import sync_pipelines

        gen = get_session()
        s = next(gen)
        try:
            result = await sync_pipelines(session=s)
            if result.get("already_running"):
                logger.info("Git Auto-Sync: %s", result.get("message", "Sync läuft bereits"))
            elif result.get("success"):
                logger.info("Git Auto-Sync erfolgreich abgeschlossen")
            else:
                logger.warning("Git Auto-Sync: %s", result.get("message", "fehlgeschlagen"))
        finally:
            s.close()

    from app.services.scheduler import get_main_loop

    loop = get_main_loop()
    try:
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_do_sync(), loop)
            future.result(timeout=_GIT_AUTO_SYNC_TIMEOUT_SEC)
        else:
            asyncio.run(_do_sync())
    except Exception as e:
        logger.error("Git Auto-Sync fehlgeschlagen: %s", e, exc_info=True)


def schedule_git_auto_sync_job() -> None:
    """
    Registriert, aktualisiert oder entfernt den Git-Auto-Sync-Job gemäß aktueller config.
    Sollte nach Start des Schedulers und bei Änderung der Auto-Sync-Einstellungen aufgerufen werden.
    """
    from app.services.scheduler import get_scheduler

    scheduler = get_scheduler()
    if scheduler is None or not scheduler.running:
        return

    if not config.AUTO_SYNC_ENABLED or config.AUTO_SYNC_INTERVAL is None or config.AUTO_SYNC_INTERVAL < 60:
        try:
            scheduler.remove_job(GIT_AUTO_SYNC_JOB_ID)
        except Exception:
            pass
        logger.debug("Git Auto-Sync: kein Scheduler-Job (deaktiviert oder Intervall < 60s)")
        return

    seconds = config.AUTO_SYNC_INTERVAL
    scheduler.add_job(
        "app.services.git_auto_sync:run_git_auto_sync",
        "interval",
        seconds=seconds,
        id=GIT_AUTO_SYNC_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Git Auto-Sync geplant: alle %s Sekunden", seconds)
