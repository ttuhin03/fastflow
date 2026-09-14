# Fast-Flow Helm Chart

Deploys the [Fast-Flow](https://github.com/ttuhin03/fastflow) orchestrator (and,
optionally, a bundled PostgreSQL) onto a Kubernetes cluster. Pipeline runs
execute as native Kubernetes `Jobs` in the release namespace — no Docker
socket or privileged access on the nodes required.

This chart is the Helm-packaged equivalent of the raw manifests in
[`k8s/`](../../k8s); prefer this chart for anything beyond a quick manual test,
since it lets you manage upgrades, rollbacks and per-environment values with
`helm` instead of hand-editing YAML.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- A default `StorageClass` (or set `persistence.*.storageClassName` explicitly)
  for the PVCs, unless you bring your own via `persistence.*.existingClaim`
- Container images: either the published `ghcr.io/ttuhin03/fastflow-*` images
  (public, no pull secret needed) or your own build — see [Images](#images)

## Quick start

```bash
# 1. Generate the two required secrets
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
JWT_SECRET_KEY=$(openssl rand -base64 32)

# 2. Install with at least one OAuth provider configured (GitHub shown here)
helm install fastflow ./helm/fastflow \
  --set secrets.encryptionKey="$ENCRYPTION_KEY" \
  --set secrets.jwtSecretKey="$JWT_SECRET_KEY" \
  --set secrets.github.clientId="<github-oauth-client-id>" \
  --set secrets.github.clientSecret="<github-oauth-client-secret>" \
  --set config.baseUrl="https://fastflow.example.com" \
  --set config.frontendUrl="https://fastflow.example.com"

# 3. Check rollout
kubectl rollout status deployment/fastflow

# 4. Access the app
kubectl port-forward svc/fastflow 8000:80
# -> http://localhost:8000
```

By default the chart installs a bundled single-replica PostgreSQL. To use
SQLite instead (fine for small/single-user setups; data lives on the `data`
PVC), set `postgresql.enabled=false` and leave `externalDatabaseUrl` empty. To
use an external/managed database, set `postgresql.enabled=false` and
`externalDatabaseUrl=postgresql://user:pass@host:5432/db`.

## Required values

Fast-Flow refuses to start without these — set them explicitly (via
`--set`, `-f values-prod.yaml`, or `secrets.existingSecret`, see below):

| Value | Description |
|---|---|
| `secrets.encryptionKey` | Fernet key used to encrypt stored pipeline secrets. Generate with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `secrets.jwtSecretKey` | Session JWT signing key, minimum 32 characters. Generate with `openssl rand -base64 32` |
| At least one OAuth provider | `secrets.github.*`, `secrets.google.*`, `secrets.microsoft.*`, or `secrets.custom.*` — Fast-Flow login is OAuth-only |

Setting `secrets.skipOauthVerification=true` skips verifying the OAuth
credentials against the provider at pod startup (useful in clusters without
outbound internet/DNS from pods) — login in the browser still works.

## Managing secrets outside of Helm (recommended for production)

Rather than passing secrets via `--set`/`values.yaml` (which land in the Helm
release's stored manifest), create the Secret yourself and point the chart at
it:

```bash
kubectl create secret generic fastflow-secrets \
  --from-literal=ENCRYPTION_KEY="$ENCRYPTION_KEY" \
  --from-literal=JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  --from-literal=GITHUB_CLIENT_ID=... \
  --from-literal=GITHUB_CLIENT_SECRET=...
```

```yaml
secrets:
  existingSecret: fastflow-secrets
```

The Secret must use the same keys as [`templates/secret.yaml`](templates/secret.yaml)
(mirrors `.env.example` in the repo root). The same pattern applies to the
database credentials via `postgresql.auth.existingSecret` (keys: `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL`).

## Images

| Value | Default | Notes |
|---|---|---|
| `image.repository` / `image.tag` | `ghcr.io/ttuhin03/fastflow-orchestrator` / Chart `appVersion` | Main app image |
| `worker.image.repository` / `worker.image.tag` | `ghcr.io/ttuhin03/fastflow-worker` / Chart `appVersion` | Used by the orchestrator when starting **notebook** pipeline Jobs (needs `/runner/nb_runner.py`) |

Pinned release images are published to GHCR on every tagged release (see the
repo root README). For a private registry, push your own build and set
`imagePullSecrets`:

```yaml
image:
  repository: your-registry.io/fastflow-orchestrator
  tag: v1.0.7
imagePullSecrets:
  - name: my-registry-cred
```

## Pipeline executor

`executor.type` controls how pipeline runs are executed:

- `kubernetes` (default) — runs pipelines as Kubernetes `Jobs` in the release
  namespace. Requires the RBAC Role/RoleBinding this chart creates
  (`rbac.create=true`) and a `cache` PVC for the shared `uv` cache.
- `docker` — runs pipelines as Docker containers via a Docker socket, matching
  the Docker Compose deployment. Not recommended inside this chart (needs a
  Docker socket or [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)
  sidecar, which this chart does not manage) — use `docker-compose.yaml` in
  the repo root for that instead. The chart drops the Kubernetes-Jobs RBAC and
  cache PVC/mounts when this is set.

## Persistence

| Value | Purpose | Access mode note |
|---|---|---|
| `persistence.data` | SQLite DB (if no Postgres), run logs, git-synced pipeline checkouts | `ReadWriteOnce` is fine — mounted only by the orchestrator pod |
| `persistence.cache` | Shared `uv` package/Python-version cache, mounted into pipeline Job pods | `ReadWriteOnce` works for single-node/Minikube. For a real multi-node cluster, switch to `ReadWriteMany` with an NFS/EFS/CephFS-backed `StorageClass` so Jobs scheduled on other nodes can read the cache |

Bring your own PVC with `persistence.data.existingClaim` /
`persistence.cache.existingClaim` instead of letting the chart create one.

## Ingress

Disabled by default (`ingress.enabled=false`). Example with `cert-manager` +
`nginx`:

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: fastflow.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: fastflow-tls
      hosts:
        - fastflow.example.com

config:
  baseUrl: https://fastflow.example.com
  frontendUrl: https://fastflow.example.com
```

Remember to update the OAuth app's callback URL to
`https://<host>/api/auth/<provider>/callback` after changing `config.baseUrl`.

## Autoscaling

`autoscaling.enabled=true` adds a `HorizontalPodAutoscaler` and removes the
fixed `replicaCount` from the Deployment. Fast-Flow itself is stateless aside
from the shared PVCs, so horizontal scaling of the orchestrator API is safe;
pipeline runs are scheduled as separate Jobs regardless of orchestrator
replica count.

## Values reference

See [`values.yaml`](values.yaml) for the full list with inline comments. Key
sections: `image`/`worker.image`, `executor`, `config` (non-secret env vars,
mirrors `.env.example`), `secrets`, `postgresql`/`externalDatabaseUrl`,
`persistence`, `service`, `ingress`, `autoscaling`, `resources`,
`nodeSelector`/`tolerations`/`affinity`.

## Uninstalling

```bash
helm uninstall fastflow
```

PVCs are not deleted automatically (Helm/Kubernetes default behavior for
PersistentVolumeClaims) — remove them manually if you want to discard data:

```bash
kubectl delete pvc -l app.kubernetes.io/instance=fastflow
```

## Differences from `k8s/`

The chart is templated and namespaced by Helm release name/instance rather
than hardcoded `fastflow-*` names, so multiple releases can coexist in one
cluster. Functionally it's equivalent to `k8s/deployment.yaml`,
`k8s/service.yaml`, `k8s/configmap.yaml`, `k8s/secrets.yaml`, `k8s/pvc.yaml`,
`k8s/postgres.yaml` and `k8s/rbac-kubernetes-executor.yaml` combined, plus
optional Ingress/HPA support that the raw manifests don't have.
