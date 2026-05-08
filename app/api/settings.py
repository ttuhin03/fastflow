"""
Settings API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für System-Einstellungen:
- Konfiguration abrufen/aktualisieren
- Force Flush (manueller Cleanup)
- Log-Dateien-Statistiken
"""

import asyncio
import logging
import os
import secrets as secrets_module
import shutil
from datetime import datetime, timezone
from pathlib import Path
import psutil
from typing import Optional, Dict, Any, List, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.database import get_session, database_url
from app.core.config import config
from app.core.notification_api_key_hash import digest_notification_api_token
from app.models import NotificationApiKey
from app.services.cleanup import cleanup_logs, cleanup_docker_resources
from app.services.s3_backup import get_backup_failures, get_last_backup_timestamp
from app.models import PipelineRun, RunStatus, User
from app.services.notifications import send_email_notification, send_teams_notification
from app.executor import _get_docker_client
from app.executor.kubernetes_backend import get_kubernetes_system_metrics
from app.auth import require_admin, require_write, get_current_user
from app.analytics.posthog_client import get_system_settings, shutdown_posthog, capture_exception
from app.core.errors import get_500_detail
from app.services.orchestrator_settings import (
    get_orchestrator_settings_or_default,
    apply_orchestrator_settings_to_config,
)
from app.services.secrets import encrypt
from app.services.audit import log_audit
from app.services.dependency_audit import get_last_dependency_audit
from sqlmodel import text
from botocore.config import Config as BotoConfig
import boto3

logger = logging.getLogger(__name__)


def _directory_size_bytes(root: Path) -> int:
    """Summiert Dateigrößen unter root; fehlendes Verzeichnis oder Fehler → 0."""
    if not root.exists():
        return 0
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def _query_database_size_bytes(session: Session) -> int:
    """DB-Größe (SQLite-Dateien oder PostgreSQL pg_database_size). Schnell, im Request-Thread."""
    database_size_bytes = 0
    try:
        if database_url.startswith("sqlite"):
            db_path = database_url.replace("sqlite:///", "")
            if os.path.exists(db_path):
                database_size_bytes = os.path.getsize(db_path)
                wal_path = f"{db_path}-wal"
                if os.path.exists(wal_path):
                    database_size_bytes += os.path.getsize(wal_path)
                shm_path = f"{db_path}-shm"
                if os.path.exists(shm_path):
                    database_size_bytes += os.path.getsize(shm_path)
        else:
            try:
                result = session.exec(text("SELECT pg_database_size(current_database())"))
                size = result.scalar()
                if size:
                    database_size_bytes = size
            except Exception:
                pass
    except Exception:
        pass
    return database_size_bytes


def _sync_build_storage_stats_payload(database_size_bytes: int) -> Dict[str, Any]:
    """
    Log-/UV-Cache-Verzeichnisgrößen und Disk-Stats — CPU-/I/O-intensiv (rglob).
    Läuft in einem Worker-Thread, damit der Async-Event-Loop nicht blockiert.
    """
    logs_dir = config.LOGS_DIR

    log_files_count = 0
    log_files_size_bytes = 0

    if logs_dir.exists():
        for file_path in logs_dir.rglob("*"):
            if file_path.is_file():
                log_files_count += 1
                try:
                    log_files_size_bytes += file_path.stat().st_size
                except (OSError, PermissionError):
                    pass

    log_files_size_mb = log_files_size_bytes / (1024 * 1024)

    total_disk_space_bytes = 0
    used_disk_space_bytes = 0
    free_disk_space_bytes = 0

    try:
        if logs_dir.exists():
            disk_usage = shutil.disk_usage(logs_dir)
            total_disk_space_bytes = disk_usage.total
            used_disk_space_bytes = disk_usage.used
            free_disk_space_bytes = disk_usage.free
        else:
            disk_usage = shutil.disk_usage("/")
            total_disk_space_bytes = disk_usage.total
            used_disk_space_bytes = disk_usage.used
            free_disk_space_bytes = disk_usage.free
    except (OSError, PermissionError):
        pass

    inode_total: Optional[int] = None
    inode_free: Optional[int] = None
    inode_used_percent: Optional[float] = None
    if hasattr(os, "statvfs"):
        try:
            stat_path = str(logs_dir) if logs_dir.exists() else "/"
            st = os.statvfs(stat_path)
            inode_total = st.f_files
            inode_free = getattr(st, "f_favail", st.f_ffree)
            inode_used = inode_total - inode_free
            inode_used_percent = (inode_used / inode_total * 100) if inode_total else None
        except (OSError, PermissionError, AttributeError):
            pass

    total_disk_space_gb = total_disk_space_bytes / (1024 * 1024 * 1024)
    used_disk_space_gb = used_disk_space_bytes / (1024 * 1024 * 1024)
    free_disk_space_gb = free_disk_space_bytes / (1024 * 1024 * 1024)

    log_files_percentage = 0.0
    if total_disk_space_bytes > 0:
        log_files_percentage = (log_files_size_bytes / total_disk_space_bytes) * 100

    database_size_mb = 0.0
    database_size_gb = 0.0
    database_percentage = 0.0
    if database_size_bytes > 0:
        database_size_mb = database_size_bytes / (1024 * 1024)
        database_size_gb = database_size_bytes / (1024 * 1024 * 1024)
        if total_disk_space_bytes > 0:
            database_percentage = (database_size_bytes / total_disk_space_bytes) * 100

    if config.UV_STORAGE_STATS:
        uv_cache_size_bytes = _directory_size_bytes(config.UV_CACHE_DIR)
        uv_python_install_size_bytes = _directory_size_bytes(config.UV_PYTHON_INSTALL_DIR)
    else:
        uv_cache_size_bytes = 0
        uv_python_install_size_bytes = 0
    uv_cache_size_mb = uv_cache_size_bytes / (1024 * 1024)
    uv_python_install_size_mb = uv_python_install_size_bytes / (1024 * 1024)
    uv_cache_percentage = 0.0
    uv_python_percentage = 0.0
    if total_disk_space_bytes > 0:
        uv_cache_percentage = (uv_cache_size_bytes / total_disk_space_bytes) * 100
        uv_python_percentage = (uv_python_install_size_bytes / total_disk_space_bytes) * 100

    result: Dict[str, Any] = {
        "log_files_count": log_files_count,
        "log_files_size_bytes": log_files_size_bytes,
        "log_files_size_mb": round(log_files_size_mb, 2),
        "total_disk_space_bytes": total_disk_space_bytes,
        "total_disk_space_gb": round(total_disk_space_gb, 2),
        "used_disk_space_bytes": used_disk_space_bytes,
        "used_disk_space_gb": round(used_disk_space_gb, 2),
        "free_disk_space_bytes": free_disk_space_bytes,
        "free_disk_space_gb": round(free_disk_space_gb, 2),
        "log_files_percentage": round(log_files_percentage, 2),
        "uv_cache_dir": str(config.UV_CACHE_DIR),
        "uv_cache_size_bytes": uv_cache_size_bytes,
        "uv_cache_size_mb": round(uv_cache_size_mb, 2),
        "uv_cache_percentage": round(uv_cache_percentage, 2),
        "uv_python_install_dir": str(config.UV_PYTHON_INSTALL_DIR),
        "uv_python_install_size_bytes": uv_python_install_size_bytes,
        "uv_python_install_size_mb": round(uv_python_install_size_mb, 2),
        "uv_python_percentage": round(uv_python_percentage, 2),
        "uv_pre_heat": config.UV_PRE_HEAT,
        "default_python_version": config.DEFAULT_PYTHON_VERSION,
        "uv_storage_stats_enabled": config.UV_STORAGE_STATS,
    }
    if inode_total is not None and inode_free is not None:
        result["inode_total"] = inode_total
        result["inode_free"] = inode_free
        result["inode_used"] = inode_total - inode_free
        if inode_used_percent is not None:
            result["inode_used_percent"] = round(inode_used_percent, 2)

    if database_size_bytes > 0:
        result.update({
            "database_size_bytes": database_size_bytes,
            "database_size_mb": round(database_size_mb, 2),
            "database_size_gb": round(database_size_gb, 2),
            "database_percentage": round(database_percentage, 2),
        })

    return result


