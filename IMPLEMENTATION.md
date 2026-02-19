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

**The Solution:** Add Spring PetClinic Microservices, a well-maintained Spring Boot application with 5 JVM services featuring heterogeneous workloads (DB writes, caching, service discovery). Supports native arm64 and easy Java 25 upgrades.

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
└── petclinic/                       # Spring PetClinic Microservices
    ├── README.md                    # Architecture, services, endpoints
    ├── kubernetes-manifests/
    │   └── petclinic.yaml           # 5 services (all JVM - Spring Boot)
    ├── locust/
    │   └── locustfile.py            # Veterinary clinic user flow
    └── docker/                      # Optional: build with Java 25
        ├── README.md
        └── build-images.sh          # Maven + Docker build script (stub)
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
   - PetClinic: `http://api-gateway:8080`

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
| **JVM Services** | 1 (adservice) | 5 (discovery-server, api-gateway, customers-service, visits-service, vets-service) |
| **Workload Types** | Ad retrieval (HashMap lookup) | CPU-intensive (DB writes, JPA mapping), memory-intensive (caching), I/O-intensive (transactions), gateway routing |
| **CPU Usage** | Low (~5-10% even under high load) | Moderate to high (customers/visits services can hit 70%+ under load) |
| **GC Activity** | Minimal (young gen GC only, <10ms pauses) | Moderate (both young and old gen, 10-50ms pauses typical) |
| **Heap Usage** | Stable (~100-150 MB) | Growing with cache (~200-400 MB, vets service uses Spring Cache) |
| **HPA Scaling** | Rarely triggers (CPU too low) | Reliably triggers at load (especially customers-service) |
| **arm64 Support** | QEMU emulation only | Native multi-arch images available |
| **Java Version** | N/A (gRPC service) | Java 17 (official images), easy to upgrade to Java 25 |
| **Best For** | Simple setup, learning | Realistic benchmarking, Spring Boot applications |

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
   # Clone PetClinic Microservices repository
   git clone https://github.com/spring-petclinic/spring-petclinic-microservices.git
   cd spring-petclinic-microservices

   # Update Dockerfiles to Java 25
   find . -name Dockerfile -exec sed -i '' 's/eclipse-temurin:17-jre/eclipse-temurin:25-jre/g' {} \;

   # Build all services with Maven
   mvn clean package -DskipTests

   # Build Docker images (native architecture)
   docker build --platform linux/arm64 -t localhost/spring-petclinic-api-gateway:java25-arm64 spring-petclinic-api-gateway/
   docker build --platform linux/arm64 -t localhost/spring-petclinic-customers-service:java25-arm64 spring-petclinic-customers-service/
   # ... repeat for visits-service, vets-service, discovery-server

   # Load images into Kind
   kind load docker-image localhost/spring-petclinic-api-gateway:java25-arm64 --name jvm-bench
   kind load docker-image localhost/spring-petclinic-customers-service:java25-arm64 --name jvm-bench
   # ... load all 5 images
   ```

4. **Update manifest to use local images:**
   Edit `applications/petclinic/kubernetes-manifests/petclinic.yaml` to use `localhost/spring-petclinic-*:java25-arm64` and set `imagePullPolicy: Never`.

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

Spring PetClinic Microservices is the distributed version of the classic [Spring PetClinic](https://github.com/spring-projects/spring-petclinic) application, decomposed into multiple Spring Boot microservices. It's maintained by the Spring community and demonstrates modern Spring Cloud patterns.

### Architecture

PetClinic simulates a veterinary clinic with owner management, pet records, vet information, and appointment scheduling.

```
┌──────────────────────────────────────────────────────────┐
│                     PetClinic                            │
│                                                          │
│                   API Gateway (8080)                     │
│                   (Spring Cloud Gateway)                 │
│                          ↓                               │
│  ┌────────────────────────────────────────────────┐     │
│  │                                                │     │
│  │  Discovery Server (8761) ← Eureka registry    │     │
│  │         ↓                                      │     │
│  │  ┌──────────────────────────────────────┐     │     │
│  │  │  Customers Service (8081)            │     │     │
│  │  │  Visits Service (8082)               │     │     │
│  │  │  Vets Service (8083)                 │     │     │
│  │  └──────────────────────────────────────┘     │     │
│  │         ↓                                      │     │
│  │  Embedded H2 databases (in-memory)            │     │
│  └────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────┘
```

### Services

| Service | Framework | Port | Workload Type | Description |
|---------|-----------|------|--------------|-------------|
| **discovery-server** | Spring Cloud Eureka | 8761 | Coordination | Service registry, heartbeat processing |
| **api-gateway** | Spring Cloud Gateway | 8080 | **I/O-intensive** | Request routing, load balancing across services |
| **customers-service** | Spring Boot + JPA | 8081 | **CPU-intensive** | CRUD operations for customers and pets (DB writes, JPA mapping) |
| **visits-service** | Spring Boot + JPA | 8082 | **I/O-intensive** | Appointment scheduling, complex queries, transactions |
| **vets-service** | Spring Boot + JPA | 8083 | **Memory-intensive** | Vet information, read-heavy with Spring Cache |

**All 5 services** run on **Spring Boot 3.x with embedded Tomcat**. Official images use **Java 17**, easily upgradeable to **Java 25** for benchmarking.

### Workload Characteristics

| Service | CPU Pattern | Memory Pattern | I/O Pattern | GC Behavior |
|---------|-------------|----------------|-------------|-------------|
| **customers-service** | High (writes) | Growing | Moderate | Frequent young gen GC during POST/PUT |
| **visits-service** | Moderate | Stable | High (transactions) | Moderate GC during complex queries |
| **vets-service** | Low | Growing (cache) | Low | Minimal GC (read-heavy, cached) |
| **api-gateway** | Low-Moderate | Stable | High (routing) | Young gen GC under high request volume |
| **discovery-server** | Low | Stable | Low | Minimal GC (heartbeats only) |

**Why this matters for benchmarking:**

- **Heterogeneous workloads**: Different services stress different JVM subsystems (CPU, heap, GC, I/O)
- **Real Spring Boot patterns**: JPA, Spring Data, Spring Cloud, embedded Tomcat — reflects production Spring applications
- **Microservices patterns**: Service discovery, API gateway, circuit breakers
- **Scalability testing**: HPA works well on customers-service and visits-service under load
- **Native arm64 support**: Official multi-arch images run natively on Apple Silicon (no QEMU emulation)

### Modifications from Upstream

The manifest was adapted from the [upstream Docker Compose setup](https://github.com/spring-petclinic/spring-petclinic-microservices) with these changes:

1. **Node selectors**: All services use `nodeSelector: node-role: workload` for isolation from monitoring stack.

2. **API Gateway NodePort**: Set to `NodePort: 30081` (port 8081 on host) to avoid conflict with Online Boutique frontend.

3. **Config Server deployment**: Added separate `config-server.yaml` manifest. The official PetClinic images require Spring Cloud Config Server. Configured with `SPRING_PROFILES_ACTIVE=native` for local configuration (no Git repository needed).

4. **OTel Java agent injection**: Added init container pattern to all 5 JVM services. Downloads OpenTelemetry Java agent v2.10.0 from GitHub, mounts via `emptyDir`, loads with `JAVA_TOOL_OPTIONS=-javaagent:/otel/opentelemetry-javaagent.jar`.

5. **Resource limits**: Based on typical Spring Boot application requirements:
   - **discovery-server**: `cpu: 100m-500m, memory: 384Mi-768Mi` (increased for OTel agent overhead)
   - **customers-service, visits-service, api-gateway**: `cpu: 100m-500m, memory: 256Mi-512Mi`
   - **vets-service**: `cpu: 100m-500m, memory: 256Mi-512Mi`
   - **config-server**: `cpu: 50m-300m, memory: 128Mi-256Mi`

6. **Probes**: Spring Boot Actuator health endpoints at `/actuator/health`:
   - **Startup probe**: `failureThreshold: 36` (up to 360s / 6 minutes for Spring context + Hibernate + Eureka + OTel agent startup)
   - **Readiness probe**: Checks if Spring context is fully initialized
   - **Liveness probe**: Checks if application is still responsive

7. **App-type labels**: Added `app-type: petclinic` to all resources for identification.

8. **Service-specific port configuration**: Each service has `SERVER_PORT` environment variable set explicitly to avoid config-server overrides:
   - discovery-server: `SERVER_PORT=8761`
   - api-gateway: `SERVER_PORT=8080`
   - customers-service: `SERVER_PORT=8081`
   - visits-service: `SERVER_PORT=8082`
   - vets-service: `SERVER_PORT=8083`

9. **Spring Cloud configuration**: All backend services configured with:
   - `SPRING_CLOUD_CONFIG_URI=http://config-server:8888` (config server endpoint)
   - `SPRING_CLOUD_CONFIG_IMPORT_CHECK_ENABLED=false` (disable strict config import)
   - `EUREKA_CLIENT_SERVICEURL_DEFAULTZONE=http://discovery-server:8761/eureka` (Eureka server endpoint)
   - **Note**: `SPRING_PROFILES_ACTIVE=docker` is NOT used because it causes services to attempt localhost connections instead of using Kubernetes service names.

