# Error Tracking & Telemetry (PostHog)

Fast-Flow uses **PostHog Cloud EU** (Frankfurt) for error reporting and product analytics. Usage is **opt-in** and controlled by the admin. All data is anonymous; sensitive keys are removed.

---

## Overview

| Phase   | Content |
|---------|--------|
| **Phase 1 (active)** | Error reporting: backend and frontend exceptions to PostHog |
| **Phase 2 (active when enable_telemetry)** | Product analytics: user (register/login), pipeline runs, sync, instance_heartbeat including storage/RAM/CPU. distinct_id = one UUID per instance (count of active instances); total_users_bucket (1, 2-5, …) for anonymous user counts. **Session recording (replay) is explicitly not used.** |

---

## Control

- **`SystemSettings`** (DB, singleton `id=1`):
  - `is_setup_completed` – whether the first-run wizard is completed
  - `enable_error_reporting` – error reports to PostHog (Phase 1)
  - `enable_telemetry` – for Phase 2 (product analytics, anonymous usage statistics). **Session recording is not used.**
- **First-run wizard**: On first admin login a modal appears; error reporting and usage statistics can be toggled there. Session recording is excluded.
- **Settings → Global Privacy & Telemetry**: Admins can adjust toggles anytime under **Settings** (visible to admins only). Session recording is not used.

---

## Backend (Python)

Implementation follows the [PostHog Product Analytics Installation (Python)](https://posthog.com/docs/product-analytics/installation/python):

- **Init**: `Posthog(project_api_key=..., host=config.POSTHOG_HOST)` (EU: `https://eu.posthog.com`). Lazy init when `enable_error_reporting` **or** `enable_telemetry`. `get_posthog_client_for_telemetry(session)` for product analytics.
- **Capture**: `client.capture(event, distinct_id=..., properties=...)`. All backend events include `"$process_person_profile": False` (no person profiles for instance UUIDs; see PostHog docs).
- **Shutdown**: `shutdown_posthog()` on app exit (flush pending events) and when `enable_error_reporting=false`.
- **Product analytics** (`app/analytics/`): `track_event` and wrappers. Active only when `enable_telemetry`. Events: `user_registered`, `user_logged_in` (provider: github|google|microsoft|custom), `pipeline_run_started`, `pipeline_run_finished` (incl. success), `sync_completed`, `sync_failed`, `instance_heartbeat` (incl. total_users_bucket, total_pipelines, total_scheduled_jobs, db_kind, uv_pre_heat_enabled, pipelines_with_requirements, log_files_count, log_files_size_mb, database_size_mb, free_disk_gb, system_ram_total_mb, system_ram_percent, system_cpu_percent). **instance_heartbeat:** once on app start, then as scheduled (daily 03:00 UTC).
- **Captured errors**:
  - FastAPI exception handler: all exceptions that end as 500; properties: `$request_method`, `$current_url` (without query), `$request_path`
  - SDK exception autocapture (unhandled exceptions)
  - Manual: `capture_exception(exc, session, properties=...)`
- **Startup test (only `ENVIRONMENT=development`)**: On start a test exception is always sent to PostHog (regardless of `enable_error_reporting`), identifiable by `$fastflow_startup_test=True`.
- **Test button (only `ENVIRONMENT=development`)**: Under **Settings → Development** test exceptions can be triggered for **backend** or **frontend** (identifiable by `$fastflow_backend_test` / `$fastflow_frontend_test`).
- **Data**: `distinct_id` = anonymous UUID from `SystemSettings`; properties are scrubbed (keys with `password`, `secret`, `api_key`, `token`). Query strings are not included in URLs.

---

## Frontend (React)

- **posthog-js**: Init only when `/api/settings/telemetry-status` returns `enable_error_reporting: true` (public endpoint, no auth).
- **Exception autocapture** (`window.onerror`, `window.onunhandledrejection`) and **ErrorBoundary** with `captureException` for React errors.
- **Session recording**: **not** used. In posthog-js `disable_session_recording: true` is set; the backend sends only anonymous events (no replay).
- **Hosts**: `https://eu.posthog.com`, ingest/scripts via `eu.i.posthog.com`, `eu-assets.i.posthog.com` (CSP adjusted in `app/middleware/security_headers.py`).

---

## API

| Endpoint | Auth | Description |
|----------|------|--------------|
| `GET /api/settings/telemetry-status` | no | Returns `enable_error_reporting`, `posthog_api_key`, `posthog_host` for frontend init |
| `GET /api/settings/system` | Admin | `is_setup_completed`, `enable_telemetry`, `enable_error_reporting` |
| `PUT /api/settings/system` | Admin | Update toggles and `is_setup_completed`; when `enable_error_reporting=false` the PostHog client is shut down |
| `POST /api/settings/trigger-test-exception` | logged in | Only when `ENVIRONMENT=development`; sends test exception (backend) to PostHog |

---

## Content-Security-Policy (CSP)

To allow PostHog to load and send, the following are allowed in `app/middleware/security_headers.py`:

- **script-src**: `https://eu-assets.i.posthog.com`
- **connect-src**: `https://eu.i.posthog.com`, `https://eu.posthog.com`, `https://eu-assets.i.posthog.com`

---

## Show wizard again (for testing)

Set `is_setup_completed` to `false`, then reload the page (log in as admin):

```bash
# SQLite
sqlite3 data/fastflow.db "UPDATE system_settings SET is_setup_completed = 0 WHERE id = 1;"

# PostgreSQL
psql "$DATABASE_URL" -c "UPDATE system_settings SET is_setup_completed = false WHERE id = 1;"
```

---

## Further info

- **PostHog**: [posthog.com](https://posthog.com)
- **DB schema**: `SystemSettings` in `docs/database/SCHEMA.md` or migration `011_add_system_settings`
