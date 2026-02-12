---
slug: api
---

# API-Dokumentation

Diese Dokumentation beschreibt alle verfügbaren REST-API-Endpoints des Fast-Flow Orchestrators.

## Basis-URL

Alle API-Endpoints sind unter `/api` verfügbar. Die vollständige Basis-URL ist:
```
http://localhost:8000/api
```

## Authentifizierung

Die meisten Endpoints erfordern Authentifizierung. Verwenden Sie einen Bearer-Token im Authorization-Header:

```
Authorization: Bearer <token>
```

Token werden über GitHub OAuth (`GET /api/auth/github/authorize`) oder Google OAuth (`GET /api/auth/google/authorize`) erhalten; nach Autorisierung Redirect zu `/auth/callback#token=...`.

## Endpoints

### Health Check

#### `GET /health`, `GET /healthz` oder `GET /api/health`

Prüft den Status der Anwendung.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0"
}
```

---

## Pipelines

### `GET /api/pipelines`

Gibt eine Liste aller verfügbaren Pipelines zurück.

**Response:**
```json
[
  {
    "name": "pipeline_a",
    "has_requirements": true,
    "last_cache_warmup": "2024-01-15T10:30:00",
    "total_runs": 42,
    "successful_runs": 40,
    "failed_runs": 2,
    "enabled": true,
    "metadata": {
      "cpu_hard_limit": 1.0,
      "mem_hard_limit": "512m",
      "description": "Prozessiert täglich eingehende Daten",
      "tags": ["data-processing", "daily"]
    }
  }
]
```

### `POST /api/pipelines/{name}/run`

Startet eine Pipeline manuell.

**Request Body:**
```json
{
  "env_vars": {
    "API_KEY": "secret-key",
    "LOG_LEVEL": "DEBUG"
  },
  "parameters": {
    "input_file": "data.csv"
  }
}
```

**Limits:** Max. 50 Einträge pro `env_vars` und `parameters`, je Wert max. 16 KB.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "pipeline_name": "pipeline_a",
  "status": "RUNNING",
  "started_at": "2024-01-15T10:30:00",
  "log_file": "logs/550e8400-e29b-41d4-a716-446655440000.log"
}
```

**Fehler:**
- `404`: Pipeline nicht gefunden oder deaktiviert
- `429`: Concurrency-Limit erreicht

### `GET /api/pipelines/{name}/runs`

Gibt die Run-Historie einer Pipeline zurück.

**Query-Parameter:**
- `limit` (optional, Standard: 100): Maximale Anzahl Runs

**Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "pipeline_name": "pipeline_a",
    "status": "SUCCESS",
    "started_at": "2024-01-15T10:30:00",
    "finished_at": "2024-01-15T10:35:00",
    "exit_code": 0,
    "log_file": "logs/550e8400-e29b-41d4-a716-446655440000.log",
    "metrics_file": "logs/550e8400-e29b-41d4-a716-446655440000_metrics.jsonl"
  }
]
```

### `GET /api/pipelines/{name}/stats`

Gibt Pipeline-Statistiken zurück.

**Response:**
```json
{
  "pipeline_name": "pipeline_a",
  "total_runs": 42,
  "successful_runs": 40,
  "failed_runs": 2,
  "success_rate": 95.24,
  "webhook_runs": 5
}
```

### `POST /api/pipelines/{name}/stats/reset`

Setzt Pipeline-Statistiken zurück.

**Response:**
```json
{
  "message": "Statistiken für Pipeline 'pipeline_a' wurden zurückgesetzt"
}
```

### `GET /api/pipelines/{name}/daily-stats`

Gibt tägliche Pipeline-Statistiken zurück.

**Query-Parameter:**
- `days` (optional, Standard: 365): Anzahl der Tage zurück
- `start_date` (optional): Startdatum (ISO-Format: YYYY-MM-DD)
- `end_date` (optional): Enddatum (ISO-Format: YYYY-MM-DD)

**Response:**
```json
{
  "daily_stats": [
    {
      "date": "2024-01-15",
      "total_runs": 5,
      "successful_runs": 4,
      "failed_runs": 1,
      "success_rate": 80.0
    }
  ]
}
```

### `GET /api/pipelines/daily-stats/all`

Gibt tägliche Statistiken für alle Pipelines kombiniert zurück.

**Query-Parameter:** (gleich wie oben)

---

## Runs

### `GET /api/runs`

Gibt alle Runs zurück (mit Filterung und Pagination).

**Query-Parameter:**
- `pipeline_name` (optional): Filter nach Pipeline-Name
- `status_filter` (optional): Filter nach Status (PENDING, RUNNING, SUCCESS, FAILED, etc.)
- `start_date` (optional): Startdatum für Filterung (ISO-Format)
- `end_date` (optional): Enddatum für Filterung (ISO-Format)
- `limit` (optional, Standard: 50): Anzahl Runs pro Seite
- `offset` (optional, Standard: 0): Offset für Pagination

**Response:**
```json
{
  "runs": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "pipeline_name": "pipeline_a",
      "status": "SUCCESS",
      "started_at": "2024-01-15T10:30:00",
      "finished_at": "2024-01-15T10:35:00",
      "exit_code": 0,
      "log_file": "logs/550e8400-e29b-41d4-a716-446655440000.log",
      "metrics_file": "logs/550e8400-e29b-41d4-a716-446655440000_metrics.jsonl",
      "uv_version": "0.1.0",
      "setup_duration": 1.2
    }
  ],
  "total": 100,
  "page": 1,
  "page_size": 50
}
```

### `GET /api/runs/{run_id}`

Gibt Details eines Runs zurück.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "pipeline_name": "pipeline_a",
  "status": "SUCCESS",
  "started_at": "2024-01-15T10:30:00",
  "finished_at": "2024-01-15T10:35:00",
  "exit_code": 0,
  "log_file": "logs/550e8400-e29b-41d4-a716-446655440000.log",
  "metrics_file": "logs/550e8400-e29b-41d4-a716-446655440000_metrics.jsonl",
  "env_vars": {
    "API_KEY": "***",
    "LOG_LEVEL": "INFO"
  },
  "parameters": {
    "input_file": "data.csv"
  },
  "uv_version": "0.1.0",
  "setup_duration": 1.2
}
```

### `POST /api/runs/{run_id}/cancel`

Bricht einen laufenden Run ab.

**Response:**
```json
{
  "message": "Run 550e8400-e29b-41d4-a716-446655440000 wurde erfolgreich abgebrochen"
}
```

**Fehler:**
- `400`: Run ist bereits beendet
- `404`: Run nicht gefunden

### `GET /api/runs/{run_id}/health`

Gibt Container-Health-Status für einen Run zurück.

**Response:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "RUNNING",
  "container_running": true,
  "container_id": "abc123def456"
}
```

---

## Logs

### `GET /api/runs/{run_id}/logs`

Gibt Logs aus Datei zurück (für abgeschlossene Runs).

**Query-Parameter:**
- `tail` (optional): Anzahl der letzten Zeilen

**Response:** Plain Text (Log-Inhalt)

### `GET /api/runs/{run_id}/logs/stream`

Server-Sent Events für Live-Logs (für laufende Runs).

**Response:** `text/event-stream`

**Format:**
```
data: {"line": "Pipeline gestartet\n"}

data: {"line": "Verarbeite Daten...\n"}

