"""
Admin-gesteuerter Reset des gepinnten SSH-Host-Keys für Git-Sync (TE-73).

Follow-up zu TE-23: Der Host-Key wird beim ersten Connect in
DATA_DIR/ssh_known_hosts gepinnt (TOFU) und jeder Sync verifiziert danach
strikt dagegen (StrictHostKeyChecking=accept-new). Das ist beabsichtigtes
MITM-Hardening, bricht aber Sync dauerhaft, wenn der Remote-Server legitim
seinen Host-Key rotiert. Dieses Modul liefert den einzigen vorgesehenen
Recovery-Pfad: ein Admin sieht alten vs. neuen Fingerprint nebeneinander und
muss den Reset explizit per getippter Bestätigung (Repository-URL) auslösen.
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from sqlmodel import Session

from app.core.config import config
from app.services.git_sync_repo_config import get_sync_repo_config

logger = logging.getLogger(__name__)

_SCAN_TIMEOUT = 10
_PROTO_TO_SHORT = {
    "ssh-rsa": "rsa",
    "ssh-ed25519": "ed25519",
    "ssh-dss": "dsa",
}


def _is_ssh_url(url: str) -> bool:
    u = (url or "").strip()
    return u.startswith("git@") or u.startswith("ssh://")


def _normalize_key_type(proto_name: str) -> str:
    """Bildet den vollen SSH-Protokoll-Namen (z.B. ssh-ed25519) auf den kurzen
    Typ ab, den `ssh-keygen -F -l` und `ssh-keyscan -t` verwenden (ed25519)."""
    name = (proto_name or "").strip()
    if name.startswith("ecdsa-sha2-"):
        return "ecdsa"
    return _PROTO_TO_SHORT.get(name, name)


def _parse_ssh_host(repo_url: str) -> Optional[Tuple[str, int]]:
    """Extrahiert (host, port) aus einer SSH-Repo-URL (git@host:path oder ssh://host[:port]/path)."""
    url = (repo_url or "").strip()
    if url.startswith("ssh://"):
        parsed = urlparse(url)
        if not parsed.hostname:
            return None
        return (parsed.hostname, parsed.port or 22)
    if url.startswith("git@"):
        rest = url[len("git@"):]
        host = rest.split(":", 1)[0].strip()
        return (host, 22) if host else None
    return None


def _known_hosts_path() -> Path:
    """Pfad zur persistierten TOFU-known_hosts-Datei (siehe app/git_sync/sync.py)."""
    return config.DATA_DIR / "ssh_known_hosts"


def _resolve_context(session: Session) -> Tuple[bool, str, Optional[str], int, Optional[str]]:
    """
    Ermittelt, ob der admin-gesteuerte Host-Key-Reset für die aktuelle Konfiguration
    zuständig ist. Returns (applicable, reason, host, port, repo_url).
    """
    if config.GIT_SSH_KNOWN_HOSTS:
        return (
            False,
            "GIT_SSH_KNOWN_HOSTS ist per Umgebungsvariable explizit vorkonfiguriert; "
            "dieser Reset-Pfad gilt nur für automatisch gepinnte (TOFU) Host-Keys.",
            None, 22, None,
        )
    repo_config = get_sync_repo_config(session)
    if not repo_config or not repo_config.get("repo_url"):
        return (False, "Kein Repository konfiguriert.", None, 22, None)
    repo_url = repo_config["repo_url"]
    if not _is_ssh_url(repo_url):
        return (False, "Repository nutzt HTTPS (kein SSH-Host-Key-Pinning aktiv).", None, 22, repo_url)
    parsed = _parse_ssh_host(repo_url)
    if not parsed:
        return (False, "SSH-Host konnte nicht aus der Repository-URL ermittelt werden.", None, 22, repo_url)
    host, port = parsed
    return (True, "", host, port, repo_url)


def _pinned_entries(host: str, known_hosts_path: Path) -> List[Dict[str, str]]:
    """Liest aktuell gepinnte Einträge für host aus known_hosts_path (funktioniert auch bei
    gehashten Hostnamen, da ssh-keygen -F intern gegen den Hash matched)."""
    if not known_hosts_path.exists():
        return []
    try:
        result = subprocess.run(
            ["ssh-keygen", "-F", host, "-f", str(known_hosts_path), "-l"],
            capture_output=True, text=True, timeout=_SCAN_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("ssh-keygen -F fehlgeschlagen für %s: %s", host, e)
        return []
    entries: List[Dict[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        _host, key_type, fingerprint = parts[0], parts[1], parts[2]
        entries.append({"key_type": key_type.lower(), "fingerprint": fingerprint})
    return entries


def _ssh_keyscan_raw(host: str, port: int, hashed: bool = False) -> Tuple[List[str], Optional[str]]:
    """Fragt den Server per ssh-keyscan nach seinem aktuellen Host-Key ab.
    Einziger Netzwerk-Ausgangspunkt dieses Moduls (erleichtert Mocking in Tests).
    Returns (raw known_hosts-Zeilen, error_message)."""
    cmd = ["ssh-keyscan", "-T", str(_SCAN_TIMEOUT)]
    if hashed:
        cmd.append("-H")
    if port and port != 22:
        cmd += ["-p", str(port)]
    cmd.append(host)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SCAN_TIMEOUT + 5,
        )
    except subprocess.TimeoutExpired:
        return ([], f"Zeitüberschreitung beim Abfragen von {host}:{port}")
    except OSError as e:
        return ([], str(e))
    lines = [l for l in result.stdout.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        err = result.stderr.strip() or "Server hat keinen Host-Key zurückgegeben"
        return ([], err)
    return (lines, None)


def _scan_current(host: str, port: int) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """Fragt den Host-Key ab, den der Server aktuell präsentiert, und berechnet Fingerprints.
    Returns (entries, error_message)."""
    lines, err = _ssh_keyscan_raw(host, port, hashed=False)
    if err:
        return ([], err)
    entries: List[Dict[str, str]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        proto_type, key_b64 = parts[1], parts[2]
        fp = _fingerprint_of(f"{host} {proto_type} {key_b64}")
        if fp:
            entries.append({"key_type": _normalize_key_type(proto_type), "fingerprint": fp})
    if not entries:
        return ([], "Host-Key konnte nicht ausgewertet werden")
    return (entries, None)


def _fingerprint_of(known_hosts_line: str) -> Optional[str]:
    """Berechnet den SHA256-Fingerprint einer einzelnen known_hosts-Zeile."""
    try:
        result = subprocess.run(
            ["ssh-keygen", "-lf", "-"],
            input=known_hosts_line, capture_output=True, text=True, timeout=_SCAN_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = result.stdout.strip().splitlines()
    if not out:
        return None
    fields = out[0].split()
    for f in fields:
        if f.startswith("SHA256:"):
            return f
    return None


def get_host_key_status(session: Session) -> Dict[str, Any]:
    """
    Vergleicht den gepinnten Host-Key mit dem, den der Server aktuell präsentiert.

    Returns dict mit applicable (bool). Wenn applicable=False, ist `reason` gesetzt
    und kein Reset möglich (z.B. kein SSH-Repo konfiguriert, oder GIT_SSH_KNOWN_HOSTS
    per Env explizit vorkonfiguriert).
    """
    applicable, reason, host, port, repo_url = _resolve_context(session)
    if not applicable:
        return {"applicable": False, "reason": reason}

    known_hosts_path = _known_hosts_path()
    pinned = _pinned_entries(host, known_hosts_path)
    current, scan_error = _scan_current(host, port)
    current_by_type = {e["key_type"]: e["fingerprint"] for e in current}

    entries = []
    for p in pinned:
        new_fp = current_by_type.get(p["key_type"])
        entries.append({
            "key_type": p["key_type"],
            "old_fingerprint": p["fingerprint"],
            "new_fingerprint": new_fp,
            "matches": bool(new_fp) and new_fp == p["fingerprint"],
        })
    mismatch = any(not e["matches"] for e in entries) if entries else False

    return {
        "applicable": True,
        "host": host,
        "port": port,
        "repo_url": repo_url,
        "pinned": bool(entries),
        "entries": entries,
        "mismatch": mismatch,
        "scan_error": scan_error,
    }


def reset_pinned_host_key(session: Session, confirm_text: str) -> Dict[str, Any]:
    """
    Setzt den gepinnten Host-Key für das konfigurierte SSH-Repo zurück: entfernt alle
    bestehenden known_hosts-Einträge für den Host und pinnt den aktuell vom Server
    präsentierten Key neu. Erfordert getippte Bestätigung der exakten Repository-URL
    (kein Ein-Klick-Bypass).

    Raises:
        ValueError: Wenn kein Reset möglich ist, die Bestätigung nicht passt, oder der
            aktuelle Host-Key nicht abgerufen werden konnte.

    Returns:
        Dict mit host, repo_url, old_entries, new_entries (für Audit-Log und Response).
    """
    applicable, reason, host, port, repo_url = _resolve_context(session)
    if not applicable:
        raise ValueError(reason)

    if (confirm_text or "").strip() != repo_url:
        raise ValueError("Bestätigung stimmt nicht mit der Repository-URL überein")

    known_hosts_path = _known_hosts_path()
    old_entries = _pinned_entries(host, known_hosts_path)
    current, scan_error = _scan_current(host, port)
    if scan_error or not current:
        raise ValueError(
            f"Aktueller Host-Key konnte nicht abgerufen werden: {scan_error or 'kein Key gefunden'}"
        )

    known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
    if not known_hosts_path.exists():
        known_hosts_path.touch(mode=0o600)

    if old_entries:
        try:
            subprocess.run(
                ["ssh-keygen", "-R", host, "-f", str(known_hosts_path)],
                capture_output=True, text=True, timeout=_SCAN_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            raise ValueError(f"Alter Host-Key konnte nicht entfernt werden: {e}")
        # ssh-keygen -R legt eine .old-Backup-Datei mit dem entfernten (jetzt
        # kompromittierten/veralteten) Key an; die Reset-Aktion ist bereits im
        # Audit-Log erfasst, daher wird die Backup-Datei nicht dauerhaft aufbewahrt.
        backup = known_hosts_path.with_name(known_hosts_path.name + ".old")
        if backup.exists():
            try:
                backup.unlink()
            except OSError:
                pass

    # Frischer Scan direkt vor dem Pinnen (statt den Scan von oben wiederzuverwenden),
    # damit der tatsächlich gepinnte Key so aktuell wie möglich ist.
    repin_lines, repin_error = _ssh_keyscan_raw(host, port, hashed=True)
    if repin_error or not repin_lines:
        raise ValueError(
            f"Neuer Host-Key konnte nicht gepinnt werden: {repin_error or 'leere Antwort vom Server'}"
        )
    with open(known_hosts_path, "a") as f:
        f.write("\n".join(repin_lines) + "\n")

    new_entries = _pinned_entries(host, known_hosts_path)
    return {
        "host": host,
        "repo_url": repo_url,
        "old_entries": old_entries,
        "new_entries": new_entries,
    }