router = APIRouter(prefix="/settings", tags=["settings"])

_UI_LOGIN_BG_ALLOWED: frozenset[str] = frozenset({"video", "game_of_life"})

# IANA-Zeitzonen für die Header-Uhr (Auswahl in den Systemeinstellungen, genau zwei aktiv).
ALLOWED_UI_HEADER_TIMEZONES: frozenset[str] = frozenset(
    {
        "UTC",
        "Europe/Berlin",
        "Europe/London",
        "Europe/Paris",
        "America/New_York",
        "America/Chicago",
        "America/Los_Angeles",
        "America/Sao_Paulo",
        "Asia/Dubai",
        "Asia/Tokyo",
        "Asia/Singapore",
        "Australia/Sydney",
    }
)


def _normalize_ui_login_background(raw: Optional[str]) -> str:
    v = (raw or "video").strip()
    return v if v in _UI_LOGIN_BG_ALLOWED else "video"


def _safe_public_url(url: Optional[str]) -> Optional[str]:
    """Nur http(s) mit Host, für sichere Nutzung als Bild-URL im Frontend."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return u


def _validate_s3_endpoint_url(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    u = raw.strip()
    if not u:
        return None
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ungültige S3 Endpoint-URL: nur http:// oder https:// mit gültigem Host erlaubt",
        )
    return u


def _validate_ui_header_timezone_id(raw: Optional[str]) -> str:
    tz = (raw or "").strip()
    if tz not in ALLOWED_UI_HEADER_TIMEZONES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ungültige Zeitzone: nur Werte aus der erlaubten Liste",
        )
    return tz


def _system_settings_audit_snapshot(ss: Any) -> Dict[str, Any]:
    """Vergleichswerte für Audit (keine Secrets)."""
    return {
        "is_setup_completed": bool(ss.is_setup_completed),
        "enable_telemetry": bool(ss.enable_telemetry),
        "enable_error_reporting": bool(ss.enable_error_reporting),
        "dependency_audit_enabled": bool(getattr(ss, "dependency_audit_enabled", True)),
        "dependency_audit_cron": (getattr(ss, "dependency_audit_cron", None) or "0 3 * * *").strip(),
        "login_branding_logo_url": getattr(ss, "login_branding_logo_url", None),
        "ui_show_attribution": bool(getattr(ss, "ui_show_attribution", True)),
        "ui_show_version": bool(getattr(ss, "ui_show_version", True)),
        "show_unconfigured_oauth_on_login": bool(getattr(ss, "show_unconfigured_oauth_on_login", True)),
        "ui_login_background": _normalize_ui_login_background(getattr(ss, "ui_login_background", None)),
        "ui_header_timezone_1": getattr(ss, "ui_header_timezone_1", None) or "UTC",
        "ui_header_timezone_2": getattr(ss, "ui_header_timezone_2", None) or "Europe/Berlin",
    }


def _build_system_settings_audit_details(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    changed = sorted(k for k in before if before[k] != after[k])
    if not changed:
        return None
    details: Dict[str, Any] = {"changed_fields": changed}
    if "login_branding_logo_url" in changed:
        details["login_branding_logo_url"] = "cleared" if not after.get("login_branding_logo_url") else "set"
    return details


_ORCHESTRATOR_AUDIT_KEYS = (
    "log_retention_runs",
    "log_retention_days",
    "log_max_size_mb",
    "max_concurrent_runs",
    "container_timeout",
    "retry_attempts",
    "auto_sync_enabled",
    "auto_sync_interval",
    "email_enabled",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_from",
    "email_recipients",
    "teams_enabled",
    "teams_webhook_url",
    "notification_api_enabled",
    "notification_api_rate_limit_per_minute",
    "s3_backup_enabled",
    "s3_endpoint_url",
    "s3_bucket",
    "s3_region",
    "s3_prefix",
    "s3_use_path_style",
    "s3_test_on_save",
)


def _orchestrator_audit_snapshot(row: Any) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    for k in _ORCHESTRATOR_AUDIT_KEYS:
        snap[k] = getattr(row, k, None)
    snap["smtp_password_encrypted"] = getattr(row, "smtp_password_encrypted", None)
    snap["s3_access_key_encrypted"] = getattr(row, "s3_access_key_encrypted", None)
    snap["s3_secret_access_key_encrypted"] = getattr(row, "s3_secret_access_key_encrypted", None)
    return snap


def _build_orchestrator_settings_audit_details(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    changed_fields: List[str] = []
    details: Dict[str, Any] = {}
    for k in _ORCHESTRATOR_AUDIT_KEYS:
        if before.get(k) != after.get(k):
            changed_fields.append(k)
    if before.get("smtp_password_encrypted") != after.get("smtp_password_encrypted"):
        details["smtp_password_updated"] = True
    if before.get("s3_access_key_encrypted") != after.get("s3_access_key_encrypted"):
        details["s3_access_key_updated"] = True
    if before.get("s3_secret_access_key_encrypted") != after.get("s3_secret_access_key_encrypted"):
        details["s3_secret_access_key_updated"] = True
    if not changed_fields and not details:
        return None
    out: Dict[str, Any] = {"changed_fields": sorted(changed_fields)}
    out.update(details)
    return out


class TelemetryStatusResponse(BaseModel):
    """Öffentliche Konfiguration für Frontend PostHog (Phase 2a: Error-Tracking). Kein Auth."""
    enable_error_reporting: bool
    posthog_api_key: str
    posthog_host: str


@router.get("/telemetry-status", response_model=TelemetryStatusResponse)
async def get_telemetry_status(
    session: Session = Depends(get_session),
) -> TelemetryStatusResponse:
    """
    Gibt PostHog-Client-Konfiguration für Frontend (Phase 2a).
    Öffentlich (kein Auth), damit Login- und Fehlerseiten auch tracken können.
    """
    enable = False
    try:
        ss = get_system_settings(session)
        enable = bool(ss.enable_error_reporting)
    except Exception as e:
        logger.debug("telemetry-status: SystemSettings nicht lesbar, enable_error_reporting=false: %s", e)
    return TelemetryStatusResponse(
        enable_error_reporting=enable,
        posthog_api_key=config.POSTHOG_API_KEY if enable else "",
        posthog_host=config.POSTHOG_HOST if enable else "",
    )


class UiDisplayResponse(BaseModel):
    """Systemweite Anzeige-Optionen (Attribution, Version, Login-Hintergrund). Öffentlich lesbar für Login-UI."""
    ui_show_attribution: bool
    ui_show_version: bool
    ui_login_background: str = "video"
    ui_header_timezone_1: str = "UTC"
    ui_header_timezone_2: str = "Europe/Berlin"


@router.get("/ui-display", response_model=UiDisplayResponse)
async def get_ui_display_settings(
    session: Session = Depends(get_session),
) -> UiDisplayResponse:
    """
    Liefert die systemweiten UI-Anzeige-Flags. Kein Auth (wie /telemetry-status),
    damit Login- und Fehlerseiten dieselben Werte wie die eingeloggte App nutzen.
    """
    try:
        ss = get_system_settings(session)
        tz1 = getattr(ss, "ui_header_timezone_1", None) or "UTC"
        tz2 = getattr(ss, "ui_header_timezone_2", None) or "Europe/Berlin"
        if tz1 not in ALLOWED_UI_HEADER_TIMEZONES:
            tz1 = "UTC"
        if tz2 not in ALLOWED_UI_HEADER_TIMEZONES:
            tz2 = "Europe/Berlin"
        if tz1 == tz2:
            tz2 = "Europe/Berlin" if tz1 != "Europe/Berlin" else "UTC"
        return UiDisplayResponse(
            ui_show_attribution=bool(getattr(ss, "ui_show_attribution", True)),
            ui_show_version=bool(getattr(ss, "ui_show_version", True)),
            ui_login_background=_normalize_ui_login_background(getattr(ss, "ui_login_background", None)),
            ui_header_timezone_1=tz1,
            ui_header_timezone_2=tz2,
        )
    except Exception as e:
        logger.debug("ui-display: SystemSettings nicht lesbar, Defaults true: %s", e)
        return UiDisplayResponse(
            ui_show_attribution=True,
            ui_show_version=True,
            ui_login_background="video",
            ui_header_timezone_1="UTC",
            ui_header_timezone_2="Europe/Berlin",
        )


class NotificationApiKeyItem(BaseModel):
    """Ein Eintrag in der Liste der Notification-API-Keys (ohne Klartext-Key)."""
    id: int
    label: Optional[str] = None
    created_at: str


class SettingsResponse(BaseModel):
    """Response-Model für System-Einstellungen."""
    log_retention_runs: Optional[int]
    log_retention_days: Optional[int]
    log_max_size_mb: Optional[int]
    max_concurrent_runs: int
    container_timeout: Optional[int]
    retry_attempts: int
    auto_sync_enabled: bool
    auto_sync_interval: Optional[int]
    email_enabled: bool
    smtp_host: Optional[str]
    smtp_port: int
    smtp_user: Optional[str]
    smtp_from: Optional[str]
    email_recipients: List[str]
    teams_enabled: bool
    teams_webhook_url: Optional[str]
    notification_api_enabled: bool = False
    notification_api_rate_limit_per_minute: int = 30
    notification_api_keys: List[NotificationApiKeyItem] = []
    s3_backup_enabled: bool = False
    s3_endpoint_url: Optional[str]
    s3_bucket: Optional[str]
    s3_region: str = "us-east-1"
    s3_prefix: str = "pipeline-logs"
    s3_use_path_style: bool = True
    s3_access_key_configured: bool = False
    s3_secret_access_key_configured: bool = False
    s3_last_test_at: Optional[str] = None
    s3_last_test_status: Optional[str] = None
    s3_last_test_error: Optional[str] = None
    s3_test_on_save: bool = False


class SystemSettingsResponse(BaseModel):
    """Response für System-Konfiguration (Wizard, Nutzer-Tab, Abhängigkeiten-Audit)."""
    is_setup_completed: bool
    enable_telemetry: bool
    enable_error_reporting: bool
    dependency_audit_enabled: bool = True
    dependency_audit_cron: str = "0 3 * * *"
    login_branding_logo_url: Optional[str] = None
    ui_show_attribution: bool = True
    ui_show_version: bool = True
    show_unconfigured_oauth_on_login: bool = True
    ui_login_background: str = "video"
    ui_header_timezone_1: str = "UTC"
    ui_header_timezone_2: str = "Europe/Berlin"


class SystemSettingsUpdate(BaseModel):
    """Request für System-Konfiguration (nur übergebene Felder werden aktualisiert)."""
    is_setup_completed: Optional[bool] = None
    enable_telemetry: Optional[bool] = None
    enable_error_reporting: Optional[bool] = None
    dependency_audit_enabled: Optional[bool] = None
    dependency_audit_cron: Optional[str] = None
    login_branding_logo_url: Optional[str] = None
    ui_show_attribution: Optional[bool] = None
    ui_show_version: Optional[bool] = None
    show_unconfigured_oauth_on_login: Optional[bool] = None
    ui_login_background: Optional[Literal["video", "game_of_life"]] = None
    ui_header_timezone_1: Optional[str] = None
    ui_header_timezone_2: Optional[str] = None


class SettingsUpdate(BaseModel):
    """Request-Model für Einstellungs-Updates."""
    log_retention_runs: Optional[int] = None
    log_retention_days: Optional[int] = None
    log_max_size_mb: Optional[int] = None
    max_concurrent_runs: Optional[int] = Field(default=None, ge=1)
    container_timeout: Optional[int] = None
    retry_attempts: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = Field(default=None, ge=60)
    email_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    email_recipients: Optional[str] = None  # Komma-separiert als String
    teams_enabled: Optional[bool] = None
    teams_webhook_url: Optional[str] = None
    notification_api_enabled: Optional[bool] = None
    notification_api_rate_limit_per_minute: Optional[int] = None
    s3_backup_enabled: Optional[bool] = None
    s3_endpoint_url: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_access_key: Optional[str] = None
    s3_region: Optional[str] = None
    s3_prefix: Optional[str] = None
    s3_use_path_style: Optional[bool] = None
    s3_clear_access_key: Optional[bool] = None
    s3_clear_secret_access_key: Optional[bool] = None
    s3_test_on_save: Optional[bool] = None


@router.get("", response_model=SettingsResponse)
async def get_settings(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> SettingsResponse:
    """
    Gibt die aktuellen System-Einstellungen zurück.
    
    Returns:
        SettingsResponse: Aktuelle Konfigurationswerte
    """
    keys_list: List[NotificationApiKeyItem] = []
    row = get_orchestrator_settings_or_default(session)
    try:
        for key_row in session.exec(select(NotificationApiKey).order_by(NotificationApiKey.id.desc())).all():
            keys_list.append(NotificationApiKeyItem(
                id=key_row.id,
                label=key_row.label,
                created_at=key_row.created_at.isoformat() if key_row.created_at else "",
            ))
    except Exception as e:
        logger.debug("notification_api_keys not yet available: %s", e)
    return SettingsResponse(
        log_retention_runs=config.LOG_RETENTION_RUNS,
        log_retention_days=config.LOG_RETENTION_DAYS,
        log_max_size_mb=config.LOG_MAX_SIZE_MB,
        max_concurrent_runs=config.MAX_CONCURRENT_RUNS,
        container_timeout=config.CONTAINER_TIMEOUT,
        retry_attempts=config.RETRY_ATTEMPTS,
        auto_sync_enabled=config.AUTO_SYNC_ENABLED,
        auto_sync_interval=config.AUTO_SYNC_INTERVAL,
        email_enabled=config.EMAIL_ENABLED,
        smtp_host=config.SMTP_HOST,
        smtp_port=config.SMTP_PORT,
        smtp_user=config.SMTP_USER,
        smtp_from=config.SMTP_FROM,
        email_recipients=config.EMAIL_RECIPIENTS,
        teams_enabled=config.TEAMS_ENABLED,
        teams_webhook_url=config.TEAMS_WEBHOOK_URL,
        notification_api_enabled=getattr(config, "NOTIFICATION_API_ENABLED", False),
        notification_api_rate_limit_per_minute=getattr(config, "NOTIFICATION_API_RATE_LIMIT_PER_MINUTE", 30),
        notification_api_keys=keys_list,
        s3_backup_enabled=getattr(config, "S3_BACKUP_ENABLED", False),
        s3_endpoint_url=getattr(config, "S3_ENDPOINT_URL", None),
        s3_bucket=getattr(config, "S3_BUCKET", None),
        s3_region=getattr(config, "S3_REGION", "us-east-1"),
        s3_prefix=getattr(config, "S3_PREFIX", "pipeline-logs"),
        s3_use_path_style=getattr(config, "S3_USE_PATH_STYLE", True),
        s3_access_key_configured=bool(getattr(config, "S3_ACCESS_KEY", None) or getattr(row, "s3_access_key_encrypted", None)),
        s3_secret_access_key_configured=bool(
            getattr(config, "S3_SECRET_ACCESS_KEY", None) or getattr(row, "s3_secret_access_key_encrypted", None)
        ),
        s3_last_test_at=row.s3_last_test_at.isoformat() if getattr(row, "s3_last_test_at", None) else None,
        s3_last_test_status=getattr(row, "s3_last_test_status", None),
        s3_last_test_error=getattr(row, "s3_last_test_error", None),
        s3_test_on_save=bool(getattr(row, "s3_test_on_save", None)),
    )


@router.put("", response_model=Dict[str, str])
async def update_settings(
    settings: SettingsUpdate,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> Dict[str, str]:
    """
    Aktualisiert System-Einstellungen und speichert sie in der Datenbank.
    Die laufende config wird sofort aktualisiert; ein Neustart ist nicht nötig.
    """
    row = get_orchestrator_settings_or_default(session)
    orch_before = _orchestrator_audit_snapshot(row)
    if settings.log_retention_runs is not None:
        row.log_retention_runs = settings.log_retention_runs
    if settings.log_retention_days is not None:
        row.log_retention_days = settings.log_retention_days
    if settings.log_max_size_mb is not None:
        row.log_max_size_mb = settings.log_max_size_mb
    if settings.max_concurrent_runs is not None:
        row.max_concurrent_runs = settings.max_concurrent_runs
    if settings.container_timeout is not None:
        row.container_timeout = settings.container_timeout
    if settings.retry_attempts is not None:
        row.retry_attempts = settings.retry_attempts
    if settings.auto_sync_enabled is not None:
        row.auto_sync_enabled = settings.auto_sync_enabled
    if settings.auto_sync_interval is not None:
        row.auto_sync_interval = settings.auto_sync_interval
    if settings.email_enabled is not None:
        row.email_enabled = settings.email_enabled
    if settings.smtp_host is not None:
        row.smtp_host = settings.smtp_host
    if settings.smtp_port is not None:
        row.smtp_port = settings.smtp_port
    if settings.smtp_user is not None:
        row.smtp_user = settings.smtp_user
    if settings.smtp_password is not None:
        row.smtp_password_encrypted = encrypt(settings.smtp_password)
    if settings.smtp_from is not None:
        row.smtp_from = settings.smtp_from
    if settings.email_recipients is not None:
        row.email_recipients = settings.email_recipients
    if settings.teams_enabled is not None:
        row.teams_enabled = settings.teams_enabled
    if settings.teams_webhook_url is not None:
        row.teams_webhook_url = settings.teams_webhook_url
    if settings.notification_api_enabled is not None:
        row.notification_api_enabled = settings.notification_api_enabled
    if settings.notification_api_rate_limit_per_minute is not None:
        row.notification_api_rate_limit_per_minute = settings.notification_api_rate_limit_per_minute
    if settings.s3_backup_enabled is not None:
        row.s3_backup_enabled = settings.s3_backup_enabled
    if settings.s3_endpoint_url is not None:
        row.s3_endpoint_url = _validate_s3_endpoint_url(settings.s3_endpoint_url)
    if settings.s3_bucket is not None:
        row.s3_bucket = (settings.s3_bucket or "").strip() or None
    if settings.s3_region is not None:
        row.s3_region = (settings.s3_region or "").strip() or "us-east-1"
    if settings.s3_prefix is not None:
        row.s3_prefix = (settings.s3_prefix or "").strip() or "pipeline-logs"
    if settings.s3_use_path_style is not None:
        row.s3_use_path_style = settings.s3_use_path_style
    if settings.s3_clear_access_key:
        row.s3_access_key_encrypted = None
    if settings.s3_clear_secret_access_key:
        row.s3_secret_access_key_encrypted = None
    if settings.s3_access_key is not None and settings.s3_access_key.strip():
        row.s3_access_key_encrypted = encrypt(settings.s3_access_key.strip())
    if settings.s3_secret_access_key is not None and settings.s3_secret_access_key.strip():
        row.s3_secret_access_key_encrypted = encrypt(settings.s3_secret_access_key.strip())
    if settings.s3_test_on_save is not None:
        row.s3_test_on_save = settings.s3_test_on_save
    enabled_after = row.s3_backup_enabled if row.s3_backup_enabled is not None else config.S3_BACKUP_ENABLED
    endpoint_after = row.s3_endpoint_url if row.s3_endpoint_url is not None else config.S3_ENDPOINT_URL
    bucket_after = row.s3_bucket if row.s3_bucket is not None else config.S3_BUCKET
    prefix_after = row.s3_prefix if row.s3_prefix is not None else config.S3_PREFIX
    access_after = row.s3_access_key_encrypted is not None or bool(config.S3_ACCESS_KEY)
    secret_after = row.s3_secret_access_key_encrypted is not None or bool(config.S3_SECRET_ACCESS_KEY)
    if enabled_after:
        if not endpoint_after:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Endpoint-URL fehlt")
        if not bucket_after:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Bucket fehlt")
        if not prefix_after:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Prefix fehlt")
        if not access_after:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Access Key fehlt")
        if not secret_after:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Secret Access Key fehlt")
    session.add(row)
    session.commit()
    session.refresh(row)
    apply_orchestrator_settings_to_config(row)
    from app.services.git_auto_sync import schedule_git_auto_sync_job
    schedule_git_auto_sync_job()
    orch_after = _orchestrator_audit_snapshot(row)
    audit_details = _build_orchestrator_settings_audit_details(orch_before, orch_after)
    if audit_details:
        log_audit(session, "settings_update", "settings", None, audit_details, current_user)
    return {
        "message": "Einstellungen wurden gespeichert und sind sofort aktiv."
    }


class CreateNotificationApiKeyRequest(BaseModel):
    """Optionales Label für einen neuen Notification-API-Key."""
    label: Optional[str] = None


class CreateNotificationApiKeyResponse(BaseModel):
    """Response nach Key-Erzeugung: Klartext-Key nur einmal zurückgeben."""
    key: str
    id: int
    label: Optional[str] = None
    created_at: str


@router.post("/notification-api/keys", response_model=CreateNotificationApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_notification_api_key(
    body: Optional[CreateNotificationApiKeyRequest] = None,
    current_user: User = Depends(require_write),
    session: Session = Depends(get_session),
) -> CreateNotificationApiKeyResponse:
    """Erzeugt einen neuen API-Key für die Benachrichtigungs-API. Der Klartext-Key wird nur einmal zurückgegeben."""
    random_urlsafe = secrets_module.token_urlsafe(32)
    key_hash = digest_notification_api_token(random_urlsafe)
    label = (body.label if body else None) or None
    if label is not None:
        label = label.strip() or None
    row = NotificationApiKey(key_hash=key_hash, label=label)
    session.add(row)
    session.commit()
    session.refresh(row)
    log_audit(session, "notification_key_create", "settings", None, {"label": label}, current_user)
    return CreateNotificationApiKeyResponse(
        key=random_urlsafe,
        id=row.id,
        label=row.label,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


@router.delete("/notification-api/keys/{key_id}", status_code=status.HTTP_200_OK)
async def delete_notification_api_key(
    key_id: int,
    current_user: User = Depends(require_write),
    session: Session = Depends(get_session),
) -> Dict[str, str]:
    """Entfernt einen Notification-API-Key."""
    row = session.get(NotificationApiKey, key_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key nicht gefunden")
    session.delete(row)
    session.commit()
    log_audit(session, "notification_key_delete", "settings", str(key_id), None, current_user)
    return {"message": "Key entfernt"}


@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings_endpoint(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    """
    Gibt System-Konfiguration zurück (is_setup_completed, enable_telemetry, enable_error_reporting).
    Nur für Admins.
    """
    ss = get_system_settings(session)
    return SystemSettingsResponse(
        is_setup_completed=ss.is_setup_completed,
        enable_telemetry=ss.enable_telemetry,
        enable_error_reporting=ss.enable_error_reporting,
        dependency_audit_enabled=getattr(ss, "dependency_audit_enabled", True),
        dependency_audit_cron=getattr(ss, "dependency_audit_cron", "0 3 * * *") or "0 3 * * *",
        login_branding_logo_url=getattr(ss, "login_branding_logo_url", None),
        ui_show_attribution=bool(getattr(ss, "ui_show_attribution", True)),
        ui_show_version=bool(getattr(ss, "ui_show_version", True)),
        show_unconfigured_oauth_on_login=bool(getattr(ss, "show_unconfigured_oauth_on_login", True)),
        ui_login_background=_normalize_ui_login_background(getattr(ss, "ui_login_background", None)),
        ui_header_timezone_1=getattr(ss, "ui_header_timezone_1", None) or "UTC",
        ui_header_timezone_2=getattr(ss, "ui_header_timezone_2", None) or "Europe/Berlin",
    )


class DependencyAuditLastResponse(BaseModel):
    """Ergebnisse des letzten Dependency-Audit-Durchgangs (Startup oder Cron-Job)."""
    last_scan_at: Optional[str] = None  # ISO 8601
    results: List[Dict[str, Any]] = []  # [{ pipeline, packages, vulnerabilities?, audit_error? }, ...]


@router.get("/dependency-audit-last", response_model=DependencyAuditLastResponse)
async def get_dependency_audit_last(
    current_user: User = Depends(get_current_user),
) -> DependencyAuditLastResponse:
    """
    Gibt Zeitpunkt und Ergebnisse des letzten Dependency-Audit-Durchgangs zurück.
    Der Scan läuft beim API-Start und optional per Cron. Erfordert Authentifizierung.
    """
    last_at, results = get_last_dependency_audit()
    return DependencyAuditLastResponse(
        last_scan_at=last_at.isoformat() if last_at else None,
        results=results,
    )


@router.put("/system", response_model=SystemSettingsResponse)
async def update_system_settings_endpoint(
    body: SystemSettingsUpdate,
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> SystemSettingsResponse:
    """
    Aktualisiert System-Konfiguration. Nur übergebene Felder werden geändert.
    Wenn enable_error_reporting auf False gesetzt wird: PostHog-Client shutdown.
    """
    ss = get_system_settings(session)
    system_before = _system_settings_audit_snapshot(ss)
    if body.is_setup_completed is not None:
        ss.is_setup_completed = body.is_setup_completed
    if body.enable_telemetry is not None:
        ss.enable_telemetry = body.enable_telemetry
    if body.enable_error_reporting is not None:
        ss.enable_error_reporting = body.enable_error_reporting
    if body.dependency_audit_enabled is not None:
        ss.dependency_audit_enabled = body.dependency_audit_enabled
    if body.dependency_audit_cron is not None:
        ss.dependency_audit_cron = (body.dependency_audit_cron or "0 3 * * *").strip()
    if body.login_branding_logo_url is not None:
        raw = (body.login_branding_logo_url or "").strip()
        if not raw:
            ss.login_branding_logo_url = None
        else:
            validated = _safe_public_url(raw)
            if not validated:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ungültige Logo-URL: nur http:// oder https:// mit gültigem Host erlaubt",
                )
            ss.login_branding_logo_url = validated
    if body.ui_show_attribution is not None:
        ss.ui_show_attribution = body.ui_show_attribution
    if body.ui_show_version is not None:
        ss.ui_show_version = body.ui_show_version
    if body.show_unconfigured_oauth_on_login is not None:
        ss.show_unconfigured_oauth_on_login = body.show_unconfigured_oauth_on_login
    if body.ui_login_background is not None:
        ss.ui_login_background = body.ui_login_background
    if body.ui_header_timezone_1 is not None:
        ss.ui_header_timezone_1 = _validate_ui_header_timezone_id(body.ui_header_timezone_1)
    if body.ui_header_timezone_2 is not None:
        ss.ui_header_timezone_2 = _validate_ui_header_timezone_id(body.ui_header_timezone_2)
    _tz1 = ss.ui_header_timezone_1 or "UTC"
    _tz2 = ss.ui_header_timezone_2 or "Europe/Berlin"
    if _tz1 == _tz2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die beiden Header-Zeitzonen müssen unterschiedlich sein.",
        )
    session.add(ss)
    session.commit()
    session.refresh(ss)
    system_after = _system_settings_audit_snapshot(ss)
    system_audit_details = _build_system_settings_audit_details(system_before, system_after)
    if system_audit_details:
        log_audit(session, "system_settings_update", "settings", None, system_audit_details, current_user)
    if ss.enable_error_reporting is False:
        shutdown_posthog()
    # Dependency-Audit-Job neu planen (Cron/Enabled geändert)
    try:
        from app.services.dependency_audit import schedule_dependency_audit_job
        schedule_dependency_audit_job()
    except Exception as e:
        logger.warning("Dependency-Audit-Job nach Einstellungs-Update nicht neu geplant: %s", e)
    return SystemSettingsResponse(
        is_setup_completed=ss.is_setup_completed,
        enable_telemetry=ss.enable_telemetry,
        enable_error_reporting=ss.enable_error_reporting,
        dependency_audit_enabled=getattr(ss, "dependency_audit_enabled", True),
        dependency_audit_cron=getattr(ss, "dependency_audit_cron", "0 3 * * *") or "0 3 * * *",
        login_branding_logo_url=getattr(ss, "login_branding_logo_url", None),
        ui_show_attribution=bool(getattr(ss, "ui_show_attribution", True)),
        ui_show_version=bool(getattr(ss, "ui_show_version", True)),
        show_unconfigured_oauth_on_login=bool(getattr(ss, "show_unconfigured_oauth_on_login", True)),
        ui_login_background=_normalize_ui_login_background(getattr(ss, "ui_login_background", None)),
        ui_header_timezone_1=getattr(ss, "ui_header_timezone_1", None) or "UTC",
        ui_header_timezone_2=getattr(ss, "ui_header_timezone_2", None) or "Europe/Berlin",
    )


@router.post("/trigger-test-exception")
async def trigger_test_exception_backend(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Dict[str, str]:
    """
    Nur in ENVIRONMENT=development. Sendet eine Test-Exception an PostHog (Backend).
    Nur wirksam, wenn Fehlerberichte (enable_error_reporting) aktiviert sind.
    """
    if config.ENVIRONMENT != "development":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nur in ENVIRONMENT=development verfügbar.",
        )
    u = str(request.url)
    url_no_query = u.split("?")[0] if "?" in u else u
    exc = RuntimeError(
        "Fast-Flow Backend-Test: Test-Exception für PostHog (manuell aus Einstellungen, ENVIRONMENT=development). "
        "Kein echter Fehler. $fastflow_backend_test=True."
    )
    capture_exception(
        exc,
        session,
        properties={
            "$fastflow_backend_test": True,
            "description": "Manuell aus Einstellungen ausgelöst (Backend).",
            "$current_url": url_no_query,
            "$request_path": request.url.path,
            "$request_method": request.method,
        },
    )
    return {"message": "Test-Exception an PostHog gesendet (Backend). In PostHog prüfen."}


@router.get("/system-status", response_model=Dict[str, Any])
async def get_system_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Gibt Readiness-Checks für die UI zurück (DB, Docker/K8s, UV-Cache, Disk, Inodes).
    Gleiche Logik wie GET /api/ready, aber auth-pflichtig und immer 200.
    """
    from app.core.readiness import run_readiness_checks
    checks, ok = run_readiness_checks()
    return {
        "status": "ready" if ok else "not_ready",
        "checks": checks,
        "version": config.VERSION,
    }


