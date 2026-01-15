"""
Git Sync API Endpoints.

Dieses Modul enthält alle REST-API-Endpoints für Git-Synchronisation:
- Git Pull ausführen
- Git-Status anzeigen
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session
from datetime import datetime
import json
import urllib.parse
import requests

from app.database import get_session
from app.git_sync import sync_pipelines, get_sync_status, get_sync_logs, test_github_app_token
from app.config import config
from app.github_config import (
    save_github_config,
    load_github_config,
    delete_github_config,
    validate_github_private_key
)
from app.github_oauth import (
    generate_oauth_state,
    store_oauth_state,
    get_oauth_state,
    delete_oauth_state
)

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncRequest(BaseModel):
    """Request-Model für Git-Sync."""
    branch: Optional[str] = None


@router.post("", response_model=Dict[str, Any])
async def sync(
    request: SyncRequest,
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """
    Führt Git Pull ausführen (mit Branch-Auswahl).
    
    Führt Git-Sync mit UV Pre-Heating aus:
    - Step 1: Git Pull (Aktualisierung des Codes)
    - Step 2: Discovery (Suche nach allen requirements.txt)
    - Step 3: Pre-Heating: Für jede Pipeline mit requirements.txt wird
      `uv pip compile` ausgeführt (lädt alle Pakete in Host-Cache)
    
    Args:
        request: Request-Body mit optionalem Branch (Standard: config.GIT_BRANCH)
        session: SQLModel Session
        
    Returns:
        Dictionary mit Sync-Status und Pre-Heating-Ergebnissen
        
    Raises:
        HTTPException: Wenn Git-Sync fehlschlägt
    """
    try:
        result = await sync_pipelines(
            branch=request.branch,
            session=session
        )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message", "Git-Sync fehlgeschlagen")
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Git-Sync: {str(e)}"
        )


@router.get("/status", response_model=Dict[str, Any])
async def sync_status() -> Dict[str, Any]:
    """
    Gibt Git-Status anzeigen.
    
    Zeigt Informationen über:
    - Aktueller Branch
    - Remote-URL
    - Letzter Commit
    - Pipeline-Discovery-Status
    - Pre-Heating-Status (welche Pipelines sind gecached)
    
    Returns:
        Dictionary mit Git-Status-Informationen
    """
    try:
        status_info = await get_sync_status()
        return status_info
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen des Git-Status: {str(e)}"
        )


class SyncSettingsRequest(BaseModel):
    """Request-Model für Sync-Einstellungen."""
    auto_sync_enabled: Optional[bool] = None
    auto_sync_interval: Optional[int] = None


@router.get("/settings", response_model=Dict[str, Any])
async def get_sync_settings() -> Dict[str, Any]:
    """
    Gibt aktuelle Sync-Einstellungen zurück.
    
    Returns:
        Dictionary mit Sync-Einstellungen
    """
    return {
        "auto_sync_enabled": config.AUTO_SYNC_ENABLED,
        "auto_sync_interval": config.AUTO_SYNC_INTERVAL
    }


@router.put("/settings", response_model=Dict[str, Any])
async def update_sync_settings(
    request: SyncSettingsRequest
) -> Dict[str, Any]:
    """
    Aktualisiert Sync-Einstellungen.
    
    Hinweis: Einstellungen werden in Environment-Variablen gespeichert.
    Für persistente Änderungen muss die .env-Datei aktualisiert werden.
    Diese Funktion aktualisiert nur die laufende Instanz.
    
    Args:
        request: Request-Body mit neuen Einstellungen
    
    Returns:
        Dictionary mit aktualisierten Einstellungen
    """
    import os
    
    # Einstellungen aktualisieren (nur für laufende Instanz)
    if request.auto_sync_enabled is not None:
        os.environ["AUTO_SYNC_ENABLED"] = str(request.auto_sync_enabled).lower()
        config.AUTO_SYNC_ENABLED = request.auto_sync_enabled
    
    if request.auto_sync_interval is not None:
        if request.auto_sync_interval < 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Auto-Sync-Intervall muss mindestens 60 Sekunden betragen"
            )
        os.environ["AUTO_SYNC_INTERVAL"] = str(request.auto_sync_interval)
        config.AUTO_SYNC_INTERVAL = request.auto_sync_interval
    
    return {
        "auto_sync_enabled": config.AUTO_SYNC_ENABLED,
        "auto_sync_interval": config.AUTO_SYNC_INTERVAL,
        "message": "Einstellungen aktualisiert (nur für laufende Instanz. Für persistente Änderungen .env-Datei bearbeiten)"
    }


@router.get("/logs", response_model=List[Dict[str, Any]])
async def get_sync_logs_endpoint(
    limit: int = Query(100, ge=1, le=1000, description="Maximale Anzahl Log-Einträge")
) -> List[Dict[str, Any]]:
    """
    Gibt Sync-Logs zurück.
    
    Args:
        limit: Maximale Anzahl Log-Einträge (Standard: 100, Max: 1000)
    
    Returns:
        Liste von Sync-Log-Einträgen (neueste zuerst)
    """
    try:
        logs = await get_sync_logs(limit=limit)
        return logs
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der Sync-Logs: {str(e)}"
        )


class GitHubConfigRequest(BaseModel):
    """Request-Model für GitHub Apps Konfiguration."""
    app_id: str
    installation_id: str
    private_key: str


@router.get("/github-config", response_model=Dict[str, Any])
async def get_github_config() -> Dict[str, Any]:
    """
    Gibt aktuelle GitHub Apps Konfiguration zurück.
    
    Private Key wird aus Sicherheitsgründen NICHT zurückgegeben.
    
    Returns:
        Dictionary mit Konfiguration (app_id, installation_id, configured, has_private_key)
    """
    try:
        config_data = load_github_config()
        return config_data
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Abrufen der GitHub Config: {str(e)}"
        )


@router.post("/github-config", response_model=Dict[str, Any])
async def save_github_config_endpoint(
    request: GitHubConfigRequest
) -> Dict[str, Any]:
    """
    Speichert GitHub Apps Konfiguration.
    
    Speichert Private Key in ./data/github_app_key.pem und aktualisiert
    Environment-Variablen und .env Datei.
    
    Args:
        request: Request-Body mit app_id, installation_id, private_key
        
    Returns:
        Dictionary mit gespeicherter Konfiguration
        
    Raises:
        HTTPException: Wenn Validierung fehlschlägt
    """
    try:
        # Validiere Private Key Format
        if not validate_github_private_key(request.private_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiges Private Key Format. Muss PEM-Format sein (-----BEGIN ... -----END ...)"
            )
        
        # Speichere Konfiguration
        save_github_config(
            app_id=request.app_id,
            installation_id=request.installation_id,
            private_key=request.private_key
        )
        
        # Lade aktualisierte Konfiguration
        config_data = load_github_config()
        
        return {
            "success": True,
            "message": "GitHub Apps Konfiguration erfolgreich gespeichert",
            **config_data
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Speichern der GitHub Config: {str(e)}"
        )


@router.post("/github-config/test", response_model=Dict[str, Any])
async def test_github_config() -> Dict[str, Any]:
    """
    Testet die GitHub Apps Konfiguration durch Token-Generierung.
    
    Versucht ein Installation Access Token zu generieren ohne Git-Operationen.
    Nützlich zum Validieren der Konfiguration.
    
    Returns:
        Dictionary mit Test-Ergebnis (success, message)
    """
    try:
        success, message = test_github_app_token()
        
        if success:
            return {
                "success": True,
                "message": message
            }
        else:
            return {
                "success": False,
                "message": message
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Testen der GitHub Config: {str(e)}"
        )


@router.get("/github-installation/callback")
async def github_installation_callback(
    installation_id: str = Query(..., description="Installation ID von GitHub"),
    setup_action: Optional[str] = Query(None, description="Setup Action (install, update)"),
    state: Optional[str] = Query(None, description="OAuth State Token")
) -> RedirectResponse:
    """
    Callback-Endpoint für GitHub App Installation.
    
    GitHub redirects hierher nach der Installation der App.
    Die Installation ID wird automatisch abgerufen und gespeichert.
    
    Args:
        installation_id: Installation ID von GitHub
        setup_action: Setup Action (install, update)
        state: Optional OAuth State Token
        
    Returns:
        Redirect zum Frontend mit Erfolgs-Message
    """
    try:
        # Lade aktuelle Config (App ID sollte bereits vorhanden sein)
        current_config = load_github_config()
        
        if not current_config.get("app_id"):
            # App ID fehlt - sollte nicht passieren, aber Fallback
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub App ist nicht konfiguriert. Bitte erstellen Sie zuerst eine App."
            )
        
        # Validiere State falls vorhanden
        if state:
            state_data = get_oauth_state(state)
            if state_data and state_data.get("type") == "installation":
                # State ist gültig - verwende App ID aus State
                app_id = state_data.get("app_id")
            else:
                app_id = current_config.get("app_id")
        else:
            app_id = current_config.get("app_id")
        
        # Aktualisiere Konfiguration mit Installation ID
        # Lade Private Key (muss bereits vorhanden sein)
        from app.github_config import GITHUB_KEY_PATH
        if not GITHUB_KEY_PATH.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Private Key fehlt. Bitte konfigurieren Sie die App zuerst."
            )
        
        with open(GITHUB_KEY_PATH, "r") as f:
            private_key = f.read()
        
        # Speichere vollständige Konfiguration
        save_github_config(
            app_id=str(app_id),
            installation_id=installation_id,
            private_key=private_key
        )
        
        # Lösche State falls vorhanden
        if state:
            delete_oauth_state(state)
        
        # Redirect zum Frontend mit Erfolgs-Message
        frontend_url = config.FRONTEND_URL or config.BASE_URL or "http://localhost:3000"
        redirect_url = f"{frontend_url}/sync?tab=github&installation_success=true"
        return RedirectResponse(url=redirect_url)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Verarbeiten der Installation: {str(e)}"
        )


@router.delete("/github-config", response_model=Dict[str, Any])
async def delete_github_config_endpoint() -> Dict[str, Any]:
    """
    Löscht GitHub Apps Konfiguration.
    
    Entfernt Private Key Datei und Environment-Variablen.
    
    Returns:
        Dictionary mit Bestätigung
    """
    try:
        delete_github_config()
        
        return {
            "success": True,
            "message": "GitHub Apps Konfiguration erfolgreich gelöscht"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Löschen der GitHub Config: {str(e)}"
        )


# GitHub App Manifest Flow Endpoints

@router.get("/github-manifest/authorize", response_model=Dict[str, Any])
async def github_manifest_authorize() -> Dict[str, Any]:
    """
    Generiert GitHub App Manifest Authorization URL.
    
    Erstellt ein Manifest JSON und gibt die URL zurück, zu der der Benutzer
    weitergeleitet werden soll, um die GitHub App zu erstellen.
    
    Returns:
        Dictionary mit authorization_url und state
    """
    try:
        # Generiere State Token für CSRF-Schutz
        state = generate_oauth_state()
        
        # Base URL für Callbacks
        base_url = config.BASE_URL.rstrip('/')
        callback_url = f"{base_url}/api/sync/github-manifest/callback"
        
        # Erstelle Manifest JSON
        # Permissions: Minimal - nur Read für Contents (für Git Pull)
        # Setup URL: Wird nach Installation aufgerufen, um Installation ID automatisch zu erhalten
        setup_url = f"{base_url}/api/sync/github-installation/callback"
        
        manifest = {
            "name": "Fast-Flow Orchestrator",
            "url": base_url,
            "hook_attributes": {
                "url": f"{base_url}/api/webhooks/github",
                "active": False  # Webhooks optional
            },
            "redirect_url": callback_url,
            "setup_url": setup_url,  # Automatischer Callback nach Installation
            "callback_urls": [callback_url],
            "public": False,
            "default_permissions": {
                "contents": "read",  # Nur Read - für Git Pull ausreichend
                "metadata": "read"
            },
            "default_events": [],
            # Wichtig: Keine OAuth-Anfrage während Installation (vereinfacht Flow)
            "request_oauth_on_install": False
        }
        
        # Speichere State
        store_oauth_state(state, {
            "type": "manifest",
            "callback_url": callback_url,
            "setup_url": setup_url
        })
        
        # Encode Manifest als URL-Parameter
        manifest_json = json.dumps(manifest)
        manifest_encoded = urllib.parse.quote(manifest_json)
        
        # GitHub Manifest URL (OHNE setup_action - wir machen manuellen Redirect nach Code-Exchange)
        # Für User: https://github.com/settings/apps/new
        # Für Org: https://github.com/organizations/{org}/settings/apps/new
        manifest_url = f"https://github.com/settings/apps/new?manifest={manifest_encoded}&state={state}"
        
        return {
            "authorization_url": manifest_url,
            "state": state
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Generieren der Manifest URL: {str(e)}"
        )


@router.get("/github-manifest/callback")
async def github_manifest_callback(
    code: str = Query(..., description="Temporärer Code von GitHub"),
    installation_id: Optional[str] = Query(None, description="Installation ID (wenn setup_action=install verwendet wurde)"),
    state: str = Query(..., description="OAuth State Token")
) -> RedirectResponse:
    """
    Callback-Endpoint für GitHub App Manifest Flow.
    
    GitHub redirects hierher nach der App-Erstellung UND Installation (wenn setup_action=install).
    Mit setup_action=install kommt sowohl code als auch installation_id in einem Schritt!
    
    Args:
        code: Temporärer Code von GitHub (muss innerhalb 1 Stunde eingelöst werden)
        installation_id: Installation ID (wenn setup_action=install verwendet wurde)
        state: OAuth State Token für CSRF-Schutz
        
    Returns:
        Redirect zum Frontend
    """
    try:
        # Validiere State
        state_data = get_oauth_state(state)
        if not state_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiger oder abgelaufener state token"
            )
        
        # Versuche Code-Exchange direkt (ohne User Token - GitHub akzeptiert das manchmal)
        exchange_url = f"https://api.github.com/app-manifests/{code}/conversions"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        try:
            response = requests.post(exchange_url, headers=headers, timeout=30)
            
            if response.status_code == 201:
                # Erfolg! Credentials erhalten
                credentials = response.json()
                
                app_id = str(credentials.get("id"))
                private_key = credentials.get("pem")
                
                if app_id and private_key:
                    # Coolify-Methode: Speichere App-Daten zuerst, dann sofortiger Redirect zur Installation
                    # Das gibt uns Sicherheit: App-Daten sind gespeichert, auch wenn User Installation abbricht
                    save_github_config(
                        app_id=app_id,
                        installation_id="",  # Wird nach Installation gesetzt
                        private_key=private_key
                    )
                    
                    # Hole App Slug aus Credentials
                    app_slug = credentials.get("slug")
                    if not app_slug:
                        # Fallback: Verwende App ID (weniger schön, aber funktioniert)
                        app_slug = app_id
                    
                    # Speichere App ID im State für Installation Callback
                    store_oauth_state(state, {
                        "type": "installation",
                        "app_id": app_id,
                        "app_slug": app_slug
                    })
                    
                    # SOFORTIGER Redirect zur Installation (Coolify-Methode)
                    # User landet direkt in der Repository-Auswahl, ohne weitere Klicks
                    install_url = f"https://github.com/apps/{app_slug}/installations/new?state={state}"
                    
                    # Redirect direkt zur Installation (User wählt nur Repos)
                    return RedirectResponse(url=install_url)
            
            # Exchange fehlgeschlagen - weiterleiten mit Code für manuellen Exchange
            # (z.B. wenn User Token erforderlich ist)
            frontend_url = config.FRONTEND_URL or config.BASE_URL or "http://localhost:3000"
            redirect_url = f"{frontend_url}/sync?tab=github&manifest_code={code}&state={state}&exchange_error=true"
            return RedirectResponse(url=redirect_url)
            
        except requests.RequestException:
            # Netzwerk-Fehler - weiterleiten mit Code
            frontend_url = config.FRONTEND_URL or config.BASE_URL or "http://localhost:3000"
            redirect_url = f"{frontend_url}/sync?tab=github&manifest_code={code}&state={state}&exchange_error=true"
            return RedirectResponse(url=redirect_url)
        
    except HTTPException:
        raise
    except Exception as e:
        # Bei anderen Fehlern: Weiterleiten mit Code
        frontend_url = config.FRONTEND_URL or config.BASE_URL or "http://localhost:3000"
        redirect_url = f"{frontend_url}/sync?tab=github&manifest_code={code}&state={state}&exchange_error=true"
        return RedirectResponse(url=redirect_url)


class ManifestExchangeRequest(BaseModel):
    """Request-Model für Manifest Code Exchange."""
    code: str
    state: str


@router.post("/github-manifest/exchange", response_model=Dict[str, Any])
async def github_manifest_exchange(
    request: ManifestExchangeRequest
) -> Dict[str, Any]:
    """
    Tauscht Manifest Code gegen GitHub App Credentials.
    
    Ruft GitHub API auf, um den temporären Code gegen die vollständigen
    App-Credentials zu tauschen (App ID, Private Key, Client ID, etc.).
    
    Args:
        request: Request mit code und state
        
    Returns:
        Dictionary mit gespeicherter Konfiguration
        
    Raises:
        HTTPException: Wenn Code-Exchange fehlschlägt
    """
    try:
        # Validiere State
        state_data = get_oauth_state(request.state)
        if not state_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ungültiger oder abgelaufener state token"
            )
        
        # Prüfe ob Code im State gespeichert ist (vom Callback)
        stored_code = state_data.get("code")
        if stored_code and stored_code != request.code:
            # Code wurde bereits verwendet oder stimmt nicht überein
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Code stimmt nicht mit gespeichertem Code überein"
            )
        
        # Exchange Code gegen Credentials
        # POST https://api.github.com/app-manifests/{code}/conversions
        exchange_url = f"https://api.github.com/app-manifests/{request.code}/conversions"
        
        # GitHub API erfordert einen User Token für den Exchange
        # Aber: Der Exchange kann auch ohne Token funktionieren, wenn der Code gültig ist
        # Versuche es erstmal ohne Token (GitHub akzeptiert das manchmal)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        response = requests.post(exchange_url, headers=headers, timeout=30)
        
        if response.status_code == 401:
            # Token erforderlich - das ist normal für den Manifest Exchange
            # Der Benutzer muss eingeloggt sein auf GitHub
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="GitHub API erfordert Authentifizierung. Bitte stellen Sie sicher, dass Sie auf GitHub eingeloggt sind und versuchen Sie es erneut."
            )
        
        response.raise_for_status()
        credentials = response.json()
        
        # Extrahiere Credentials
        app_id = str(credentials.get("id"))
        private_key = credentials.get("pem")
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")
        webhook_secret = credentials.get("webhook_secret")
        
        if not app_id or not private_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="GitHub API hat keine vollständigen Credentials zurückgegeben"
            )
        
        # Speichere Konfiguration
        # Für jetzt speichern wir nur App ID und Private Key
        # Installation ID muss später über den Installation Flow abgerufen werden
        save_github_config(
            app_id=app_id,
            installation_id="",  # Wird später über Installation Flow gesetzt
            private_key=private_key
        )
        
        # Lösche State nach erfolgreichem Exchange
        delete_oauth_state(request.state)
        
        return {
            "success": True,
            "message": "GitHub App erfolgreich erstellt und konfiguriert",
            "app_id": app_id,
            "client_id": client_id,
            "has_private_key": True,
            "next_step": "Bitte installieren Sie die App in Ihrem Repository/Organisation"
        }
        
    except HTTPException:
        raise
    except requests.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Code-Exchange mit GitHub API: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fehler beim Manifest Exchange: {str(e)}"
        )