### Endpoints

**API Gateway:** `http://localhost:8081/api/customer/owners`

**REST API examples:**
- List owners: `GET http://localhost:8081/api/customer/owners`
- Get owner: `GET http://localhost:8081/api/customer/owners/{id}`
- Add pet: `POST http://localhost:8081/api/customer/owners/{id}/pets`
- Schedule visit: `POST http://localhost:8081/api/visit/owners/*/pets/{petId}/visits`
- List vets: `GET http://localhost:8081/api/vet/vets`

**Eureka Dashboard:** `http://localhost:8081/eureka` - view registered services

**Health checks (Spring Boot Actuator):**
- API Gateway: `GET http://localhost:8081/actuator/health`
- Customers: `GET http://customers-service:8081/actuator/health`
- Visits: `GET http://visits-service:8082/actuator/health`
- Vets: `GET http://vets-service:8083/actuator/health`

### Performance Expectations

Under moderate load (50-100 concurrent users):

| Service | CPU Usage | Heap Usage | GC Frequency | Expected Bottleneck |
|---------|-----------|------------|--------------|---------------------|
| **customers-service** | 20-50% | 250-400 MB | 1-2 GC/min | CPU (JPA writes, object mapping) |
| **visits-service** | 15-40% | 200-350 MB | 1 GC/min | Database I/O (transactions) |
| **vets-service** | 5-15% | 150-250 MB | <1 GC/min | None (read-heavy, cached) |
| **api-gateway** | 10-25% | 200-300 MB | 0.5-1 GC/min | Network I/O (routing overhead) |
| **discovery-server** | 3-8% | 128-200 MB | <1 GC/min | None (heartbeats only) |

