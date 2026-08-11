# Fast-Flow auf Kubernetes

Manifests für den Betrieb des Fast-Flow Orchestrators in Kubernetes: Orchestrator + Docker-Socket-Proxy, optional PostgreSQL, PVC für Daten/Logs/Pipelines.

---

## Deployment auf einem Kubernetes-Cluster

So deployest du Fast-Flow auf einem **beliebigen K8s-Cluster** (z. B. eigener Cluster, On-Prem, Cloud mit Docker-Nodes).

### Voraussetzungen

- **kubectl** ist installiert und auf den Cluster konfiguriert (`kubectl cluster-info`).
- **Pipeline-Runs als K8s-Jobs:** Die Manifests nutzen keinen Docker-Socket; Pipeline-Runs laufen als Kubernetes Jobs (funktioniert mit containerd/Talos).
- **Images** stehen in einer Registry oder werden in den Cluster geladen (siehe unten).

### 1. Images bereitstellen

**Variante A – Vorgefertigte Images von GitHub (ghcr.io):**  
Bei jedem **Release-Tag** (z. B. `v1.0.0`) baut ein GitHub-Actions-Workflow automatisch beide Images und pusht sie in die GitHub Container Registry. Für ein K8s-Deployment reicht es dann, diese Images zu referenzieren (öffentliches Repo → Images ohne Login pullbar):

- **Orchestrator:** `ghcr.io/<REPO-OWNER>/fastflow-orchestrator:1.0.0` (oder Tag mit `v`: `v1.0.0`)
- **Worker:** `ghcr.io/<REPO-OWNER>/fastflow-worker:1.0.0`

Beispiel für dieses Repo (Owner z. B. `ttuhin03`): Im Deployment `image: ghcr.io/ttuhin03/fastflow-orchestrator:v1.0.0`, in der ConfigMap `WORKER_BASE_IMAGE: "ghcr.io/ttuhin03/fastflow-worker:v1.0.0"`. `<REPO-OWNER>` durch den GitHub-Benutzernamen bzw. die Organisation ersetzen. Neues Image erzeugen: im Repo einen Tag pushen (z. B. `git tag v1.0.0 && git push origin v1.0.0`), der Workflow unter „Actions“ baut und pusht dann die Images.

**Variante B – Eigene Registry:**  
Orchestrator und Worker selbst bauen und in eine eigene Registry pushen:

```bash
docker build -t your-registry.io/fastflow-orchestrator:v1.0.0 .
docker push your-registry.io/fastflow-orchestrator:v1.0.0
docker build -f Dockerfile.worker -t your-registry.io/fastflow-worker:v1.0.0 .
docker push your-registry.io/fastflow-worker:v1.0.0
```

Im Deployment `image:` auf `your-registry.io/fastflow-orchestrator:v1.0.0` setzen, in der ConfigMap `WORKER_BASE_IMAGE: "your-registry.io/fastflow-worker:v1.0.0"`. Bei privater Registry **imagePullSecrets** im Deployment eintragen.

**Variante C – Cluster ohne Registry (z. B. Kind):**  
Images lokal bauen und in den Cluster laden (z. B. `kind load docker-image fastflow-orchestrator:latest`). Deployment mit `image: fastflow-orchestrator:latest` und `imagePullPolicy: IfNotPresent` nutzen.

### 2. Secrets und ConfigMap anpassen

- **Secrets:** `k8s/secrets.yaml` kopieren, alle Werte ersetzen (ENCRYPTION_KEY, JWT_SECRET_KEY, OAuth-Credentials). Für Produktion `SKIP_OAUTH_VERIFICATION: "false"` setzen. Datei **nicht** mit echten Secrets ins Repo committen (z. B. über CI/CD oder externes Secret-Management einspielen).
- **ConfigMap:** In `k8s/configmap.yaml` mindestens anpassen:
  - **BASE_URL** / **FRONTEND_URL:** Öffentliche URL der App (z. B. `https://fastflow.example.com`).
  - **ENVIRONMENT:** `production` für echten Betrieb.
  - **WORKER_BASE_IMAGE:** Wie in Schritt 1 (Registry-Image inkl. Tag für Notebook-Pipelines).

