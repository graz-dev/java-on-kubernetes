# Spring PetClinic Microservices

A microservices version of the classic Spring PetClinic application, designed for cloud-native deployments and JVM benchmarking.

## Overview

Spring PetClinic Microservices is a distributed version of the famous Spring PetClinic application, decomposed into multiple independent services. It demonstrates Spring Boot, Spring Cloud, and microservices patterns including service discovery, API gateway, circuit breakers, and distributed tracing.

**Source**: https://github.com/spring-petclinic/spring-petclinic-microservices

## Architecture

```
                                   ┌─────────────┐
                                   │   Clients   │
                                   └──────┬──────┘
                                          │
                                   ┌──────▼──────────┐
                                   │  API Gateway    │ (8080)
                                   │  (Spring Cloud) │
                                   └────────┬────────┘
                                            │
                  ┌─────────────────────────┼─────────────────────────┐
                  │                         │                         │
         ┌────────▼─────────┐    ┌─────────▼────────┐    ┌──────────▼─────────┐
         │ Customers Service│    │  Visits Service  │    │   Vets Service     │
         │  (Customer/Pet)  │    │ (Appointments)   │    │ (Veterinarians)    │
         └──────────────────┘    └──────────────────┘    └────────────────────┘
                  │                         │                         │
                  └─────────────────────────┼─────────────────────────┘
                                            │
                                   ┌────────▼─────────┐
                                   │  Discovery       │
                                   │  (Eureka)        │
                                   └──────────────────┘
```

## Services

| Service | Purpose | Workload Type | Port | Java Version |
|---------|---------|---------------|------|--------------|
| **api-gateway** | Routes requests to backend services, load balancing | I/O-intensive | 8080 | 25 |
| **customers-service** | Manages customers and their pets (CRUD operations) | Memory-intensive (caching) | 8081 | 25 |
| **visits-service** | Manages vet visit appointments and history | I/O-intensive (database queries) | 8082 | 25 |
| **vets-service** | Manages veterinarian information and specialties | Memory-intensive (read-heavy) | 8083 | 25 |
| **discovery-server** | Eureka service registry for service discovery | CPU-light, memory-moderate | 8761 | 25 |

**Total JVM services**: 5 (all Spring Boot microservices)

## Key Features for Benchmarking

### Heterogeneous Workloads

- **API Gateway**: High connection count, request routing overhead
- **Customers Service**: Database writes, object serialization, Spring Data JPA
- **Visits Service**: Complex queries, JOIN operations, transaction management
- **Vets Service**: Read-heavy caching (Spring Cache), minimal writes
- **Discovery Server**: Heartbeat processing, service registry updates

### JVM Characteristics

- **Heap usage**: Spring Boot baseline ~200-400 MB per service
- **GC activity**: Varies by workload (customers-service creates more garbage than vets-service)
- **Thread pools**: Tomcat embedded server (default 200 threads), async processing
- **Class loading**: Spring context initialization, lazy vs eager bean loading

### HPA Targets

Recommended services for HPA autoscaling studies:

1. **customers-service** - CPU scales with write operations (POST/PUT)
2. **visits-service** - CPU scales with complex queries and transaction overhead
3. **api-gateway** - Scales with total request volume across all endpoints

## API Endpoints

All requests go through the API Gateway at `http://api-gateway:8080/api`.

### Customer Endpoints

```
GET    /api/customer/owners          - List all owners
GET    /api/customer/owners/{id}     - Get owner details (includes pets)
POST   /api/customer/owners          - Create new owner
PUT    /api/customer/owners/{id}     - Update owner
GET    /api/customer/owners/*/pets/{id} - Get pet details
POST   /api/customer/owners/{id}/pets   - Add pet to owner
```

### Visit Endpoints

```
GET    /api/visit/owners/*/pets/{petId}/visits  - List visits for a pet
POST   /api/visit/owners/*/pets/{petId}/visits  - Schedule new visit
```

### Vet Endpoints

```
GET    /api/vet/vets                 - List all veterinarians (with specialties)
```

## Load Testing

### Standard Load Test

The Locust load generator simulates realistic user workflows:

