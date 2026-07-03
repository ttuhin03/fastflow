---
sidebar_position: 11
---

# Security Rollout (Non-Root + readOnlyRootFilesystem)

Diese Anleitung beschreibt, was nach dem Security-Update für **Production** zu tun ist: Images bauen, Manifests anwenden, UV-Cache migrieren, prüfen und bei Problemen zurückrollen.

Betrifft:

- **Orchestrator** (K8s Deployment / Docker Compose)
- **Pipeline-Worker** (K8s Jobs / Docker-Container)
- **UV-Cache-Pfade** auf Kubernetes (Orchestrator ↔ Worker abgestimmt)

Siehe auch: [Kubernetes Deployment](K8S.md), [Configuration](CONFIGURATION.md), [Production Checklist](PRODUCTION_CHECKLIST.md).

---

## Was sich geändert hat (Kurzüberblick)

| Bereich | Vorher | Nachher |
|--------|--------|---------|
| Orchestrator UID | teils root (Image) | **UID/GID 1001** (`fastflow`) |
| Orchestrator Root-FS | beschreibbar | **`readOnlyRootFilesystem: true`** + `emptyDir` für `/tmp` |
| Pipeline-Jobs | root / kein readOnly | **UID 1001**, **`readOnlyRootFilesystem`**, `emptyDir` `/tmp` |
| Worker UV-Cache (K8s) | `/root/.cache/uv` | **`/cache/uv`** (PVC-Subpath `uv_cache`) |
| Orchestrator UV-Cache (K8s) | `/app/data/uv_cache` (anderes PVC) | **`/shared/uv_cache`** (gleiches PVC wie Jobs) |
| Worker-Image Default | `ghcr.io/astral-sh/uv:…` | **`fastflow-worker:latest`** (`Dockerfile.worker`) |
| Docker-Worker | root, rw root-fs | **UID 1001**, **`read_only: true`**, `tmpfs` `/tmp` |
| Seccomp | nicht gesetzt | **`RuntimeDefault`** (Pod/Container) |
| Worker-Env | — | **`HOME=/tmp`**, **`PYTHONDONTWRITEBYTECODE=1`** |

Technische Konstanten und Security-Builder: `app/executor/worker_runtime.py`  
Automatisierte Checks: `tests/test_worker_security.py`

---

## Checkliste vor dem Rollout

- [ ] Neues **Orchestrator-Image** bauen (`Dockerfile`)
- [ ] Neues **Worker-Image** bauen (`Dockerfile.worker`) — **Pflicht** für Notebook-Pipelines (`/runner`) und Non-Root
- [ ] In **ConfigMap** / `.env`: `WORKER_BASE_IMAGE` auf euer Registry-Image setzen (nicht das alte Astral-`uv`-Image)
- [ ] K8s: **`kubectl apply`** für geänderte Manifests (`deployment.yaml`, ggf. `postgres.yaml`)
- [ ] K8s: **UV-Cache migrieren** (falls bisher unter `/app/data/uv_cache` auf `fastflow-pvc`)
- [ ] **`ENVIRONMENT=production`** in ConfigMap (wenn Prod-Betrieb)
- [ ] Smoke-Test: Orchestrator startet, eine Pipeline läuft durch
- [ ] Optional: `pytest tests/test_worker_security.py` in CI

---

## 1. Images bauen und veröffentlichen

### Lokal / Minikube

```bash
# Im Repo-Root
docker build -t fastflow-orchestrator:latest .
docker build -f Dockerfile.worker -t fastflow-worker:latest .

# Minikube: Images in die Minikube-Docker-Engine laden
eval $(minikube docker-env)
docker build -t fastflow-orchestrator:latest .
docker build -f Dockerfile.worker -t fastflow-worker:latest .
```

### Production (Registry)

```bash
export REGISTRY=ghcr.io/<owner>   # anpassen
export TAG=v0.8.0                 # euer Release-Tag

docker build -t $REGISTRY/fastflow-orchestrator:$TAG .
docker build -f Dockerfile.worker -t $REGISTRY/fastflow-worker:$TAG .

docker push $REGISTRY/fastflow-orchestrator:$TAG
docker push $REGISTRY/fastflow-worker:$TAG
```

