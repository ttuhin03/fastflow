"""
Git Synchronization Module.

Dieses Modul verwaltet die Git-Synchronisation des Pipeline-Repositories:
- Git Pull mit Branch-Auswahl
- UV Pre-Heating (Dependency-Caching)
- Konflikt-Handling
- GitHub Apps Authentifizierung
"""

import asyncio
import os
import subprocess
import logging
import time
import json
import aiofiles
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Set
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import jwt
import requests
from sqlmodel import Session

from app.analytics import track_sync_completed, track_sync_failed
from app.config import config
from app.models import Pipeline
from app.pipeline_discovery import discover_pipelines, invalidate_cache, get_pipeline

logger = logging.getLogger(__name__)

# Thread Pool für synchrone Git-Operationen
_executor = ThreadPoolExecutor(max_workers=2)

# Git-Sync-Lock (verhindert gleichzeitige Syncs)
_sync_lock = asyncio.Lock()

# GitHub App Token Cache (Token ist 1 Stunde gültig)
_github_token_cache: Optional[Tuple[str, datetime]] = None


def _get_sync_log_file() -> Path:
    """
    Gibt den Pfad zur Sync-Log-Datei zurück.
    
    Returns:
        Path: Pfad zur Sync-Log-Datei
    """
    return config.LOGS_DIR / "sync.log"


async def _write_sync_log(entry: Dict[str, Any]) -> None:
    """
    Schreibt einen Sync-Log-Eintrag in die Log-Datei (JSONL-Format).
    
    Args:
        entry: Dictionary mit Log-Eintrag-Daten
    """
    log_file = _get_sync_log_file()
    
    # Stelle sicher, dass Logs-Verzeichnis existiert
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Timestamp hinzufügen
    entry["timestamp"] = datetime.utcnow().isoformat()
    
    # JSON-Zeile in Datei schreiben (JSONL-Format)
    try:
        async with aiofiles.open(log_file, "a", encoding="utf-8") as f:
            await f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.error(f"Fehler beim Schreiben von Sync-Log: {e}")


