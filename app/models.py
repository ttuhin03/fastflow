"""
Models Module.

Dieses Modul definiert alle SQLModel-Models für die Datenbank:
- Pipeline (Metadaten)
- PipelineRun (Ausführungs-Historie)
- ScheduledJob (Geplante Jobs)
- Secret (Verschlüsselte Secrets)
- User (Benutzer für Authentifizierung)
- Session (Session-Tokens für persistente Authentifizierung)
"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4, UUID
from enum import Enum
from sqlalchemy import Text
from sqlmodel import SQLModel, Field, JSON, Column


class RunStatus(str, Enum):
    """Status eines Pipeline-Runs."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    WARNING = "WARNING"


class TriggerType(str, Enum):
    """Typ des Scheduler-Triggers."""
    CRON = "CRON"
    INTERVAL = "INTERVAL"


class UserRole(str, Enum):
    """Rolle eines Benutzers."""
    READONLY = "READONLY"
    WRITE = "WRITE"
    ADMIN = "ADMIN"


class UserStatus(str, Enum):
    """Status eines Benutzers (Zugriff/Beitrittsanfrage)."""
    ACTIVE = "active"
    PENDING = "pending"
    REJECTED = "rejected"


class Pipeline(SQLModel, table=True):
    """
    Pipeline-Metadaten-Model.
    
    Speichert Metadaten über verfügbare Pipelines, inklusive
    Statistiken und Cache-Status.
    """
    __tablename__ = "pipelines"
    
    pipeline_name: str = Field(primary_key=True, description="Name der Pipeline")
    has_requirements: bool = Field(
        default=False,
        description="Wurde eine requirements.txt gefunden?"
    )
    last_cache_warmup: Optional[datetime] = Field(
        default=None,
        description="Zeitstempel des letzten erfolgreichen uv pip compile"
    )
    total_runs: int = Field(
        default=0,
        description="Gesamtanzahl Runs (Zähler, resetbar)"
    )
    successful_runs: int = Field(
        default=0,
        description="Anzahl erfolgreicher Runs (resetbar)"
    )
    failed_runs: int = Field(
        default=0,
        description="Anzahl fehlgeschlagener Runs (resetbar)"
    )
    webhook_runs: int = Field(
        default=0,
        description="Anzahl webhook-getriggerter Runs (resetbar)"
    )


class PipelineRun(SQLModel, table=True):
    """
    PipelineRun-Model.
    
    Speichert Informationen über jeden Pipeline-Ausführung,
    inklusive Status, Logs, Metrics und Environment-Variablen.
    """
    __tablename__ = "pipeline_runs"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Run-ID"
    )
    pipeline_name: str = Field(
        index=True,
        description="Name der Pipeline"
    )
    status: RunStatus = Field(
        default=RunStatus.PENDING,
        description="Aktueller Status des Runs"
    )
    log_file: str = Field(
        description="Pfad zur Log-Datei"
    )
    metrics_file: Optional[str] = Field(
        default=None,
        description="Pfad zur Metrics-Datei (CPU/RAM über Zeit)"
    )
    env_vars: Dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Environment-Variablen (Secrets + Parameter)"
    )
    parameters: Dict[str, str] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Normale Parameter (nicht verschlüsselt)"
    )
    uv_version: Optional[str] = Field(
        default=None,
        description="Die genutzte uv-Version für Reproduzierbarkeit"
    )
    setup_duration: Optional[float] = Field(
        default=None,
        description="Zeit in Sekunden, die uv für das Bereitstellen der Umgebung benötigt hat"
    )
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Start-Zeitpunkt (UTC)"
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        description="End-Zeitpunkt (UTC, optional)"
    )
    exit_code: Optional[int] = Field(
        default=None,
        description="Exit-Code des Container-Prozesses"
    )
    triggered_by: str = Field(
        default="manual",
        description="Trigger-Quelle: 'manual', 'webhook', oder 'scheduler'"
    )