In **`k8s/deployment.yaml`** das Orchestrator-Image anpassen:

```yaml
image: ghcr.io/<owner>/fastflow-orchestrator:v0.8.0
```

In **`k8s/configmap.yaml`** (oder per Patch):

```yaml
WORKER_BASE_IMAGE: "ghcr.io/<owner>/fastflow-worker:v0.8.0"
```

---

## 2. Kubernetes Rollout

### Manifest-Reihenfolge

Wenn ihr das komplette Setup neu aufsetzt (wie in [K8S.md](K8S.md)):

```bash
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/postgres.yaml          # optional
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/rbac-kubernetes-executor.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Bei **Update** eines laufenden Clusters reicht meist:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/postgres.yaml          # falls Postgres genutzt
kubectl rollout restart deployment/fastflow-orchestrator
kubectl rollout status deployment/fastflow-orchestrator
```

### Wichtige Env-Variablen im Deployment

Diese Werte sind im Manifest bereits gesetzt — nach manuellen Änderungen prüfen:

| Variable | Wert (K8s) | Bedeutung |
|----------|------------|-----------|
| `UV_CACHE_DIR` | `/shared/uv_cache` | Pre-Heating-Cache (Cache-PVC) |
| `UV_PYTHON_INSTALL_DIR` | `/shared/uv_python` | `uv python install` (Cache-PVC) |
| `KUBERNETES_SHARED_CACHE_MOUNT_PATH` | `/shared` | Mount des Cache-PVC im Orchestrator |
| `TMPDIR` | `/tmp` | Writable via `emptyDir` |
| `PYTHONDONTWRITEBYTECODE` | `1` | Keine `.pyc` ins read-only `/app` |

Worker-Jobs mounten dieselben PVC-Subpaths:

| Orchestrator (unter `/shared`) | Worker-Job (Mount) | PVC-Subpath |
|-------------------------------|-------------------|-------------|
| `/shared/uv_cache` | `/cache/uv` | `uv_cache` |
| `/shared/uv_python` | `/cache/uv_python` | `uv_python` |
| `pipeline_runs/<run-id>` | `/app` | `pipeline_runs/<run-id>` |

---

## 3. UV-Cache migrieren (nur bei bestehendem K8s-Deployment)

Wenn ihr **vorher** Pre-Heating auf `fastflow-pvc` unter `/app/data/uv_cache` hattet, liegt der Cache dort noch — der Orchestrator liest ihn **nicht mehr**.

**Option A — Cache kopieren (schneller erster Run nach Upgrade):**

```bash
# Pod-Name ermitteln
POD=$(kubectl get pod -l app=fastflow-orchestrator -o jsonpath='{.items[0].metadata.name}')

# Prüfen ob alter Cache existiert
kubectl exec "$POD" -c orchestrator -- ls -la /app/data/uv_cache 2>/dev/null || true

# Kopieren auf das shared Cache-Volume (einmalig)
kubectl exec "$POD" -c orchestrator -- sh -c '
  mkdir -p /shared/uv_cache /shared/uv_python
  if [ -d /app/data/uv_cache ] && [ "$(ls -A /app/data/uv_cache 2>/dev/null)" ]; then
    cp -a /app/data/uv_cache/. /shared/uv_cache/
  fi
  if [ -d /app/data/uv_python ] && [ "$(ls -A /app/data/uv_python 2>/dev/null)" ]; then
    cp -a /app/data/uv_python/. /shared/uv_python/
  fi
'
```

**Option B — Neu aufwärmen:** Git-Sync / Pre-Heating erneut laufen lassen (dauert länger, aber einfacher).

---

## 4. Docker Compose Rollout