async def get_sync_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Liest Sync-Logs aus der Log-Datei.
    
    Args:
        limit: Maximale Anzahl Log-Einträge (Standard: 100)
    
    Returns:
        Liste von Log-Einträgen (neueste zuerst)
    """
    log_file = _get_sync_log_file()
    
    if not log_file.exists():
        return []
    
    try:
        logs = []
        async with aiofiles.open(log_file, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        logs.append(entry)
                    except json.JSONDecodeError:
                        # Ungültige JSON-Zeile ignorieren
                        continue
        
        # Neueste zuerst (reverse)
        logs.reverse()
        
        # Limit anwenden
        return logs[:limit]
        
    except Exception as e:
        logger.error(f"Fehler beim Lesen von Sync-Logs: {e}")
        return []


def test_github_app_token() -> Tuple[bool, str]:
    """
    Testet die GitHub Apps Konfiguration durch Token-Generierung.
    
    Versucht ein Installation Access Token zu generieren ohne Git-Operationen.
    Nützlich zum Validieren der Konfiguration.
    
    Returns:
        Tuple (success: bool, message: str)
    """
    try:
        token = get_github_app_token()
        if token:
            return (True, "GitHub Apps Konfiguration erfolgreich. Token wurde generiert.")
        else:
            return (False, "GitHub Apps ist nicht konfiguriert oder Konfiguration ist unvollständig.")
    except Exception as e:
        return (False, f"Fehler bei Token-Generierung: {str(e)}")


def get_github_app_token() -> Optional[str]:
    """
    Generiert ein GitHub Installation Access Token via GitHub Apps API.
    
    Verwendet JWT (RS256) mit Private Key für Authentifizierung.
    Token wird gecacht (1 Stunde Gültigkeit) um Rate-Limit-Throttling zu vermeiden.
    
    Returns:
        Installation Access Token oder None wenn Konfiguration fehlt
        
    Raises:
        RuntimeError: Wenn Token-Generierung fehlschlägt
    """
    global _github_token_cache
    
    # Prüfe ob GitHub Apps konfiguriert ist
    if not config.GITHUB_APP_ID or not config.GITHUB_INSTALLATION_ID or not config.GITHUB_PRIVATE_KEY_PATH:
        return None
    
    # Prüfe Cache (Token ist 1 Stunde gültig, erneuere 5 Minuten vor Ablauf)
    if _github_token_cache is not None:
        token, expires_at = _github_token_cache
        if datetime.utcnow() < expires_at - timedelta(minutes=5):
            return token
    
    try:
        # Private Key laden
        private_key_path = Path(config.GITHUB_PRIVATE_KEY_PATH)
        if not private_key_path.exists():
            raise RuntimeError(f"GitHub Private Key nicht gefunden: {private_key_path}")
        
        with open(private_key_path, "r") as f:
            private_key = f.read()
        
        # JWT erstellen (RS256, 10 Minuten Gültigkeit)
        now = int(time.time())
        jwt_payload = {
            "iat": now - 60,  # 1 Minute Puffer
            "exp": now + (10 * 60),  # 10 Minuten Gültigkeit
            "iss": config.GITHUB_APP_ID
        }
        
        jwt_token = jwt.encode(jwt_payload, private_key, algorithm="RS256")
        
        # Installation Access Token anfordern
        url = f"https://api.github.com/app/installations/{config.GITHUB_INSTALLATION_ID}/access_tokens"
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        response = requests.post(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        installation_token = data["token"]
        expires_at_str = data.get("expires_at")
        
        # Expires-At parsen (ISO-Format)
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        else:
            # Standard: 1 Stunde (GitHub Standard)
            expires_at = datetime.utcnow() + timedelta(hours=1)
        
        # Cache aktualisieren
        _github_token_cache = (installation_token, expires_at)
        
        logger.info("GitHub Installation Access Token erfolgreich generiert")
        return installation_token
        
    except Exception as e:
        error_msg = f"Fehler bei GitHub App Token-Generierung: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def _run_git_command(cmd: list, cwd: Path, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    """
    Führt einen Git-Befehl aus (synchron).
    
    Args:
        cmd: Git-Befehl als Liste (z.B. ["git", "pull", "origin", "main"])
        cwd: Arbeitsverzeichnis
        env: Optional Environment-Variablen (für GitHub Token)
        
    Returns:
        Tuple (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5 Minuten Timeout
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        logger.error(f"Git-Befehl Timeout: {' '.join(cmd)}")
        return (-1, "", "Timeout: Git-Befehl dauerte länger als 5 Minuten")
    except Exception as e:
        logger.error(f"Fehler beim Ausführen von Git-Befehl: {e}")
        return (-1, "", str(e))


async def _git_pull(branch: str, pipelines_dir: Path) -> Tuple[bool, str]:
    """
    Führt Git Pull aus (mit GitHub Apps Authentifizierung falls konfiguriert).
    
    Args:
        branch: Git-Branch (z.B. "main")
        pipelines_dir: Pfad zum Pipelines-Verzeichnis
        
    Returns:
        Tuple (success, message)
    """
    # Prüfe ob Verzeichnis ein Git-Repository ist
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return (False, "Pipelines-Verzeichnis ist kein Git-Repository")
    
    # GitHub Token abrufen (falls konfiguriert)
    github_token = get_github_app_token()
    
    # Environment-Variablen für Git-Befehle
    env = None
    if github_token:
        # Remote-URL mit Token aktualisieren
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = _run_git_command(remote_url_cmd, pipelines_dir)
        
        if exit_code == 0:
            remote_url = stdout.strip()
            # Prüfe ob URL bereits Token enthält
            if "x-access-token" not in remote_url:
                # URL mit Token aktualisieren
                if remote_url.startswith("https://"):
                    # GitHub URL: https://github.com/owner/repo.git
                    # Konvertiere zu: https://x-access-token:TOKEN@github.com/owner/repo.git
                    parts = remote_url.split("://")
                    if len(parts) == 2:
                        new_url = f"https://x-access-token:{github_token}@{parts[1]}"
                        set_url_cmd = ["git", "config", "remote.origin.url", new_url]
                        _run_git_command(set_url_cmd, pipelines_dir)
    
    # Git Fetch
    fetch_cmd = ["git", "fetch", "origin", branch]
    exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
        _executor,
        lambda: _run_git_command(fetch_cmd, pipelines_dir, env)
    )
    
    if exit_code != 0:
        return (False, f"Git Fetch fehlgeschlagen: {stderr}")
    
    # Git Reset --hard (Remote-Version übernehmen, Konflikte lösen)
    reset_cmd = ["git", "reset", "--hard", f"origin/{branch}"]
    exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
        _executor,
        lambda: _run_git_command(reset_cmd, pipelines_dir, env)
    )
    
    if exit_code != 0:
        return (False, f"Git Reset fehlgeschlagen: {stderr}")
    
    # Git Pull (zusätzlich, um sicherzustellen dass alles aktuell ist)
    pull_cmd = ["git", "pull", "origin", branch]
    exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
        _executor,
        lambda: _run_git_command(pull_cmd, pipelines_dir, env)
    )
    
    if exit_code != 0:
        return (False, f"Git Pull fehlgeschlagen: {stderr}")
    
    return (True, f"Git Pull erfolgreich: {stdout.strip()}")