class RunCellLog(SQLModel, table=True):
    """
    Zellen-Log für Notebook-Pipeline-Runs.
    
    Pro Run und Code-Zelle eine Zeile: Status, stdout, stderr, optionale Ausgaben (z. B. Bilder).
    """
    __tablename__ = "run_cell_logs"
    __table_args__ = ({"sqlite_autoincrement": False})

    run_id: UUID = Field(foreign_key="pipeline_runs.id", primary_key=True, description="Run-ID")
    cell_index: int = Field(primary_key=True, description="Index der Code-Zelle (0-basiert)")
    status: str = Field(default="RUNNING", description="SUCCESS | FAILED | RETRYING | RUNNING")
    stdout: str = Field(default="", sa_column=Column(Text()), description="Stdout der Zelle")
    stderr: str = Field(default="", sa_column=Column(Text()), description="Stderr der Zelle")
    outputs: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Optionale Ausgaben (z. B. Bilder als Base64)",
    )


class ScheduledJob(SQLModel, table=True):
    """
    ScheduledJob-Model.
    
    Speichert geplante Pipeline-Ausführungen mit Cron- oder
    Interval-Triggers.
    """
    __tablename__ = "scheduled_jobs"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Job-ID"
    )
    pipeline_name: str = Field(
        index=True,
        description="Name der Pipeline"
    )
    trigger_type: TriggerType = Field(
        description="Typ des Triggers (CRON oder INTERVAL)"
    )
    trigger_value: str = Field(
        description="Cron-Expression oder Interval-String"
    )
    enabled: bool = Field(
        default=True,
        description="Job aktiviert/deaktiviert"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


class Secret(SQLModel, table=True):
    """
    Secret-Model.
    
    Speichert verschlüsselte Secrets in der Datenbank.
    Secrets werden mit Fernet verschlüsselt gespeichert.
    Parameter (is_parameter=True) werden nicht verschlüsselt gespeichert.
    """
    __tablename__ = "secrets"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Secret-ID"
    )
    key: str = Field(
        unique=True,
        index=True,
        description="Secret-Key (eindeutig)"
    )
    value: str = Field(
        description="Verschlüsselter Secret-Wert (oder unverschlüsselt wenn is_parameter=True)"
    )
    is_parameter: bool = Field(
        default=False,
        description="True wenn Parameter (nicht verschlüsselt), False wenn Secret (verschlüsselt)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Erstellungs-Zeitpunkt (UTC)"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Letzte Aktualisierung (UTC)"
    )


class User(SQLModel, table=True):
    """
    User-Model. Authentifizierung via GitHub OAuth, Google OAuth (und Einladung).
    """
    __tablename__ = "users"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige User-ID"
    )
    username: str = Field(
        unique=True,
        index=True,
        description="Benutzername (eindeutig)"
    )
    email: Optional[str] = Field(
        default=None,
        index=True,
        description="E-Mail (von GitHub/Google oder manuell)"
    )
    role: UserRole = Field(
        default=UserRole.READONLY,
        description="Benutzer-Rolle (readonly, write, admin)"
    )
    blocked: bool = Field(
        default=False,
        description="Ist der Benutzer blockiert?"
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        description="active=Zugriff, pending=Beitrittsanfrage, rejected=abgelehnt"
    )
    microsoft_id: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="Microsoft OAuth ID (optional, für zukünftige Microsoft-Auth)"
    )
    github_id: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="GitHub OAuth ID (optional, für GitHub-Login)"
    )
    github_login: Optional[str] = Field(
        default=None,
        description="GitHub-Benutzername (login) für Profile-Link"
    )
    google_id: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="Google OAuth ID (optional, für Google-Login)"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        description="Profilbild-URL (von OAuth-Provider)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


