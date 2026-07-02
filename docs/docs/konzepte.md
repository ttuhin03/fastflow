---
sidebar_position: 12
---

# Concepts & Glossary

Brief explanation of the central terms in Fast-Flow – for everyone who wants to look under the hood.

## Runner cache principle

Fast-Flow does **not** use its own Docker images per pipeline or a shared worker environment. Instead:

- **Runner:** Each run starts **ephemeral** isolation – either a Docker container or a **Kubernetes Job Pod** ("Disposable Worker"), controlled via `PIPELINE_EXECUTOR`. After the run, the sandbox is removed or terminated.
- **Cache:** The **uv cache** (packages) and **uv Python installations** (e.g. 3.11, 3.12) are **persistent** (host volumes with Docker Compose, **PVCs** with Kubernetes). They are **mounted** into the worker, not rebuilt on every run.
- **Effect:** No image build per pipeline, no dependency hell. Dependencies are available in milliseconds after the first run (hardlinks or cache from the volume).

## uv (package manager)

[uv](https://github.com/astral-sh/uv) is an extremely fast Python package manager (Rust). Fast-Flow uses it in the pipeline container:

- **Installation:** `uv run --python {version} --with-requirements requirements.txt main.py` – packages are installed as needed and stored in the shared cache.
- **Benefit:** Significantly faster than `pip`, deterministic, same environment possible locally and in the orchestrator.

## JIT (Just-In-Time) environment

**Just-In-Time** means: The runtime environment (Python version + dependencies) is provided **at runtime**, not during image build.

- On the **first** run of a pipeline, Python installation and packages may load briefly.
- **Preheating** (`UV_PRE_HEAT=true`): On startup and after Git sync, required Python versions and dependencies are pre-installed – the first run is then often as fast as subsequent ones.

## Disposable Worker

Each pipeline execution runs in its **own, fresh** worker – Docker container or K8s Job. After the run, the environment is removed or the Job is terminated. There are no long-lived worker processes sharing state or dependencies – maximum **isolation** and **cleanliness**.

## Docker Socket Proxy

Only in **`PIPELINE_EXECUTOR=docker`** mode: The orchestrator does **not** talk directly to the Docker socket (`/var/run/docker.sock`), but via a [Docker Socket Proxy](https://github.com/Tecnativa/docker-socket-proxy) (`tecnativa/docker-socket-proxy`). The proxy only allows configured operations (e.g. create container, logs, stats) and blocks the rest. With **`kubernetes`**, this path is omitted; instead, the application talks to the **Kubernetes API** (Jobs, Pods, logs).

## Git as source of truth

There is **no** manual upload of pipelines and **no** pipeline-specific image build. The only source for pipeline code and configuration is your **Git repository**. Push → sync (auto-sync or manual sync) → code is available in the orchestrator. Rollback = `git revert`.

## Pipeline name

The **pipeline name** is always the **directory name** under `PIPELINES_DIR` (e.g. `pipelines/data_sync/` → name `data_sync`). It appears in the UI and in the API.

## Zero-config discovery

Pipelines do **not** need to be created in the database or UI. As soon as a folder with `main.py` (or `main.ipynb` + `"type": "notebook"`) exists under `PIPELINES_DIR` (locally or after Git sync), it is automatically recognized as a pipeline.

## Next steps

- [**Architecture**](/docs/architektur) – Runner cache and container lifecycle in detail
- [**Pipelines – Overview**](/docs/pipelines/uebersicht) – Structure and discovery
- [**Docker Socket Proxy**](/docs/deployment/DOCKER_PROXY) – Security architecture (Docker executor)
- [**Kubernetes Deployment**](/docs/deployment/K8S) – Jobs executor