Under high load (200+ concurrent users):
- **customers-service** will hit CPU limits first (good HPA target, POST/PUT operations)
- **visits-service** CPU increases due to transaction overhead (good HPA target)
- **api-gateway** may experience increased latency due to routing volume
- **vets-service** remains stable (caching prevents load growth)

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
- **PetClinic**: `http://api-gateway:8080`

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
- Browse owners (60% of traffic - triggers customers-service with JPA queries)
- View owner details including pets (20% of traffic - entity relationships, cache behavior)
- Schedule visits (15% of traffic - triggers visits-service with DB writes, transactions)
- Browse vets (5% of traffic - triggers vets-service, tests Spring Cache effectiveness)
- Logout

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

This is the primary dashboard for JVM benchmarking. It has 4 sections with 8 panels:

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

### PetClinic services not starting

PetClinic has more complex startup requirements than Online Boutique. Common issues:

**Problem: Services stuck at 0/1 READY with CrashLoopBackOff**

**Root causes and fixes:**

1. **Config Server missing**: All PetClinic services require Spring Cloud Config Server.
   - **Solution**: Ensure `config-server.yaml` is deployed before other services.
   - Verify: `kubectl get svc config-server -n microservices-demo`

2. **Wrong ports**: Services may start on port 8080 but health probes check service-specific ports.
   - **Solution**: Each service must have `SERVER_PORT` environment variable set explicitly (8761 for discovery-server, 8080 for api-gateway, 8081 for customers-service, etc.)
   - Verify: `kubectl logs -n microservices-demo deployment/customers-service | grep "Tomcat started on port"`