```

---

## Metrics

### `GET /api/runs/{run_id}/metrics`

Gibt Metrics aus Datei zurück (für abgeschlossene Runs).

**Response:**
```json
[
  {
    "timestamp": "2024-01-15T10:30:00",
    "cpu_percent": 45.2,
    "ram_mb": 128.5,
    "ram_limit_mb": 512
  },
  {
    "timestamp": "2024-01-15T10:30:02",
    "cpu_percent": 50.1,
    "ram_mb": 135.2,
    "ram_limit_mb": 512
  }
]
```

### `GET /api/runs/{run_id}/metrics/stream`

Server-Sent Events für Live-Metrics (für laufende Runs).

**Response:** `text/event-stream`

**Format:**
```
data: {"timestamp": "2024-01-15T10:30:00", "cpu_percent": 45.2, "ram_mb": 128.5, "ram_limit_mb": 512}

```

---

## Scheduler

### `GET /api/scheduler/jobs`

Gibt alle geplanten Jobs zurück.

**Response:**
```json
[
  {
    "id": "660e8400-e29b-41d4-a716-446655440000",
    "pipeline_name": "pipeline_a",
    "trigger_type": "CRON",
    "trigger_value": "0 0 * * *",
    "enabled": true,
    "created_at": "2024-01-15T10:00:00",
    "next_run_time": "2024-01-16T00:00:00",
    "last_run_time": "2024-01-15T00:00:00",
    "run_count": 15
  }
]
```

### `GET /api/scheduler/jobs/{job_id}`

Gibt einen Job anhand der ID zurück.

### `POST /api/scheduler/jobs`

Erstellt einen neuen geplanten Job.

**Request Body:**
```json
{
  "pipeline_name": "pipeline_a",
  "trigger_type": "CRON",
  "trigger_value": "0 0 * * *",
  "enabled": true
}
```

**Trigger-Typen:**
- `CRON`: Cron-Expression (z.B. `"0 0 * * *"` für täglich um Mitternacht)
- `INTERVAL`: Interval in Sekunden (z.B. `"3600"` für stündlich)

**Fehler:**
- `404`: Pipeline nicht gefunden
- `400`: Ungültige Trigger-Expression
- `503`: Scheduler nicht verfügbar

### `PUT /api/scheduler/jobs/{job_id}`

Aktualisiert einen bestehenden Job.

**Request Body:**
```json
{
  "pipeline_name": "pipeline_b",
  "trigger_type": "INTERVAL",
  "trigger_value": "1800",
  "enabled": false
}
```

### `DELETE /api/scheduler/jobs/{job_id}`

Löscht einen Job.

**Response:** `204 No Content`

### `GET /api/scheduler/jobs/{job_id}/runs`

Gibt die Run-Historie für einen Job zurück.

**Query-Parameter:**
- `limit` (optional, Standard: 50): Maximale Anzahl Runs

---

## Secrets

### `GET /api/secrets`

Gibt alle Secrets zurück.

**Response:**
```json
[
  {
    "key": "API_KEY",
    "value": "secret-value",
    "is_parameter": false,
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T10:00:00"
  }
]
```

**Hinweis:** Secrets werden verschlüsselt gespeichert, aber entschlüsselt zurückgegeben. Parameter (`is_parameter: true`) werden nicht verschlüsselt.

### `POST /api/secrets/encrypt-for-pipeline`

Verschlüsselt einen Klartext mit dem Server-`ENCRYPTION_KEY` für manuellen Eintrag in `pipeline.json` unter `encrypted_env`. **Max. 64 KB** pro Wert.

**Request Body:** `{ "value": "klartext" }`

### `POST /api/secrets`

Erstellt ein neues Secret.

**Request Body:**
```json
{
  "key": "API_KEY",
  "value": "secret-value",
  "is_parameter": false
}
```

**Fehler:**
- `409`: Secret existiert bereits (verwende PUT für Aktualisierung)

### `PUT /api/secrets/{key}`

Aktualisiert ein bestehendes Secret.

**Request Body:**
```json
{
  "value": "new-secret-value",
  "is_parameter": false
}
```

### `DELETE /api/secrets/{key}`

Löscht ein Secret.

**Response:**
```json
{
  "message": "Secret 'API_KEY' erfolgreich gelöscht.",
  "key": "API_KEY"
}
```

---

## Sync (Git)

### `POST /api/sync`

Führt Git Pull aus (mit UV Pre-Heating).

**Request Body:**
```json
{
  "branch": "main"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Git-Sync erfolgreich",
  "branch": "main",
  "commit": "abc123def456",
  "pre_heating": {
    "pipelines_processed": 5,
    "pipelines_cached": 3,
    "pipelines_failed": 0
  }
}
```

### `GET /api/sync/status`

Gibt Git-Status zurück.

**Response:**
```json
{
  "branch": "main",
  "remote_url": "https://github.com/user/repo.git",
  "last_commit": "abc123def456",
  "last_commit_message": "Update pipelines",
  "last_sync": "2024-01-15T10:00:00",
  "pipelines_discovered": 5,
  "pre_heating_status": {
    "cached": 3,
    "not_cached": 2
  }
}
```

### `GET /api/sync/settings`

Gibt aktuelle Sync-Einstellungen zurück.

**Response:**
```json
{
  "auto_sync_enabled": true,
  "auto_sync_interval": 3600
}
```

### `PUT /api/sync/settings`

Aktualisiert Sync-Einstellungen.

**Request Body:**
```json
{
  "auto_sync_enabled": true,
  "auto_sync_interval": 1800
}
```

**Hinweis:** Einstellungen werden nur für die laufende Instanz aktualisiert. Für persistente Änderungen muss die `.env`-Datei bearbeitet werden.

### `GET /api/sync/logs`

Gibt Sync-Logs zurück.

**Query-Parameter:**
- `limit` (optional, Standard: 100): Maximale Anzahl Log-Einträge

### GitHub Apps Konfiguration

#### `GET /api/sync/github-config`

Gibt aktuelle GitHub Apps Konfiguration zurück.

**Response:**
```json
{
  "app_id": "123456",
  "installation_id": "789012",
  "configured": true,
  "has_private_key": true
}
```

**Hinweis:** Private Key wird aus Sicherheitsgründen NICHT zurückgegeben.

#### `POST /api/sync/github-config`

Speichert GitHub Apps Konfiguration.

**Request Body:**
```json
{
  "app_id": "123456",
  "installation_id": "789012",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n..."
}
```

#### `POST /api/sync/github-config/test`

Testet die GitHub Apps Konfiguration.

**Response:**
```json
{
  "success": true,
  "message": "Token erfolgreich generiert"
}
```

#### `DELETE /api/sync/github-config`

Löscht GitHub Apps Konfiguration.

### GitHub App Manifest Flow

**Erfordert Admin-Rechte** (authorize und exchange).

#### `GET /api/sync/github-manifest/authorize`

Generiert HTML-Formular für GitHub App Manifest Flow. Erfordert Admin-Login.

#### `GET /api/sync/github-manifest/callback`

Callback-Endpoint für GitHub App Manifest Flow (von GitHub aufgerufen).

#### `POST /api/sync/github-manifest/exchange`

Tauscht Manifest Code gegen GitHub App Credentials. Erfordert Admin-Login.

**Request Body:**
```json
{
  "code": "temporary-code",
  "state": "state-token"
}
```

---

## Settings

### `GET /api/settings`

Gibt die aktuellen System-Einstellungen zurück.

**Response:**
```json
{
  "log_retention_runs": 100,
  "log_retention_days": 30,
  "log_max_size_mb": 100,
  "max_concurrent_runs": 10,
  "container_timeout": 3600,
  "retry_attempts": 3,
  "auto_sync_enabled": true,
  "auto_sync_interval": 3600,
  "email_enabled": false,
  "smtp_host": null,
  "smtp_port": 587,
  "smtp_user": null,
  "smtp_from": null,
  "email_recipients": [],
  "teams_enabled": false,
  "teams_webhook_url": null
}
```

### `PUT /api/settings`

Aktualisiert System-Einstellungen.

**Hinweis:** Aktuell werden Einstellungen nur aus Environment-Variablen geladen. Diese Funktion gibt eine Warnung zurück, dass Einstellungen über Environment-Variablen geändert werden müssen.

### `GET /api/settings/storage`

Gibt Speicherplatz-Statistiken zurück.

**Response:**
```json
{
  "log_files_count": 150,
  "log_files_size_bytes": 52428800,
  "log_files_size_mb": 50.0,
  "total_disk_space_bytes": 107374182400,
  "total_disk_space_gb": 100.0,
  "used_disk_space_bytes": 53687091200,
  "used_disk_space_gb": 50.0,
  "free_disk_space_bytes": 53687091200,
  "free_disk_space_gb": 50.0,
  "log_files_percentage": 0.05,
  "database_size_bytes": 1048576,
  "database_size_mb": 1.0,
  "database_size_gb": 0.001,
  "database_percentage": 0.001
}
```

### `POST /api/settings/test-email`

Sendet eine Test-E-Mail.

**Response:**
```json
{
  "status": "success",
  "message": "Test-E-Mail erfolgreich an user@example.com gesendet"
}
```

### `POST /api/settings/test-teams`

Sendet eine Test-Teams-Nachricht.

**Response:**
```json
{
  "status": "success",
  "message": "Test-Teams-Nachricht erfolgreich gesendet"
}
```

### `POST /api/settings/cleanup/force`

Führt einen manuellen Force-Flush (Cleanup) durch.

**Response:**
```json
{
  "status": "success",
  "message": "Cleanup erfolgreich abgeschlossen",
  "summary": [
    "10 Runs aus Datenbank gelöscht",
    "15 Log-Dateien gelöscht",
    "5 Docker-Container gelöscht"
  ],
  "log_cleanup": {
    "deleted_runs": 10,
    "deleted_logs": 15,
    "deleted_metrics": 8,
    "truncated_logs": 2
  },
  "docker_cleanup": {
    "deleted_containers": 5,
    "deleted_volumes": 3
  }
}
```

### `GET /api/settings/system-metrics`

Gibt System-Metriken zurück.

**Response:**
```json
{
  "active_containers": 3,
  "containers_ram_mb": 384.5,
  "containers_cpu_percent": 45.2,
  "api_ram_mb": 128.0,
  "api_cpu_percent": 5.1,
  "system_ram_total_mb": 16384.0,
  "system_ram_used_mb": 8192.0,
  "system_ram_percent": 50.0,
  "system_cpu_percent": 25.5,
  "container_details": [
    {
      "run_id": "550e8400-e29b-41d4-a716-446655440000",
      "pipeline_name": "pipeline_a",
      "container_id": "abc123def456",
      "ram_mb": 128.5,
      "ram_percent": 25.1,
      "cpu_percent": 15.2,
      "status": "running"
    }
  ]
}
```

---

## Webhooks

### `POST /api/webhooks/{pipeline_name}/{webhook_key}`

Triggert eine Pipeline via Webhook. **Rate Limit: 30 Requests/Minute** pro IP (Bruteforce-Schutz).

**Hinweis:** Der `webhook_key` muss in der `pipeline.json` der Pipeline konfiguriert sein.

**Request Body (optional):** Bei `Content-Type: application/json` kann ein JSON-Body mit denselben Feldern wie bei `POST /api/pipelines/{name}/run` übergeben werden:

- `env_vars` (optional): Dictionary mit Environment-Variablen/Secrets für den Run
- `parameters` (optional): Dictionary mit Pipeline-Parametern

**Limits:** Max. 50 Einträge pro `env_vars` und `parameters`, je Wert max. 16 KB.

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "pipeline_name": "pipeline_a",
  "status": "RUNNING",
  "started_at": "2024-01-15T10:30:00",
  "log_file": "logs/550e8400-e29b-41d4-a716-446655440000.log"
}
```