### 3. Manifests anwenden

Reihenfolge einhalten (PVCs, Postgres, Secrets/ConfigMap, RBAC, Deployment, Service):

```bash
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/postgres.yaml    # optional, sonst SQLite im PVC
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/rbac-kubernetes-executor.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

**Anderer Namespace als `default`?** `kubectl apply -n <ns>` allein genügt **nicht** — das RoleBinding-Subject muss mit umgeschrieben werden, sonst greift die Bindung für niemanden und jeder Run scheitert mit 403. Kommando in [Anderer Namespace als `default`](#anderer-namespace-als-default).

**Wichtig bei einem Update eines laufenden Clusters:** Die RBAC **vor** dem Deployment anwenden. Der Executor legt die Env-Vars eines Runs in einem Per-Run-Secret ab und braucht dafür `secrets: create, patch, delete`; rollt man das Image zuerst aus, scheitert jeder Run mit `infrastructure_error` (403). Siehe [RBAC des Executors](#rbac-des-executors) und [Security Rollout](../docs/docs/deployment/SECURITY-ROLLOUT.md).

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

1. **Cluster starten** mit VM-Treiber (Pipeline-Runs laufen als K8s-Jobs, kein Docker-Socket nötig).
2. **metrics-server aktivieren** – für CPU/RAM-Anzeige in der UI (Run-Detail → Metrics, Einstellungen → System-Metriken / Aktive Container). Ohne metrics-server bleiben diese Werte 0.
3. **Images bauen** in der Minikube-VM (kein Registry nötig):
   - `fastflow-orchestrator:latest` – die App
   - `fastflow-worker:latest` – Worker mit uv + Notebook-Runner (`nb_runner.py`) für Notebook-Pipelines
4. **Manifests anwenden** in der richtigen Reihenfolge.
5. **ConfigMap patchen:** `WORKER_BASE_IMAGE=fastflow-worker:latest` (für Notebook-Pipelines).
6. **Rollout-Restart**, damit Pods die aktuellen Secrets/ConfigMap laden.

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
| `--delete-pvcs` | Löscht die Deployments `fastflow-orchestrator` und `postgres` sowie die PVCs aus `pvc.yaml` (fastflow-pvc, fastflow-cache-pvc) und postgres-pvc. Nützlich für einen **frischen Test** (leere DB, leere Pipelines/Logs). Danach Skript ohne Option erneut ausführen, um mit neuen Volumes zu deployen. |
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

### Log-Streaming und Ressourcen (CPU/RAM)

- **Logs:** Die Pipeline-Logs werden aus dem Job-Pod gestreamt. Die angezeigten Zeiten stammen von der K8s-API (`timestamps=true`), sodass die Reihenfolge auch bei gebündeltem Stream stimmt. Sehr schnelle Jobs (Pod schon „Succeeded“, bevor der Stream startet) werden trotzdem vollständig geloggt.
- **CPU/RAM pro Run und in den System-Metriken:** Dafür wird die Kubernetes Metrics-API (`metrics.k8s.io`) genutzt. Das Minikube-Skript aktiviert dafür das Addon **metrics-server**. Nach dem ersten Start kann es 1–2 Minuten dauern, bis Metriken verfügbar sind (`kubectl top pods` zum Prüfen).

---

**Hinweis:** Die Manifests in `k8s/` sind für den Betrieb **auf Kubernetes mit Pipeline-Runs als K8s-Jobs** (kein Docker auf den Nodes). Für den Betrieb mit **Docker** (Pipeline-Container über Socket-Proxy) nutze Docker Compose bzw. das Dockerfile.

---

## Manifests-Übersicht

| Datei                         | Inhalt |
|-------------------------------|--------|
| `pvc.yaml`                    | Zwei PVCs: Daten/Logs/Pipelines (RWO) + UV-Cache/Pipeline-Kopien (RWM für Jobs) |
| `rbac-kubernetes-executor.yaml` | ServiceAccount + Role + RoleBinding für K8s-Jobs (inkl. write-only Secrets, siehe unten) sowie der rechtelose `fastflow-runner`-SA für die Pipeline-Pods |
| `postgres.yaml`               | Optional: PostgreSQL (Secret, PVC, Deployment, Service) |
| `secrets.yaml`                | Fast-Flow Secrets (OAuth, JWT, Encryption, SKIP_OAUTH_VERIFICATION) |
| `configmap.yaml`              | Nicht-sensible Umgebungsvariablen (BASE_URL, WORKER_BASE_IMAGE, …) |
| `deployment.yaml`             | Orchestrator (PIPELINE_EXECUTOR=kubernetes), Cache-PVC, Init-Container |
| `service.yaml`                | NodePort 30080 |

**Reihenfolge** beim manuellen Anwenden:  
`pvc.yaml` → `postgres.yaml` → `secrets.yaml` → `configmap.yaml` → `rbac-kubernetes-executor.yaml` → `deployment.yaml` → `service.yaml`.  
Danach ggf. `kubectl rollout restart deployment/fastflow-orchestrator`, damit neue Secrets/ConfigMap geladen werden.

---

## RBAC des Executors

Die Role in `rbac-kubernetes-executor.yaml` ist namespaced und ohne Wildcards:

| API-Group | Resource | Verbs | Wofür |
|-----------|----------|-------|-------|
| `batch` | `jobs` | `create`, `get`, `list`, `delete` | Pipeline-Runs als Jobs starten, überwachen, abbrechen |
| *(core)* | `pods`, `pods/log` | `get`, `list` | Pod zum Job finden, Logs streamen |
| *(core)* | `secrets` | `create`, `patch`, `delete` | Per-Run-Env-Secret — **kein Lesen** |
| `metrics.k8s.io` | `pods` | `get` | CPU/RAM-Anzeige (metrics-server, optional) |

**Env-Vars liegen in einem Per-Run-Secret**, nicht als Literale in der Job-Spec. Literale würden im etcd, in `kubectl describe job` und im API-Audit-Log landen — und die eingebaute `view`-ClusterRole erlaubt get/list auf Jobs und Pods, aber **nicht** auf Secrets. Auch `EncryptionConfiguration` (Encryption-at-Rest) deckt in typischen Clustern nur `secrets` ab.

Die Secret-Rechte sind bewusst **write-only** (kein `get`/`list`/`watch`): Der Orchestrator kann sein Run-Secret anlegen und löschen, aber kein Secret lesen — insbesondere nicht `fastflow-secrets` (Master-Fernet-Key) und nicht das Postgres-Secret. `create` lässt sich in RBAC nicht per `resourceNames` einschränken; die Secret-Namen werden deshalb deterministisch aus der Run-ID abgeleitet (`ff-run-env-<run-id>`), sodass Löschen und Startup-Sweep ohne `list` auskommen.

Rechte prüfen (Namespace anpassen):

```bash
kubectl auth can-i create secrets --as=system:serviceaccount:default:fastflow-executor -n default   # yes
kubectl auth can-i get    secrets --as=system:serviceaccount:default:fastflow-executor -n default   # no
```

Aufgeräumt wird das Secret explizit am Run-Ende (Erfolg, Fehler, Cancel, Reconcile, Shutdown); zusätzlich hängt eine `ownerReference` auf den Job als Backstop daran, und beim App-Start räumt ein Sweep Reste nach einem unclean Shutdown ab.

Notausstieg, falls die RBAC nicht ausgerollt werden kann: `KUBERNETES_ENV_VIA_SECRET=false` (Details und Aufräum-Kommando in [Security Rollout](../docs/docs/deployment/SECURITY-ROLLOUT.md), Abschnitt 2a).

### Anderer Namespace als `default`

Die Manifeste tragen bewusst kein `metadata.namespace`, damit `kubectl apply -f k8s/` im aktuellen Kontext läuft. **Eine Stelle deckt `kubectl apply -n <ns>` aber nicht ab:** Das RoleBinding-Subject in `rbac-kubernetes-executor.yaml` ist für `kind: ServiceAccount` in RBAC **pflichtig namespaced** (`namespace: default`) und wird von `-n` nicht umgeschrieben.

Wer nur `-n` nutzt, legt SA, Role und RoleBinding in `<ns>` an, während das Subject weiter auf `default:fastflow-executor` zeigt — einen Principal, den es in `<ns>` nicht gibt. Die Bindung greift dann für niemanden, **jeder Job- und Secret-Create scheitert mit 403**, und jeder Run endet als `infrastructure_error`. Der Fehler ist beim Apply unsichtbar: `kubectl apply` meldet Erfolg.

Deshalb das Subject vor dem Apply mit umschreiben:

```bash
NS=fastflow
sed "s/^\( *\)namespace: default$/\1namespace: $NS/" k8s/rbac-kubernetes-executor.yaml \
  | kubectl apply -n "$NS" -f -
