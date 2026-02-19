#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="jvm-bench"
NAMESPACE="microservices-demo"
MONITORING_NS="monitoring"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# -------------------------------------------------------------------
# 0. Parse arguments
# -------------------------------------------------------------------
APP_NAME="online-boutique"  # Default application

while [[ $# -gt 0 ]]; do
  case $1 in
    --app)
      APP_NAME="$2"
      shift 2
      ;;
    *)
      error "Unknown argument: $1. Usage: $0 [--app <name>]"
      ;;
  esac
done

# Validate app exists
if [ ! -d "$SCRIPT_DIR/applications/$APP_NAME" ]; then
  error "Application '$APP_NAME' not found. Available: $(ls -1 $SCRIPT_DIR/applications/ | grep -v _template | tr '\n' ' ')"
fi

info "Selected application: $APP_NAME"

# -------------------------------------------------------------------
# 1. Prerequisites check
# -------------------------------------------------------------------
info "Checking prerequisites..."

for cmd in docker kind kubectl helm; do
  if ! command -v "$cmd" &>/dev/null; then
    error "'$cmd' is not installed. Please install it before running this script."
  fi
done

if ! docker info &>/dev/null; then
  error "Docker is not running. Please start Docker first."
fi

echo "  docker  $(docker --version | awk '{print $3}' | tr -d ',')"
echo "  kind    $(kind version | awk '{print $2}')"
echo "  kubectl $(kubectl version --client -o json 2>/dev/null | grep gitVersion | awk -F'"' '{print $4}')"
echo "  helm    $(helm version --short)"
echo ""

# Detect architecture
ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64)
    info "Architecture: x86_64 (Intel/AMD)"
    ;;
  arm64|aarch64)
    info "Architecture: arm64 (Apple Silicon)"
    # Check if app has native arm64 support
    case "$APP_NAME" in
      petclinic)
        info "✓ PetClinic has native arm64 images (no emulation needed)"
        ;;
      online-boutique)
        warn "Docker images will run under QEMU emulation (slower startup)"
        warn "For better performance, use: ./setup.sh --app petclinic"
        ;;
      *)
        warn "Docker images may run under QEMU emulation (slower startup)"
        warn "Check applications/$APP_NAME/docker/README.md for native builds"
        ;;
    esac
    ;;
  *)
    warn "Unknown architecture: $ARCH (proceeding anyway)"
    ;;
esac
echo ""

# -------------------------------------------------------------------
# 2. Create Kind cluster
# -------------------------------------------------------------------
if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
  warn "Cluster '$CLUSTER_NAME' already exists. Skipping creation."
else
  info "Creating Kind cluster '$CLUSTER_NAME' (1 control-plane + 2 workers)..."
  kind create cluster --name "$CLUSTER_NAME" --config "$SCRIPT_DIR/kind-config.yaml"
fi

kubectl cluster-info --context "kind-$CLUSTER_NAME"
echo ""

# -------------------------------------------------------------------
# 3. Create namespaces
# -------------------------------------------------------------------
info "Creating namespaces..."
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl create namespace "$MONITORING_NS" --dry-run=client -o yaml | kubectl apply -f -

# -------------------------------------------------------------------
# 4. Install kube-prometheus-stack
# -------------------------------------------------------------------
info "Installing kube-prometheus-stack (Prometheus + Grafana)..."
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts 2>/dev/null || true
helm repo update

if helm status kube-prometheus -n "$MONITORING_NS" &>/dev/null; then
  warn "kube-prometheus-stack already installed. Upgrading..."
  helm upgrade kube-prometheus prometheus-community/kube-prometheus-stack \
    --namespace "$MONITORING_NS" \
    --values "$SCRIPT_DIR/monitoring/kube-prometheus-values.yaml" \
    --wait --timeout 5m
else
  helm install kube-prometheus prometheus-community/kube-prometheus-stack \
    --namespace "$MONITORING_NS" \
    --values "$SCRIPT_DIR/monitoring/kube-prometheus-values.yaml" \
    --wait --timeout 5m
fi

# -------------------------------------------------------------------
# 5. Deploy OTel Collector
# -------------------------------------------------------------------
info "Deploying OpenTelemetry Collector..."
kubectl apply -f "$SCRIPT_DIR/monitoring/otel-collector.yaml"

info "Waiting for OTel Collector to be ready..."
kubectl wait --for=condition=available deployment/otel-collector -n "$MONITORING_NS" --timeout=120s

