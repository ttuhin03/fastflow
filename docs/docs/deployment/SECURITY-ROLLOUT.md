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
| Pipeline-Job Env (K8s) | Literale in der Job-Spec | **Per-Run-Secret + `valueFrom.secretKeyRef`** |
| Executor-RBAC | Jobs/Pods | **zusätzlich `secrets: create, patch, delete`** (kein Lesen) |
| Pipeline-Pod SA-Token | Token des `default`-SA automatisch gemountet | **`automountServiceAccountToken: false`** (+ optionaler rechteloser SA `fastflow-runner`) |

Technische Konstanten und Security-Builder: `app/executor/worker_runtime.py`  
Automatisierte Checks: `tests/test_worker_security.py`, `tests/test_kubernetes_env_secret.py`

---

## Checkliste vor dem Rollout

- [ ] Neues **Orchestrator-Image** bauen (`Dockerfile`)
- [ ] Neues **Worker-Image** bauen (`Dockerfile.worker`) — **Pflicht** für Notebook-Pipelines (`/runner`) und Non-Root
- [ ] In **ConfigMap** / `.env`: `WORKER_BASE_IMAGE` auf euer Registry-Image setzen (nicht das alte Astral-`uv`-Image)
- [ ] K8s: **RBAC zuerst** anwenden (`rbac-kubernetes-executor.yaml`) — **vor** dem Image-Rollout, siehe Abschnitt 2a
- [ ] K8s: Bei einem **Namespace ≠ `default`** das RoleBinding-Subject mit umschreiben (`kubectl apply -n` allein genügt nicht), siehe Abschnitt 2a
- [ ] K8s: Optional `KUBERNETES_JOB_SERVICE_ACCOUNT=fastflow-runner` — **erst nach** dem RBAC-Apply, siehe Abschnitt 2b
- [ ] K8s: **`kubectl apply`** für geänderte Manifests (`deployment.yaml`, ggf. `postgres.yaml`)
- [ ] K8s: **UV-Cache migrieren** (falls bisher unter `/app/data/uv_cache` auf `fastflow-pvc`)
- [ ] **`ENVIRONMENT=production`** in ConfigMap (wenn Prod-Betrieb)
- [ ] Smoke-Test: Orchestrator startet, eine Pipeline läuft durch
- [ ] Optional: `pytest tests/test_worker_security.py tests/test_kubernetes_env_secret.py` in CI

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
kubectl apply -f k8s/rbac-kubernetes-executor.yaml   # MUSS vor dem Deployment, siehe 2a
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

## 2a. Env-Vars über Per-Run-Secret (RBAC zuerst!)

### Was sich ändert

Die Env-Vars eines Pipeline-Runs (inklusive entschlüsselter Secrets) standen bisher als **Literale in der Job-Spec**:

```yaml
# vorher – Klartext im etcd, in `kubectl describe job` und im API-Audit-Log
env:
  - name: API_KEY
    value: sk-live-…
```

Jetzt legt der Orchestrator pro Run ein **Secret** an und referenziert es pro Key:

```yaml
# nachher
env:
  - name: API_KEY
    valueFrom:
      secretKeyRef:
        name: ff-run-env-<run-id>
        key: API_KEY
```

**Warum das eine echte Grenze ist:** Die eingebaute `view`-ClusterRole erlaubt get/list auf **Jobs und Pods**, aber **nicht** auf Secrets. Und `EncryptionConfiguration` (Encryption-at-Rest) deckt in typischen Clustern nur die Ressource `secrets` ab. Klartext in der Job-Spec hebelt damit genau die Kontrollen aus, die der Cluster-Betreiber für aktiv hält.

Aufräumen: explizites `delete` am Run-Ende (Erfolg, Fehler, Cancel, Reconcile, Shutdown), zusätzlich eine `ownerReference` auf den Job als Backstop und ein Startup-Sweep für Reste nach einem unclean Shutdown.

### Reihenfolge — RBAC VOR dem Image