@router.get("/concurrency", response_model=Dict[str, Any])
async def get_concurrency(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Gibt Concurrency-Status zurück: aktive Runs, Limit, Auslastung, Executor-Typ.
    """
    from app.executor import _running_containers
    limit = config.MAX_CONCURRENT_RUNS
    active = len(_running_containers)
    utilization = (active / limit) if limit > 0 else 0.0
    return {
        "active_runs": active,
        "concurrency_limit": limit,
        "utilization": round(utilization, 4),
        "executor": config.PIPELINE_EXECUTOR,
    }


@router.get("/storage", response_model=Dict[str, Any])
async def get_storage_stats(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Gibt Speicherplatz-Statistiken zurück.
    
    Returns:
        Dictionary mit:
        - log_files_count: Anzahl Log-Dateien
        - log_files_size_bytes: Gesamtgröße der Log-Dateien in Bytes
        - log_files_size_mb: Gesamtgröße der Log-Dateien in MB
        - total_disk_space_bytes: Gesamter Speicherplatz in Bytes
        - total_disk_space_gb: Gesamter Speicherplatz in GB
        - used_disk_space_bytes: Verwendeter Speicherplatz in Bytes
        - used_disk_space_gb: Verwendeter Speicherplatz in GB
        - free_disk_space_bytes: Freier Speicherplatz in Bytes
        - free_disk_space_gb: Freier Speicherplatz in GB
        - log_files_percentage: Anteil der Log-Dateien am Gesamtspeicherplatz in Prozent
        - database_size_bytes: Größe der Datenbank in Bytes (falls verfügbar)
        - database_size_mb: Größe der Datenbank in MB (falls verfügbar)
        - database_size_gb: Größe der Datenbank in GB (falls verfügbar)
        - database_percentage: Anteil der Datenbank am Gesamtspeicherplatz in Prozent (falls verfügbar)
        - inode_total, inode_free, inode_used, inode_used_percent: Inode-Statistik (nur Unix, df -i)
        - uv_cache_dir, uv_cache_size_*, uv_cache_percentage: UV-Paketcache (Größen nur wenn UV_STORAGE_STATS=true)
        - uv_python_install_dir, uv_python_install_size_*, uv_python_percentage: UV-Python-Installs (ebenfalls)
        - uv_storage_stats_enabled: ob Größen ermittelt wurden (Env UV_STORAGE_STATS)
        - uv_pre_heat, default_python_version: Runner-Konfiguration (Env)
    """
    try:
        database_size_bytes = _query_database_size_bytes(session)
        # rglob über große UV-Cache-Bäume blockiert sonst den Event-Loop (Liveness / UI)
        return await asyncio.to_thread(_sync_build_storage_stats_payload, database_size_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Speicherplatz-Statistiken: {str(e)}"
        )


@router.post("/test-email", response_model=Dict[str, str])
async def test_email(
    current_user: User = Depends(require_write)
) -> Dict[str, str]:
    """
    Sendet eine Test-E-Mail mit aktuellen E-Mail-Einstellungen.
    
    Returns:
        Dictionary mit Erfolgs- oder Fehlermeldung
    """
    if not config.EMAIL_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-Mail-Benachrichtigungen sind nicht aktiviert"
        )
    
    if not config.SMTP_HOST or not config.SMTP_FROM or not config.EMAIL_RECIPIENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-Mail-Konfiguration unvollständig (SMTP_HOST, SMTP_FROM, EMAIL_RECIPIENTS erforderlich)"
        )
    
    try:
        # Erstelle einen Mock-Run für Test-E-Mail
        from datetime import datetime, timezone
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            exit_code=1
        )
        
        await send_email_notification(test_run, RunStatus.FAILED)
        
        return {
            "status": "success",
            "message": f"Test-E-Mail erfolgreich an {', '.join(config.EMAIL_RECIPIENTS)} gesendet"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Senden der Test-E-Mail: {str(e)}"
        )