3. **Out of Memory (OOMKilled)**: Spring Boot + Hibernate + Eureka + OTel agent uses ~350-500 MB.
   - **Solution**: Memory limits must be at least 384Mi for discovery-server, 256Mi for other services.
   - Check: `kubectl get pods -n microservices-demo | grep OOMKilled`

4. **Startup timeout**: Spring Boot context initialization + Hibernate + Eureka registration + OTel agent can take 3-4 minutes.
   - **Solution**: Startup probe `failureThreshold: 36` (6 minutes total with 10s periodSeconds)
   - Verify: `kubectl describe pod -n microservices-demo <pod-name> | grep "Startup probe failed"`

5. **Localhost connection errors**: `SPRING_PROFILES_ACTIVE=docker` profile causes services to attempt localhost:8888 instead of config-server:8888.
   - **Solution**: DO NOT use `SPRING_PROFILES_ACTIVE=docker`. Instead, explicitly set:
     - `SPRING_CLOUD_CONFIG_URI=http://config-server:8888`
     - `EUREKA_CLIENT_SERVICEURL_DEFAULTZONE=http://discovery-server:8761/eureka`
     - `SPRING_CLOUD_CONFIG_IMPORT_CHECK_ENABLED=false`
   - Verify: `kubectl logs -n microservices-demo deployment/customers-service | grep UnknownHostException`

**Debugging steps:**
```bash
# 1. Check all pod status
kubectl get pods -n microservices-demo -l app-type=petclinic

# 2. Check recent logs for errors
kubectl logs -n microservices-demo deployment/customers-service --tail=50

# 3. Test health endpoint directly
kubectl exec -n microservices-demo deployment/customers-service -- curl -s http://localhost:8081/actuator/health

# 4. Verify Eureka registration
kubectl exec -n microservices-demo deployment/discovery-server -- curl -s http://localhost:8761/eureka/apps
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

# Expected output:
# NAME                REFERENCE                      TARGETS    MINPODS   MAXPODS   REPLICAS
# customers-service   Deployment/customers-service   8%/70%     1         10        1
# visits-service      Deployment/visits-service      7%/70%     1         8         1
```

**Note:** The `setup.sh` script does NOT install metrics-server automatically because it's only needed for HPA-based studies. Studies that use HPA should document this prerequisite in their README.

### PetClinic: Empty database prevents load testing

**Problem:** PetClinic starts with empty in-memory databases. Load tests fail because:
- No owners exist → browse operations return `[]`
- No pets exist → schedule_visit operations cannot run (need pet IDs)
- CPU usage remains low because services process no actual data

**Root cause:** PetClinic uses H2 in-memory databases without pre-loaded sample data.

**Solution:** Seed the database before starting load tests:
```bash
# Run the seeding script (creates 50 owners with 2 pets each)
./applications/petclinic/scripts/seed-database.sh

# Or specify custom count
NUM_OWNERS=100 ./applications/petclinic/scripts/seed-database.sh
```

**Verification:**
```bash
# Check database has data
kubectl run test --image=curlimages/curl --rm -i --restart=Never -n microservices-demo \
  -- curl -s http://customers-service:8081/owners | head -c 500

# Should return JSON array with owner objects
```

**Why this matters for HPA:** Without data, services perform minimal work (returning empty arrays uses negligible CPU), preventing HPA from triggering even under high request volumes.

### PetClinic: API Gateway returns 405 errors

**Problem:** Requests through API Gateway fail with `405 Method Not Allowed`:
```
GET http://api-gateway:8080/api/customer/owners → 405
POST http://api-gateway:8080/api/visit/owners/*/pets/{id}/visits → 405
```

