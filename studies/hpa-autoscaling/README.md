# Study: HPA Autoscaling for JVM Services

## Objective

Evaluate how Kubernetes Horizontal Pod Autoscaler (HPA) behaves for Java microservices
under varying load. Understand the interaction between JVM-specific behaviors
(GC pauses, heap warmup) and CPU-based autoscaling decisions.

**Supported applications:**
- **Online Boutique**: HPA on adservice (single JVM service)
- **PetClinic**: HPA on petclinic deployment (Spring MVC + Hibernate + H2, CPU-intensive POST workloads)

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
- Service: `petclinic` (Spring MVC WAR on Tomcat 11 — DB writes, Hibernate, OTel instrumentation)
  - Target: 70% CPU
  - Replicas: 1-5
- Advantage: POST visits generate Hibernate transaction + OTel span overhead on a single 500m CPU pod, reliably triggering scaling

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

**PetClinic (petclinic):**
- WILL trigger HPA scaling reliably under intensive POST load
- Moderate GC activity (Serial GC with 500m CPU limit, ~256 MB heap)
- CPU driven by Hibernate transactions, H2 writes, and OTel instrumentation per request
- Tomcat startup + Spring context init + OTel warm-up takes ~60–90 s (watch startup probe)
- Better for studying JVM performance under a real Spring MVC + Hibernate scaling scenario

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

**Recommendation:** Use **PetClinic** for this study. It reliably triggers HPA scaling under intensive POST load, providing clear JVM performance insights under autoscaling.

### PetClinic-Specific Setup

PetClinic (spring-framework-petclinic) ships with pre-populated H2 sample data (10 owners, 13 pets) — **no seeding step required**.

#### 1. Use CPU-Intensive Load Test

The `run-study.sh` script automatically switches to `locustfile-intensive.py` (70% POST visits, 0.1–0.5 s wait). This generates enough Hibernate transaction + OTel instrumentation overhead to push the single pod above the 70% CPU threshold.

**Verify intensive load is working:**
```bash
# Check Locust UI
open http://localhost:8089
# Should show high RPS, mostly POST requests to /owners/{id}/pets/{petId}/visits/new
```

#### 2. Verify Scaling is Triggered

After 2–3 minutes with the intensive load:

```bash
kubectl get hpa -n microservices-demo -w

# Expected output (scaling triggered):
NAME        REFERENCE              TARGETS        MINPODS   MAXPODS   REPLICAS
petclinic   Deployment/petclinic   cpu: 120%/70%  1         5         3
```

If CPU stays below 70%, check:
1. Intensive locustfile is active (Locust UI at http://localhost:8089 shows POST-heavy traffic)
2. Pod has started (startup probe passes — check `kubectl get pods -n microservices-demo`)
3. Requests are succeeding (Locust shows 0% failure rate)

## Results

<!-- Paste screenshots and observations here after running the study -->

## Conclusions

<!-- Summarize findings and recommendations -->
