"""
Pipeline Dependencies & Vulnerability Scanning.

- Parses requirements.txt (and optional requirements.txt.lock) per pipeline.
- Runs pip-audit for vulnerability scanning.
- Used by the Dependencies API and frontend.
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def _run_pip_audit_sync(requirements_path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Run pip-audit -r requirements_path -f json. Returns (vulnerabilities_list, error_message).
    """
    pip_audit_cmd = shutil.which("pip-audit")
    if not pip_audit_cmd:
        pip_audit_cmd = shutil.which("pip_audit")
    if pip_audit_cmd:
        args = [pip_audit_cmd, "-r", str(requirements_path), "-f", "json"]
    else:
        args = ["python3", "-m", "pip_audit", "-r", str(requirements_path), "-f", "json"]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(requirements_path.parent),
        )
        if proc.returncode not in (0, 1):
            return [], f"pip-audit exited with {proc.returncode}: {proc.stderr or proc.stdout}"
        # Exit 0 = no vulns, 1 = vulns found; both output JSON
        out = (proc.stdout or "").strip()
        if not out:
            return [], None
        data = json.loads(out)
        vulns: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            if "vulnerabilities" in data and isinstance(data["vulnerabilities"], list):
                vulns = data["vulnerabilities"]
            else:
                # pip-audit can output { "dependency_name==version": [ { "id": "CVE-...", ... } ], ... }
                for key, val in data.items():
                    if isinstance(val, list) and key not in ("dependencies",):
                        for item in val:
                            if isinstance(item, dict):
                                v = dict(item)
                                if "name" not in v and "==" in str(key):
                                    pkg, _, ver = str(key).partition("==")
                                    v["name"] = pkg.strip()
                                    v["version"] = ver.strip()
                                vulns.append(v)
        return vulns, None
    except subprocess.TimeoutExpired:
        return [], "pip-audit timeout"
    except json.JSONDecodeError as e:
        logger.warning("pip-audit JSON parse error: %s", e)
        return [], f"Invalid JSON: {e}"
    except FileNotFoundError:
        return [], "pip-audit not installed (pip install pip-audit)"
    except Exception as e:
        logger.exception("pip-audit failed: %s", e)
        return [], str(e)


async def run_pip_audit(requirements_path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
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