**Root cause:** Spring Cloud Gateway routing rules misconfiguration. The gateway expects specific headers or path patterns that Locust doesn't provide.

**Workaround:** Bypass the API gateway and access services directly in the locustfile:
```python
# Instead of routing through gateway:
host = "http://api-gateway:8080"  # ❌ Returns 405

# Access services directly:
host = "http://customers-service.microservices-demo.svc.cluster.local:8081"  # ✅ Works

# For visits-service, use full URL:
self.client.post(
    f"http://visits-service.microservices-demo.svc.cluster.local:8082/owners/*/pets/{pet_id}/visits",
    json=payload
)
```

**IMPORTANT:** Update `FRONTEND_URL` environment variable in loadgenerator deployment:
```bash
kubectl set env deployment/ak-loadgenerator -n microservices-demo \
  FRONTEND_URL=http://customers-service.microservices-demo.svc.cluster.local:8081
```

The load generator's `online_test.py` script uses this variable to configure Locust's host, overriding the locustfile setting.

**Trade-offs:**
- ✅ **Pros**: Eliminates 405 errors, isolates load per service (better for HPA studies), more realistic for microservices testing
- ⚠️ **Cons**: Doesn't test API Gateway (not representative of production traffic patterns)

### PetClinic: Load test not CPU-intensive enough for HPA

**Problem:** Standard load test uses 60% read operations (GET requests) and only 15% writes. This creates minimal CPU load:
- Read operations are cached or return small datasets
- Low CPU usage (5-20%) even with 500-800 concurrent users
- HPA never triggers (threshold is 70% CPU)

**Root cause:** PetClinic services are efficient for typical workloads. Read operations don't create enough garbage collection pressure or CPU overhead.

**Solution:** Use the CPU-intensive locustfile variant:
```bash
# Update ConfigMap to use intensive version
kubectl create configmap locust-tasks \
  --from-file=locustfile.py=applications/petclinic/locust/locustfile-intensive.py \
  -n microservices-demo --dry-run=client -o yaml | kubectl apply -f -

# Restart load generator to pick up changes
kubectl delete deployment ak-loadgenerator -n microservices-demo
kubectl apply -f loadgenerator/loadgenerator.yaml
```

**Key differences in intensive version:**
- **70% write operations** (schedule_visit POST to visits-service) instead of 15%
- **10x faster request rate**: wait_time `between(0.1, 0.5)` instead of `between(1, 3)`
- **More aggressive user ramp**: 100 → 500 → 1000 → 1500 → 2000 users

**Expected results with intensive load:**
```bash
# After 2-3 minutes with 500+ users:
kubectl get hpa -n microservices-demo

NAME                REFERENCE                      TARGETS        MINPODS   MAXPODS   REPLICAS
customers-service   Deployment/customers-service   cpu: 405%/70%  1         10        8
visits-service      Deployment/visits-service      cpu: 475%/70%  1         8         7
```

**Verification:**
```bash
# Check load test is making write operations
kubectl port-forward -n microservices-demo svc/ak-loadgenerator 8089:8089 &
curl -s http://localhost:8089/stats/requests | jq '.stats[] | select(.name | contains("visit"))'

# Should show thousands of requests to visit endpoints
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
| `app/kubernetes-manifest.yaml` | Online Boutique (11 services) with OTel agent on adservice |
| `monitoring/kube-prometheus-values.yaml` | Helm values for Prometheus + Grafana |
| `monitoring/otel-collector.yaml` | OTel Collector: ConfigMap + Deployment + Service |
| `monitoring/servicemonitors.yaml` | Prometheus ServiceMonitor for Locust metrics |
| `loadgenerator/loadgenerator.yaml` | Locust deployment with exporter sidecar |
| `dashboards/jvm-overview.json` | JVM metrics dashboard (heap, GC, threads, CPU) |
| `dashboards/load-test-overview.json` | Load test and cluster resource dashboard |
| `studies/_template/` | Template for new benchmark studies |
| `studies/hpa-autoscaling/` | Example study: HPA behavior on JVM services |