```bash
docker build -t fastflow-orchestrator:latest .
docker build -f Dockerfile.worker -t fastflow-worker:latest .

# .env: WORKER_BASE_IMAGE=fastflow-worker:latest (siehe .env.example)

docker compose down
docker compose up -d --build
```

Der Orchestrator läuft mit `read_only: true` und `tmpfs: [/tmp]`.  
UV-Cache bleibt unter **`/app/data/uv_cache`** (Host-Volume) — für Docker ist **keine** Cache-Migration nötig, Orchestrator und Worker teilen sich dieselben Host-Pfade.

Worker-Container starten mit `user: 1001:1001`, `read_only: true`, beschreibbare Bind-Mounts für `/app`, `/cache/uv`, `/cache/uv_python`.

---

## 5. Verifikation (Smoke-Tests)

### 5.1 Orchestrator gesund

```bash
# K8s
kubectl get pods -l app=fastflow-orchestrator
kubectl logs deploy/fastflow-orchestrator -c orchestrator --tail=50

curl -sf http://<host>:<port>/health
curl -sf http://<host>:<port>/ready
```

Pod sollte **Running** sein, Init-Container `wait-for-postgres` **Completed** (oder übersprungen bei SQLite).

### 5.2 Security-Context prüfen

```bash
kubectl get pod -l app=fastflow-orchestrator -o jsonpath='{.items[0].spec.securityContext}' | jq .
kubectl get pod -l app=fastflow-orchestrator -o jsonpath='{.items[0].spec.containers[0].securityContext}' | jq .
```

Erwartet u.a.: `runAsUser: 1001`, `readOnlyRootFilesystem: true`, `seccompProfile.type: RuntimeDefault`.

### 5.3 Pipeline-Job starten und Job-Pod prüfen

Eine Pipeline manuell in der UI starten, dann:

```bash
kubectl get jobs -l app=fastflow-runner
kubectl get pods -l app=fastflow-runner

JOB_POD=$(kubectl get pods -l app=fastflow-runner --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl get pod "$JOB_POD" -o jsonpath='{.spec.containers[0].securityContext}' | jq .
kubectl logs "$JOB_POD" -c pipeline
```

Erwartet: Job **Completed**, Logs ohne Permission-Denied auf `/tmp` oder `/cache`.

### 5.4 Pre-Heating / UV-Cache

```bash
kubectl exec deploy/fastflow-orchestrator -c orchestrator -- ls -la /shared/uv_cache
kubectl exec deploy/fastflow-orchestrator -c orchestrator -- ls -la /shared/uv_python
```

Nach Git-Sync oder erstem Pipeline-Run sollten Verzeichnisse wachsen.

### 5.5 Unit-Tests (lokal / CI)

```bash
pytest tests/test_worker_security.py -q
```

---

## 6. PVC-Berechtigungen (bestehende Cluster)

Neue Pods laufen als **UID 1001** mit **`fsGroup: 1001`**. Wenn alte Dateien auf dem PVC noch **root** gehören, können Schreibzugriffe fehlschlagen.

Symptom: `Permission denied` in Orchestrator-Logs beim Schreiben nach `/app/data`, `/app/logs`, `/app/pipelines` oder `/shared`.

**Prüfen:**

```bash
kubectl exec deploy/fastflow-orchestrator -c orchestrator -- id
kubectl exec deploy/fastflow-orchestrator -c orchestrator -- touch /shared/.write_test && echo OK
```

**Einmalig reparieren** (Vorsicht — nur wenn nötig):

```bash
kubectl exec deploy/fastflow-orchestrator -c orchestrator -- sh -c '
  chown -R 1001:1001 /app/data /app/logs /app/pipelines /shared 2>/dev/null || true
'
```

Langfristig: frische PVCs oder einmalige Migration mit Backup.

---

## 7. Typische Fehler & Lösungen

