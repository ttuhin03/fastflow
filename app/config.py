"""
Configuration Module.

Dieses Modul lädt und verwaltet alle Konfigurationsparameter aus
Environment-Variablen und .env-Dateien.

Die Konfiguration unterstützt:
- Environment-Variablen aus dem System
- .env-Dateien im Projekt-Root (via python-dotenv)
- Sinnvolle Standardwerte für alle Parameter

Alle Parameter werden beim Modul-Import geladen und sind dann über
die globale `config`-Instanz verfügbar.
"""

import os
from typing import Optional, List
from pathlib import Path
from dotenv import load_dotenv


# Lade .env-Datei falls vorhanden
load_dotenv()


class Config:
    """
    Konfigurationsklasse für den Fast-Flow Orchestrator.
    
    Alle konfigurierbaren Parameter werden aus Environment-Variablen geladen,
    mit sinnvollen Standardwerten als Fallback. Die Konfiguration wird beim
    Modul-Import initialisiert.
    
    Attributes:
        VERSION: Aktuelle Version der Anwendung aus VERSION-Datei
        DATABASE_URL: Datenbank-URL (None = SQLite, PostgreSQL-Format: postgresql://...)
        PIPELINES_DIR: Verzeichnis für Pipeline-Repository
        LOGS_DIR: Verzeichnis für Log-Dateien
        DATA_DIR: Verzeichnis für Datenbank und Daten
        WORKER_BASE_IMAGE: Docker-Image für Pipeline-Container
        UV_CACHE_DIR: Verzeichnis für UV-Package-Cache
        UV_PRE_HEAT: Automatisches Pre-Heating von Dependencies beim Git-Sync
        MAX_CONCURRENT_RUNS: Maximale Anzahl gleichzeitiger Pipeline-Runs
        CONTAINER_TIMEOUT: Globaler Timeout für Container in Sekunden (None = unbegrenzt)
        RETRY_ATTEMPTS: Anzahl Retry-Versuche bei fehlgeschlagenen Runs
        GIT_BRANCH: Git-Branch für Sync-Operationen
        AUTO_SYNC_INTERVAL: Automatisches Sync-Intervall in Sekunden (None = deaktiviert)
        LOG_RETENTION_RUNS: Maximale Anzahl Runs pro Pipeline (None = unbegrenzt)
        LOG_RETENTION_DAYS: Maximale Alter von Logs in Tagen (None = unbegrenzt)
        LOG_MAX_SIZE_MB: Maximale Größe einer Log-Datei in MB (None = unbegrenzt)
        LOG_STREAM_RATE_LIMIT: Maximale Zeilen pro Sekunde für SSE-Log-Streaming
        ENCRYPTION_KEY: Fernet Key für Secrets-Verschlüsselung (MUSS gesetzt werden)
        GITHUB_APP_ID: GitHub App ID für Authentifizierung (optional)
        GITHUB_INSTALLATION_ID: GitHub Installation ID (optional)
        GITHUB_PRIVATE_KEY_PATH: Pfad zur GitHub App Private Key .pem Datei (optional)
    """
    
    # Version aus Datei lesen
    VERSION: str = Path("VERSION").read_text().strip().lstrip("v") if Path("VERSION").exists() else "0.0.0"

    # Datenbank-Konfiguration
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL", None)
    """
    Datenbank-URL für SQLModel.
    
    - None: SQLite wird verwendet (./data/fastflow.db)
    - PostgreSQL: postgresql://user:password@host:5432/dbname
    """
    
    # Verzeichnis-Konfiguration
    PIPELINES_DIR: Path = Path(os.getenv("PIPELINES_DIR", "./pipelines")).resolve()
    """Verzeichnis für das Pipeline-Repository (wird als Volume gemountet)."""
    
    PIPELINES_HOST_DIR: Optional[str] = os.getenv("PIPELINES_HOST_DIR")
    """
    Host-Pfad für das Pipeline-Repository (für Docker Volume-Mounts).
    
    Wenn nicht gesetzt, wird PIPELINES_DIR verwendet. Muss gesetzt werden,
    wenn der Code in einem Docker-Container läuft, um den Host-Pfad zu verwenden.
    """
    
    RUNNERS_DIR: Path = (Path(__file__).resolve().parent / "runners").resolve()
    """Pfad zum Runner-Verzeichnis (app/runners, z. B. nb_runner.py für Notebook-Pipelines)."""
    
    RUNNERS_HOST_DIR: Optional[str] = os.getenv("RUNNERS_HOST_DIR")
    """Host-Pfad für RUNNERS_DIR (für Docker Volume-Mount in Worker bei Notebook-Pipelines)."""
    
    LOGS_DIR: Path = Path(os.getenv("LOGS_DIR", "./logs")).resolve()
    """Verzeichnis für persistente Log-Dateien aller Pipeline-Runs."""
    
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "./data")).resolve()
    """Verzeichnis für Datenbank und persistente Daten."""
    
    UV_CACHE_HOST_DIR: Optional[str] = os.getenv("UV_CACHE_HOST_DIR")
    """
    Host-Pfad für UV-Cache (für Docker Volume-Mounts).
    
    Wenn nicht gesetzt, wird UV_CACHE_DIR verwendet. Muss gesetzt werden,
    wenn der Code in einem Docker-Container läuft, um den Host-Pfad zu verwenden.
    """
    
    UV_PYTHON_INSTALL_HOST_DIR: Optional[str] = os.getenv("UV_PYTHON_INSTALL_HOST_DIR")
    """
    Host-Pfad für UV-Python-Installationen (für Docker Volume-Mounts in Worker-Container).
    
    Optional. Wenn nicht gesetzt, wird aus den Orchestrator-Mounts abgeleitet.
    """
    
    # Docker & UV-Konfiguration
    DOCKER_PROXY_URL: str = os.getenv("DOCKER_PROXY_URL", "http://docker-proxy:2375")
    """
    Docker Socket Proxy URL.
    
    URL des docker-socket-proxy Services für sichere Docker-API-Kommunikation.
    Standard: http://docker-proxy:2375 (für Docker Compose Setup)
    Kann über Environment-Variable DOCKER_PROXY_URL überschrieben werden.
    """
    
    WORKER_BASE_IMAGE: str = os.getenv(
        "WORKER_BASE_IMAGE",
        "ghcr.io/astral-sh/uv:python3.11-bookworm-slim"
    )
    """
    Docker-Image für Pipeline-Container.
    
    Muss UV (Astral UV) enthalten und Python 3.11+ unterstützen.
    Standard: ghcr.io/astral-sh/uv:python3.11-bookworm-slim
    """
    
    UV_CACHE_DIR: Path = Path(os.getenv("UV_CACHE_DIR", "./data/uv_cache")).resolve()
    """
    Verzeichnis für UV-Package-Cache.
    
    Wird als Volume zwischen allen Container-Runs geteilt, um
    Dependencies nicht bei jedem Run neu herunterladen zu müssen.
    """
    
    UV_PRE_HEAT: bool = os.getenv("UV_PRE_HEAT", "true").lower() == "true"
    """
    Automatisches Pre-Heating von Dependencies beim Git-Sync.
    
    Wenn True: `uv pip compile` + `uv pip install` wird für alle requirements.txt ausgeführt,
    um Lock-Files zu erstellen und Dependencies im Cache zu speichern. Beim Pipeline-Run
    wird dann `uv run --frozen` verwendet, um die Resolution zu überspringen und nur den Cache zu nutzen.
    Verhindert Wartezeiten beim ersten Pipeline-Start nach einem Sync.
    """
    
    DEFAULT_PYTHON_VERSION: str = os.getenv("DEFAULT_PYTHON_VERSION", "3.11")
    """
    Standard-Python-Version, wenn python_version in pipeline.json fehlt.
    Wird für uv run --python und Pre-Heating genutzt.
    """
    
    UV_PYTHON_INSTALL_DIR: Path = Path(
        os.getenv("UV_PYTHON_INSTALL_DIR", str(Path(os.getenv("DATA_DIR", "./data")).resolve() / "uv_python"))
    ).resolve()
    """
    Verzeichnis für von uv verwaltete Python-Installationen (uv python install).
    Muss auf ein persistentes Volume zeigen, damit Worker-Container darauf zugreifen.
    """
    
    # Concurrency & Timeouts
    MAX_CONCURRENT_RUNS: int = int(os.getenv("MAX_CONCURRENT_RUNS", "10"))
    """
    Maximale Anzahl gleichzeitiger Pipeline-Runs.
    
    Wenn das Limit erreicht ist, werden neue Pipeline-Starts abgelehnt
    (HTTP 429). Verhindert Ressourcen-Überlastung des Host-Systems.
    """
    
    CONTAINER_TIMEOUT: Optional[int] = (
        int(os.getenv("CONTAINER_TIMEOUT")) 
        if os.getenv("CONTAINER_TIMEOUT") 
        else None
    )
    """
    Globaler Timeout für Container in Sekunden.
    
    None = unbegrenzt. Pipeline-spezifische Timeouts aus Metadaten-JSON
    überschreiben diesen Wert. Container wird nach Timeout beendet (killed).
    """
    
    RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "0"))
    """
    Globale Anzahl Retry-Versuche bei fehlgeschlagenen Runs.
    
    Pipeline-spezifische Retry-Attempts aus Metadaten-JSON überschreiben
    diesen Wert. Retry erfolgt nur bei Exit-Code != 0.
    """
    
    # Git-Konfiguration
    GIT_BRANCH: str = os.getenv("GIT_BRANCH", "main")
    """Git-Branch für Sync-Operationen (Standard: main)."""
    
    AUTO_SYNC_ENABLED: bool = os.getenv("AUTO_SYNC_ENABLED", "false").lower() == "true"
    """
    Aktiviert automatisches Git-Sync.
    
    Wenn True: Periodisches Git-Pull basierend auf AUTO_SYNC_INTERVAL.
    Standard: false (deaktiviert).
    """
    
    AUTO_SYNC_INTERVAL: Optional[int] = (
        int(os.getenv("AUTO_SYNC_INTERVAL"))
        if os.getenv("AUTO_SYNC_INTERVAL")
        else None
    )
    """
    Automatisches Git-Sync-Intervall in Sekunden.
    
    None = Auto-Sync deaktiviert. Wenn gesetzt: Periodisches Git-Pull
    aus dem konfigurierten Branch. Wird nur verwendet wenn AUTO_SYNC_ENABLED=True.
    """
    
    # Log-Management
    LOG_RETENTION_RUNS: Optional[int] = (
        int(os.getenv("LOG_RETENTION_RUNS"))
        if os.getenv("LOG_RETENTION_RUNS")
        else None
    )
    """
    Maximale Anzahl Runs pro Pipeline, die aufbewahrt werden.
    
    None = unbegrenzt. Älteste Runs werden gelöscht, wenn das Limit
    überschritten wird. Gilt pro Pipeline separat.
    """
    
    LOG_RETENTION_DAYS: Optional[int] = (
        int(os.getenv("LOG_RETENTION_DAYS"))
        if os.getenv("LOG_RETENTION_DAYS")
        else None
    )
    """
    Maximale Alter von Log-Dateien in Tagen.
    
    None = unbegrenzt. Logs älter als dieser Wert werden automatisch
    gelöscht (Cleanup-Job).
    """
    
    LOG_MAX_SIZE_MB: Optional[int] = (
        int(os.getenv("LOG_MAX_SIZE_MB"))
        if os.getenv("LOG_MAX_SIZE_MB")
        else None
    )
    """
    Maximale Größe einer Log-Datei in MB.
    
    None = unbegrenzt. Zusätzlich zu Docker Log-Limits. Überschreitung
    wird geloggt oder Stream wird gekappt (Schutz vor Log-Spam).
    """
    
    LOG_STREAM_RATE_LIMIT: int = int(os.getenv("LOG_STREAM_RATE_LIMIT", "100"))
    """
    Maximale Zeilen pro Sekunde für SSE-Log-Streaming.
    
    Schutz vor Memory-Problemen bei High-Frequency-Log-Output.
    Alle Logs werden in Datei geschrieben (vollständig), SSE-Streaming
    ist rate-limited.
    """
    
    # Log-Backup (S3/MinIO)
    S3_BACKUP_ENABLED: bool = os.getenv("S3_BACKUP_ENABLED", "false").lower() == "true"
    """
    Aktiviert S3-Backup von Pipeline-Logs vor der lokalen Löschung.
    
    Wenn True: Log- und Metrics-Dateien werden vor dem Cleanup nach S3/MinIO
    hochgeladen. Lokale Löschung erfolgt nur bei erfolgreichem Upload.
    """
    
    S3_ENDPOINT_URL: Optional[str] = os.getenv("S3_ENDPOINT_URL")
    """S3-kompatibler Endpoint (z.B. http://minio:9000 für MinIO)."""
    
    S3_BUCKET: Optional[str] = os.getenv("S3_BUCKET")
    """S3-Bucket für Log-Backups."""
    
    S3_ACCESS_KEY: Optional[str] = os.getenv("S3_ACCESS_KEY")
    """Access Key für S3/MinIO."""
    
    S3_SECRET_ACCESS_KEY: Optional[str] = os.getenv("S3_SECRET_ACCESS_KEY")
    """Secret Access Key für S3/MinIO."""
    
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    """S3-Region (MinIO oft egal, z.B. us-east-1)."""
    
    S3_PREFIX: str = os.getenv("S3_PREFIX", "pipeline-logs")
    """Prefix für S3-Objektkeys (z.B. pipeline-logs/pipeline_name/run_id/run.log)."""
    
    S3_USE_PATH_STYLE: bool = os.getenv("S3_USE_PATH_STYLE", "true").lower() == "true"
    """Path-Style-URLs für S3 (für MinIO typischerweise true)."""
    
    # Secrets-Verschlüsselung
    ENCRYPTION_KEY: Optional[str] = os.getenv("ENCRYPTION_KEY")
    """
    Fernet Key für Secrets-Verschlüsselung (Base64-kodiert).
    
    MUSS gesetzt werden! Wird verwendet, um Secrets verschlüsselt
    in der Datenbank zu speichern.
    
    Generierung: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    
    # GitHub Apps Authentifizierung
    GITHUB_APP_ID: Optional[str] = os.getenv("GITHUB_APP_ID")
    """
    GitHub App ID für Authentifizierung (optional).
    
    Wird verwendet, um Installation Access Tokens für Git-Operationen
    zu generieren. Erforderlich für Private Repositories.
    """
    
    GITHUB_INSTALLATION_ID: Optional[str] = os.getenv("GITHUB_INSTALLATION_ID")
    """
    GitHub Installation ID (optional).
    
    Installation-ID der GitHub App in der Organisation/Repository.
    Erforderlich zusammen mit GITHUB_APP_ID und GITHUB_PRIVATE_KEY_PATH.
    """
    
    GITHUB_PRIVATE_KEY_PATH: Optional[str] = os.getenv("GITHUB_PRIVATE_KEY_PATH")
    """
    Pfad zur GitHub App Private Key .pem Datei (optional).
    
    Private Key wird verwendet, um JWT-Tokens für GitHub API-Aufrufe
    zu signieren. Muss zusammen mit GITHUB_APP_ID und GITHUB_INSTALLATION_ID
    gesetzt werden.
    """
    
    # GitHub OAuth (User-Login, getrennt von GitHub App)
    GITHUB_CLIENT_ID: Optional[str] = os.getenv("GITHUB_CLIENT_ID")
    """
    GitHub OAuth App Client ID für User-Login.
    
    Erstelle eine OAuth App unter GitHub: Settings → Developer settings → OAuth Apps.
    Authorization callback URL: {BASE_URL}/api/auth/github/callback
    """
    
    GITHUB_CLIENT_SECRET: Optional[str] = os.getenv("GITHUB_CLIENT_SECRET")
    """GitHub OAuth App Client Secret für User-Login."""
    
    INITIAL_ADMIN_EMAIL: Optional[str] = os.getenv("INITIAL_ADMIN_EMAIL")
    """
    E-Mail des ersten Admins (Zutritt ohne Einladung).
    
    Wenn gesetzt: User mit dieser E-Mail (GitHub oder Google) erhalten beim ersten
    Login automatisch Admin-Rechte. Danach: normale Einladung für weitere User.
    """

    # Google OAuth (User-Login)
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID")
    """
    Google OAuth 2.0 Client ID für User-Login.
    OAuth-Client in Google Cloud Console anlegen (Web-Anwendung).
    Authorization redirect URI: {BASE_URL}/api/auth/google/callback
    """
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_CLIENT_SECRET")
    """Google OAuth 2.0 Client Secret für User-Login."""

    # Authentication-Konfiguration (Login via GitHub OAuth, Google OAuth)
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    """
    Secret Key für JWT-Token-Signierung.
    
    Standard: change-me-in-production. MUSS in Produktion geändert werden!
    Sollte ein zufälliger, sicherer String sein (mindestens 32 Zeichen).
    """
    
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    """Algorithmus für JWT-Token-Signierung (Standard: HS256)."""
    
    JWT_EXPIRATION_HOURS: int = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))
    """
    Gültigkeitsdauer von JWT-Tokens in Stunden.
    
    Standard: 24 Stunden. Nach Ablauf muss sich der Benutzer erneut
    anmelden.
    
    Hinweis: Für bessere Sicherheit wird empfohlen, kürzere Laufzeiten
    (z.B. 15 Minuten für Access Tokens) mit Refresh Token Flow zu verwenden.
    """
    
    JWT_ACCESS_TOKEN_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "15"))
    """
    Gültigkeitsdauer von Access Tokens in Minuten (für Refresh Token Flow).
    
    Standard: 15 Minuten. Kürzere Laufzeit reduziert das Risiko bei
    kompromittierten Tokens.
    """
    
    # E-Mail-Benachrichtigungen
    EMAIL_ENABLED: bool = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
    """
    Aktiviert E-Mail-Benachrichtigungen für Pipeline-Fehler.
    
    Wenn True: E-Mails werden bei FAILED oder INTERRUPTED Status gesendet.
    Standard: false (deaktiviert).
    """
    
    SMTP_HOST: Optional[str] = os.getenv("SMTP_HOST")
    """SMTP-Server-Hostname für E-Mail-Versand."""
    
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    """
    SMTP-Server-Port.
    
    Standard: 587 (TLS). Alternative: 465 (SSL) oder 25 (unverschlüsselt).
    """
    
    SMTP_USER: Optional[str] = os.getenv("SMTP_USER")
    """SMTP-Benutzername für Authentifizierung."""
    
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD")
    """SMTP-Passwort für Authentifizierung."""
    
    SMTP_FROM: Optional[str] = os.getenv("SMTP_FROM")
    """Absender-E-Mail-Adresse für Benachrichtigungen."""
    
    EMAIL_RECIPIENTS: List[str] = (
        [email.strip() for email in os.getenv("EMAIL_RECIPIENTS", "").split(",") if email.strip()]
        if os.getenv("EMAIL_RECIPIENTS")
        else []
    )
    """
    Liste der E-Mail-Empfänger für Benachrichtigungen.
    
    Komma-separierte Liste von E-Mail-Adressen.
    Beispiel: "admin@example.com,team@example.com"
    """
    
    # Microsoft Teams-Benachrichtigungen
    TEAMS_ENABLED: bool = os.getenv("TEAMS_ENABLED", "false").lower() == "true"
    """
    Aktiviert Microsoft Teams-Benachrichtigungen für Pipeline-Fehler.
    
    Wenn True: Teams-Nachrichten werden bei FAILED oder INTERRUPTED Status gesendet.
    Standard: false (deaktiviert).
    """
    
    TEAMS_WEBHOOK_URL: Optional[str] = os.getenv("TEAMS_WEBHOOK_URL")
    """
    Microsoft Teams-Webhook-URL für Benachrichtigungen.
    
    Webhook-URL kann in Teams-Kanal über "Connectors" erstellt werden.
    Format: https://outlook.office.com/webhook/...
    """

    # PostHog (Phase 1: Error-Tracking; Phase 2: Session Replay, Product Analytics, Survey)
    # Host fest auf EU; API-Key derzeit fest. Steuerung nur über SystemSettings.enable_error_reporting.
    POSTHOG_API_KEY: str = "phc_PxPEXdUC56hAwgi8A2Tge84wvt2BOnWV0CyH1zenKg9"
    POSTHOG_HOST: str = "https://eu.posthog.com"

    FRONTEND_URL: Optional[str] = os.getenv("FRONTEND_URL")
    """
    Frontend-URL für Links in Benachrichtigungen.
    
    Wird verwendet, um Links zu Run-Details in E-Mails und Teams-Nachrichten einzufügen.
    Beispiel: "http://localhost:3000" oder "https://fastflow.example.com"
    """
    
    BASE_URL: Optional[str] = os.getenv("BASE_URL", os.getenv("FRONTEND_URL", "http://localhost:8000"))
    """
    Base URL für API-Callbacks (z.B. GitHub OAuth Callbacks).
    
    Wird verwendet für Callback-URLs in OAuth-Flows.
    Standard: FRONTEND_URL oder http://localhost:8000
    Beispiel: "http://localhost:8000" oder "https://fastflow.example.com"
    """
    
    SKIP_OAUTH_VERIFICATION: bool = (
        os.getenv("SKIP_OAUTH_VERIFICATION", "").lower() in ("1", "true", "yes")
    )
    """
    Überspringt die HTTP-Verifizierung der OAuth-Credentials beim Start.
    Nützlich für Tests/CI. Die Prüfung „mind. ein OAuth-Provider vollständig“
    wird weiterhin ausgeführt.
    """

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
    """
    Umgebungsmodus der App (development oder production).
    
    Standard: development
    In Produktion sollte dies auf "production" gesetzt werden.
    Beeinflusst Sicherheitsvalidierungen beim Start:
    - In Produktion werden Standardwerte für JWT_SECRET_KEY blockiert
    - In Development werden nur Warnungen ausgegeben
    """

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    """
    Log-Level für Root-Logger (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    Standard: INFO.
    """

    LOG_JSON: bool = os.getenv("LOG_JSON", "false").lower() == "true"
    """
    Strukturiertes Logging als JSON (für zentrale Log-Aggregation in Produktion).
    Standard: false. In Produktion oft true für ELK/Datadog etc.
    """

    MAX_REQUEST_BODY_MB: Optional[int] = (
        int(os.getenv("MAX_REQUEST_BODY_MB"))
        if os.getenv("MAX_REQUEST_BODY_MB")
        else None
    )
    """
    Maximale Request-Body-Größe in MB. Überschreitende Requests erhalten 413.
    None = unbegrenzt. Empfohlen in Produktion z.B. 10.
    """

    CORS_ORIGINS: List[str] = (
        [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
        if os.getenv("CORS_ORIGINS")
        else [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://0.0.0.0:8000",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:3000",
        ]
    )
    """
    Liste der erlaubten CORS-Origins.
    
    Standard: Localhost-Origins für Entwicklung.
    In Produktion sollte dies über die CORS_ORIGINS Environment-Variable gesetzt werden.
    Format: Komma-separierte Liste, z.B. "https://example.com,https://app.example.com"
    """
    
    @classmethod
    def ensure_directories(cls) -> None:
        """
        Erstellt alle benötigten Verzeichnisse falls sie nicht existieren.
        
        Wird beim App-Start aufgerufen, um sicherzustellen, dass alle
        Verzeichnisse für Logs, Daten und Cache vorhanden sind.
        
        Erstellt folgende Verzeichnisse:
        - PIPELINES_DIR: Pipeline-Repository
        - LOGS_DIR: Log-Dateien
        - DATA_DIR: Datenbank und persistente Daten
        - UV_CACHE_DIR: UV-Package-Cache
        - UV_PYTHON_INSTALL_DIR: uv python install (Python-Versionen für Worker)
        """
        cls.PIPELINES_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cls.UV_PYTHON_INSTALL_DIR.mkdir(parents=True, exist_ok=True)


# Globale Config-Instanz
config = Config()
