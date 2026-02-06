"""
Scheduled Dependency Audit (pip-audit).

Läuft täglich (oder per Cron aus SystemSettings) und prüft alle Pipelines
mit requirements.txt auf Sicherheitslücken. Bei Fund: E-Mail/Teams-Benachrichtigung.
Beim API-Start wird einmalig ein Durchgang ausgeführt; die letzten Ergebnisse
werden persistent gespeichert und stehen im Frontend (GET /settings/dependency-audit-last)
dauerhaft zur Verfügung – auch nach API-Neustart und bei mehreren Workern.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import config
from app.core.dependencies import get_pipeline_packages, run_pip_audit
from app.services.pipeline_discovery import discover_pipelines
from app.services.notifications import send_dependency_vuln_notification

logger = logging.getLogger(__name__)

DEPENDENCY_AUDIT_JOB_ID = "dependency_audit_job"

# Datei für persistente Speicherung (überlebt Neustart, gemeinsamer Zugriff bei mehreren Workern)
_AUDIT_LAST_FILE: Path = config.DATA_DIR / "dependency_audit_last.json"

# In-Memory-Cache (wird bei Schreiben und beim ersten Lesen aus Datei gefüllt)
_last_audit_at: Optional[datetime] = None
_last_audit_results: List[Dict[str, Any]] = []


def _load_audit_from_file() -> Tuple[Optional[datetime], List[Dict[str, Any]]]:
    """Lädt letzten Scan aus Datei. Gibt (None, []) zurück wenn Datei fehlt oder ungültig."""
    if not _AUDIT_LAST_FILE.exists():
        return None, []
    try:
        with open(_AUDIT_LAST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_at_str = data.get("last_scan_at")
        results = data.get("results") or []
        if not isinstance(results, list):
            return None, []
        last_at: Optional[datetime] = None
        if last_at_str:
            try:
                last_at = datetime.fromisoformat(last_at_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        return last_at, results
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Dependency-Audit-Last-Datei nicht lesbar: %s", e)
        return None, []


def _save_audit_to_file(last_at: datetime, results: List[Dict[str, Any]]) -> None:
    """Speichert Zeitpunkt und Ergebnisse in Datei."""
    try:
        config.ensure_directories()
        payload = {
            "last_scan_at": last_at.isoformat(),
            "results": results,
        }
        with open(_AUDIT_LAST_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=0)
    except OSError as e:
        logger.warning("Dependency-Audit-Ergebnisse konnten nicht in Datei gespeichert werden: %s", e)


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


def _store_audit_results(results: List[Dict[str, Any]]) -> None:
    """Speichert Ergebnisse und Zeitpunkt in Memory und in Datei (persistent für Frontend)."""
    global _last_audit_at, _last_audit_results
    _last_audit_at = datetime.now(timezone.utc)
    _last_audit_results = list(results)
    _save_audit_to_file(_last_audit_at, _last_audit_results)


def get_last_dependency_audit() -> Tuple[Optional[datetime], List[Dict[str, Any]]]:
    """
    Gibt Zeitpunkt und Ergebnisse des letzten Dependency-Audit-Durchgangs zurück.
    Liest bei Bedarf aus persistenter Datei (bleibt nach Neustart und für alle Worker verfügbar).
    """
    global _last_audit_at, _last_audit_results
    if _last_audit_at is not None:
        return _last_audit_at, list(_last_audit_results or [])
    last_at, results = _load_audit_from_file()
    if last_at is not None or results:
        _last_audit_at = last_at
        _last_audit_results = list(results)
        return _last_audit_at, _last_audit_results
    return None, []


def run_dependency_audit_job_sync() -> None:
    """
    Job-Funktion: Führt Audit aus und sendet bei Schwachstellen E-Mail/Teams.
    Wird vom Scheduler aufgerufen (sync). Speichert Ergebnisse für Frontend.
    """
    try:
        results = run_dependency_audit_sync()
        _store_audit_results(results)
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


async def run_dependency_audit_on_startup_async() -> None:
    """
    Führt einmalig einen Dependency-Audit-Durchgang beim API-Start aus (Hintergrund).
    Ergebnisse werden gespeichert; Benachrichtigungen werden nicht gesendet.
    """
    try:
        results = await run_dependency_audit_async()
        _store_audit_results(results)
        vuln_count = sum(1 for r in results if (r.get("vulnerabilities") or []) and not r.get("audit_error"))
        logger.info(
            "Dependency-Audit (Startup): %d Pipelines geprüft, %d mit Schwachstellen",
            len(results),
            vuln_count,
        )
    except Exception as e:
        logger.exception("Dependency-Audit (Startup) fehlgeschlagen: %s", e)


def schedule_dependency_audit_job() -> None:
    """
    Liest SystemSettings und plant den Dependency-Audit-Job (oder entfernt ihn).
    Wird beim App-Start und nach Änderung der System-Einstellungen aufgerufen.
    """
    try:
        from app.services.scheduler import get_scheduler
        from app.core.database import engine
        from app.analytics.posthog_client import get_system_settings
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
            func="app.services.dependency_audit:run_dependency_audit_job_sync",
            trigger=trigger,
            id=DEPENDENCY_AUDIT_JOB_ID,
            name="Dependency Audit (pip-audit)",
            replace_existing=True,
        )
        logger.info("Dependency-Audit-Job geplant: Cron %s", cron_expr)
    except Exception as e:
        logger.error("Fehler beim Planen des Dependency-Audit-Jobs: %s", e, exc_info=True)
