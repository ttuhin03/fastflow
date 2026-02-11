---
sidebar_position: 9
---

# Kubernetes Deployment

Fast-Flow kann in einem lokalen oder produktiven Kubernetes-Cluster betrieben werden. Die API ist K8s-ready mit Liveness- (`/health`) und Readiness-Probes (`/ready`).

## Voraussetzungen

- **kubectl** installiert
- **Kubernetes-Cluster** (eine der folgenden Optionen):

  | Option | Empfehlung | Hinweis |
  |--------|------------|---------|
  | **kubeadm** | Produktion | Reale oder VM-Nodes mit Docker auf dem Host |
  | **Docker Desktop** | Lokale Entwicklung | Einstellungen → „Enable Kubernetes“ aktivieren |
  | **Kind** (Kubernetes in Docker) | Leichtgewichtig | Erfordert [extraMounts](#kind-docker-socket) für Docker-Socket |
  | **Minikube** | Feature-reich | Mit `--driver=docker` für Docker-Socket-Zugriff |

- **Docker** auf dem Host/Node (für Pipeline-Runs; der Orchestrator nutzt den Docker-Daemon via Socket)

## Kind: Docker-Socket freigeben

Der Orchestrator benötigt Zugriff auf den Docker-Daemon für Pipeline-Runs. Bei Kind müssen Sie den Host-Docker-Socket in die Nodes mounten.

Die Datei `kind-config.yaml` liegt im Projekt-Root. Cluster erstellen:

```bash
kind create cluster --config kind-config.yaml
```

## Manuelles Deployment

### 1. Secrets

**Standard:** `k8s/secrets.yaml` enthält alle Werte (inkl. Dev-Dummy für OAuth). Einfach `kubectl apply -f k8s/` – kein manuelles Secret nötig.

**Produktion:** Werte in `k8s/secrets.yaml` ersetzen (ENCRYPTION_KEY, JWT_SECRET_KEY, echte OAuth-Credentials). Oder eigenes Secret verwenden und `secrets.yaml` nicht anwenden.

### 2. Image bauen und laden (Kind/Minikube)

```bash
docker build -t fastflow-orchestrator:latest .
```

**Kind:**

```bash
kind load docker-image fastflow-orchestrator:latest
```

**Minikube:**

```bash
eval $(minikube docker-env)
docker build -t fastflow-orchestrator:latest .
```

### 3. Manifests anwenden

```bash
kubectl apply -f k8s/
```

PostgreSQL wird mit deployt (Standard). Der Orchestrator wartet per Init-Container auf die DB, bevor er startet.

### 4. Zugriff

**Option A – NodePort (z. B. Port 30080):**

- Docker Desktop / Minikube: `http://localhost:30080`
- Kind: `kubectl get nodes -o wide` → Node-IP, dann `http://<node-ip>:30080`

**Option B – Port-Forward:**

```bash
kubectl port-forward service/fastflow-orchestrator 8000:80
```

Dann: `http://localhost:8000`

### 5. BASE_URL anpassen

Je nach Zugriffsmethode `BASE_URL` und `FRONTEND_URL` in der ConfigMap setzen:

- NodePort 30080: `http://localhost:30080` (oder Ihre tatsächliche URL)
- Port-Forward: `http://localhost:8000`

```bash
kubectl edit configmap fastflow-config
```

Danach Pod neu starten: `kubectl rollout restart deployment/fastflow-orchestrator`

### 6. Wichtige URLs

| URL | Beschreibung |
|-----|--------------|
| `/` | React-Frontend (Dashboard) |
| `/doku` | Docusaurus-Dokumentation |
| `/docs` | FastAPI Swagger (API-Doku) |
| `/redoc` | FastAPI ReDoc |

### 7. Pipelines: hostPath und DEV vs. PROD

Pipelines werden per **hostPath** (`/opt/fastflow-pipelines`) bereitgestellt, damit Worker-Container den gleichen Pfad auf dem Node mounten können.

- **`PIPELINES_HOST_DIR`** (ConfigMap): Muss mit dem hostPath übereinstimmen (`/opt/fastflow-pipelines`). Ohne diese Variable funktionieren Pipeline-Runs nicht (404 auf `/app/main.py`).

- **`ENVIRONMENT`** steuert die Befüllung:
  - **`development`**: Beim Start werden Beispiel-Pipelines aus dem Image nach `/app/pipelines` kopiert, falls das Verzeichnis leer ist.
  - **`production`**: Kein Kopieren. Pipelines kommen ausschließlich über [Git-Sync](./GIT_DEPLOYMENT.md) oder manuelles Befüllen des hostPath.

Für Produktion in der ConfigMap setzen:

```yaml
ENVIRONMENT: "production"
PIPELINES_HOST_DIR: "/opt/fastflow-pipelines"
```

## Skaffold (Dev-Workflow)

Mit [Skaffold](https://skaffold.dev/) wird bei Codeänderungen automatisch gebaut, deployed und Port-Forward eingerichtet.

```bash
skaffold dev
```

Skaffold übernimmt:

- Image-Build
- Deploy in den Cluster (inkl. `kind load` bei Kind)
- Port-Forward auf `localhost:8000`
- Log-Streaming

## Prüfen

```bash
kubectl get pods
kubectl logs -f deployment/fastflow-orchestrator -c orchestrator
```

Health-Checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## Datenbank

**Standard:** PostgreSQL ist enthalten (`k8s/postgres.yaml`). Der Orchestrator verbindet sich automatisch via `DATABASE_URL` aus dem `postgres-secret`.

**SQLite statt PostgreSQL:** Wenn Sie `k8s/postgres.yaml` nicht anwenden, nutzt der Orchestrator SQLite im `fastflow-data-pvc` (kein `postgres-secret` → keine `DATABASE_URL`).

**PostgreSQL-Passwort ändern (Produktion):** In `k8s/postgres.yaml` im Secret `POSTGRES_PASSWORD` und `DATABASE_URL` anpassen.

## Architektur

- **Orchestrator**: FastAPI + React-Frontend + Docusaurus-Doku, Port 8000
- **PostgreSQL** (optional): Datenbank-Service auf Port 5432
- **Docker-Proxy** (Sidecar): Sicherer Zugriff auf den Host-Docker-Socket für Pipeline-Runs
- **Volumes**:
  - **PVCs**: `fastflow-data-pvc` (UV-Cache, ggf. SQLite), `fastflow-logs-pvc`, `postgres-pvc` (bei PostgreSQL)
  - **hostPath** (Pipelines): `/opt/fastflow-pipelines` – Worker-Container müssen denselben Pfad auf dem Node mounten können

Der Docker-Socket-Zugriff funktioniert nur, wenn die Cluster-Nodes Zugriff auf einen Docker-Daemon haben (kubeadm, Kind mit extraMounts, Minikube mit docker driver, Docker Desktop).

## Siehe auch

- [Production-Checkliste](./PRODUCTION_CHECKLIST.md)
- [Konfiguration](./CONFIGURATION.md)
- [Docker Socket Proxy](./DOCKER_PROXY.md)
