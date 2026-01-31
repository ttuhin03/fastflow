---
sidebar_position: 12
---

# Konzepte & Glossar

Kurze Erklärung der zentralen Begriffe in Fast-Flow – für alle, die unter die Haube schauen wollen.

## Runner-Cache-Prinzip

Fast-Flow nutzt **keine** eigenen Docker-Images pro Pipeline und keine shared Worker-Umgebung. Stattdessen:

- **Runner:** Jeder Run startet einen **ephemeren** Docker-Container („Disposable Worker“). Nach dem Lauf wird der Container entfernt.
- **Cache:** Der **uv-Cache** (Pakete) und **uv-Python-Installationen** (z.B. 3.11, 3.12) liegen als **persistente Volumes** auf dem Host. Sie werden in die Container **gemountet**, nicht bei jedem Run neu gebaut.
- **Effekt:** Kein `docker build`, keine Dependency-Hölle. Dependencies sind nach dem ersten Run in Millisekunden verfügbar (Hardlinks aus dem Cache).

## uv (Paketmanager)

[uv](https://github.com/astral-sh/uv) ist ein extrem schneller Python-Paketmanager (Rust). Fast-Flow nutzt ihn im Pipeline-Container:

- **Installation:** `uv run --python {version} --with-requirements requirements.txt main.py` – Pakete werden bei Bedarf installiert und im gemeinsamen Cache abgelegt.
- **Vorteil:** Deutlich schneller als `pip`, deterministisch, gleiche Umgebung lokal und im Orchestrator möglich.

## JIT (Just-In-Time) Environment

**Just-In-Time** bedeutet: Die Laufzeitumgebung (Python-Version + Dependencies) wird **zur Laufzeit** bereitgestellt, nicht beim Image-Build.

- Beim **ersten** Run einer Pipeline können Python-Installation und Pakete kurz laden.
- **Preheating** (`UV_PRE_HEAT=true`): Beim Start und nach Git-Sync werden benötigte Python-Versionen und Dependencies vorinstalliert – der erste Run ist dann oft so schnell wie die folgenden.

## Disposable Worker

Jede Pipeline-Ausführung läuft in einem **eigenen, frischen** Container. Nach dem Lauf wird der Container mit `--rm` entfernt. Es gibt keine langlebigen Worker-Prozesse, die sich Zustand oder Dependencies teilen – dadurch maximale **Isolation** und **Sauberkeit**.

## Docker Socket Proxy

Der Orchestrator spricht **nicht** direkt mit dem Docker-Socket (`/var/run/docker.sock`), sondern über einen [Docker-Socket-Proxy](https://github.com/Tecnativa/docker-socket-proxy) (`tecnativa/docker-socket-proxy`). Der Proxy erlaubt nur konfigurierte Operationen (z.B. Container erstellen, Logs, Stats) und blockiert den Rest – so bleibt der Root-Zugriff auf den Host eingeschränkt.

## Git als Source of Truth

Es gibt **keinen** manuellen Upload von Pipelines und **keinen** Pipeline-spezifischen Image-Build. Die einzige Quelle für Pipeline-Code und Konfiguration ist dein **Git-Repository**. Push → Sync (Webhook oder Auto-Sync) → Code ist im Orchestrator verfügbar. Rollback = `git revert`.

## Pipeline-Name

Der **Pipeline-Name** ist immer der **Verzeichnisname** unter `PIPELINES_DIR` (z.B. `pipelines/data_sync/` → Name `data_sync`). Er erscheint in der UI und in der API.

## Zero-Config Discovery

Pipelines müssen **nicht** in der Datenbank oder UI angelegt werden. Sobald ein Ordner mit `main.py` (oder `main.ipynb` + `"type": "notebook"`) unter `PIPELINES_DIR` existiert (lokal oder nach Git-Sync), wird er automatisch als Pipeline erkannt.

## Nächste Schritte

- [**Architektur**](/docs/architektur) – Runner-Cache und Container-Lifecycle im Detail
- [**Pipelines – Übersicht**](/docs/pipelines/uebersicht) – Struktur und Erkennung
- [**Docker Socket Proxy**](/docs/deployment/DOCKER_PROXY) – Sicherheitsarchitektur
