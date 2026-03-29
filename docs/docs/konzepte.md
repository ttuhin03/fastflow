---
sidebar_position: 12
---

# Konzepte & Glossar

Kurze Erklärung der zentralen Begriffe in Fast-Flow – für alle, die unter die Haube schauen wollen.

## Runner-Cache-Prinzip

Fast-Flow nutzt **keine** eigenen Docker-Images pro Pipeline und keine shared Worker-Umgebung. Stattdessen:

- **Runner:** Jeder Run startet eine **ephemere** Isolation – entweder ein Docker-Container oder ein **Kubernetes-Job-Pod** („Disposable Worker“), gesteuert über `PIPELINE_EXECUTOR`. Nach dem Lauf wird die Sandbox entfernt bzw. beendet.
- **Cache:** Der **uv-Cache** (Pakete) und **uv-Python-Installationen** (z.B. 3.11, 3.12) liegen **persistent** (Host-Volumes bei Docker Compose, **PVCs** bei Kubernetes). Sie werden in den Worker **gemountet**, nicht bei jedem Run neu gebaut.
- **Effekt:** Kein Image-Build pro Pipeline, keine Dependency-Hölle. Dependencies sind nach dem ersten Run in Millisekunden verfügbar (Hardlinks bzw. Cache aus dem Volume).

## uv (Paketmanager)

[uv](https://github.com/astral-sh/uv) ist ein extrem schneller Python-Paketmanager (Rust). Fast-Flow nutzt ihn im Pipeline-Container:

- **Installation:** `uv run --python {version} --with-requirements requirements.txt main.py` – Pakete werden bei Bedarf installiert und im gemeinsamen Cache abgelegt.
- **Vorteil:** Deutlich schneller als `pip`, deterministisch, gleiche Umgebung lokal und im Orchestrator möglich.

## JIT (Just-In-Time) Environment

**Just-In-Time** bedeutet: Die Laufzeitumgebung (Python-Version + Dependencies) wird **zur Laufzeit** bereitgestellt, nicht beim Image-Build.

- Beim **ersten** Run einer Pipeline können Python-Installation und Pakete kurz laden.
- **Preheating** (`UV_PRE_HEAT=true`): Beim Start und nach Git-Sync werden benötigte Python-Versionen und Dependencies vorinstalliert – der erste Run ist dann oft so schnell wie die folgenden.

## Disposable Worker

Jede Pipeline-Ausführung läuft in einem **eigenen, frischen** Worker – Docker-Container oder K8s-Job. Nach dem Lauf wird die Umgebung entfernt bzw. der Job beendet. Es gibt keine langlebigen Worker-Prozesse, die sich Zustand oder Dependencies teilen – dadurch maximale **Isolation** und **Sauberkeit**.

## Docker Socket Proxy

Nur im Modus **`PIPELINE_EXECUTOR=docker`**: Der Orchestrator spricht **nicht** direkt mit dem Docker-Socket (`/var/run/docker.sock`), sondern über einen [Docker-Socket-Proxy](https://github.com/Tecnativa/docker-socket-proxy) (`tecnativa/docker-socket-proxy`). Der Proxy erlaubt nur konfigurierte Operationen (z.B. Container erstellen, Logs, Stats) und blockiert den Rest. Bei **`kubernetes`** entfällt dieser Pfad; stattdessen spricht die Anwendung mit der **Kubernetes-API** (Jobs, Pods, Logs).

## Git als Source of Truth

Es gibt **keinen** manuellen Upload von Pipelines und **keinen** Pipeline-spezifischen Image-Build. Die einzige Quelle für Pipeline-Code und Konfiguration ist dein **Git-Repository**. Push → Sync (Webhook oder Auto-Sync) → Code ist im Orchestrator verfügbar. Rollback = `git revert`.

## Pipeline-Name

Der **Pipeline-Name** ist immer der **Verzeichnisname** unter `PIPELINES_DIR` (z.B. `pipelines/data_sync/` → Name `data_sync`). Er erscheint in der UI und in der API.

## Zero-Config Discovery

Pipelines müssen **nicht** in der Datenbank oder UI angelegt werden. Sobald ein Ordner mit `main.py` (oder `main.ipynb` + `"type": "notebook"`) unter `PIPELINES_DIR` existiert (lokal oder nach Git-Sync), wird er automatisch als Pipeline erkannt.

## Nächste Schritte

- [**Architektur**](/docs/architektur) – Runner-Cache und Container-Lifecycle im Detail
- [**Pipelines – Übersicht**](/docs/pipelines/uebersicht) – Struktur und Erkennung
- [**Docker Socket Proxy**](/docs/deployment/DOCKER_PROXY) – Sicherheitsarchitektur (Docker-Executor)
- [**Kubernetes Deployment**](/docs/deployment/K8S) – Jobs-Executor
