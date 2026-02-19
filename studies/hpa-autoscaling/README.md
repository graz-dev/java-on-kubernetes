# Study: HPA Autoscaling for JVM Services

## Objective

Evaluate how Kubernetes Horizontal Pod Autoscaler (HPA) behaves for Java microservices
under varying load. Understand the interaction between JVM-specific behaviors
(GC pauses, heap warmup) and CPU-based autoscaling decisions.

**Supported applications:**
- **Online Boutique**: HPA on adservice (single JVM service)
- **PetClinic**: HPA on customers-service and visits-service (CPU-intensive Spring Boot workloads)

## Hypothesis

CPU-based HPA may produce suboptimal scaling for JVM workloads because:
- GC activity creates CPU spikes unrelated to actual user load
- JVM startup time (class loading, JIT compilation) means new pods are slow to become effective
- The 80% CPU utilization target may not be the best signal for JVM services

## Setup

### Prerequisites

- Base platform is running (`./setup.sh` completed successfully)
- All pods in `microservices-demo` namespace are Ready
- **Metrics-server installed** (required for HPA to read CPU metrics)

**To install metrics-server:**
```bash
# 1. Install metrics-server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# 2. Patch for Kind (disable TLS verification)
kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/args/-",
    "value": "--kubelet-insecure-tls"
  }
]'

# 3. Verify it's working
kubectl top nodes
```

### Study-Specific Resources

| Resource | Description |
|----------|-------------|
| `adservice-hpa.yaml` | HPA for Online Boutique: adservice at 80% CPU, 1-20 replicas |
| `run-study.sh` | Applies app-specific HPA configuration (detects current app automatically) |
| `scenario-config.yaml` | Spike load pattern to trigger scaling events |
| `dashboard.json` | HPA-specific Grafana dashboard |

**HPA Configuration by Application:**

**Online Boutique:**
- Service: `adservice` (ad retrieval, lightweight)
- Target: 80% CPU
- Replicas: 1-20
- Challenge: Low CPU usage may not trigger scaling

**PetClinic:**
- Service: `customers-service` (database writes, JPA object mapping, CPU-intensive)
  - Target: 70% CPU
  - Replicas: 1-10
- Service: `visits-service` (complex queries, transaction management, I/O-intensive)
  - Target: 70% CPU
  - Replicas: 1-8
- Advantage: High CPU usage under write operations reliably triggers scaling

## Methodology

### Load Profile

A spike-and-ramp pattern designed to trigger multiple scaling events:

1. **Baseline** (10 min): 50 users — establish steady state
2. **Ramp up** (5 min): 200 users — gradual increase
3. **Sustained high** (20 min): 500 users — trigger scale-up, observe stabilization
4. **Drop** (5 min): 200 users — trigger scale-down
5. **Cool down** (10 min): 50 users — return to baseline
6. **Extreme spike** (20 min): 800 users — test aggressive scaling
7. **Recovery** (10 min): 50 users — observe scale-down behavior

### Duration

~80 minutes total.

### Metrics to Observe

1. **JVM Overview dashboard**: Watch heap usage, GC frequency, and thread count during scale events
2. **HPA Autoscaling Study dashboard**: Replica count, CPU utilization vs limits, CPU throttling
3. **Load Test Overview dashboard**: Correlate user count with RPS and response time

### Key Questions

- How quickly does HPA react to load changes?
- Do new pods receive traffic before JVM warmup is complete?
- Is there CPU throttling that could be mistaken for high utilization?
- What is the impact of GC pauses on p95 response time?
- **(PetClinic-specific)**: Do different services (customers vs visits) scale differently based on workload type?
- **(PetClinic-specific)**: How does JPA write overhead affect scaling decisions compared to transaction management?

### Expected Observations

**Online Boutique (adservice):**
- May NOT trigger HPA scaling even under high load (adservice is too lightweight)
- Minimal GC activity, stable heap usage
- Useful for understanding HPA mechanics but limited for JVM performance insights

**PetClinic (customers-service, visits-service):**
- WILL trigger HPA scaling reliably under load
- Moderate to significant GC activity, growing heap usage
- Customers-service: CPU increases during POST/PUT operations (JPA writes, object mapping)
- Visits-service: Sustained CPU during transaction overhead and complex queries
- Spring Boot context initialization affects pod startup time (watch for slow readiness)
- Better for studying JVM performance under real Spring Boot scaling scenarios

## How to Run

