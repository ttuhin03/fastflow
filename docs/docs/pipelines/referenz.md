---
sidebar_position: 5
---

# pipeline.json – Reference

Optional metadata file for resource limits, timeout, retries, description, tags, and environment variables.

**Filenames:** `pipeline.json` (preferred) or `{pipeline_name}.json` (e.g. `data_processor.json`).

## JSON format (example)

**Script pipeline:**

```json
{
  "cpu_hard_limit": 1.0,
  "mem_hard_limit": "1g",
  "cpu_soft_limit": 0.8,
  "mem_soft_limit": "800m",
  "timeout": 3600,
  "retry_attempts": 3,
  "description": "Processes incoming data daily",
  "tags": ["data-processing", "daily"],
  "enabled": true,
  "python_version": "3.12",
  "default_env": {
    "LOG_LEVEL": "INFO",
    "DEBUG": "false"
  }
}
```

**Notebook pipeline** (with cell retries):

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "Notebook with cell retries",
  "python_version": "3.12",
  "timeout": 120,
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 }
  ]
}
```

## Fields

### Resource limits

| Field | Default | Description |
|------|----------|--------------|
| `cpu_hard_limit` | – | CPU limit in cores (e.g. `0.5`, `1.0`, `2.0`). **Strictly** enforced (throttling). |
| `mem_hard_limit` | – | RAM (e.g. `"512m"`, `"1g"`, `"2g"`). **OOM kill** on exceed. |
| `cpu_soft_limit` | – | CPU threshold for **monitoring/warnings** in the UI only, no limiting. |
| `mem_soft_limit` | – | RAM threshold for **monitoring/warnings** in the UI only, no limiting. |

### Pipeline type

| Field | Type | Description |
|------|-----|--------------|
| `type` | String, optional | **`"script"`** (default) or **`"notebook"`**. With `"notebook"`, **`main.ipynb`** must exist in the pipeline folder; the notebook is then executed cell by cell (see [Notebook Pipelines](/docs/pipelines/notebook-pipelines)). With `"script"`, **`main.py`** is executed. |

### Pipeline configuration

| Field | Type | Description |
|------|-----|--------------|
| `timeout` | Integer, optional | Timeout in seconds (overrides global `CONTAINER_TIMEOUT`). `0` = no timeout (e.g. for long-running daemons). Per schedule, a separate value can be set in `schedules[].timeout`. |
| `retry_attempts` | Integer, optional | Number of retries on failure (overrides global `RETRY_ATTEMPTS`). **Note:** For notebook pipelines, **pipeline-level retries** are not executed; only [cell retries](/docs/pipelines/notebook-pipelines#cell-retries-the-cells-array) in `cells` or cell metadata apply. |
| `retry_strategy` | Object, optional | Wait strategy between retries. See [Retry strategies](#retry-strategies). Applies only to script pipelines. |
| `enabled` | Boolean, optional | Pipeline enabled/disabled (default: `true`). |
| `python_version` | String, optional | Python version for `uv run --python` – **any per pipeline** (e.g. `"3.10"`, `"3.11"`, `"3.12"`). Each pipeline can use a different version. If omitted: `DEFAULT_PYTHON_VERSION` (default 3.11). |

**Example in the pipeline template:** The **`timeout_example`** pipeline in the [fastflow-pipeline-template](https://github.com/ttuhin03/fastflow-pipeline-template) demonstrates timeout per pipeline: `pipeline.json` has `"timeout": 10`, the script runs 25 seconds – the run is terminated after 10 seconds and marked as **FAILED** (error type: timeout).

### Notebook pipelines: cell retries (`cells`)

Relevant only when **`type`** = **`"notebook"`**. See in detail [Notebook Pipelines – Cell retries](/docs/pipelines/notebook-pipelines#cell-retries-the-cells-array).

| Field | Type | Description |
|------|-----|--------------|
| `cells` | Array, optional | One entry per **code cell** (index 0 = first code cell, 1 = second, …). Each entry can contain **`retries`** (Integer) and **`delay_seconds`** (Number). If an entry or the array is missing: 0 retries, 1 s pause. Cell metadata in the notebook (`metadata.fastflow`) overrides values for the respective cell. |

### Schedule (cron / interval in pipeline.json)

You can define the schedule **directly in pipeline.json**. On orchestrator startup and after Git sync, scheduler jobs are created automatically from this (source: `pipeline_json`). Specify either **cron** or **interval**, not both. Optional start/end times limit the active period.

| Field | Type | Description |
|------|-----|--------------|
| `schedule_cron` | String, optional | 5-part cron (e.g. `"0 9 * * *"` = daily at 09:00). Format: minute hour day month weekday. |
| `schedule_interval_seconds` | Integer, optional | Interval in seconds (e.g. `3600` = hourly). Either this or `schedule_cron`. |
| `schedule_start` | String, optional | ISO date/time – start of the period during which the schedule runs (inclusive). |
| `schedule_end` | String, optional | ISO date/time – end of the period (inclusive). |

| `run_once_at` | String, optional | ISO date/time – run the pipeline once at this time. On Git sync/startup, a corresponding scheduler job (type DATE) is created. Must be in the future. |

If both `schedule_cron` and `schedule_interval_seconds` are set, cron takes precedence. Without `schedule_start`/`schedule_end`, the schedule runs indefinitely.

### Multiple run configurations (`schedules`)

If you need **multiple scheduled runs per pipeline** with different cron/interval, env vars, or time ranges, you can use the optional **`schedules`** array. Each entry becomes its own scheduler job; each run uses the associated run configuration (including its own `default_env` and optional `encrypted_env`).

**Behavior:** If `schedules` is present and not empty, **only** these entries are used; top-level fields `schedule_cron`/`schedule_interval_seconds`/`schedule_start`/`schedule_end` are then **not** used for scheduler jobs. If `schedules` is omitted or empty, a single job from the top-level schedule fields applies as before.

| Field (per entry) | Type | Description |
|-------------------|-----|---------------|
| `id` | String, required | Unique identifier of the run configuration (e.g. `"prod"`, `"staging"`). Shown in the UI and run history as `run_config_id`. |
| `schedule_cron` | String, optional | 5-part cron (e.g. `"0 8 * * *"`). Either this or `schedule_interval_seconds`. |
| `schedule_interval_seconds` | Integer, optional | Interval in seconds. Either this or `schedule_cron`. |
| `schedule_start` | String, optional | ISO date/time – start of the period for this schedule. |
| `schedule_end` | String, optional | ISO date/time – end of the period. |
| `default_env` | Object, optional | Additional/overriding env vars for this run. Merged with pipeline `default_env` (entry overrides). |
| `encrypted_env` | Object, optional | Per-schedule encrypted env vars (key → ciphertext). Merged with pipeline `encrypted_env`; same key is overridden. |
| `enabled` | Boolean, optional | Schedule enabled/disabled (default: `true`). With `false`, the job is created but disabled (pipeline `enabled` still applies). |
| `cpu_hard_limit` | Number, optional | CPU limit in cores for this schedule (overrides pipeline value). |
| `mem_hard_limit` | String, optional | RAM limit (e.g. `"512m"`, `"1g"`) for this schedule (overrides pipeline value). |
| `cpu_soft_limit` | Number, optional | CPU soft limit for monitoring for this schedule. |
| `mem_soft_limit` | String, optional | RAM soft limit for monitoring for this schedule. |
| `timeout` | Integer, optional | Timeout in seconds for this schedule (`0` = unlimited). Overrides pipeline `timeout`. |
| `retry_attempts` | Integer, optional | Number of retry attempts for this schedule. Overrides pipeline `retry_attempts`. |
| `retry_strategy` | Object, optional | Retry strategy for this schedule (see [Retry strategies](#retry-strategies)). Overrides pipeline `retry_strategy`. |
| `webhook_key` | String, optional | Separate webhook key for this schedule. If set: `POST /api/webhooks/{pipeline_name}/{webhook_key}` starts a run with **this** run configuration (run_config_id = `id`). Each `webhook_key` may appear only **once** per pipeline (pipeline level and all schedules combined). |

**Example:**

```json
{
  "description": "ETL with multiple runs",
  "default_env": { "LOG_LEVEL": "INFO" },
  "schedules": [
    {
      "id": "prod",
      "schedule_cron": "0 8 * * *",
      "schedule_start": "2025-01-01T00:00:00",
      "schedule_end": "2025-12-31T23:59:59",
      "default_env": { "ENVIRONMENT": "production", "DRY_RUN": "false" }
    },
    {
      "id": "staging",
      "schedule_interval_seconds": 3600,
      "default_env": { "ENVIRONMENT": "staging", "DRY_RUN": "true" }
    }
  ]
}
```

### Long-running processes (daemon)

| Field | Type | Description |
|------|-----|--------------|
| `timeout` | Integer, optional | `0` = no timeout (pipeline runs indefinitely). For long-running processes with `while True` loop. |
| `restart_on_crash` | Boolean, optional | If `true`: pipeline is automatically restarted after FAILED (after `restart_cooldown` seconds). |
| `restart_cooldown` | Integer, optional | Seconds between stop and restart (default: 60). Prevents restart loops. |
| `restart_interval` | String, optional | Regular restart. Cron expression (e.g. `"0 3 * * *"` = daily at 03:00) or interval in seconds. Terminates running run, waits cooldown, starts again. |
| `max_instances` | Integer, optional | Maximum number of concurrent runs of this pipeline. If set, a new start is rejected once the number of PENDING/RUNNING runs reaches the limit. Without limit, only global `MAX_CONCURRENT_RUNS` applies. |

### Pipeline chaining (downstream triggers)

| Field | Type | Description |
|------|-----|--------------|
| `downstream_triggers` | Array, optional | List of downstream pipelines started automatically after this pipeline completes. Each entry: `{"pipeline": "name", "on_success": true, "on_failure": false, "on_route": null, "run_config_id": "prod"}`. Fields: `on_success` (default: `true`), `on_failure` (default: `false`), `on_route` (optional, see below), `run_config_id` (optional). |

Triggers from `pipeline.json` and from the UI (API) are merged. Runs are started with `triggered_by="downstream"`.

**Trigger fields overview:**

| Field | Default | Description |
|------|----------|--------------|
| `on_success` | `true` | Starts downstream when this pipeline exits with code 0 |
| `on_failure` | `false` | Starts downstream when this pipeline exits with code ≠ 0 |
| `on_route` | `null` | Starts downstream only when the pipeline writes exactly this route string to `FASTFLOW_ROUTE_FILE` (success only) |
| `run_config_id` | `null` | Schedule ID of the downstream pipeline (`schedules[].id`); if omitted = default config |

**Example (classic):**

```json
{
  "description": "Pipeline A – starts B on success, C on success or failure",
  "downstream_triggers": [
    { "pipeline": "pipeline_b", "on_success": true, "on_failure": false, "run_config_id": "prod" },
    { "pipeline": "pipeline_c", "on_success": true, "on_failure": true }
  ]
}
```

**Example (route-based routing):**

With `on_route`, the pipeline can control in code which downstream pipeline starts next – without misusing the exit code:

```json
{
  "description": "Routing based on data situation",
  "downstream_triggers": [
    { "pipeline": "handler_full",    "on_route": "full",    "on_success": false },
    { "pipeline": "handler_partial", "on_route": "partial", "on_success": false },
    { "pipeline": "handler_error",   "on_failure": true,    "on_success": false }
  ]
}
```

```python
# main.py
import os, sys

