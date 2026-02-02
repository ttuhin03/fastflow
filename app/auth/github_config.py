"""
GitHub Apps Configuration Management.

Dieses Modul verwaltet die GitHub Apps Konfiguration:
- Speicherung des Private Keys in einer sicheren Datei
- Aktualisierung der .env Datei
- Laden und Validierung der Konfiguration
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv, set_key, find_dotenv

from app.core.config import config

# Pfad für Private Key Datei
GITHUB_KEY_PATH = Path("./data/github_app_key.pem")


def validate_github_private_key(key_content: str) -> bool:
    """
    Validiert ob der Private Key ein gültiges PEM-Format hat.
    
    Args:
        key_content: Private Key als String
        
    Returns:
        True wenn gültiges PEM-Format, sonst False
    """
    if not key_content or not isinstance(key_content, str):
        return False
    
    # Prüfe ob Private Key mit BEGIN/END Markern beginnt/endet
    key_content = key_content.strip()
    if not key_content.startswith("-----BEGIN"):
        return False
    
    if "-----END" not in key_content:
        return False
    
    # Prüfe ob es RSA oder EC Private Key ist
    if "RSA PRIVATE KEY" not in key_content and "PRIVATE KEY" not in key_content:
        return False
    
    return True


def save_private_key(key_content: str) -> None:
    """
    Speichert den Private Key in einer sicheren Datei.
    
    Args:
        key_content: Private Key als String
        
    Raises:
        ValueError: Wenn Private Key Format ungültig ist
        IOError: Wenn Datei nicht geschrieben werden kann
    """
    if not validate_github_private_key(key_content):
        raise ValueError("Ungültiges Private Key Format. Muss PEM-Format sein (-----BEGIN ... -----END ...)")
    
    # Stelle sicher, dass Verzeichnis existiert
    GITHUB_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    # Schreibe Private Key
    GITHUB_KEY_PATH.write_text(key_content.strip() + "\n", encoding="utf-8")
    
    # Setze sichere Berechtigungen (nur Owner lesbar/schreibbar)
    os.chmod(GITHUB_KEY_PATH, 0o600)


def delete_private_key() -> None:
    """
    Löscht die Private Key Datei.
    """
    if GITHUB_KEY_PATH.exists():
        GITHUB_KEY_PATH.unlink()


def update_env_file(key: str, value: Optional[str]) -> None:
    """
    Aktualisiert eine Environment-Variable in der .env Datei.
    
    Args:
        key: Environment-Variable Name
        value: Neuer Wert (None = entfernen)
    """
    env_file = find_dotenv()
    
    if not env_file:
        # .env Datei existiert nicht, erstelle sie
        env_file = Path(".env")
        env_file.touch()
    
    env_file_path = Path(env_file) if isinstance(env_file, str) else env_file
    
    if value is None:
        # Entferne Variable: Lese Datei, entferne Zeile, schreibe zurück
        if env_file_path.exists():
            with open(env_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            with open(env_file_path, "w", encoding="utf-8") as f:
                for line in lines:
                    # Überspringe Zeilen die diese Variable enthalten (mit oder ohne Whitespace)
                    stripped = line.strip()
                    if not stripped.startswith(f"{key}="):
                        f.write(line)
    else:
        # Verwende python-dotenv's set_key Funktion zum Aktualisieren/Hinzufügen
        set_key(str(env_file_path), key, value)


def save_github_config(app_id: str, installation_id: str, private_key: str) -> None:
    """
    Speichert die GitHub Apps Konfiguration.
    
    Args:
        app_id: GitHub App ID
        installation_id: GitHub Installation ID
        private_key: Private Key als String
        
    Raises:
        ValueError: Wenn Validierung fehlschlägt
    """
    # Validiere Private Key
    if not validate_github_private_key(private_key):
        raise ValueError("Ungültiges Private Key Format. Muss PEM-Format sein.")
    
    # Validiere App ID und Installation ID (sollten numerisch sein)
    if not app_id or not app_id.strip().isdigit():
        raise ValueError("GitHub App ID muss eine Zahl sein")
    
    if not installation_id or not installation_id.strip().isdigit():
        raise ValueError("GitHub Installation ID muss eine Zahl sein")
    
    # Speichere Private Key
    save_private_key(private_key)
    
    # Aktualisiere .env Datei
    update_env_file("GITHUB_APP_ID", app_id.strip())
    update_env_file("GITHUB_INSTALLATION_ID", installation_id.strip())
    update_env_file("GITHUB_PRIVATE_KEY_PATH", str(GITHUB_KEY_PATH.resolve()))
    
    # Aktualisiere in-memory Config (für sofortige Verwendung)
    os.environ["GITHUB_APP_ID"] = app_id.strip()
    os.environ["GITHUB_INSTALLATION_ID"] = installation_id.strip()
    os.environ["GITHUB_PRIVATE_KEY_PATH"] = str(GITHUB_KEY_PATH.resolve())
    
    # Lade .env neu (für config Objekt)
    load_dotenv(override=True)
    
    # Aktualisiere config Objekt direkt
    config.GITHUB_APP_ID = app_id.strip()
    config.GITHUB_INSTALLATION_ID = installation_id.strip()
    config.GITHUB_PRIVATE_KEY_PATH = str(GITHUB_KEY_PATH.resolve())


def load_github_config() -> Dict[str, Any]:
    """
    Lädt die aktuelle GitHub Apps Konfiguration.
    
    Returns:
        Dictionary mit Konfiguration (app_id, installation_id, configured, has_private_key)
    """
    app_id = config.GITHUB_APP_ID
    installation_id = config.GITHUB_INSTALLATION_ID
    private_key_path = config.GITHUB_PRIVATE_KEY_PATH
    
    # Prüfe ob Private Key Datei existiert
    has_private_key = False
    if private_key_path:
        key_path = Path(private_key_path)
        if key_path.exists():
            has_private_key = True
    elif GITHUB_KEY_PATH.exists():
        has_private_key = True
        # Migriere zu neuem Pfad
        if not private_key_path:
            update_env_file("GITHUB_PRIVATE_KEY_PATH", str(GITHUB_KEY_PATH.resolve()))
            config.GITHUB_PRIVATE_KEY_PATH = str(GITHUB_KEY_PATH.resolve())
    
    configured = bool(app_id and installation_id and has_private_key)
    
    return {
        "app_id": app_id,
        "installation_id": installation_id,
        "configured": configured,
        "has_private_key": has_private_key
    }


def delete_github_config() -> None:
    """
    Löscht die GitHub Apps Konfiguration.
    """
    # Lösche Private Key Datei
    delete_private_key()
    
    # Entferne aus .env
    update_env_file("GITHUB_APP_ID", None)
    update_env_file("GITHUB_INSTALLATION_ID", None)
    update_env_file("GITHUB_PRIVATE_KEY_PATH", None)
    
    # Entferne aus Environment-Variablen
    os.environ.pop("GITHUB_APP_ID", None)
    os.environ.pop("GITHUB_INSTALLATION_ID", None)
    os.environ.pop("GITHUB_PRIVATE_KEY_PATH", None)
    
    # Aktualisiere config Objekt
    config.GITHUB_APP_ID = None
    config.GITHUB_INSTALLATION_ID = None
    config.GITHUB_PRIVATE_KEY_PATH = None
