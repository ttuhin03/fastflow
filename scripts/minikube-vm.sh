#!/usr/bin/env bash
#
# Fast-Flow: Lokales Kubernetes-Testing mit Minikube in einer VM
# (ohne Docker Desktop – z.B. VirtualBox oder QEMU)
#
# Voraussetzungen:
#   - kubectl, minikube
#   - Ein VM-Treiber: QEMU (Standard), VirtualBox oder VMware
#
# Nutzung:
#   ./scripts/minikube-vm.sh                  # Cluster starten, Images bauen, deployen
#   ./scripts/minikube-vm.sh --no-start      # Cluster läuft schon; nur bauen + deployen
#   ./scripts/minikube-vm.sh --stop          # Minikube-Cluster stoppen
#   ./scripts/minikube-vm.sh --delete-pvcs  # PVCs + zugehörige Deployments löschen (frischer Test)
#   ./scripts/minikube-vm.sh --driver=virtualbox
#
# Optionen:
#   --no-start      Kein minikube start; nur Docker-Env, Build, Apply, Restart
#   --stop          Nur minikube stop (kein kubectl nötig)
#   --delete-pvcs  Löscht fastflow-orchestrator- und postgres-Deployment sowie alle
#                   Fast-Flow-PVCs (fastflow-pvc, postgres-pvc). Danach erneuter Aufruf
#                   ohne Option deployt mit frischen Volumes.
#   --driver=NAME   VM-Treiber: qemu (default), virtualbox, vmware
#   -h, --help      Diese Hilfe anzeigen
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
K8S_DIR="$REPO_ROOT/k8s"

# VM-Driver: virtualbox | qemu | vmware (je nachdem was installiert ist)
MINIKUBE_DRIVER="${MINIKUBE_DRIVER:-qemu}"
# Container-Runtime im Node: Docker wird für Pipeline-Runs (docker-socket-proxy) benötigt
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-docker}"

usage() {
  echo "Usage: $0 [OPTIONS]"
  echo ""
  echo "Options:"
  echo "  --no-start      Cluster läuft schon; nur Images bauen und deployen"
  echo "  --stop          Minikube-Cluster stoppen"
  echo "  --delete-pvcs   Deployments + PVCs löschen (frischer Test, danach erneut deployen)"
  echo "  --driver=NAME   VM-Treiber: qemu (default), virtualbox, vmware"
  echo "  -h, --help       Diese Hilfe anzeigen"
  exit 0
}

STOP_ONLY=false
NO_START=false
DELETE_PVCS=false
for arg in "$@"; do
  case "$arg" in
    --stop)         STOP_ONLY=true ;;
    --no-start)     NO_START=true ;;
    --delete-pvcs)  DELETE_PVCS=true ;;
    --driver=*)     MINIKUBE_DRIVER="${arg#--driver=}" ;;
    -h|--help)      usage ;;
  esac
done

# --delete-pvcs: Deployments löschen (damit PVCs freigegeben werden), dann PVCs löschen
if [ "$DELETE_PVCS" = true ]; then
  echo "Deleting deployments (to release PVCs)..."
  kubectl delete deployment fastflow-orchestrator --ignore-not-found=true --timeout=60s || true
  kubectl delete deployment postgres --ignore-not-found=true --timeout=60s || true
  echo "Waiting for pods to terminate..."
  sleep 5
  echo "Deleting PVCs..."
  kubectl delete pvc fastflow-pvc fastflow-cache-pvc postgres-pvc --ignore-not-found=true --timeout=60s || true
  echo "Done. Run the script again without --delete-pvcs to deploy with fresh volumes."
  exit 0
fi

