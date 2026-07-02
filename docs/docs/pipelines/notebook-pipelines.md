---
sidebar_position: 4
---

# Notebook Pipelines (Jupyter)

In addition to classic Python scripts (`main.py`), Fast-Flow supports **notebook pipelines**: a pipeline runs as a **Jupyter notebook** (`main.ipynb`). Cells run sequentially; per **code cell** you can configure **retries**. Logs and errors are shown **per cell** in the run detail view – including all retry attempts for failed cells.

---

## When to use notebook pipelines?

| Scenario | Recommendation |
|----------|------------|
| **Exploratory analysis, prototyping** | Notebook: cells runnable individually, output visible directly. |
| **Reproducible steps (ETL, reports)** | Notebook or script: both run in the container; notebook offers cell logs and cell retries. |
| **Strict automation, CI/CD** | Often `main.py`: one entry point, clear exit codes, less runtime overhead. |

Notebook pipelines work well when you want to work **step by step**, need **cell logs** and **cell retries**, or want to integrate existing notebooks into Fast-Flow.

---

## Structure of a notebook pipeline

A notebook pipeline is discovered when **`main.ipynb`** exists in the pipeline folder and **`"type": "notebook"`** is set in `pipeline.json`.

### Minimal directory structure

```
pipelines/meine_notebook_pipeline/
├── main.ipynb          # Entry point – executed cell by cell
├── pipeline.json      # type: "notebook", optional: cells, timeout, …
└── requirements.txt   # nbclient, nbformat, ipykernel (minimum)
```

### Required in `requirements.txt`

The notebook runner uses **nbclient** and **nbformat**. These (and a kernel) must be available in the pipeline environment:

```
nbclient
nbformat
ipykernel
```

Without these packages, starting the notebook pipeline fails.

---

## pipeline.json for notebook pipelines

