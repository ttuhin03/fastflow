---
sidebar_position: 3
---

# Advanced Pipelines

Once your first pipeline is running, the focus shifts to robustness, scheduling, and clean structure. This section covers retries, timeouts, secrets, scheduling, webhooks, resource limits, and typical patterns for more complex pipelines.

---

## 1. Structuring code

### 1.1 `main()` and clear steps

Even though a "flat" script (everything top to bottom) works, **functions** and a `main()` help with reading and testing:

```python
# main.py
import sys

def laden():
    # Fetch data
    pass

def transformieren(daten):
    # Process
    pass

def speichern(ergebnis):
    # Output
    pass

def main():
    daten = laden()
    ergebnis = transformieren(daten)
    speichern(ergebnis)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
```

**Benefit:** You can test `laden()`, `transformieren()`, etc. individually or reuse them in other pipelines.

### 1.2 Multiple files in the pipeline folder

You may add additional modules in the same folder, e.g. `utils.py`, `config.py`. The **entry point** is always `main.py`. Other files are loaded only through imports from `main.py`.

Example:

```
pipelines/data_job/
├── main.py        # from utils import parse_date
├── utils.py
└── requirements.txt
```

Note: The **working directory** in the container is the pipeline folder. Relative imports like `from . import utils` or `import utils` (when `utils.py` is in the same folder) work.

---

## 2. Retries and timeout

### 2.1 Automatic retries

When a pipeline ends **FAILED** (exit code ≠ 0), Fast-Flow can automatically restart it. You set the number of attempts.

**Global** (for all pipelines) in [Configuration](/docs/deployment/CONFIGURATION): `RETRY_ATTEMPTS`.

**Per pipeline** in `pipeline.json`:

```json
{
  "retry_attempts": 3
}
```

The pipeline value overrides the global setting. With e.g. `3`, there are up to **3 retry attempts** after the first failure.

**Typical use case:** Unstable external APIs or brief network outages. For logical errors (bad data, bugs), retries often help little – improve error handling in code instead.