@router.post("/test-teams", response_model=Dict[str, str])
async def test_teams(
    current_user: User = Depends(require_write)
) -> Dict[str, str]:
    """
    Sendet eine Test-Teams-Nachricht mit aktuellen Teams-Einstellungen.
    
    Returns:
        Dictionary mit Erfolgs- oder Fehlermeldung
    """
    if not config.TEAMS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Teams-Benachrichtigungen sind nicht aktiviert"
        )
    
    if not config.TEAMS_WEBHOOK_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Teams-Webhook-URL ist nicht konfiguriert"
        )
    
    try:
        # Erstelle einen Mock-Run für Test-Teams-Nachricht
        from datetime import datetime, timezone
        from uuid import uuid4
        
        test_run = PipelineRun(
            id=uuid4(),
            pipeline_name="test-pipeline",
            status=RunStatus.FAILED,
            log_file="test.log",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            exit_code=1
        )
        
        await send_teams_notification(test_run, RunStatus.FAILED)
        
        return {
            "status": "success",
            "message": "Test-Teams-Nachricht erfolgreich gesendet"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Senden der Test-Teams-Nachricht: {str(e)}"
        )


class BackupFailureItem(BaseModel):
    run_id: str
    pipeline_name: str
    error_message: str
    created_at: str


class BackupFailuresResponse(BaseModel):
    failures: List[BackupFailureItem]
    last_backup_at: Optional[str] = None


