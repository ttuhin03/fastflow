---
slug: api
---

# API Documentation

This documentation describes all available REST API endpoints of the Fast-Flow orchestrator.

## Base URL

All API endpoints are available under `/api`. The full base URL is:
```
http://localhost:8000/api
```

## Authentication

Most endpoints require authentication. Use a Bearer token in the Authorization header:

```
Authorization: Bearer <token>
```

Tokens are obtained via OAuth providers (`GET /api/auth/{provider}/authorize`), e.g. GitHub, Google, Microsoft, or Custom OAuth; after authorization redirect to `/auth/callback#token=...`.

## Endpoints

### Health Check

#### `GET /health`, `GET /healthz`, or `GET /api/health`

Checks application status.

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

Returns a list of all available pipelines.

**Query parameters:**
- `tags` (optional): Comma-separated tags; only pipelines that have **at least one** of these tags in their `pipeline.json` (`metadata.tags`) are returned. Example: `?tags=production,experiment`

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
      "description": "Processes incoming data daily",
      "tags": ["data-processing", "daily"]
    }
  }
]
```

### `POST /api/pipelines/{name}/run`

Starts a pipeline manually.

**Request body:**
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

**Limits:** Max. 50 entries per `env_vars` and `parameters`, max. 16 KB per value.

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

**Errors:**
- `404`: Pipeline not found or disabled
- `429`: Concurrency limit reached

### `GET /api/pipelines/{name}/runs`

Returns the run history of a pipeline.

**Query parameters:**
- `limit` (optional, default: 100): Maximum number of runs

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

Returns pipeline statistics.

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

Resets pipeline statistics.

**Response:**
```json
{
  "message": "Statistics for pipeline 'pipeline_a' have been reset"
}
```

### `GET /api/pipelines/{name}/daily-stats`

Returns daily pipeline statistics.

**Query parameters:**
- `days` (optional, default: 365): Number of days back
- `start_date` (optional): Start date (ISO format: YYYY-MM-DD)
- `end_date` (optional): End date (ISO format: YYYY-MM-DD)

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

Returns daily statistics for all pipelines combined.

**Query parameters:** (same as above)

---

## Runs

### `GET /api/runs`

Returns all runs (with filtering and pagination).

**Query parameters:**
- `pipeline_name` (optional): Filter by pipeline name
- `status_filter` (optional): Filter by status (PENDING, RUNNING, SUCCESS, FAILED, etc.)
- `start_date` (optional): Start date for filtering (ISO format)
- `end_date` (optional): End date for filtering (ISO format)
- `limit` (optional, default: 50): Number of runs per page
- `offset` (optional, default: 0): Offset for pagination

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

Returns details of a run.

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

Cancels a running run.

**Response:**
```json
{
  "message": "Run 550e8400-e29b-41d4-a716-446655440000 was cancelled successfully"
}
```

**Errors:**
- `400`: Run has already finished
- `404`: Run not found

### `POST /api/runs/{run_id}/retry`

Starts a new run with the same parameters and env variables as the specified run. Only allowed for finished runs (SUCCESS, FAILED, INTERRUPTED, WARNING). The new run is started with `triggered_by="manual"`.

**Response:**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "pipeline_name": "data_sync",
  "status": "PENDING",
  "started_at": "2025-02-27T12:00:00.000000+00:00",
  "log_file": "./logs/data_sync_2025-02-27T12:00:00.000000.log"
}
```

**Errors:**
- `400`: Run is not finished (PENDING/RUNNING only)
- `404`: Run not found or pipeline does not exist
- `429`: Concurrency limit reached
- `500`: Error starting run

### `GET /api/runs/{run_id}/health`

Returns container health status for a run.

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

Returns logs from file (for completed runs).

**Query parameters:**
- `tail` (optional): Number of last lines

**Response:** Plain Text (Log-Inhalt)

### `GET /api/runs/{run_id}/logs/stream`

Server-Sent Events for live logs (for running runs).

**Response:** `text/event-stream`

**Format:**
```
data: {"line": "Pipeline started\n"}

data: {"line": "Processing data...\n"}

```

---

## Metrics

### `GET /api/runs/{run_id}/metrics`

Returns metrics from file (for completed runs).

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

Server-Sent Events for live metrics (for running runs).

**Response:** `text/event-stream`

**Format:**
```
data: {"timestamp": "2024-01-15T10:30:00", "cpu_percent": 45.2, "ram_mb": 128.5, "ram_limit_mb": 512}

```

---

## Scheduler

### `GET /api/scheduler/jobs`

Returns all scheduled jobs.

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

