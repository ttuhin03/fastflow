"""
Configuration Module.

Dieses Modul lädt und verwaltet alle Konfigurationsparameter aus
Environment-Variablen und .env-Dateien.
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
    mit sinnvollen Standardwerten als Fallback.
    """
    
    # Datenbank-Konfiguration
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL", None)
    # Standard: SQLite (wenn DATABASE_URL nicht gesetzt)
    # Format für PostgreSQL: postgresql://user:password@host:5432/dbname
    
    # Verzeichnis-Konfiguration
    PIPELINES_DIR: Path = Path(os.getenv("PIPELINES_DIR", "./pipelines"))
    LOGS_DIR: Path = Path(os.getenv("LOGS_DIR", "./logs"))
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "./data"))
    
    # Docker & UV-Konfiguration
    WORKER_BASE_IMAGE: str = os.getenv(
        "WORKER_BASE_IMAGE",
        "ghcr.io/astral-sh/uv:python3.11-bookworm-slim"
    )
    UV_CACHE_DIR: Path = Path(os.getenv("UV_CACHE_DIR", "./data/uv_cache"))
    UV_PRE_HEAT: bool = os.getenv("UV_PRE_HEAT", "true").lower() == "true"
    
    # Concurrency & Timeouts
    MAX_CONCURRENT_RUNS: int = int(os.getenv("MAX_CONCURRENT_RUNS", "10"))
    CONTAINER_TIMEOUT: Optional[int] = (
        int(os.getenv("CONTAINER_TIMEOUT")) 
        if os.getenv("CONTAINER_TIMEOUT") 
        else None
    )
    RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "0"))
    
    # Git-Konfiguration
    GIT_BRANCH: str = os.getenv("GIT_BRANCH", "main")
    AUTO_SYNC_INTERVAL: Optional[int] = (
        int(os.getenv("AUTO_SYNC_INTERVAL"))
        if os.getenv("AUTO_SYNC_INTERVAL")
        else None
    )
    
    # Log-Management
    LOG_RETENTION_RUNS: Optional[int] = (
        int(os.getenv("LOG_RETENTION_RUNS"))
        if os.getenv("LOG_RETENTION_RUNS")
        else None
    )
    LOG_RETENTION_DAYS: Optional[int] = (
        int(os.getenv("LOG_RETENTION_DAYS"))
        if os.getenv("LOG_RETENTION_DAYS")
        else None
    )
    LOG_MAX_SIZE_MB: Optional[int] = (
        int(os.getenv("LOG_MAX_SIZE_MB"))
        if os.getenv("LOG_MAX_SIZE_MB")
        else None
    )
    LOG_STREAM_RATE_LIMIT: int = int(os.getenv("LOG_STREAM_RATE_LIMIT", "100"))
    
    # Secrets-Verschlüsselung
    ENCRYPTION_KEY: Optional[str] = os.getenv("ENCRYPTION_KEY")
    # Muss gesetzt werden - Fernet Key für Secrets-Verschlüsselung
    
    # GitHub Apps Authentifizierung
    GITHUB_APP_ID: Optional[str] = os.getenv("GITHUB_APP_ID")
    GITHUB_INSTALLATION_ID: Optional[str] = os.getenv("GITHUB_INSTALLATION_ID")
    GITHUB_PRIVATE_KEY_PATH: Optional[str] = os.getenv("GITHUB_PRIVATE_KEY_PATH")
    
    @classmethod
    def ensure_directories(cls) -> None:
        """
        Erstellt alle benötigten Verzeichnisse falls sie nicht existieren.
        
        Wird beim App-Start aufgerufen, um sicherzustellen, dass alle
        Verzeichnisse für Logs, Daten und Cache vorhanden sind.
        """
        cls.PIPELINES_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.UV_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# Globale Config-Instanz
config = Config()