class S3ConnectivityTestResponse(BaseModel):
    success: bool
    message: str
    tested_at: str


@router.get("/backup-failures", response_model=BackupFailuresResponse)
async def get_backup_failures_endpoint(
    current_user: User = Depends(get_current_user),
) -> BackupFailuresResponse:
    """
    Gibt die letzten S3-Backup-Fehler und den Zeitstempel des letzten erfolgreichen
    Backups zurück (für UI-Benachrichtigungen und Anzeige in Einstellungen).
    Erfordert Authentifizierung.
    """
    items = [
        BackupFailureItem(
            run_id=f["run_id"],
            pipeline_name=f["pipeline_name"],
            error_message=f["error_message"],
            created_at=f["created_at"],
        )
        for f in get_backup_failures()
    ]
    ts = get_last_backup_timestamp()
    last_backup_at = ts.isoformat() if ts else None
    return BackupFailuresResponse(failures=items, last_backup_at=last_backup_at)


@router.post("/s3/test", response_model=S3ConnectivityTestResponse)
async def test_s3_connectivity(
    current_user: User = Depends(require_admin),
    session: Session = Depends(get_session),
) -> S3ConnectivityTestResponse:
    """
    Testet die aktuelle S3-Konfiguration (HeadBucket) und speichert den letzten
    Teststatus in OrchestratorSettings.
    """
    tested_at = datetime.now(timezone.utc)
    row = get_orchestrator_settings_or_default(session)
    try:
        if not config.S3_BACKUP_ENABLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3-Backup ist deaktiviert")
        if not config.S3_ENDPOINT_URL or not config.S3_BUCKET:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Endpoint/Bucket ist unvollständig")
        if not config.S3_ACCESS_KEY or not config.S3_SECRET_ACCESS_KEY:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="S3 Credentials sind unvollständig")

        boto_cfg = BotoConfig(s3={"addressing_style": "path"}) if config.S3_USE_PATH_STYLE else None
        client = boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT_URL,
            aws_access_key_id=config.S3_ACCESS_KEY,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
            region_name=config.S3_REGION,
            config=boto_cfg,
        )
        client.head_bucket(Bucket=config.S3_BUCKET)
        row.s3_last_test_at = tested_at
        row.s3_last_test_status = "success"
        row.s3_last_test_error = None
        session.add(row)
        session.commit()
        session.refresh(row)
        log_audit(session, "s3_connectivity_test", "settings", None, {"status": "success"}, current_user)
        return S3ConnectivityTestResponse(
            success=True,
            message="S3-Verbindung erfolgreich getestet.",
            tested_at=tested_at.isoformat(),
        )
    except HTTPException as e:
        row.s3_last_test_at = tested_at
        row.s3_last_test_status = "failed"
        row.s3_last_test_error = str(e.detail)
        session.add(row)
        session.commit()
        session.refresh(row)
        log_audit(session, "s3_connectivity_test", "settings", None, {"status": "failed", "reason": str(e.detail)}, current_user)
        raise
    except Exception as e:
        logger.warning("S3 connectivity test failed: %s", e)
        row.s3_last_test_at = tested_at
        row.s3_last_test_status = "failed"
        row.s3_last_test_error = "S3-Verbindungstest fehlgeschlagen. Bitte Konfiguration und Netzwerk prüfen."
        session.add(row)
        session.commit()
        session.refresh(row)
        log_audit(session, "s3_connectivity_test", "settings", None, {"status": "failed"}, current_user)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="S3-Verbindungstest fehlgeschlagen. Bitte Konfiguration und Netzwerk prüfen.",
        )


