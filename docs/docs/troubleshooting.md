---
sidebar_position: 20
---

# Troubleshooting

Common errors and quick fixes.

## "Docker is not running" / "Connection refused"

- **Cause:** Docker daemon not reachable.
- **Solution:**
  - Start Docker Desktop (or on Linux: `sudo systemctl start docker`).
  - Check: `docker ps`

## "Docker proxy / 403 Forbidden"

The orchestrator only communicates via the [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY). Disallowed operations result in 403.

- **Check logs:**  
  `docker compose logs docker-proxy`
- **Ensure:** In the proxy configuration, e.g. `POST=1` must be set for container creation. See [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY).

## "Port 8000 in use"

- **Solution:** Set the `PORT` variable in `.env` to a free port (e.g. `PORT=8001`).

## "ENCRYPTION_KEY missing"

The application will not start without a valid `ENCRYPTION_KEY`.

- **Solution:**
  1. Generate key:  
     `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  2. Add to `.env`: `ENCRYPTION_KEY=<generated key>`

## OAuth / login not working

- **Callbacks:** GitHub `{BASE_URL}/api/auth/github/callback`, Google `{BASE_URL}/api/auth/google/callback`, Microsoft `{BASE_URL}/api/auth/microsoft/callback`, Custom `{BASE_URL}/api/auth/custom/callback`. `BASE_URL` in `.env` must exactly match the reachable URL (including port, no trailing slash).
- **Docker vs. Dev:**  
  - Everything on :8000: omit `FRONTEND_URL` or set `=http://localhost:8000`, `BASE_URL=http://localhost:8000`.  
  - Frontend :3000, Backend :8000: `FRONTEND_URL=http://localhost:3000`, `BASE_URL=http://localhost:8000`.

Details: [OAuth (GitHub, Google, Microsoft, Custom)](/docs/oauth/readme).

## Pipeline does not appear / is not recognized

- **`main.py`:** The folder must contain a `main.py`.
- **Path:** `PIPELINES_DIR` in `.env` must point to the correct directory (volume or cloned repo).
- **Git sync:** With Git sync, trigger a manual sync after changes or wait for the next auto-sync.

**Sync/webhook: Pipeline does not appear after push**

- **Auto-sync:** Check `AUTO_SYNC_ENABLED=true` and `AUTO_SYNC_INTERVAL`; after push, wait for the next run or trigger a **manual sync** in the UI.
- **Webhook:** Is the webhook URL correctly configured in GitHub/GitLab etc.? Do repo URL and `GIT_BRANCH` in `.env` match the pushed branch.
- **Manual sync:** Run sync in the UI and check logs/error messages.

## `pipeline.json` errors (invalid JSON)

If the UI shows errors about pipeline metadata:

- **Syntax:** `pipeline.json` (or `{pipeline_name}.json`) must be valid JSON. Common errors: missing bracket, **trailing comma** (e.g. `"tags": ["a", ]`), quotes around keys.
- **Check:** `python3 -c "import json; json.load(open('pipelines/meine_pipeline/pipeline.json'))"` – produces no output for valid JSON, otherwise an error message with line/position.
- **Fallback:** Temporarily rename or delete the file; Fast-Flow also runs without `pipeline.json` (all metadata optional).

## Run fails with exit code 137

- **Common:** Out-of-memory (OOM). The container was terminated by the system.
- **Solution:** Increase `mem_hard_limit` in `pipeline.json` or adjust global memory limits.

<a id="pipeline-lokal-orchestrator-fehlt"></a>

## Pipeline runs locally, fails in orchestrator

Fast-Flow aims for **"If it runs locally, it runs in Fast-Flow"** – same runtime (uv), no custom pipeline images. If a difference still occurs, check first:

- **Local run like in orchestrator:**  
  `uv run --python {version} --with-requirements requirements.txt main.py` (or `pip install -r requirements.txt` and `python main.py`). `{version}` from `pipeline.json` (`python_version`, freely configurable per pipeline) – Python version and packages should be comparable.
- **`requirements.txt`:** All used external packages must be listed.
- **Paths:** In the container, the working directory is the pipeline folder. Use relative paths from `main.py`.
- **Secrets/env:** Values set in the UI are passed as environment variables. If e.g. `API_KEY` is missing, `os.getenv("API_KEY")` may return `None`.

**When reporting a bug** (e.g. [Fast-Flow Issues](https://github.com/ttuhin03/fastflow/issues)), include:

- `main.py`, `pipeline.json`, `requirements.txt`
- Logs from the orchestrator UI (run logs)
- Brief description: What do you expect, what happens?

This makes it possible to trace and fix compatibility issues in a targeted way.

## Further help

- [Configuration](/docs/deployment/CONFIGURATION) – all env variables
- [Quick Start](/docs/schnellstart) – go through basic setup again
