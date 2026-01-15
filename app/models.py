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
    User-Model.
    
    Speichert Benutzer-Informationen für Authentifizierung.
    Passwörter werden gehasht gespeichert (passlib bcrypt).
    Unterstützt lokale Authentifizierung und Microsoft OAuth (zukünftig).
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
    password_hash: Optional[str] = Field(
        default=None,
        description="Gehashtes Passwort (bcrypt, optional für Microsoft-User)"
    )
    email: Optional[str] = Field(
        default=None,
        index=True,
        description="E-Mail-Adresse (optional, für Microsoft-Auth)"
    )
    role: UserRole = Field(
        default=UserRole.READONLY,
        description="Benutzer-Rolle (readonly, write, admin)"
    )
    blocked: bool = Field(
        default=False,
        description="Ist der Benutzer blockiert?"
    )
    invitation_token: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="Einladungs-Token (optional)"
    )
    invitation_expires_at: Optional[datetime] = Field(
        default=None,
        description="Ablauf-Zeitpunkt der Einladung (UTC, optional)"
    )
    microsoft_id: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="Microsoft OAuth ID (optional, für zukünftige Microsoft-Auth)"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


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
