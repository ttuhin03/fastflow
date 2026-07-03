---
sidebar_position: 3
---

import GenerateEncryptionKey from '@site/src/components/GenerateEncryptionKey';
import GenerateJwtSecret from '@site/src/components/GenerateJwtSecret';

# Setup Guide

This guide walks you step by step through setting up Fast-Flow – including the most important environment variables and what they do.

## Who is this guide for?

- You want to get Fast-Flow running for the first time.
- You want to understand **why** certain settings are necessary – not just **that** they must be set.
- You are planning a production deployment and need a checklist.

For the complete reference of all variables, see [Configuration](/docs/deployment/CONFIGURATION).

---

## Overview: What you need

| Prerequisite | Purpose |
|---------------|--------|
| **Docker & Docker Compose** | To start the orchestrator and pipeline containers. |
| **Python 3.11+** | For local development only (e.g. `uvicorn`, `pip`, key generation). |
| **Git** | If you sync pipelines from a repository (optional, otherwise local directory). |

---

## 1. Prepare the project

### 1.1 Clone the repository (if not done yet)

```bash
git clone https://github.com/ttuhin03/fastflow.git
cd fastflow
```

### 1.2 Create `.env` from the template

Fast-Flow reads configuration from a `.env` file in the project root. The file is **not** committed to Git (listed in `.gitignore`).

```bash
cp .env.example .env
```

Open `.env` in an editor – most lines are commented out (`#`). You will only need to activate and set a portion of them.

---

## 2. Required variables: Security & startup

Without these values, the application will not start or will block startup in production.

### 2.1 `ENCRYPTION_KEY` (must be set)

**What it is:** A symmetric key (Fernet) for encrypting **secrets** in the database (API keys, passwords you enter in the UI).

**Why it matters:** Without this key, secrets cannot be stored securely. The app refuses to start.

**How to generate:**

<GenerateEncryptionKey />

Or via command line:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

A string like `xYz123...=` will appear. Enter it **completely** in `.env` (you can copy the key generated via the button with "Copy"):

```
ENCRYPTION_KEY=xYz123...=
```

**Tip:** Keep the key secure. If lost, existing secrets in the DB cannot be decrypted.

---

### 2.2 `JWT_SECRET_KEY` (required in production)

**What it is:** A secret value used by the app to sign **JWT tokens** (for logged-in users). It must be long and random.

**Why it matters:** Anyone who knows the key can create forged login tokens. In `ENVIRONMENT=production`, the default value `change-me-in-production` is rejected.

**Local/development:** The value from `.env.example` is sufficient for testing.

**Production:** At least 32 characters, random. Generate as follows:

<GenerateJwtSecret />

Or via command line:

```bash
openssl rand -base64 32
# or
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Enter in `.env` (copy the button-generated value with "Copy"):

```
JWT_SECRET_KEY=your-long-random-string
```

---

### 2.3 OAuth: At least one login provider

Fast-Flow has **no** classic password login. Access runs via OAuth providers (**GitHub**, **Google**, **Microsoft**, or **Custom OAuth**). At least **one** provider must be fully configured (each with `CLIENT_ID` and `CLIENT_SECRET`), otherwise the app will not start.

#### GitHub OAuth

**What you need:** An OAuth app on GitHub.

1. GitHub → **Settings** (your profile) → **Developer settings** → **OAuth Apps** → **New OAuth App**.
2. Set **Authorization callback URL** to:  
   `http://localhost:8000/api/auth/github/callback` (local with Docker, everything on :8000)  
   or `https://your-domain.com/api/auth/github/callback` in production.
3. Copy **Client ID** and **Client Secret**.

In `.env` (uncomment lines = remove `#` and enter values):

```
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
```

**Important:** The callback URL must **exactly** match `BASE_URL` (see below). Otherwise the OAuth flow fails.

#### Google OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Credentials** → **OAuth 2.0 Client IDs**.
2. Add **Authorized redirect URIs**:  
   `http://localhost:8000/api/auth/google/callback` (local) or `https://your-domain.com/api/auth/google/callback` (production).
3. Enter **Client ID** and **Client Secret**.

In `.env`:

