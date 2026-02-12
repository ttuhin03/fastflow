# Fast-Flow auf Kubernetes

Manifests für den Betrieb des Fast-Flow Orchestrators in Kubernetes: Orchestrator + Docker-Socket-Proxy, optional PostgreSQL, PVC für Daten/Logs/Pipelines.

---

## Deployment auf einem Kubernetes-Cluster

So deployest du Fast-Flow auf einem **beliebigen K8s-Cluster** (z. B. eigener Cluster, On-Prem, Cloud mit Docker-Nodes).

### Voraussetzungen

- **kubectl** ist installiert und auf den Cluster konfiguriert (`kubectl cluster-info`).
- **Nodes mit Docker:** Die Pipeline-Container laufen über den Docker-Socket. Die Cluster-Nodes müssen einen **Docker-Daemon** haben (nicht nur containerd). Bei managed Clustern (GKE, EKS, AKS) ohne Docker siehe README „Produktion“ / Architektur-Hinweise.
- **Images** stehen in einer Registry oder werden in den Cluster geladen (siehe unten).

### 1. Images bereitstellen

**Variante A – Registry (empfohlen für Produktion):**  
Orchestrator und Worker bauen, in eine Registry pushen, in ConfigMap/Deployment den vollen Image-Namen inkl. Tag eintragen:

```bash
docker build -t your-registry.io/fastflow-orchestrator:v1.0.0 .
docker push your-registry.io/fastflow-orchestrator:v1.0.0
docker build -f Dockerfile.worker -t your-registry.io/fastflow-worker:v1.0.0 .
docker push your-registry.io/fastflow-worker:v1.0.0
```

Im Deployment `image:` auf `your-registry.io/fastflow-orchestrator:v1.0.0` setzen, in der ConfigMap `WORKER_BASE_IMAGE: "your-registry.io/fastflow-worker:v1.0.0"`. Bei privater Registry ggf. **imagePullSecrets** im Deployment anlegen und eintragen.

**Variante B – Cluster ohne Registry (z. B. Kind):**  
Images lokal bauen und in den Cluster laden (z. B. `kind load docker-image fastflow-orchestrator:latest`). Deployment mit `image: fastflow-orchestrator:latest` und `imagePullPolicy: IfNotPresent` nutzen.

### 2. Secrets und ConfigMap anpassen

- **Secrets:** `k8s/secrets.yaml` kopieren, alle Werte ersetzen (ENCRYPTION_KEY, JWT_SECRET_KEY, OAuth-Credentials). Für Produktion `SKIP_OAUTH_VERIFICATION: "false"` setzen. Datei **nicht** mit echten Secrets ins Repo committen (z. B. über CI/CD oder externes Secret-Management einspielen).
- **ConfigMap:** In `k8s/configmap.yaml` mindestens anpassen:
  - **BASE_URL** / **FRONTEND_URL:** Öffentliche URL der App (z. B. `https://fastflow.example.com`).
  - **ENVIRONMENT:** `production` für echten Betrieb.
  - **WORKER_BASE_IMAGE:** Wie in Schritt 1 (Registry-Image inkl. Tag für Notebook-Pipelines).

### 3. Manifests anwenden

Reihenfolge einhalten (PVC vor Postgres vor Secrets/ConfigMap vor Deployment vor Service):

```bash
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/postgres.yaml    # optional, sonst SQLite im PVC
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

### 4. Zugriff auf die App

- **NodePort (Standard in service.yaml):** Service nutzt NodePort 30080. App erreichbar unter `http://<eine-Node-IP>:30080`. Für feste URL und TLS einen **Ingress** anlegen (z. B. mit cert-manager).
- **Port-Forward zum Testen:**  
  `kubectl port-forward svc/fastflow-orchestrator 8000:80` → **http://localhost:8000**

### 5. OAuth-Callback-URL

In der GitHub-/Google-OAuth-App die **Authorization callback URL** auf die tatsächliche App-URL setzen, z. B.  
`https://fastflow.example.com/api/auth/github/callback` (mit der in BASE_URL verwendeten Domain).

---

## Lokales Testen mit Minikube (VM, ohne Docker Desktop)

Zum Testen der gesamten App auf Kubernetes **in einer echten VM** (nicht Docker-Desktop-K8s) dient das Skript **`scripts/minikube-vm.sh`** mit Minikube und einem VM-Treiber (QEMU, VirtualBox, VMware).

### Voraussetzungen