**Fehler:**
- `400`: Ungültiger Request-Body (z. B. ungültiges JSON oder Verletzung der Limits für env_vars/parameters)
- `404`: Pipeline nicht gefunden, deaktiviert oder Webhooks deaktiviert
- `401`: Ungültiger Webhook-Schlüssel
- `429`: Concurrency-Limit erreicht

**Beispiel (ohne Body):**
```bash
curl -X POST http://localhost:8000/api/webhooks/pipeline_a/my-secret-key
```

**Beispiel (mit env_vars und parameters):**
```bash
curl -X POST http://localhost:8000/api/webhooks/pipeline_a/my-secret-key \
  -H "Content-Type: application/json" \
  -d '{"env_vars":{"API_KEY":"secret-value","LOG_LEVEL":"DEBUG"},"parameters":{"input_file":"data.csv"}}'
```

---

## Users (Nutzerverwaltung)

Alle Endpoints erfordern Authentifizierung. `GET /api/users`, Invites, Approve, Reject, Block, Unblock, Delete und Invite erfordern **Admin**.

### `GET /api/users`

Listet alle Nutzer (inkl. `status`, `github_id`, `google_id`). Keine Filterung; Frontend gruppiert in „Aktive Nutzer“ (`status=active`) und „Beitrittsanfragen“ (`status=pending`).