```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

#### Microsoft OAuth (Entra ID)

In `.env`:

```
MICROSOFT_CLIENT_ID=...
MICROSOFT_CLIENT_SECRET=...
MICROSOFT_TENANT_ID=common
```

Callback:
`http://localhost:8000/api/auth/microsoft/callback` (local) or `https://your-domain.com/api/auth/microsoft/callback`.

#### Custom OAuth (e.g. Keycloak/Auth0)

In `.env`:

```
CUSTOM_OAUTH_CLIENT_ID=...
CUSTOM_OAUTH_CLIENT_SECRET=...
CUSTOM_OAUTH_AUTHORIZE_URL=...
CUSTOM_OAUTH_TOKEN_URL=...
CUSTOM_OAUTH_USERINFO_URL=...
```

Callback:
`http://localhost:8000/api/auth/custom/callback` (local) or `https://your-domain.com/api/auth/custom/callback`.

Detailed steps: [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme).

---

### 2.4 `INITIAL_ADMIN_EMAIL` (strongly recommended)

**What it is:** The email address of the **first admin**. The user who signs in with this email via a supported OAuth provider automatically receives the admin role on first login – **without** a prior invitation.

**Why it matters:** Without an admin, no one can invite other users or change settings. With `INITIAL_ADMIN_EMAIL`, you have an admin immediately.

```
INITIAL_ADMIN_EMAIL=your-email@example.com
```

The email must match the address your OAuth provider returns for your account.

---

### 2.5 `BASE_URL` and `FRONTEND_URL`

**BASE_URL:** The publicly reachable URL of the **backend** (API). Used for OAuth callbacks and links in emails. **No** trailing `/`.

**FRONTEND_URL:** The URL of the **frontend** if it runs separately (e.g. in local development: frontend on :3000, backend on :8000). If frontend and backend run together on one URL (e.g. everything on :8000), `FRONTEND_URL` can be omitted or set equal to `BASE_URL`.

**Typical cases:**

| Scenario | BASE_URL | FRONTEND_URL |
|----------|----------|--------------|
| Docker, everything on port 8000 | `http://localhost:8000` | omit or `http://localhost:8000` |
| Local: Frontend :3000, Backend :8000 | `http://localhost:8000` | `http://localhost:3000` |
| Production, single domain | `https://fastflow.example.com` | omit or identical |

**Common pitfall:** If `BASE_URL` does not exactly match the accessed URL (including `http`/`https`, port), the OAuth redirect will not work.

---

## 3. Important optional variables

### 3.1 `ENVIRONMENT`

- `development`: Relaxed security checks, debug info. For local work.
- `production`: Strict checks (e.g. `JWT_SECRET_KEY` must not be the default). For live operation.

```
ENVIRONMENT=development
```

For production: `ENVIRONMENT=production`.

---

### 3.2 `PIPELINES_DIR`

**What it is:** The path to the directory where your pipeline folders live (each with `main.py`).

**Default:** `./pipelines`

**When to adjust:** If you use a different directory or a cloned Git repo. With Docker: The path is **inside the container**; via `docker compose` a host folder is typically mounted (see `docker-compose.yaml`).

```
PIPELINES_DIR=./pipelines
```

---

### 3.3 `DATABASE_URL`

**Default:** Empty → **SQLite** is used (`./data/fastflow.db`).

**Production / team:** Often **PostgreSQL** for better concurrency and backup options.

```
# SQLite (default, leave unset or empty)
# DATABASE_URL=

# PostgreSQL
DATABASE_URL=postgresql://user:password@host:5432/fastflow
```

---

### 3.4 `UV_CACHE_DIR`

**What it is:** The global cache for **uv** (Python package manager). All pipeline containers share this cache; already downloaded packages are not downloaded again.

**Default:** `./data/uv_cache`

**When to adjust:** Only if you want a different location for the cache (e.g. larger disk). The default is sufficient to get started.

---

### 3.4a `UV_PYTHON_INSTALL_DIR` and `DEFAULT_PYTHON_VERSION`

**UV_PYTHON_INSTALL_DIR:** Directory for `uv python install` (uv-managed Python versions). Must be persistent (volume). Default: `{DATA_DIR}/uv_python`.

