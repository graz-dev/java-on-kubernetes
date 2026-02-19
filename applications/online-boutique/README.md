# Online Boutique

## Overview

Online Boutique is a cloud-first microservices demo application by Google Cloud Platform. It simulates an e-commerce website where users can browse products, add them to cart, and place orders.

**Version:** v0.10.4
**Source:** https://github.com/GoogleCloudPlatform/microservices-demo

## Architecture

### Services

| Service | Language/Framework | Port | Purpose | JVM? |
|---------|-------------------|------|---------|------|
| frontend | Go | 8080 | Web UI and API gateway | No |
| cartservice | C# (.NET) | 7070 | Shopping cart backed by Redis | No |
| productcatalogservice | Go | 3550 | Product inventory and search | No |
| currencyservice | Node.js | 7000 | Currency conversion | No |
| paymentservice | Node.js | 50051 | Payment processing (mock) | No |
| shippingservice | Go | 50051 | Shipping cost calculation | No |
| emailservice | Python | 8080 | Order confirmation emails (mock) | No |
| checkoutservice | Go | 5050 | Checkout flow orchestration | No |
| recommendationservice | Python | 8080 | Product recommendations | No |
| **adservice** | **Java 21** | **9555** | **Ad serving** | **Yes** |
| redis-cart | Redis | 6379 | In-memory cart storage | No |

### JVM Services for Benchmarking

Online Boutique has **only 1 JVM service**:
- **adservice** (Java) - Serves ads based on product context

**Limitation:** adservice performs simple HashMap lookups to serve pre-defined ads from memory. It is **extremely lightweight** and barely uses CPU even under heavy load, making it **unsuitable for realistic JVM benchmarking** (HPA scaling, GC pressure analysis, memory profiling).

**For serious JVM benchmarking, consider using the `petclinic` application instead, which has 5 Spring Boot microservices with CPU/memory-intensive workloads.**

## Endpoints

### Web UI
- URL: `http://localhost:8080`
- Description: E-commerce storefront (frontend service)

### API Endpoints (internal, via frontend)
The frontend exposes gRPC services internally. For HTTP load testing, the Locust script interacts with the web UI endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Homepage with featured products |
| GET | `/product/<id>` | Product detail page |
| POST | `/cart` | Add item to cart |
| GET | `/cart` | View shopping cart |
| POST | `/cart/checkout` | Place order |

## Deployment

Deploy Online Boutique with:
```bash
./setup.sh --app online-boutique
```

Access points:
- **Frontend:** `http://localhost:8080`
- **Locust:** `http://localhost:8089`
- **Grafana:** `http://localhost:3000` (admin/admin)

## Load Testing

The Locust load test simulates realistic e-commerce user behavior:
1. Browse homepage
2. View random products
3. Add products to cart
4. Complete checkout
5. Repeat

The load test is automatically configured when deploying with `./setup.sh --app online-boutique`.

## JVM Metrics

The **adservice** is instrumented with OpenTelemetry Java agent v2.25.0 (injected via init container). Metrics collected:

- Heap memory (Eden, Survivor, Old Gen)
- GC frequency and pause duration (G1GC)
- Thread count
- CPU utilization
- Non-heap memory (Metaspace, CodeHeap)
- Class loading

**Note:** Due to adservice's trivial workload (HashMap lookups), you may observe:
- Very low CPU usage (<5% even under 1000 RPS)
- Minimal GC activity (mostly young gen, infrequent)
- Stable heap usage (ads are loaded once at startup)
- No memory pressure or thread contention

View metrics in Grafana's **JVM Overview** dashboard.

## Cross-Architecture Support

### Pre-built Images
- **x86_64 (Intel/AMD)**: Uses official Google images from `us-central1-docker.pkg.dev` (fast, no build needed)
- **arm64 (Apple Silicon)**: Images run under QEMU emulation (slower startup, ~30-60s for adservice with OTel agent)

### Building for arm64
Google does not provide arm64 images for Online Boutique. Running on Apple Silicon will use QEMU emulation.

For native arm64 JVM benchmarking, use the **petclinic** application instead:
```bash
./teardown.sh
./setup.sh --app petclinic
```

## Why Use PetClinic Instead?

| Criterion | Online Boutique | PetClinic |
|-----------|----------------|-----------|
| JVM services | 1 (adservice) | 5 (all Spring Boot services) |
| CPU-intensive workload | No (HashMap lookup) | Yes (JPA writes, transactions) |
| Memory pressure | No (static data) | Yes (Spring Cache, growing heap) |
| HPA scaling works? | No (CPU never hits threshold) | Yes (CPU scales with load) |
| Realistic benchmarking | No | Yes |
| arm64 support | QEMU emulation only | Native multi-arch images |
| Java version | N/A (gRPC service) | Java 17 (upgradeable to Java 25) |

**Recommendation:** Online Boutique is useful for understanding the starter pack structure and testing the monitoring stack. For actual JVM benchmarking (HPA, GC, heap analysis), switch to PetClinic.
