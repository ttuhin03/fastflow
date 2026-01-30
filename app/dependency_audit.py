"""
Scheduled Dependency Audit (pip-audit).

Läuft täglich (oder per Cron aus SystemSettings) und prüft alle Pipelines
mit requirements.txt auf Sicherheitslücken. Bei Fund: E-Mail/Teams-Benachrichtigung.
"""

import asyncio
import logging
from typing import Any, Dict, List

from app.dependencies import get_pipeline_packages, run_pip_audit
from app.pipeline_discovery import discover_pipelines
from app.notifications import send_dependency_vuln_notification

logger = logging.getLogger(__name__)

DEPENDENCY_AUDIT_JOB_ID = "dependency_audit_job"


async def run_dependency_audit_async() -> List[Dict[str, Any]]:
    """
    Führt pip-audit für alle Pipelines mit requirements.txt aus.
    Gibt Liste von {pipeline, packages, vulnerabilities?, audit_error?} zurück.
    """
    pipelines = discover_pipelines()
    results: List[Dict[str, Any]] = []
    for p in pipelines:
        if not p.has_requirements:
            continue
        req_path = p.path / "requirements.txt"
        vulns, err = await run_pip_audit(req_path)
        entry: Dict[str, Any] = {
            "pipeline": p.name,
            "packages": get_pipeline_packages(p.name),
            "vulnerabilities": vulns,
        }
        if err:
            entry["audit_error"] = err
        results.append(entry)
    return results


def run_dependency_audit_sync() -> List[Dict[str, Any]]:
    """Synchroner Wrapper für run_dependency_audit_async (für APScheduler)."""
    return asyncio.run(run_dependency_audit_async())


def run_dependency_audit_job_sync() -> None:
    """
    Job-Funktion: Führt Audit aus und sendet bei Schwachstellen E-Mail/Teams.
    Wird vom Scheduler aufgerufen (sync).
    """
    try:
        results = run_dependency_audit_sync()
        vuln_entries = [r for r in results if (r.get("vulnerabilities") or []) and not r.get("audit_error")]
        if vuln_entries:
            asyncio.run(send_dependency_vuln_notification(vuln_entries))
        logger.info(
            "Dependency-Audit-Job abgeschlossen: %d Pipelines geprüft, %d mit Schwachstellen",
            len(results),
            len(vuln_entries),
        )
    except Exception as e:
        logger.exception("Dependency-Audit-Job fehlgeschlagen: %s", e)


def schedule_dependency_audit_job() -> None:
    """
    Liest SystemSettings und plant den Dependency-Audit-Job (oder entfernt ihn).
    Wird beim App-Start und nach Änderung der System-Einstellungen aufgerufen.
    """
    try:
        from app.scheduler import get_scheduler
        from app.database import engine
        from app.posthog_client import get_system_settings
        from sqlmodel import Session
        from apscheduler.triggers.cron import CronTrigger

        scheduler = get_scheduler()
        if scheduler is None or not scheduler.running:
            return

        with Session(engine) as session:
            ss = get_system_settings(session)
            enabled = getattr(ss, "dependency_audit_enabled", False)
            cron_expr = getattr(ss, "dependency_audit_cron", "0 3 * * *") or "0 3 * * *"

        try:
            scheduler.remove_job(DEPENDENCY_AUDIT_JOB_ID)
        except Exception:
            pass

        if not enabled:
            logger.info("Dependency-Audit-Job deaktiviert (System-Einstellungen)")
            return

        # Cron-Format: minute hour day month day_of_week (5 Felder)
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            logger.warning("Dependency-Audit Cron ungültig (erwarte 5 Felder): %s", cron_expr)
            cron_expr = "0 3 * * *"
            parts = cron_expr.split()

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
        scheduler.add_job(
            func="app.dependency_audit:run_dependency_audit_job_sync",
            trigger=trigger,
            id=DEPENDENCY_AUDIT_JOB_ID,
            name="Dependency Audit (pip-audit)",
            replace_existing=True,
        )
        logger.info("Dependency-Audit-Job geplant: Cron %s", cron_expr)
    except Exception as e:
        logger.error("Fehler beim Planen des Dependency-Audit-Jobs: %s", e, exc_info=True)