class Invitation(SQLModel, table=True):
    """
    Einladung für neuen User (Token-Einladung via GitHub OAuth).
    Token wird an /invite?token=... übergeben; state im OAuth = token.
    """
    __tablename__ = "invitations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    recipient_email: str = Field(index=True)
    token: str = Field(unique=True, index=True)  # secrets.token_urlsafe(32)
    is_used: bool = Field(default=False)
    expires_at: datetime = Field(...)  # Pflicht, Token läuft ab
    role: UserRole = Field(default=UserRole.READONLY)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SystemSettings(SQLModel, table=True):
    """
    SystemSettings-Model (Singleton, id=1).
    
    Steuert First-Run-Wizard, Error-Tracking (Phase 1) und
    zukünftig Telemetrie (Phase 2: Product Analytics, Session Replay, Survey).
    """
    __tablename__ = "system_settings"

    id: int = Field(primary_key=True, default=1, description="Singleton (immer 1)")
    is_setup_completed: bool = Field(default=False, description="Wizard abgeschlossen?")
    enable_telemetry: bool = Field(
        default=False,
        description="Phase 2: Nutzungsstatistiken, Product Analytics, Session Replay, Survey",
    )
    enable_error_reporting: bool = Field(
        default=False,
        description="Phase 1: PostHog Error-Tracking (Autocapture + FastAPI-Handler)",
    )
    telemetry_distinct_id: Optional[str] = Field(
        default=None,
        description="Anonyme UUID für PostHog distinct_id (keine E-Mail/Klarnamen)",
    )
    dependency_audit_enabled: bool = Field(
        default=False,
        description="Automatische Sicherheitsprüfung (pip-audit) täglich; Benachrichtigung bei Schwachstellen",
    )
    dependency_audit_cron: str = Field(
        default="0 3 * * *",
        description="Cron-Ausdruck für Zeitpunkt (Standard: 3:00 Uhr täglich)",
    )


class OrchestratorSettings(SQLModel, table=True):
    """
    OrchestratorSettings-Model (Singleton, id=1).

    Persistente Einstellungen aus der Settings-UI. Werte aus der DB
    überschreiben beim Start die Environment-Variablen (config).
    None = kein Override, config-Wert bleibt.
    """
    __tablename__ = "orchestrator_settings"

    id: int = Field(primary_key=True, default=1, description="Singleton (immer 1)")
    # Log & Cleanup
    log_retention_runs: Optional[int] = Field(default=None)
    log_retention_days: Optional[int] = Field(default=None)
    log_max_size_mb: Optional[int] = Field(default=None)
    # Concurrency & Timeouts
    max_concurrent_runs: Optional[int] = Field(default=None)
    container_timeout: Optional[int] = Field(default=None)
    retry_attempts: Optional[int] = Field(default=None)
    # Git Sync
    auto_sync_enabled: Optional[bool] = Field(default=None)
    auto_sync_interval: Optional[int] = Field(default=None)
    # E-Mail
    email_enabled: Optional[bool] = Field(default=None)
    smtp_host: Optional[str] = Field(default=None)
    smtp_port: Optional[int] = Field(default=None)
    smtp_user: Optional[str] = Field(default=None)
    smtp_password_encrypted: Optional[str] = Field(default=None)
    smtp_from: Optional[str] = Field(default=None)
    email_recipients: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Teams
    teams_enabled: Optional[bool] = Field(default=None)
    teams_webhook_url: Optional[str] = Field(default=None)


class Session(SQLModel, table=True):
    """
    Session-Model.

    Speichert Session-Tokens in der Datenbank für persistente
    Authentifizierung. Verhindert Session-Verlust bei App-Neustart.
    """
    __tablename__ = "sessions"
    
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Session-ID"
    )
    token: str = Field(
        unique=True,
        index=True,
        description="JWT-Token (eindeutig)"
    )
    user_id: UUID = Field(
        foreign_key="users.id",
        index=True,
        description="Verknüpfte User-ID"
    )
    expires_at: datetime = Field(
        description="Ablauf-Zeitpunkt (UTC)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Erstellungs-Zeitpunkt (UTC)"
    )