- **kubectl** – [Installation](https://kubernetes.io/docs/tasks/tools/)
- **minikube** – z.B. `brew install minikube`
- **Ein VM-Treiber** (nur einer nötig):
  - **QEMU:** `brew install qemu` (Standard im Skript)
  - **VirtualBox:** [Download](https://www.virtualbox.org/wiki/Downloads)
  - **VMware:** Fusion/Workstation

Optional für erreichbare Node-IP und `minikube service` (QEMU):

- **socket_vmnet:** `brew install socket_vmnet && sudo brew services start socket_vmnet`  
  Dann startet das Skript Minikube mit `--network=socket_vmnet`.

### Was das Skript macht

1. **Cluster starten** mit VM-Treiber und **Docker** als Container-Runtime (damit Pipeline-Container über den Docker-Socket laufen).
2. **Images bauen** in der Minikube-VM (kein Registry nötig):
   - `fastflow-orchestrator:latest` – die App
   - `fastflow-worker:latest` – Worker mit uv + Notebook-Runner (`nb_runner.py`) für Notebook-Pipelines
3. **Manifests anwenden** in der richtigen Reihenfolge.
4. **ConfigMap patchen:** `WORKER_BASE_IMAGE=fastflow-worker:latest` (für Notebook-Pipelines).
5. **Rollout-Restart**, damit Pods die aktuellen Secrets/ConfigMap laden.

`BASE_URL` / `FRONTEND_URL` bleiben aus der ConfigMap auf **`http://localhost:8000`**, damit OAuth mit Port-Forward funktioniert (siehe unten).

### Befehle

```bash
# Alles: Cluster starten, Images bauen, deployen
./scripts/minikube-vm.sh

# Cluster läuft schon – nur bauen und deployen
./scripts/minikube-vm.sh --no-start

# Anderen VM-Treiber
MINIKUBE_DRIVER=virtualbox ./scripts/minikube-vm.sh
./scripts/minikube-vm.sh --driver=virtualbox

# Cluster stoppen
./scripts/minikube-vm.sh --stop

# PVCs löschen (frischer Test) – danach erneut deployen
./scripts/minikube-vm.sh --delete-pvcs
./scripts/minikube-vm.sh
```

### Skript-Referenz: `scripts/minikube-vm.sh`

| Option | Beschreibung |
|--------|--------------|
| *(keine)* | Minikube starten (falls nötig), beide Images bauen, Manifests anwenden, Rollout-Restart |
| `--no-start` | Cluster nicht starten; nur Docker-Env setzen, Images bauen, Manifests anwenden, Restart (Cluster muss laufen) |
| `--stop` | Nur `minikube stop` ausführen (kubectl nicht nötig) |
| `--delete-pvcs` | Löscht die Deployments `fastflow-orchestrator` und `postgres` sowie die PVCs `fastflow-pvc` und `postgres-pvc`. Nützlich für einen **frischen Test** (leere DB, leere Pipelines/Logs). Danach Skript ohne Option erneut ausführen, um mit neuen Volumes zu deployen. |
| `--driver=NAME` | VM-Treiber: `qemu` (Standard), `virtualbox`, `vmware` |
| `-h`, `--help` | Kurze Hilfe mit allen Optionen anzeigen |

Hilfe im Terminal: `./scripts/minikube-vm.sh --help`

### App aufrufen (Zugriff vom Mac)

- **Empfohlen (funktioniert immer, auch bei QEMU):**  
  ```bash
  kubectl port-forward svc/fastflow-orchestrator 8000:80
  ```  
  Dann im Browser: **http://localhost:8000**

- **Direkt über NodePort** (wenn die Minikube-IP vom Mac erreichbar ist):  
  `http://$(minikube ip):30080`  
  Bei QEMU ohne socket_vmnet ist die Node-IP oft `10.0.2.15` und vom Mac aus nicht erreichbar. Mit socket_vmnet oder VirtualBox gibt es meist eine erreichbare IP.

- **`minikube service fastflow-orchestrator --url`** funktioniert nur, wenn Minikube mit `--network=socket_vmnet` gestartet wurde (QEMU).

### OAuth (GitHub) bei Port-Forward

Wenn du die App über **http://localhost:8000** (Port-Forward) aufrufst:

1. In der **GitHub OAuth App** (Settings → Developer settings → OAuth Apps → deine App) bei **Authorization callback URL** eintragen:
   - **`http://localhost:8000/api/auth/github/callback`**
2. Kein Slash am Ende, exakt `http` (nicht `https`), Port 8000.

Die App nutzt `BASE_URL` für den Redirect; mit ConfigMap-Default `localhost:8000` passt das zur Callback-URL.

### Wichtige Konfigurationen für K8s/Minikube

- **SKIP_OAUTH_VERIFICATION:** In `secrets.yaml` für lokales K8s auf `"true"` gesetzt. So schlägt der Startup nicht fehl, wenn der Pod kein ausgehendes DNS hat (OAuth-Login im Browser funktioniert trotzdem).
- **WORKER_BASE_IMAGE:** Wird vom Skript auf `fastflow-worker:latest` gepatcht. Das Worker-Image enthält `/runner` (u.a. `nb_runner.py`) für Notebook-Pipelines; in K8s gibt es dafür keinen Host-Pfad.
- **Pipeline-Host-Pfad:** Der Executor ermittelt den Host-Pfad für `/app/pipelines` automatisch über die Docker-API (Mounts des Orchestrator-Containers). Ein manuelles Setzen von `PIPELINES_HOST_DIR` ist in der Regel nicht nötig.

---

## Manifests-Übersicht

| Datei            | Inhalt |
|------------------|--------|
| `pvc.yaml`       | PersistentVolumeClaim für Daten/Logs/Pipelines (Orchestrator) |
| `postgres.yaml`  | Optional: PostgreSQL (Secret, PVC, Deployment, Service) |
| `secrets.yaml`   | Fast-Flow Secrets (OAuth, JWT, Encryption, SKIP_OAUTH_VERIFICATION) |
| `configmap.yaml` | Nicht-sensible Umgebungsvariablen (BASE_URL, WORKER_BASE_IMAGE, …) |
| `deployment.yaml`| Orchestrator + Docker-Proxy-Sidecar, Init-Container wartet auf Postgres |
| `service.yaml`   | NodePort 30080 |

**Reihenfolge** beim manuellen Anwenden:  
`pvc.yaml` → `postgres.yaml` → `secrets.yaml` → `configmap.yaml` → `deployment.yaml` → `service.yaml`.  
Danach ggf. `kubectl rollout restart deployment/fastflow-orchestrator`, damit neue Secrets/ConfigMap geladen werden.

---

## Pipeline-Runs in K8s

- **Script-Pipelines:** Der Orchestrator findet den Host-Pfad für das Pipeline-Verzeichnis über die Docker-API (Mounts des eigenen Containers). Das gemountete PVC erscheint dort als Host-Pfad; Worker-Container erhalten das richtige Verzeichnis unter `/app`.
- **Notebook-Pipelines:** Es wird das Image **fastflow-worker:latest** verwendet (im Skript gebaut). Es enthält `/runner/nb_runner.py`. Ein Mount von `app/runners` vom Host ist in K8s nicht nötig (und nicht vorhanden).

---

## Troubleshooting

- **Deployment wird nicht ready / CrashLoopBackOff:**  
  Das Skript gibt bei Timeout Diagnose aus (Pods, Describe, Logs). Oft reicht:
  ```bash
  kubectl rollout restart deployment/fastflow-orchestrator
  kubectl logs -f deploy/fastflow-orchestrator -c orchestrator --tail=100
  ```
- **OAuth: "redirect_uri is not associated with this application":**  
  Callback-URL in der GitHub OAuth App exakt wie oben (z.B. `http://localhost:8000/api/auth/github/callback`). Nach Änderung an Secrets/ConfigMap: `kubectl rollout restart deployment/fastflow-orchestrator`.
- **Pipeline: "No such file or directory: '/app/main.py'":**  
  Host-Pfad für Pipelines wurde nicht gefunden. Image neu bauen und deployen (Executor nutzt seit Fix die Docker-API zur Ermittlung des Mounts).
- **Notebook-Pipeline: "can't open file '/runner/nb_runner.py'":**  
  Worker-Image muss `fastflow-worker:latest` sein (enthält `/runner`). Skript baut es und patcht `WORKER_BASE_IMAGE`. Sonst: `docker build -f Dockerfile.worker -t fastflow-worker:latest .` in Minikube-Docker-Env und ConfigMap patchen.

---

## Produktion

Vorgehen wie unter **„Deployment auf einem Kubernetes-Cluster“**; zusätzlich:

- **Secrets:** Alle Werte ersetzen (Fernet-Key neu generieren, OAuth-Credentials), `SKIP_OAUTH_VERIFICATION: "false"`. Secrets nicht im Repo; über CI/CD oder externes Secret-Management einspielen.
- **ConfigMap:** `BASE_URL` / `FRONTEND_URL` = echte Domain, `ENVIRONMENT: production`, `WORKER_BASE_IMAGE` = Registry-Image inkl. Tag.
- **Images:** Orchestrator und Worker aus Registry mit festem Tag (nicht `:latest`).
- Optional: Ingress + TLS, Ressourcen sind im Deployment bereits gesetzt, mehrere Replicas, HPA, eigener Namespace.
