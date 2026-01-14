"""
NiceGUI UI Components Module.

Dieses Modul enthält alle NiceGUI-UI-Komponenten:
- Login-Seite (Phase 9.2)
- Dashboard-Seite (Phase 13.2)
- Run-Historie & Details (Phase 13.3)
- Live-Log-Viewer & Metrics-Monitoring (Phase 13.4)
- Secrets-Management-UI (Phase 13.5)
- Scheduler-Konfiguration-UI (Phase 13.6)
"""

import logging
from typing import Optional

import httpx
from nicegui import ui

from app.config import config

logger = logging.getLogger(__name__)

def get_api_base_url() -> str:
    """
    Ermittelt die API-Base-URL.
    
    Da NiceGUI im selben Prozess wie FastAPI läuft, können wir
    die Base-URL aus der Konfiguration oder dem Browser-Kontext ermitteln.
    
    Returns:
        str: API-Base-URL
    """
    # Versuche URL aus Browser-Kontext zu ermitteln (wenn im Browser)
    try:
        # NiceGUI stellt window.location.origin über JavaScript zur Verfügung
        # Für jetzt verwenden wir einen einfacheren Ansatz
        # In Produktion sollte dies über eine Konfiguration gesetzt werden
        return "http://localhost:8000"
    except Exception:
        return "http://localhost:8000"


def get_auth_token() -> Optional[str]:
    """
    Holt das JWT-Token aus dem Browser-Storage.
    
    Returns:
        Optional[str]: JWT-Token wenn vorhanden, sonst None
    """
    try:
        return ui.context.client.storage.get("auth_token")
    except Exception:
        return None


def set_auth_token(token: str) -> None:
    """
    Speichert das JWT-Token im Browser-Storage.
    
    Args:
        token: JWT-Token
    """
    try:
        ui.context.client.storage.set("auth_token", token)
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Auth-Tokens: {e}")


def clear_auth_token() -> None:
    """
    Löscht das JWT-Token aus dem Browser-Storage.
    """
    try:
        ui.context.client.storage.remove("auth_token")
    except Exception as e:
        logger.error(f"Fehler beim Löschen des Auth-Tokens: {e}")


def is_authenticated() -> bool:
    """
    Prüft ob der Benutzer authentifiziert ist.
    
    Returns:
        bool: True wenn Token vorhanden, sonst False
    """
    return get_auth_token() is not None


async def login_user(username: str, password: str) -> tuple[bool, Optional[str]]:
    """
    Authentifiziert einen Benutzer über die API.
    
    Args:
        username: Benutzername
        password: Passwort
        
    Returns:
        tuple[bool, Optional[str]]: (Erfolg, Fehlermeldung)
    """
    try:
        api_url = get_api_base_url()
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{api_url}/auth/login",
                json={"username": username, "password": password},
                timeout=10.0
            )
            
            if response.status_code == 200:
                data = response.json()
                token = data.get("access_token")
                if token:
                    set_auth_token(token)
                    return True, None
                else:
                    return False, "Token nicht in Antwort erhalten"
            else:
                error_data = response.json()
                return False, error_data.get("detail", "Authentifizierung fehlgeschlagen")
    except httpx.TimeoutException:
        return False, "Zeitüberschreitung beim Verbinden mit dem Server"
    except Exception as e:
        logger.error(f"Fehler bei Login: {e}")
        return False, f"Fehler: {str(e)}"


async def logout_user() -> None:
    """
    Meldet den Benutzer ab.
    """
    token = get_auth_token()
    if token:
        try:
            api_url = get_api_base_url()
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{api_url}/auth/logout",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=10.0
                )
        except Exception as e:
            logger.error(f"Fehler bei Logout: {e}")
    
    clear_auth_token()