Returns a job by ID.

### `POST /api/scheduler/jobs`

Creates a new scheduled job.

**Request body:**
```json
{
  "pipeline_name": "pipeline_a",
  "trigger_type": "CRON",
  "trigger_value": "0 0 * * *",
  "enabled": true
}
```

**Trigger-Typen:**
- `CRON`: Cron expression (e.g. `"0 0 * * *"` for daily at midnight)
- `INTERVAL`: Interval in seconds (e.g. `"3600"` for hourly)

**Errors:**
- `404`: Pipeline not found
- `400`: Invalid trigger expression
- `503`: Scheduler not available

### `PUT /api/scheduler/jobs/{job_id}`

Updates an existing job.

**Request body:**
```json
{
  "pipeline_name": "pipeline_b",
  "trigger_type": "INTERVAL",
  "trigger_value": "1800",
  "enabled": false
}
```

### `DELETE /api/scheduler/jobs/{job_id}`

Deletes a job.

**Response:** `204 No Content`

### `GET /api/scheduler/jobs/{job_id}/runs`

Returns run history for a job.

**Query parameters:**
- `limit` (optional, default: 50): Maximum number of runs

---

## Secrets

### `GET /api/secrets`

Returns all secrets.

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

**Note:** Secrets are stored encrypted but returned decrypted. Parameters (`is_parameter: true`) are not encrypted.

### `POST /api/secrets/encrypt-for-pipeline`

Encrypts plaintext with the server `ENCRYPTION_KEY` for manual entry in `pipeline.json` under `encrypted_env`. **Max. 64 KB** per value.

**Request body:** `{ "value": "plaintext" }`

### `POST /api/secrets`

Creates a new secret.

**Request body:**
```json
{
  "key": "API_KEY",
  "value": "secret-value",
  "is_parameter": false
}
```

**Errors:**
- `409`: Secret already exists (use PUT to update)

### `PUT /api/secrets/{key}`

Updates an existing secret.

**Request body:**
```json
{
  "value": "new-secret-value",
  "is_parameter": false
}
```

### `DELETE /api/secrets/{key}`

Deletes a secret.

**Response:**
```json
{
  "message": "Secret 'API_KEY' deleted successfully.",
  "key": "API_KEY"
}
```

---

## Sync (Git)

### `POST /api/sync`

Runs Git pull (with UV pre-heating).

**Request body:**
```json
{
  "branch": "main"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Git sync successful",
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

Returns Git status.

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

Returns current sync settings.

**Response:**
```json
{
  "auto_sync_enabled": true,
  "auto_sync_interval": 3600
}
```

### `PUT /api/sync/settings`

Updates sync settings.

**Request body:**
```json
{
  "auto_sync_enabled": true,
  "auto_sync_interval": 1800
}
```

**Note:** Settings are updated only for the running instance. For persistent changes, edit the `.env` file.

### `GET /api/sync/logs`

Returns sync logs.

**Query parameters:**
- `limit` (optional, default: 100): Maximum number of log entries

### GitHub Apps Configuration

#### `GET /api/sync/github-config`

Returns current GitHub Apps configuration.

**Response:**
```json
{
  "app_id": "123456",
  "installation_id": "789012",
  "configured": true,
  "has_private_key": true
}
```

**Note:** Private key is NOT returned for security reasons.

#### `POST /api/sync/github-config`

Saves GitHub Apps configuration.

**Request body:**
```json
{
  "app_id": "123456",
  "installation_id": "789012",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n..."
}
```

#### `POST /api/sync/github-config/test`

Tests GitHub Apps configuration.

**Response:**
```json
{
  "success": true,
  "message": "Token generated successfully"
}
```

#### `DELETE /api/sync/github-config`

Deletes GitHub Apps configuration.

### GitHub App Manifest Flow

**Requires admin rights** (authorize and exchange).

#### `GET /api/sync/github-manifest/authorize`

Generates HTML form for GitHub App Manifest flow. Requires admin login.

#### `GET /api/sync/github-manifest/callback`

Callback endpoint for GitHub App Manifest flow (called by GitHub).

#### `POST /api/sync/github-manifest/exchange`

Exchanges manifest code for GitHub App credentials. Requires admin login.

**Request body:**
```json
{
  "code": "temporary-code",
  "state": "state-token"
}
```

---

## Settings

### `GET /api/settings`

Returns current system settings (incl. persistent values from `orchestrator_settings`, e.g. log retention, notifications, S3 backup).

**Response (excerpt):**
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
  "teams_webhook_url": null,
  "s3_backup_enabled": false,
  "s3_endpoint_url": null,
  "s3_bucket": null,
  "s3_region": "us-east-1",
  "s3_prefix": "pipeline-logs",
  "s3_use_path_style": true,
  "s3_access_key_configured": false,
  "s3_secret_access_key_configured": false,
  "s3_last_test_at": null,
  "s3_last_test_status": null,
  "s3_last_test_error": null,
  "s3_test_on_save": false
}
```

