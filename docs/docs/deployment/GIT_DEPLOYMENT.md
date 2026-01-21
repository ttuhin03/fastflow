---
sidebar_position: 2
---

# Git-Native Deployment

**Push to Deploy, No Build Needed.**

In Fast-Flow ist dein **Git-Repository die einzige Wahrheit**. Es gibt keinen "Upload"-Button und keinen manuellen Build-Schritt.

## Die alte Welt (Airflow, Dagster, Mage)

- **Image-Hell:** Jede Code-Änderung erfordert oft einen neuen Docker-Build (5–10 Minuten).
- **Sidecar-Chaos:** Git-Sync-Sidecars oder S3-Buckets, um DAGs zu verteilen.
- **Version-Gap:** UI und Git-Repository sind oft nicht im Einklang.

## Der Fast-Flow Weg: "Source of Truth"

- **Zero-Build Deployment:** Code-Änderungen werden per Webhook oder manuellem Sync gezogen. Dank uv-JIT ist die neue Version sofort lauffähig.
- **Vollständige Rückverfolgbarkeit:** `pipeline.json` und `requirements.txt` liegen im Git – wer hat wann Limits oder Dependencies geändert, steht im Git-Log.
- **Atomic Sync:** Pipelines lesen keine "halben" Dateien; Änderungen werden atomar eingespielt.

| Feature | Traditionelle Tools | Fast-Flow |
|---------|---------------------|-----------|
| **Deployment-Speed** | Minuten (Build & Push) | Sekunden (Git Pull) |
| **Versionierung** | Oft nur Code | Code, Deps & Ressourcen-Limits |
| **Rollback** | Image-Rollback (komplex) | `git revert` (einfach) |
| **Wahrheit** | UI vs. Git vs. Image | **Git ist Gesetz** |

## Ablauf

1. **Entwickeln:** Python-Skript lokal schreiben und testen.
2. **Pushen:** `git push origin main`
3. **Syncen:** Orchestrator holt Änderungen per Webhook oder Auto-Sync.
4. **Laufen:** Pipeline startet mit dem neuen Code – ohne Docker-Builds.

> "Wir haben das Deployment so langweilig wie möglich gemacht, damit du dich auf das Spannende konzentrieren kannst: Deinen Code."

## Konfiguration

Relevante Variablen (siehe [Konfiguration](/docs/deployment/CONFIGURATION)):

- `PIPELINES_DIR` – Pfad zum (geklonten) Pipeline-Repo
- `GIT_BRANCH` – Branch für den Sync (z.B. `main`)
- `AUTO_SYNC_ENABLED` / `AUTO_SYNC_INTERVAL` – automatischer Sync
- `UV_PRE_HEAT` – Dependencies beim Sync vorinstallieren
- GitHub App / Git-URL für private Repos

## Siehe auch

- [Pipelines – Übersicht](/docs/pipelines/uebersicht)
- [Architektur](/docs/architektur) – Runner-Cache, Zero-Build
- [Konfiguration](/docs/deployment/CONFIGURATION)
