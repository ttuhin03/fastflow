---
sidebar_position: 1
---

# ⚙️ Configuration

Fast-Flow is configured primarily via environment variables in a `.env` file. This file should live in the project root directory (based on `.env.example`).

## Global Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Sets the mode (`development` or `production`). In `production`, insecure default values (e.g. `JWT_SECRET_KEY`) are blocked. |

## Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | *Empty* (SQLite) | Database connection string. If empty, SQLite (`./data/fastflow.db`) is used. For PostgreSQL: `postgresql://user:password@host:5432/dbname`. |

## Directories

| Variable | Default | Description |
|----------|---------|-------------|
| `PIPELINES_DIR` | `./pipelines` | Path to the Git repository containing pipeline scripts. |
| `LOGS_DIR` | `./logs` | Path for persistent log files. |
| `DATA_DIR` | `./data` | Path for SQLite DB and other data. |
| `UV_CACHE_DIR` | `./data/uv_cache` | Path for the global `uv` cache (shared between containers). |
| `UV_PYTHON_INSTALL_DIR` | `{DATA_DIR}/uv_python` | Directory for `uv python install` (Python versions for workers). Must be persistent. |
| `UV_PYTHON_INSTALL_HOST_DIR` | *Empty* | Host path for worker volume mounts (optional; otherwise derived from orchestrator volumes). |
| `DEFAULT_PYTHON_VERSION` | `3.11` | Default Python version when `python_version` is missing in pipeline.json. The Python version can be configured freely per pipeline (e.g. 3.10, 3.11, 3.12). |

## Docker & Executor

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_BASE_IMAGE` | `ghcr.io/astral-sh/uv:python3.11-bookworm-slim` | Base image for pipeline containers (must include `uv`). For a minimal setup with uv only: `ghcr.io/astral-sh/uv:bookworm-slim` or a custom image from `Dockerfile.worker` (then preheating must provide Python). |
| `MAX_CONCURRENT_RUNS` | `10` | Maximum number of pipelines running concurrently. |
| `CONTAINER_TIMEOUT` | *Empty* (no timeout) | Global timeout for pipeline runs in seconds. |
| `RETRY_ATTEMPTS` | `0` | Default number of retry attempts on failure. |

## Git Sync

Repository URL and authentication (PAT or deploy key) can be set **either** via environment variables **or** in the UI under **Settings → Git Sync → Repository**. Environment variables take precedence. **Either** **HTTPS + Personal Access Token (PAT)** **or** **SSH + Deploy Key** is used—the method is determined by the URL.

| Variable | Default | Description |
|----------|---------|-------------|
| `GIT_REPO_URL` | *Empty* | URL of the pipeline repository: HTTPS (e.g. `https://github.com/org/repo.git`) or SSH (e.g. `git@github.com:org/repo.git`). |
| `GIT_SYNC_TOKEN` | *Empty* | Optional: Personal Access Token (PAT) for private repos with an **HTTPS** URL. |
| `GIT_SYNC_DEPLOY_KEY` | *Empty* | Optional: Content of the private SSH deploy key for an **SSH** URL. Sensitive—set as a secret. |
| `GIT_BRANCH` | `main` | The Git branch to synchronize. |
| `AUTO_SYNC_ENABLED` | `false` | Whether pipelines should be synchronized automatically. |
| `AUTO_SYNC_INTERVAL` | *Empty* | Interval in seconds for automatic sync. |
| `UV_PRE_HEAT` | `true` | Whether dependencies should be preinstalled ("preheated") automatically during sync. |

**Deploy Key (SSH):** For an SSH URL (e.g. `git@github.com:org/repo.git`), a private SSH key must be configured. Create the deploy key in the repository under *Settings → Deploy keys*; enter the **private** key here or in the Sync UI. **Semi-automatic:** In the Sync UI, a deploy key can be generated on the server for SSH—only add the displayed public key on GitHub (Deploy keys). Only one method (PAT or deploy key) is ever used—depending on the chosen URL. When switching methods (e.g. from HTTPS to SSH), clear the pipelines directory in the UI and run sync again.

## Logs & Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_RETENTION_RUNS` | *Empty* (unlimited) | Maximum number of runs kept per pipeline. Older runs are deleted. |
| `LOG_RETENTION_DAYS` | *Empty* (unlimited) | Logs older than X days are deleted. |
| `LOG_MAX_SIZE_MB` | *Empty* (unlimited) | Maximum size of a log file in MB. |
| `LOG_STREAM_RATE_LIMIT`| `100` | Maximum number of log lines per second for live streaming (SSE). |

## Log Backup (S3/MinIO, optional)