@ui.page("/login")
def login_page() -> None:
    """
    Login-Seite für NiceGUI.
    
    Zeigt ein Login-Formular an und authentifiziert Benutzer über die API.
    Nach erfolgreichem Login wird der Benutzer zur Hauptseite weitergeleitet.
    """
    # Prüfe ob bereits authentifiziert
    if is_authenticated():
        ui.open("/")
        return
    
    # Login-Formular
    with ui.card().classes("absolute-center w-96"):
        ui.label("Fast-Flow Orchestrator").classes("text-h4 mb-4")
        ui.label("Anmeldung erforderlich").classes("text-body2 text-grey-7 mb-6")
        
        username_input = ui.input(
            "Benutzername",
            placeholder="Benutzername eingeben"
        ).classes("w-full mb-4")
        
        password_input = ui.input(
            "Passwort",
            password=True,
            placeholder="Passwort eingeben"
        ).classes("w-full mb-4")
        
        error_label = ui.label("").classes("text-red-500 text-sm mb-4")
        error_label.set_visibility(False)
        
        login_button = ui.button(
            "Anmelden",
            on_click=lambda: handle_login(
                username_input.value,
                password_input.value,
                error_label,
                login_button
            )
        ).classes("w-full mb-2")
        
        # Enter-Taste für Login
        def on_enter():
            handle_login(
                username_input.value,
                password_input.value,
                error_label,
                login_button
            )
        
        username_input.on("keydown.enter", on_enter)
        password_input.on("keydown.enter", on_enter)
        
        ui.separator().classes("my-4")
        
        ui.label(
            "⚠️ Standard-Credentials: admin/admin\n"
            "Bitte in Produktion ändern!"
        ).classes("text-xs text-grey-6 text-center")


async def handle_login(
    username: str,
    password: str,
    error_label: ui.label,
    login_button: ui.button
) -> None:
    """
    Behandelt den Login-Prozess.
    
    Args:
        username: Benutzername
        password: Passwort
        error_label: UI-Label für Fehlermeldungen
        login_button: Login-Button (für Deaktivierung während der Anfrage)
    """
    if not username or not password:
        error_label.text = "Bitte Benutzername und Passwort eingeben"
        error_label.set_visibility(True)
        return
    
    # Deaktiviere Login-Button während der Anfrage
    login_button.set_enabled(False)
    error_label.set_visibility(False)
    
    success, error_message = await login_user(username, password)
    
    if success:
        ui.notify("Erfolgreich angemeldet", color="positive")
        ui.open("/")
    else:
        error_label.text = error_message or "Authentifizierung fehlgeschlagen"
        error_label.set_visibility(True)
        login_button.set_enabled(True)


@ui.page("/")
def main_page() -> None:
    """
    Hauptseite (Dashboard).
    
    Prüft Authentifizierung und zeigt Dashboard an.
    Wird in Phase 13 vollständig implementiert.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    with ui.header().classes("bg-primary text-white"):
        ui.label("Fast-Flow Orchestrator").classes("text-h5")
        with ui.row().classes("ml-auto"):
            ui.button(
                "Abmelden",
                on_click=lambda: handle_logout()
            ).classes("bg-red-500")
    
    with ui.column().classes("w-full p-4"):
        ui.label("Dashboard").classes("text-h4 mb-4")
        ui.label("Willkommen beim Fast-Flow Orchestrator!").classes("text-body1")
        ui.label(
            "Das vollständige Dashboard wird in Phase 13 implementiert."
        ).classes("text-body2 text-grey-6 mt-2")


async def handle_logout() -> None:
    """
    Behandelt den Logout-Prozess.
    """
    await logout_user()
    ui.notify("Erfolgreich abgemeldet", color="info")
    ui.open("/login")


def init_ui(app) -> None:
    """
    Initialisiert NiceGUI und mountet es in die FastAPI-App.
    
    Args:
        app: FastAPI-App-Instanz
    """
    ui.run_with(
        app=app,
        storage_secret=config.JWT_SECRET_KEY,  # Für persistentes Storage
        title="Fast-Flow Orchestrator",
        favicon="🚀",
        dark=False
    )
    
    logger.info("NiceGUI UI initialisiert")
