# JVM Benchmarking on Kubernetes — Starter Pack

A ready-to-use framework for running JVM performance benchmarks on Kubernetes, with support for multiple applications including [Google's Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) and [Spring PetClinic Microservices](https://github.com/spring-petclinic/spring-petclinic-microservices).

Run everything locally on [Kind](https://kind.sigs.k8s.io/) with full observability
(Prometheus, Grafana, OpenTelemetry) and reproducible load testing (Locust). Supports both Intel/AMD (x86_64) and Apple Silicon (arm64) architectures.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kind Cluster (jvm-bench)                     │
│                                                                     │
│  ┌──────────────── node: workload ────────────────┐                 │
│  │                                                │                 │
│  │  Online Boutique (11 services)                 │                 │
│  │  ┌──────────────────────────────────────────┐  │                 │
│  │  │ frontend → checkout → payment, shipping  │  │                 │
│  │  │         → currency, cart (Redis)         │  │                 │
│  │  │         → recommendation, email          │  │                 │
│  │  │         → adservice (Java/JVM) ← TARGET  │  │                 │
│  │  └──────────────────────────────────────────┘  │                 │
│  └────────────────────────────────────────────────┘                 │
│                                                                     │
│  ┌───────────────── node: tools ──────────────────┐                 │
│  │                                                │                 │
│  │  Prometheus + Grafana (kube-prometheus-stack)   │                 │
│  │  OpenTelemetry Collector                        │                 │
│  │  Locust Load Generator                          │                 │
│  └────────────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

**Workload isolation**: Application services run on one node, observability tools on another.
This prevents monitoring overhead from affecting benchmark measurements.

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | 20+ | [docker.com](https://docs.docker.com/get-docker/) |
| Kind | 0.20+ | `brew install kind` |
| kubectl | 1.27+ | `brew install kubectl` |
| Helm | 3.12+ | `brew install helm` |

**Machine requirements**: At least 8 GB RAM allocated to Docker (the full stack uses ~4-5 GB).

## Quickstart

```bash
# 1. Bootstrap the cluster (Kind + monitoring + app + loadgenerator)
./setup.sh                          # Default: online-boutique
./setup.sh --app petclinic          # Or use PetClinic

# 2. All UIs are exposed automatically:
#    Grafana:  http://localhost:3000  (admin / admin)
#    Locust:   http://localhost:8089
#    Frontend: http://localhost:8080 (online-boutique)
#              http://localhost:8081/api/customer/owners (petclinic)

# 3. Run a study
./studies/hpa-autoscaling/run-study.sh

# 4. Switch applications
./teardown.sh && ./setup.sh --app petclinic

# 5. Tear down when done
./teardown.sh
```

## Project Structure

```
.
├── setup.sh                  # One-command cluster bootstrap (--app flag)
├── teardown.sh               # Destroy the cluster
├── kind-config.yaml          # Kind cluster config (1 CP + 2 workers)
│
├── applications/             # Multi-application support
│   ├── _template/                    # Template for adding new apps
│   ├── online-boutique/              # Google's microservices demo (1 JVM service)
│   │   ├── README.md
│   │   ├── kubernetes-manifests/
│   │   └── locust/
│   └── petclinic/                    # Spring Framework PetClinic (single WAR on Tomcat 11)
│       ├── README.md
│       ├── kubernetes-manifests/
│       ├── locust/
│       └── docker/                   # Optional: build for Java 25 + arm64
│
├── monitoring/               # Observability stack
│   ├── kube-prometheus-values.yaml   # Helm values for Prometheus + Grafana
│   ├── otel-collector.yaml           # OpenTelemetry Collector
│   └── servicemonitors.yaml          # Prometheus scrape targets
│
├── loadgenerator/            # Load testing infrastructure
│   ├── loadgenerator.yaml            # Locust deployment (app-agnostic)
│   ├── README.md                     # Load generator documentation
│   ├── scenarios/                    # Example scenario ConfigMaps
│   └── scenario_generator_scripts/   # Python tool to generate scenarios
│
├── dashboards/               # Shared Grafana dashboards
│   ├── jvm-overview.json             # Heap, GC, threads, CPU
│   └── load-test-overview.json       # Locust metrics, cluster resources
│
└── studies/                  # Benchmark studies
    ├── _template/                    # Template for new studies
    └── hpa-autoscaling/              # Example: HPA behavior on JVM services
```

## Multi-Application Support

The framework supports multiple applications, each with different characteristics for JVM benchmarking.

### Available Applications

| Application | JVM Services | Best For | Workload Types |
|-------------|-------------|----------|----------------|
| **online-boutique** | 1 (adservice) | Simple setup, lightweight workloads | Ad retrieval (HashMap lookups) |
| **petclinic** | 1 (single WAR on Tomcat 11) | Realistic benchmarking, Spring MVC + Hibernate | CPU-intensive POST visits (Hibernate transaction + OTel), cached GET /vets |

**Recommendation**: Use **PetClinic** for serious benchmarking. Online Boutique's adservice is too lightweight — it only does HashMap lookups and rarely triggers HPA scaling or significant GC activity.

### Selecting an Application

```bash
# Use the default (online-boutique)
./setup.sh

# Explicitly select online-boutique
./setup.sh --app online-boutique

# Use PetClinic (recommended for benchmarking)
./setup.sh --app petclinic

# List available applications
ls -1 applications/ | grep -v _template
```

### Switching Applications

```bash
# Tear down current application
./teardown.sh

# Deploy a different application
./setup.sh --app petclinic
```

### Adding a New Application

Copy the template and fill in the required files:

```bash
cp -r applications/_template applications/my-app
cd applications/my-app

# Edit:
# - README.md (document architecture, services, endpoints)
# - kubernetes-manifests/*.yaml (add app-type: my-app label)
# - locust/locustfile.py (define realistic user behavior)
```

**Requirements**:
- All Kubernetes manifests must include `app-type: my-app` label for app detection
- JVM services must be instrumented with OpenTelemetry Java agent
- Locust file must define realistic user workflows

See [applications/_template/README.md](applications/_template/README.md) for detailed guidance.

## Cross-Architecture Support

The framework works on both **Intel/AMD (x86_64)** and **Apple Silicon (arm64)** architectures.

### Architecture Detection

`setup.sh` automatically detects your system architecture and displays a warning on Apple Silicon:

```
Architecture: arm64 (Apple Silicon)
✅ PetClinic images available as multi-arch (native arm64 support)
⚠️ Online Boutique runs under QEMU emulation (slower startup)
```

### Performance Considerations

| Architecture | Application | Pre-built Images | Startup Time | Runtime Performance |
|--------------|-------------|-----------------|--------------|---------------------|
| **x86_64** (Intel/AMD) | All | ✅ Native | Fast (~30-45s per service) | 100% |
| **arm64** (Apple Silicon) | PetClinic | ✅ Native multi-arch | Fast (~30-45s per service) | 100% |
| **arm64** (Apple Silicon) | Online Boutique | ⚠️ QEMU emulation | Slower (~60-90s per service) | 70-80% |

**PetClinic has official multi-arch images** that run natively on both x86_64 and arm64, making it the best choice for Apple Silicon users.

### Building with Java 25 (Optional)

The official PetClinic images use Java 17. To benchmark with Java 25, you can build from source:

```bash
# See application-specific build instructions
cat applications/petclinic/docker/README.md

# Build process (automated via script):
cd applications/petclinic/docker
./build-images.sh --load-to-kind

# Or manually:
# 1. Clone PetClinic Microservices repository
# 2. Update Dockerfiles to Java 25
# 3. Build with Maven: mvn clean package -DskipTests
# 4. Build Docker images with --platform linux/arm64 (or linux/amd64)
# 5. Load images into Kind
# 6. Deploy with setup.sh
```

**Note**: Building from source requires Java 11+, Maven 3.6+, and ~20-30 minutes for the first build.

## How Studies Work

Each study is a self-contained benchmark experiment inside `studies/`. A study contains:

| File | Purpose |
|------|---------|
| `README.md` | Methodology, hypothesis, results, conclusions |
| `run-study.sh` | Apply/teardown study-specific Kubernetes resources |
| `scenario-config.yaml` | Load scenario ConfigMap for this study |
| `*.yaml` | Study-specific K8s resources (HPA, configs, etc.) |
| `dashboard.json` | Study-specific Grafana dashboard |

### Running a Study

```bash
./studies/<study-name>/run-study.sh           # Apply resources and start
./studies/<study-name>/run-study.sh teardown   # Clean up
```

### Creating a New Study

```bash
cp -r studies/_template studies/my-new-study
# Edit the files in studies/my-new-study/
```

## Dashboards

| Dashboard | Scope | Key Metrics |
|-----------|-------|-------------|
| **JVM Overview** | All JVM services | Heap usage, GC frequency/pauses, threads, CPU |
| **Load Test Overview** | Cluster-wide | Locust users/RPS/latency, node CPU/memory |
| **Per-study dashboards** | Study-specific | Varies (e.g., HPA replicas, scaling latency) |

## Observability Stack

- **Prometheus** (via kube-prometheus-stack): Scrapes all Kubernetes metrics, node metrics, and custom ServiceMonitors
- **Grafana**: Auto-loads dashboards from ConfigMaps
- **OpenTelemetry Collector**: Receives OTLP from JVM services, exports to Prometheus via remote write
- **Locust Exporter**: Sidecar that exposes Locust metrics to Prometheus

## JVM Benchmark Targets

All JVM services are instrumented with the **OpenTelemetry Java agent**, which auto-instruments and exports JVM metrics:

- Heap memory (Eden, Survivor, Old Gen)
- GC pauses (frequency, duration)
- Thread count (live, daemon, peak)
- CPU utilization (process, system)
- Class loading

### Online Boutique

- **adservice**: The only Java service in Online Boutique
- **Workload**: Ad retrieval (simple HashMap lookups)
- **Limitation**: Too lightweight for realistic benchmarking — rarely triggers HPA scaling or significant GC activity

### PetClinic (Recommended)

- **Single WAR**: Spring MVC 7 + Hibernate + H2 in-memory DB, deployed on Apache Tomcat 11
- **Workload types**:
  - **DB writes**: `POST /owners/{id}/pets/{petId}/visits/new` — Hibernate transaction + H2 write + OTel span
  - **DB reads**: `GET /owners/{id}` — JOIN query (owner + pets + visits)
  - **Cached reads**: `GET /vets` — Spring Cache (very cheap)
- **Benefits**:
  - Pre-populated H2 sample data (10 owners, 13 pets) — no seeding step needed
  - Single HPA target (one deployment), deterministic scaling behaviour
  - Native arm64 support (official image is amd64 only; custom builds are native)
  - Easy to benchmark Java 17 / 21 / 25 with `--java-version`

**HPA/Autoscaling Studies:**

No seeding required — H2 data is pre-loaded at pod startup. Use the intensive locustfile (70% POSTs) to trigger CPU-based HPA scaling:
```bash
# Run the HPA study (deploys petclinic, runs intensive load, watches scaling)
./studies/hpa-autoscaling/run-study.sh
```

Use the **JVM Overview** dashboard in Grafana to observe GC, heap, and CPU metrics.

## Credits

- Application: [Google Cloud Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) v0.10.4
- Load Generator: Custom Locust-based generator with scenario support
