# [Application Name]

## Overview

Brief description of the application - what it does, what domain it simulates (e-commerce, banking, etc.).

## Architecture

### Services

| Service | Language/Framework | Port | Purpose | Workload Type |
|---------|-------------------|------|---------|---------------|
| service-a | Java 21 / Spring Boot | 8080 | Example service | CPU-intensive |
| service-b | Java 21 / Spring Boot | 8081 | Example service | Memory-intensive |
| service-c | Java 21 / Spring Boot | 8082 | Example service | I/O-intensive |

### JVM Services for Benchmarking

List which services are JVM-based and will be instrumented with the OpenTelemetry Java agent:
- `service-a` - Primary benchmark target
- `service-b` - Secondary target

## Endpoints

### Web UI
- URL: `http://localhost:<port>/path`
- Description: User-facing interface

### API Endpoints (for load testing)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/resource` | Example endpoint |
| POST | `/api/resource` | Example endpoint |

## Deployment

This application is deployed via:
```bash
./setup.sh --app <app-name>
```

Access points:
- Web UI: `http://localhost:<port>`
- Locust: `http://localhost:8089`
- Grafana: `http://localhost:3000`

## Load Testing

The application includes a Locust load test in `locust/locustfile.py` that simulates realistic user behavior:
1. Step 1 (e.g., login)
2. Step 2 (e.g., browse)
3. Step 3 (e.g., transaction)

## JVM Metrics

All JVM services are instrumented with OpenTelemetry Java agent v2.25.0. Metrics include:
- Heap memory (used, committed, limit) by memory pool
- GC frequency and pause duration
- Thread count (daemon/non-daemon)
- CPU utilization
- Non-heap memory (Metaspace, CodeHeap)
- Class loading statistics

View metrics in Grafana's "JVM Overview" dashboard.

## Cross-Architecture Support

### Pre-built Images
- **x86_64 (Intel/AMD)**: Uses pre-built Docker images from [registry]
- **arm64 (Apple Silicon)**: Images run under QEMU emulation (slower startup)

### Building for arm64
For native arm64 performance on M1/M2/M3 Macs, see `docker/README.md` for build instructions.