def set_route(label: str) -> None:
    """Writes a route string to FASTFLOW_ROUTE_FILE."""
    route_file = os.environ.get("FASTFLOW_ROUTE_FILE")
    if route_file:
        open(route_file, "w").write(label)

if got_full_data:
    set_route("full")
    sys.exit(0)   # Exit code stays 0 → handler_full starts
elif got_partial:
    set_route("partial")
    sys.exit(0)   # Exit code stays 0 → handler_partial starts
else:
    sys.exit(1)   # Real error → handler_error starts
```

Fastflow sets `FASTFLOW_ROUTE_FILE` as an env var with the path to a writable file. After container exit, the executor reads the file and decides which downstream triggers with `on_route` fire.

> **Why not exit codes?** Exit codes like `1`, `2` have standard meanings (errors) and can be set by libraries or the OS. Route labels are explicit and do not interfere with error handling.

**Example (cron/interval):**

```json
{
  "description": "Daily report at 09:00",
  "schedule_cron": "0 9 * * *",
  "schedule_start": "2025-01-01",
  "schedule_end": "2025-12-31T23:59:59"
}
```

**Example (one-time execution):**

```json
{
  "description": "One-time execution on 2026-01-15 at 12:00 UTC",
  "run_once_at": "2026-01-15T12:00:00"
}
```

**Example (long-running daemon):**

```json
{
  "description": "Long-running daemon with auto-restart on crash",
  "timeout": 0,
  "restart_on_crash": true,
  "restart_cooldown": 120,
  "restart_interval": "0 3 * * *"
}
```

### Webhooks

| Field | Description |
|------|--------------|
| `webhook_key` | Webhook key (string). If set and not empty: pipeline can be triggered via `POST /api/webhooks/{pipeline_name}/{webhook_key}`. **Do not set or leave empty** = webhooks disabled. |

### Documentation

| Field | Type | Description |
|------|-----|--------------|
| `description` | String, optional | Description, shown in the UI. |
| `tags` | Array[String], optional | Tags for categorization/filtering. |

### Environment variables

| Field | Type | Description |
|------|-----|--------------|
| `default_env` | Object, optional | Default env vars on every run. Merged with UI env vars (UI takes precedence). **Do not put secrets here** – use `encrypted_env` (see next row). |
| `encrypted_env` | Object, optional | **Encrypted** env vars (key → ciphertext). Values are encrypted with the server `ENCRYPTION_KEY`; plaintext never in the file. In the UI under "Secrets" → "Encrypt for pipeline.json", enter plaintext, generate ciphertext, and **manually** enter it here. At runtime the server decrypts and provides values to the pipeline environment. |
| `secrets` | Array[String], optional | Allow-list of secret **keys** from the global database-backed Secrets store that this pipeline is entitled to receive as env vars at runtime. Each run only gets the keys listed here – nothing is injected by default. A pipeline that doesn't need database secrets should omit this field. |

**Example `encrypted_env`:** Encrypt plaintext in the UI, then enter in pipeline.json:

```json
{
  "default_env": { "LOG_LEVEL": "INFO" },
  "encrypted_env": {
    "API_KEY": "gAAAAABl...",
    "DB_PASSWORD": "gAAAAABl..."
  }
}
```

**Example `secrets`:** only `SHARED_S3_TOKEN` (from the database Secrets store) is injected into this pipeline's env at runtime – secrets belonging to other pipelines stay out of reach:

```json
{
  "secrets": ["SHARED_S3_TOKEN"]
}
```

### Retry strategies

`retry_strategy` controls **how long** to wait before each retry. Without `retry_strategy`, a fixed default interval applies (e.g. 60 s).

| `type` | Additional fields | Description |
|--------|--------------|--------------|
| `exponential_backoff` | `initial_delay`, `max_delay`, `multiplier` | Wait time grows: `initial_delay * (multiplier ^ attempt)`, capped at `max_delay`. Suitable for unstable APIs. |
| `fixed_delay` | `delay` | Always the same wait time (seconds). Suitable for internal services. |
| `custom_schedule` | `delays` | List of wait times in seconds, one value per retry (e.g. `[60, 300, 3600]`). |

**Example: Exponential Backoff**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "exponential_backoff",
    "initial_delay": 60,
    "max_delay": 3600,
    "multiplier": 2.0
  }
}
```

