"""
NiceGUI UI Components Module.

Dieses Modul enthält alle NiceGUI-UI-Komponenten:
- Login-Seite (Phase 9.2)
- Dashboard-Seite (Phase 13.2)
- Run-Historie & Details (Phase 13.3)
- Live-Log-Viewer & Metrics-Monitoring (Phase 13.4)
- Secrets-Management-UI (Phase 13.5)
- Scheduler-Konfiguration-UI (Phase 13.6)
- Git-Sync-UI & Konfiguration (Phase 13.8)
- Pipeline-Management-UI (Phase 13.9)
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID

import httpx
from nicegui import ui

from app.config import config

logger = logging.getLogger(__name__)

# Globale Variablen für API-Base-URL
API_BASE_URL = "http://localhost:8000"


def get_api_base_url() -> str:
    """
    Ermittelt die API-Base-URL.
    
    Da NiceGUI im selben Prozess wie FastAPI läuft, können wir
    die Base-URL aus der Konfiguration oder dem Browser-Kontext ermitteln.
    
    Returns:
        str: API-Base-URL
    """
    return API_BASE_URL


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


async def api_request(
    method: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Führt einen API-Request aus.
    
    Args:
        method: HTTP-Methode (GET, POST, PUT, DELETE)
        endpoint: API-Endpoint (ohne Base-URL)
        data: Request-Body (optional)
        params: Query-Parameter (optional)
        
    Returns:
        Dict[str, Any]: Response-Daten
        
    Raises:
        Exception: Wenn Request fehlschlägt
    """
    token = get_auth_token()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"{get_api_base_url()}{endpoint}"
    
    async with httpx.AsyncClient() as client:
        if method == "GET":
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
        elif method == "POST":
            response = await client.post(url, headers=headers, json=data, params=params, timeout=30.0)
        elif method == "PUT":
            response = await client.put(url, headers=headers, json=data, params=params, timeout=30.0)
        elif method == "DELETE":
            response = await client.delete(url, headers=headers, params=params, timeout=30.0)
        else:
            raise ValueError(f"Unbekannte HTTP-Methode: {method}")
        
        if response.status_code >= 400:
            error_data = response.json() if response.headers.get("content-type") == "application/json" else {}
            raise Exception(error_data.get("detail", f"HTTP {response.status_code}: {response.text}"))
        
        if response.status_code == 204:  # No Content
            return {}
        
        return response.json()


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


# ============================================================================
# Navigation & Layout
# ============================================================================

def create_navigation() -> None:
    """
    Erstellt die Navigation für alle Seiten.
    """
    with ui.header().classes("bg-primary text-white shadow-lg"):
        ui.label("Fast-Flow Orchestrator").classes("text-h5 font-bold")
        with ui.row().classes("ml-auto gap-2"):
            ui.button(
                icon="home",
                on_click=lambda: ui.open("/")
            ).props("flat").tooltip("Dashboard")
            ui.button(
                icon="play_arrow",
                on_click=lambda: ui.open("/runs")
            ).props("flat").tooltip("Runs")
            ui.button(
                icon="settings",
                on_click=lambda: ui.open("/pipelines")
            ).props("flat").tooltip("Pipelines")
            ui.button(
                icon="schedule",
                on_click=lambda: ui.open("/scheduler")
            ).props("flat").tooltip("Scheduler")
            ui.button(
                icon="lock",
                on_click=lambda: ui.open("/secrets")
            ).props("flat").tooltip("Secrets")
            ui.button(
                icon="sync",
                on_click=lambda: ui.open("/sync")
            ).props("flat").tooltip("Git Sync")
            ui.button(
                "Abmelden",
                icon="logout",
                on_click=lambda: handle_logout()
            ).classes("bg-red-500")


# ============================================================================
# Login Page
# ============================================================================

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


async def handle_logout() -> None:
    """
    Behandelt den Logout-Prozess.
    """
    await logout_user()
    ui.notify("Erfolgreich abgemeldet", color="info")
    ui.open("/login")


# ============================================================================
# Dashboard Page (Phase 13.2)
# ============================================================================

