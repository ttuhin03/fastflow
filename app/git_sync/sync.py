"""
Git-Sync: Pull, Pre-Heating, Sync-Status.
"""

import asyncio
import os
import subprocess
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, Set
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import Session

from app.analytics import track_sync_completed, track_sync_failed
from app.core.config import config
from app.models import Pipeline
from app.services.pipeline_discovery import discover_pipelines, invalidate_cache

from app.git_sync.sync_log import _write_sync_log
from app.git_sync.github_token import get_github_app_token

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)
_sync_lock = asyncio.Lock()


def _run_git_command(cmd: list, cwd: Path, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    """Führt einen Git-Befehl aus (synchron). Returns (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=300
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        logger.error("Git-Befehl Timeout: %s", " ".join(cmd))
        return (-1, "", "Timeout: Git-Befehl dauerte länger als 5 Minuten")
    except Exception as e:
        logger.error("Fehler beim Ausführen von Git-Befehl: %s", e)
        return (-1, "", str(e))


async def _git_pull(branch: str, pipelines_dir: Path) -> Tuple[bool, str]:
    """Führt Git Pull aus (mit GitHub Apps falls konfiguriert). Retry bis zu 3 Versuche."""
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return (False, "Pipelines-Verzeichnis ist kein Git-Repository")
    last_msg = ""
    for attempt in range(1, 4):
        success, msg = await _git_pull_once(branch, pipelines_dir)
        if success:
            return (True, msg)
        last_msg = msg
        if attempt < 3:
            wait = min(30, 2 ** attempt)
            logger.warning("Git Pull Versuch %d/3 fehlgeschlagen: %s. Retry in %ds.", attempt, msg, wait)
            await asyncio.sleep(wait)
    return (False, last_msg)


async def _git_pull_once(branch: str, pipelines_dir: Path) -> Tuple[bool, str]:
    """Einzelner Git-Pull-Versuch (Fetch, Reset, Pull)."""
    github_token = get_github_app_token()
    env = None
    if github_token:
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = _run_git_command(remote_url_cmd, pipelines_dir)
        if exit_code == 0:
            remote_url = stdout.strip()
            if "x-access-token" not in remote_url and remote_url.startswith("https://"):
                parts = remote_url.split("://")
                if len(parts) == 2:
                    new_url = f"https://x-access-token:{github_token}@{parts[1]}"
                    set_url_cmd = ["git", "config", "remote.origin.url", new_url]
                    _run_git_command(set_url_cmd, pipelines_dir)
    fetch_cmd = ["git", "fetch", "origin", branch]
    exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
        _executor, lambda: _run_git_command(fetch_cmd, pipelines_dir, env)
    )
    if exit_code != 0:
        return (False, f"Git Fetch fehlgeschlagen: {stderr}")
    reset_cmd = ["git", "reset", "--hard", f"origin/{branch}"]
    exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
        _executor, lambda: _run_git_command(reset_cmd, pipelines_dir, env)
    )
    if exit_code != 0:
        return (False, f"Git Reset fehlgeschlagen: {stderr}")
    pull_cmd = ["git", "pull", "origin", branch]
    exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
        _executor, lambda: _run_git_command(pull_cmd, pipelines_dir, env)
    )
    if exit_code != 0:
        return (False, f"Git Pull fehlgeschlagen: {stderr}")
    return (True, f"Git Pull erfolgreich: {stdout.strip()}")


def get_required_python_versions() -> Set[str]:
    """Sammelt alle von Pipelines benötigten Python-Versionen."""
    discovered = discover_pipelines(force_refresh=True)
    return {p.get_python_version() for p in discovered}


def ensure_python_version(version: str) -> None:
    """
    Stellt sicher, dass die angegebene Python-Version in UV_PYTHON_INSTALL_DIR
    installiert ist (idempotent). Wird z. B. vor einem Run aufgerufen, damit
    Pipelines mit nicht-Standard-Python auch ohne vorherigen Sync funktionieren.
    """
    if not version or not str(version).strip():
        return
    _ensure_python_versions({str(version).strip()})


def _ensure_python_versions(versions: Set[str]) -> None:
    """Installiert die angegebenen Python-Versionen via uv python install."""
    if not versions:
        return
    env = {
        **os.environ.copy(),
        "UV_PYTHON_INSTALL_DIR": str(config.UV_PYTHON_INSTALL_DIR),
        "UV_CACHE_DIR": str(config.UV_CACHE_DIR),
    }
    for v in sorted(versions):
        try:
            result = subprocess.run(
                ["uv", "python", "install", v],
                capture_output=True, text=True, timeout=300, env=env,
            )
            if result.returncode == 0:
                logger.info("uv python install %s ok", v)
            else:
                logger.warning("uv python install %s fehlgeschlagen: %s", v, result.stderr or result.stdout or "")
        except subprocess.TimeoutExpired:
            logger.warning("uv python install %s Timeout", v)
        except Exception as e:
            logger.warning("uv python install %s Fehler: %s", v, e)


async def _run_python_preheat(session: Session) -> Dict[str, Dict[str, Any]]:
    """Führt Python-Preheating aus: uv python install + uv pip compile für jede Pipeline mit requirements.txt."""
    pre_heat_results: Dict[str, Dict[str, Any]] = {}
    versions = get_required_python_versions()
    if versions:
        await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: _ensure_python_versions(versions)
        )
    discovered = discover_pipelines(force_refresh=True)
    logger.info("Gefundene Pipelines für Pre-Heating: %d", len(discovered))
    requirements_count = 0
    for p in discovered:
        req = p.path / "requirements.txt"
        if not req.exists() or not req.is_file():
            continue
        requirements_count += 1
        ok, msg = await _pre_heat_pipeline(p.name, req, p.get_python_version(), session)
        pre_heat_results[p.name] = {"success": ok, "message": msg}
    logger.info("Requirements.txt Dateien gefunden: %d (von %d Pipelines)", requirements_count, len(discovered))
    return pre_heat_results


async def _pre_heat_pipeline(
    pipeline_name: str, requirements_path: Path, python_version: str, session: Session
) -> Tuple[bool, str]:
    """Pre-Heating für eine Pipeline (Lock-File + Managed Environment)."""
    try:
        env = {
            **os.environ.copy(),
            "UV_CACHE_DIR": str(config.UV_CACHE_DIR),
            "UV_PYTHON_INSTALL_DIR": str(config.UV_PYTHON_INSTALL_DIR),
            "UV_LINK_MODE": "copy",
        }
        lock_file_path = requirements_path.parent / "requirements.txt.lock"
        compile_cmd = [
            "uv", "pip", "compile", "--python", python_version,
            str(requirements_path), "-o", str(lock_file_path),
        ]
        compile_result = await asyncio.get_running_loop().run_in_executor(
            _executor,
            lambda: subprocess.run(
                compile_cmd, cwd=requirements_path.parent,
                capture_output=True, text=True, timeout=600, env=env,
            ),
        )
        if compile_result.returncode != 0:
            error_msg = f"Pre-Heating Lock-File-Erstellung fehlgeschlagen für {pipeline_name}: {compile_result.stderr or compile_result.stdout or ''}"
            logger.warning(error_msg)
            return (False, error_msg)
        pipeline_dir = requirements_path.parent
        app_path = Path("/app")
        temp_app_created = False
        try:
            if not app_path.exists():
                app_path.symlink_to(pipeline_dir)
                temp_app_created = True
                logger.debug("Temporärer symlink /app -> %s erstellt für Pre-Heating", pipeline_dir)
            elif app_path.is_symlink():
                if app_path.resolve() != pipeline_dir.resolve():
                    lock_file_absolute = str(lock_file_path.resolve())
                else:
                    lock_file_absolute = "/app/requirements.txt.lock"
            else:
                lock_file_absolute = str(lock_file_path.resolve())
            if not temp_app_created and (not app_path.exists() or (app_path.is_symlink() and app_path.resolve() == pipeline_dir.resolve())):
                lock_file_absolute = "/app/requirements.txt.lock"
            elif not temp_app_created:
                lock_file_absolute = str(lock_file_path.resolve())
            run_cmd = [
                "uv", "run", "--python", python_version,
                "--with-requirements", lock_file_absolute,
                "python", "-c", "pass",
            ]
            cwd_for_run = app_path if app_path.exists() or temp_app_created else pipeline_dir
            install_result = await asyncio.get_running_loop().run_in_executor(
                _executor,
                lambda: subprocess.run(
                    run_cmd, cwd=str(cwd_for_run),
                    capture_output=True, text=True, timeout=600, env=env,
                ),
            )
        finally:
            if temp_app_created and app_path.is_symlink():
                try:
                    app_path.unlink()
                    logger.debug("Temporärer symlink /app entfernt")
                except Exception as e:
                    logger.warning("Fehler beim Entfernen des temporären symlinks /app: %s", e)
        if install_result.returncode != 0:
            error_msg = f"Pre-Heating Installation fehlgeschlagen für {pipeline_name}: {install_result.stderr or install_result.stdout or ''}"
            logger.warning(error_msg)
            return (False, error_msg)
        pipeline = session.get(Pipeline, pipeline_name)
        if pipeline:
            pipeline.last_cache_warmup = datetime.now(timezone.utc)
            session.add(pipeline)
            session.commit()
        else:
            pipeline = Pipeline(
                pipeline_name=pipeline_name,
                has_requirements=True,
                last_cache_warmup=datetime.now(timezone.utc),
            )
            session.add(pipeline)
            session.commit()
        return (True, f"Pre-Heating erfolgreich für {pipeline_name}")
    except subprocess.TimeoutExpired:
        return (False, f"Pre-Heating Timeout für {pipeline_name}")
    except Exception as e:
        logger.error("Fehler beim Pre-Heating für %s: %s", pipeline_name, e)
        return (False, str(e))


async def run_pre_heat_at_startup() -> None:
    """UV Pre-Heating beim API-Start (Hintergrund-Task)."""
    if not config.UV_PRE_HEAT:
        return
    try:
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        try:
            logger.info("Starte UV Pre-Heating beim Start (Python-Install + pip compile/install)")
            pre_heat_results = await _run_python_preheat(session)
            ok = sum(1 for v in pre_heat_results.values() if v.get("success"))
            fail = len(pre_heat_results) - ok
            total_pipelines = len(discover_pipelines(force_refresh=False))
            logger.info(
                "UV Pre-Heating beim Start abgeschlossen: %d ok, %d fehlgeschlagen (von %d Pipelines insgesamt, %d mit requirements.txt)",
                ok, fail, total_pipelines, len(pre_heat_results),
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning("UV Pre-Heating beim Start fehlgeschlagen: %s", e)


async def sync_pipelines(
    branch: Optional[str] = None,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Führt Git-Sync mit UV Pre-Heating aus."""
    if branch is None:
        branch = config.GIT_BRANCH
    if session is None:
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    try:
        async with _sync_lock:
            pipelines_dir = config.PIPELINES_DIR
            sync_start_time = datetime.now(timezone.utc)
            logger.info("Starte Git Pull für Branch: %s", branch)
            await _write_sync_log({"event": "sync_started", "branch": branch, "status": "started"})
            success, message = await _git_pull(branch, pipelines_dir)
            if not success:
                await _write_sync_log({"event": "sync_failed", "branch": branch, "status": "failed", "error": message})
                raise RuntimeError(f"Git Pull fehlgeschlagen: {message}")
            logger.info("Git Pull erfolgreich: %s", message)
            invalidate_cache()
            discovered_pipelines = discover_pipelines(force_refresh=True)
            from app.services.scheduler import sync_scheduler_jobs_from_pipeline_json
            sync_scheduler_jobs_from_pipeline_json(session)
            pre_heat_results: Dict[str, Dict[str, Any]] = {}
            if config.UV_PRE_HEAT:
                logger.info("Starte UV Pre-Heating (Python-Install + pip compile für requirements.txt)")
                pre_heat_results = await _run_python_preheat(session)
                for name, res in pre_heat_results.items():
                    if res.get("success"):
                        logger.info("Pre-Heating erfolgreich für %s", name)
                    else:
                        logger.warning("Pre-Heating fehlgeschlagen für %s: %s", name, res.get("message", ""))
            sync_end_time = datetime.now(timezone.utc)
            sync_duration = (sync_end_time - sync_start_time).total_seconds()
            await _write_sync_log({
                "event": "sync_completed", "branch": branch, "status": "success",
                "duration_seconds": sync_duration, "pipelines_cached": list(pre_heat_results.keys()),
                "pre_heat_results": pre_heat_results,
            })
            try:
                pipelines_pre_heated = sum(1 for v in pre_heat_results.values() if v.get("success"))
                pre_heat_failures = sum(1 for v in pre_heat_results.values() if not v.get("success"))
                track_sync_completed(
                    session, branch, sync_duration,
                    len(discovered_pipelines), pipelines_pre_heated, pre_heat_failures,
                )
            except Exception:
                pass
            return {
                "success": True, "message": "Git-Sync erfolgreich abgeschlossen",
                "branch": branch, "timestamp": datetime.now(timezone.utc).isoformat(),
                "pipelines_discovered": len(discovered_pipelines), "pre_heat_results": pre_heat_results,
            }
    except RuntimeError:
        raise
    except Exception as e:
        error_msg = f"Fehler beim Git-Sync: {e}"
        logger.error(error_msg, exc_info=True)
        em = (error_msg or "").lower()
        if "git pull" in em or "fetch" in em or "reset" in em:
            error_type = "fetch"
        elif "pre-heating" in em or "pre_heat" in em:
            error_type = "pre_heat"
        else:
            error_type = "other"
        try:
            track_sync_failed(session, branch, error_type)
        except Exception:
            pass
        try:
            await _write_sync_log({"event": "sync_failed", "branch": branch, "status": "failed", "error": error_msg})
        except Exception:
            pass
        return {
            "success": False, "message": error_msg,
            "branch": branch, "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        if close_session:
            session.close()


async def get_sync_status() -> Dict[str, Any]:
    """Gibt Git-Status-Informationen zurück."""
    pipelines_dir = config.PIPELINES_DIR
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return {"is_git_repo": False, "message": "Pipelines-Verzeichnis ist kein Git-Repository"}
    try:
        branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: _run_git_command(branch_cmd, pipelines_dir)
        )
        current_branch = stdout.strip() if exit_code == 0 else "unknown"
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: _run_git_command(remote_url_cmd, pipelines_dir)
        )
        remote_url = stdout.strip() if exit_code == 0 else None
        last_commit_cmd = ["git", "log", "-1", "--format=%H|%s|%ai", "HEAD"]
        exit_code, stdout, stderr = await asyncio.get_running_loop().run_in_executor(
            _executor, lambda: _run_git_command(last_commit_cmd, pipelines_dir)
        )
        last_commit = None
        if exit_code == 0 and stdout.strip():
            parts = stdout.strip().split("|")
            if len(parts) == 3:
                last_commit = {"hash": parts[0], "message": parts[1], "date": parts[2]}
        discovered_pipelines = discover_pipelines()
        pipelines_with_requirements = sum(1 for p in discovered_pipelines if p.has_requirements)
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        try:
            pre_heated_pipelines = []
            for pipeline in discovered_pipelines:
                if pipeline.has_requirements:
                    db_pipeline = session.get(Pipeline, pipeline.name)
                    if db_pipeline and db_pipeline.last_cache_warmup:
                        pre_heated_pipelines.append({
                            "name": pipeline.name,
                            "last_cache_warmup": db_pipeline.last_cache_warmup.isoformat(),
                        })
        finally:
            session.close()
        return {
            "is_git_repo": True, "current_branch": current_branch, "remote_url": remote_url,
            "last_commit": last_commit, "pipelines_discovered": len(discovered_pipelines),
            "pipelines_with_requirements": pipelines_with_requirements,
            "pre_heated_pipelines": pre_heated_pipelines, "uv_pre_heat_enabled": config.UV_PRE_HEAT,
        }
    except Exception as e:
        logger.error("Fehler beim Abrufen des Git-Status: %s", e)
        return {"is_git_repo": True, "error": str(e)}
