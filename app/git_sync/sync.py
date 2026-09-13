"""
Git-Sync: Pull, Pre-Heating, Sync-Status.
"""

import asyncio
import os
import re
import shutil
import subprocess
import logging
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List, Set
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from sqlmodel import Session

from app.core.config import config
from app.core.python_version import UnsafePythonVersionError, ensure_safe_python_version
from app.models import Pipeline
from app.services.pipeline_discovery import discover_pipelines, invalidate_cache

from app.git_sync.sync_log import _write_sync_log
from app.services.git_sync_repo_config import get_sync_repo_config

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Gehärtete uv-Aufrufe im Orchestrator
#
# Pre-Heating verarbeitet die requirements.txt aus dem Pipeline-Repository. Diese
# Datei ist nicht vertrauenswürdig – wer ins Repo committen darf, bestimmt ihren
# Inhalt. Sie wird aber im Orchestrator-Prozess verarbeitet, nicht im isolierten
# Worker-Container. Ohne die folgenden Schranken wäre das eine Codeausführung:
#
#   * sdist-Build     -> setup.py / PEP-517-Backend des Pakets läuft als
#                        Orchestrator-Prozess. Verhindert durch --no-build.
#   * Projekt-Modus   -> `uv run` würde ein pyproject.toml im Pipeline-Verzeichnis
#                        als Projekt bauen und installieren. Verhindert durch
#                        --no-project.
#   * uv-Konfiguration -> uv.toml / [tool.uv] im Pipeline-Verzeichnis (und in
#                        dessen Eltern) kann z. B. index-url umbiegen.
#                        Verhindert durch UV_NO_CONFIG=1 plus neutralem cwd.
#
# Das Entpacken eines Wheels führt im Gegensatz zum sdist-Build keinen Paket-Code
# aus – deshalb ist "nur Wheels" die Grenze, an der das Pre-Heating sicher ist.
# --------------------------------------------------------------------------- #

#: Hinweis, der an uv-Fehlermeldungen angehängt wird, solange --no-build aktiv ist.
_NO_BUILD_HINT = (
    "Hinweis: Pre-Heating baut aus Sicherheitsgründen keine Source-Distributions "
    "(sdists). Fehlt für ein Paket ein Wheel, wird diese Pipeline nicht vorgewärmt – "
    "sie läuft weiterhin, der Build passiert dann im isolierten Worker-Container. "
    "Siehe UV_ALLOW_SOURCE_BUILDS in .env.example."
)


def _uv_env() -> Dict[str, str]:
    """
    Environment für uv-Subprozesse des Orchestrators.

    UV_NO_CONFIG=1 lässt uv jede uv.toml / [tool.uv]-Sektion ignorieren. Ohne das
    würde uv beim Auflösen die Konfiguration im (vom Repository kontrollierten)
    Arbeitsverzeichnis und dessen Eltern einlesen und z. B. einen fremden
    index-url akzeptieren.
    """
    return {
        **os.environ.copy(),
        "UV_CACHE_DIR": str(config.UV_CACHE_DIR),
        "UV_PYTHON_INSTALL_DIR": str(config.UV_PYTHON_INSTALL_DIR),
        "UV_LINK_MODE": "copy",
        "UV_NO_CONFIG": "1",
    }


def _uv_build_args() -> List[str]:
    """
    Argumente, die uv sdist-Builds im Orchestrator verbieten.

    Leer, wenn UV_ALLOW_SOURCE_BUILDS ausdrücklich gesetzt ist – dann vertraut der
    Betreiber dem Pipeline-Repository bewusst wie dem eigenen Code.
    """
    if config.UV_ALLOW_SOURCE_BUILDS:
        return []
    return ["--no-build"]


#: Include-Direktive in einer requirements.txt: "-r base.txt", "--constraint x.txt".
_REQUIREMENTS_INCLUDE_PATTERN = re.compile(
    r"^\s*(?:-r|--requirement|-c|--constraint)(?:[=\s]+|(?<=-r)|(?<=-c))(\S+)"
)