def get_required_python_versions() -> Set[str]:
    """
    Sammelt alle von Pipelines benötigten Python-Versionen.
    
    Returns:
        Set von Versions-Strings (z.B. {"3.11", "3.12"}).
    """
    discovered = discover_pipelines(force_refresh=True)
    return {p.get_python_version() for p in discovered}


def _ensure_python_versions(versions: Set[str]) -> None:
    """
    Installiert die angegebenen Python-Versionen via uv python install.
    Fehler werden nur geloggt, der Ablauf bricht nicht ab.
    
    Args:
        versions: Set von Versions-Strings (z.B. {"3.11", "3.12"}).
    """
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
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
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
    """
    Führt das vollständige Python-Preheating aus:
    1) uv python install für alle benötigten Versionen
    2) uv pip compile + uv pip install für jede Pipeline mit requirements.txt
       (erstellt Lock-File und cached alle Pakete)
    
    Returns:
        pre_heat_results: {pipeline_name: {"success": bool, "message": str}}
    """
    pre_heat_results: Dict[str, Dict[str, Any]] = {}
    versions = get_required_python_versions()
    if versions:
        await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: _ensure_python_versions(versions)
        )
    discovered = discover_pipelines(force_refresh=True)
    logger.info("Gefundene Pipelines für Pre-Heating: %d", len(discovered))
    # Verarbeite ALLE Pipelines, nicht nur die mit has_requirements=True
    # (has_requirements könnte veraltet sein oder sich geändert haben)
    requirements_count = 0
    for p in discovered:
        req = p.path / "requirements.txt"
        # Prüfe ob requirements.txt existiert (auch wenn has_requirements=False ist)
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
    """
    Pre-Heating für eine Pipeline (Lock-File-basiert mit Managed Environments).
    
    Erstellt ein Lock-File mit uv pip compile und erstellt dann eine Managed Environment
    mit uv run. uv run erstellt automatisch eine Managed Environment im Cache basierend
    auf dem Hash des Lock-Files. Diese wird beim Pipeline-Run wiederverwendet.
    
    Args:
        pipeline_name: Name der Pipeline
        requirements_path: Pfad zur requirements.txt
        python_version: Python-Version (z.B. "3.11", "3.12")
        session: SQLModel Session
        
    Returns:
        Tuple (success, message)
    """
    try:
        env = {
            **os.environ.copy(),
            "UV_CACHE_DIR": str(config.UV_CACHE_DIR),
            "UV_PYTHON_INSTALL_DIR": str(config.UV_PYTHON_INSTALL_DIR),
            "UV_LINK_MODE": "copy",  # Verhindert Probleme mit Hardlinks in Docker-Volumes
        }
        
        # Schritt 1: Erstelle Lock-File (uv pip compile)
        # Dies fixiert die Versionen und verhindert Re-Resolution beim Run
        lock_file_path = requirements_path.parent / "requirements.txt.lock"
        compile_cmd = [
            "uv", "pip", "compile",
            "--python", python_version,
            str(requirements_path),
            "-o", str(lock_file_path),
        ]
        
        compile_result = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: subprocess.run(
                compile_cmd,
                cwd=requirements_path.parent,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
        )
        
        if compile_result.returncode != 0:
            error_msg = f"Pre-Heating Lock-File-Erstellung fehlgeschlagen für {pipeline_name}: {compile_result.stderr or compile_result.stdout or ''}"
            logger.warning(error_msg)
            return (False, error_msg)
        
        # Schritt 2: Pre-Heat Managed Environment mit uv run
        # WICHTIG: Der Hash für Managed Environments basiert auf dem absoluten Pfad!
        # Beim Run ist der absolute Pfad /app/requirements.txt.lock (cwd=/app, Pipeline nach /app gemountet)
        # Beim Pre-Heating müssen wir den GLEICHEN absoluten Pfad verwenden
        # Lösung: Erstelle temporären symlink /app -> Pipeline-Verzeichnis (nur wenn /app nicht existiert)
        #         Dann verwenden beide den gleichen absoluten Pfad /app/requirements.txt.lock
        
        pipeline_dir = requirements_path.parent
        app_path = Path("/app")
        temp_app_created = False
        
        try:
            # Prüfe ob /app existiert
            if not app_path.exists():
                # Erstelle symlink /app -> Pipeline-Verzeichnis (temporär)
                app_path.symlink_to(pipeline_dir)
                temp_app_created = True
                logger.debug(f"Temporärer symlink /app -> {pipeline_dir} erstellt für Pre-Heating")
            elif app_path.is_symlink():
                # /app ist bereits ein symlink, prüfe ob er auf das richtige Verzeichnis zeigt
                if app_path.resolve() != pipeline_dir.resolve():
                    logger.warning(f"/app existiert bereits als symlink zu {app_path.resolve()}, nicht {pipeline_dir}")
                    # Verwende den tatsächlichen absoluten Pfad (Managed Environment wird nicht wiederverwendet)
                    lock_file_absolute = str(lock_file_path.resolve())
                else:
                    # /app zeigt bereits auf das richtige Verzeichnis
                    lock_file_absolute = "/app/requirements.txt.lock"
            else:
                # /app existiert als Verzeichnis
                logger.warning("/app existiert bereits als Verzeichnis, verwende tatsächlichen absoluten Pfad")
                lock_file_absolute = str(lock_file_path.resolve())
            
            # Wenn /app nicht existiert oder auf das richtige Verzeichnis zeigt, verwende /app/requirements.txt.lock
            if not temp_app_created and (not app_path.exists() or (app_path.is_symlink() and app_path.resolve() == pipeline_dir.resolve())):
                lock_file_absolute = "/app/requirements.txt.lock"
            elif not temp_app_created:
                # Verwende tatsächlichen absoluten Pfad
                lock_file_absolute = str(lock_file_path.resolve())
            
            run_cmd = [
                "uv", "run",
                "--python", python_version,
                "--with-requirements", lock_file_absolute,
                "python", "-c", "pass",  # Dummy-Befehl, nur um Managed Environment zu erstellen
            ]
            
            install_cmd = run_cmd
            
            # WICHTIG: cwd muss /app sein (wie beim Run), damit der absolute Pfad /app/requirements.txt.lock ist
            cwd_for_run = app_path if app_path.exists() or temp_app_created else pipeline_dir
            
            install_result = await asyncio.get_event_loop().run_in_executor(
                _executor,
                lambda: subprocess.run(
                    install_cmd,
                    cwd=str(cwd_for_run),  # /app (wie beim Run) oder Pipeline-Verzeichnis
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=env,
                )
            )
        finally:
            # Cleanup: Entferne temporären symlink
            if temp_app_created and app_path.is_symlink():
                try:
                    app_path.unlink()
                    logger.debug("Temporärer symlink /app entfernt")
                except Exception as e:
                    logger.warning(f"Fehler beim Entfernen des temporären symlinks /app: {e}")
        
        if install_result.returncode != 0:
            error_msg = f"Pre-Heating Installation fehlgeschlagen für {pipeline_name}: {install_result.stderr or install_result.stdout or ''}"
            logger.warning(error_msg)
            return (False, error_msg)
        
        logger.debug(f"Pre-Heating erfolgreich für {pipeline_name}: Lock-File erstellt und Pakete installiert/gecacht")
        
        # Status in DB aktualisieren (last_cache_warmup)
        pipeline = session.get(Pipeline, pipeline_name)
        if pipeline:
            pipeline.last_cache_warmup = datetime.utcnow()
            session.add(pipeline)
            session.commit()
        else:
            # Pipeline existiert noch nicht in DB, erstelle Eintrag
            pipeline = Pipeline(
                pipeline_name=pipeline_name,
                has_requirements=True,
                last_cache_warmup=datetime.utcnow()
            )
            session.add(pipeline)
            session.commit()
        
        return (True, f"Pre-Heating erfolgreich für {pipeline_name}")
        
    except subprocess.TimeoutExpired:
        error_msg = f"Pre-Heating Timeout für {pipeline_name}"
        logger.warning(error_msg)
        return (False, error_msg)
    except Exception as e:
        error_msg = f"Fehler beim Pre-Heating für {pipeline_name}: {e}"
        logger.error(error_msg)
        return (False, error_msg)