| Symptom | Wahrscheinliche Ursache | Maßnahme |
|--------|-------------------------|----------|
| `CrashLoopBackOff` Orchestrator | Schreibversuch ins read-only `/app` | `TMPDIR=/tmp`, PVC-Mounts prüfen, Logs lesen |
| Init-Container `wait-for-postgres` failed | Postgres nicht erreichbar / falsches Secret | `kubectl logs <pod> -c wait-for-postgres` |
| Pipeline-Job `CreateContainerConfigError` | Worker-Image nicht pullbar | `WORKER_BASE_IMAGE`, `imagePullSecrets` |
| Job: `permission denied` auf `/cache/uv` | PVC-Rechte / falsches Worker-Image | `fastflow-worker` nutzen, `fsGroup` prüfen |
| Notebook-Pipeline schlägt fehl | Standard-`uv`-Image ohne `/runner` | `Dockerfile.worker` bauen und deployen |
| Pre-Heating hilft Jobs nicht | Alter Cache noch auf `fastflow-pvc` | Abschnitt **UV-Cache migrieren** |
| Docker-Worker startet nicht | Altes Image, root-only Pfade | `fastflow-worker:latest` bauen, `WORKER_BASE_IMAGE` setzen |

---

## 8. Rollback

Falls das Upgrade Probleme macht:

1. **Images** auf den vorherigen Tag zurücksetzen (`deployment.yaml`, `WORKER_BASE_IMAGE`)
2. **Alte Manifests** aus Git auschecken und `kubectl apply`
3. **`kubectl rollout undo deployment/fastflow-orchestrator`**
4. Bei Cache-Migration: Daten auf `/shared` bleiben erhalten; alte Pfade unter `/app/data/uv_*` sind unverändert

Rollback setzt die Security-Härtung zurück — nur als Notfall nutzen.

---

## 9. Hinweise für Cluster-Admins (Pod Security)

Die Workloads sind ausgelegt für:

- `runAsNonRoot: true`
- `readOnlyRootFilesystem: true` (mit beschreibbaren Volume-/emptyDir-Mounts)
- `allowPrivilegeEscalation: false`
- `capabilities.drop: [ALL]`
- `seccompProfile.type: RuntimeDefault`

Falls der Cluster **Pod Security Standards** (z. B. `restricted`) erzwingt, sollten Orchestrator und Pipeline-Jobs diese Anforderungen erfüllen. Postgres ist nur teilweise gehärtet (Non-Root, kein readOnlyRootFS auf dem DB-Container).

---

## 10. Dateien im Überblick

| Datei | Rolle |
|-------|--------|
| `Dockerfile` | Orchestrator, User `fastflow` (1001) |
| `Dockerfile.worker` | Worker, User `worker` (1001), `/runner` |
| `k8s/deployment.yaml` | Orchestrator Security + UV-Pfade + `/tmp` emptyDir |
| `k8s/postgres.yaml` | Postgres Pod-Security (Basis) |
| `k8s/configmap.yaml` | `WORKER_BASE_IMAGE`, `ENVIRONMENT`, … |
| `app/executor/worker_runtime.py` | Gemeinsame Pfade, Security-Builder |
| `app/executor/kubernetes_backend.py` | Job-Specs mit readOnlyRootFS |
| `app/executor/core.py` | Docker-Worker Security |
| `docker-compose.yaml` | Orchestrator `read_only` + Worker-Image |
| `tests/test_worker_security.py` | Regressionstests |

---

## Kurz: Minimalablauf Production

```bash
# 1. Build & Push
docker build -t $REGISTRY/fastflow-orchestrator:$TAG .
docker build -f Dockerfile.worker -t $REGISTRY/fastflow-worker:$TAG .
docker push $REGISTRY/fastflow-orchestrator:$TAG
docker push $REGISTRY/fastflow-worker:$TAG

# 2. Config anpassen (Image-Tags, WORKER_BASE_IMAGE, ENVIRONMENT=production)

# 3. Deploy
kubectl apply -f k8s/
kubectl rollout restart deployment/fastflow-orchestrator

# 4. Cache migrieren (falls Upgrade von alter Version)

# 5. Smoke-Test: /health, /ready, eine Pipeline starten

# 6. CI: pytest tests/test_worker_security.py
```