### `PUT /api/settings`

Updates system settings and saves them in the database (`orchestrator_settings`). Running configuration is applied immediately (no restart needed). S3 access/secret can be sent as plaintext (stored encrypted); stored keys can be removed with `s3_clear_access_key` / `s3_clear_secret_access_key`.

### `POST /api/settings/s3/test`

Tests current S3 configuration (e.g. `HeadBucket`). **Admin only.** Stores time and status of last test in the database.

**Response:**
```json
{
  "success": true,
  "message": "S3 connection tested successfully.",
  "tested_at": "2026-04-07T12:00:00+00:00"
}
```

### `GET /api/settings/storage`

Returns storage statistics.

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

Sends a test email.

**Response:**
```json
{
  "status": "success",
  "message": "Test email sent successfully to user@example.com"
}
```

### `POST /api/settings/test-teams`

Sends a test Teams message.

**Response:**
```json
{
  "status": "success",
  "message": "Test Teams message sent successfully"
}
```

### `POST /api/settings/cleanup/force`

Runs a manual force flush (cleanup).

**Response:**
```json
{
  "status": "success",
  "message": "Cleanup completed successfully",
  "summary": [
    "10 runs deleted from database",
    "15 log files deleted",
    "5 Docker containers deleted"
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

Returns system metrics.

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

Triggers a pipeline via webhook. **Rate limit: 30 requests/minute** per IP (brute-force protection).

**Note:** The `webhook_key` must be configured in the pipeline's `pipeline.json`.

**Request body (optional):** With `Content-Type: application/json`, a JSON body with the same fields as `POST /api/pipelines/{name}/run` can be passed:

- `env_vars` (optional): Dictionary with environment variables/secrets for the run
- `parameters` (optional): Dictionary with pipeline parameters

**Limits:** Max. 50 entries per `env_vars` and `parameters`, max. 16 KB per value.

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

**Errors:**
- `400`: Invalid request body (e.g. invalid JSON or violation of env_vars/parameters limits)
- `404`: Pipeline not found, disabled, or webhooks disabled
- `401`: Invalid webhook key
- `429`: Concurrency limit reached

**Example (without body):**
```bash
curl -X POST http://localhost:8000/api/webhooks/pipeline_a/my-secret-key
```

**Example (with env_vars and parameters):**
```bash
curl -X POST http://localhost:8000/api/webhooks/pipeline_a/my-secret-key \
  -H "Content-Type: application/json" \
  -d '{"env_vars":{"API_KEY":"secret-value","LOG_LEVEL":"DEBUG"},"parameters":{"input_file":"data.csv"}}'
```

---

## Users (user management)

All endpoints require authentication. `GET /api/users`, invites, approve, reject, block, unblock, delete, and invite require **Admin**.

### `GET /api/users`

Lists all users (incl. `status`, `github_id`, `google_id`, `microsoft_id`, `custom_oauth_id`). No filtering; frontend groups into "Active users" (`status=active`) and "Join requests" (`status=pending`).

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

Get a single user.

### `PUT /api/users/{user_id}`

Update user. Body: `{ "role": "READONLY|WRITE|ADMIN", "blocked": false }`. Email comes from OAuth provider and is not changed via API.

### `POST /api/users/{user_id}/approve`

**Approve join request.** Only when `status=pending`. Sets `status=active`, `blocked=false`, `role` from body (default: `READONLY`). Optional: email to user on approval (when `EMAIL_ENABLED` and `user.email`).

**Request body (optional):**
```json
{ "role": "READONLY" }
```
`role`: `READONLY`, `WRITE`, or `ADMIN`. If body is omitted, `READONLY` is used.

**Error:** `400` if user is not `pending`.

### `POST /api/users/{user_id}/reject`

**Reject join request.** Only when `status=pending`. Sets `status=rejected`, `blocked=true`.

**Error:** `400` if user is not `pending`.

### `POST /api/users/{user_id}/block`

Block user. All sessions are deleted.

### `POST /api/users/{user_id}/unblock`

Unblock user.

### `DELETE /api/users/{user_id}`

Delete user. Not allowed to delete yourself.

### `GET /api/users/invites`

Lists all invitations (admin).

### `POST /api/users/invite`

Creates an invitation. Body: `{ "email": "...", "role": "READONLY|WRITE|ADMIN", "expires_hours": 168 }`. Response: `{ "link": "...", "expires_at": "..." }`.

### `DELETE /api/users/invites/{invitation_id}`

Revoke invitation (admin).

---

## Authentication

### `GET /api/auth/providers`

Returns enabled login providers for the login page.

**Response:**
```json
{
  "providers": ["github", "google", "microsoft", "custom"]
}
```

### `GET /api/auth/github/authorize`

Redirects to GitHub OAuth page. After authorization: redirect to `{FRONTEND_URL}/auth/callback#token=...`.