Pipeline logs are backed up to S3/MinIO before local deletion (cleanup). Details: [S3 Log Backup](S3_LOG_BACKUP.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BACKUP_ENABLED` | `false` | Enables S3 backup before local deletion. |
| `S3_ENDPOINT_URL` | *Empty* | S3 endpoint (e.g. `http://minio:9000`). |
| `S3_BUCKET` | *Empty* | Bucket name. |
| `S3_ACCESS_KEY` | *Empty* | Access key. |
| `S3_SECRET_ACCESS_KEY` | *Empty* | Secret access key. |
| `S3_REGION` | `us-east-1` | Region (often irrelevant for MinIO). |
| `S3_PREFIX` | `pipeline-logs` | Prefix for object keys. |
| `S3_USE_PATH_STYLE` | `true` | Path-style URLs (typical for MinIO). |

Alternatively (or additionally), S3 backup parameters can be managed in the **Settings UI** under **Pipeline & Runs**: values are stored in `orchestrator_settings` (access/secret encrypted). Environment variables still apply; on startup, saved DB values are applied to the running configuration. A **connection test** is available via button or optionally **after saving** (`POST /api/settings/s3/test`, admin only).

## Security & Authentication

> [!IMPORTANT]
> These values are CRITICAL for security, especially with Docker socket access.

| Variable | Default | Description | Production |
|----------|---------|-------------|------------|
| `ENCRYPTION_KEY` | *Must be set* | Fernet key for encrypting secrets in the DB. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Required** |
| `JWT_SECRET_KEY` | `change-me-in-production` | Secret key for signing and verifying JWT tokens. Must be long and random (min. 32 characters). In production: use your own value; `change-me-in-production` is blocked. | **Required** |
| `JWT_ALGORITHM` | `HS256` | Algorithm for JWT signature (typically HS256). | HS256 |
| `JWT_ACCESS_TOKEN_MINUTES` | `15` | Access token validity in minutes (JWT lifetime, `exp` claim). Shorter lifetime reduces risk from compromised tokens. | 15 |
| `JWT_EXPIRATION_HOURS` | `24` | Session validity in the DB in hours. After expiry, "Session expired" appears; re-login required. | 24 |
| `GITHUB_CLIENT_ID` | *Empty* | OAuth App Client ID (GitHub). | **Required** (at least one provider) |
| `GITHUB_CLIENT_SECRET` | *Empty* | OAuth App Client Secret (GitHub). | **Required** (at least one provider) |
| `GOOGLE_CLIENT_ID` | *Empty* | OAuth 2.0 Client ID (Google). Callback: `{BASE_URL}/api/auth/google/callback`. | Optional |
| `GOOGLE_CLIENT_SECRET` | *Empty* | OAuth 2.0 Client Secret (Google). | Optional |
| `MICROSOFT_CLIENT_ID` | *Empty* | OAuth Client ID (Microsoft Entra ID). Callback: `{BASE_URL}/api/auth/microsoft/callback`. | Optional |
| `MICROSOFT_CLIENT_SECRET` | *Empty* | OAuth Client Secret (Microsoft Entra ID). | Optional |
| `MICROSOFT_TENANT_ID` | `common` | Tenant scoping for Microsoft OAuth (`common`, tenant ID, `organizations`, `consumers`). | Optional |
| `CUSTOM_OAUTH_CLIENT_ID` | *Empty* | OAuth Client ID for custom provider (e.g. Keycloak/Auth0). | Optional |
| `CUSTOM_OAUTH_CLIENT_SECRET` | *Empty* | OAuth Client Secret for custom provider. | Optional |
| `CUSTOM_OAUTH_AUTHORIZE_URL` | *Empty* | Authorize endpoint of the custom provider. | Optional |
| `CUSTOM_OAUTH_TOKEN_URL` | *Empty* | Token endpoint of the custom provider. | Optional |
| `CUSTOM_OAUTH_USERINFO_URL` | *Empty* | UserInfo endpoint of the custom provider. | Optional |
| `CUSTOM_OAUTH_SCOPES` | `openid email profile` | Scopes for custom OAuth. | Optional |
| `CUSTOM_OAUTH_CLAIM_ID` | `sub` | Claim for unique user ID with custom provider. | Optional |
| `CUSTOM_OAUTH_CLAIM_EMAIL` | `email` | Claim for email with custom provider. | Optional |
| `CUSTOM_OAUTH_CLAIM_NAME` | `name` | Claim for display name with custom provider. | Optional |
| `CUSTOM_OAUTH_NAME` | `Custom` | Display name of the custom provider on the login page. | Optional |
| `CUSTOM_OAUTH_ICON_URL` | *Empty* | Optional icon URL for the custom login button. | Optional |
| `SKIP_OAUTH_VERIFICATION` | *Empty* | `1`/`true`: skip HTTP verification of OAuth credentials on startup (e.g. CI/tests). The check for "at least one provider fully configured" remains active. | Optional |
| `INITIAL_ADMIN_EMAIL` | *Empty* | Email of the first admin (access without invitation, via supported OAuth provider). | **Recommended** |
| `FRONTEND_URL` / `BASE_URL` | see [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme) | For OAuth callback and invitation links. | Adjust |
| `PROXY_HEADERS_TRUSTED` | `false` | When `true`: `X-Forwarded-For` is used for rate limiting. **Only** enable when the app runs behind a trusted reverse proxy (Nginx, Traefik). When `false`, `request.client.host` is used (protection against spoofing). | With proxy: `true` |

**OAuth on startup:** At least one OAuth provider (GitHub, Google, Microsoft, or Custom) must be fully configured (each with `CLIENT_ID` and `CLIENT_SECRET`; for Custom additionally Authorize/Token/UserInfo URLs). Without this, the app will not start. On startup, configured credentials are verified via a request to the respective provider; with invalid values or redirect URI mismatch, the app will also not start.

## Notifications (Optional)

| Variable | Description |
|----------|-------------|
| `EMAIL_ENABLED` | `true` or `false` |
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | SMTP port (e.g. 587) |
| `EMAIL_RECIPIENTS` | Comma-separated list of recipients |
| `TEAMS_ENABLED` | `true` or `false` |
| `TEAMS_WEBHOOK_URL`| Webhook URL for Microsoft Teams channel |

These settings are also used for **notifications from the automatic security scan (dependency audit)**: when pip-audit runs daily and finds vulnerabilities (CVEs), email and/or Teams notifications are sent as configured above. Activation and schedule (cron) are set in the **UI under Settings → Dependencies – automatic security scan** (admins only). Details: [Dependencies and Security Scan](/docs/pipelines/abhaengigkeiten-sicherheit).