# Voraussetzungen prüfen (außer bei --stop, damit "minikube stop" auch ohne kubectl funktioniert)
if [ "$STOP_ONLY" != true ]; then
  if ! command -v minikube &>/dev/null; then
    echo "minikube ist nicht installiert oder nicht im PATH."
    echo "Installation (macOS):  brew install minikube"
    echo "Installation (Linux):  https://minikube.sigs.k8s.io/docs/start/"
    exit 1
  fi
  if ! command -v kubectl &>/dev/null; then
    echo "kubectl ist nicht installiert oder nicht im PATH."
    echo "Installation (macOS):  brew install kubectl"
    echo "Installation (Linux):  https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/"
    exit 1
  fi
fi

if [ "$STOP_ONLY" = true ]; then
  echo "Stopping Minikube cluster..."
  minikube stop
  exit 0
fi

# VM-Treiber verfügbar? (vermeidet kryptische Minikube-Fehler)
check_driver() {
  case "$MINIKUBE_DRIVER" in
    docker)
      if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        return 0
      fi
      echo "Docker ist nicht lauffähig (wird für driver=docker benötigt)."
      echo "Docker Desktop oder Colima starten, oder einen VM-Treiber nutzen: --driver=qemu"
      return 1
      ;;
    qemu|qemu2)
      if command -v qemu-system-aarch64 &>/dev/null || command -v qemu-system-x86_64 &>/dev/null; then
        return 0
      fi
      echo "QEMU ist nicht installiert (wird für driver=$MINIKUBE_DRIVER benötigt)."
      echo "Installation (macOS):  brew install qemu"
      echo "Alternativ:  ./scripts/minikube-vm.sh --driver=docker  (ohne VM)"
      return 1
      ;;
    virtualbox)
      if command -v VBoxManage &>/dev/null; then return 0; fi
      echo "VirtualBox ist nicht installiert."
      echo "Download: https://www.virtualbox.org/wiki/Downloads"
      echo "Oder QEMU nutzen:  brew install qemu && ./scripts/minikube-vm.sh --driver=qemu"
      return 1
      ;;
    vmware)
      if command -v vmrun &>/dev/null; then return 0; fi
      echo "VMware (Fusion/Workstation) ist nicht installiert oder nicht im PATH."
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

# Cluster starten (Pipeline-Runs laufen als K8s-Jobs, containerd reicht; Docker-Runtime optional)
if [ "$NO_START" != true ]; then
  check_driver || exit 1
  echo "Starting Minikube with driver=$MINIKUBE_DRIVER, container-runtime=$CONTAINER_RUNTIME..."
  if minikube status &>/dev/null; then
    echo "Cluster already running."
  else
    EXTRA_OPTS=()
    if [ "$MINIKUBE_DRIVER" = "qemu" ] || [ "$MINIKUBE_DRIVER" = "qemu2" ]; then
      # socket_vmnet: VM vom Mac aus erreichbar. Ohne: API oft unter 10.0.2.15, Timeouts möglich.
      if [ -n "${MINIKUBE_NETWORK:-}" ]; then
        EXTRA_OPTS+=(--network="$MINIKUBE_NETWORK")
      elif command -v socket_vmnet &>/dev/null; then
        EXTRA_OPTS+=(--network=socket_vmnet)
      else
        echo "Hinweis: socket_vmnet nicht gefunden. QEMU startet ggf. mit default-Netz (API-Server-Timeouts möglich)."
        echo "  Besser: brew install socket_vmnet && sudo brew services start socket_vmnet"
        echo "  Oder Docker-Treiber (ohne VM): ./scripts/minikube-vm.sh --driver=docker"
      fi
    fi
    if ! minikube start \
      --driver="$MINIKUBE_DRIVER" \
      --container-runtime="$CONTAINER_RUNTIME" \
      --cpus=4 \
      --memory=4096 \
      --disk-size=40g \
      "${EXTRA_OPTS[@]}"; then
      echo ""
      echo "Minikube-Start fehlgeschlagen. Häufige Abhilfe:"
      echo "  1. Altes Profil löschen und erneut starten:"
      echo "     minikube delete"
      echo "     $0"
      echo "  2. Ohne VM (Docker-Desktop/Colima):"
      echo "     $0 --driver=docker"
      echo "  3. QEMU mit explizitem Netzwerk: MINIKUBE_NETWORK=default $0"
      exit 1
    fi
  fi