**Response:**
```json
[
  {
    "id": "uuid",
    "username": "max",
    "email": "max@example.com",
    "role": "READONLY",
    "blocked": false,
    "created_at": "2024-01-15T10:00:00",
    "github_id": "123",
    "google_id": "456",
    "status": "active"
  }
]
```

### `GET /api/users/{user_id}`

Einzelnen Nutzer abrufen.

### `PUT /api/users/{user_id}`

Nutzer aktualisieren. Body: `{ "role": "READONLY|WRITE|ADMIN", "blocked": false }`. E-Mail kommt von GitHub/Google und wird nicht per API geändert.

### `POST /api/users/{user_id}/approve`

**Beitrittsanfrage freigeben.** Nur wenn `status=pending`. Setzt `status=active`, `blocked=false`, `role` aus Body (Default: `READONLY`). Optional: E-Mail an Nutzer bei Freigabe (wenn `EMAIL_ENABLED` und `user.email`).

**Request Body (optional):**
```json
{ "role": "READONLY" }
```
`role`: `READONLY`, `WRITE` oder `ADMIN`. Fehlt der Body, wird `READONLY` verwendet.

**Fehler:** `400` wenn Nutzer nicht `pending` ist.

### `POST /api/users/{user_id}/reject`

**Beitrittsanfrage ablehnen.** Nur wenn `status=pending`. Setzt `status=rejected`, `blocked=true`.

