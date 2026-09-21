"""
Readiness-Checks für die Fast-Flow-Instanz.

Wird von /ready (Kubernetes Probe) und von GET /api/settings/system-status (UI) genutzt.
Gibt ein einheitliches Checks-Dict und ok-Status zurück.
"""

import logging
import os
import re
import shutil
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import config

logger = logging.getLogger(__name__)

# Der öffentliche Status wird von jedem Browser-Tab gepollt und ist deshalb
# gecached. Der Check selbst öffnet eine DB-Verbindung, die wollen wir nicht
# pro Tab und Intervall bezahlen.
_PUBLIC_STATUS_TTL_SECONDS = 5.0
_public_status_lock = threading.Lock()
_public_status_cache: Optional[Tuple[float, Dict[str, Any]]] = None

# Verbindungsfehler enthalten Hostnamen, Cluster-IPs und (bei Vault-Rotation)
# den dynamischen DB-Benutzernamen. Nichts davon gehört in eine Antwort, die
# ohne Authentifizierung abrufbar ist.
_REDACTION_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    # psycopg stellt dem Wert immer ein Schlüsselwort voran und setzt ihn in
    # Anführungszeichen. Das Schlüsselwort bleibt stehen (es sagt, *woran* es
    # scheitert), der Wert dahinter nicht. Die Reihenfolge in der Alternative ist
    # relevant: die mehrwortigen Formen müssen vor den einwortigen stehen, sonst
    # greift "host" schon in "host name".
    #
    # Abgedeckte Formen (Postgres, alle unauthentifiziert erreichbar):
    #   connection to server at "db-rw.ns.svc" (10.0.0.1), port 5432 failed
    #   could not translate host name "db-rw.ns" to address: ...
    #   Is the server running on host "db-rw.ns" and accepting ...
    #   password authentication failed for user "v-kubernet-..."
    (
        re.compile(
            r'(?i)\b((?:server|host)\s+at|host\s*name|hostname|user|role|database|host|server)'
            r'\s+"[^"]*"'
        ),
        r'\1 "<redacted>"',
    ),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "<redacted-ip>"),
    # Auffanglinie für Hostnamen ohne vorangestelltes Schlüsselwort. Bewusst erst
    # ab drei Labels (a.b.c): ab zwei würde sie auch "psycopg2.OperationalError"
    # und "sqlalche.me" schreddern, also genau das, was die Meldung noch lesbar
    # macht. Die kurze Cluster-Form "service.namespace" deckt deshalb die
    # Schlüsselwort-Regel oben ab, nicht diese hier.
    (re.compile(r'\b[\w-]+(?:\.[\w-]+){2,}\b'), "<redacted-host>"),
    (re.compile(r'(?i)\b(?:password|passwd|pwd)\s*=\s*\S+'), "password=<redacted>"),
    (re.compile(r'(?i)\b[a-z+]+://[^\s"\']+'), "<redacted-url>"),
)


def redact_error(message: str, *, max_length: int = 200) -> str:
    """
    Entfernt Infrastruktur-Details aus einer Fehlermeldung.

    Gedacht für Antworten, die ohne Authentifizierung erreichbar sind: Hostnamen,
    IPs, DB-Benutzer, Verbindungs-URLs und Passwörter werden ersetzt. Die
    ungekürzte Meldung steht weiterhin im Log und im authentifizierten
    /api/settings/system-status.
    """
    redacted = message
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = " ".join(redacted.split())
    if len(redacted) > max_length:
        redacted = redacted[: max_length - 1].rstrip() + "…"
    return redacted


def redact_checks(checks: Dict[str, Any]) -> Dict[str, Any]:
    """Wendet redact_error auf alle String-Werte eines Checks-Dicts an."""
    return {
        key: redact_error(value) if isinstance(value, str) else value
        for key, value in checks.items()
    }


def _check_database() -> Tuple[bool, Optional[str]]:
    """Öffnet eine DB-Verbindung und führt SELECT 1 aus. (ok, Fehlermeldung)."""
    try:
        from app.core.database import engine
        from sqlmodel import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        return False, str(e)


def _build_public_status() -> Dict[str, Any]:
    from app.core.database import SQLITE_FALLBACK_ACTIVE

    failing: List[str] = []
    detail: Optional[str] = None

    db_ok, db_error = _check_database()
    if not db_ok:
        failing.append("database")
        detail = redact_error(db_error or "")
        logger.warning("Public-Status: DB-Check fehlgeschlagen: %s", db_error)

    if SQLITE_FALLBACK_ACTIVE:
        failing.append("sqlite_fallback")

    return {
        "status": "ok" if not failing else "degraded",
        "failing": failing,
        "detail": detail,
        "log_viewer_url": config.LOG_VIEWER_URL,
        "version": config.VERSION,
    }