**Retry strategy (`retry_strategy`):** In addition to `retry_attempts`, you can define in `pipeline.json` **how long** to wait before each retry: e.g. **Exponential Backoff** (for flaky APIs), **Fixed Delay** (fixed seconds), or **Custom Schedule** (list of wait times). See [pipeline.json reference – Retry strategies](/docs/pipelines/referenz#retry-strategien).

### 2.2 Timeout

If a pipeline runs too long, you can abort it after a certain **runtime** (seconds).

**Global:** `CONTAINER_TIMEOUT` (in seconds).

**Per pipeline** in `pipeline.json`:

```json
{
  "timeout": 3600
}
```

`3600` = 1 hour. The pipeline value takes precedence over the global setting.

**Note:** On timeout, the container is terminated. The pipeline ends as **FAILED** (or similar). Set large timeouts only when the job really needs to run long (e.g. large files, many API calls).

---

## 3. Secrets, parameters, and `default_env`

### 3.1 Secrets vs. parameters

| | **Secrets** | **Parameters** |
|---|-------------|----------------|
| **Storage** | Encrypted in the database | Unencrypted |
| **Use** | API keys, passwords, tokens | Endpoints, filenames, flags |
| **In the pipeline** | Both as environment variables (`os.getenv("NAME")`) |

Both are managed in the **UI** per pipeline (or globally, depending on Fast-Flow version). In code you do not distinguish – everything arrives as an env var.

### 3.2 `default_env` in `pipeline.json`

For **non-sensitive** defaults (e.g. `LOG_LEVEL`, `API_BASE`, `DRY_RUN=false`) you can use `default_env` in `pipeline.json`:

```json
{
  "description": "ETL job",
  "default_env": {
    "LOG_LEVEL": "INFO",
    "API_BASE": "https://api.example.com",
    "DRY_RUN": "false"
  }
}
```

- These values are set on **every** run.
- Env vars set additionally in the UI (e.g. for a single run) **override** these defaults.
- **Do not put secrets** in `default_env` – use the UI instead. `pipeline.json` typically lives in Git and would otherwise be a security risk.

---

## 4. Scheduling: Time-based execution

Instead of starting only manually or via webhook, you can run pipelines **on a schedule** (cron or interval).

### In pipeline.json (schedule from code)

You can define the schedule **directly in pipeline.json**: `schedule_cron` (e.g. `"0 9 * * *"`) or `schedule_interval_seconds` (e.g. `3600`). Optionally, `schedule_start` and `schedule_end` (ISO date/time) limit the period during which the schedule is active. On orchestrator startup and after Git sync, scheduler jobs are created automatically from this. See [pipeline.json reference – Schedule](/docs/pipelines/referenz#schedule-cron--intervall-in-pipelinejson).

### Multiple run configurations (`schedules`)

Per pipeline you can define **multiple** scheduled runs with different cron/interval, env vars, time ranges, and resources. The optional **`schedules`** array in pipeline.json serves this purpose. Each entry has a unique **`id`** (e.g. `"prod"`, `"staging"`) and can have its own values for `schedule_cron`/`schedule_interval_seconds`, `schedule_start`/`schedule_end`, `default_env`, optional `encrypted_env`, as well as **per-schedule overrides** for `cpu_hard_limit`, `mem_hard_limit`, `cpu_soft_limit`, `mem_soft_limit`, `timeout`, `retry_attempts`, and `retry_strategy`. Env vars are merged: first pipeline `default_env`, then entry `default_env`; then pipeline `encrypted_env`, then entry `encrypted_env`. This lets you run the same pipeline e.g. daily for production with higher limits and more retries, and hourly for staging with lower resources. Details and example: [pipeline.json reference – schedules](/docs/pipelines/referenz#mehrere-run-konfigurationen-schedules).

### In the UI

Under the respective pipeline (or in the scheduler section) you can set up **cron expressions** or **intervals** (e.g. every 6 hours). The exact fields depend on the Fast-Flow version; typical:

- **Cron:** e.g. `0 2 * * *` = daily at 2:00 AM
- **Interval:** e.g. every 3600 seconds
- **Start/end:** optional time range (ISO date/time)

### Use cases

- **Daily:** Reports, data ETL, cleanup.
- **Hourly:** Aggregations, checks.
- **Weekly:** Large computations, archiving.

Scheduling is stored in the database (e.g. via APScheduler). Details: [API](/docs/api/api) (scheduler endpoints) and [Configuration](/docs/deployment/CONFIGURATION).

---

## 5. Webhooks: External trigger

Via a **webhook**, an external system (CI/CD, another service, cron on another machine) can trigger a pipeline without being in the Fast-Flow UI.

### Activation: `webhook_key` in `pipeline.json`

Webhooks are active when a **`webhook_key`** is set at pipeline level and/or per entry in **`schedules[]`** (not empty). Without any `webhook_key`, webhooks are disabled for that pipeline.

**Pipeline level** (one key for the entire pipeline, run with default config):

```json
{
  "description": "Sync job",
  "webhook_key": "dein-geheimer-schluessel"
}
```

**Per schedule** (separate key per run configuration): Each entry in `schedules[]` can optionally include **`webhook_key`**. The called URL then determines which run configuration (run_config_id) is used – e.g. separate keys for "prod" and "staging". Each `webhook_key` may appear only **once** per pipeline (pipeline level and all schedules combined); duplicates cause an error when loading pipeline.json.

```json
{
  "schedules": [
    { "id": "prod", "schedule_cron": "0 9 * * *", "webhook_key": "geheim-prod" },
    { "id": "staging", "schedule_cron": "0 10 * * *", "webhook_key": "geheim-staging" }
  ]
}
```

**Important:** Keep keys **secret** – anyone who knows the webhook URL can start the pipeline (or the associated schedule).

### Endpoint and invocation

- **Method:** `POST`
- **URL:** `/api/webhooks/{pipeline_name}/{webhook_key}`
- **Body:** optional (empty or `{}`). The key is in the path; a `{"webhook_key": "..."}` in the body is not required.

Example:

```bash
curl -X POST "https://deine-instanz.de/api/webhooks/data_sync/dein-geheimer-schluessel"
```

**Responses:** 200 with run info; **401** for wrong `webhook_key`; **404** if the pipeline does not exist, is disabled, or webhooks are off for it.

The **complete webhook URL** (with your key) is shown in the pipeline detail view in the UI and can be copied there. Details: [pipeline.json reference – Webhooks](/docs/pipelines/referenz#webhooks-pipeline-per-http-auslösen) and [API](/docs/api/api).

### Typical usage

- **CI/CD:** Start a smoke test or data import after build or deploy.
- **External tools:** When another system is "done", it triggers the next stage in Fast-Flow.
- **Event-driven:** In combination with a message broker or queue (the caller reads the queue and calls the webhook).

---

## 6. Resource limits (CPU, RAM)

To prevent a pipeline from overloading the rest of the system, you can limit **CPU** and **RAM**. This is done via `pipeline.json` and applies as **Docker limits** in the container.

### Hard limits

- **`cpu_hard_limit`:** CPU cores (e.g. `1.0` = one core, `0.5` = half a core). If the container becomes CPU-intensive, it is throttled.
- **`mem_hard_limit`:** RAM, e.g. `"512m"`, `"1g"`, `"2g"`. Exceeding it leads to **OOM kill** (exit code 137) – the pipeline is **FAILED**.

Example:

```json
{
  "cpu_hard_limit": 1.0,
  "mem_hard_limit": "1g"
}
```

### Soft limits (monitoring only)

- **`cpu_soft_limit`** and **`mem_soft_limit`** are **not** enforced as hard caps. They serve **monitoring**; exceeding them may appear as a warning in the UI. Useful to see whether you should raise the hard limits.

Full details: [pipeline.json reference](/docs/pipelines/referenz).

---

## 7. Error handling and logging

### 7.1 Exceptions and exit code

- **Unhandled exception** → Python exits with exit code ≠ 0 → run **FAILED**.
- **`sys.exit(0)`** → success. **`sys.exit(1)`** (or any value ≠ 0) → failure.

For better logs and control:

```python
import sys
import traceback

def main():
    try:
        # ... logic ...
        return 0
    except ConnectionError as e:
        print("Connection error:", e, file=sys.stderr)
        traceback.print_exc()
        return 1
    except ValueError as e:
        print("Data error:", e, file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
```

`traceback.print_exc()` appears in the **logs** and helps with debugging.

### 7.2 Logging module

Instead of only `print`, you can use the standard **`logging`** module:

```python
import logging
import os

# Optional: LOG_LEVEL from env (e.g. from default_env or UI)
level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, level, logging.INFO))
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting processing ...")
    # ...
    logger.warning("No new data.")
    logger.info("Done.")
    return 0
```

`logging` writes to **stderr**, which appears in Fast-Flow logs. This keeps logs manageable even for longer pipelines.

---

## 8. Longer and more robust jobs

### 8.1 Work in small steps (chunks)

Very large data volumes or many API calls should be processed in **chunks**:

- Less risk of hitting the timeout.
- On failure, damage is limited; you can resume from a defined point.

Example idea: 100,000 rows → process 1,000 at a time, log progress. Optionally store a **checkpoint** (e.g. "up to row X done") in a file or DB and continue on the next run.

### 8.2 Idempotency

When a pipeline runs **multiple times** (retry, duplicate webhook, scheduled run), the result should be **idempotent**: running twice = same end state as running once. Typical approaches:

- **"Upsert"** instead of blind append (e.g. in DB or filesystem).
- **Deduplication** via IDs or timestamps.
- **Temporary files** with unique names and cleanup at the end.

### 8.3 External services (APIs, databases, object storage)

- **APIs:** `requests` or `httpx`, set timeouts, retries in code (e.g. `tenacity`) for brief network outages. Secrets (API keys) from `os.getenv`.
- **Databases:** Driver in `requirements.txt` (e.g. `psycopg2`, `pymysql`, `sqlalchemy`). Connection strings as secrets/parameters.
- **S3-like storage:** `boto3` or appropriate library, credentials from env. For large files: streaming or chunk transfer to respect RAM limits.

---

## 9. Overview: When to use what?

| Goal | Where / How |
|------|-------------|
| **Retries on failure** | `retry_attempts` in `pipeline.json` or `RETRY_ATTEMPTS` globally |
| **Maximum runtime** | `timeout` in `pipeline.json` or `CONTAINER_TIMEOUT` |
| **Secret values** | Secrets in the UI, `os.getenv("NAME")` in code |
| **Non-critical defaults** | `default_env` in `pipeline.json` |
| **Schedule** | Scheduling in the UI (cron/interval) |
| **External trigger** | Webhook URL, `POST` request |
| **Limit CPU/RAM** | `cpu_hard_limit`, `mem_hard_limit` in `pipeline.json` |
| **Structure and maintainability** | `main()`, modules, `logging` |
| **Large data / long runs** | Chunks, checkpoints, idempotent logic |
| **Wait time between retries** | `retry_strategy` in `pipeline.json` (exponential_backoff, fixed_delay, custom_schedule) |
| **Webhook trigger** | `webhook_key` in `pipeline.json`, `POST /api/webhooks/{pipeline_name}/{webhook_key}` |
| **Notebook: retries per cell** | `type: "notebook"` + `cells` in `pipeline.json` and/or cell metadata `fastflow`. See [Notebook Pipelines](/docs/pipelines/notebook-pipelines). |

---

## 10. Best practices

- **Clean code:** Keep `main.py` modular. Use helper functions and additional modules in the same folder.
- **Environment variables:** Configuration and secrets via `os.getenv("NAME")`. Manage secret values in the **Fast-Flow UI** as secrets, not in `pipeline.json` or code.
- **Logs:** Simply use `print()`. Fast-Flow captures **stdout** and **stderr** and streams them to the UI. For more structured output: `logging` (see section 7).

---

## 11. Support: "If it runs locally, it runs in Fast-Flow"

Fast-Flow stands for **plain Python that runs locally also running in the orchestrator** – same runtime (uv), no custom pipeline images.

If your script **runs locally** but **not** in the orchestrator, please report:

- **Fast-Flow Issues:** [GitHub Issues](https://github.com/ttuhin03/fastflow/issues)

**Information that helps:**

- `main.py` (code)
- `pipeline.json` and `requirements.txt`
- Logs from the orchestrator UI (run logs)

Further steps and typical causes: [Troubleshooting – Pipeline runs locally, not in orchestrator](/docs/troubleshooting#pipeline-lokal-orchestrator-fehlt).

---

## See also

- [pipeline.json reference](/docs/pipelines/referenz) – all fields including soft limits, tags, `enabled`, `type`, `cells`
- [Notebook Pipelines](/docs/pipelines/notebook-pipelines) – Jupyter notebooks, cell retries, logs per cell
- [Pipelines – Overview](/docs/pipelines/uebersicht) – basic structure, `main.py`, `main.ipynb`, `requirements.txt`
- [First Pipeline](/docs/pipelines/erste-pipeline) – getting started from zero
- [Configuration](/docs/deployment/CONFIGURATION) – global values (`RETRY_ATTEMPTS`, `CONTAINER_TIMEOUT`, …)
- [API](/docs/api/api) – scheduler, webhooks, runs
