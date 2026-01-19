# Error-Tracking & Telemetrie (PostHog)

Fast-Flow nutzt **PostHog Cloud EU** (Frankfurt) für Fehlerberichte und Product Analytics. Die Nutzung ist **opt-in** und wird vom Admin gesteuert. Alle Daten sind anonym, sensible Keys werden entfernt.

---

## Übersicht

| Phase   | Inhalt |
|---------|--------|
| **Phase 1 (aktiv)** | Fehlerberichte: Backend- und Frontend-Exceptions an PostHog |
| **Phase 2 (aktiv bei enable_telemetry)** | Product Analytics: User (Register/Login), Pipeline-Runs, Sync, instance_heartbeat inkl. Storage/RAM/CPU. distinct_id = eine UUID pro Instanz (Anzahl aktive Instanzen); total_users_bucket (1, 2-5, …) für anonyme Nutzerzahlen. **Session Recording (Replay) wird ausdrücklich nicht genutzt.** |

---

## Steuerung

- **`SystemSettings`** (DB, Singleton `id=1`):
  - `is_setup_completed` – ob der First-Run-Wizard abgeschlossen ist
  - `enable_error_reporting` – Fehlerberichte an PostHog (Phase 1)
  - `enable_telemetry` – für Phase 2 (Product Analytics, anonyme Nutzungsstatistiken). **Session Recording wird nicht verwendet.**
- **First-Run-Wizard**: Beim ersten Admin-Login erscheint ein Modal; dort können Fehlerberichte und Nutzungsstatistiken ein-/ausgeschaltet werden. Session Recording ist ausgeschlossen.
- **Einstellungen → Global Privacy & Telemetry**: Admins können die Toggles jederzeit unter **Einstellungen** (nur für Admins sichtbar) anpassen. Session Recording wird nicht genutzt.

---

## Backend (Python)

Implementierung orientiert an der [PostHog Product Analytics Installation (Python)](https://posthog.com/docs/product-analytics/installation/python):

- **Init**: `Posthog(project_api_key=..., host=config.POSTHOG_HOST)` (EU: `https://eu.posthog.com`). Lazy-Init bei `enable_error_reporting` **oder** `enable_telemetry`. `get_posthog_client_for_telemetry(session)` für Product Analytics.
- **Capture**: `client.capture(event, distinct_id=..., properties=...)`. In allen Backend-Events wird `"$process_person_profile": False` mitgesendet (keine Person-Profile für Instanz-UUIDs; vgl. PostHog-Docs).
- **Shutdown**: `shutdown_posthog()` beim App-Exit (Flush ausstehender Events) sowie bei `enable_error_reporting=false`.
- **Product Analytics** (`app/analytics.py`): `track_event` und Wrapper. Nur aktiv bei `enable_telemetry`. Events: `user_registered`, `user_logged_in` (provider: github|google), `pipeline_run_started`, `pipeline_run_finished` (u.a. success), `sync_completed`, `sync_failed`, `instance_heartbeat` (täglich 03:00 UTC inkl. total_users_bucket, total_pipelines, total_scheduled_jobs, db_kind, uv_pre_heat_enabled, pipelines_with_requirements, log_files_count, log_files_size_mb, database_size_mb, free_disk_gb, system_ram_total_mb, system_ram_percent, system_cpu_percent).
- **Erfasste Fehler**:
  - FastAPI-Exception-Handler: alle Exceptions, die als 500 enden; Properties: `$request_method`, `$current_url` (ohne Query), `$request_path`
  - Exception-Autocapture des SDK (unbehandelte Exceptions)
  - Manuell: `capture_exception(exc, session, properties=...)`
- **Startup-Test (nur `ENVIRONMENT=development`)**: Beim Start wird immer eine Test-Exception an PostHog gesendet (unabhängig von `enable_error_reporting`), erkennbar an `$fastflow_startup_test=True`.
- **Test-Button (nur `ENVIRONMENT=development`)**: Unter **Einstellungen → Entwicklung** können Test-Exceptions für **Backend** oder **Frontend** ausgelöst werden (erkennbar an `$fastflow_backend_test` / `$fastflow_frontend_test`).
- **Daten**: `distinct_id` = anonyme UUID aus `SystemSettings`; Properties werden mit Scrubbing (Keys mit `password`, `secret`, `api_key`, `token`) bereinigt. Query-Strings werden in URLs nicht mitgeschickt.

---

## Frontend (React)

- **posthog-js**: Init nur, wenn `/api/settings/telemetry-status` `enable_error_reporting: true` liefert (öffentlicher Endpoint, kein Auth).
- **Exception-Autocapture** (`window.onerror`, `window.onunhandledrejection`) sowie **ErrorBoundary** mit `captureException` für React-Fehler.
- **Session Recording**: wird **nicht** verwendet. In posthog-js ist `disable_session_recording: true` gesetzt; das Backend sendet nur anonyme Events (kein Replay).
- **Hosts**: `https://eu.posthog.com`, Ingest/Scripts über `eu.i.posthog.com`, `eu-assets.i.posthog.com` (CSP in `app/middleware/security_headers.py` angepasst).

---

## API

| Endpoint | Auth | Beschreibung |
|----------|------|--------------|
| `GET /api/settings/telemetry-status` | nein | Liefert `enable_error_reporting`, `posthog_api_key`, `posthog_host` für Frontend-Init |
| `GET /api/settings/system` | Admin | `is_setup_completed`, `enable_telemetry`, `enable_error_reporting` |
| `PUT /api/settings/system` | Admin | Toggles und `is_setup_completed` aktualisieren; bei `enable_error_reporting=false` wird der PostHog-Client heruntergefahren |
| `POST /api/settings/trigger-test-exception` | eingeloggt | Nur bei `ENVIRONMENT=development`; sendet Test-Exception (Backend) an PostHog |

---

## Content-Security-Policy (CSP)

Damit PostHog laden und senden kann, sind in `app/middleware/security_headers.py` erlaubt:

- **script-src**: `https://eu-assets.i.posthog.com`
- **connect-src**: `https://eu.i.posthog.com`, `https://eu.posthog.com`, `https://eu-assets.i.posthog.com`

---

## Wizard erneut anzeigen (zum Testen)

Setze `is_setup_completed` auf `false`, danach Seite neu laden (als Admin einloggen):

```bash
# SQLite
sqlite3 data/fastflow.db "UPDATE system_settings SET is_setup_completed = 0 WHERE id = 1;"

# PostgreSQL
psql "$DATABASE_URL" -c "UPDATE system_settings SET is_setup_completed = false WHERE id = 1;"
```

---

## Weitere Infos

- **PostHog**: [posthog.com](https://posthog.com)
- **DB-Schema**: `SystemSettings` in `docs/database/SCHEMA.md` bzw. Migration `011_add_system_settings`