The study automatically detects which application is deployed and applies the appropriate HPA configuration.

```bash
# 1. Deploy your preferred application
./setup.sh --app online-boutique   # Lightweight (may not scale much)
# OR
./setup.sh --app petclinic         # CPU-intensive Spring Boot (better for HPA study)

# 2. Apply study resources (HPA, scenario, dashboard)
#    The script will automatically configure HPA for the current app
./studies/hpa-autoscaling/run-study.sh

# 3. Watch HPA scaling in real-time
kubectl get hpa -n microservices-demo -w

# 4. Open the dashboards (exposed automatically, no port-forward needed)
#    Grafana: http://localhost:3000 (admin/admin)
#    Locust:  http://localhost:8089

# 5. When done, tear down study-specific resources
./studies/hpa-autoscaling/run-study.sh teardown
```

**Recommendation:** Use **PetClinic** for this study. The customers-service and visits-service are CPU-intensive Spring Boot services that will reliably trigger HPA scaling under load, providing better insights into JVM performance under autoscaling.

### PetClinic-Specific Setup

PetClinic requires additional configuration for HPA studies to work correctly:

#### 1. Seed the Database

PetClinic starts with an empty database. Without data, services process minimal workload (returning empty arrays) and CPU remains low regardless of request volume.

```bash
# Seed with 50 owners and 100 pets (default)
./applications/petclinic/scripts/seed-database.sh

# Or specify custom count
NUM_OWNERS=100 ./applications/petclinic/scripts/seed-database.sh
```

**Verify:**
```bash
kubectl run test --image=curlimages/curl --rm -i --restart=Never -n microservices-demo \
  -- curl -s http://customers-service:8081/owners | head -c 200

# Should return JSON array with owner objects (not empty)
```

#### 2. Use CPU-Intensive Load Test

The standard PetClinic load test uses 60% read operations and only 15% writes, which doesn't generate enough CPU load to trigger HPA scaling.

**Deploy the intensive variant:**
```bash
# Update load generator to use intensive locustfile (70% writes, 10x faster)
kubectl create configmap locust-tasks \
  --from-file=locustfile.py=applications/petclinic/locust/locustfile-intensive.py \
  -n microservices-demo --dry-run=client -o yaml | kubectl apply -f -

# Set FRONTEND_URL to customers-service (bypass broken API gateway)
kubectl set env deployment/ak-loadgenerator -n microservices-demo \
  FRONTEND_URL=http://customers-service.microservices-demo.svc.cluster.local:8081

# Recreate deployment to pick up ConfigMap changes (subPath mounts don't auto-update)
kubectl delete deployment ak-loadgenerator -n microservices-demo
kubectl apply -f loadgenerator/loadgenerator.yaml
```

**What this changes:**
- **Write operations**: 70% (schedule_visit POST) instead of 15%
- **Request rate**: 10x faster (wait_time 0.1-0.5s instead of 1-3s)
- **Target**: Direct service access (bypasses API gateway 405 errors)

**Verify intensive load is working:**
```bash
# Check that write operations are being made
kubectl port-forward -n microservices-demo svc/ak-loadgenerator 8089:8089 &
curl -s http://localhost:8089/stats/requests | jq '.stats[] | select(.name | contains("visit"))'

# Should show thousands of POST requests to visit endpoints
```

#### 3. Use Aggressive Load Scenario

The default spike scenario may not generate enough users. Use the CPU-intensive scenario:

```bash
kubectl apply -f loadgenerator/scenarios/scenario-cpu-intensive.yaml
```

This ramps users more aggressively: 100 → 500 → 1000 → 1500 → 2000 users.

#### 4. Verify Scaling is Triggered

After 2-3 minutes with the intensive load:

```bash
kubectl get hpa -n microservices-demo

# Expected output (scaling triggered):
NAME                REFERENCE                      TARGETS        MINPODS   MAXPODS   REPLICAS
customers-service   Deployment/customers-service   cpu: 405%/70%  1         10        8
visits-service      Deployment/visits-service      cpu: 475%/70%  1         8         7
```

If CPU remains below 70%, check:
1. Database has data (step 1)
2. Intensive locustfile is loaded (step 2)
3. Load test is making requests (check Locust UI at http://localhost:8089)
4. Write operations are succeeding (not getting 405 errors)

## Results

<!-- Paste screenshots and observations here after running the study -->

## Conclusions

<!-- Summarize findings and recommendations -->
