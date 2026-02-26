"""
Readiness-Checks für die Fast-Flow-Instanz.

Wird von /ready (Kubernetes Probe) und von GET /api/settings/system-status (UI) genutzt.
Gibt ein einheitliches Checks-Dict und ok-Status zurück.
"""

import logging
import os
import shutil
from typing import Any, Dict, Tuple

from app.core.config import config

logger = logging.getLogger(__name__)


def run_readiness_checks() -> Tuple[Dict[str, Any], bool]:
    """
    Führt alle Readiness-Checks aus (DB, Executor, UV-Cache, Disk, Inodes).

    Returns:
        (checks, ok): checks enthält pro Check einen String („ok“ oder Fehlermeldung)
        bzw. Zahlen (disk_free_gb, inode_total, inode_free). ok ist False, wenn
        mindestens ein Check fehlschlägt.
    """
    checks: Dict[str, Any] = {}
    ok = True

    # DB-Check
    try:
        from app.core.database import engine
        from sqlmodel import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Readiness: DB-Check fehlgeschlagen: %s", e)
        checks["database"] = str(e)
        ok = False

    # Executor-Check: Docker-Proxy oder Kubernetes-API
    if config.PIPELINE_EXECUTOR == "kubernetes":
        try:
            from app.executor.kubernetes_backend import _get_apis
            _get_apis()
            checks["kubernetes"] = "ok"
        except Exception as e:
            checks["kubernetes"] = str(e)
            ok = False
    else:
        try:
            from app.executor import _get_docker_client
            from app.resilience import circuit_docker, CircuitBreakerOpenError
            client = _get_docker_client()
            if client:
                circuit_docker.call(lambda: client.ping())
            checks["docker"] = "ok"
        except CircuitBreakerOpenError as e:
            checks["docker"] = str(e)
            ok = False
        except Exception as e:
            checks["docker"] = str(e)
            ok = False

    # UV-Cache-Volume beschreibbar (kritisch für Pipeline-Runs)
    try:
        uv_cache = config.UV_CACHE_DIR
        uv_cache.mkdir(parents=True, exist_ok=True)
        test_file = uv_cache / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        checks["uv_cache"] = "ok"
    except Exception as e:
        logger.warning("Readiness: UV-Cache-Check fehlgeschlagen: %s", e)
        checks["uv_cache"] = str(e)
        ok = False

    # Disk-Space verfügbar (kritisch für Logs, DB, UV-Cache)
    try:
        disk = shutil.disk_usage(str(config.DATA_DIR))
        free_gb = disk.free / (1024 ** 3)
        checks["disk_free_gb"] = round(free_gb, 2)
        if free_gb < 0.5:  # < 500 MB = nicht ready
            checks["disk"] = f"kritisch: nur {free_gb:.2f} GB frei"
            ok = False
        else:
            checks["disk"] = "ok"
    except Exception as e:
        logger.warning("Readiness: Disk-Check fehlgeschlagen: %s", e)
        checks["disk"] = str(e)
        ok = False

    # Inodes (df -i): oft voll bei vielen kleinen Dateien (Logs, Cache)
    if hasattr(os, "statvfs"):
        try:
            st = os.statvfs(str(config.DATA_DIR))
            inode_total = st.f_files
            inode_free = getattr(st, "f_favail", st.f_ffree)
            inode_used = inode_total - inode_free
            checks["inode_total"] = inode_total
            checks["inode_free"] = inode_free
            inode_pct = (inode_used / inode_total * 100) if inode_total else 0
            if inode_free < 1000 or inode_pct > 95:
                checks["inodes"] = f"kritisch: nur {inode_free} Inodes frei ({inode_pct:.1f}% belegt)"
                ok = False
            else:
                checks["inodes"] = "ok"
        except Exception as e:
            logger.warning("Readiness: Inode-Check fehlgeschlagen: %s", e)
            checks["inodes"] = str(e)
    else:
        checks["inodes"] = "n/a (nur Unix)"

    return checks, ok
