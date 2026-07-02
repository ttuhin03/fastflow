---
sidebar_position: 2
---

# Quick Start

**~5 min.** – Get Fast-Flow running in a few minutes.

## Prerequisites

- **Docker** & Docker Compose  
- **Python 3.11+** (for local development only)

## Option 1: Docker (recommended for production)

```bash
# 1. Prepare .env
cp .env.example .env

# 2. Generate encryption key (IMPORTANT!)
# Add the output key to ENCRYPTION_KEY in .env.
# For login: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, INITIAL_ADMIN_EMAIL (see Login section).
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. Start
docker compose up -d

# 4. View logs
docker compose logs -f orchestrator
```

**UI:** [http://localhost:8000](http://localhost:8000)

![Dashboard after startup](./img/dashboard.png)

## Option 2: Local (for development)

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configuration
cp .env.example .env
# -> Set ENCRYPTION_KEY in .env

# 3. Start
# Terminal 1 – Backend:
uvicorn app.main:app --reload
# Terminal 2 – Frontend:
cd frontend && npm run dev
```

**Optional – quick test with a minimal pipeline:** Create folder `pipelines/hello/` and `main.py` with the following content (default `PIPELINES_DIR` is `./pipelines`):

```python
# pipelines/hello/main.py
if __name__ == "__main__":
    print("Hello from Fast-Flow!")
```

After restarting the backend, the pipeline appears in the UI; test locally with `uv run main.py` (in the `pipelines/hello/` folder).

## Option 3: Kubernetes

Fast-Flow also runs **natively on Kubernetes** alongside Docker. Pipeline runs then execute as Kubernetes Jobs (no Docker socket required). Full guide: [Kubernetes Deployment](/docs/deployment/K8S) and the [k8s/README.md](https://github.com/ttuhin03/fastflow/blob/main/k8s/README.md) in the repository.

## Login (GitHub, Google, Microsoft, Custom OAuth)

1. **GitHub:** Callback `{BASE_URL}/api/auth/github/callback`  
   **Google:** Callback `{BASE_URL}/api/auth/google/callback`  
   **Microsoft:** Callback `{BASE_URL}/api/auth/microsoft/callback`  
   **Custom OAuth:** Callback `{BASE_URL}/api/auth/custom/callback`
2. In **`.env`:** configure at least one provider completely (`GITHUB_*`, `GOOGLE_*`, `MICROSOFT_*`, or `CUSTOM_OAUTH_*`) as well as `INITIAL_ADMIN_EMAIL`.
3. **Docker (everything on :8000):** omit `FRONTEND_URL` or set `=http://localhost:8000`, `BASE_URL=http://localhost:8000`.  
   **Dev (Frontend :3000, Backend :8000):** `FRONTEND_URL=http://localhost:3000`, `BASE_URL=http://localhost:8000`.

:::tip
Detailed steps, invitations, account linking, join requests: [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme).
:::

## Next steps

- [**Setup Guide**](/docs/setup) – Detailed explanation of env variables, OAuth, directories
- [**First Pipeline**](/docs/pipelines/erste-pipeline) – Tutorial: write your first pipeline from scratch
- [**Pipelines – Overview**](/docs/pipelines/uebersicht) – Structure, `main.py`, `requirements.txt`; volume or Git sync
- [**Pipeline Template**](https://github.com/ttuhin03/fastflow-pipeline-template) – pre-built structure
- [**Architecture**](/docs/architektur) – Runner cache, container lifecycle
- [**Configuration**](/docs/deployment/CONFIGURATION) – all environment variables (reference)