> **Reihenfolge einhalten.** Der neue Code braucht `secrets: create, patch, delete`. Rollt ihr **das Image zuerst** aus, scheitert **jeder Run** mit `infrastructure_error` (403 beim Secret-Create), bis die Role da ist.

```bash
# 1. RBAC zuerst
kubectl apply -f k8s/rbac-kubernetes-executor.yaml

# 2. Rechte verifizieren (siehe unten) – erst dann weiter

# 3. Danach das Image
kubectl apply -f k8s/deployment.yaml
kubectl rollout restart deployment/fastflow-orchestrator
kubectl rollout status deployment/fastflow-orchestrator
```

`skaffold.yaml` listet `rbac-kubernetes-executor.yaml` bereits **vor** `deployment.yaml`, für Skaffold-Deploys stimmt die Reihenfolge also automatisch.

### Namespace ≠ `default`: RoleBinding-Subject mitziehen

Die Manifeste tragen bewusst kein `metadata.namespace`. **Eine Stelle deckt `kubectl apply -n <ns>` aber nicht ab:** Das RoleBinding-Subject ist für `kind: ServiceAccount` in RBAC pflichtig namespaced (`namespace: default`) und wird von `-n` **nicht** umgeschrieben.

SA, Role und RoleBinding landen dann in `<ns>`, das Subject zeigt weiter auf `default:fastflow-executor` — einen Principal, den es in `<ns>` nicht gibt. Die Bindung greift für niemanden, **jeder Job- und Secret-Create endet mit 403**, jeder Run als `infrastructure_error`. `kubectl apply` meldet dabei Erfolg; sichtbar wird der Fehler erst am ersten Run.

```bash
NS=fastflow
sed "s/^\( *\)namespace: default$/\1namespace: $NS/" k8s/rbac-kubernetes-executor.yaml \
  | kubectl apply -n "$NS" -f -
```

Mit **kustomize** genügt `namespace: $NS` (der Namespace-Transformer zieht ServiceAccount-Subjects von RoleBindings mit), mit **Helm** `.Release.Namespace` im Subject. `KUBERNETES_NAMESPACE` im Deployment muss derselbe Namespace sein.

### Rechte verifizieren

Namespace anpassen (`-n <ns>`), Default ist `default`:

```bash
kubectl auth can-i create secrets --as=system:serviceaccount:default:fastflow-executor -n default
# erwartet: yes

kubectl auth can-i get secrets --as=system:serviceaccount:default:fastflow-executor -n default
# erwartet: no   <-- MUSS "no" sein
```

Die Role ist bewusst **write-only** auf Secrets: kein `get`/`list`/`watch`. Der Orchestrator kann sein Run-Secret also anlegen und löschen, aber **kein** Secret lesen — insbesondere nicht `fastflow-secrets` (Master-Fernet-Key) und nicht das Postgres-Secret. `create` lässt sich in RBAC nicht per `resourceNames` einschränken; die Secret-Namen werden deshalb deterministisch aus der Run-ID abgeleitet, sodass Löschen und Startup-Sweep ohne `list` auskommen.

Nach einem Run prüfen, dass kein Klartext mehr in der Job-Spec steht:

```bash
JOB=$(kubectl get jobs -l app=fastflow-runner --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
kubectl get job "$JOB" -o jsonpath='{.spec.template.spec.containers[0].env}' | jq .
# erwartet: nur name + valueFrom.secretKeyRef, keine "value"-Felder

# Und dass die Run-Secrets nach dem Run wieder weg sind:
kubectl get secrets -l app=fastflow-runner
```

### Notausstieg: `KUBERNETES_ENV_VIA_SECRET=false`

Falls die RBAC im Cluster nicht rechtzeitig ausgerollt werden kann (oder etwas Unerwartetes passiert), schaltet das Flag auf das alte Verhalten zurück — **ohne** Image-Rollback:

```bash
kubectl set env deployment/fastflow-orchestrator KUBERNETES_ENV_VIA_SECRET=false
```

