#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="microservices-demo"
MONITORING_NS="monitoring"
STUDY_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if teardown is requested
if [ "${1:-}" = "teardown" ]; then
  echo "Removing HPA autoscaling study resources..."
  kubectl delete hpa --all -n "$NAMESPACE" --ignore-not-found
  kubectl delete configmap test-scenario -n "$NAMESPACE" --ignore-not-found
  kubectl delete configmap grafana-dashboard-hpa-autoscaling -n "$MONITORING_NS" --ignore-not-found
  kubectl delete pod -l app=ak-loadgenerator -n "$NAMESPACE" --ignore-not-found
  echo "Teardown complete."
  exit 0
fi

# Detect current application
echo "Detecting deployed application..."
CURRENT_APP=$(kubectl get deployment -n "$NAMESPACE" -l app-type -o jsonpath='{.items[0].metadata.labels.app-type}' 2>/dev/null || echo "unknown")

if [ "$CURRENT_APP" = "unknown" ]; then
  echo "❌ ERROR: No application detected. Please run ./setup.sh first."
  exit 1
fi

echo "✓ Detected application: $CURRENT_APP"
echo ""

echo "=== HPA Autoscaling Study ==="
echo ""

# PetClinic-specific setup (automated)
if [ "$CURRENT_APP" = "petclinic" ]; then
  echo "=== PetClinic-Specific Setup (Automated) ==="
  echo ""

  # Check metrics-server
  echo "[Setup 1/4] Checking metrics-server..."
  if kubectl get deployment metrics-server -n kube-system &>/dev/null; then
    echo "  ✓ metrics-server already installed"
  else
    echo "  → Installing metrics-server..."
    kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml >/dev/null 2>&1
    kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
      {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}
    ]' >/dev/null 2>&1
    echo "  → Waiting for metrics-server to be ready..."
    kubectl wait --for=condition=ready pod -l k8s-app=metrics-server -n kube-system --timeout=60s >/dev/null 2>&1 || true
    echo "  ✓ metrics-server installed"
  fi

  # Seed database
  echo "[Setup 2/4] Seeding database..."
  OWNER_COUNT=$(kubectl run test-seed-check --image=curlimages/curl --rm -i --restart=Never -n "$NAMESPACE" -- curl -s http://customers-service:8081/owners 2>/dev/null | grep -o '"id"' | wc -l | tr -d ' ' || echo "0")

  if [ "$OWNER_COUNT" -gt 10 ]; then
    echo "  ✓ Database already has data ($OWNER_COUNT entries)"
  else
    echo "  → Seeding database with 50 owners and 100 pets..."
    kubectl run petclinic-seeder --image=curlimages/curl --rm -i --restart=Never -n "$NAMESPACE" -- sh -c '
      BASE="http://customers-service:8081"
      for i in $(seq 1 50); do
        OWNER_JSON="{\"firstName\":\"Owner$i\",\"lastName\":\"Test\",\"address\":\"${i} Main St\",\"city\":\"Boston\",\"telephone\":\"617000$(printf \"%04d\" $i)\"}"
        OWNER_ID=$(curl -s -X POST "$BASE/owners" -H "Content-Type: application/json" -d "$OWNER_JSON" | grep -o "\"id\":[0-9]*" | cut -d: -f2)
        if [ -n "$OWNER_ID" ]; then
          curl -s -X POST "$BASE/owners/$OWNER_ID/pets" -H "Content-Type: application/json" \
            -d "{\"name\":\"Pet${i}A\",\"birthDate\":\"2020-01-15\",\"type\":{\"name\":\"dog\"}}" > /dev/null
          curl -s -X POST "$BASE/owners/$OWNER_ID/pets" -H "Content-Type: application/json" \
            -d "{\"name\":\"Pet${i}B\",\"birthDate\":\"2021-06-20\",\"type\":{\"name\":\"cat\"}}" > /dev/null
        fi
      done
    ' 2>&1 | grep -v "command prompt" >/dev/null
    echo "  ✓ Database seeded successfully"
  fi

  # Deploy intensive load test
  echo "[Setup 3/4] Deploying CPU-intensive load test..."
  REPO_ROOT="$(cd "$STUDY_DIR/../.." && pwd)"
  kubectl create configmap locust-tasks \
    --from-file=locustfile.py="$REPO_ROOT/applications/petclinic/locust/locustfile-intensive.py" \
    -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

  echo "  ✓ Intensive load test configured (will set FRONTEND_URL after deployment restart)"

  # Apply CPU-intensive scenario
  echo "[Setup 4/4] Applying aggressive load scenario..."
  kubectl apply -f "$REPO_ROOT/loadgenerator/scenarios/scenario-cpu-intensive.yaml" >/dev/null
  echo "  ✓ Aggressive scenario applied (100→500→1000→1500→2000 users)"

  echo ""
  echo "=== PetClinic Setup Complete ==="
  echo "  ✓ Metrics-server ready"
  echo "  ✓ Database populated with test data"
  echo "  ✓ CPU-intensive load test (70% writes, 10x faster)"
  echo "  ✓ Aggressive user ramp (up to 2000 users)"
  echo ""
fi

# 1. Apply HPA based on current application
echo "[1/4] Applying HPA configuration..."

case "$CURRENT_APP" in
  online-boutique)
    echo "  → Configuring HPA for adservice (Online Boutique)"
    kubectl apply -f "$STUDY_DIR/adservice-hpa.yaml"
    ;;
  petclinic)
    echo "  → Configuring HPA for CPU-intensive PetClinic services (customers-service, visits-service)"
    # Create HPA for customers-service (CPU-intensive: database writes, JPA operations)
    cat <<EOF | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: customers-service
  namespace: $NAMESPACE
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: customers-service
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF
    # Create HPA for visits-service (CPU-intensive: complex queries, transactions)
    cat <<EOF | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: visits-service
  namespace: $NAMESPACE
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: visits-service
  minReplicas: 1
  maxReplicas: 8
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF
    ;;
  *)
    echo "❌ ERROR: Unknown application '$CURRENT_APP'"
    exit 1
    ;;
