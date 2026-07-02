---
sidebar_position: 2
---

# Git-Native Deployment

**Push to Deploy, No Build Needed.**

In Fast-Flow, your **Git repository is the single source of truth**. There is no "Upload" button and no manual build step.

## The Old World (Airflow, Dagster, Mage)

- **Image hell:** Every code change often requires a new Docker build (5–10 minutes).
- **Sidecar chaos:** Git-sync sidecars or S3 buckets to distribute DAGs.
- **Version gap:** UI and Git repository are often out of sync.

## The Fast-Flow Way: "Source of Truth"

- **Zero-build deployment:** Code changes are pulled via webhook or manual sync. Thanks to uv JIT, the new version is immediately runnable.
- **Full traceability:** `pipeline.json` and `requirements.txt` live in Git—who changed limits, dependencies, or the **per-pipeline selectable** Python version and when is recorded in the Git log.
- **Atomic sync:** Pipelines never read "half" files; changes are applied atomically.

| Feature | Traditional Tools | Fast-Flow |
|---------|-------------------|-----------|
| **Deployment speed** | Minutes (build & push) | Seconds (Git pull) |
| **Versioning** | Often code only | Code, deps & resource limits |
| **Rollback** | Image rollback (complex) | `git revert` (simple) |
| **Source of truth** | UI vs. Git vs. image | **Git is law** |

## Workflow

1. **Develop:** Write and test Python scripts locally.
2. **Push:** `git push origin main`
3. **Sync:** Orchestrator fetches changes via webhook or auto-sync.
4. **Run:** Pipeline starts with the new code—without Docker builds.

> "We made deployment as boring as possible so you can focus on what's exciting: your code."

## Configuration

Relevant variables (see [Configuration](/docs/deployment/CONFIGURATION)):

- `PIPELINES_DIR` – path to the (cloned) pipeline repo
- `GIT_BRANCH` – branch for sync (e.g. `main`)
- `AUTO_SYNC_ENABLED` / `AUTO_SYNC_INTERVAL` – automatic sync
- `UV_PRE_HEAT` – preinstall dependencies during sync
- GitHub App / Git URL for private repos

## See Also

- [Pipelines – Overview](/docs/pipelines/uebersicht)
- [Architecture](/docs/architektur) – runner cache, zero-build
- [Configuration](/docs/deployment/CONFIGURATION)