```

Mit **kustomize** genügt `namespace: $NS` in der `kustomization.yaml` — der Namespace-Transformer zieht ServiceAccount-Subjects von RoleBindings automatisch mit. Gleiches gilt für Helm-Charts mit `.Release.Namespace` im Subject.

Danach verifizieren (muss `yes` sein):

```bash
kubectl auth can-i create jobs --as=system:serviceaccount:$NS:fastflow-executor -n $NS
```

Der Namespace der Pipeline-Jobs selbst kommt aus `KUBERNETES_NAMESPACE` (Deployment/ConfigMap, Default `default`) — er muss derselbe sein.

### Pipeline-Pods bekommen kein ServiceAccount-Token

Pipeline-Pods führen fremden User-Code aus. Ihre Pod-Spec setzt daher **`automountServiceAccountToken: false`** (`build_pipeline_job` in `app/executor/kubernetes_backend.py`). Ohne das mountet das Kubelet den Token des `default`-ServiceAccounts unter `/var/run/secrets/kubernetes.io/serviceaccount` — eine Cluster-Credential, die jede Pipeline benutzen kann. Hat `default` irgendein Secret-Read-Recht (üblich, wo Rollen an `system:serviceaccounts` hängen), liest Pipeline-Code damit die Env-Secrets **anderer** Runs und `fastflow-secrets` mit dem Master-Fernet-Key (`ENCRYPTION_KEY`) und `JWT_SECRET_KEY`.

Optional als zweite Stufe: Die Pods an einen eigenen, rechtelosen ServiceAccount hängen, statt an der Identität von `default` (relevant für Audit-Logs und NetworkPolicies). `rbac-kubernetes-executor.yaml` liefert dafür `fastflow-runner` — **ohne** RoleBinding, also ohne jedes Recht:

```bash
kubectl apply -f k8s/rbac-kubernetes-executor.yaml    # bringt fastflow-runner mit
kubectl set env deployment/fastflow-orchestrator KUBERNETES_JOB_SERVICE_ACCOUNT=fastflow-runner
```

**Reihenfolge beachten:** Erst das Manifest, dann die Variable. Existiert der SA im Namespace nicht, legt das ServiceAccount-Admission-Plugin den Pod nie an; der Job bleibt ohne Pod, und bei nicht gesetztem `CONTAINER_TIMEOUT` pollt der Orchestrator ohne Deadline — der Run hängt dauerhaft in `RUNNING` und blockiert einen `MAX_CONCURRENT_RUNS`-Slot. Genau deshalb ist die Variable ein Opt-in und nicht der Default.

Prüfen (funktioniert auch an einem bereits beendeten Job-Pod):

```bash
POD=$(kubectl get pods -l app=fastflow-runner --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl get pod "$POD" -o jsonpath='{.spec.automountServiceAccountToken}{"\n"}'   # erwartet: false
kubectl get pod "$POD" -o jsonpath='{.spec.volumes[*].name}{"\n"}'                # erwartet: nur cache tmp, kein kube-api-access-*
```

**Bewusst in Kauf genommen:** Eine Pipeline, die aus ihrem Container heraus per In-Cluster-Token die Kubernetes-API anspricht (`load_incluster_config()`), bricht damit. Im Repo tut das nichts — der Job-Container startet nur ein statisches `uv run … python -u -c <wrapper>`. Wer API-Zugriff aus einer Pipeline braucht, hinterlegt einen eigenen, eng gefassten Token als Pipeline-Secret; siehe [Security Rollout](../docs/docs/deployment/SECURITY-ROLLOUT.md), Abschnitt 2b.

---

## Pipeline-Runs in K8s

- **Script-Pipelines:** Der Orchestrator findet den Host-Pfad für das Pipeline-Verzeichnis über die Docker-API (Mounts des eigenen Containers). Das gemountete PVC erscheint dort als Host-Pfad; Worker-Container erhalten das richtige Verzeichnis unter `/app`.
- **Notebook-Pipelines:** Es wird das Image **fastflow-worker:latest** verwendet (im Skript gebaut). Es enthält `/runner/nb_runner.py`. Ein Mount von `app/runners` vom Host ist in K8s nicht nötig (und nicht vorhanden).

### Hinweis zu `entrypoint.sh` (K8s)

Im Standard-Deployment (`k8s/deployment.yaml`) ist für den Orchestrator **kein** `command`/`args` gesetzt. Daher nutzt Kubernetes den Image-Default aus dem `Dockerfile`: `CMD ["./entrypoint.sh"]`.

Wenn du `command` oder `args` im Deployment überschreibst, rufe `./entrypoint.sh` weiterhin auf (oder übernimm dessen Init-Schritte explizit), damit DB-Init/Migrationen und Startlogik konsistent bleiben.

### Pipeline-Arten – K8s-Support (Übersicht)

In der App gibt es genau **zwei Einstiegstypen** (`type` in `pipeline.json` bzw. Discovery via `main.py` / `main.ipynb`):

| Typ        | Beschreibung              | K8s-Support | Hinweis |
|-----------|---------------------------|-------------|---------|
| **script**  | `main.py`, Default        | ✅ Ja       | Gleicher Befehl wie Docker (`_build_container_command`), Run via Job-Pod. |
| **notebook**| `main.ipynb`              | ✅ Ja       | Worker-Image muss `/runner/nb_runner.py` enthalten (z. B. `fastflow-worker:latest`). |

Weitere **Pipeline-Features** (gelten für beide Executoren, werden im Orchestrator bzw. beim Job-Start berücksichtigt):

- **python_version** – ✅ (uv `--python` im Container-Command)
- **requirements.txt** / **requirements.txt.lock** – ✅ (uv `--with-requirements`, Mount unter `/app`)
- **timeout** – ✅ (Job `active_deadline_seconds`)
- **cpu_hard_limit** / **mem_hard_limit** – ✅ (Pod `resources.limits`)
- **retry_attempts** / **retry_strategy** – ✅ nur für **script** (Notebook-Runs werden in K8s bei Fehler nicht automatisch retried)
- **default_env**, **encrypted_env** – ✅ (werden im Core entschlüsselt und als `env_vars` an den K8s-Job übergeben)
- **schedules** / **run_config_id** – ✅ (Timeout/Limits/Retry aus Schedule-Eintrag)
- **downstream_triggers** – ✅ (Orchestrator-Logik, unabhängig vom Executor)
- **max_instances** – ✅ (prüft vor Start im Core)

---

## Pipeline-Jobs live prüfen

Welche Jobs laufen bzw. sind fehlgeschlagen:

```bash
# Alle Fast-Flow-Pipeline-Jobs (aktiv + abgeschlossen)
kubectl get jobs -l app=fastflow-orchestrator

# Pods zu diesen Jobs
kubectl get pods -l app=fastflow-orchestrator
```

Logs eines laufenden Pipeline-Pods (Job-Name aus `kubectl get jobs`):

```bash
kubectl logs -f job/<job-name> -c pipeline
# oder Pod-Name aus kubectl get pods
kubectl logs -f <pod-name> -c pipeline
```

Wenn Pipeline-Runs mit Exit-Code -1 enden und keine Logs erscheinen: oft war der **Cache-PVC (fastflow-cache-pvc)** nicht gebunden (z. B. ReadWriteMany ohne passende StorageClass). Die Manifests nutzen für den Cache-PVC **ReadWriteOnce**, damit Minikube/Single-Node funktioniert. Nach PVC-Änderung ggf. PVC löschen und erneut deployen.

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