**Fehler:** `400` wenn Nutzer nicht `pending` ist.

### `POST /api/users/{user_id}/block`

Nutzer blockieren. Alle Sessions werden gelöscht.

### `POST /api/users/{user_id}/unblock`

Nutzer entblockieren.

### `DELETE /api/users/{user_id}`

Nutzer löschen. Nicht erlaubt, sich selbst zu löschen.

### `GET /api/users/invites`

Listet alle Einladungen (Admin).

### `POST /api/users/invite`

Erstellt eine Einladung. Body: `{ "email": "...", "role": "READONLY|WRITE|ADMIN", "expires_hours": 168 }`. Response: `{ "link": "...", "expires_at": "..." }`.

### `DELETE /api/users/invites/{invitation_id}`

Einladung widerrufen (Admin).

---

## Authentifizierung

### `GET /api/auth/github/authorize`

Leitet zur GitHub OAuth-Seite weiter. Nach Autorisierung: Redirect zu `{FRONTEND_URL}/auth/callback#token=...`.

- **Query (optional):** `state` – z.B. Invitation-Token für Einladungs-Flow.

### `GET /api/auth/github/callback`

GitHub OAuth Callback (vom Browser aufgerufen). Erstellt Session und leitet zu `{FRONTEND_URL}/auth/callback#token=...` weiter. Bei **Link-Flow:** Redirect zu `{FRONTEND_URL}/settings?linked=github`. Bei **Beitrittsanfrage (anklopfen_only):** **kein** Token, **keine** Session; Redirect zu `{FRONTEND_URL}/request-sent` (pending) oder `{FRONTEND_URL}/request-rejected` (rejected/blocked).