@router.post("/cleanup/force", response_model=Dict[str, Any])
async def force_cleanup(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_write)
) -> Dict[str, Any]:
    """
    Führt einen manuellen Force-Flush (Cleanup) durch.
    
    Führt sowohl Log-Cleanup als auch Docker-Ressourcen-Cleanup aus.
    
    Args:
        session: SQLModel Session
        
    Returns:
        Dictionary mit Cleanup-Statistiken und detaillierten Informationen
    """
    try:
        # Sammle Informationen über was geflusht wird
        cleanup_info = {
            "log_cleanup": {
                "description": "Bereinigt Log-Dateien, Metrics-Dateien und Datenbank-Einträge",
                "actions": []
            },
            "docker_cleanup": {
                "description": "Bereinigt verwaiste Docker-Container und Volumes (nur bei PIPELINE_EXECUTOR=docker)",
                "actions": []
            }
        }
        if config.PIPELINE_EXECUTOR == "docker":
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht verwaiste Container mit Label 'fastflow-run-id' (ohne zugehörigen DB-Eintrag)"
            )
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht beendete Container mit Label 'fastflow-run-id'"
            )
            cleanup_info["docker_cleanup"]["actions"].append(
                "Löscht verwaiste Volumes mit Label 'fastflow-run-id'"
            )
        else:
            cleanup_info["docker_cleanup"]["actions"].append("Nicht aktiv (PIPELINE_EXECUTOR=kubernetes)")
        
        # Log-Cleanup Informationen
        if config.LOG_RETENTION_RUNS:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Löscht älteste Runs pro Pipeline (max. {config.LOG_RETENTION_RUNS} Runs pro Pipeline behalten)"
            )
        if config.LOG_RETENTION_DAYS:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Löscht Runs älter als {config.LOG_RETENTION_DAYS} Tage"
            )
        if config.LOG_MAX_SIZE_MB:
            cleanup_info["log_cleanup"]["actions"].append(
                f"Kürzt oder löscht Log-Dateien größer als {config.LOG_MAX_SIZE_MB} MB"
            )
        if not cleanup_info["log_cleanup"]["actions"]:
            cleanup_info["log_cleanup"]["actions"].append(
                "Keine Log-Cleanup-Regeln konfiguriert"
            )
        
        # Log-Cleanup durchführen
        log_stats = await cleanup_logs(session)
        
        # Docker-Ressourcen-Cleanup (nur bei PIPELINE_EXECUTOR=docker)
        docker_stats = await cleanup_docker_resources() if config.PIPELINE_EXECUTOR == "docker" else {}
        
        # Detaillierte Zusammenfassung erstellen
        summary = []
        
        if log_stats.get("deleted_runs", 0) > 0:
            summary.append(f"{log_stats['deleted_runs']} Runs aus Datenbank gelöscht")
        if log_stats.get("deleted_logs", 0) > 0:
            summary.append(f"{log_stats['deleted_logs']} Log-Dateien gelöscht")
        if log_stats.get("deleted_metrics", 0) > 0:
            summary.append(f"{log_stats['deleted_metrics']} Metrics-Dateien gelöscht")
        if log_stats.get("truncated_logs", 0) > 0:
            summary.append(f"{log_stats['truncated_logs']} Log-Dateien gekürzt")
        
        if docker_stats.get("deleted_containers", 0) > 0:
            summary.append(f"{docker_stats['deleted_containers']} Docker-Container gelöscht")
        if docker_stats.get("deleted_volumes", 0) > 0:
            summary.append(f"{docker_stats['deleted_volumes']} Docker-Volumes gelöscht")
        
        if not summary:
            summary.append("Keine Ressourcen zum Bereinigen gefunden")
        log_audit(
            session, "cleanup_force", "settings", None,
            details={"summary": summary, "log_stats": log_stats},
            user=current_user,
        )
        return {
            "status": "success",
            "message": "Cleanup erfolgreich abgeschlossen",
            "summary": summary,
            "cleanup_info": cleanup_info,
            "log_cleanup": log_stats,
            "docker_cleanup": docker_stats,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Cleanup: {str(e)}"
        )


