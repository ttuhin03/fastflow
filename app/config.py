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
from typing import Optional
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
    
    LOGS_DIR: Path = Path(os.getenv("LOGS_DIR", "./logs")).resolve()
    """Verzeichnis für persistente Log-Dateien aller Pipeline-Runs."""
    
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "./data")).resolve()
    """Verzeichnis für Datenbank und persistente Daten."""
    
    # Docker & UV-Konfiguration
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
    
    Wenn True: `uv pip compile` wird für alle requirements.txt ausgeführt,
    um Dependencies im Cache vorzubereiten. Verhindert Wartezeiten beim
    ersten Pipeline-Start nach einem Sync.
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
    
    AUTO_SYNC_INTERVAL: Optional[int] = (
        int(os.getenv("AUTO_SYNC_INTERVAL"))
        if os.getenv("AUTO_SYNC_INTERVAL")
        else None
    )
    """
    Automatisches Git-Sync-Intervall in Sekunden.
    
    None = Auto-Sync deaktiviert. Wenn gesetzt: Periodisches Git-Pull
    aus dem konfigurierten Branch.
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
    
    # Authentication-Konfiguration
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")
    """
    Benutzername für Basic Authentication.
    
    Standard: admin. Sollte in Produktion geändert werden.
    """
    
    AUTH_PASSWORD: str = os.getenv("AUTH_PASSWORD", "admin")
    """
    Passwort für Basic Authentication.
    
    Standard: admin. MUSS in Produktion geändert werden!
    ⚠️ KRITISCH: Authentifizierung ist der wichtigste Schutz gegen
    Docker-Socket-Missbrauch (Docker-Socket = Root-Zugriff auf Host).
    """
    
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
        """
        cls.PIPELINES_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# Globale Config-Instanz
config = Config()