**DEFAULT_PYTHON_VERSION:** Default Python version when `pipeline.json` has no `python_version`. Default: `3.11`. The Python version is freely configurable per pipeline (e.g. 3.10, 3.11, 3.12).

**When to adjust:** Usually not necessary. Adjust `DEFAULT_PYTHON_VERSION` only if you want to use e.g. 3.12 globally.

---

### 3.5 `UV_PRE_HEAT`

**What it is:** `true` or `false`. When `true`, on **Git sync** and on **startup**:
- `uv python install {version}` for all Python versions required by pipelines,
- `uv pip compile --python {version}` for each `requirements.txt` (dependencies in cache).

On the first pipeline run, Python and packages are then usually already available (low latency).

**Recommendation:** Leave as `true`.

```
UV_PRE_HEAT=true
```

---

### 3.6 Git sync (when pipelines come from a repo)

| Variable | Meaning | typical value |
|----------|-----------|----------------|
| `GIT_BRANCH` | Branch to sync | `main` |
| `AUTO_SYNC_ENABLED` | Automatic sync on/off | `false` or `true` |
| `AUTO_SYNC_INTERVAL` | Interval in seconds | e.g. `300` |

Additionally: repo URL (`GIT_REPO_URL`) and, for private repos, `GIT_SYNC_TOKEN` (PAT, HTTPS) or `GIT_SYNC_DEPLOY_KEY` (SSH) — alternatively via the Sync UI (see [Configuration](/docs/deployment/CONFIGURATION), Git Sync).

---

## 4. Start Fast-Flow

### With Docker (recommended for production and easy setup)

```bash
docker compose up -d
```

Check logs:

```bash
docker compose logs -f orchestrator
```

The UI is at **http://localhost:8000** (or at the address configured in `BASE_URL`).

#### Note on `entrypoint.sh`

The orchestrator image uses `./entrypoint.sh` as the default start command (via `Dockerfile` `CMD`). This runs important steps before the API starts, such as DB initialization/migration and (in dev mode) seed pipeline copy.

If you override `command`/`args` for the orchestrator in Compose or Kubernetes, still call `./entrypoint.sh` or explicitly perform the init steps so startup and worker mount setup remain consistent.

### Local (for development)

Two terminals:

**Terminal 1 – Backend:**

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Terminal 2 – Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Then: Frontend usually at **http://localhost:3000**, backend at **http://localhost:8000**. Set `FRONTEND_URL` and `BASE_URL` as in the table above.

---

## 5. After startup

1. **First login:** Sign in with an OAuth provider. The email stored in `INITIAL_ADMIN_EMAIL` becomes admin on first login.
2. **Pipelines:** Either create folders under `PIPELINES_DIR` (e.g. `pipelines/my_first/main.py`) or set up Git sync. See [First Pipeline](/docs/pipelines/erste-pipeline) and [Pipelines – Overview](/docs/pipelines/uebersicht).
3. **Secrets:** Define them in `pipeline.json` (`encrypted_env` for sensitive values, `default_env` for plain defaults). The UI under Pipelines → Secrets shows all keys and provides an **encryption helper** for `encrypted_env` values. Use in the pipeline via `os.getenv("NAME")`.

---

## 6. Production checklist

- [ ] `ENVIRONMENT=production`
- [ ] `ENCRYPTION_KEY` and `JWT_SECRET_KEY` newly and securely generated, not the examples from the docs
- [ ] OAuth (GitHub/Google/Microsoft/Custom, at least one provider) with **production** callback URLs
- [ ] `BASE_URL` and optionally `FRONTEND_URL` with **https** and the real domain
- [ ] HTTPS (e.g. reverse proxy like Nginx) – [Deployment Guide](/docs/deployment/PRODUCTION)
- [ ] `DATABASE_URL` set for PostgreSQL (recommended)
- [ ] Backups planned for database and `.env`

---

## See also

- [Configuration](/docs/deployment/CONFIGURATION) – all environment variables at a glance
- [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme) – detailed OAuth setup
- [Quick Start](/docs/schnellstart) – compact version without explanations
- [Troubleshooting](/docs/troubleshooting) – when something does not start