@ui.page("/")
def dashboard_page() -> None:
    """
    Dashboard-Seite mit Pipeline-Übersicht.
    
    Zeigt alle verfügbaren Pipelines mit Status, Statistiken und Quick-Actions.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Dashboard").classes("text-h4 mb-4")
        
        # Git-Sync-Status und Button
        with ui.row().classes("w-full gap-2 mb-4"):
            sync_status_label = ui.label("Git-Sync-Status wird geladen...").classes("text-body2")
            sync_button = ui.button(
                "Sync",
                icon="sync",
                on_click=lambda: handle_git_sync(sync_status_label, sync_button)
            )
        
        # Pipeline-Liste
        pipeline_container = ui.column().classes("w-full gap-4")
        
        # Auto-Refresh für Pipeline-Status
        async def refresh_pipelines():
            """Lädt Pipeline-Liste neu."""
            try:
                pipelines = await api_request("GET", "/pipelines")
                pipeline_container.clear()
                
                for pipeline in pipelines:
                    with ui.card().classes("w-full p-4"):
                        with ui.row().classes("w-full items-center gap-4"):
                            # Pipeline-Name und Status
                            with ui.column().classes("flex-1 gap-2"):
                                ui.label(pipeline["name"]).classes("text-h6")
                                
                                # Status-Badges
                                with ui.row().classes("gap-2"):
                                    status_color = "green" if pipeline["enabled"] else "grey"
                                    ui.badge(
                                        "Aktiv" if pipeline["enabled"] else "Inaktiv",
                                        color=status_color
                                    )
                                    
                                    if pipeline["has_requirements"]:
                                        cache_status = "Cached" if pipeline["last_cache_warmup"] else "Nicht cached"
                                        cache_color = "green" if pipeline["last_cache_warmup"] else "orange"
                                        ui.badge(cache_status, color=cache_color)
                                
                                # Statistiken
                                with ui.row().classes("gap-4 text-sm"):
                                    ui.label(f"Total: {pipeline['total_runs']}")
                                    ui.label(f"✓ {pipeline['successful_runs']}").classes("text-green-600")
                                    ui.label(f"✗ {pipeline['failed_runs']}").classes("text-red-600")
                                    
                                    if pipeline["total_runs"] > 0:
                                        success_rate = (pipeline["successful_runs"] / pipeline["total_runs"]) * 100
                                        ui.label(f"Erfolgsrate: {success_rate:.1f}%")
                                
                                # Resource-Limits (aus Metadaten)
                                metadata = pipeline.get("metadata", {})
                                if metadata:
                                    with ui.row().classes("gap-4 text-xs text-grey-6"):
                                        if "cpu_hard_limit" in metadata:
                                            ui.label(f"CPU: {metadata['cpu_hard_limit']}")
                                        if "mem_hard_limit" in metadata:
                                            ui.label(f"RAM: {metadata['mem_hard_limit']}")
                            
                            # Quick-Actions
                            with ui.column().classes("gap-2"):
                                ui.button(
                                    "Starten",
                                    icon="play_arrow",
                                    on_click=lambda p=pipeline: handle_start_pipeline(p["name"])
                                ).classes("bg-green-500")
                                
                                ui.button(
                                    "Details",
                                    icon="info",
                                    on_click=lambda p=pipeline: ui.open(f"/pipelines/{p['name']}")
                                ).classes("bg-blue-500")
                                
                                ui.button(
                                    "Runs",
                                    icon="history",
                                    on_click=lambda p=pipeline: ui.open(f"/runs?pipeline={p['name']}")
                                ).classes("bg-purple-500")
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Pipelines: {str(e)}", color="negative")
        
        # Initiales Laden
        await refresh_pipelines()
        
        # Auto-Refresh alle 5 Sekunden
        ui.timer(5.0, refresh_pipelines)


async def handle_git_sync(status_label: ui.label, sync_button: ui.button) -> None:
    """
    Führt Git-Sync aus.
    
    Args:
        status_label: Label für Status-Anzeige
        sync_button: Sync-Button (für Deaktivierung)
    """
    sync_button.set_enabled(False)
    status_label.text = "Sync läuft..."
    
    try:
        result = await api_request("POST", "/sync", data={})
        if result.get("success"):
            ui.notify("Git-Sync erfolgreich", color="positive")
            status_label.text = f"Letzter Sync: {datetime.now().strftime('%H:%M:%S')}"
        else:
            ui.notify(f"Git-Sync fehlgeschlagen: {result.get('message', 'Unbekannter Fehler')}", color="negative")
            status_label.text = "Sync fehlgeschlagen"
    except Exception as e:
        ui.notify(f"Fehler beim Git-Sync: {str(e)}", color="negative")
        status_label.text = "Fehler"
    finally:
        sync_button.set_enabled(True)


async def handle_start_pipeline(pipeline_name: str, env_vars: Optional[Dict[str, str]] = None, parameters: Optional[Dict[str, str]] = None) -> None:
    """
    Startet eine Pipeline mit optionalen Parametern.
    
    Args:
        pipeline_name: Name der Pipeline
        env_vars: Environment-Variablen (optional)
        parameters: Parameter (optional)
    """
    # Dialog für Parameter-Eingabe
    with ui.dialog() as dialog, ui.card().classes("w-96"):
        ui.label(f"Pipeline starten: {pipeline_name}").classes("text-h6 mb-4")
        
        # Parameter-Input (vereinfacht: ein Textfeld für JSON)
        params_input = ui.textarea(
            "Parameter (JSON-Format, optional)",
            placeholder='{"key": "value"}'
        ).classes("w-full mb-4")
        
        with ui.row().classes("gap-2"):
            ui.button(
                "Starten",
                on_click=lambda: handle_confirm_start_pipeline(
                    pipeline_name,
                    params_input.value,
                    dialog
                )
            ).classes("bg-green-500")
            ui.button("Abbrechen", on_click=dialog.close).classes("bg-grey-500")
        
        dialog.open()


async def handle_confirm_start_pipeline(pipeline_name: str, params_json: str, dialog: ui.dialog) -> None:
    """
    Bestätigt und startet die Pipeline.
    
    Args:
        pipeline_name: Name der Pipeline
        params_json: Parameter als JSON-String
        dialog: Dialog zum Schließen
    """
    try:
        parameters = {}
        if params_json.strip():
            try:
                parameters = json.loads(params_json)
            except json.JSONDecodeError:
                ui.notify("Ungültiges JSON-Format für Parameter", color="negative")
                return
        
        result = await api_request("POST", f"/pipelines/{pipeline_name}/run", data={
            "parameters": parameters
        })
        ui.notify(f"Pipeline '{pipeline_name}' gestartet", color="positive")
        dialog.close()
        ui.open(f"/runs/{result['id']}")
    except Exception as e:
        ui.notify(f"Fehler beim Starten der Pipeline: {str(e)}", color="negative")


# ============================================================================
# Run History & Details Page (Phase 13.3)
# ============================================================================

@ui.page("/runs")
def runs_page() -> None:
    """
    Run-Historie-Seite.
    
    Zeigt alle Runs in einer Tabelle mit Filterung und Sortierung.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Run-Historie").classes("text-h4 mb-4")
        
        # Filter
        with ui.row().classes("w-full gap-4 items-end"):
            pipeline_filter = ui.input(
                "Pipeline",
                placeholder="Pipeline-Name filtern"
            ).classes("flex-1")
            
            status_filter = ui.select(
                ["Alle", "PENDING", "RUNNING", "SUCCESS", "FAILED", "INTERRUPTED", "WARNING"],
                label="Status",
                value="Alle"
            ).classes("w-48")
            
            refresh_button = ui.button(
                "Aktualisieren",
                icon="refresh",
                on_click=lambda: refresh_runs_table()
            )
        
        # Runs-Tabelle
        runs_table = ui.table(
            columns=[
                {"name": "id", "label": "ID", "field": "id", "required": True},
                {"name": "pipeline_name", "label": "Pipeline", "field": "pipeline_name"},
                {"name": "status", "label": "Status", "field": "status"},
                {"name": "started_at", "label": "Gestartet", "field": "started_at"},
                {"name": "finished_at", "label": "Beendet", "field": "finished_at"},
                {"name": "exit_code", "label": "Exit-Code", "field": "exit_code"},
                {"name": "actions", "label": "Aktionen", "field": "actions"}
            ],
            rows=[],
            row_key="id"
        ).classes("w-full")
        
        async def refresh_runs_table():
            """Lädt Runs-Tabelle neu."""
            try:
                params = {}
                if pipeline_filter.value:
                    params["pipeline_name"] = pipeline_filter.value
                if status_filter.value != "Alle":
                    params["status_filter"] = status_filter.value
                
                runs = await api_request("GET", "/runs", params=params)
                
                # Tabellen-Daten vorbereiten
                table_rows = []
                for run in runs:
                    started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                    finished = datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00")) if run.get("finished_at") else None
                    
                    duration = ""
                    if finished:
                        delta = finished - started
                        duration = f"{delta.total_seconds():.1f}s"
                    
                    table_rows.append({
                        "id": str(run["id"]),
                        "pipeline_name": run["pipeline_name"],
                        "status": run["status"],
                        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
                        "finished_at": finished.strftime("%Y-%m-%d %H:%M:%S") if finished else "-",
                        "exit_code": run.get("exit_code", "-"),
                        "duration": duration,
                        "actions": f"view_{run['id']}"
                    })
                
                runs_table.rows = table_rows
                runs_table.update()
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Runs: {str(e)}", color="negative")
        
        # Initiales Laden
        await refresh_runs_table()
        
        # Auto-Refresh alle 3 Sekunden
        ui.timer(3.0, refresh_runs_table)
        
        # Klick-Handler für Tabellen-Zeilen
        def on_row_click(e):
            """Öffnet Run-Details bei Klick auf Zeile."""
            if e.args and len(e.args) > 0:
                run_id = e.args[0].get("id")
                if run_id:
                    ui.open(f"/runs/{run_id}")
        
        runs_table.on("rowClick", on_row_click)