### Set type

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "My notebook pipeline",
  "python_version": "3.12",
  "timeout": 120
}
```

- **`type`: `"notebook"`** – ensures Fast-Flow finds `main.ipynb` and uses the notebook runner (instead of `main.py`).
- All other fields (e.g. `timeout`, `python_version`, `description`, `tags`) work like script pipelines. See [pipeline.json reference](/docs/pipelines/referenz).

### Cell retries: the `cells` array

You can define per **code cell** how many times to retry on failure and how long to wait between attempts.

**Format:** `cells` is an **array**. The entry at index **0** applies to the **first code cell**, index **1** to the second, and so on. (Markdown cells do not count – only **code cells** are numbered.)

| Field per cell | Type | Description |
|----------------|-----|--------------|
| `retries` | Integer, optional | Number of **additional** attempts on failure (0 = no retry). |
| `delay_seconds` | Number, optional | Wait time in seconds between two attempts (default: 1). |

**Example:** 4 code cells; the third should have up to 3 retries with 1 second pause:

```json
{
  "type": "notebook",
  "enabled": true,
  "python_version": "3.12",
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 },
    { "retries": 1, "delay_seconds": 2 }
  ]
}
```

- Cell 0 (first code cell): 2 retries, 1 s pause.
- Cell 1: no retries.
- Cell 2: 3 retries, 1 s pause.
- Cell 3: 1 retry, 2 s pause.

If an entry for a cell is missing (or the array is shorter), that cell gets **0 retries** and **1 s** `delay_seconds`.

---

## Cell metadata (optional): override per cell

In addition to `pipeline.json`, you can set metadata **in each cell** of the notebook. If a cell has its own retry values, they **override** the values from `pipeline.json` for that cell.

**Where:** In Jupyter: select cell → edit metadata (or in the raw JSON view of the `.ipynb`).

**Format:** In **cell metadata**, an object **`fastflow`** with optional **`retries`** and **`delay_seconds`**:

```json
"metadata": {
  "fastflow": {
    "retries": 3,
    "delay_seconds": 2
  }
}
```

**Merge behavior:**

1. **Base:** Values from `pipeline.json` → `cells[code_cell_index]` (e.g. `retries: 2`, `delay_seconds: 1`).
2. **Override:** If the cell has `metadata.fastflow.retries` or `metadata.fastflow.delay_seconds`, **only those** fields are used for the cell.

This lets you set sensible defaults for all cells in `pipeline.json` and assign higher retries or longer pauses in the notebook for only a few "critical" cells.

---

## Execution flow: how is the notebook run?

1. Fast-Flow starts a container with the pipeline folder (including `main.ipynb`, `pipeline.json`, `requirements.txt`).
2. The **notebook runner** reads `main.ipynb` and `pipeline.json` (including `cells`).
3. **Code cells** are executed in order (markdown cells are skipped).
4. Per code cell:
   - **Retries** and **delay_seconds** come from `pipeline.json` → `cells[code_cell_index]`, overridden by the cell's `metadata.fastflow`.
   - On **failure** (exception, timeout, kernel crash): wait `delay_seconds`, then retry until `retries` are exhausted.
   - If errors persist after all attempts: run ends with **FAILED**; the cell is considered failed.
5. **Logs** (stdout, stderr, cell output) are collected per cell and shown in the run detail view.

:::important
**Pipeline-level retries** ("restart entire run") are **disabled** for notebook pipelines. Only **cell retries** within a run apply. This avoids duplicate retry logic and shows all attempts per cell in one place.
:::

---

## Logs and run detail view

### Cell logs

- In the **run detail view** (tab **Logs**), notebook pipelines show output **grouped by cell**.
- Per cell: **stdout**, **stderr**, optional **images** (display_data).
- **Status per cell:** RUNNING, SUCCESS, RETRYING, FAILED.

### Failed cell: all attempts visible

For a cell with retries, **all failed attempts** are collected in **stderr**:

- **Retry attempt 1 failed:** &lt;error message&gt;
- **Retry attempt 2 failed:** &lt;error message&gt;
- …
- **Finally failed**

This lets you see exactly what went wrong on each attempt in a failed cell – without searching logs across multiple runs.

### Download log file

The **"Download Logs"** button downloads the **entire run log file** (text). It includes readable cell summaries (start, success, retry, failed). On errors (e.g. log file missing), a clear error message appears in the UI.

---

## Example: complete notebook pipeline

### Directory

```
pipelines/notebook_example/
├── main.ipynb
├── pipeline.json
└── requirements.txt
```

### `pipeline.json`

```json
{
  "type": "notebook",
  "enabled": true,
  "description": "Example notebook with cell retries",
  "tags": ["notebook", "example"],
  "python_version": "3.12",
  "timeout": 120,
  "cells": [
    { "retries": 2, "delay_seconds": 1 },
    { "retries": 0 },
    { "retries": 3, "delay_seconds": 1 },
    { "retries": 1, "delay_seconds": 2 }
  ]
}
```

### `requirements.txt`

```
nbclient
nbformat
ipykernel
```

### `main.ipynb` (content)

- Cell 0 (Markdown): description.
- Cell 1 (Code): `import sys`; `print('Python:', sys.version)` – 2 retries from `cells[0]`.
- Cell 2 (Code): simple calculation – no retries from `cells[1]`.
- Cell 3 (Code): e.g. `raise Exception('Test error')` – 3 retries from `cells[2]`; after 4 attempts the cell (and run) ends with FAILED; all 4 error messages appear in cell stderr.
- Cell 4 (Code): closing text – 1 retry from `cells[3]`.

This lets you observe cell retry behavior and the display of all attempts in the UI directly.

---

## Local testing

Run the notebook locally (e.g. in Jupyter or VS Code): as usual.  
The **retry logic** and **structured logs** (FASTFLOW_CELL_*) run only in the Fast-Flow container; locally you see "normal" notebook behavior.

For a quick check that the environment is correct:

```bash
cd pipelines/notebook_example
uv pip install -r requirements.txt
jupyter nbconvert --to notebook --execute main.ipynb
```

If that completes, the notebook should also run in the orchestrator – provided the same Python version and dependencies are used (note `python_version` in `pipeline.json`).

---

## Quick reference: what to configure where?

| Goal | Where |
|------|-----|
| **Recognize pipeline as notebook** | `pipeline.json`: `"type": "notebook"` + `main.ipynb` in folder |
| **Retries per cell (default)** | `pipeline.json`: `"cells": [ { "retries", "delay_seconds" }, … ]` |
| **Override retries for one cell** | In cell: cell metadata → `fastflow`: `retries`, `delay_seconds` |
| **Timeout, Python version, description** | Like script pipelines in `pipeline.json` |
| **Logs per cell + all retry attempts** | Run detail → Logs tab (cells grouped); stderr of failed cell contains all attempts |
| **Full log file** | Run detail → Logs tab → "Download Logs" button |

---

## See also

- [pipeline.json reference](/docs/pipelines/referenz) – fields `type` and `cells`, all other options
- [Pipelines – Overview](/docs/pipelines/uebersicht) – basic structure, script vs. notebook
- [Advanced Pipelines](/docs/pipelines/erweiterte-pipelines) – retries, timeout, webhooks (pipeline level; for notebooks, cell retries apply as above)