Das ist ausdrücklich ein Notausstieg, kein Dauerzustand: Danach stehen die Env-Werte wieder im Klartext in der Job-Spec. Nach dem Zurückschalten **einmal aufräumen**, weil das Flag auch das Löschen abschaltet:

```bash
kubectl delete secret -l app=fastflow-runner
```

**Entfernungsziel:** Das Flag entfällt mit der zweiten Minor-Release nach seiner Einführung, sobald der Secret-Pfad im Betrieb bestätigt ist.

### Ungültige Env-Var-Namen

Secret-Data-Keys erlauben nur Buchstaben, Ziffern, `-`, `_` und `.`. Der Orchestrator validiert die Namen **vorab** dagegen und bricht den Run mit `infrastructure_error` ab, **bevor** irgendetwas im Cluster angelegt wird. Die Fehlermeldung nennt nur die betroffenen **Namen** (nie Werte). Betrifft z. B. Keys mit Leerzeichen, `=`, `/` oder Umlauten in `default_env`/`encrypted_env` — solche Keys umbenennen.

Bewusst hartes Scheitern statt `envFrom`: Dort würde das Kubelet ungültige Keys **still fallen lassen** und die Pipeline lief ohne die Variable.

Bewusst **nicht** strenger geprüft wird gegen das engere Env-Var-Regelwerk (`C_IDENTIFIER`): Ob ein Key wie `MY-VAR` als Env-Var-Name durchgeht, entscheidet die Cluster-Version — genau wie vor der Umstellung beim Job-Create. Eine strengere Prüfung würde Pipelines brechen, die heute laufen. Weil das Secret **vor** dem Job entsteht, scheitert so ein Key sauber am Job-Create (das Secret wird dabei wieder abgeräumt) und hinterlässt keinen Pod in `CreateContainerConfigError`.

---

## 2b. Pipeline-Pods ohne ServiceAccount-Token

### Was sich ändert

Die Pod-Spec der Pipeline-Jobs setzt jetzt **`automountServiceAccountToken: false`** (`build_pipeline_job` in `app/executor/kubernetes_backend.py`):

```yaml
# vorher – Token des default-SA gemountet unter
#          /var/run/secrets/kubernetes.io/serviceaccount
spec:
  restartPolicy: Never
  containers: [...]

# nachher
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  containers: [...]
```

**Warum:** Diese Pods führen beliebigen User-Pipeline-Code aus. Ohne das Flag mountet das Kubelet den Token des `default`-ServiceAccounts des Namespace — eine ambiente Cluster-Credential, die jede Pipeline mit einem einzigen `curl` gegen `$KUBERNETES_SERVICE_HOST` verwenden kann. Hat `default` irgendein Secret-Read-Recht — üblich in Clustern, in denen Rollen an `system:serviceaccounts` gebunden sind —, liest Pipeline-Code damit die Per-Run-Env-Secrets **anderer** Runs und `fastflow-secrets` mit dem Master-Fernet-Key (`ENCRYPTION_KEY`, entschlüsselt **alle** hinterlegten Pipeline-Secrets) und `JWT_SECRET_KEY` (beliebige Sessions signierbar). Die Abschottung aus Abschnitt 2a wäre damit wieder offen: Der Orchestrator darf Secrets bewusst nicht lesen — der Pod, den er startet, konnte es.

Der Rollout ist **nicht** reihenfolgeabhängig und braucht keine Cluster-Änderung: Es ist ein Feld in der Job-Spec, gültig für alle Jobs, die das neue Image erzeugt. Laufende Jobs behalten ihre alte Spec.

### Optional: eigener rechtloser ServiceAccount

Zweite Stufe, damit die Pods nicht mehr an der Identität von `default` hängen (relevant für Audit-Logs, NetworkPolicies und Cluster, in denen `default` Rechte hat). `rbac-kubernetes-executor.yaml` bringt dafür `fastflow-runner` mit — **ohne** RoleBinding, also ohne jedes Recht, plus `automountServiceAccountToken: false` am SA selbst:

```bash
# 1. Manifest zuerst (bringt fastflow-runner mit)
kubectl apply -f k8s/rbac-kubernetes-executor.yaml

# 2. SA existiert? MUSS gefunden werden, bevor Schritt 3 kommt
kubectl get serviceaccount fastflow-runner

# 3. Erst dann die Variable setzen
kubectl set env deployment/fastflow-orchestrator KUBERNETES_JOB_SERVICE_ACCOUNT=fastflow-runner
```

> **Reihenfolge einhalten.** Fehlt der SA im Namespace, lehnt das ServiceAccount-Admission-Plugin den Pod ab: Der Job bleibt **ohne Pod**, und bei nicht gesetztem `CONTAINER_TIMEOUT` pollt `_wait_for_job_completion` ohne Deadline — der Run hängt dauerhaft in `RUNNING` und blockiert einen `MAX_CONCURRENT_RUNS`-Slot. Genau deshalb ist die Variable ein Opt-in und leer per Default; Bestandsinstallationen, die das Manifest nie neu angewendet haben, bleiben unverändert lauffähig.

Zurückschalten jederzeit ohne Image-Rollback: `kubectl set env deployment/fastflow-orchestrator KUBERNETES_JOB_SERVICE_ACCOUNT-`. Der Token-Mount bleibt in beiden Fällen aus.

### Verifizieren

```bash
POD=$(kubectl get pods -l app=fastflow-runner --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')

kubectl get pod "$POD" -o jsonpath='{.spec.automountServiceAccountToken}{"\n"}'
# erwartet: false

kubectl get pod "$POD" -o jsonpath='{.spec.volumes[*].name}{"\n"}'
# erwartet: nur cache + tmp, kein kube-api-access-* Volume

# Nur solange ein Run läuft (danach ist der Pod beendet und exec schlägt fehl):
kubectl exec "$POD" -- ls /var/run/secrets/kubernetes.io/serviceaccount
# erwartet: No such file or directory
```

Beide `get pod`-Checks funktionieren auch an einem bereits beendeten Job-Pod — solange die Job-TTL (`KUBERNETES_JOB_TTL_SECONDS_AFTER_FINISHED`) ihn nicht schon aufgeräumt hat.

### Bewusst in Kauf genommenes Verhalten

Eine Pipeline, die **aus ihrem Container heraus** per In-Cluster-Token die Kubernetes-API anspricht, bricht mit dieser Änderung — typisch `kubernetes.config.load_incluster_config()`, das ohne den Token-Mount mit `ConfigException` scheitert, oder ein `curl` gegen `$KUBERNETES_SERVICE_HOST` ohne `Authorization`-Header (401).

Das ist **beabsichtigt und im Repo folgenlos**: Der Job-Container startet nur ein statisches `uv run … python -u -c <wrapper>` (`_build_container_command` in `app/executor/core.py`), keine Pipeline hier spricht die API an. Falls eine eigene Pipeline das doch braucht, ist der Weg **nicht**, den Automount wieder einzuschalten (das gäbe das Recht *allen* Pipelines), sondern:

1. Im Cluster einen eigenen ServiceAccount mit genau den benötigten Rechten anlegen.
2. Ein Token dafür ausstellen (`kubectl create token <sa> --duration=…`) bzw. ein kubeconfig bauen.
3. Es als **Pipeline-Secret** hinterlegen (UI → Secrets) — der Wert landet über das Per-Run-Secret aus Abschnitt 2a als Env-Var im Pod.
4. In der Pipeline explizit damit konfigurieren (`load_kube_config_from_dict()` / `Configuration(host=…, api_key=…)`).

Das ist ohnehin die saubere Variante: pro Pipeline sichtbar, eng gefasst und widerrufbar, statt eines ambienten Tokens für alles, was im Namespace läuft.

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