fi

# Metrics-Server: für CPU/RAM-Anzeige in der UI (Run-Detail + Einstellungen → System-Metriken)
echo "Enabling metrics-server (für CPU/RAM in Run-Detail und Einstellungen)..."
minikube addons enable metrics-server 2>/dev/null || true

# Docker-Env auf Minikube-Node setzen (Image wird im Node gebaut)
echo "Setting Docker env to Minikube node..."
eval "$(minikube docker-env)"

echo "Building fastflow-orchestrator image inside Minikube..."
docker build -t fastflow-orchestrator:latest "$REPO_ROOT"
echo "Building fastflow-worker image (uv + nb_runner für Notebook-Pipelines)..."
docker build -f "$REPO_ROOT/Dockerfile.worker" -t fastflow-worker:latest "$REPO_ROOT"

# Manifests in richtiger Reihenfolge anwenden
echo "Applying Kubernetes manifests..."
kubectl apply -f "$K8S_DIR/pvc.yaml"
kubectl apply -f "$K8S_DIR/postgres.yaml"
kubectl apply -f "$K8S_DIR/secrets.yaml"
kubectl apply -f "$K8S_DIR/configmap.yaml"
kubectl apply -f "$K8S_DIR/rbac-kubernetes-executor.yaml"
# BASE_URL/FRONTEND_URL bleiben aus configmap.yaml (localhost:8000), damit OAuth-Redirect
# bei Nutzung von kubectl port-forward mit der in GitHub eingetragenen Callback-URL übereinstimmt.
# Worker-Image für K8s: enthält /runner (nb_runner.py) für Notebook-Pipelines
kubectl patch configmap fastflow-config --type merge -p '{"data":{"WORKER_BASE_IMAGE":"fastflow-worker:latest"}}'

MINIKUBE_IP="$(minikube ip)"

kubectl apply -f "$K8S_DIR/deployment.yaml"
kubectl apply -f "$K8S_DIR/service.yaml"

# Pods laden Secrets/ConfigMap nur beim Start – Restart damit Änderungen greifen
kubectl rollout restart deployment/fastflow-orchestrator

echo "Waiting for deployment to be ready (timeout 5m)..."
if ! kubectl rollout status deployment/fastflow-orchestrator --timeout=300s; then
  echo ""
  echo "Deployment did not become ready in time. Diagnostics:"
  echo "--- Pods ---"
  kubectl get pods -l app=fastflow-orchestrator -o wide 2>/dev/null || true
  echo ""
  echo "--- Pod status (describe) ---"
  kubectl describe pod -l app=fastflow-orchestrator 2>/dev/null | tail -80
  echo ""
  echo "--- Orchestrator logs ---"
  kubectl logs deploy/fastflow-orchestrator -c orchestrator --tail=60 2>/dev/null || true
  echo ""
  echo "--- Init container (wait-for-postgres) logs ---"
  kubectl logs deploy/fastflow-orchestrator -c wait-for-postgres 2>/dev/null || true
  echo ""
  echo "Tipp: Nach Behebung: kubectl rollout restart deployment/fastflow-orchestrator"
  exit 1
fi

echo ""
echo "Fast-Flow is deployed. Zugriff (OAuth-Callback = BASE_URL = http://localhost:8000):"
echo "  kubectl port-forward svc/fastflow-orchestrator 8000:80"
echo "  Browser: http://localhost:8000"
echo "  In GitHub OAuth App: Callback-URL = http://localhost:8000/api/auth/github/callback"
echo ""
echo "Alternativ direkt (wenn Netz erreichbar): http://${MINIKUBE_IP}:30080"
echo ""
echo "Useful commands:"
echo "  minikube dashboard   # Kubernetes-Dashboard"
echo "  kubectl get pods -l app=fastflow-orchestrator"
echo "  kubectl logs -f deploy/fastflow-orchestrator -c orchestrator"
