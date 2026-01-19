# Error-Tracking & Telemetrie (PostHog)

Fast-Flow nutzt **PostHog Cloud EU** (Frankfurt) für Fehlerberichte. Die Nutzung ist **opt-in** und wird vom Admin gesteuert. Alle Daten sind anonym, sensible Keys werden entfernt.

---

## Übersicht

| Phase   | Inhalt |
|---------|--------|
| **Phase 1 (aktiv)** | Fehlerberichte: Backend- und Frontend-Exceptions an PostHog |
| **Phase 2 (vorbereitet)** | Nutzungsstatistiken, Session Replay, Surveys (Toggles in DB/UI, noch nicht angebunden) |

---

## Steuerung

- **`SystemSettings`** (DB, Singleton `id=1`):
  - `is_setup_completed` – ob der First-Run-Wizard abgeschlossen ist
  - `enable_error_reporting` – Fehlerberichte an PostHog (Phase 1)
  - `enable_telemetry` – für Phase 2 (Product Analytics, Replay, Surveys)
- **First-Run-Wizard**: Beim ersten Admin-Login erscheint ein Modal; dort können Fehlerberichte und (vorbereitet) Nutzungsstatistiken ein-/ausgeschaltet werden.
- **Einstellungen → Global Privacy & Telemetry**: Admins können die Toggles jederzeit unter **Einstellungen** (nur für Admins sichtbar) anpassen.

---

## Backend (Python)

- **PostHog Python SDK** (`app/posthog_client.py`): Lazy-Init nur bei `enable_error_reporting`.
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