# Env kommt aus dem Run-Secret, nicht als Literal in der Spec (siehe 2a)
kubectl get pod "$JOB_POD" -o jsonpath='{.spec.containers[0].env}' | jq .
```

Erwartet: Job **Completed**, Logs ohne Permission-Denied auf `/tmp` oder `/cache`, und in `env` ausschließlich `valueFrom.secretKeyRef` (keine `value`-Felder).

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
| **Alle** Runs `infrastructure_error`, Log zeigt 403 auf `secrets` | RBAC nicht (oder im falschen Namespace) ausgerollt | `kubectl apply -f k8s/rbac-kubernetes-executor.yaml`, dann `kubectl auth can-i create secrets --as=…` — Notausstieg: `KUBERNETES_ENV_VIA_SECRET=false` |
| Run `infrastructure_error`: „Env-Var-Namen sind als Kubernetes-Secret-Keys nicht gültig“ | Key in `default_env`/`encrypted_env` mit Leerzeichen, `=`, `/` o. Ä. | Key umbenennen (Abschnitt 2a) |
| Job-Pod `CreateContainerConfigError`, Event nennt `ff-run-env-…` | Run-Secret fehlt (manuell gelöscht oder ownerReference-Owner weg) | Run neu starten; nicht per Hand in `fastflow-runner`-Secrets eingreifen |

---

## 8. Rollback

Falls das Upgrade Probleme macht:

1. **Images** auf den vorherigen Tag zurücksetzen (`deployment.yaml`, `WORKER_BASE_IMAGE`)
2. **Alte Manifests** aus Git auschecken und `kubectl apply`
3. **`kubectl rollout undo deployment/fastflow-orchestrator`**
4. Bei Cache-Migration: Daten auf `/shared` bleiben erhalten; alte Pfade unter `/app/data/uv_*` sind unverändert
5. Für die Env-Injektion braucht es **keinen** Image-Rollback: `KUBERNETES_ENV_VIA_SECRET=false` reicht (Abschnitt 2a). Danach einmal `kubectl delete secret -l app=fastflow-runner` — das Flag schaltet auch das Löschen ab.

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
| `k8s/rbac-kubernetes-executor.yaml` | ServiceAccount + Role (Jobs/Pods + write-only Secrets) |
| `app/executor/worker_runtime.py` | Gemeinsame Pfade, Security-Builder |
| `app/executor/kubernetes_backend.py` | Job-Specs mit readOnlyRootFS, Per-Run-Env-Secret |
| `app/executor/core.py` | Docker-Worker Security |
| `docker-compose.yaml` | Orchestrator `read_only` + Worker-Image |
| `tests/test_worker_security.py` | Regressionstests |
| `tests/test_kubernetes_env_secret.py` | Regressionstests Env-Secret + RBAC-Tripwire |

---

## Kurz: Minimalablauf Production

```bash
# 1. Build & Push
docker build -t $REGISTRY/fastflow-orchestrator:$TAG .
docker build -f Dockerfile.worker -t $REGISTRY/fastflow-worker:$TAG .
docker push $REGISTRY/fastflow-orchestrator:$TAG
docker push $REGISTRY/fastflow-worker:$TAG

# 2. Config anpassen (Image-Tags, WORKER_BASE_IMAGE, ENVIRONMENT=production)

# 3. RBAC ZUERST + verifizieren (sonst scheitert jeder Run mit 403, siehe 2a)
kubectl apply -f k8s/rbac-kubernetes-executor.yaml
kubectl auth can-i create secrets --as=system:serviceaccount:default:fastflow-executor   # yes
kubectl auth can-i get    secrets --as=system:serviceaccount:default:fastflow-executor   # no

# 4. Deploy
kubectl apply -f k8s/
kubectl rollout restart deployment/fastflow-orchestrator

# 5. Cache migrieren (falls Upgrade von alter Version)

# 6. Smoke-Test: /health, /ready, eine Pipeline starten

# 7. CI: pytest tests/test_worker_security.py tests/test_kubernetes_env_secret.py
```
