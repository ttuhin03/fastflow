# Database Schema

Fast-Flow uses **SQLModel** (based on SQLAlchemy) as its ORM. **SQLite** is used by default, but **PostgreSQL** is fully supported.

## Tables (Models)

### 1. `Pipeline` (Metadata)

Stores static information about discovered pipelines.

| Column | Type | Description |
|--------|-----|--------------|
| `pipeline_name` | String (PK) | Unique pipeline name (matches directory name). |
| `has_requirements` | Boolean | Indicates whether a `requirements.txt` was found. |
| `last_cache_warmup` | DateTime | Timestamp of the last successful `uv pip compile`. |
| `total_runs` | Integer | Total number of runs. |
| `successful_runs` | Integer | Number of successful runs. |
| `failed_runs` | Integer | Number of failed runs. |
| `enabled` | Boolean | Whether the pipeline is enabled (from `pipeline.json`). |
| `metadata` | JSON | Additional metadata from `pipeline.json` (limits, description, tags). |
| `webhook_runs` | Integer | Number of runs triggered by webhooks. |

### 2. `PipelineRun` (History)

Stores each individual pipeline execution attempt.

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique run ID. |
| `pipeline_name` | String (FK) | Reference to `Pipeline`. |
| `status` | Enum | `PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `INTERRUPTED`, `WARNING`. |
| `started_at` | DateTime | Start time. |
| `finished_at` | DateTime | End time. |
| `exit_code` | Integer | Container exit code (0 = success). |
| `log_file` | String | Path to log file on the filesystem. |
| `metrics_file` | String | Path to metrics file on the filesystem. |
| `env_vars` | JSON | Set environment variables (masked in API responses). |
| `parameters` | JSON | Passed parameters. |
| `uv_version` | String | Version of `uv` used. |
| `setup_duration` | Float | Environment setup duration in seconds. |
| `triggered_by` | String | Run trigger (e.g. "manual", "scheduler", "webhook", "downstream"). |
| `run_config_id` | String | (Optional) Run configuration from `pipeline.json` `schedules` (e.g. `prod`). |
| `git_sha` / `git_branch` / `git_commit_message` | String | (Optional) Git HEAD of the pipeline repo at run start (reproducibility). |

### 3. `ScheduledJob` (Scheduler)

Stores scheduled executions for APScheduler via `SQLAlchemyJobStore`.

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique job ID. |
| `pipeline_name` | String (FK) | Pipeline to execute. |
| `trigger_type` | Enum | `CRON` or `INTERVAL`. |
| `trigger_value` | String | Cron string (e.g. `0 0 * * *`) or interval in seconds. |
| `enabled` | Boolean | Whether the job is active. |
| `start_date` / `end_date` | DateTime | (Optional) Validity period of the job. |
| `source` | String | Origin of the job (e.g. `pipeline_json`). |
| `run_config_id` | String | (Optional) Run configuration from `pipeline.json` `schedules`. |
| `created_at` | DateTime | Creation date. |

### 4. `Secret` (Configuration)

Stores sensitive data and parameters.

| Column | Type | Description |
|--------|-----|--------------|
| `key` | String (PK) | Secret/parameter name (e.g. `API_KEY`). |
| `value` | String | The value. **IMPORTANT**: Stored encrypted (Fernet). |
| `is_parameter` | Boolean | `true` = parameter (unencrypted/visible), `false` = secret (encrypted). |
| `created_at` | DateTime | Creation date. |
| `updated_at` | DateTime | Last modified date. |

### 5. `User` (Authentication)

Stores users. Login via OAuth (GitHub, Google, Microsoft, Custom) plus invitation flow.

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique user ID. |
| `username` | String | Username (unique, indexed). |
| `email` | String | (Optional) Email (from OAuth provider or manual). |
| `role` | Enum | `ADMIN`, `WRITE`, `READONLY`. |
| `blocked` | Boolean | Whether the user is blocked. |
| `github_id` | String | (Optional) GitHub OAuth ID (unique). |
| `google_id` | String | (Optional) Google OAuth ID (unique). |
| `avatar_url` | String | (Optional) Profile image URL from OAuth provider. |
| `microsoft_id` | String | (Optional) Microsoft OAuth ID (unique). |
| `custom_oauth_id` | String | (Optional) Custom OAuth ID (unique). |
| `status` | String | `active` (access), `pending` (join request), `rejected` (declined). Default: `active`. |
| `created_at` | DateTime | Creation date. |

### 6. `Invitation` (Invitations)

Token invitations for new users (redeemed via OAuth provider).

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique ID. |
| `recipient_email` | String | Recipient email. |
| `token` | String | One-time token (unique, in URL: `/invite?token=...`). |
| `is_used` | Boolean | Whether the invitation has already been redeemed. |
| `expires_at` | DateTime | Expiration time. |
| `role` | Enum | Role of the new user. |
| `created_at` | DateTime | Creation date. |

### 7. `Session` (Sessions)

Persistent sessions (JWT token in DB).

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique session ID. |
| `token` | String | JWT token (unique). |
| `user_id` | UUID (FK) | Reference to `users.id`. |
| `expires_at` | DateTime | Session expiration. |
| `created_at` | DateTime | Creation date. |

### 8. `PipelineDailyStat` (Calendar statistics)

Persistent daily counters per pipeline (survive log/run cleanup; used for the calendar heatmap).

| Column | Type | Description |
|--------|-----|--------------|
| `pipeline_name` | String (PK, FK) | Pipeline. |
| `day` | Date (PK) | Day. |
| `total_runs` / `successful_runs` / `failed_runs` | Integer | Daily counters. |

### 9. `RunCellLog` (Notebook cells)

Per-cell logs for notebook pipelines (`main.ipynb`).

| Column | Type | Description |
|--------|-----|--------------|
| `run_id` | UUID (PK, FK) | Reference to `PipelineRun`. |
| `cell_index` | Integer (PK) | Index of the code cell (0-based). |
| `status` | String | `RUNNING`, `SUCCESS`, `FAILED`, `RETRYING`. |
| `stdout` / `stderr` | Text | Cell output. |
| `outputs` | JSON | (Optional) Rich outputs (e.g. images). |

### 10. `DownstreamTrigger` (Pipeline chaining)

Triggers that start a downstream pipeline after an upstream pipeline finishes.

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique ID. |
| `upstream_pipeline` / `downstream_pipeline` | String | Pipeline names. |
| `on_success` / `on_failure` | Boolean | Trigger conditions. |
| `on_route` | String | (Optional) Route string (from `FASTFLOW_ROUTE_FILE`). |
| `run_config_id` | String | (Optional) Run configuration for the downstream run. |
| `enabled` | Boolean | Whether the trigger is active. |
| `created_at` | DateTime | Creation date. |

### 11. `SystemSettings` (Singleton)

System-wide UI/telemetry settings (single row, `id=1`): setup wizard status, telemetry/error reporting opt-in, dependency audit schedule, login branding, UI display options.

### 12. `OrchestratorSettings` (Singleton)

Persistent orchestrator settings (single row, `id=1`), applied to the running config at startup: log retention, concurrency, timeouts, Git sync repo config (token/deploy key encrypted), SMTP/Teams notifications, notification API, S3 backup (keys encrypted).

### 13. `NotificationApiKey`

API keys for the notification script API (`POST /api/notifications/send`).

| Column | Type | Description |
|--------|-----|--------------|
| `id` | Integer (PK) | Unique ID. |
| `key_hash` | String | Hash of the API key (the key itself is not stored). |
| `label` | String | (Optional) Label. |
| `created_at` | DateTime | Creation date. |

### 14. `AuditLogEntry` (Audit log)

Records administrative actions (who did what and when).

| Column | Type | Description |
|--------|-----|--------------|
| `id` | UUID (PK) | Unique ID. |
| `created_at` | DateTime | Timestamp (indexed). |
| `user_id` / `username` | UUID / String | Acting user. |
| `action` | String | Action (e.g. `run_cancel`, `sync_repo_config_delete`). |
| `resource_type` / `resource_id` | String | Affected resource. |
| `details` | JSON | (Optional) Additional details. |
| `ip_address` | String | (Optional) Client IP. |

---

## Relationships

- A **Pipeline** can have many **PipelineRuns** (1:n).
- A **Pipeline** can have many **ScheduledJobs** (1:n).
- **Secrets** are globally available and injected into runs as needed.
- A **User** can have many **Sessions** (1:n).
- **Invitation** stands alone; after redemption a new **User** is created with the assigned role.

## Notes

- All timestamps are stored as **UTC**.
- SQLite uses **WAL mode** (Write-Ahead Logging) for better concurrency.
- JSON fields are stored as TEXT in SQLite and as JSONB in PostgreSQL.

## See also

- [Migrations](/docs/database/MIGRATIONS) – schema changes, Alembic
- [Configuration](/docs/deployment/CONFIGURATION) – `DATABASE_URL`