esac

# 2. Apply load scenario
echo "[2/4] Applying load scenario..."
kubectl apply -f "$STUDY_DIR/scenario-config.yaml"

# 3. Import study-specific dashboard
echo "[3/4] Importing Grafana dashboard..."
kubectl create configmap grafana-dashboard-hpa-autoscaling \
  --from-file=hpa-autoscaling.json="$STUDY_DIR/dashboard.json" \
  -n "$MONITORING_NS" \
  --dry-run=client -o yaml | \
  kubectl label --local -f - grafana_dashboard=1 -o yaml | \
  kubectl apply -f -

# 4. Restart loadgenerator to pick up new scenario
echo "[4/4] Restarting load generator..."
if [ "$CURRENT_APP" = "petclinic" ]; then
  # PetClinic: Need to recreate deployment (subPath mounts don't auto-update)
  REPO_ROOT="$(cd "$STUDY_DIR/../.." && pwd)"
  kubectl delete deployment ak-loadgenerator -n "$NAMESPACE" --ignore-not-found >/dev/null
  kubectl apply -f "$REPO_ROOT/loadgenerator/loadgenerator.yaml" >/dev/null

  # Set FRONTEND_URL after deployment is created (otherwise it gets reset)
  kubectl set env deployment/ak-loadgenerator -n "$NAMESPACE" \
    FRONTEND_URL=http://customers-service.microservices-demo.svc.cluster.local:8081 >/dev/null 2>&1

  echo "  → Waiting for load generator to be ready..."
  kubectl wait --for=condition=available deployment/ak-loadgenerator -n "$NAMESPACE" --timeout=120s >/dev/null
else
  # Online Boutique: Just restart pods
  kubectl delete pod -l app=ak-loadgenerator -n "$NAMESPACE"
fi

echo ""
echo "=== Study is running ==="
echo ""
echo "Application: $CURRENT_APP"

case "$CURRENT_APP" in
  online-boutique)
    echo "HPA target:  adservice (80% CPU, 1-20 replicas)"
    ;;
  petclinic)
    echo "HPA targets:"
    echo "  - customers-service (70% CPU, 1-10 replicas) - Database writes, JPA"
    echo "  - visits-service (70% CPU, 1-8 replicas) - Complex queries, transactions"
    ;;
esac

echo ""
echo "Monitor via Grafana dashboards:"
echo "  - JVM Overview:           heap, GC, threads (compare across replicas)"
echo "  - HPA Autoscaling Study:  replica count, CPU, throttling"
echo "  - Load Test Overview:     users, RPS, response time"
echo ""
echo "Watch HPA status:"
echo "  kubectl get hpa -n $NAMESPACE -w"
echo ""
echo "Access Grafana:  http://localhost:3000"
echo "Access Locust:   http://localhost:8089"
if [ "$CURRENT_APP" = "petclinic" ]; then
  echo "Access Eureka:   http://localhost:8761"
fi
echo ""
echo "To tear down: $0 teardown"