- **Query (optional):** `state` – e.g. invitation token for invitation flow.

### `GET /api/auth/github/callback`

GitHub OAuth callback (called from browser). Creates session and redirects to `{FRONTEND_URL}/auth/callback#token=...`. On **link flow:** redirect to `{FRONTEND_URL}/settings?linked=github`. On **join request (knock only):** **no** token, **no** session; redirect to `{FRONTEND_URL}/request-sent` (pending) or `{FRONTEND_URL}/request-rejected` (rejected/blocked).

### `GET /api/auth/google/authorize`

Redirects to Google OAuth page. `state` optional (invitation token or CSRF).

### `GET /api/auth/google/callback`

Google OAuth callback. Same behavior as GitHub callback; on link flow: `{FRONTEND_URL}/settings?linked=google`; on knock only: `{FRONTEND_URL}/request-sent` or `{FRONTEND_URL}/request-rejected` without session.

### `GET /api/auth/microsoft/authorize`

Redirects to Microsoft OAuth page. `state` optional (invitation token or CSRF).

### `GET /api/auth/microsoft/callback`

Microsoft OAuth callback. Same behavior as GitHub/Google callback; on link flow: `{FRONTEND_URL}/settings?linked=microsoft`; on knock only: `{FRONTEND_URL}/request-sent` or `{FRONTEND_URL}/request-rejected` without session.

### `GET /api/auth/custom/authorize`

Redirects to configured Custom OAuth provider. `state` optional (invitation token or CSRF).

### `GET /api/auth/custom/callback`

Custom OAuth callback. Same behavior as other providers; on link flow: `{FRONTEND_URL}/settings?linked=custom`; on knock only: `{FRONTEND_URL}/request-sent` or `{FRONTEND_URL}/request-rejected` without session.

### `GET /api/auth/link/google`

Starts Google OAuth to **link** the Google account to the logged-in user. Requires authentication. Redirect to `{FRONTEND_URL}/settings?linked=google` on success.

### `GET /api/auth/link/github`

Starts GitHub OAuth to **link** the GitHub account. Requires authentication. Redirect to `{FRONTEND_URL}/settings?linked=github` on success.

### `GET /api/auth/link/microsoft`

Starts Microsoft OAuth to **link** the Microsoft account. Requires authentication. Redirect to `{FRONTEND_URL}/settings?linked=microsoft` on success.

### `GET /api/auth/link/custom`

Starts Custom OAuth to **link** the Custom provider account. Requires authentication. Redirect to `{FRONTEND_URL}/settings?linked=custom` on success.

### `POST /api/auth/logout`

Logs out a user.

**Response:**
```json
{
  "message": "Logged out successfully"
}
```

### `GET /api/auth/me`

Returns information about the current user (incl. for linked-accounts UI).

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
| General | 100/min |

Client IP is used for rate limiting. Behind a reverse proxy, set `PROXY_HEADERS_TRUSTED=true` so `X-Forwarded-For` is considered (see [Configuration](/docs/deployment/CONFIGURATION)).

---

## Status-Codes

- `200 OK`: Successful request
- `201 Created`: Resource created successfully
- `204 No Content`: Successful request without response body
- `400 Bad Request`: Invalid request
- `401 Unauthorized`: Authentication required
- `404 Not Found`: Resource not found
- `409 Conflict`: Resource already exists
- `429 Too Many Requests`: Rate limit or concurrency limit reached
- `500 Internal Server Error`: Server error
- `503 Service Unavailable`: Service unavailable (e.g. scheduler)

---

## Error handling

All errors are returned in the following format:

```json
{
  "detail": "Error message"
}
```

Example:
```json
{
  "detail": "Pipeline not found: pipeline_x"
}
```

## See also

- [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme) – login, token
- [Configuration](/docs/deployment/CONFIGURATION) – `JWT_*`, `ENCRYPTION_KEY`
- [Quick Start](/docs/schnellstart) – first steps