### `GET /api/auth/google/authorize`

Leitet zur Google OAuth-Seite weiter. `state` optional (Invitation-Token oder CSRF).

### `GET /api/auth/google/callback`

Google OAuth Callback. Verhalten wie GitHub-Callback; bei Link-Flow: `{FRONTEND_URL}/settings?linked=google`; bei anklopfen_only: `{FRONTEND_URL}/request-sent` oder `{FRONTEND_URL}/request-rejected` ohne Session.

### `GET /api/auth/link/google`

Startet Google-OAuth zum **Verknüpfen** des Google-Kontos mit dem eingeloggten User. Erfordert Authentifizierung. Redirect zu `{FRONTEND_URL}/settings?linked=google` nach Erfolg.

### `GET /api/auth/link/github`

Startet GitHub-OAuth zum **Verknüpfen** des GitHub-Kontos. Erfordert Authentifizierung. Redirect zu `{FRONTEND_URL}/settings?linked=github` nach Erfolg.

### `POST /api/auth/logout`

Meldet einen Benutzer ab.

**Response:**
```json
{
  "message": "Erfolgreich abgemeldet"
}
```

### `GET /api/auth/me`

Gibt Informationen über den aktuellen Benutzer zurück (u.a. für Verknüpfte-Konten-UI).

**Response:**
```json
{
  "username": "dein-username",
  "id": "uuid",
  "email": "user@example.com",
  "has_github": true,
  "has_google": false,
  "avatar_url": "https://...",
  "created_at": "2024-01-18T12:00:00",
  "role": "admin"
}
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| OAuth Authorize (GitHub, Google, etc.) | 20/min |
| OAuth Callbacks | 60/min |
| Token Refresh | 30/min |
| Logout | 60/min |
| Webhooks | 30/min |
| Allgemein | 100/min |

Die Client-IP wird für das Rate Limiting verwendet. Hinter einem Reverse-Proxy muss `PROXY_HEADERS_TRUSTED=true` gesetzt werden, damit `X-Forwarded-For` berücksichtigt wird (siehe [Konfiguration](/docs/deployment/CONFIGURATION)).

---

## Status-Codes

- `200 OK`: Erfolgreiche Anfrage
- `201 Created`: Ressource erfolgreich erstellt
- `204 No Content`: Erfolgreiche Anfrage ohne Response-Body
- `400 Bad Request`: Ungültige Anfrage
- `401 Unauthorized`: Authentifizierung erforderlich
- `404 Not Found`: Ressource nicht gefunden
- `409 Conflict`: Ressource existiert bereits
- `429 Too Many Requests`: Rate-Limit oder Concurrency-Limit erreicht
- `500 Internal Server Error`: Server-Fehler
- `503 Service Unavailable`: Service nicht verfügbar (z.B. Scheduler)

---

## Fehlerbehandlung

Alle Fehler werden im folgenden Format zurückgegeben:

```json
{
  "detail": "Fehlermeldung"
}
```

Beispiel:
```json
{
  "detail": "Pipeline nicht gefunden: pipeline_x"
}
```

## Siehe auch

- [OAuth (GitHub & Google)](/docs/oauth/readme) – Login, Token
- [Konfiguration](/docs/deployment/CONFIGURATION) – `JWT_*`, `ENCRYPTION_KEY`
- [Schnellstart](/docs/schnellstart) – Erste Schritte
