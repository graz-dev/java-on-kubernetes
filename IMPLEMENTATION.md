# Implementation Guide

This document explains every component of the JVM Benchmarking Starter Pack in detail.
It covers the architecture, the reasoning behind each design choice, and the full data flow
from application startup to metrics appearing in Grafana dashboards.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Multi-Application Architecture](#multi-application-architecture)
3. [Cross-Architecture Deployment](#cross-architecture-deployment)
4. [Kind Cluster Configuration](#kind-cluster-configuration)
5. [Node Isolation Strategy](#node-isolation-strategy)
6. [Application Stack (Online Boutique)](#application-stack-online-boutique)
7. [Application Stack (PetClinic)](#application-stack-petclinic)
8. [JVM Instrumentation Pipeline](#jvm-instrumentation-pipeline)
9. [Monitoring Stack](#monitoring-stack)
10. [Load Generator](#load-generator)
11. [Grafana Dashboards](#grafana-dashboards)
12. [Studies Framework](#studies-framework)
13. [Setup and Teardown Scripts](#setup-and-teardown-scripts)
14. [Troubleshooting](#troubleshooting)

---

## High-Level Architecture

The system runs entirely inside a local [Kind](https://kind.sigs.k8s.io/) (Kubernetes in Docker)
cluster. It consists of three layers:

```
┌─────────────────────────────────────────────────────────────────────┐
│                  Kind Cluster (jvm-bench)                           │
│                                                                     │
│  ┌─── Node: workload ─────────────────────────────────────────┐    │
│  │  Online Boutique (11 microservices)                        │    │
│  │  adservice (Java/JVM) ← benchmark target with OTel agent  │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─── Node: tools ────────────────────────────────────────────┐    │
│  │  Prometheus + Grafana (kube-prometheus-stack)               │    │
│  │  OpenTelemetry Collector                                    │    │
│  │  Locust Load Generator                                      │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  ┌─── Node: control-plane ────────────────────────────────────┐    │
│  │  Kubernetes API server, etcd, scheduler, etc.               │    │
│  │  Port mappings: 3000→Grafana, 8089→Locust, 8080→Frontend   │    │
│  └────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
adservice (Java 25 + OTel Agent v2.25.0)
    │
    │ OTLP/gRPC (port 4317)
    ▼
OTel Collector (monitoring namespace)
    │
    │ Prometheus Remote Write
    ▼
Prometheus (monitoring namespace)
    │
    │ PromQL queries
    ▼
Grafana dashboards (JVM Overview, Load Test Overview)
```

---

## Multi-Application Architecture

The framework supports multiple applications, following the same pattern as the studies framework. Each application is self-contained in `applications/<app-name>/`.

### Design Philosophy

**Why multi-application support?**

Different JVM applications exhibit different performance characteristics. A simple ad service that does HashMap lookups will never trigger the same GC behavior, memory pressure, or CPU patterns as a complex application with BCrypt authentication, image caching, or matrix computations.

**The Online Boutique Problem:** The adservice (Google's microservices demo) is too lightweight for realistic JVM benchmarking. It rarely hits CPU thresholds for HPA scaling, has minimal GC activity, and doesn't stress the heap.

**The Solution:** Add Spring Framework PetClinic, a well-maintained Spring MVC WAR application with realistic workloads (Hibernate DB writes, Spring Cache, OTel instrumentation). Runs on Tomcat 11, supports native arm64, and easy Java version upgrades via `--java-version`.

### Application Directory Structure

```
applications/
├── _template/                       # Template for adding new apps
│   ├── README.md                    # Guide for creating a new app
│   ├── kubernetes-manifests/
│   │   └── app.yaml                 # Example manifest
│   └── locust/
│       └── locustfile.py            # Example Locust file
│
├── online-boutique/                 # Google's microservices demo
│   ├── README.md                    # Architecture, services, endpoints
│   ├── kubernetes-manifests/
│   │   └── online-boutique.yaml     # 11 services (1 JVM)
│   └── locust/
│       └── locustfile.py            # E-commerce user flow
│
└── petclinic/                       # Spring Framework PetClinic (single WAR)
    ├── README.md                    # Architecture, endpoints, load testing
    ├── kubernetes-manifests/
    │   └── petclinic.yaml           # 1 service (Spring MVC WAR on Tomcat 11)
    ├── locust/
    │   ├── locustfile.py            # Web UI user flow (HTML endpoints)
    │   └── locustfile-intensive.py  # CPU-intensive variant for HPA
    └── docker/                      # Optional: build with custom Java version
        ├── README.md
        ├── Dockerfile               # WAR + Tomcat 11 + jvm-entrypoint.sh
        ├── build-images.sh          # Maven + Docker build script
        └── jvm-entrypoint.sh        # Captures JVM flags at startup
```

### Application Selection Mechanism

The `setup.sh` script accepts an `--app` parameter:

```bash
./setup.sh                          # Default: online-boutique
./setup.sh --app online-boutique    # Explicit
./setup.sh --app petclinic          # Use PetClinic
```

**Implementation details:**

1. **App validation**: `setup.sh` checks if `applications/$APP_NAME/` exists and fails fast with a clear error listing available apps.

2. **Dynamic manifest loading**: Instead of hardcoding `app/kubernetes-manifest.yaml`, the script loops over all YAML files in `applications/$APP_NAME/kubernetes-manifests/*.yaml`.

3. **App-specific Locust files**: A ConfigMap named `locust-tasks` is created from `applications/$APP_NAME/locust/locustfile.py` and mounted into the load generator.

4. **App-specific FRONTEND_URL**: The load generator's `FRONTEND_URL` environment variable is set based on the app:
   - Online Boutique: `http://frontend:80`
   - PetClinic: `http://petclinic:8080`

5. **App-type labels**: All Kubernetes manifests include `app-type: <app-name>` labels for identification. This enables:
   - Studies to validate they're running on the correct app
   - Dashboards to filter by app type
   - Troubleshooting commands to identify which app is deployed

### Load Generator Integration

The load generator is **app-agnostic**. It's a shared deployment that changes behavior based on which locustfile is mounted:

```yaml
volumes:
  - name: locust-tasks
    configMap:
      name: locust-tasks   # Created by setup.sh from app-specific file
```

The locustfile defines realistic user behavior for each app:
- **Online Boutique**: Browse homepage → view products → add to cart → checkout
- **PetClinic**: Browse owners → view owner details → schedule visits → browse vets

### Adding a New Application

1. **Copy the template:**
   ```bash
   cp -r applications/_template applications/my-app
   ```

2. **Create Kubernetes manifests** in `kubernetes-manifests/`:
   - Add `app-type: my-app` label to all resources
   - Add `nodeSelector: {node-role: workload}` to app services
   - Add OTel Java agent injection to JVM services (see PetClinic example)
   - Define appropriate resource requests/limits
   - Add startup/readiness/liveness probes

3. **Create Locust file** in `locust/locustfile.py`:
   - Define realistic user workflows
   - Use task weights to model conversion funnels
   - Add appropriate wait times between requests

4. **Document the app** in `README.md`:
   - Architecture diagram
   - Service descriptions (language, purpose, workload type)
   - Endpoints for manual testing
   - Expected performance characteristics

5. **Update `setup.sh`** if needed (add FRONTEND_URL case):
   ```bash
   my-app)
     FRONTEND_URL="http://my-service:8080/path"
     ;;
   ```

6. **Test the app**:
   ```bash
   ./setup.sh --app my-app
   kubectl get pods -n microservices-demo  # All ready?
   curl http://localhost:8080/...           # Frontend accessible?
   ```

### Comparison: Online Boutique vs PetClinic

| Aspect | Online Boutique | PetClinic |
|--------|-----------------|----------|
| **JVM Services** | 1 (adservice) | 1 (petclinic — Spring MVC WAR on Tomcat 11) |
| **Workload Types** | Ad retrieval (HashMap lookup) | DB writes (Hibernate), JOIN queries, Spring Cache, JSP rendering |
| **CPU Usage** | Low (~5-10% even under high load) | High under write load (POST visits triggers Hibernate + H2 + OTel) |
| **GC Activity** | Minimal (young gen GC only, <10ms pauses) | Moderate (Hibernate entity allocation, young gen GC under load) |
| **Heap Usage** | Stable (~100-150 MB) | Moderate (~400-700 MB; Tomcat + Spring ctx + OTel agent) |
| **HPA Scaling** | Rarely triggers (CPU too low) | Reliably triggers at load (70% POST visits) |
| **arm64 Support** | QEMU emulation only | Official image amd64 only (QEMU); custom build native arm64 |
| **Java Version** | N/A (gRPC service) | Java 17 (official image), custom build any version |
| **Best For** | Simple setup, learning | Realistic benchmarking, single-service HPA studies |

**Recommendation:** Use PetClinic for serious benchmarking. Use Online Boutique only for testing the framework itself or learning Kubernetes observability basics.

---

## Cross-Architecture Deployment

The framework runs on both **x86_64 (Intel/AMD)** and **arm64 (Apple Silicon)** architectures.

**PetClinic** has official **multi-arch images** (both amd64 and arm64) that run natively on all architectures. **Online Boutique** images are amd64-only and require QEMU emulation on arm64.

### The Challenge

Kind runs Kubernetes inside Docker. When you deploy an amd64 image on an arm64 host (Apple Silicon Mac), Docker uses QEMU to emulate x86_64 instructions. This works, but has performance implications.

### Architecture Detection

The `setup.sh` script automatically detects the host architecture:

```bash
ARCH=$(uname -m)
case "$ARCH" in
  x86_64|amd64)
    info "Architecture: x86_64 (Intel/AMD)"
    ;;
  arm64|aarch64)
    info "Architecture: arm64 (Apple Silicon)"
    warn "Docker images will run under QEMU emulation (slower startup)"
    warn "For native performance, see: applications/$APP_NAME/docker/README.md"
    ;;
  *)
    warn "Unknown architecture: $ARCH (proceeding anyway)"
    ;;
esac
```

### Performance Impact

| Metric | x86_64 (Native) | arm64 (QEMU Emulation) |
|--------|----------------|------------------------|
| **JVM Startup Time** | 30-45 seconds | 60-90 seconds |
| **Image Pull + Init** | ~20 seconds | ~35 seconds |
| **Runtime CPU Performance** | 100% | 70-80% |
| **Memory Overhead** | None | ~10-15% |
| **GC Behavior** | Native | Slightly slower, but patterns similar |

**Key Insight:** QEMU emulation affects **absolute** performance, but **relative** patterns remain consistent. You can still:
- Observe GC frequency and pause duration trends
- Measure heap usage and allocation rates
- Identify CPU bottlenecks and thread contention
- Test HPA scaling behavior (just with higher thresholds)

### When QEMU Emulation Is Acceptable

For most use cases, running under emulation is fine:
- **Learning and experimentation**: Understanding Kubernetes, Prometheus, Grafana, load testing
- **Local development**: Testing changes to manifests, dashboards, or studies
- **Relative comparisons**: Comparing different GC algorithms, heap sizes, or JVM flags on the same host

**When you need native performance:**
- **Precise latency measurements**: Sub-millisecond GC pause analysis
- **Startup time benchmarking**: Comparing JVM startup optimizations
- **Maximum throughput tests**: Stress testing with thousands of requests per second
- **Production simulation**: Matching production environment performance exactly

### Building with Java 25 (Optional)

Each application's `docker/` directory contains instructions for building custom images from source.

**Example: PetClinic with Java 25**

The official PetClinic images use Java 17. To benchmark with Java 25, you can build from source:

1. **Prerequisites:**
   - Java 25+ (OpenJDK or Eclipse Temurin)
   - Maven 3.9+
   - Docker Desktop (with multi-platform support)
   - ~2 GB disk space
   - ~20-30 minutes build time (first build downloads dependencies)

2. **Build process (automated):**
   ```bash
   cd applications/petclinic/docker
   ./build-images.sh --load-to-kind
   ```

3. **Build process (manual):**
   ```bash
   # Clone spring-framework-petclinic repository
   git clone --depth 1 https://github.com/spring-petclinic/spring-framework-petclinic.git /tmp/petclinic-build
   cd /tmp/petclinic-build

   # Build the WAR with Maven (or via Docker if local Java absent)
   mvn clean package -DskipTests
   # WAR output: target/petclinic.war  (finalName set in pom.xml)

   # Prepare Docker build context
   mkdir /tmp/ctx
   cp target/petclinic.war /tmp/ctx/spring-framework-petclinic.war
   cp applications/petclinic/docker/jvm-entrypoint.sh /tmp/ctx/

   # Build Docker image (native architecture)
   docker build --platform linux/arm64 \
     --build-arg JAVA_VERSION=25 \
     -t localhost/spring-framework-petclinic:java25-arm64 \
     -f applications/petclinic/docker/Dockerfile \
     /tmp/ctx/

   # Load image into Kind
   kind load docker-image localhost/spring-framework-petclinic:java25-arm64 --name jvm-bench
   ```

4. **Update manifest to use local image:**
   `setup.sh` automatically substitutes `springcommunity/spring-framework-petclinic:latest` → `localhost/spring-framework-petclinic:java25-arm64` when `--java-version 25` is passed.

**Status:** Automated build script available at `applications/petclinic/docker/build-images.sh`. See `applications/petclinic/docker/README.md` for detailed manual build instructions.

### Troubleshooting Architecture Issues

**Symptoms of QEMU issues:**
- Very slow pod startup (>5 minutes)
- Startup probe failures (`CrashLoopBackOff` before JVM finishes starting)
- Unexpected timeouts during health checks

**Solutions:**
1. **Increase startup probe failure threshold:**
   ```yaml
   startupProbe:
     failureThreshold: 30   # Increase from 18 on arm64
   ```

2. **Accept slower performance:**
   - Just wait longer for pods to become ready
   - Reduce load test intensity (fewer users)
   - Use longer observation windows for metrics to stabilize

3. **Build native images:**
   - Follow the instructions in `applications/<app>/docker/README.md`

**Check if emulation is active:**
```bash
docker inspect $(docker ps -q --filter name=jvm-bench-worker) | grep Architecture
# arm64 host running amd64 images will show: "Architecture": "amd64"
```

---

## Kind Cluster Configuration

**File:** `kind-config.yaml`

The cluster has 3 nodes:

| Node | Role | Purpose |
|------|------|---------|
| control-plane | Kubernetes control plane | Runs API server, scheduler, etcd. Also handles port mappings to the host. |
| worker-1 | `node-role: workload` | Runs application services (Online Boutique or PetClinic). |
| worker-2 | `node-role: tools` | Runs Prometheus, Grafana, OTel Collector, Locust. |

### Port Mappings

Kind uses `extraPortMappings` on the control-plane node to expose services to `localhost`.
This works by mapping a host port to a NodePort on the control-plane container:

| Host Port | NodePort | Service |
|-----------|----------|---------|
| `localhost:3000` | 30300 | Grafana |
| `localhost:8089` | 30899 | Locust Web UI |
| `localhost:8080` | 30080 | Online Boutique Frontend |
| `localhost:8081` | 30081 | PetClinic API Gateway |

**How it works:** Kind runs Kubernetes nodes as Docker containers. The `extraPortMappings`
directive tells Docker to forward traffic from the host to the control-plane container.
Kubernetes then routes NodePort traffic from the control-plane to the actual pods on the
worker nodes via kube-proxy.

**Why only on control-plane?** Kind only supports `extraPortMappings` on the control-plane
node. NodePort services are accessible from any node in the cluster, so traffic arriving
at the control-plane's NodePort is correctly routed to the pod regardless of which worker
node it runs on.

---

## Node Isolation Strategy

Application pods and monitoring/tooling pods run on separate nodes. This is enforced via
Kubernetes `nodeSelector` on every deployment:

```yaml
# Application services
nodeSelector:
  node-role: workload

# Monitoring and load generation
nodeSelector:
  node-role: tools
```

**Why this matters for benchmarking:**
- Prometheus, Grafana, and OTel Collector consume CPU and memory. If they share a node
  with the application, they can steal resources and distort benchmark results.
- The load generator (Locust) is CPU-intensive. Running it on the same node as the app
  would artificially limit the load it can generate and compete with application pods.
- With isolation, CPU/memory metrics from the workload node reflect only the application
  behavior, making measurements more reliable.

---

## Application Stack (Online Boutique)

**File:** `applications/online-boutique/kubernetes-manifests/online-boutique.yaml`

The application is [Google Cloud's Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo)
v0.10.4, a polyglot microservices demo simulating an e-commerce store.

### Services

| Service | Language | Port | Description |
|---------|----------|------|-------------|
| frontend | Go | 8080 | Web UI, proxies to all backend services |
| checkoutservice | Go | 5050 | Orchestrates the checkout flow |
| cartservice | C# | 7070 | Shopping cart backed by Redis |
| redis-cart | Redis | 6379 | In-memory cart storage |
| productcatalogservice | Go | 3550 | Product listing and search |
| currencyservice | Node.js | 7000 | Currency conversion |
| paymentservice | Node.js | 50051 | Payment processing (mock) |
| shippingservice | Go | 50051 | Shipping cost calculation |
| emailservice | Python | 8080 | Order confirmation emails (mock) |
| recommendationservice | Python | 8080 | Product recommendations |
| **adservice** | **Java** | **9555** | **Ad serving — JVM benchmark target** |

### Modifications from Upstream

The manifest was adapted from the upstream v0.10.4 release with these changes:

1. **Node selectors**: All services use `nodeSelector: node-role: workload` (upstream uses
   no selectors or cloud-specific ones).

2. **Frontend service type**: Changed from `LoadBalancer` (cloud-only) to `NodePort: 30080`
   so it's accessible via Kind port mappings.

3. **Load generator removed**: The upstream includes a built-in load generator. It was removed
   from this manifest because we use a separate, more configurable Locust deployment.

4. **adservice JVM instrumentation**: This is the most significant change. See the next section.

5. **cartservice probes**: Added `startupProbe` with `failureThreshold: 10` and increased
   probe `timeoutSeconds` to 3. The default 1-second timeout caused CrashLoopBackOff on
   resource-constrained Kind clusters. Memory limit increased from 128Mi to 256Mi.

---

## Application Stack (PetClinic)

**File:** `applications/petclinic/kubernetes-manifests/petclinic.yaml`

Spring Framework PetClinic is the classic Spring MVC + JSP veterinary clinic application.
It runs as a single WAR on Tomcat 11 with H2 in-memory database pre-populated at startup.

**Source**: https://github.com/spring-petclinic/spring-framework-petclinic

### Architecture

```
┌─────────────────────────────────────┐
│  petclinic (NodePort 30081)         │
│  Spring Framework 7.0.3             │
│  Spring MVC + JSP                   │
│  Tomcat 11 (embedded via WAR)       │
│  Hibernate / Spring Data JPA        │
│  H2 in-memory DB (pre-populated)    │
│  OTel Java agent v2.10.0            │
└─────────────────────────────────────┘
```

No service discovery. No config server. One pod.

### Key Facts

| Property | Value |
|----------|-------|
| Official image | `springcommunity/spring-framework-petclinic:latest` |
| Default Java | 17 (amd64 only; custom builds for arm64 or other versions) |
| Port | 8080 (NodePort 30081 → `http://localhost:8081`) |
| Sample owners | 10 (IDs 1–10), pre-loaded at startup |
| Sample pets | 13 (IDs 1–13) |

### Workload Characteristics

| Endpoint | Workload Type | CPU Driver |
|----------|--------------|------------|
| `GET /owners?lastName=` | DB query + JSP render | Hibernate, JDBC |
| `GET /owners/{id}` | JOIN query (owner+pets+visits) | Hibernate eager load |
| `POST .../visits/new` | DB insert + redirect | Hibernate transaction, OTel instrumentation |
| `GET /vets` | Spring Cache hit | Minimal (cached) |

**Why this matters for benchmarking:**
- **POST visits** is the primary HPA trigger: each request runs a Hibernate transaction, OTel span, and H2 write — all on a single pod with a 500m CPU limit
- **Single HPA target**: simpler than multi-service setup, deterministic scaling behaviour
- **Pre-populated data**: no seeding step needed, load tests work immediately after pod startup

### Modifications from Upstream

The manifest adapts `springcommunity/spring-framework-petclinic:latest` for Kubernetes:

1. **OTel Java agent injection**: Init container (`busybox:1.36`) downloads OTel agent v2.10.0 via `wget`, shares it via `emptyDir` volume. `JAVA_TOOL_OPTIONS=-javaagent:/otel/opentelemetry-javaagent.jar` loads it automatically.

2. **Resource limits**: `cpu: 200m–500m, memory: 512Mi–1Gi` — higher memory than individual microservices because Tomcat + Spring + Hibernate + OTel all share one heap.

3. **Startup probe**: `httpGet /owners/find, failureThreshold: 36` — allows up to 6 minutes for Tomcat startup + Spring context init + OTel agent warm-up.

4. **NodePort 30081**: Exposed on host as `http://localhost:8081`, matching the previous API gateway port so Kind port mappings are unchanged.

5. **App-type labels**: `app-type: petclinic` on all resources for study scripts to detect.

6. **JVM configuration entrypoint** (custom builds): `jvm-entrypoint.sh` is the Docker `ENTRYPOINT` in custom images. It runs `java -XX:+PrintFlagsFinal`, extracts GC algorithm, heap sizes, JIT settings, and injects them as `OTEL_RESOURCE_ATTRIBUTES`. See [JVM Configuration Capture](#jvm-configuration-capture).

### Endpoints

**Web UI:** `http://localhost:8081`

| URL | Description |
|-----|-------------|
| `http://localhost:8081/owners?lastName=` | All owners list |
| `http://localhost:8081/owners/{id}` | Owner detail (pets + visits) |
| `http://localhost:8081/vets` | Vet list |
| `http://localhost:8081/owners/find` | Owner search form (also used as health probe) |

### Performance Expectations

Under intensive load (100–200 concurrent users, 70% POST visits, 0.1–0.5 s wait):

| Metric | Expected |
|--------|---------|
| CPU usage | 80–200% (exceeds 500m limit → throttling visible) |
| Heap usage | 400–700 MB |
| GC frequency | Moderate young-gen GC (Hibernate entity allocation) |
| HPA scale-out | 1 → 3–5 replicas within ~2 min |

---

## JVM Instrumentation Pipeline

This is the core of the benchmarking framework. It enables JVM metrics collection from the
adservice without modifying the application source code.

### The Problem

The Google adservice Docker image (`adservice:v0.10.4`) ships as a pre-built Java application.
It does **not** include any OpenTelemetry SDK or agent. The image uses **Eclipse Temurin JDK 25**
(Java 25 LTS), which has strict module encapsulation.

### The Solution: Init Container + Java Agent

We inject the OpenTelemetry Java agent into the adservice pod at runtime using a Kubernetes
init container pattern:

```yaml
initContainers:
  - name: otel-agent
    image: busybox:1.36
    command: ['wget', '-O', '/otel/opentelemetry-javaagent.jar',
      'https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/download/v2.25.0/opentelemetry-javaagent.jar']
    volumeMounts:
      - name: otel-agent
        mountPath: /otel
```

**How it works:**
1. Before the main container starts, the init container downloads the OTel Java agent JAR
   (~23 MB) from GitHub Releases into a shared `emptyDir` volume at `/otel/`.
2. The main container mounts the same volume at `/otel/` (read-only).
3. The `JAVA_TOOL_OPTIONS` environment variable tells the JVM to load the agent:
   ```
   JAVA_TOOL_OPTIONS=-javaagent:/otel/opentelemetry-javaagent.jar
   ```
4. `JAVA_TOOL_OPTIONS` is a standard JVM mechanism — the JVM automatically picks it up
   without any changes to the application entrypoint or Dockerfile.

### Why v2.25.0?

The OTel Java agent version matters because of JDK compatibility:

| Agent Version | Issue with adservice (Java 25) |
|---------------|-------------------------------|
| v2.8.0 | `InaccessibleObjectException` — agent tries to access `java.lang.ClassLoader.findLoadedClass` via reflection, blocked by Java 25 module system |
| v2.12.0 | `NoClassDefFoundError: GrpcSingletons` — gRPC instrumentation module incompatible |
| v2.25.0 | Works correctly. Built with Java 25 support (experimental). Minor warnings about `sun.misc.Unsafe` deprecation in Netty are harmless. |

### Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `JAVA_TOOL_OPTIONS` | `-javaagent:/otel/opentelemetry-javaagent.jar` | Loads the OTel agent into the JVM |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.monitoring:4317` | Where to send telemetry (OTel Collector in monitoring namespace) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | Use gRPC protocol (port 4317). The default `http/protobuf` uses port 4318. |
| `OTEL_SERVICE_NAME` | `adservice` | Identifies this service in metrics |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace=microservices-demo` | Adds namespace context to all metrics |
| `OTEL_METRICS_EXPORTER` | `otlp` | Export metrics via OTLP (to the Collector) |
| `OTEL_LOGS_EXPORTER` | `none` | Disable log export (not needed for benchmarking) |
| `OTEL_INSTRUMENTATION_GRPC_ENABLED` | `true` | Enable gRPC auto-instrumentation |

### Probes

The OTel agent adds approximately 50-60 seconds to JVM startup because it instruments all
loaded classes via bytecode manipulation. Standard readiness/liveness probes would kill the
pod before it finishes starting. The solution is a `startupProbe`:

```yaml
startupProbe:
  grpc:
    port: 9555
  initialDelaySeconds: 10
  periodSeconds: 10
  failureThreshold: 18   # 10 + 18*10 = up to 190 seconds to start
readinessProbe:
  periodSeconds: 15
  grpc:
    port: 9555
livenessProbe:
  periodSeconds: 15
  grpc:
    port: 9555
```

The `startupProbe` runs first. Only after it succeeds do the `readinessProbe` and
`livenessProbe` take over. This gives the JVM up to ~190 seconds to start without
being killed.

### Resource Limits

```yaml
resources:
  requests:
    cpu: 200m
    memory: 300Mi
  limits:
    cpu: 300m
    memory: 512Mi
```

The OTel agent adds ~100-150 MB of memory overhead on top of the base application (~150 MB).
The upstream default of 180Mi/300Mi is insufficient and causes OOM kills.

### JVM Metrics Produced

The OTel Java agent automatically exports these JVM metrics via OTLP:

| Metric Name | Type | Description |
|-------------|------|-------------|
| `jvm_memory_used_bytes` | Gauge | Memory used, with labels `jvm_memory_type` (heap/non_heap) and `jvm_memory_pool_name` (Eden, Survivor, Old Gen, Metaspace, etc.) |
| `jvm_memory_committed_bytes` | Gauge | Memory committed by the JVM |
| `jvm_memory_limit_bytes` | Gauge | Maximum memory available (-1 if unlimited) |
| `jvm_memory_used_after_last_gc_bytes` | Gauge | Memory used after the last GC cycle |
| `jvm_gc_duration_seconds` | Histogram | GC pause duration, with label `jvm_gc_name` (e.g., G1 Young Generation) |
| `jvm_thread_count` | Gauge | Active thread count, with label `jvm_thread_daemon` (true/false) |
| `jvm_cpu_recent_utilization_ratio` | Gauge | Recent CPU utilization (0.0 to 1.0) |
| `jvm_cpu_time_seconds_total` | Counter | Total CPU time consumed |
| `jvm_cpu_count` | Gauge | Number of available processors |
| `jvm_class_count` | Gauge | Currently loaded classes |
| `jvm_class_loaded_total` | Counter | Total classes loaded since JVM start |
| `jvm_class_unloaded_total` | Counter | Total classes unloaded |

**Important label note:** OTel metrics use `host_name` (not `pod`) to identify the pod.
The value of `host_name` is the Kubernetes pod name (e.g., `adservice-f94b6b478-c5r7r`).
All Grafana dashboard queries use `host_name` for filtering.

---

## JVM Configuration Capture

Beyond standard runtime metrics (heap, GC, CPU), the platform captures the **actual JVM configuration** at pod startup and surfaces it as Prometheus labels on every metric. This makes the Grafana JVM Overview dashboard show a per-pod config table without any hardcoding — the configuration is discovered dynamically from the running JVM.

### End-to-End Pipeline

```
1. build-images.sh injects jvm-entrypoint.sh as Docker ENTRYPOINT
        │
        ▼
2. Pod starts → jvm-entrypoint.sh runs first
        │
        ▼
3. env -u JAVA_TOOL_OPTIONS java -XX:+PrintFlagsFinal -version
   (JAVA_TOOL_OPTIONS unset to skip OTel agent — probe exits in milliseconds)
        │
        ▼
4. Parse flags with awk → build OTEL_RESOURCE_ATTRIBUTES string
   e.g. "jvm.config.gc=G1GC,jvm.config.heap.max=536870912,..."
        │
        ▼
5. export OTEL_RESOURCE_ATTRIBUTES (appended to any existing K8s-set attrs)
        │
        ▼
6. exec /opt/tomcat/bin/catalina.sh run
   (Tomcat starts; OTel agent loads via JAVA_TOOL_OPTIONS)
        │
        ▼
7. OTel agent reads OTEL_RESOURCE_ATTRIBUTES → attaches as resource attributes
   to ALL JVM metrics exported via OTLP
        │
        ▼
8. OTel Collector: resource_to_telemetry_conversion: enabled: true
   Converts resource attrs → Prometheus labels (dots → underscores)
   jvm.config.gc → jvm_config_gc
        │
        ▼
9. Prometheus stores metrics with jvm_config_* labels on every time series
        │
        ▼
10. Grafana panel 201: group by (jvm_config_gc, ...) → labelsToFields → table
```

### The jvm-entrypoint.sh Script

**File:** `applications/petclinic/docker/jvm-entrypoint.sh`

**Why unset `JAVA_TOOL_OPTIONS` for the probe?** The env var contains the OTel agent path (`-javaagent:/otel/opentelemetry-javaagent.jar`). If kept, the probe JVM would spend ~30 seconds loading and initializing the agent, then fail to connect to the Collector (the process exits immediately). By unsetting it, the probe exits in milliseconds with only the flags output.

**Flag extraction** uses awk with exact field-name matching (field 2 in `PrintFlagsFinal` output):
```sh
get_flag() {
  echo "$FLAGS" | awk -v f="$1" '$2 == f { print $4; exit }'
}
```

### Captured Flags

| OTel Attribute | JVM Flag | Description |
|----------------|----------|-------------|
| `jvm.config.gc` | `UseG1GC` / `UseZGC` / etc. | Active GC algorithm (G1GC, ZGC, Shenandoah, Parallel, Serial) |
| `jvm.config.heap.max` | `MaxHeapSize` | Maximum heap in bytes |
| `jvm.config.heap.init` | `InitialHeapSize` | Initial heap in bytes |
| `jvm.config.gc.max.pause.ms` | `MaxGCPauseMillis` | GC pause target (ms) |
| `jvm.config.gc.threads.parallel` | `ParallelGCThreads` | Parallel GC thread count |
| `jvm.config.gc.threads.concurrent` | `ConcGCThreads` | Concurrent GC thread count |
| `jvm.config.gc.g1.region.bytes` | `G1HeapRegionSize` | G1 heap region size in bytes |
| `jvm.config.jit.tiered` | `TieredCompilation` | Tiered JIT compilation on/off |
| `jvm.config.jit.compilers` | `CICompilerCount` | Number of JIT compiler threads |
| `jvm.config.compressed.oops` | `UseCompressedOops` | Compressed object pointers on/off |
| `jvm.config.cpu.count` | `ActiveProcessorCount` | CPU count visible to the JVM |

### Label Propagation: OTel Attribute → Prometheus Label

The OTel Collector's `resource_to_telemetry_conversion: enabled: true` setting converts every OTel resource attribute into a Prometheus label on **every metric** the service exports. The transformation is dots → underscores:

| OTel Resource Attribute | Prometheus Label |
|-------------------------|-----------------|
| `jvm.config.gc` | `jvm_config_gc` |
| `jvm.config.heap.max` | `jvm_config_heap_max` |
| `process.runtime.version` | `process_runtime_version` |

Because resource attributes are attached at the service level, **every** JVM metric (heap, GC, CPU, threads, classes) automatically carries these labels. You can filter or group by JVM configuration across all metric types.

### Integration with build-images.sh

`build-images.sh` appends the `jvm-entrypoint.sh` injection to the PetClinic `docker/Dockerfile` at build time:
1. Copies `jvm-entrypoint.sh` into the Docker build context
2. Adds `COPY jvm-entrypoint.sh /jvm-entrypoint.sh` and `RUN chmod +x /jvm-entrypoint.sh` to the Dockerfile
3. Replaces the default `ENTRYPOINT` with `ENTRYPOINT ["/jvm-entrypoint.sh"]`

This approach is non-invasive: the spring-framework-petclinic source is not modified. The entrypoint wraps the Tomcat launch command (`/opt/tomcat/bin/catalina.sh run`).

---

## Monitoring Stack

### Prometheus + Grafana (kube-prometheus-stack)

**File:** `monitoring/kube-prometheus-values.yaml`

Installed via the [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
Helm chart, which bundles:

- **Prometheus Operator**: Manages Prometheus instances and ServiceMonitors
- **Prometheus**: Metrics storage and query engine
- **Grafana**: Dashboard visualization
- **kube-state-metrics**: Kubernetes object metrics (deployments, pods, HPAs)
- **node-exporter**: Node-level CPU, memory, disk, network metrics

#### Key Configuration Choices

| Setting | Value | Why |
|---------|-------|-----|
| `enableRemoteWriteReceiver: true` | Allows OTel Collector to push metrics | OTel Collector exports via Prometheus Remote Write API |
| `serviceMonitorSelectorNilUsesHelmValues: false` | Scrape all ServiceMonitors | Without this, Prometheus only scrapes monitors with specific labels matching the Helm release |
| `defaultDashboardsEnabled: false` | No default Grafana dashboards | The default dashboards (50+) clutter the UI. We provide our own focused dashboards. |
| `alertmanager.enabled: false` | No alerting | Not needed for benchmarking |
| `grafana.sidecar.dashboards.enabled: true` | Auto-import dashboards from ConfigMaps | Any ConfigMap with label `grafana_dashboard=1` is automatically loaded as a dashboard |
| `retention: 7d` | Keep metrics for 7 days | Enough for multiple benchmark runs |

### OpenTelemetry Collector

**File:** `monitoring/otel-collector.yaml`

The OTel Collector acts as a telemetry gateway between the application and Prometheus.

```
adservice ──OTLP/gRPC──→ OTel Collector ──Remote Write──→ Prometheus
                              │
                              └──traces──→ debug (logs to stdout)
```

#### Configuration

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317    # gRPC receiver
      http:
        endpoint: 0.0.0.0:4318    # HTTP receiver (unused but available)

processors:
  batch:
    timeout: 10s                   # Buffer metrics for 10s before sending
  memory_limiter:
    check_interval: 5s
    limit_mib: 256                 # Hard memory limit

exporters:
  prometheusremotewrite:
    endpoint: "http://kube-prometheus-kube-prome-prometheus.monitoring:9090/api/v1/write"
    resource_to_telemetry_conversion:
      enabled: true                # Converts OTel resource attributes to Prometheus labels
  debug:
    verbosity: basic               # Traces are logged to stdout for debugging
```

**Why use a Collector instead of direct Prometheus scraping?**
- The OTel Java agent exports metrics via OTLP push, not Prometheus pull. A Collector
  bridges this gap.
- `resource_to_telemetry_conversion: enabled: true` is critical: it converts OTel resource
  attributes (like `host_name`, `service_name`) into Prometheus labels. Without this,
  you cannot filter by pod or service in queries.

**Why `prometheusremotewrite` instead of the `prometheus` exporter?**
- The `prometheus` exporter creates a scrape endpoint that Prometheus must be configured to
  scrape. This adds latency and complexity.
- `prometheusremotewrite` pushes directly to Prometheus's Remote Write API, which is simpler
  and has lower latency.

#### Traces Pipeline

The traces pipeline exists to prevent OTel Collector startup errors. The OTel Java agent
sends both metrics and traces. If the Collector has no traces pipeline configured, it logs
errors. The `debug` exporter logs trace spans to stdout with minimal overhead.

### ServiceMonitors

**File:** `monitoring/servicemonitors.yaml`

Defines a `ServiceMonitor` for the Locust load generator metrics exporter:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: locust-monitor
  namespace: microservices-demo
spec:
  selector:
    matchLabels:
      app: ak-loadgenerator
  endpoints:
    - port: metrics        # Port 9646 (locust-exporter sidecar)
      interval: 15s
```

This tells Prometheus to scrape the Locust exporter sidecar every 15 seconds, making
load test metrics (users, RPS, response times) available in Grafana.

---

## Load Generator

**File:** `loadgenerator/loadgenerator.yaml`

The load generator is a custom [Locust](https://locust.io/) deployment with two containers:

1. **main**: The Locust master that runs load test scenarios against the frontend
2. **locust-exporter**: A sidecar that scrapes Locust's API and exposes metrics in
   Prometheus format on port 9646

### How Scenarios Work

The load generator reads a JSON scenario file mounted from a Kubernetes ConfigMap:

```json
[
  {"n_users": 50, "spawn_rate": 10, "duration": 600},
  {"n_users": 200, "spawn_rate": 20, "duration": 300}
]
```

Each phase defines:
- `n_users`: Target number of concurrent users
- `spawn_rate`: Users spawned per second until `n_users` is reached
- `duration`: How long this phase lasts (seconds)

The phases run sequentially. When all phases complete, the test stops.

### Default Scenario

The `setup.sh` script creates a default scenario if none exists:

```json
[{"n_users": 50, "spawn_rate": 10, "duration": 3600}]
```

This runs 50 concurrent users for 1 hour, ensuring continuous traffic from the moment
the cluster is ready. This is essential because JVM metrics like GC frequency and heap
usage are more meaningful under load.

### Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `RUN_ONLINE` | `True` | Auto-start the test from the scenario file (no manual UI interaction needed) |
| `SCENARIO_JSON` | `scenario.json` | Filename of the scenario inside `/scenarios/` |
| `FRONTEND_URL` | **App-specific** (set by setup.sh) | Target URL for load testing |
| `LOCUST_URL` | `http://0.0.0.0:8089` | Locust web UI listen address |

**FRONTEND_URL values by application:**
- **Online Boutique**: `http://frontend:80`
- **PetClinic**: `http://petclinic:8080`

The `setup.sh` script uses `sed` to replace `__FRONTEND_URL__` placeholder in the manifest with the app-specific URL before applying.

### App-Specific Locust Files

The load generator is **app-agnostic** — it doesn't have a hardcoded Locust file. Instead, `setup.sh` creates a ConfigMap with the app-specific locustfile:

```bash
kubectl create configmap locust-tasks \
  --from-file=locustfile.py="applications/$APP_NAME/locust/locustfile.py" \
  -n microservices-demo
```

This ConfigMap is mounted at `/locust/locustfile.py` in the load generator container.

**Online Boutique locustfile:**
- Browse homepage (triggers ad service)
- View product pages (triggers product catalog, currency, recommendation services)
- Add products to cart (triggers cart service)
- Complete checkout (triggers checkout orchestrator, payment, shipping, email services)

**PetClinic locustfile:**
- Browse owners (40% of traffic) — `GET /owners?lastName=` DB query + JSP render
- View owner details (30% of traffic) — `GET /owners/{id}` JOIN query with pets + visits
- Submit new visit (20% of traffic) — `POST .../visits/new` DB insert, OTel instrumented
- Browse vets (10% of traffic) — `GET /vets` Spring Cache hit (very cheap)

**Task weights** model realistic conversion funnels (many browsers, few buyers).

### Changing the Scenario

To change the load pattern without redeploying:

```bash
# Create/update the ConfigMap
kubectl create configmap test-scenario -n microservices-demo \
  --from-literal=scenario.json='[{"n_users": 100, "spawn_rate": 5, "duration": 1800}]' \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart the load generator to pick up the new scenario
kubectl rollout restart deployment/ak-loadgenerator -n microservices-demo
```

Or use the Locust Web UI at http://localhost:8089 to manually start/stop/configure tests.

---

## Grafana Dashboards

Dashboards are stored as JSON files in `dashboards/` and imported into Grafana as ConfigMaps
with the label `grafana_dashboard=1`. Grafana's sidecar container watches for these ConfigMaps
and auto-imports them.

### JVM Overview Dashboard

**File:** `dashboards/jvm-overview.json`
**UID:** `jvm-overview`

This is the primary dashboard for JVM benchmarking. It has 5 rows: a runtime info table at the top, plus 4 metric sections with 8 panels.

#### JVM Runtime Info (Panel 201)

A **table panel** at the top of the dashboard showing the actual JVM configuration of every running pod — GC algorithm, heap sizes, JIT settings, and more. The data comes from `jvm_config_*` Prometheus labels injected at startup by `jvm-entrypoint.sh`.

**PromQL query** (deduplicates by grouping labels, tolerates metric gaps with `last_over_time`):
```promql
group by (host_name, process_runtime_version, jvm_config_gc, jvm_config_heap_max, jvm_config_heap_init,
          jvm_config_gc_max_pause_ms, jvm_config_gc_threads_parallel, jvm_config_gc_threads_concurrent,
          jvm_config_gc_g1_region_bytes, jvm_config_jit_tiered, jvm_config_jit_compilers,
          jvm_config_compressed_oops, jvm_config_cpu_count)
  (last_over_time(jvm_memory_used_bytes{host_name=~"$pod"}[5m]))
```

**Transformations:**
1. `labelsToFields` (mode: columns) — turns each Prometheus label into a separate column
2. `organize` — renames labels to human-readable headers (`jvm_config_gc` → `GC`, `jvm_config_heap_max` → `Max Heap`), hides `Time` and `Value`, defines column order

**Unit overrides:** `Max Heap`, `Init Heap`, and `G1 Region` columns use the `bytes` unit so Grafana auto-formats them (e.g. `512 MiB`).

See [JVM Configuration Capture](#jvm-configuration-capture) for how these labels are produced.

#### Heap Memory
- **Heap Memory (Used / Committed / Limit)**: Shows total heap usage with committed (orange
  dashed) and limit (red dashed) reference lines. Aggregated by pod.
- **Heap Memory by Pool**: Stacked area chart showing Eden Space, Survivor Space, and
  Old Gen individually. Useful for understanding GC generation behavior.

#### Garbage Collection
- **GC Frequency (events/sec)**: Bar chart showing GC events per second. Separates young
  and old generation GC by the `jvm_gc_name` label.
- **GC Pause Duration**: Line chart showing average and p99 GC pause duration. Long pauses
  (>100ms) indicate GC pressure and potential latency issues.

#### Threads & CPU
- **Thread Count**: Shows total threads split by daemon/non-daemon. A rapidly increasing
  thread count may indicate a thread leak.
- **CPU Usage**: Shows `jvm_cpu_recent_utilization_ratio` (0-1 scale) and
  `jvm_cpu_time_seconds_total` rate. The first is instantaneous, the second is smoothed.

#### Non-Heap Memory & Classes
- **Non-Heap Memory**: Stacked chart of Metaspace, CodeHeap, and Compressed Class Space.
  Metaspace growth after warmup may indicate a class loader leak.
- **Loaded Classes**: Current class count and class loading rate. Should stabilize after
  JVM warmup.

#### Template Variables

| Variable | Source | Purpose |
|----------|--------|---------|
| `datasource` | Auto-detected Prometheus instances | Select which Prometheus to query |
| `pod` | `label_values(jvm_memory_used_bytes, host_name)` | Filter by pod (uses `host_name` label from OTel) |

### Load Test Overview Dashboard

**File:** `dashboards/load-test-overview.json`
**UID:** `load-test-overview`

Cluster-wide dashboard showing:
- Locust active users, RPS, and response time percentiles
- Node CPU and memory usage by node role (workload vs tools)
- Pod-level CPU and memory for the application namespace

---

## Studies Framework

Studies are self-contained benchmark experiments. Each study lives in `studies/<name>/` and
contains everything needed to run, observe, and document the experiment.

### Study Structure

```
studies/<name>/
├── README.md              # Methodology, hypothesis, results
├── run-study.sh           # Apply/teardown Kubernetes resources
├── scenario-config.yaml   # Load scenario ConfigMap
├── *.yaml                 # Study-specific K8s resources (HPA, resource limits, etc.)
└── dashboard.json         # Study-specific Grafana dashboard
```

### Creating a New Study

```bash
cp -r studies/_template studies/my-new-study
```

Then edit the files:
1. `README.md`: Define your hypothesis and methodology
2. `scenario-config.yaml`: Design a load pattern that tests your hypothesis
3. Add any Kubernetes resources needed (HPA, resource quotas, config changes)
4. `dashboard.json`: Create or adapt a Grafana dashboard for the metrics you need
5. `run-study.sh`: Script that applies/tears down all resources

### Example: HPA Autoscaling Study

**Directory:** `studies/hpa-autoscaling/`

**Prerequisite:** This study requires **metrics-server** to be installed. HPA cannot read CPU metrics without it. See [Troubleshooting](#hpa-not-showing-cpu-metrics-shows-unknown) for installation instructions.

**Hypothesis:** CPU-based HPA may be suboptimal for JVM workloads because:
1. GC activity inflates CPU metrics without indicating real load
2. JVM startup time (class loading, JIT compilation) means new pods aren't immediately useful
3. JVM memory is mostly committed upfront, so memory-based scaling doesn't work

**Load Pattern (7 phases, ~80 minutes):**
1. Baseline: 50 users for 10 min
2. Ramp up: 200 users for 5 min
3. Sustained high: 500 users for 20 min
4. Drop: 200 users for 5 min
5. Cool down: 50 users for 10 min
6. Extreme spike: 800 users for 20 min
7. Recovery: 50 users for 10 min

**Resources applied:**
- `adservice-hpa.yaml`: HPA targeting 80% CPU, 1-20 replicas

**Study-specific dashboard panels:**
- HPA desired vs actual replicas
- CPU utilization vs 80% target
- Per-pod CPU usage (shows new pods warming up)
- CPU throttling (container cgroup limits)
- Pod restart counts

### Running a Study

```bash
# Apply study resources and start the load test
./studies/hpa-autoscaling/run-study.sh

# Monitor via Grafana (http://localhost:3000)

# Clean up when done
./studies/hpa-autoscaling/run-study.sh teardown
```

The `run-study.sh` script:
1. Applies the HPA configuration
2. Replaces the load scenario ConfigMap with the study scenario
3. Imports the study dashboard into Grafana
4. Restarts the load generator to pick up the new scenario

---

## Setup and Teardown Scripts

### setup.sh

The bootstrap script creates the entire environment from scratch. It is idempotent — running
it again will skip already-completed steps.

**Execution order (and why it matters):**

| Step | Action | Wait? | Why this order |
|------|--------|-------|----------------|
| 1 | Check prerequisites (docker, kind, kubectl, helm) | — | Fail fast if tools are missing |
| 2 | Create Kind cluster | Yes | Everything depends on the cluster existing |
| 3 | Create namespaces | — | Resources need their namespaces |
| 4 | Install kube-prometheus-stack | Yes (`--wait`) | Prometheus must be running before OTel Collector can push metrics |
| 5 | Deploy OTel Collector | Yes (`kubectl wait`) | Collector must be ready before adservice starts sending OTLP data |
| 6 | Deploy ServiceMonitors | — | Tells Prometheus what to scrape |
| 7 | Deploy application | — | adservice init container downloads OTel agent (~30s) |
| 8 | Deploy load generator | — | Starts load test automatically with default scenario |
| 9 | Import Grafana dashboards | — | Creates ConfigMaps that Grafana sidecar picks up |
| 10 | Wait for all pods | Yes | Final readiness check |

**Time to complete:** Approximately 5-8 minutes on first run (depends on image pull speed).
Subsequent runs with cached images take ~3 minutes.

### teardown.sh

Simply deletes the Kind cluster:

```bash
kind delete cluster --name jvm-bench
```

This removes all Docker containers, networks, and volumes associated with the cluster.
All data (Prometheus metrics, Grafana dashboards) is lost.

---

## Troubleshooting

### JVM metrics not appearing in Grafana

**Check 1: Is the OTel agent loaded?**
```bash
kubectl logs -n microservices-demo -l app=adservice -c server | head -5
```
You should see:
```
Picked up JAVA_TOOL_OPTIONS: -javaagent:/otel/opentelemetry-javaagent.jar
[otel.javaagent ...] INFO ... opentelemetry-javaagent - version: 2.25.0
```
If you see "OpenTelemetry Javaagent failed to start", the agent version is incompatible
with the JDK version in the adservice image.

**Check 2: Is the init container downloading the agent?**
```bash
kubectl logs -n microservices-demo -l app=adservice -c otel-agent
```
You should see the wget download completing successfully.

**Check 3: Is the OTel Collector running?**
```bash
kubectl logs -n monitoring -l app=otel-collector --tail=20
```
Look for "Everything is ready. Begin running and processing data."

**Check 4: Are metrics in Prometheus?**
```bash
kubectl exec -n monitoring prometheus-kube-prometheus-kube-prome-prometheus-0 \
  -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/query?query=jvm_memory_used_bytes'
```
If the result array is empty, metrics are not flowing from the Collector to Prometheus.

**Check 5: Is Prometheus Remote Write enabled?**
```bash
kubectl exec -n monitoring prometheus-kube-prometheus-kube-prome-prometheus-0 \
  -c prometheus -- wget -qO- 'http://localhost:9090/api/v1/status/config' | grep remote_write
```

### adservice keeps restarting

The OTel Java agent adds 50-60 seconds to startup. Check:
1. The `startupProbe` must have sufficient `failureThreshold` (18 × 10s = 180s window)
2. Memory limit must be at least 512Mi (agent adds ~150MB overhead)
3. `readOnlyRootFilesystem` must be `false` (agent needs temp files)

### cartservice CrashLoopBackOff

Usually caused by gRPC health check timeout (default 1s is too short under load). Ensure:
- `timeoutSeconds: 3` on readiness and liveness probes
- `startupProbe` configured with sufficient delay
- Memory limit at least 256Mi

### Load test not generating traffic

Check if the load generator is running and the scenario ConfigMap exists:
```bash
kubectl get configmap test-scenario -n microservices-demo -o jsonpath='{.data.scenario\.json}'
kubectl logs -n microservices-demo -l app=ak-loadgenerator -c main --tail=20
```

### Grafana dashboards missing

Verify ConfigMaps exist with the correct label:
```bash
kubectl get configmap -n monitoring -l grafana_dashboard=1
```
If dashboards don't appear, restart the Grafana pod to force the sidecar to rescan:
```bash
kubectl rollout restart deployment/kube-prometheus-grafana -n monitoring
```

### PetClinic pod not starting

**Problem: Pod stuck at 0/1 READY or startup probe failing**

**Root causes and fixes:**

1. **OTel agent init slow**: The init container downloads the OTel agent JAR (~23 MB). On slow networks, this may take 1–2 minutes.
   - Verify: `kubectl logs -n microservices-demo deployment/petclinic -c download-otel-agent`

2. **Tomcat startup slow**: Tomcat + Spring context + Hibernate + OTel agent initialisation can take 1–3 minutes.
   - Startup probe `failureThreshold: 36` (6 minutes total) should be enough.
   - Verify: `kubectl describe pod -n microservices-demo <pod-name> | grep "Startup probe failed"`

3. **Out of Memory (OOMKilled)**: Tomcat + Spring + Hibernate + OTel agent needs ~400–700 MB.
   - Memory limit is 1Gi. If OOMKilled: `kubectl get pods -n microservices-demo | grep OOMKilled`

**Debugging:**
```bash
# Check pod status
kubectl get pods -n microservices-demo -l app=petclinic

# Check logs
kubectl logs -n microservices-demo deployment/petclinic --tail=50

# Test endpoint directly
kubectl exec -n microservices-demo deployment/petclinic -- \
  wget -qO- http://localhost:8080/owners/find | head -c 200
```

### HPA not showing CPU metrics (shows `<unknown>`)

**Problem:** HPA displays `cpu: <unknown>/70%` instead of actual CPU values.

**Root cause:** Metrics Server is not installed. HPA requires the Kubernetes Metrics API (`metrics.k8s.io/v1beta1`) to read CPU/memory utilization, but this API is provided by metrics-server, which is NOT included in Kind clusters by default.

**Solution:** Install metrics-server with TLS verification disabled (required for Kind):
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

# 3. Wait for metrics-server to start
kubectl wait --for=condition=ready pod -l k8s-app=metrics-server -n kube-system --timeout=60s

# 4. Verify metrics are available
kubectl top nodes
kubectl top pods -n microservices-demo
```

**Verification:**
```bash
# Check HPA status (should show actual CPU percentages)
kubectl get hpa -n microservices-demo

# Expected output (petclinic):
# NAME       REFERENCE              TARGETS   MINPODS  MAXPODS  REPLICAS
# petclinic  Deployment/petclinic   8%/70%    1        5        1
```

**Note:** The `setup.sh` script does NOT install metrics-server automatically because it's only needed for HPA-based studies. Studies that use HPA should document this prerequisite in their README.

### PetClinic: Load test not CPU-intensive enough for HPA

**Problem:** Standard load test (40% reads, 20% writes, 1–3 s wait) may not generate enough CPU load under low user counts.

**Solution:** Use the intensive locustfile variant (via `run-study.sh`, which sets it automatically):
```bash
# Apply manually:
kubectl create configmap locust-tasks \
  --from-file=locustfile.py=applications/petclinic/locust/locustfile-intensive.py \
  -n microservices-demo --dry-run=client -o yaml | kubectl apply -f -

kubectl delete deployment ak-loadgenerator -n microservices-demo
kubectl apply -f loadgenerator/loadgenerator.yaml
kubectl set env deployment/ak-loadgenerator -n microservices-demo \
  FRONTEND_URL=http://petclinic.microservices-demo.svc.cluster.local:8080
```

**Key differences in intensive version:**
- **70% POST visits** (Hibernate insert + OTel span) instead of 20%
- **10x faster wait time**: `between(0.1, 0.5)` instead of `between(1, 3)`

**Expected results (150–200 users, intensive):**
```bash
kubectl get hpa -n microservices-demo
# NAME       REFERENCE              TARGETS       MINPODS  MAXPODS  REPLICAS
# petclinic  Deployment/petclinic   cpu: 180%/70% 1        5        3
```

### ConfigMap changes not reflected in pods with subPath mounts

**Problem:** After updating a ConfigMap, pods don't see the new content when the ConfigMap is mounted with `subPath`.

**Root cause:** Kubernetes doesn't update subPath mounts when ConfigMaps change (this is by design for atomicity). Regular directory mounts get updated via symlinks, but subPath mounts are hardlinked at pod creation time.

**Solution:** Force pod recreation after ConfigMap changes:
```bash
# Delete the deployment (not just pods)
kubectl delete deployment ak-loadgenerator -n microservices-demo

# Reapply the manifest (creates new deployment)
kubectl apply -f loadgenerator/loadgenerator.yaml
```

Simply deleting pods is not enough - you must delete and recreate the deployment itself.

**In our case:** The loadgenerator mounts the locustfile ConfigMap with `subPath: "locustfile.py"` to `/loadgen/locustfile.py`, so updates require deployment recreation.

---

## File Reference

| File | Description |
|------|-------------|
| `setup.sh` | One-command cluster bootstrap |
| `teardown.sh` | Destroy the cluster |
| `kind-config.yaml` | Kind cluster: 3 nodes + port mappings |
| `applications/petclinic/docker/Dockerfile` | WAR + Tomcat 11 image with optional Java version |
| `applications/petclinic/docker/build-images.sh` | Maven + Docker build script (Java version selectable, Docker-based Maven fallback) |
| `applications/petclinic/docker/jvm-entrypoint.sh` | Docker entrypoint: captures JVM flags at startup, launches Tomcat with OTel agent |
| `applications/online-boutique/kubernetes-manifests/online-boutique.yaml` | Online Boutique (11 services) with OTel agent on adservice |
| `monitoring/kube-prometheus-values.yaml` | Helm values for Prometheus + Grafana |
| `monitoring/otel-collector.yaml` | OTel Collector: ConfigMap + Deployment + Service |
| `monitoring/servicemonitors.yaml` | Prometheus ServiceMonitor for Locust metrics |
| `loadgenerator/loadgenerator.yaml` | Locust deployment with exporter sidecar |
| `dashboards/jvm-overview.json` | JVM metrics dashboard (heap, GC, threads, CPU) |
| `dashboards/load-test-overview.json` | Load test and cluster resource dashboard |
| `studies/_template/` | Template for new benchmark studies |
| `studies/hpa-autoscaling/` | Example study: HPA behavior on JVM services |
