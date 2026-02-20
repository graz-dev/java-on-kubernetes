# Spring Framework PetClinic

A single-service Spring MVC web application designed for JVM benchmarking.

## Overview

Spring Framework PetClinic is the classic Spring MVC + JSP veterinary clinic application.
It runs as a single WAR on Tomcat 11 with an H2 in-memory database pre-populated with sample data at startup.

**Source**: https://github.com/spring-petclinic/spring-framework-petclinic

## Architecture

```
                           ┌─────────────┐
                           │   Clients   │
                           └──────┬──────┘
                                  │ HTTP
                           ┌──────▼──────┐
                           │  petclinic  │ :8080  (NodePort 30081)
                           │ Spring MVC  │
                           │ Tomcat 11   │
                           │ H2 in-mem   │
                           └─────────────┘
```

No service discovery. No config server. No API gateway. One pod, one HPA target.

## Key Facts

| Property | Value |
|----------|-------|
| Framework | Spring Framework 7.0.3 (not Spring Boot) |
| Runtime | Tomcat 11 embedded |
| Database | H2 in-memory, **pre-populated at startup** |
| Port | 8080 (NodePort 30081) |
| Official image | `springcommunity/spring-framework-petclinic:latest` (Java 17, amd64) |
| Sample owners | 10 (IDs 1–10) |
| Sample pets | 13 (IDs 1–13) |

## Pre-populated Sample Data

The H2 database is seeded at startup from `src/main/resources/db/h2/data.sql`.
No external seeding step is required.

| Resource | IDs |
|----------|-----|
| Owners | 1–10 |
| Pets | 1–13 (fixed owner mapping) |
| Vets | 6 |

## Web UI Endpoints

All requests hit the single `petclinic` service at `http://localhost:8081`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/owners?lastName=` | GET | List all owners (DB query + JSP render) |
| `/owners/{id}` | GET | Owner detail with pets and visits (JOIN query) |
| `/owners/{ownerId}/pets/{petId}/visits/new` | POST | Submit new visit (DB insert → redirect) |
| `/vets` | GET | Vet list (Spring Cache — very cheap) |
| `/owners/find` | GET | Owner search form (used as health probe) |

## Load Testing

### Standard Load Test

The Locust load generator simulates realistic user behaviour:

1. **Browse owners** (40% of traffic) — `GET /owners?lastName=`
2. **View owner details** (30% of traffic) — `GET /owners/{id}`
3. **Submit new visit** (20% of traffic) — `POST .../visits/new`
4. **Browse vets** (10% of traffic) — `GET /vets`

No JSON parsing — IDs are hard-coded from sample data (no warm-up phase needed).

### CPU-Intensive Load Test for HPA

For autoscaling studies (`locustfile-intensive.py`):

- **70% POST visits** — DB insert + Hibernate transaction + OTel instrumentation overhead
- **20% GET owner details** — JOIN query
- **10% GET owners list** — list query
- **10x faster wait time** (0.1–0.5 s vs 1–3 s)

This generates enough CPU load to trigger HPA autoscaling (>70% CPU threshold).

### No Database Seeding Required

Unlike the microservices version, `spring-framework-petclinic` ships with pre-populated H2 data. Load tests work immediately after pod startup.

## OpenTelemetry Instrumentation

The pod uses the init-container pattern to inject the OTel Java agent v2.10.0:

```yaml
initContainers:
  - name: download-otel-agent
    image: busybox:1.36
    command: [wget, -O, /otel/opentelemetry-javaagent.jar, <url>]
```

Metrics exported via OTLP HTTP to the OTel Collector → Prometheus → Grafana.

## Resource Requirements

| Resource | Request | Limit |
|----------|---------|-------|
| CPU | 200m | 500m |
| Memory | 512Mi | 1Gi |

Memory is higher than the microservices version because Tomcat + Spring MVC + Hibernate
all share one heap, and the OTel agent adds ~100–150 MB overhead.

## Building for Custom Java Versions

The official image uses Java 17. To benchmark with a different Java version (e.g. 25),
build a custom image with `build-images.sh`. See [docker/README.md](docker/README.md).

```bash
./applications/petclinic/docker/build-images.sh --java-version 25 --load-to-kind
./setup.sh --app petclinic --java-version 25
```

## Deployment

```bash
./setup.sh --app petclinic
```

Access points:
- **PetClinic**: http://localhost:8081
- **Grafana**: http://localhost:3000 (JVM Overview dashboard)
- **Locust**: http://localhost:8089

## Comparison to Online Boutique

| Aspect | Online Boutique (adservice) | PetClinic |
|--------|-----------------------------|-----------|
| JVM services | 1 | 1 |
| Workload | Ad retrieval (HashMap) | DB writes, Hibernate, JSP render |
| HPA effectiveness | Poor (CPU rarely >20%) | Good (POST visits hits CPU limit fast) |
| GC activity | Minimal | Moderate (Hibernate entity allocation) |
| Spring Boot | No (gRPC Java) | No (Spring MVC WAR) |
| Database | No | Yes (H2, pre-populated) |
| Caching | No | Yes (vets — Spring Cache) |
| Startup time | ~30 s | ~60 s (Tomcat + Spring ctx + OTel agent) |

**Verdict**: PetClinic is better for JVM benchmarking — real DB workloads, realistic GC patterns, reliable HPA scaling.

## References

- GitHub: https://github.com/spring-petclinic/spring-framework-petclinic
- Official Docker image: `springcommunity/spring-framework-petclinic`