@ui.page("/runs/{run_id}")
def run_details_page(run_id: str) -> None:
    """
    Run-Detailansicht.
    
    Zeigt alle Details eines Runs inklusive Logs und Metrics.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Run-Details").classes("text-h4 mb-4")
        
        # Run-Details laden
        run_details_container = ui.column().classes("w-full gap-4")
        
        async def load_run_details():
            """Lädt Run-Details."""
            try:
                run = await api_request("GET", f"/runs/{run_id}")
                
                run_details_container.clear()
                
                with ui.card().classes("w-full p-4"):
                    with ui.column().classes("gap-2"):
                        ui.label(f"Pipeline: {run['pipeline_name']}").classes("text-h6")
                        ui.label(f"Status: {run['status']}").classes("text-body1")
                        ui.label(f"Run-ID: {run_id}").classes("text-body2 text-grey-6")
                        
                        if run.get("started_at"):
                            started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                            ui.label(f"Gestartet: {started.strftime('%Y-%m-%d %H:%M:%S')}").classes("text-body2")
                        
                        if run.get("finished_at"):
                            finished = datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00"))
                            ui.label(f"Beendet: {finished.strftime('%Y-%m-%d %H:%M:%S')}").classes("text-body2")
                        
                        if run.get("exit_code") is not None:
                            ui.label(f"Exit-Code: {run['exit_code']}").classes("text-body2")
                        
                        if run.get("uv_version"):
                            ui.label(f"UV-Version: {run['uv_version']}").classes("text-body2")
                        
                        if run.get("setup_duration"):
                            ui.label(f"Setup-Dauer: {run['setup_duration']:.2f}s").classes("text-body2")
                        
                        # Cancel-Button für laufende Runs
                        if run.get("status") == "RUNNING":
                            ui.button(
                                "Abbrechen",
                                icon="stop",
                                on_click=lambda: handle_cancel_run(run_id)
                            ).classes("bg-red-500 mt-2")
                        
                        # Retry-Button für fehlgeschlagene Runs
                        if run.get("status") == "FAILED":
                            ui.button(
                                "Erneut starten",
                                icon="refresh",
                                on_click=lambda: handle_retry_run(run["pipeline_name"], run.get("env_vars"), run.get("parameters"))
                            ).classes("bg-green-500 mt-2")
                
                # Logs und Metrics
                with ui.tabs().classes("w-full") as tabs:
                    logs_tab = ui.tab("Logs", icon="description")
                    metrics_tab = ui.tab("Metrics", icon="show_chart")
                
                with ui.tab_panels(tabs, value=logs_tab).classes("w-full"):
                    with ui.tab_panel(logs_tab):
                        await load_run_logs(run_id, run.get("status") == "RUNNING")
                    
                    with ui.tab_panel(metrics_tab):
                        await load_run_metrics(run_id, run.get("status") == "RUNNING")
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Run-Details: {str(e)}", color="negative")
        
        await load_run_details()


async def load_run_logs(run_id: str, is_running: bool) -> None:
    """
    Lädt Run-Logs (Live oder aus Datei).
    
    Verwendet ui.log mit max_lines=500 für Browser-Memory-Leak-Prevention.
    Alte Zeilen werden automatisch entfernt (Ring-Buffer-Verhalten).
    
    Args:
        run_id: Run-ID
        is_running: Ob Run noch läuft
    """
    log_viewer = ui.log(max_lines=500).classes("w-full h-96")
    
    # Auto-Scroll-Toggle
    auto_scroll = ui.switch("Auto-Scroll", value=True).classes("mb-2")
    
    # Download-Button
    async def download_logs():
        """Lädt Logs herunter."""
        try:
            response = await httpx.AsyncClient().get(
                f"{get_api_base_url()}/runs/{run_id}/logs",
                headers={"Authorization": f"Bearer {get_auth_token()}"},
                timeout=30.0
            )
            if response.status_code == 200:
                ui.download(response.content, filename=f"run_{run_id}_logs.txt", media_type="text/plain")
        except Exception as e:
            ui.notify(f"Fehler beim Herunterladen der Logs: {str(e)}", color="negative")
    
    ui.button("Logs herunterladen", icon="download", on_click=download_logs).classes("mb-2")
    
    last_line_count = 0
    
    if is_running:
        # Live-Log-Streaming via Polling (NiceGUI unterstützt kein natives SSE)
        async def poll_logs():
            nonlocal last_line_count
            try:
                # Versuche Logs aus Datei zu lesen (letzte 100 Zeilen)
                response = await httpx.AsyncClient().get(
                    f"{get_api_base_url()}/runs/{run_id}/logs",
                    params={"tail": 100},
                    headers={"Authorization": f"Bearer {get_auth_token()}"},
                    timeout=5.0
                )
                if response.status_code == 200:
                    content = response.text
                    lines = content.split("\n")
                    # Nur neue Zeilen hinzufügen
                    new_lines = lines[last_line_count:]
                    for line in new_lines:
                        if line.strip():
                            log_viewer.push(line)
                    last_line_count = len(lines)
            except Exception:
                pass
        
        ui.timer(0.5, poll_logs)
    else:
        # Abgeschlossener Run: Lade gesamte Logs
        try:
            response = await httpx.AsyncClient().get(
                f"{get_api_base_url()}/runs/{run_id}/logs",
                headers={"Authorization": f"Bearer {get_auth_token()}"},
                timeout=30.0
            )
            if response.status_code == 200:
                content = response.text
                for line in content.split("\n"):
                    if line.strip():
                        log_viewer.push(line)
        except Exception as e:
            ui.notify(f"Fehler beim Laden der Logs: {str(e)}", color="negative")


async def load_run_metrics(run_id: str, is_running: bool) -> None:
    """
    Lädt Run-Metrics (Live oder aus Datei).
    
    Zeigt CPU- und RAM-Usage als Line-Charts mit Soft-Limit-Warnungen.
    
    Args:
        run_id: Run-ID
        is_running: Ob Run noch läuft
    """
    metrics_container = ui.column().classes("w-full gap-4")
    
    if is_running:
        # Live-Metrics via Polling
        cpu_values = []
        ram_values = []
        timestamps = []
        
        cpu_progress = ui.linear_progress(value=0).classes("w-full")
        cpu_label = ui.label("CPU: 0%").classes("text-body2")
        
        ram_progress = ui.linear_progress(value=0).classes("w-full")
        ram_label = ui.label("RAM: 0 MB / 0 MB").classes("text-body2")
        
        async def poll_metrics():
            try:
                # Versuche Metrics aus Datei zu lesen (letzte 50 Einträge)
                response = await httpx.AsyncClient().get(
                    f"{get_api_base_url()}/runs/{run_id}/metrics",
                    headers={"Authorization": f"Bearer {get_auth_token()}"},
                    timeout=5.0
                )
                if response.status_code == 200:
                    metrics = response.json()
                    if metrics:
                        latest = metrics[-1]
                        cpu_percent = latest.get("cpu_percent", 0)
                        ram_mb = latest.get("ram_mb", 0)
                        ram_limit_mb = latest.get("ram_limit_mb", 0)
                        
                        cpu_progress.value = cpu_percent / 100.0
                        cpu_label.text = f"CPU: {cpu_percent:.1f}%"
                        
                        if ram_limit_mb > 0:
                            ram_progress.value = ram_mb / ram_limit_mb
                            ram_label.text = f"RAM: {ram_mb:.1f} MB / {ram_limit_mb:.1f} MB"
                        else:
                            ram_label.text = f"RAM: {ram_mb:.1f} MB"
                        
                        # Soft-Limit-Warnung
                        if latest.get("soft_limit_exceeded"):
                            ui.notify("Soft-Limit überschritten!", color="warning", timeout=2000)
            except Exception:
                pass
        
        ui.timer(2.0, poll_metrics)
    else:
        # Abgeschlossener Run: Lade Metrics aus Datei
        try:
            metrics = await api_request("GET", f"/runs/{run_id}/metrics")
            
            if metrics:
                # CPU-Chart mit Soft-Limit
                cpu_data = []
                ram_data = []
                timestamps = []
                
                for i, m in enumerate(metrics):
                    timestamps.append(i)
                    cpu_data.append(m.get("cpu_percent", 0))
                    ram_data.append(m.get("ram_mb", 0))
                
                # CPU-Chart
                with ui.card().classes("w-full p-4"):
                    ui.label("CPU Usage (%)").classes("text-h6 mb-2")
                    # NiceGUI Chart (vereinfachte Darstellung)
                    cpu_chart_data = "\n".join([f"{i}: {v:.1f}%" for i, v in enumerate(cpu_data[-50:])])
                    ui.label(cpu_chart_data).classes("text-xs font-mono")
                
                # RAM-Chart
                with ui.card().classes("w-full p-4"):
                    ui.label("RAM Usage (MB)").classes("text-h6 mb-2")
                    ram_chart_data = "\n".join([f"{i}: {v:.1f} MB" for i, v in enumerate(ram_data[-50:])])
                    ui.label(ram_chart_data).classes("text-xs font-mono")
                
                # Download-Button
                async def download_metrics():
                    """Lädt Metrics als JSON herunter."""
                    try:
                        response = await httpx.AsyncClient().get(
                            f"{get_api_base_url()}/runs/{run_id}/metrics",
                            headers={"Authorization": f"Bearer {get_auth_token()}"},
                            timeout=30.0
                        )
                        if response.status_code == 200:
                            ui.download(
                                response.content,
                                filename=f"run_{run_id}_metrics.json",
                                media_type="application/json"
                            )
                    except Exception as e:
                        ui.notify(f"Fehler beim Herunterladen der Metrics: {str(e)}", color="negative")
                
                ui.button("Metrics herunterladen", icon="download", on_click=download_metrics).classes("mt-2")
        except Exception as e:
            metrics_container.add(ui.label(f"Keine Metrics verfügbar: {str(e)}"))


# ============================================================================
# Secrets Management UI (Phase 13.5)
# ============================================================================

@ui.page("/secrets")
def secrets_page() -> None:
    """
    Secrets-Management-Seite.
    
    Zeigt alle Secrets in einer Tabelle und ermöglicht CRUD-Operationen.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Secrets Management").classes("text-h4 mb-4")
        
        # Neues Secret-Formular
        with ui.card().classes("w-full p-4"):
            ui.label("Neues Secret/Parameter hinzufügen").classes("text-h6 mb-4")
            
            secret_key_input = ui.input("Key", placeholder="Secret-Key").classes("w-full mb-2")
            secret_value_input = ui.input("Value", password=True, placeholder="Secret-Wert").classes("w-full mb-2")
            is_parameter = ui.checkbox("Als Parameter (nicht verschlüsselt)").classes("mb-2")
            
            ui.button(
                "Hinzufügen",
                icon="add",
                on_click=lambda: handle_create_secret(secret_key_input, secret_value_input, is_parameter)
            ).classes("bg-green-500")
        
        # Secrets-Tabelle
        secrets_table = ui.table(
            columns=[
                {"name": "key", "label": "Key", "field": "key"},
                {"name": "value", "label": "Value", "field": "value"},
                {"name": "created_at", "label": "Erstellt", "field": "created_at"},
                {"name": "actions", "label": "Aktionen", "field": "actions"}
            ],
            rows=[],
            row_key="key"
        ).classes("w-full")
        
        async def refresh_secrets():
            """Lädt Secrets-Tabelle neu."""
            try:
                secrets = await api_request("GET", "/secrets")
                
                table_rows = []
                for secret in secrets:
                    with ui.row().classes("hidden") as action_row:
                        edit_btn = ui.button(
                            "Bearbeiten",
                            icon="edit",
                            on_click=lambda s=secret: handle_edit_secret(s)
                        ).classes("bg-blue-500")
                        
                        delete_btn = ui.button(
                            "Löschen",
                            icon="delete",
                            on_click=lambda s=secret: handle_delete_secret(s["key"])
                        ).classes("bg-red-500")
                    
                    table_rows.append({
                        "key": secret["key"],
                        "value": "***" * 10,  # Versteckter Wert
                        "created_at": datetime.fromisoformat(secret["created_at"].replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S"),
                        "actions": f"edit_{secret['key']}"
                    })
                
                secrets_table.rows = table_rows
                secrets_table.update()
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Secrets: {str(e)}", color="negative")
        
        await refresh_secrets()
        
        ui.timer(5.0, refresh_secrets)


async def handle_create_secret(key_input: ui.input, value_input: ui.input, is_parameter: ui.checkbox) -> None:
    """
    Erstellt ein neues Secret oder Parameter.
    
    Args:
        key_input: Key-Input-Feld
        value_input: Value-Input-Feld
        is_parameter: Checkbox für Parameter-Flag
    """
    if not key_input.value or not value_input.value:
        ui.notify("Bitte Key und Value eingeben", color="negative")
        return
    
    try:
        # Parameter werden nicht verschlüsselt (werden als normale Parameter gespeichert)
        # Für jetzt: Beide werden als Secrets gespeichert (später kann man Parameter separat speichern)
        await api_request("POST", "/secrets", data={
            "key": key_input.value,
            "value": value_input.value
        })
        ui.notify("Secret/Parameter erfolgreich erstellt", color="positive")
        key_input.value = ""
        value_input.value = ""
        is_parameter.value = False
    except Exception as e:
        ui.notify(f"Fehler beim Erstellen des Secrets: {str(e)}", color="negative")


async def handle_edit_secret(secret: Dict[str, Any]) -> None:
    """
    Bearbeitet ein Secret.
    
    Args:
        secret: Secret-Daten
    """
    # Dialog zum Bearbeiten
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Secret bearbeiten: {secret['key']}").classes("text-h6 mb-4")
        value_input = ui.input("Value", password=True, value=secret.get("value", "")).classes("w-full mb-4")
        
        with ui.row().classes("gap-2"):
            ui.button(
                "Speichern",
                on_click=lambda: handle_update_secret(secret["key"], value_input.value, dialog)
            ).classes("bg-green-500")
            ui.button("Abbrechen", on_click=dialog.close).classes("bg-grey-500")
        
        dialog.open()


async def handle_update_secret(key: str, value: str, dialog: ui.dialog) -> None:
    """
    Aktualisiert ein Secret.
    
    Args:
        key: Secret-Key
        value: Neuer Wert
        dialog: Dialog zum Schließen
    """
    try:
        await api_request("PUT", f"/secrets/{key}", data={"value": value})
        ui.notify("Secret erfolgreich aktualisiert", color="positive")
        dialog.close()
    except Exception as e:
        ui.notify(f"Fehler beim Aktualisieren des Secrets: {str(e)}", color="negative")


async def handle_delete_secret(key: str) -> None:
    """
    Löscht ein Secret (mit Bestätigung).
    
    Args:
        key: Secret-Key
    """
    # Bestätigungs-Dialog
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Secret '{key}' wirklich löschen?").classes("text-h6 mb-4")
        
        with ui.row().classes("gap-2"):
            ui.button(
                "Löschen",
                on_click=lambda: handle_confirm_delete_secret(key, dialog)
            ).classes("bg-red-500")
            ui.button("Abbrechen", on_click=dialog.close).classes("bg-grey-500")
        
        dialog.open()


async def handle_confirm_delete_secret(key: str, dialog: ui.dialog) -> None:
    """
    Bestätigt und führt das Löschen eines Secrets aus.
    
    Args:
        key: Secret-Key
        dialog: Dialog zum Schließen
    """
    try:
        await api_request("DELETE", f"/secrets/{key}")
        ui.notify("Secret erfolgreich gelöscht", color="positive")
        dialog.close()
    except Exception as e:
        ui.notify(f"Fehler beim Löschen des Secrets: {str(e)}", color="negative")


# ============================================================================
# Scheduler Configuration UI (Phase 13.6)
# ============================================================================

@ui.page("/scheduler")
def scheduler_page() -> None:
    """
    Scheduler-Konfiguration-Seite.
    
    Zeigt alle geplanten Jobs und ermöglicht CRUD-Operationen.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Scheduler").classes("text-h4 mb-4")
        
        # Neuer Job-Formular
        with ui.card().classes("w-full p-4"):
            ui.label("Neuen Job erstellen").classes("text-h6 mb-4")
            
            pipeline_input = ui.input("Pipeline-Name", placeholder="Pipeline-Name").classes("w-full mb-2")
            trigger_type_select = ui.select(
                ["CRON", "INTERVAL"],
                label="Trigger-Typ",
                value="CRON"
            ).classes("w-full mb-2")
            trigger_value_input = ui.input("Trigger-Wert", placeholder="Cron-Expression oder Interval").classes("w-full mb-2")
            
            ui.button(
                "Job erstellen",
                icon="add",
                on_click=lambda: handle_create_job(pipeline_input, trigger_type_select, trigger_value_input)
            ).classes("bg-green-500")
        
        # Jobs-Tabelle
        jobs_table = ui.table(
            columns=[
                {"name": "id", "label": "ID", "field": "id"},
                {"name": "pipeline_name", "label": "Pipeline", "field": "pipeline_name"},
                {"name": "trigger_type", "label": "Trigger-Typ", "field": "trigger_type"},
                {"name": "trigger_value", "label": "Trigger-Wert", "field": "trigger_value"},
                {"name": "enabled", "label": "Aktiviert", "field": "enabled"},
                {"name": "actions", "label": "Aktionen", "field": "actions"}
            ],
            rows=[],
            row_key="id"
        ).classes("w-full")
        
        async def refresh_jobs():
            """Lädt Jobs-Tabelle neu."""
            try:
                jobs = await api_request("GET", "/scheduler/jobs")
                
                table_rows = []
                for job in jobs:
                    table_rows.append({
                        "id": str(job["id"]),
                        "pipeline_name": job["pipeline_name"],
                        "trigger_type": job["trigger_type"],
                        "trigger_value": job["trigger_value"],
                        "enabled": "Ja" if job["enabled"] else "Nein",
                        "actions": f"edit_{job['id']}"
                    })
                
                jobs_table.rows = table_rows
                jobs_table.update()
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Jobs: {str(e)}", color="negative")
        
        await refresh_jobs()
        
        ui.timer(5.0, refresh_jobs)
        
        # Job-Aktionen (Edit, Delete, Enable/Disable) werden über Kontext-Menü oder Buttons hinzugefügt


async def handle_create_job(
    pipeline_input: ui.input,
    trigger_type_select: ui.select,
    trigger_value_input: ui.input
) -> None:
    """
    Erstellt einen neuen Job.
    
    Args:
        pipeline_input: Pipeline-Name-Input
        trigger_type_select: Trigger-Typ-Select
        trigger_value_input: Trigger-Wert-Input
    """
    if not pipeline_input.value or not trigger_value_input.value:
        ui.notify("Bitte alle Felder ausfüllen", color="negative")
        return
    
    try:
        await api_request("POST", "/scheduler/jobs", data={
            "pipeline_name": pipeline_input.value,
            "trigger_type": trigger_type_select.value,
            "trigger_value": trigger_value_input.value,
            "enabled": True
        })
        ui.notify("Job erfolgreich erstellt", color="positive")
        pipeline_input.value = ""
        trigger_value_input.value = ""
    except Exception as e:
        ui.notify(f"Fehler beim Erstellen des Jobs: {str(e)}", color="negative")


# ============================================================================
# Git Sync UI (Phase 13.8)
# ============================================================================

@ui.page("/sync")
def sync_page() -> None:
    """
    Git-Sync-Seite.
    
    Zeigt Git-Status und ermöglicht manuellen Sync.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Git Sync").classes("text-h4 mb-4")
        
        # Sync-Status
        status_container = ui.column().classes("w-full gap-2")
        
        # Sync-Button
        sync_button = ui.button(
            "Sync ausführen",
            icon="sync",
            on_click=lambda: handle_sync(sync_button, status_container)
        ).classes("bg-blue-500 mb-4")
        
        async def load_sync_status():
            """Lädt Git-Sync-Status."""
            try:
                status = await api_request("GET", "/sync/status")
                
                status_container.clear()
                
                with ui.card().classes("w-full p-4"):
                    with ui.column().classes("gap-2"):
                        ui.label("Git-Status").classes("text-h6")
                        ui.label(f"Branch: {status.get('branch', 'N/A')}").classes("text-body2")
                        ui.label(f"Remote: {status.get('remote', 'N/A')}").classes("text-body2")
                        if status.get("last_commit"):
                            ui.label(f"Letzter Commit: {status['last_commit']}").classes("text-body2")
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden des Status: {str(e)}", color="negative")
        
        await load_sync_status()
        
        ui.timer(10.0, load_sync_status)


async def handle_sync(sync_button: ui.button, status_container: ui.column) -> None:
    """
    Führt Git-Sync aus.
    
    Args:
        sync_button: Sync-Button
        status_container: Container für Status-Anzeige
    """
    sync_button.set_enabled(False)
    
    try:
        result = await api_request("POST", "/sync", data={})
        if result.get("success"):
            ui.notify("Git-Sync erfolgreich", color="positive")
        else:
            ui.notify(f"Git-Sync fehlgeschlagen: {result.get('message', 'Unbekannter Fehler')}", color="negative")
    except Exception as e:
        ui.notify(f"Fehler beim Git-Sync: {str(e)}", color="negative")
    finally:
        sync_button.set_enabled(True)


# ============================================================================
# Pipeline Management UI (Phase 13.9)
# ============================================================================

@ui.page("/pipelines")
def pipelines_page() -> None:
    """
    Pipeline-Management-Seite.
    
    Zeigt alle Pipelines mit Details, Statistiken und Resource-Limits.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("Pipelines").classes("text-h4 mb-4")
        
        pipelines_container = ui.column().classes("w-full gap-4")
        
        async def load_pipelines():
            """Lädt Pipeline-Liste."""
            try:
                pipelines = await api_request("GET", "/pipelines")
                
                pipelines_container.clear()
                
                for pipeline in pipelines:
                    with ui.card().classes("w-full p-4"):
                        with ui.column().classes("gap-2"):
                            ui.label(pipeline["name"]).classes("text-h6")
                            
                            # Statistiken
                            with ui.row().classes("gap-4"):
                                ui.label(f"Total Runs: {pipeline['total_runs']}").classes("text-body2")
                                ui.label(f"Erfolgreich: {pipeline['successful_runs']}").classes("text-body2 text-green-600")
                                ui.label(f"Fehlgeschlagen: {pipeline['failed_runs']}").classes("text-body2 text-red-600")
                            
                            # Resource-Limits
                            metadata = pipeline.get("metadata", {})
                            if metadata:
                                with ui.row().classes("gap-4 text-sm"):
                                    if "cpu_hard_limit" in metadata:
                                        ui.label(f"CPU Limit: {metadata['cpu_hard_limit']}").classes("text-grey-6")
                                    if "mem_hard_limit" in metadata:
                                        ui.label(f"RAM Limit: {metadata['mem_hard_limit']}").classes("text-grey-6")
                            
                            # Aktionen
                            with ui.row().classes("gap-2"):
                                ui.button(
                                    "Starten",
                                    icon="play_arrow",
                                    on_click=lambda p=pipeline: handle_start_pipeline(p["name"])
                                ).classes("bg-green-500")
                                
                                ui.button(
                                    "Details",
                                    icon="info",
                                    on_click=lambda p=pipeline: ui.open(f"/pipelines/{p['name']}")
                                ).classes("bg-blue-500")
                                
                                ui.button(
                                    "Statistiken zurücksetzen",
                                    icon="refresh",
                                    on_click=lambda p=pipeline: handle_reset_stats(p["name"])
                                ).classes("bg-orange-500")
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Pipelines: {str(e)}", color="negative")
        
        await load_pipelines()
        
        ui.timer(5.0, load_pipelines)


@ui.page("/pipelines/{pipeline_name}")
def pipeline_details_page(pipeline_name: str) -> None:
    """
    Pipeline-Detailansicht.
    
    Zeigt alle Details einer Pipeline inklusive Statistiken und Runs.
    """
    # Prüfe Authentifizierung
    if not is_authenticated():
        ui.open("/login")
        return
    
    create_navigation()
    
    with ui.column().classes("w-full p-4 gap-4"):
        ui.label(f"Pipeline: {pipeline_name}").classes("text-h4 mb-4")
        
        details_container = ui.column().classes("w-full gap-4")
        
        async def load_pipeline_details():
            """Lädt Pipeline-Details."""
            try:
                # Pipeline-Info
                pipelines = await api_request("GET", "/pipelines")
                pipeline = next((p for p in pipelines if p["name"] == pipeline_name), None)
                
                if not pipeline:
                    ui.notify(f"Pipeline '{pipeline_name}' nicht gefunden", color="negative")
                    return
                
                details_container.clear()
                
                # Pipeline-Statistiken
                stats = await api_request("GET", f"/pipelines/{pipeline_name}/stats")
                
                with ui.card().classes("w-full p-4"):
                    with ui.column().classes("gap-2"):
                        ui.label("Statistiken").classes("text-h6")
                        ui.label(f"Total Runs: {stats['total_runs']}").classes("text-body1")
                        ui.label(f"Erfolgreich: {stats['successful_runs']}").classes("text-body1 text-green-600")
                        ui.label(f"Fehlgeschlagen: {stats['failed_runs']}").classes("text-body1 text-red-600")
                        ui.label(f"Erfolgsrate: {stats['success_rate']:.1f}%").classes("text-body1")
                        
                        ui.button(
                            "Statistiken zurücksetzen",
                            icon="refresh",
                            on_click=lambda: handle_reset_stats(pipeline_name)
                        ).classes("bg-orange-500 mt-2")
                
                # Runs-Historie
                runs = await api_request("GET", f"/pipelines/{pipeline_name}/runs", params={"limit": 20})
                
                with ui.card().classes("w-full p-4"):
                    ui.label("Letzte Runs").classes("text-h6 mb-4")
                    
                    runs_table = ui.table(
                        columns=[
                            {"name": "id", "label": "ID", "field": "id"},
                            {"name": "status", "label": "Status", "field": "status"},
                            {"name": "started_at", "label": "Gestartet", "field": "started_at"},
                            {"name": "actions", "label": "Aktionen", "field": "actions"}
                        ],
                        rows=[],
                        row_key="id"
                    ).classes("w-full")
                    
                    table_rows = []
                    for run in runs:
                        started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
                        table_rows.append({
                            "id": str(run["id"]),
                            "status": run["status"],
                            "started_at": started.strftime("%Y-%m-%d %H:%M:%S"),
                            "actions": f"view_{run['id']}"
                        })
                    
                    runs_table.rows = table_rows
                    runs_table.update()
            
            except Exception as e:
                ui.notify(f"Fehler beim Laden der Pipeline-Details: {str(e)}", color="negative")
        
        await load_pipeline_details()


async def handle_reset_stats(pipeline_name: str) -> None:
    """
    Setzt Pipeline-Statistiken zurück.
    
    Args:
        pipeline_name: Name der Pipeline
    """
    try:
        await api_request("POST", f"/pipelines/{pipeline_name}/stats/reset")
        ui.notify("Statistiken erfolgreich zurückgesetzt", color="positive")
    except Exception as e:
        ui.notify(f"Fehler beim Zurücksetzen der Statistiken: {str(e)}", color="negative")


async def handle_cancel_run(run_id: str) -> None:
    """
    Bricht einen laufenden Run ab.
    
    Args:
        run_id: Run-ID
    """
    try:
        await api_request("POST", f"/runs/{run_id}/cancel")
        ui.notify("Run wurde abgebrochen", color="info")
        # Seite neu laden
        ui.open(f"/runs/{run_id}")
    except Exception as e:
        ui.notify(f"Fehler beim Abbrechen des Runs: {str(e)}", color="negative")


async def handle_retry_run(pipeline_name: str, env_vars: Optional[Dict[str, str]], parameters: Optional[Dict[str, str]]) -> None:
    """
    Startet einen Run erneut (Retry).
    
    Args:
        pipeline_name: Name der Pipeline
        env_vars: Environment-Variablen (optional)
        parameters: Parameter (optional)
    """
    try:
        result = await api_request("POST", f"/pipelines/{pipeline_name}/run", data={
            "env_vars": env_vars or {},
            "parameters": parameters or {}
        })
        ui.notify(f"Pipeline '{pipeline_name}' erneut gestartet", color="positive")
        ui.open(f"/runs/{result['id']}")
    except Exception as e:
        ui.notify(f"Fehler beim erneuten Starten der Pipeline: {str(e)}", color="negative")


# ============================================================================
# NiceGUI Initialization
# ============================================================================

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
