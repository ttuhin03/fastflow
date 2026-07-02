---
sidebar_position: 2
---

# Writing Your First Pipeline

**~10 min.** – This tutorial walks you from zero to your first runnable pipeline – with explanations for each step. You need a running Fast-Flow instance (see [Quick Start](/docs/schnellstart) or [Setup Guide](/docs/setup)).

---

## What is a pipeline in Fast-Flow?

A **pipeline** is essentially a **Python script** in its own folder. Fast-Flow:

- discovers the folder automatically (as soon as it is under `PIPELINES_DIR` or arrives via Git sync),
- starts the script in an **isolated Docker container**,
- shows you **logs and status** in the UI.

You do not need to learn DAGs, operators, or special frameworks. If the script runs locally with `python main.py` (or `uv run main.py`), it will also run in Fast-Flow – provided you use a `requirements.txt` for external packages.

---

## Step 1: Create folder and `main.py`

### Where do pipelines live?

The default path is `./pipelines` (relative to the Fast-Flow project root). With Docker, this folder is usually mounted via a volume; in `docker-compose.yaml` you can see which host path is used.

**Important:** The **folder name** = **pipeline name** in the UI. Example: `pipelines/hello_world/` → the pipeline is named `hello_world`.

### Minimal structure

Every pipeline needs a **`main.py`** file in its folder. Everything else is optional.

Create:

```
pipelines/hello_world/main.py
```

Contents of `main.py`:

```python
# main.py
print("Hello from Fast-Flow!")
```

You can write code **top to bottom**. A `main()` function or `if __name__ == "__main__"` is **not** required, but allowed.

---

## Step 2: See and start the pipeline in the UI

### Synchronization

- **Local `pipelines/` directory:** If you create the folder directly under `PIPELINES_DIR`, the pipeline appears after the next **sync** or **restart** of the orchestrator. Some setups scan automatically at startup.
- **Git sync:** If pipelines come from a Git repo, you must trigger a **manual sync** (UI: Sync/Repository) or wait for the next auto-sync.

### In the UI

1. Open the Fast-Flow UI (e.g. http://localhost:8000) and sign in.
2. Go to **Pipelines**. You should see **`hello_world`** there.
3. Click **Run** to start the pipeline once.
4. Open the **run** and check the **logs** – you will see `Hello from Fast-Flow!`.

**Colors/status:**  
- **RUNNING** = currently running  
- **SUCCESS** = finished with exit code 0  
- **FAILED** = error (e.g. exception or exit code ≠ 0)

---

## Step 3: External packages – `requirements.txt`

As soon as you need libraries like `requests`, `pandas`, or `numpy`, create a `requirements.txt` in the **same pipeline folder** – like in a normal Python project.

### Example

```
pipelines/hello_world/
├── main.py
└── requirements.txt
```

Contents of `requirements.txt`:

```
requests==2.31.0
```

Contents of `main.py`:

```python
# main.py
import requests
print("Hello from Fast-Flow!")
r = requests.get("https://httpbin.org/get")
print("Status:", r.status_code)
```

### What happens with this?

- Fast-Flow runs the pipeline with **`uv`**. `uv` reads `requirements.txt` and provides the packages.
- On the **first** run, packages may take a moment to download; afterward they land in the **shared uv cache**. Further runs are often ready in under a second.
- If you use **Git sync** with `UV_PRE_HEAT=true`, dependencies are preloaded during sync.

**Format:** Standard `requirements.txt` (e.g. `package==1.2.3` or `package>=1.0`).

---

## Step 4: Metadata – `pipeline.json` (optional)

With a `pipeline.json` (or `{pipeline_name}.json`, e.g. `hello_world.json`) you can:

- provide a **description** (shown in the UI),
- set **resource limits** (CPU, RAM),
- configure **timeout** and **retries**,
- set the **Python version** (`python_version`, e.g. `"3.12"`) – **any per pipeline**, each pipeline can use 3.10, 3.11, 3.12, etc.; if omitted, `DEFAULT_PYTHON_VERSION` applies,
- assign **tags**.

### Simple example

`pipelines/hello_world/pipeline.json`:

```json
{
  "description": "My first pipeline – says hello and checks httpbin.",
  "tags": ["tutorial", "test"]
}
```

After the next sync, the description appears in the pipeline list. Full reference of all fields: [pipeline.json reference](/docs/pipelines/referenz).

---

## Step 5: Secrets and environment variables

Passwords, API keys, etc. do **not** belong in code and **not** in `pipeline.json`. Enter them in the Fast-Flow UI as **Secrets** (or parameters); they are stored **encrypted** and passed to the pipeline at runtime as **environment variables**.

### In the UI

1. Go to **Pipelines** → select `hello_world` (or the corresponding pipeline).
2. Open the **Secrets** / **Parameters** section (depending on UI naming).
3. Create a secret **`MEIN_API_KEY`** and enter a value (for the tutorial only: `test-123`).

### In code

In `main.py`, read environment variables with `os.getenv`:

```python
# main.py
import os

api_key = os.getenv("MEIN_API_KEY")
if api_key:
    print("API key is set (length):", len(api_key))
else:
    print("MEIN_API_KEY not set – please enter it in the UI.")
```

When the run starts, Fast-Flow sets the secrets/parameters configured in the UI as env vars. **Parameters** are unencrypted (for non-sensitive values), **Secrets** are stored encrypted.

---

## Step 6: Errors and logs

- **Unhandled exception** → Python exits with exit code ≠ 0 → run is **FAILED**.
- **`print` output** appears in the run **logs**. Use logs for debugging.
- If an **import** fails (e.g. package missing from `requirements.txt`), the error message appears in the logs.

### Example with error handling

```python
# main.py
import sys

def main():
    print("Starting ...")
    # ... your logic ...
    print("Done.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("Error:", e, file=sys.stderr)
        sys.exit(1)
```

`sys.exit(0)` = success, `sys.exit(1)` (or any value ≠ 0) = failure. Fast-Flow evaluates the exit code.

---

## Local testing (without UI)

You can run the pipeline locally **exactly** as in the container – with **`uv`** (or `pip` + `python`):

```bash
cd pipelines/hello_world
uv run --with-requirements requirements.txt main.py
```

If no `requirements.txt` exists: `uv run main.py`. Alternative: `pip install -r requirements.txt` and `python main.py`.

:::important "If it runs, it runs"
**If the script completes successfully locally this way, it will also run in the Fast-Flow orchestrator.** Same runtime (uv), no custom pipeline images. If you still get an error in the orchestrator: [Troubleshooting](/docs/troubleshooting#pipeline-lokal-orchestrator-fehlt).
:::

This helps you catch many errors before the first run in Fast-Flow.

---

## Quick checklist: First pipeline

- [ ] Folder under `PIPELINES_DIR` (e.g. `pipelines/mein_name/`) with **`main.py`**
- [ ] Optional: **`requirements.txt`** for external packages
- [ ] Optional: **`pipeline.json`** for description, tags, limits
- [ ] Create secrets/parameters in the **UI** and read them in `main.py` with **`os.getenv("NAME")`**
- [ ] After sync/restart, verify the pipeline in the UI and start a **Run**
- [ ] Check **logs** on success and on failure

---

## Next steps

- [**Pipelines – Overview**](/docs/pipelines/uebersicht) – Directory structure, discovery, all file types
- [**Advanced Pipelines**](/docs/pipelines/erweiterte-pipelines) – Retries, timeout, scheduling, webhooks, structure
- [**pipeline.json reference**](/docs/pipelines/referenz) – All fields for metadata and limits