def _reject_untrusted_requirement_sources(pipeline_dir: Path, *names: str) -> Optional[str]:
    """
    Stellt sicher, dass uv beim Pre-Heating nur Dateien der eigenen Pipeline liest.

    Zwei Wege führen sonst aus dem Pipeline-Verzeichnis heraus, beide allein durch
    einen Commit ins Repository:

    * Symlink — Git überträgt ihn unverändert, das Pipeline-Verzeichnis ist im
      Orchestrator gemountet.
    * Include — `-r ../../.env` in der requirements.txt; uv löst solche Verweise
      relativ zur einschliessenden Datei auf, nicht zum Arbeitsverzeichnis.

    Beides ist ein Leseprimitiv auf Orchestrator-Dateien: uv zitiert die erste
    unparsbare Zeile der gelesenen Datei in seiner Fehlermeldung, und die landet
    über _uv_failure_message im Sync-Log und in der UI. Beim Lock-File kommt
    hinzu, dass uv ein parsebares Ziel mit dem erzeugten Lock-File überschreibt.

    Includes werden transitiv verfolgt: eine erlaubte base.txt darf ihrerseits
    nicht nach aussen zeigen.

    Returns:
        None wenn alles unbedenklich ist, sonst die Fehlermeldung.
    """
    directory = pipeline_dir.resolve()
    pending = [pipeline_dir / name for name in names]
    seen: Set[Path] = set()

    while pending:
        candidate = pending.pop()
        if candidate.is_symlink():
            return (
                f"{candidate.name} ist ein Symlink. Pre-Heating verarbeitet nur echte "
                "Dateien im Pipeline-Verzeichnis, damit ein Repository nicht auf "
                "Dateien des Orchestrators zeigen kann."
            )
        try:
            resolved = candidate.resolve()
            resolved.relative_to(directory)
        except ValueError:
            return (
                f"{candidate.name} verweist mit {candidate} aus dem Pipeline-Verzeichnis "
                f"{directory} heraus. Pre-Heating liest nur Dateien der eigenen Pipeline."
            )
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.debug("Requirements-Datei %s nicht lesbar: %s", resolved, e)
            continue
        for line in content.splitlines():
            match = _REQUIREMENTS_INCLUDE_PATTERN.match(line)
            if match:
                pending.append(resolved.parent / match.group(1))

    return None


def _uv_failure_message(prefix: str, result: subprocess.CompletedProcess) -> str:
    """Baut eine Fehlermeldung aus uv-Output und ergänzt den --no-build-Hinweis."""
    detail = (result.stderr or result.stdout or "").strip()
    message = f"{prefix}: {detail}" if detail else prefix
    if not config.UV_ALLOW_SOURCE_BUILDS:
        message = f"{message}\n{_NO_BUILD_HINT}"
    return message


def _is_ssh_url(url: str) -> bool:
    """True wenn URL SSH-Format hat (git@... oder ssh://...)."""
    u = (url or "").strip()
    return u.startswith("git@") or u.startswith("ssh://")


