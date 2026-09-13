"""
Pipeline-Paket-Abhängigkeiten und Vulnerability-Scanning.

Dieses Modul behandelt requirements.txt und pip-audit pro Pipeline –
nicht FastAPI Depends() / Dependency Injection. Verwendet von der
Dependencies-API und dem Frontend.

- Parst requirements.txt (und optional requirements.txt.lock) pro Pipeline.
- Führt pip-audit für Schwachstellenscans aus.

Der Scan läuft im Orchestrator-Prozess über Dateien aus dem Pipeline-Repository
und damit über nicht vertrauenswürdige Eingaben. Er verzichtet deshalb komplett
auf Dependency-Resolution (siehe _run_pip_audit_sync) — sonst würde pip-audit
Pakete herunterladen und für sdists deren Build-Backend ausführen.
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from app.core.config import config
from app.services.pipeline_discovery import discover_pipelines, get_pipeline as get_discovered_pipeline

logger = logging.getLogger(__name__)

# Pip-audit JSON output: {"dependencies": [{"name": "...", "version": "..."}], "vulnerabilities": [{"id": "...", "fix_versions": [...], "affected_versions": "...", ...}]}
# Or per dependency: vulnerabilities may have "affects" with package name


def _parse_requirements_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse a single requirements.txt line. Returns (name, specifier) or None if skip."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    # Remove inline comments
    if " #" in line:
        line = line.split(" #")[0].strip()
    if not line:
        return None
    # Match package name and optional version specifier (==, >=, <=, ~=, etc.)
    m = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9._-]*)\s*([=<>!~].*)?$", line)
    if not m:
        return None
    name = m.group(1).strip().lower()
    spec = (m.group(2) or "").strip()
    return (name, spec if spec else "any")


def parse_requirements(requirements_path: Path) -> List[Dict[str, str]]:
    """
    Parse requirements.txt into list of {name, specifier}.
    specifier may be "any" if no version specified.
    """
    if not requirements_path.exists() or not requirements_path.is_file():
        return []
    result: List[Dict[str, str]] = []
    try:
        with open(requirements_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_requirements_line(line)
                if parsed:
                    name, specifier = parsed
                    result.append({"name": name, "specifier": specifier})
    except OSError as e:
        logger.warning("Could not read %s: %s", requirements_path, e)
    return result


def _parse_lock_line(line: str) -> Optional[Tuple[str, str]]:
    """Parse a uv lock line 'package==version'. Returns (name, version) or None."""
    line = line.strip()
    if not line or line.startswith("#") or line.startswith(" "):
        return None
    if "==" in line:
        name, _, version = line.partition("==")
        name = name.strip().lower()
        version = version.strip()
        if name and version:
            return (name, version)
    return None


def parse_lock_file(lock_path: Path) -> Dict[str, str]:
    """
    Parse requirements.txt.lock (uv format) into {package_name: resolved_version}.
    Only top-level lines (no leading space) are package lines.
    """
    if not lock_path.exists() or not lock_path.is_file():
        return {}
    result: Dict[str, str] = {}
    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _parse_lock_line(line)
                if parsed:
                    name, version = parsed
                    result[name] = version
    except OSError as e:
        logger.warning("Could not read %s: %s", lock_path, e)
    return result


def get_pipeline_packages(pipeline_name: str) -> List[Dict[str, str]]:
    """
    For a pipeline, return list of packages with name, specifier, and resolved version (if lock exists).
    """
    discovered = get_discovered_pipeline(pipeline_name)
    if not discovered:
        return []
    path = discovered.path
    req_path = path / "requirements.txt"
    lock_path = path / "requirements.txt.lock"
    packages = parse_requirements(req_path)
    resolved = parse_lock_file(lock_path)
    out: List[Dict[str, str]] = []
    for p in packages:
        name = p["name"]
        row: Dict[str, str] = {"name": name, "specifier": p["specifier"]}
        if name in resolved:
            row["version"] = resolved[name]
        else:
            row["version"] = p["specifier"] if p["specifier"] != "any" else "n/a"
        out.append(row)
    return out


class PipAuditResult(NamedTuple):
    """
    Ergebnis eines Schwachstellen-Scans für eine Pipeline.

    unaudited nennt die Pakete, die nicht geprüft werden konnten, weil keine
    exakte Version feststand. Dieses Feld ist kein Beiwerk: ohne es liesse sich
    "keine Schwachstellen gefunden" nicht von "nichts geprüft" unterscheiden.
    """

    vulnerabilities: List[Dict[str, Any]]
    error: Optional[str]
    unaudited: List[str]


#: Exakte Versionsfestlegung ("==1.2.3"). PEP 440 erlaubt neben Ziffern auch
#: Epoche (!), Pre-/Post-/Dev-Segmente und lokale Versionen (+).
_EXACT_PIN_PATTERN = re.compile(r"^==\s*([A-Za-z0-9][A-Za-z0-9._+!-]*)$")


def _exact_pin_version(specifier: str) -> Optional[str]:
    """
    Liefert die Version eines "=="-Specifiers, sonst None.

    Environment-Marker (`; python_version < "3.12"`) und Hash-Anhänge
    (`--hash=sha256:...`) werden abgeschnitten; alles andere (Bereiche, ~=, any)
    gilt als nicht exakt festgelegt.
    """
    head = (specifier or "").split(";", 1)[0].strip()
    if not head:
        return None
    match = _EXACT_PIN_PATTERN.match(head.split()[0])
    return match.group(1) if match else None


def collect_pinned_requirements(requirements_path: Path) -> Tuple[List[str], List[str]]:
    """
    Ermittelt die exakt festgelegten Anforderungen einer Pipeline für den Audit.

    Bevorzugt requirements.txt.lock (vom Pre-Heating erzeugt, vollständig gepinnt
    inklusive transitiver Abhängigkeiten). Ohne Lock-File werden nur die direkten
    Anforderungen mit "=="-Pin übernommen.

    Der Rückgabewert ist bewusst eine Liste normalisierter "name==version"-Zeilen
    und nicht der Pfad zur Original-Datei: pip-audit bekommt damit ausschliesslich
    Daten, die dieses Modul selbst erzeugt hat. Pip-Optionen aus der Repo-Datei
    (--index-url, --find-links, -e, VCS-/URL-Referenzen) erreichen das Werkzeug
    dadurch gar nicht erst.

    Returns:
        (pinned, unaudited): normalisierte Zeilen und Namen ohne exakte Version.
    """
    locked = parse_lock_file(requirements_path.parent / "requirements.txt.lock")
    if locked:
        return [f"{name}=={version}" for name, version in sorted(locked.items())], []

    pinned: List[str] = []
    unaudited: List[str] = []
    for entry in parse_requirements(requirements_path):
        version = _exact_pin_version(entry["specifier"])
        if version:
            pinned.append(f"{entry['name']}=={version}")
        else:
            unaudited.append(entry["name"])
    return pinned, unaudited


def _extract_vulnerabilities(data: Any) -> List[Dict[str, Any]]:
    """
    Normalisiert die JSON-Ausgabe von pip-audit zu einer flachen Vulnerability-Liste.

    pip-audit gibt seit 2.x `{"dependencies": [{"name", "version", "vulns": [...]}]}`
    aus. Ältere und alternative Formate (`{"vulnerabilities": [...]}` sowie
    `{"paket==version": [...]}`) werden weiter unterstützt, damit ein Versions-
    wechsel des Werkzeugs den Scan nicht stillschweigend auf null Funde setzt.
    """
    if not isinstance(data, dict):
        return []

    vulns: List[Dict[str, Any]] = []

    dependencies = data.get("dependencies")
    if isinstance(dependencies, list):
        for dep in dependencies:
            if not isinstance(dep, dict):
                continue
            for item in dep.get("vulns") or []:
                if not isinstance(item, dict):
                    continue
                vulns.append({**item, "name": dep.get("name"), "version": dep.get("version")})

    top_level = data.get("vulnerabilities")
    if isinstance(top_level, list):
        vulns.extend(item for item in top_level if isinstance(item, dict))

    for key, value in data.items():
        # Legacy: der Key ist selbst die Paketangabe ("paket==version"). Bewusst
        # eng auf dieses Muster begrenzt, damit ein künftiger Listen-Schlüssel von
        # pip-audit (z. B. "warnings") nicht als Fundliste gedeutet wird.
        name, separator, version = str(key).partition("==")
        if not separator or not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            entry.setdefault("name", name.strip())
            entry.setdefault("version", version.strip())
            vulns.append(entry)

    return vulns


def _run_pip_audit_sync(requirements_path: Path) -> PipAuditResult:
    """
    Prüft die Abhängigkeiten einer Pipeline mit pip-audit auf bekannte Schwachstellen.

    Sicherheit: pip-audit läuft im Orchestrator-Prozess, die zu prüfende
    requirements.txt stammt aber aus dem Pipeline-Repository. Ohne --no-deps würde
    pip-audit den Abhängigkeitsbaum auflösen, dafür Pakete herunterladen und für
    Source-Distributions deren Build-Backend ausführen — also fremden Code im
    Orchestrator, ausserhalb jeder Container-Isolation.

    Deshalb: --no-deps (keine Auflösung, keine Downloads von Paketen),
    --disable-pip (pip wird gar nicht erst als Resolver herangezogen) und eine
    selbst erzeugte, ausschliesslich aus "name==version" bestehende Eingabedatei
    in einem temporären Verzeichnis.
    """
    pinned, unaudited = collect_pinned_requirements(requirements_path)
    if not pinned:
        # Ohne exakte Versionen gibt es nichts zu prüfen. Kein Subprozess, aber
        # eine ehrliche Antwort: alle Pakete stehen als ungeprüft im Ergebnis.
        return PipAuditResult([], None, unaudited)

    pip_audit_cmd = shutil.which("pip-audit") or shutil.which("pip_audit")
    base_args = [pip_audit_cmd] if pip_audit_cmd else [sys.executable, "-m", "pip_audit"]

    try:
        with tempfile.TemporaryDirectory(prefix="fastflow_audit_") as work_dir:
            audit_input = Path(work_dir) / "requirements.txt"
            audit_input.write_text("\n".join(pinned) + "\n", encoding="utf-8")

            proc = subprocess.run(
                [*base_args, "--no-deps", "--disable-pip", "-r", str(audit_input), "-f", "json"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=work_dir,
            )

        if proc.returncode not in (0, 1):
            # Exit 0 = keine Funde, 1 = Funde; alles andere ist ein echter Fehler.
            return PipAuditResult(
                [], f"pip-audit exited with {proc.returncode}: {proc.stderr or proc.stdout}", unaudited
            )

        out = (proc.stdout or "").strip()
        if not out:
            return PipAuditResult([], None, unaudited)
        return PipAuditResult(_extract_vulnerabilities(json.loads(out)), None, unaudited)

    except subprocess.TimeoutExpired:
        return PipAuditResult([], "pip-audit timeout", unaudited)
    except json.JSONDecodeError as e:
        logger.warning("pip-audit JSON parse error: %s", e)
        return PipAuditResult([], f"Invalid JSON: {e}", unaudited)
    except FileNotFoundError:
        return PipAuditResult([], "pip-audit not installed (pip install pip-audit)", unaudited)
    except OSError as e:
        logger.warning("pip-audit konnte nicht ausgeführt werden: %s", e)
        return PipAuditResult([], str(e), unaudited)
    except Exception as e:
        logger.exception("pip-audit failed: %s", e)
        return PipAuditResult([], str(e), unaudited)


async def run_pip_audit(requirements_path: Path) -> PipAuditResult:
    """Async wrapper for pip-audit (runs in executor)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run_pip_audit_sync, requirements_path)


def get_all_pipelines_dependencies() -> List[Dict[str, Any]]:
    """
    Synchronously get dependencies for all pipelines that have requirements.txt.
    No vulnerability scan (call run_pip_audit per pipeline from API if needed).
    """
    pipelines = discover_pipelines()
    result: List[Dict[str, Any]] = []
    for p in pipelines:
        if not p.has_requirements:
            continue
        packages = get_pipeline_packages(p.name)
        result.append({
            "pipeline": p.name,
            "packages": packages,
        })
    return result