1. **Browse owners** (60% of traffic) - GET /api/customer/owners
2. **View owner details** (20% of traffic) - GET /api/customer/owners/{id}
3. **Schedule visit** (15% of traffic) - POST /api/visit/owners/*/pets/{petId}/visits
4. **Browse vets** (5% of traffic) - GET /api/vet/vets

These ratios create a read-heavy workload with occasional writes, typical of a veterinary clinic application.

### CPU-Intensive Load Test for HPA

For autoscaling studies, use the intensive variant (`locustfile-intensive.py`):

- **70% write operations** (schedule_visit) - CPU-intensive POST operations
- **15% view owner details** - Moderate reads
- **10% browse owners** - Light reads for data availability
- **5% browse vets** - Minimal reads
- **10x faster wait time** (0.1-0.5s vs 1-3s) - Generates significantly more RPS

This configuration generates enough CPU load to trigger HPA autoscaling (>70% CPU threshold).

### Database Seeding (Required)

PetClinic starts with an **empty database**. Before load testing, seed the database with test data:

```bash
# From repository root
./applications/petclinic/scripts/seed-database.sh

# Or manually specify number of owners
NUM_OWNERS=100 ./applications/petclinic/scripts/seed-database.sh
```

This creates:
- N owners (default: 50)
- 2 pets per owner (dog and cat)
- Required for load test to function (schedule_visit needs existing pets)

## OpenTelemetry Instrumentation

All 5 JVM services are instrumented with the OpenTelemetry Java agent (v2.10.0), exporting metrics to the OTel Collector:

- **JVM metrics**: Heap, GC, threads, CPU, class loading
- **HTTP metrics**: Request rate, latency, error rate (via Spring Boot Actuator + OTel)
- **Custom metrics**: Spring-specific metrics (Tomcat threads, datasource connections, cache stats)

Metrics are available in Prometheus and visualized in the **JVM Overview** Grafana dashboard.

## Resource Requirements

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|-------------|-----------|----------------|--------------|
| api-gateway | 100m | 500m | 256Mi | 512Mi |
| customers-service | 100m | 500m | 256Mi | 512Mi |
| visits-service | 100m | 500m | 256Mi | 512Mi |
| vets-service | 50m | 300m | 128Mi | 256Mi |
| discovery-server | 50m | 300m | 128Mi | 256Mi |

**Total**: ~650m CPU, ~1Gi memory (minimum), scales with replicas under HPA.

## Building for arm64 (Apple Silicon)

Pre-built images are available for both x86_64 and arm64:

```bash
# Official multi-arch images from Docker Hub
docker pull springcommunity/spring-petclinic-api-gateway:latest
docker pull springcommunity/spring-petclinic-customers-service:latest
docker pull springcommunity/spring-petclinic-visits-service:latest
docker pull springcommunity/spring-petclinic-vets-service:latest
docker pull springcommunity/spring-petclinic-discovery-server:latest
```

For building locally with Java 25, see [docker/README.md](docker/README.md).

## Deployment

Deploy via the main setup script:

```bash
./setup.sh --app petclinic
```

Access the application:
- **API Gateway**: http://localhost:8081/api/customer/owners
- **Discovery Server UI**: http://localhost:8081/eureka (Eureka dashboard)
- **Grafana**: http://localhost:3000 (JVM Overview dashboard)
- **Locust**: http://localhost:8089 (Load testing UI)

## Comparison to Online Boutique

| Aspect | Online Boutique (adservice) | PetClinic |
|--------|----------------------------|-----------|
| JVM services | 1 | 5 |
| Workload complexity | Low (HashMap lookups) | Moderate (DB, caching, routing) |
| HPA effectiveness | Poor (rarely scales) | Good (customers/visits scale well) |
| GC activity | Minimal | Moderate to high |
| Spring Boot | No (gRPC Java) | Yes (full Spring stack) |
| Database | No | Yes (customers, visits services) |
| Caching | No | Yes (vets service) |

**Verdict**: PetClinic is significantly better for JVM benchmarking due to heterogeneous workloads and realistic Spring Boot patterns.

## Known Issues

### API Gateway Routing (405 Errors)

The API Gateway may return 405 (Method Not Allowed) errors for some requests. This is a known configuration issue with Spring Cloud Gateway routing rules.

**Workaround**: For load testing and HPA studies, bypass the API gateway and access services directly:

```yaml
# In locustfile, use direct service URLs:
host = "http://customers-service.microservices-demo.svc.cluster.local:8081"

# Visit endpoints use full URL:
POST http://visits-service.microservices-demo.svc.cluster.local:8082/owners/*/pets/{petId}/visits
```

This approach:
- ✅ Eliminates 405 errors
- ✅ Tests individual services directly (more realistic for HPA studies)
- ✅ Better isolates CPU load per service
- ⚠️ Bypasses API Gateway (not representative of production traffic patterns)

### Empty Database on First Start

PetClinic uses in-memory databases that start empty. Always run `seed-database.sh` before load testing.

## References

- GitHub: https://github.com/spring-petclinic/spring-petclinic-microservices
- Spring PetClinic (monolith): https://github.com/spring-projects/spring-petclinic
- Spring Cloud documentation: https://spring.io/projects/spring-cloud