def _with_age(checked_at: float, status: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ergänzt den Status um sein Alter in Sekunden.

    Notwendig wegen des Caches: Eine Antwort beschreibt nicht den Moment der
    Anfrage, sondern eine bis zu _PUBLIC_STATUS_TTL_SECONDS alte Beobachtung.
    Ohne diese Angabe kann das Frontend ein gecachtes "ok" nicht von einem
    frischen unterscheiden — und würde damit eine jüngere, direkt beobachtete
    503-Meldung wieder ausblenden (siehe api/degradedState.ts).

    Das Alter wird pro Antwort berechnet, der gecachte Dict bleibt unberührt.
    """
    age = max(0.0, time.monotonic() - checked_at)
    return {**status, "age_seconds": round(age, 1)}


def get_public_status() -> Dict[str, Any]:
    """
    Liefert einen knappen, unauthentifiziert abrufbaren Systemstatus.

    Bewusst leichtgewichtig: nur DB-Erreichbarkeit plus der SQLite-Fallback-Flag,
    kein Docker-/Kubernetes-Ping und kein Disk-Check. Grund ist der Zweck des
    Endpoints — er muss genau dann noch antworten, wenn die Datenbank weg ist und
    deshalb jeder authentifizierte Endpoint (inkl. /api/settings/system-status)
    an der Auth-Dependency scheitert. Alles Weitere bleibt hinter Auth.

    Das Ergebnis wird für _PUBLIC_STATUS_TTL_SECONDS gecached; wie alt es ist,
    steht in age_seconds.
    """
    global _public_status_cache

    now = time.monotonic()
    cached = _public_status_cache
    if cached is not None and (now - cached[0]) < _PUBLIC_STATUS_TTL_SECONDS:
        return _with_age(cached[0], cached[1])

    with _public_status_lock:
        # Zweiter Blick: ein paralleler Aufrufer kann den Cache befüllt haben,
        # während wir auf das Lock gewartet haben.
        cached = _public_status_cache
        now = time.monotonic()
        if cached is not None and (now - cached[0]) < _PUBLIC_STATUS_TTL_SECONDS:
            return _with_age(cached[0], cached[1])

        # Zeitstempel vom Beginn der Messung, nicht von ihrem Ende: Der DB-Check
        # kann in genau dem Fall, um den es hier geht, in einen Timeout laufen.
        # Die Beobachtung ist dann so alt wie ihr Start — lieber zu alt schätzen
        # als zu jung, sonst verwirft das Frontend die falsche Meldung.
        checked_at = time.monotonic()
        status = _build_public_status()
        _public_status_cache = (checked_at, status)
        return _with_age(checked_at, status)


# Das shared Volume des Kubernetes-Backends liegt auf einem eigenen PVC
# (k8s/deployment.yaml: cache-pvc auf /shared), nicht auf dem Volume von
# DATA_DIR. Läuft es voll, scheitert jeder Run in _copy_pipeline_to_shared mit
# ENOSPC, während DATA_DIR unbeeindruckt Platz meldet — der Disk-Check unten
# sieht davon nichts. Genau diese Lücke hat rote Runs hinter durchgehend
# grünen Probes versteckt.
_SHARED_CACHE_MIN_FREE_GB = 1.0
# Eine Pipeline-Kopie legt pro Run schnell dreistellig viele kleine Dateien an;
# der Platz kann also reichen, während die Inodes ausgehen.
_SHARED_CACHE_MIN_FREE_INODES = 5000


def _check_shared_cache(checks: Dict[str, Any]) -> None:
    """
    Prüft Platz und Inodes auf dem shared Volume (nur Kubernetes-Backend).

    Meldet, gated aber nicht: ok bleibt unberührt. Mit vollem /shared ist der
    Orchestrator weiter verkehrsfähig — DB, API und UI arbeiten normal, nur neue
    Runs scheitern beim Kopieren. Ein NotReady würde bei replicas: 1 den einzigen
    Pod aus dem Service nehmen und damit die UI abschalten, über die man den
    Zustand überhaupt sieht, ohne dass der Pod davon heilt: neu gestartet wird er
    nicht (Liveness hängt an /health) und der Scheduler feuert unabhängig von der
    Probe weiter. Das Signal läuft deshalb über Log-Level, den Checks-Eintrag
    (sichtbar in /api/settings/system-status) und die Prometheus-Gauge.
    """
    mount = config.KUBERNETES_SHARED_CACHE_MOUNT_PATH
    try:
        disk = shutil.disk_usage(mount)
    except Exception as e:
        logger.warning("Readiness: Shared-Volume-Check fehlgeschlagen: %s", e)
        checks["shared_cache"] = str(e)
        return

    free_gb = disk.free / (1024 ** 3)
    checks["shared_cache_free_gb"] = round(free_gb, 2)
    problems: List[str] = []
    if free_gb < _SHARED_CACHE_MIN_FREE_GB:
        problems.append(f"nur {free_gb:.2f} GB frei")

    inode_free = _shared_cache_inodes_free(mount, checks)
    if inode_free is not None and inode_free < _SHARED_CACHE_MIN_FREE_INODES:
        problems.append(f"nur {inode_free} Inodes frei")

    if not problems:
        checks["shared_cache"] = "ok"
        return

    message = ", ".join(problems)
    checks["shared_cache"] = f"kritisch: {message}"
    # ERROR, nicht WARNING: In diesem Zustand scheitert jeder neue Run.
    logger.error(
        "Readiness: Shared-Volume %s erschöpft (%s) — Pipeline-Runs scheitern beim "
        "Kopieren mit ENOSPC. Die Probe bleibt bewusst ready, siehe _check_shared_cache.",
        mount, message,
    )


def _shared_cache_inodes_free(mount: str, checks: Dict[str, Any]) -> Optional[int]:
    """Freie Inodes des shared Volumes, oder None wenn nicht ermittelbar."""
    if not hasattr(os, "statvfs"):
        return None
    try:
        st = os.statvfs(mount)
    except Exception as e:
        checks["shared_cache_inodes"] = str(e)
        return None
    inode_free = int(getattr(st, "f_favail", st.f_ffree))
    checks["shared_cache_inode_free"] = inode_free
    return inode_free


def run_readiness_checks() -> Tuple[Dict[str, Any], bool]:
    """
    Führt alle Readiness-Checks aus (DB, Executor, UV-Cache, Shared Volume,
    Disk, Inodes).

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

    # Shared Volume des Kubernetes-Backends: eigenes PVC, das der DATA_DIR-Check
    # unten nicht abdeckt. Setzt ok bewusst nicht — Begründung in _check_shared_cache.
    if config.PIPELINE_EXECUTOR == "kubernetes":
        _check_shared_cache(checks)

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