async def run_pre_heat_at_startup() -> None:
    """
    UV Pre-Heating beim API-Start (Hintergrund-Task).
    
    Wenn UV_PRE_HEAT aktiviert ist: uv python install für benötigte Versionen,
    dann uv pip compile + uv pip install für jede Pipeline mit requirements.txt.
    Läuft asynchron, blockiert den App-Start nicht.
    """
    if not config.UV_PRE_HEAT:
        return
    try:
        from app.database import get_session
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
                ok, fail, total_pipelines, len(pre_heat_results)
            )
        finally:
            session.close()
    except Exception as e:
        logger.warning("UV Pre-Heating beim Start fehlgeschlagen: %s", e)


async def sync_pipelines(
    branch: Optional[str] = None,
    session: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Führt Git-Sync mit UV Pre-Heating aus.
    
    Args:
        branch: Git-Branch (Standard: config.GIT_BRANCH)
        session: SQLModel Session (optional, wird intern erstellt wenn nicht vorhanden)
        
    Returns:
        Dictionary mit Sync-Status und Pre-Heating-Ergebnissen
        
    Raises:
        RuntimeError: Wenn Git-Sync fehlschlägt
    """
    if branch is None:
        branch = config.GIT_BRANCH
    
    # Session verwenden oder neue erstellen
    if session is None:
        from app.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False
    
    try:
        # Git-Sync-Lock (verhindert gleichzeitige Syncs)
        async with _sync_lock:
            pipelines_dir = config.PIPELINES_DIR
            sync_start_time = datetime.utcnow()
            
            # Step 1: Git Pull
            logger.info(f"Starte Git Pull für Branch: {branch}")
            await _write_sync_log({
                "event": "sync_started",
                "branch": branch,
                "status": "started"
            })
            
            success, message = await _git_pull(branch, pipelines_dir)
            
            if not success:
                await _write_sync_log({
                    "event": "sync_failed",
                    "branch": branch,
                    "status": "failed",
                    "error": message
                })
                raise RuntimeError(f"Git Pull fehlgeschlagen: {message}")
            
            logger.info(f"Git Pull erfolgreich: {message}")
            
            # Step 2: Pipeline-Discovery-Cache invalidieren
            invalidate_cache()
            
            # Step 3: Discovery (Suche nach allen requirements.txt)
            discovered_pipelines = discover_pipelines(force_refresh=True)
            
            # Step 4: UV Pre-Heating (wenn UV_PRE_HEAT aktiviert: uv python install + pip compile)
            pre_heat_results: Dict[str, Dict[str, Any]] = {}
            
            if config.UV_PRE_HEAT:
                logger.info("Starte UV Pre-Heating (Python-Install + pip compile für requirements.txt)")
                pre_heat_results = await _run_python_preheat(session)
                for name, res in pre_heat_results.items():
                    if res.get("success"):
                        logger.info("Pre-Heating erfolgreich für %s", name)
                    else:
                        logger.warning("Pre-Heating fehlgeschlagen für %s: %s", name, res.get("message", ""))
            
            sync_end_time = datetime.utcnow()
            sync_duration = (sync_end_time - sync_start_time).total_seconds()
            
            # Sync-Log schreiben
            await _write_sync_log({
                "event": "sync_completed",
                "branch": branch,
                "status": "success",
                "duration_seconds": sync_duration,
                "pipelines_cached": list(pre_heat_results.keys()),
                "pre_heat_results": pre_heat_results
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
                "success": True,
                "message": "Git-Sync erfolgreich abgeschlossen",
                "branch": branch,
                "timestamp": datetime.utcnow().isoformat(),
                "pipelines_discovered": len(discovered_pipelines),
                "pre_heat_results": pre_heat_results
            }
            
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
        
        # Sync-Log für Fehler schreiben
        try:
            await _write_sync_log({
                "event": "sync_failed",
                "branch": branch,
                "status": "failed",
                "error": error_msg
            })
        except Exception:
            pass  # Log-Fehler nicht weiterwerfen
        
        return {
            "success": False,
            "message": error_msg,
            "branch": branch,
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        if close_session:
            session.close()


async def get_sync_status() -> Dict[str, Any]:
    """
    Gibt Git-Status-Informationen zurück.
    
    Returns:
        Dictionary mit Git-Status (Branch, Commits ahead/behind, etc.)
    """
    pipelines_dir = config.PIPELINES_DIR
    
    # Prüfe ob Verzeichnis ein Git-Repository ist
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return {
            "is_git_repo": False,
            "message": "Pipelines-Verzeichnis ist kein Git-Repository"
        }
    
    try:
        # Aktueller Branch
        branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: _run_git_command(branch_cmd, pipelines_dir)
        )
        
        current_branch = stdout.strip() if exit_code == 0 else "unknown"
        
        # Remote-URL
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: _run_git_command(remote_url_cmd, pipelines_dir)
        )
        
        remote_url = stdout.strip() if exit_code == 0 else None
        
        # Letzter Commit
        last_commit_cmd = ["git", "log", "-1", "--format=%H|%s|%ai", "HEAD"]
        exit_code, stdout, stderr = await asyncio.get_event_loop().run_in_executor(
            _executor,
            lambda: _run_git_command(last_commit_cmd, pipelines_dir)
        )
        
        last_commit = None
        if exit_code == 0 and stdout.strip():
            parts = stdout.strip().split("|")
            if len(parts) == 3:
                last_commit = {
                    "hash": parts[0],
                    "message": parts[1],
                    "date": parts[2]
                }
        
        # Pipeline-Discovery-Info
        discovered_pipelines = discover_pipelines()
        pipelines_with_requirements = sum(1 for p in discovered_pipelines if p.has_requirements)
        
        # Pre-Heating-Status (aus DB)
        from app.database import get_session
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
                            "last_cache_warmup": db_pipeline.last_cache_warmup.isoformat()
                        })
        finally:
            session.close()
        
        return {
            "is_git_repo": True,
            "current_branch": current_branch,
            "remote_url": remote_url,
            "last_commit": last_commit,
            "pipelines_discovered": len(discovered_pipelines),
            "pipelines_with_requirements": pipelines_with_requirements,
            "pre_heated_pipelines": pre_heated_pipelines,
            "uv_pre_heat_enabled": config.UV_PRE_HEAT
        }
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Git-Status: {e}")
        return {
            "is_git_repo": True,
            "error": str(e)
        }