**Example: Fixed Delay**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "fixed_delay",
    "delay": 120
  }
}
```

**Example: Custom Schedule**

```json
{
  "retry_attempts": 3,
  "retry_strategy": {
    "type": "custom_schedule",
    "delays": [60, 300, 3600]
  }
}
```

---

## Webhooks: Trigger pipeline via HTTP

If a **`webhook_key`** is set in `pipeline.json` (at pipeline level and/or per entry in **`schedules[]`**), the pipeline can be triggered via **HTTP POST**:

- **Endpoint:** `POST /api/webhooks/{pipeline_name}/{webhook_key}`
- **Body:** optional (e.g. `{}` or empty). The key is in the path.
- **Resolution:** The `webhook_key` used determines the run configuration:
  - Key matches **pipeline-level** `webhook_key` → run with default config (without schedule-specific env/limits).
  - Key matches a **`schedules[].webhook_key`** → run with exactly that run configuration (run_config_id = `schedules[].id`).
- **Response:** 200 with run info; **401** for wrong key; **404** if pipeline does not exist or webhooks are disabled.

Each `webhook_key` may appear only **once** per pipeline (strict duplicate check; otherwise error when loading pipeline.json).

Example (pipeline level):

```bash
curl -X POST "https://deine-instanz.de/api/webhooks/data_sync/mein-geheimer-key"
```

Webhook URL(s) are shown in the pipeline detail view in the UI (per pipeline level and per schedule with `webhook_key`). **Keep `webhook_key` secret** – anyone with the URL can start the pipeline. Statistics show webhook triggers total and optionally per run configuration.

---

## Behavior

- **Hard limits:** Set as Docker limits.  
  - Memory exceed → OOM kill (exit code 137).  
  - CPU → throttling.
- **Soft limits:** Monitoring only, no limiting; exceed appears in the frontend as a warning.
- **Missing metadata:** Global/default limits are used (if configured).
- **Timeout & retry:** Pipeline values override global configuration.

## Minimal example

```json
{
  "cpu_hard_limit": 2.0,
  "mem_hard_limit": "2g",
  "cpu_soft_limit": 1.5,
  "mem_soft_limit": "1.5g"
}
```

## See also

- [Pipelines – Overview](/docs/pipelines/uebersicht)
- [Notebook Pipelines](/docs/pipelines/notebook-pipelines) – `type: "notebook"`, `cells`, cell retries, logs per cell
- [Advanced Pipelines](/docs/pipelines/erweiterte-pipelines) – webhooks, best practices
- [API](/docs/api/api) – webhook endpoint `POST /api/webhooks/{pipeline_name}/{webhook_key}`
- [Configuration](/docs/deployment/CONFIGURATION) – global limits, `CONTAINER_TIMEOUT`, `RETRY_ATTEMPTS`