# -------------------------------------------------------------------
# 6. Deploy ServiceMonitors
# -------------------------------------------------------------------
info "Deploying ServiceMonitors..."
kubectl apply -f "$SCRIPT_DIR/monitoring/servicemonitors.yaml"

# -------------------------------------------------------------------
# 7. Deploy application
# -------------------------------------------------------------------
info "Deploying $APP_NAME application..."
for manifest in "$SCRIPT_DIR/applications/$APP_NAME/kubernetes-manifests"/*.yaml; do
  kubectl apply -f "$manifest" -n "$NAMESPACE"
done

# -------------------------------------------------------------------
# 8. Deploy load generator with a default continuous scenario
# -------------------------------------------------------------------
info "Deploying load generator..."

# Create a default scenario that runs continuously (1 hour with 50 users).
# This ensures JVM metrics are generated from the start.
# Override by applying a different test-scenario ConfigMap before setup,
# or replace it later with a study-specific scenario.
kubectl get configmap test-scenario -n "$NAMESPACE" &>/dev/null || \
kubectl create configmap test-scenario -n "$NAMESPACE" \
  --from-literal=scenario.json='[{"n_users": 50, "spawn_rate": 10, "duration": 3600}]'

# Create ConfigMap with app-specific Locust tasks
info "Loading Locust tasks for $APP_NAME..."
kubectl create configmap locust-tasks \
  --from-file=locustfile.py="$SCRIPT_DIR/applications/$APP_NAME/locust/locustfile.py" \
  -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

# Set FRONTEND_URL based on application
case "$APP_NAME" in
  online-boutique)
    FRONTEND_URL="http://frontend:80"
    ;;
  petclinic)
    FRONTEND_URL="http://api-gateway:8080"
    ;;
  *)
    warn "Unknown app '$APP_NAME', using default FRONTEND_URL"
    FRONTEND_URL="http://frontend:80"
    ;;
esac

# Apply load generator with app-specific FRONTEND_URL
sed "s|__FRONTEND_URL__|${FRONTEND_URL}|g" "$SCRIPT_DIR/loadgenerator/loadgenerator.yaml" | \
  kubectl apply -f -

# -------------------------------------------------------------------
# 9. Import shared Grafana dashboards
# -------------------------------------------------------------------
info "Importing Grafana dashboards..."
for f in "$SCRIPT_DIR"/dashboards/*.json; do
  name=$(basename "$f" .json)
  kubectl create configmap "grafana-dashboard-${name}" \
    --from-file="$(basename "$f")=$f" \
    -n "$MONITORING_NS" \
    --dry-run=client -o yaml | \
    kubectl label --local -f - grafana_dashboard=1 -o yaml | \
    kubectl apply -f -
  echo "  Imported: $name"
done

# -------------------------------------------------------------------
# 10. Wait for all pods to be ready
# -------------------------------------------------------------------
info "Waiting for application pods to be ready (timeout: 5 min)..."
kubectl wait --for=condition=ready pod --all -n "$NAMESPACE" --timeout=300s || \
  warn "Some pods may not be ready yet. Check with: kubectl get pods -n $NAMESPACE"

info "Waiting for monitoring pods to be ready..."
kubectl wait --for=condition=ready pod --all -n "$MONITORING_NS" --timeout=120s || \
  warn "Some monitoring pods may not be ready yet. Check with: kubectl get pods -n $MONITORING_NS"

echo ""
info "============================================"
info "  Setup complete!"
info "============================================"
echo ""
echo "  Application: $APP_NAME"
echo ""
echo "  Access points (available immediately via Kind port mappings):"
echo ""
echo "  Grafana:   http://localhost:3000  (admin / admin)"
echo "  Locust:    http://localhost:8089"

# Show app-specific frontend URL
case "$APP_NAME" in
  online-boutique)
    echo "  Frontend:  http://localhost:8080"
    ;;
  petclinic)
    echo "  API Gateway: http://localhost:8081/api/customer/owners"
    echo "  Eureka UI:   http://localhost:8081/eureka"
    ;;
  *)
    echo "  Frontend:  See applications/$APP_NAME/README.md for endpoints"
    ;;
esac

echo ""
echo "  Load test is running automatically with 50 users."
echo "  JVM metrics will appear in Grafana within 1-2 minutes."
echo ""
echo "  To run a study:  ./studies/hpa-autoscaling/run-study.sh"
echo "  To switch apps:  ./teardown.sh && ./setup.sh --app <name>"
echo "  To tear down:    ./teardown.sh"
echo ""