@contextmanager
def _ssh_key_env(deploy_key: str):
    """Erstellt eine temporäre Key-Datei und liefert ein Env-Dict mit GIT_SSH_COMMAND. Löscht die Datei danach."""
    fd = None
    key_path = None
    kh_path = None
    try:
        fd, path = tempfile.mkstemp(prefix="fastflow_deploy_key_", suffix=".key")
        key_content = deploy_key.encode() if isinstance(deploy_key, str) else deploy_key
        os.write(fd, key_content)
        os.close(fd)
        fd = None
        key_path = Path(path)
        key_path.chmod(0o600)
        env = os.environ.copy()
        if config.GIT_SSH_KNOWN_HOSTS:
            fd2, kh = tempfile.mkstemp(prefix="fastflow_known_hosts_")
            kh_content = config.GIT_SSH_KNOWN_HOSTS.encode() if isinstance(config.GIT_SSH_KNOWN_HOSTS, str) else config.GIT_SSH_KNOWN_HOSTS
            os.write(fd2, kh_content)
            os.close(fd2)
            kh_path = Path(kh)
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o StrictHostKeyChecking=yes -o UserKnownHostsFile={kh_path}"
            )
        else:
            persisted_known_hosts = config.DATA_DIR / "ssh_known_hosts"
            persisted_known_hosts.parent.mkdir(parents=True, exist_ok=True)
            if not persisted_known_hosts.exists():
                persisted_known_hosts.touch(mode=0o600)
            logger.warning(
                "GIT_SSH_KNOWN_HOSTS nicht gesetzt — Host-Key wird beim ersten Connect "
                "in %s gepinnt (TOFU) und danach bei jedem Sync verifiziert. "
                "Setze GIT_SSH_KNOWN_HOSTS für explizit vorab konfigurierte Host-Keys.",
                persisted_known_hosts,
            )
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new "
                f"-o UserKnownHostsFile={persisted_known_hosts}"
            )
        yield env
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if key_path is not None and key_path.exists():
            try:
                key_path.unlink()
            except OSError:
                pass
        if kh_path is not None and kh_path.exists():
            try:
                kh_path.unlink()
            except OSError:
                pass

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


