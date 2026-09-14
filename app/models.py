"""
Models Module.

Dieses Modul definiert alle SQLModel-Models für die Datenbank:
- Pipeline (Metadaten)
- PipelineRun (Ausführungs-Historie)
- ScheduledJob (Geplante Jobs)
- Secret (Verschlüsselte Secrets)
- User (Benutzer für Authentifizierung)
- Session (Session-Tokens für persistente Authentifizierung)
- ApiToken (persönliche API-Tokens für nicht-interaktive Clients)
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from sqlalchemy import Enum as SAEnum, Text
from sqlmodel import SQLModel, Field, JSON, Column


# Foreign-Key-Ziel der users-Tabelle. Vier Modelle verweisen darauf; als Konstante,
# damit ein Umbenennen der Tabelle nicht an ebenso vielen Stellen einzeln nachgezogen
# werden muss – ein übersehenes Vorkommen fiele erst beim Anlegen des Schemas auf.
USERS_ID_FK = "users.id"


def _utc_now() -> datetime:
    """Gibt die aktuelle UTC-Zeit zurück (zeitzone-aware)."""
    return datetime.now(timezone.utc)


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
    DATE = "DATE"


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


class ApiTokenScope(str, Enum):
    """Berechtigungsbereich eines API-Tokens.

    Geschnitten nach Risikoklasse, nicht nach Endpoint – ein Token für
    Laufzeit-Statistiken soll nicht zwangsläufig auch Logs lesen dürfen.

    - READ:   Metadaten (Pipelines, Runs, Stats, Dependencies, Graph)
    - LOGS:   Log-Inhalte und Cell-stdout/stderr (potenziell Nutzdaten/Credentials)
    - SOURCE: Pipeline-Quelldateien und pipeline.json
    - RUN:    Runs starten, abbrechen, wiederholen (setzt UserRole.WRITE voraus)

    Es gibt bewusst keinen Admin-Scope: Settings, Nutzerverwaltung, Secrets und
    Deploy-Keys bleiben ausschließlich über eine Browser-Session erreichbar,
    damit ein entwendetes Token die Instanz nicht umkonfigurieren kann.
    """
    READ = "read"
    LOGS = "logs"
    SOURCE = "source"
    RUN = "run"


class EphemeralTokenType(str, Enum):
    """Typ eines DB-gebundenen Kurzzeit-Tokens (siehe EphemeralToken)."""
    ACCOUNT_LINK = "account_link"
    LOG_DOWNLOAD = "log_download"


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


class PipelineDailyStat(SQLModel, table=True):
    """
    Tägliche Run-Statistiken pro Pipeline (persistent, wird beim Cleanup nicht gelöscht).
    Wird beim Run-Ende erhöht; Kalender liest daraus, sodass Anzahlen nach Flush erhalten bleiben.
    """
    __tablename__ = "pipeline_daily_stats"

    pipeline_name: str = Field(foreign_key="pipelines.pipeline_name", primary_key=True)
    day: date = Field(primary_key=True, description="Kalendertag (UTC)")
    total_runs: int = Field(default=0)
    successful_runs: int = Field(default=0)
    failed_runs: int = Field(default=0)


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
        index=True,
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
        default_factory=_utc_now,
        index=True,
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
        description="Trigger-Quelle: 'manual', 'webhook', 'scheduler', 'daemon_restart', 'downstream'"
    )
    run_config_id: Optional[str] = Field(
        default=None,
        index=True,
        description="Run-Konfiguration aus pipeline.json schedules (z.B. prod, staging)"
    )
    git_sha: Optional[str] = Field(
        default=None,
        description="Git-Commit-SHA (HEAD) des Pipeline-Repos zum Startzeitpunkt (Reproduzierbarkeit)"
    )
    git_branch: Optional[str] = Field(
        default=None,
        description="Git-Branch des Pipeline-Repos zum Startzeitpunkt"
    )
    git_commit_message: Optional[str] = Field(
        default=None,
        description="Erste Zeile der Git-Commit-Message zum Startzeitpunkt"
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
    start_date: Optional[datetime] = Field(
        default=None,
        description="Optionaler Start des Zeitraums, in dem der Schedule läuft (UTC)"
    )
    end_date: Optional[datetime] = Field(
        default=None,
        description="Optionales Ende des Zeitraums (UTC)"
    )
    source: str = Field(
        default="api",
        description="Herkunft: 'api' (UI/API) oder 'pipeline_json'"
    )
    run_config_id: Optional[str] = Field(
        default=None,
        index=True,
        description="Run-Konfiguration aus pipeline.json schedules (z.B. prod, staging)"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


class DownstreamTrigger(SQLModel, table=True):
    """
    Downstream-Trigger für Pipeline-Chaining (UI-konfiguriert).

    Wenn Pipeline A (upstream) fertig ist, wird Pipeline B (downstream) gestartet,
    abhängig von on_success/on_failure. Überschneidet sich mit pipeline.json
    downstream_triggers – beide Quellen werden beim Trigger-Vorgang zusammengeführt.
    """
    __tablename__ = "downstream_triggers"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Trigger-ID",
    )
    upstream_pipeline: str = Field(
        index=True,
        description="Name der Upstream-Pipeline (A)",
    )
    downstream_pipeline: str = Field(
        index=True,
        description="Name der Downstream-Pipeline (B)",
    )
    on_success: bool = Field(
        default=True,
        description="Pipeline B starten wenn A erfolgreich endet",
    )
    on_failure: bool = Field(
        default=False,
        description="Pipeline B starten wenn A fehlschlägt",
    )
    on_route: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Trigger wenn Pipeline diesen Route-String in FASTFLOW_ROUTE_FILE schreibt (nur bei SUCCESS).",
    )
    run_config_id: Optional[str] = Field(
        default=None,
        description="Run-Konfiguration der Downstream-Pipeline (schedules[].id)",
    )
    enabled: bool = Field(
        default=True,
        description="Trigger aktiviert/deaktiviert",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)",
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
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
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
        description="active=Zugriff, pending=Beitrittsanfrage, rejected=abgelehnt",
        sa_column=Column(
            SAEnum(UserStatus, values_callable=lambda x: [e.value for e in x], native_enum=False),
            nullable=False,
            server_default="active",
        ),
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
    custom_oauth_id: Optional[str] = Field(
        default=None,
        unique=True,
        index=True,
        description="Custom OAuth subject ID (optional, für Custom IdP)"
    )
    avatar_url: Optional[str] = Field(
        default=None,
        description="Profilbild-URL (von OAuth-Provider)"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )
    last_login_at: Optional[datetime] = Field(
        default=None,
        description="Zeitpunkt der letzten erfolgreichen Anmeldung (UTC); None = noch nie angemeldet"
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
    created_at: datetime = Field(default_factory=_utc_now)


class SystemSettings(SQLModel, table=True):
    """
    SystemSettings-Model (Singleton, id=1).

    Steuert First-Run-Wizard, Dependency-Audit und UI-Anzeige-Optionen.
    """
    __tablename__ = "system_settings"

    id: int = Field(primary_key=True, default=1, description="Singleton (immer 1)")
    is_setup_completed: bool = Field(default=False, description="Wizard abgeschlossen?")
    enable_telemetry: bool = Field(
        default=False,
        description="Legacy: unused (formerly product analytics opt-in)",
    )
    enable_error_reporting: bool = Field(
        default=False,
        description="Legacy: unused (formerly error reporting opt-in)",
    )
    telemetry_distinct_id: Optional[str] = Field(
        default=None,
        description="Legacy: unused anonymous instance identifier",
    )
    dependency_audit_enabled: bool = Field(
        default=True,
        description="Automatische Sicherheitsprüfung (pip-audit) täglich; Benachrichtigung bei Schwachstellen",
    )
    dependency_audit_cron: str = Field(
        default="0 3 * * *",
        description="Cron-Ausdruck für Zeitpunkt (Standard: 3:00 Uhr täglich)",
    )
    login_branding_logo_url: Optional[str] = Field(
        default=None,
        description="Optional: Logo-URL (http/https) für Login und UI; überschreibt LOGIN_BRANDING_LOGO_URL aus der Umgebung wenn gesetzt",
    )
    ui_show_attribution: bool = Field(
        default=True,
        description="„Made with …“-Hinweis systemweit anzeigen (alle Nutzer, alle Clients)",
    )
    ui_show_version: bool = Field(
        default=True,
        description="Versionsnummer systemweit anzeigen (alle Nutzer, alle Clients)",
    )
    show_unconfigured_oauth_on_login: bool = Field(
        default=True,
        description="Auf der Login-Seite auch nicht konfigurierte OAuth-Provider als deaktivierte Buttons anzeigen; bei False nur konfigurierte Provider",
    )
    ui_login_background: str = Field(
        default="video",
        description="Login-Hintergrund: video oder game_of_life (systemweit)",
    )
    ui_header_timezone_1: str = Field(
        default="UTC",
        description="Erste Zeitzone für Header-Uhr (IANA, z. B. UTC)",
    )
    ui_header_timezone_2: str = Field(
        default="Europe/Berlin",
        description="Zweite Zeitzone für Header-Uhr (IANA, z. B. Europe/Berlin = CET/CEST)",
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
    git_sync_repo_url: Optional[str] = Field(default=None, description="HTTPS- oder SSH-URL des Pipeline-Repos")
    git_sync_token_encrypted: Optional[str] = Field(default=None, description="Verschlüsseltes PAT für private Repos (HTTPS)")
    git_sync_deploy_key_encrypted: Optional[str] = Field(default=None, description="Verschlüsselter privater SSH-Deploy-Key (für SSH-URL)")
    git_sync_branch: Optional[str] = Field(default=None, description="Branch für Sync (Override)")
    pipelines_subdir: Optional[str] = Field(default=None, description="Unterordner im Repo mit Pipeline-Ordnern, z. B. pipelines")
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
    # Notification API (Skripte: E-Mail/Teams per Key)
    notification_api_enabled: Optional[bool] = Field(default=None)
    notification_api_rate_limit_per_minute: Optional[int] = Field(default=None)
    # S3 Log-Backup (optional)
    s3_backup_enabled: Optional[bool] = Field(default=None)
    s3_endpoint_url: Optional[str] = Field(default=None)
    s3_bucket: Optional[str] = Field(default=None)
    s3_access_key_encrypted: Optional[str] = Field(default=None)
    s3_secret_access_key_encrypted: Optional[str] = Field(default=None)
    s3_region: Optional[str] = Field(default=None)
    s3_prefix: Optional[str] = Field(default=None)
    s3_use_path_style: Optional[bool] = Field(default=None)
    s3_last_test_at: Optional[datetime] = Field(default=None)
    s3_last_test_status: Optional[str] = Field(default=None, description="success | failed")
    s3_last_test_error: Optional[str] = Field(default=None)
    s3_test_on_save: Optional[bool] = Field(
        default=None,
        description="Nach Speichern der Settings automatisch S3-Verbindungstest ausführen (UI)",
    )


class NotificationApiKey(SQLModel, table=True):
    """
    API-Keys für die Benachrichtigungs-API (Skripte).
    Key wird gehashed gespeichert; Klartext nur einmal bei Erzeugung zurückgegeben.
    """
    __tablename__ = "notification_api_keys"

    id: int = Field(primary_key=True)
    key_hash: str = Field(index=True, description="SHA-256-Hash des Keys (constant-time Vergleich)")
    label: Optional[str] = Field(default=None, description="Optionale Bezeichnung z.B. CI Job")
    created_at: datetime = Field(default_factory=_utc_now)


class ApiToken(SQLModel, table=True):
    """Persönliches API-Token für nicht-interaktive Clients (CI, Skripte, MCP).

    Im Unterschied zu :class:`Session` entsteht ein Token nicht aus einem
    OAuth-Flow, sondern wird vom Nutzer selbst erzeugt. Gespeichert wird nur der
    SHA-256-Digest (siehe app.core.api_token_hash); der Klartext existiert
    ausschließlich in der Antwort des erzeugenden Requests.

    Die effektive Berechtigung ist stets die Schnittmenge aus ``scopes`` und den
    Scopes, die die Rolle des Besitzers zulässt (siehe app.auth.principal).
    Dadurch entwertet ein Rollenentzug bestehende Tokens sofort mit, ohne dass
    sie einzeln widerrufen werden müssen.
    """

    __tablename__ = "api_tokens"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Token-ID (auch in Audit-Einträgen referenziert)"
    )
    token_hash: str = Field(
        unique=True,
        index=True,
        description="SHA-256-Hex-Digest des vollständigen Tokens (Nachschlage-Schlüssel)"
    )
    prefix: str = Field(
        description="Öffentlicher Teil des Tokens (8 Zeichen), zur Wiedererkennung in der UI"
    )
    label: str = Field(
        description="Vom Nutzer vergebene Bezeichnung, z.B. 'CI nightly'"
    )
    user_id: UUID = Field(
        foreign_key=USERS_ID_FK,
        index=True,
        description="Besitzer des Tokens"
    )
    scopes: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="Gewährte Scopes als Liste von ApiTokenScope-Werten"
    )
    expires_at: datetime = Field(
        index=True,
        description="Ablauf-Zeitpunkt (UTC). Pflicht – ein Token ohne Ablauf ist ein Passwort ohne Rotation"
    )
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Letzte erfolgreiche Verwendung (UTC); gedrosselt geschrieben, siehe app.auth.principal"
    )
    revoked_at: Optional[datetime] = Field(
        default=None,
        description="Zeitpunkt des Widerrufs (UTC); None = aktiv. Bewusst kein Hard-Delete, damit Audit-Einträge zuordenbar bleiben"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


class AuditLogEntry(SQLModel, table=True):
    """
    Audit-Log: Wer hat wann welche Aktion ausgeführt (Compliance, Nachvollziehbarkeit).
    """
    __tablename__ = "audit_log"

    id: UUID = Field(default_factory=uuid4, primary_key=True, description="Eindeutige Eintrags-ID")
    created_at: datetime = Field(default_factory=_utc_now, index=True, description="Zeitpunkt der Aktion (UTC)")
    user_id: Optional[UUID] = Field(default=None, foreign_key=USERS_ID_FK, index=True, description="User der die Aktion ausgeführt hat")
    username: str = Field(default="", description="Benutzername zum Zeitpunkt der Aktion (Snapshot)")
    action: str = Field(index=True, description="Aktion z.B. run_start, system_settings_update, user_block, git_sync, downstream_trigger_create, …")
    resource_type: str = Field(index=True, description="Betroffene Ressource: pipeline, run, user, settings, secret, invite")
    resource_id: Optional[str] = Field(default=None, index=True, description="ID der betroffenen Ressource (z.B. Run-ID, Pipeline-Name)")
    details: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON), description="Zusätzliche Daten (z.B. new_run_id)")
    ip_address: Optional[str] = Field(default=None, description="Client-IP zum Zeitpunkt der Aktion (None bei System-/Hintergrund-Aktionen)")


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
        foreign_key=USERS_ID_FK,
        index=True,
        description="Verknüpfte User-ID"
    )
    expires_at: datetime = Field(
        description="Ablauf-Zeitpunkt (UTC)"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )


class EphemeralToken(SQLModel, table=True):
    """
    DB-gebundene Kurzzeit-Tokens für Auth-Flows ohne Authorization-Header
    (OAuth-Account-Linking per Browser-Navigation, Log-Download-Direktlinks).

    Anders als ein reines JWT reicht eine gültige Signatur allein nicht aus:
    das Token muss zusätzlich einer nicht abgelaufenen (und beim Account-Link
    auch noch nicht eingelösten) Zeile hier entsprechen. Das schließt die
    Fälschungslücke, falls JWT_SECRET_KEY jemals schwach/geleakt/wiederverwendet
    ist (siehe TE-11 Finding 2): die Zeile wird serverseitig pro Request erzeugt
    und lässt sich nicht allein aus dem Secret rekonstruieren.
    """
    __tablename__ = "ephemeral_tokens"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        description="Eindeutige Token-ID"
    )
    token: str = Field(
        unique=True,
        index=True,
        description="Opaker, zufälliger Token-Wert"
    )
    issued_to_user_id: Optional[UUID] = Field(
        default=None,
        foreign_key=USERS_ID_FK,
        index=True,
        description=(
            "Nutzer, für den das Token ausgestellt wurde. None nur für Alt-Zeilen. "
            "Beim Einlösen wird geprüft, ob dieser Nutzer noch aktiv ist"
        ),
    )
    issued_via_api_token_id: Optional[UUID] = Field(
        default=None,
        foreign_key="api_tokens.id",
        index=True,
        description=(
            "API-Token, mit dem dieses Kurzzeit-Token angefordert wurde (None bei "
            "Browser-Session). Wird es widerrufen, verfällt auch dieses Token"
        ),
    )
    token_type: EphemeralTokenType = Field(
        sa_column=Column(
            SAEnum(EphemeralTokenType, values_callable=lambda x: [e.value for e in x], native_enum=False),
            nullable=False,
        ),
        description="account_link oder log_download"
    )
    subject: str = Field(
        index=True,
        description="Bezugsobjekt als String: user_id (account_link) oder run_id (log_download)"
    )
    expires_at: datetime = Field(
        description="Ablauf-Zeitpunkt (UTC)"
    )
    consumed_at: Optional[datetime] = Field(
        default=None,
        description="Zeitpunkt des Einlösens (single-use); None solange ungenutzt"
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="Erstellungs-Zeitpunkt (UTC)"
    )