@router.get("/system-metrics", response_model=Dict[str, Any])
async def get_system_metrics(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Gibt System-Metriken zurück (Docker-Container, RAM, CPU).
    
    Erfordert Authentifizierung.
    
    Returns:
        Dictionary mit:
        - active_containers: Anzahl aktiver Pipeline-Container
        - containers_ram_mb: Gesamter RAM-Verbrauch der Container in MB
        - containers_cpu_percent: Gesamter CPU-Verbrauch der Container in Prozent
        - api_ram_mb: RAM-Verbrauch der API in MB
        - api_cpu_percent: CPU-Verbrauch der API in Prozent
        - system_ram_total_mb: Gesamter System-RAM in MB
        - system_ram_used_mb: Verwendeter System-RAM in MB
        - system_ram_percent: System-RAM-Auslastung in Prozent
        - system_cpu_percent: System-CPU-Auslastung in Prozent
        - container_details: Liste mit Details zu jedem Container
    """
    try:
        metrics = {
            "active_containers": 0,
            "containers_ram_mb": 0.0,
            "containers_cpu_percent": 0.0,
            "api_ram_mb": 0.0,
            "api_cpu_percent": 0.0,
            "system_ram_total_mb": 0.0,
            "system_ram_used_mb": 0.0,
            "system_ram_percent": 0.0,
            "system_cpu_percent": 0.0,
            "container_details": []
        }
        
        # API-Prozess-Metriken (psutil)
        try:
            process = psutil.Process()
            api_memory_info = process.memory_info()
            metrics["api_ram_mb"] = round(api_memory_info.rss / (1024 * 1024), 2)
            metrics["api_cpu_percent"] = round(process.cpu_percent(interval=0.1), 2)
        except Exception as e:
            logger.warning(f"Fehler beim Ermitteln der API-Metriken: {e}")
        
        # System-Metriken
        try:
            system_memory = psutil.virtual_memory()
            metrics["system_ram_total_mb"] = round(system_memory.total / (1024 * 1024), 2)
            metrics["system_ram_used_mb"] = round(system_memory.used / (1024 * 1024), 2)
            metrics["system_ram_percent"] = round(system_memory.percent, 2)
            metrics["system_cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 2)
        except Exception as e:
            logger.warning(f"Fehler beim Ermitteln der System-Metriken: {e}")
        
        # Docker-Container-Metriken (nur bei PIPELINE_EXECUTOR=docker)
        if config.PIPELINE_EXECUTOR == "docker":
            try:
                docker_client = _get_docker_client()
                containers = docker_client.containers.list(
                    filters={"label": "fastflow-run-id"},
                    all=False
                )
                metrics["active_containers"] = len(containers)
                total_ram_mb = 0.0
                total_cpu_percent = 0.0
                container_details = []
                for container in containers:
                    try:
                        stats = container.stats(stream=False)
                        memory_usage = stats.get("memory_stats", {}).get("usage", 0)
                        memory_limit = stats.get("memory_stats", {}).get("limit", 0)
                        ram_mb = memory_usage / (1024 * 1024) if memory_usage else 0
                        ram_percent = (memory_usage / memory_limit * 100) if memory_limit > 0 else 0
                        cpu_percent = 0.0
                        cpu_stats = stats.get("cpu_stats", {})
                        precpu_stats = stats.get("precpu_stats", {})
                        if cpu_stats and precpu_stats:
                            cpu_delta = (
                                cpu_stats.get("cpu_usage", {}).get("total_usage", 0) -
                                precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
                            )
                            system_delta = (
                                cpu_stats.get("system_cpu_usage", 0) -
                                precpu_stats.get("system_cpu_usage", 0)
                            )
                            if system_delta > 0:
                                online_cpus = len(cpu_stats.get("cpu_usage", {}).get("percpu_usage", [])) or 1
                                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                        total_ram_mb += ram_mb
                        total_cpu_percent += cpu_percent
                        container_details.append({
                            "run_id": container.labels.get("fastflow-run-id", "unknown"),
                            "pipeline_name": container.labels.get("fastflow-pipeline", "unknown"),
                            "container_id": container.id[:12],
                            "ram_mb": round(ram_mb, 2),
                            "ram_percent": round(ram_percent, 2),
                            "cpu_percent": round(cpu_percent, 2),
                            "status": container.status
                        })
                    except Exception as e:
                        logger.warning(f"Fehler beim Ermitteln der Container-Stats für {container.id}: {e}")
                metrics["containers_ram_mb"] = round(total_ram_mb, 2)
                metrics["containers_cpu_percent"] = round(total_cpu_percent, 2)
                metrics["container_details"] = container_details
            except RuntimeError:
                pass
            except Exception as e:
                logger.warning(f"Fehler beim Ermitteln der Docker-Container-Metriken: {e}")

        # Kubernetes: aktive Pipeline-Jobs (Pods) für Aktive Container / RAM / CPU
        if config.PIPELINE_EXECUTOR == "kubernetes":
            try:
                k8s_metrics = await asyncio.get_running_loop().run_in_executor(
                    None, get_kubernetes_system_metrics
                )
                metrics["active_containers"] = k8s_metrics.get("active_containers", 0)
                metrics["containers_ram_mb"] = k8s_metrics.get("containers_ram_mb", 0.0)
                metrics["containers_cpu_percent"] = k8s_metrics.get("containers_cpu_percent", 0.0)
                metrics["container_details"] = k8s_metrics.get("container_details", [])
            except Exception as e:
                logger.warning(f"Fehler beim Ermitteln der Kubernetes-System-Metriken: {e}")
        
        return metrics
        
    except Exception as e:
        logger.exception("Fehler beim Abrufen der System-Metriken")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_500_detail(e),
        )