def get_current_git_info(pipelines_dir: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Liest aktuellen Git-HEAD im Pipeline-Repo (SHA, Branch, Commit-Message).

    Wird beim Anlegen eines Pipeline-Runs aufgerufen, um die Version zu speichern.
    Returns (git_sha, git_branch, git_commit_message); bei Fehlern (None, None, None).
    """
    if not (pipelines_dir / ".git").exists():
        return (None, None, None)
    try:
        sha_cmd = ["git", "rev-parse", "HEAD"]
        exit_code, stdout, _ = _run_git_command(sha_cmd, pipelines_dir)
        git_sha = stdout.strip() if exit_code == 0 and stdout.strip() else None
        branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        exit_code, stdout, _ = _run_git_command(branch_cmd, pipelines_dir)
        git_branch = stdout.strip() if exit_code == 0 and stdout.strip() else None
        msg_cmd = ["git", "log", "-1", "--format=%s", "HEAD"]
        exit_code, stdout, _ = _run_git_command(msg_cmd, pipelines_dir)
        git_commit_message = stdout.strip() if exit_code == 0 and stdout.strip() else None
        return (git_sha, git_branch, git_commit_message)
    except Exception as e:
        logger.debug("get_current_git_info: %s", e)
        return (None, None, None)


def _build_auth_url(repo_url: str, token: Optional[str]) -> str:
    """Baut HTTPS-URL mit Token für Clone/Pull (x-access-token für GitHub-kompatibel)."""
    if not token or not repo_url.strip():
        return repo_url.strip()
    url = repo_url.strip()
    if "x-access-token" in url or (url.startswith("https://") and "@" in url.split("://", 1)[1]):
        return url
    if url.startswith("https://"):
        rest = url.split("://", 1)[1]
        return f"https://x-access-token:{token}@{rest}"
    if url.startswith("http://"):
        rest = url.split("://", 1)[1]
        return f"http://x-access-token:{token}@{rest}"
    return url


def clear_pipelines_directory() -> Tuple[bool, str]:
    """
    Löscht den gesamten Inhalt des Pipeline-Verzeichnisses (inkl. .git).
    Danach kann ein neues Repo per Sync geklont werden.
    Returns (success, message).
    """
    pipelines_dir = config.PIPELINES_DIR
    try:
        if not pipelines_dir.exists():
            pipelines_dir.mkdir(parents=True, exist_ok=True)
            return (True, "Verzeichnis war leer oder wurde erstellt.")
        for item in pipelines_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        invalidate_cache()
        return (True, "Pipelines-Verzeichnis wurde geleert.")
    except OSError as e:
        logger.exception("Fehler beim Leeren des Pipeline-Verzeichnisses")
        return (False, str(e))


def _ensure_repo_cloned(
    repo_url: str,
    token: Optional[str],
    deploy_key: Optional[str],
    branch: str,
    pipelines_dir: Path,
) -> Tuple[bool, str]:
    """Führt initialen Git-Clone aus, wenn pipelines_dir leer ist. Returns (success, message)."""
    pipelines_dir.mkdir(parents=True, exist_ok=True)
    if (pipelines_dir / ".git").exists():
        return (True, "")
    try:
        existing = list(pipelines_dir.iterdir())
        if existing:
            return (False, "Pipelines-Verzeichnis ist nicht leer und kein Git-Repository")
    except OSError as e:
        return (False, f"Verzeichnis nicht lesbar: {e}")
    if deploy_key:
        clone_url = repo_url.strip()
        with _ssh_key_env(deploy_key) as env:
            cmd = ["git", "clone", "--branch", branch, clone_url, str(pipelines_dir)]
            exit_code, stdout, stderr = _run_git_command(cmd, pipelines_dir.parent, env)
    else:
        auth_url = _build_auth_url(repo_url, token)
        cmd = ["git", "clone", "--branch", branch, auth_url, str(pipelines_dir)]
        exit_code, stdout, stderr = _run_git_command(cmd, pipelines_dir.parent)
    if exit_code != 0:
        return (False, f"Git Clone fehlgeschlagen: {stderr or stdout}")
    return (True, "")


async def _git_pull(
    branch: str,
    pipelines_dir: Path,
    sync_token: Optional[str] = None,
    sync_deploy_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """Führt Git Pull aus (mit optionalem Token oder Deploy Key für private Repos). Retry bis zu 3 Versuche."""
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return (False, "Pipelines-Verzeichnis ist kein Git-Repository")
    last_msg = ""
    for attempt in range(1, 4):
        success, msg = await _git_pull_once(
            branch, pipelines_dir, sync_token=sync_token, sync_deploy_key=sync_deploy_key
        )
        if success:
            return (True, msg)
        last_msg = msg
        if attempt < 3:
            wait = min(30, 2 ** attempt)
            logger.warning("Git Pull Versuch %d/3 fehlgeschlagen: %s. Retry in %ds.", attempt, msg, wait)
            await asyncio.sleep(wait)
    return (False, last_msg)


async def _git_pull_once(
    branch: str,
    pipelines_dir: Path,
    sync_token: Optional[str] = None,
    sync_deploy_key: Optional[str] = None,
) -> Tuple[bool, str]:
    """Einzelner Git-Pull-Versuch (Fetch, Reset, Pull)."""
    env = None
    if sync_deploy_key:
        # SSH: Env mit GIT_SSH_COMMAND wird pro Aufruf erzeugt; wir müssen die Key-Datei
        # für die Dauer aller Git-Befehle behalten. Da _git_pull_once synchron in einem
        # Executor läuft, können wir hier with _ssh_key_env nutzen.
        with _ssh_key_env(sync_deploy_key) as env:
            return await _git_pull_once_with_env(branch, pipelines_dir, sync_token, env)
    return await _git_pull_once_with_env(branch, pipelines_dir, sync_token, None)


async def _git_pull_once_with_env(
    branch: str,
    pipelines_dir: Path,
    sync_token: Optional[str],
    env: Optional[Dict[str, str]],
) -> Tuple[bool, str]:
    """Pull-Logik mit optionalem env (für SSH oder HTTPS mit Token-URL-Update)."""
    if sync_token and not env:
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = _run_git_command(remote_url_cmd, pipelines_dir)
        if exit_code == 0:
            remote_url = stdout.strip()
            if "x-access-token" not in remote_url and remote_url.startswith("https://"):
                parts = remote_url.split("://")
                if len(parts) == 2:
                    new_url = f"https://x-access-token:{sync_token}@{parts[1]}"
                    set_url_cmd = ["git", "config", "remote.origin.url", new_url]
                    _run_git_command(set_url_cmd, pipelines_dir)
            elif "x-access-token" not in remote_url and remote_url.startswith("http://"):
                parts = remote_url.split("://")
                if len(parts) == 2:
                    new_url = f"http://x-access-token:{sync_token}@{parts[1]}"
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


# Serialisiert `uv python install` innerhalb des Orchestrators. uv sperrt
# UV_PYTHON_INSTALL_DIR über ein flock auf <dir>/.lock; parallele Installs
# blockieren sich gegenseitig und laufen auf Netz-/FUSE-Dateisystemen in
# "Could not acquire lock ... (os error 5)".
_python_install_lock = threading.Lock()


def is_python_version_installed(version: str) -> bool:
    """
    Prüft ohne uv-Subprozess, ob eine Python-Version bereits in
    UV_PYTHON_INSTALL_DIR liegt.

    uv legt managed Installs als `cpython-<version>-<platform>` ab. Geprüft wird
    auf ein vorhandenes `bin/python3`, damit abgebrochene Downloads nicht als
    fertige Installation zählen.
    """
    version = (version or "").strip()
    if not version:
        return False
    install_dir = config.UV_PYTHON_INSTALL_DIR
    try:
        entries = list(install_dir.iterdir())
    except OSError:
        return False

    # "3.11" darf nicht auf "cpython-3.1.x" matchen -> Trennzeichen mitprüfen
    prefix = f"cpython-{version}"
    for entry in entries:
        name = entry.name
        if not name.startswith(prefix):
            continue
        if len(name) > len(prefix) and name[len(prefix)] not in (".", "-", "+"):
            continue
        if (entry / "bin" / "python3").exists():
            return True
    return False


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
    """
    Installiert die angegebenen Python-Versionen via uv python install.

    Bereits installierte Versionen werden per Dateisystem-Check übersprungen,
    damit der Hot-Path (ein Aufruf pro Run) keinen uv-Prozess startet und das
    uv-Lock nicht anfasst. Verbleibende Installs laufen serialisiert.

    Unzulässige Versionsangaben werden verworfen, bevor sie die Kommandozeile
    erreichen: `uv python install <pfad>` würde die angegebene Datei ausführen
    (siehe app.core.python_version).
    """
    if not versions:
        return

    safe_versions: Set[str] = set()
    for raw in versions:
        try:
            safe_versions.add(ensure_safe_python_version(raw))
        except UnsafePythonVersionError as e:
            logger.error("Python-Installation übersprungen: %s", e)
    if not safe_versions:
        return

    pending = sorted(v for v in safe_versions if not is_python_version_installed(v))
    if not pending:
        return

    env = _uv_env()
    for v in pending:
        with _python_install_lock:
            # Erneut prüfen: ein paralleler Aufruf kann die Version inzwischen
            # installiert haben, während wir auf das Lock gewartet haben.
            if is_python_version_installed(v):
                logger.debug("Python %s bereits installiert (während Wartezeit), überspringe", v)
                continue
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
    """
    Pre-Heating für eine Pipeline: Lock-File erzeugen und Wheels in den UV-Cache legen.

    Beide uv-Aufrufe laufen im Orchestrator-Prozess und verarbeiten eine
    requirements.txt aus dem Pipeline-Repository, also nicht vertrauenswürdige
    Eingaben. Sie sind deshalb eingeschnürt: keine sdist-Builds, kein
    Projekt-Modus, keine repo-eigene uv-Konfiguration, neutrales
    Arbeitsverzeichnis, keine Symlinks auf Dateien ausserhalb der Pipeline und
    eine validierte Python-Version.
    """
    try:
        safe_python_version = ensure_safe_python_version(python_version)
    except UnsafePythonVersionError as e:
        error_msg = f"Pre-Heating für {pipeline_name} abgebrochen: {e}"
        logger.error(error_msg)
        return (False, error_msg)

    pipeline_dir = requirements_path.parent
    source_error = _reject_untrusted_requirement_sources(
        pipeline_dir, "requirements.txt", "requirements.txt.lock"
    )
    if source_error:
        error_msg = f"Pre-Heating für {pipeline_name} abgebrochen: {source_error}"
        logger.error(error_msg)
        return (False, error_msg)

    env = _uv_env()
    build_args = _uv_build_args()
    lock_file_path = (pipeline_dir / "requirements.txt.lock").resolve()
    loop = asyncio.get_running_loop()

    def _run_uv(cmd: List[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, timeout=600, env=env
        )

    try:
        # Neutrales Arbeitsverzeichnis: uv sucht uv.toml / pyproject.toml ab dem cwd
        # aufwärts. Im Pipeline-Verzeichnis wäre das eine vom Repository kontrollierte
        # Datei. Relative Verweise *innerhalb* der requirements.txt (z. B. "-r base.txt")
        # löst uv relativ zur Requirements-Datei auf, nicht zum cwd — der Wechsel
        # ändert daran also nichts.
        with tempfile.TemporaryDirectory(prefix="fastflow_preheat_") as work_dir:
            work_path = Path(work_dir)

            compile_cmd = [
                "uv", "pip", "compile",
                "--python", safe_python_version,
                *build_args,
                str(requirements_path.resolve()),
                "-o", str(lock_file_path),
            ]
            compile_result = await loop.run_in_executor(
                _executor, lambda: _run_uv(compile_cmd, work_path)
            )
            if compile_result.returncode != 0:
                error_msg = _uv_failure_message(
                    f"Pre-Heating Lock-File-Erstellung fehlgeschlagen für {pipeline_name}",
                    compile_result,
                )
                logger.warning(error_msg)
                return (False, error_msg)

            # --no-project: ohne das würde uv ein pyproject.toml im Arbeitsverzeichnis
            # als Projekt behandeln, bauen und installieren. Das cwd ist hier zwar
            # bereits neutral, aber diese Absicht gehört explizit in die Kommandozeile
            # und nicht in eine Annahme über das Arbeitsverzeichnis.
            install_cmd = [
                "uv", "run", "--no-project", "--no-config",
                "--python", safe_python_version,
                *build_args,
                "--with-requirements", str(lock_file_path),
                "python", "-c", "pass",
            ]
            install_result = await loop.run_in_executor(
                _executor, lambda: _run_uv(install_cmd, work_path)
            )
            if install_result.returncode != 0:
                error_msg = _uv_failure_message(
                    f"Pre-Heating Installation fehlgeschlagen für {pipeline_name}",
                    install_result,
                )
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
    # Im Testbetrieb nie pre-heaten: `uv pip compile` würde die eingecheckten
    # requirements.txt.lock der echten pipelines/ überschreiben (mit lokalen
    # Host-Pfaden und plattformspezifischen Paketen).
    if config.TESTING or not config.UV_PRE_HEAT:
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
    """Führt Git-Sync mit UV Pre-Heating aus. Gibt sofort zurück wenn bereits ein Sync läuft (already_running)."""
    if branch is None:
        branch = config.GIT_BRANCH
    if session is None:
        from app.core.database import get_session
        session_gen = get_session()
        session = next(session_gen)
        close_session = True
    else:
        close_session = False

    if _sync_lock.locked():
        if close_session:
            session.close()
        return {
            "success": False,
            "message": "Ein Sync läuft bereits. Status unter GET /api/sync/status.",
            "already_running": True,
            "branch": branch,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    try:
        async with _sync_lock:
            pipelines_dir = config.PIPELINES_DIR
            repo_config = get_sync_repo_config(session)
            sync_token: Optional[str] = None
            sync_deploy_key: Optional[str] = None
            if repo_config:
                branch = repo_config.get("branch") or branch
                if _is_ssh_url(repo_config["repo_url"]):
                    sync_deploy_key = repo_config.get("deploy_key")
                else:
                    sync_token = repo_config.get("token")
                git_dir = pipelines_dir / ".git"
                if not git_dir.exists():
                    ok, msg = await asyncio.get_running_loop().run_in_executor(
                        _executor,
                        lambda: _ensure_repo_cloned(
                            repo_config["repo_url"],
                            sync_token,
                            sync_deploy_key,
                            branch,
                            pipelines_dir,
                        ),
                    )
                    if not ok:
                        await _write_sync_log(
                            {"event": "sync_failed", "branch": branch, "status": "failed", "error": msg}
                        )
                        raise RuntimeError(f"Git Clone fehlgeschlagen: {msg}")
            elif not (pipelines_dir / ".git").exists():
                await _write_sync_log(
                    {"event": "sync_failed", "branch": branch, "status": "failed", "error": "Kein Repository konfiguriert"}
                )
                raise RuntimeError(
                    "Kein Repository konfiguriert. Bitte in Sync → Repository URL angeben oder GIT_REPO_URL setzen."
                )
            sync_start_time = datetime.now(timezone.utc)
            logger.info("Starte Git Pull für Branch: %s", branch)
            await _write_sync_log({"event": "sync_started", "branch": branch, "status": "started"})
            success, message = await _git_pull(
                branch, pipelines_dir, sync_token=sync_token, sync_deploy_key=sync_deploy_key
            )
            if not success:
                await _write_sync_log({"event": "sync_failed", "branch": branch, "status": "failed", "error": message})
                raise RuntimeError(f"Git Pull fehlgeschlagen: {message}")
            logger.info("Git Pull erfolgreich: %s", message)
            invalidate_cache()
            discovered_pipelines = discover_pipelines(force_refresh=True)
            from app.services.scheduler import sync_scheduler_jobs_from_pipeline_json, _sync_jobs_from_database
            sync_scheduler_jobs_from_pipeline_json(session)
            _sync_jobs_from_database()  # Sicherstellen, dass alle aktiven DB-Jobs im Scheduler sind
            pre_heat_results: Dict[str, Dict[str, Any]] = {}
            if config.UV_PRE_HEAT:
                logger.info("Starte UV Pre-Heating (Python-Install + pip compile für requirements.txt)")
                pre_heat_results = await _run_python_preheat(session)
                for name, res in pre_heat_results.items():
                    if res.get("success"):
                        logger.info("Pre-Heating erfolgreich für %s", name)
                    else:
                        logger.warning("Pre-Heating fehlgeschlagen für %s: %s", name, res.get("message", ""))
            try:
                from app.services.dependency_audit import run_dependency_audit_on_startup_async
                await run_dependency_audit_on_startup_async()
                logger.info("Dependency-Audit nach Pull abgeschlossen")
            except Exception as audit_err:
                logger.warning("Dependency-Audit nach Pull fehlgeschlagen (Sync gilt als erfolgreich): %s", audit_err)
            sync_end_time = datetime.now(timezone.utc)
            sync_duration = (sync_end_time - sync_start_time).total_seconds()
            await _write_sync_log({
                "event": "sync_completed", "branch": branch, "status": "success",
                "duration_seconds": sync_duration, "pipelines_cached": list(pre_heat_results.keys()),
                "pre_heat_results": pre_heat_results,
            })
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


def test_sync_repo_config(session: Session) -> Tuple[bool, str]:
    """Testet die Sync-Repo-Konfiguration per git ls-remote."""
    cfg = get_sync_repo_config(session)
    if not cfg or not cfg.get("repo_url"):
        return (False, "Keine Repository-URL konfiguriert")
    branch = cfg.get("branch") or "main"
    if _is_ssh_url(cfg["repo_url"]):
        deploy_key = cfg.get("deploy_key")
        if not deploy_key:
            return (False, "Bei SSH-URL muss ein Deploy Key (privater SSH-Key) konfiguriert sein")
        url = cfg["repo_url"].strip()
        with _ssh_key_env(deploy_key) as env:
            cmd = ["git", "ls-remote", "--heads", url, f"refs/heads/{branch}"]
            exit_code, stdout, stderr = _run_git_command(cmd, Path("."), env)
    else:
        url = _build_auth_url(cfg["repo_url"], cfg.get("token"))
        cmd = ["git", "ls-remote", "--heads", url, f"refs/heads/{branch}"]
        exit_code, stdout, stderr = _run_git_command(cmd, Path("."))
    if exit_code != 0:
        return (False, (stderr or stdout or "Unbekannter Fehler").strip())
    return (True, "Verbindung erfolgreich")


def _strip_credentials_from_url(url: str) -> str:
    """Entfernt eingebettete Credentials (user:token@) aus einer Git-Remote-URL."""
    from urllib.parse import urlparse, urlunparse
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            clean = parsed._replace(netloc=parsed.hostname + (f":{parsed.port}" if parsed.port else ""))
            return urlunparse(clean)
    except Exception:
        pass
    return url


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
        if remote_url:
            remote_url = _strip_credentials_from_url(remote_url)
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


def get_pipeline_json_github_url(pipeline_name: str) -> Optional[str]:
    """
    Gibt die GitHub-Blob-URL für die pipeline.json einer Pipeline zurück.

    Ermöglicht Bearbeitung der JSON-Datei direkt auf GitHub.
    Gibt None zurück, wenn kein GitHub-Repository oder die URL nicht ableitbar ist.

    Args:
        pipeline_name: Name der Pipeline (z.B. "test_simple")

    Returns:
        URL wie https://github.com/owner/repo/blob/main/test_simple/pipeline.json oder None
    """
    pipelines_dir = config.PIPELINES_DIR
    git_dir = pipelines_dir / ".git"
    if not git_dir.exists():
        return None
    try:
        # Branch und Remote-URL abrufen (synchron, da diese Funktion von API aufgerufen wird)
        branch_cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
        exit_code, stdout, stderr = _run_git_command(branch_cmd, pipelines_dir)
        branch = stdout.strip() if exit_code == 0 else config.GIT_BRANCH
        remote_url_cmd = ["git", "config", "remote.origin.url"]
        exit_code, stdout, stderr = _run_git_command(remote_url_cmd, pipelines_dir)
        remote_url = stdout.strip() if exit_code == 0 else None
        if not remote_url:
            return None
        # Remote-URL zu GitHub-Web-URL konvertieren
        # https://github.com/user/repo.git oder https://x-access-token:xxx@github.com/user/repo.git
        # git@github.com:user/repo.git
        url = remote_url
        if "x-access-token:" in url and "@" in url:
            url = url.split("@", 1)[1]
        elif "://" in url and "@" in url.split("://", 1)[1]:
            url = url.split("@", 1)[1]
        url = url.replace(".git", "").rstrip("/")
        if url.startswith("git@"):
            # git@github.com:user/repo -> https://github.com/user/repo
            url = url.replace(":", "/", 1).replace("git@", "https://")
        elif not url.startswith("https://"):
            url = "https://" + url
        if "github.com" not in url:
            return None
        path = f"{pipeline_name}/pipeline.json"
        return f"{url}/blob/{branch}/{path}"
    except Exception as e:
        logger.warning("Fehler beim Erstellen der GitHub-URL für %s: %s", pipeline_name, e)
        return None
