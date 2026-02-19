# Building PetClinic with a custom Java version

## Overview

The official `springcommunity/spring-framework-petclinic:latest` image uses **Java 17** (amd64 only).
For arm64-native builds or a different Java version, use `build-images.sh` to produce a custom image.

The custom build also injects `jvm-entrypoint.sh` as the Docker `ENTRYPOINT`. At pod startup
this script captures the actual JVM configuration flags and exposes them as Prometheus labels
in Grafana (GC algorithm, heap sizes, JIT settings, etc.).

## Architecture: WAR on Tomcat

Unlike the microservices version (Spring Boot fat JAR), `spring-framework-petclinic` is a
classic Spring MVC WAR deployed on Apache Tomcat 11.

```
Dockerfile
├── Base image: eclipse-temurin:<JAVA_VERSION>
├── Downloads Tomcat 11.0.2 from Apache archives
├── Deploys petclinic.war as ROOT.war
└── ENTRYPOINT: jvm-entrypoint.sh → catalina.sh run
```

`jvm-entrypoint.sh` captures `PrintFlagsFinal` before Tomcat starts, then launches Tomcat
via `catalina.sh run`. Tomcat inherits `JAVA_TOOL_OPTIONS` (OTel agent) and
`OTEL_RESOURCE_ATTRIBUTES` (JVM config labels).

## Why Custom Builds?

1. **Native arm64 support**: Official image is amd64-only; runs under QEMU on Apple Silicon (slower startup, less accurate benchmarks)
2. **Java version flexibility**: Benchmark Java 17 vs 21 vs 25 on identical application code
3. **JVM config labels**: `jvm-entrypoint.sh` injects GC algorithm, heap sizes, JIT settings into Grafana

## Prerequisites

| Tool | Version |
|------|---------|
| Docker | 20+ |
| Git | 2.30+ |

Java and Maven are **not required** locally — the build script falls back to a
`maven:3.9-eclipse-temurin-<version>` Docker container automatically.

## Build Process

### Automated (recommended)

```bash
cd applications/petclinic/docker

# Build with Java 17 (default)
./build-images.sh

# Build with Java 25 and load directly into Kind
./build-images.sh --java-version 25 --load-to-kind
```

The script:
1. Clones `spring-framework-petclinic` from GitHub (shallow clone)
2. Builds the WAR with Maven (Docker-based build if local Java/Maven absent)
3. Builds the Docker image using `Dockerfile` (WAR + Tomcat 11 + `jvm-entrypoint.sh`)
4. Tags as `localhost/spring-framework-petclinic:java<N>-<arch>`
5. Optionally loads into Kind cluster `jvm-bench`

**Build time**: ~10–15 min first run (Maven downloads dependencies), ~3–5 min incremental.

### Manual Build

```bash
# 1. Clone the repository
git clone --depth 1 https://github.com/spring-petclinic/spring-framework-petclinic.git /tmp/petclinic-build
cd /tmp/petclinic-build

# 2. Build the WAR
mvn clean package -DskipTests
# WAR output: target/petclinic.war  (finalName in pom.xml)

# 3. Prepare Docker build context
mkdir /tmp/ctx
cp target/petclinic.war /tmp/ctx/spring-framework-petclinic.war
cp /path/to/docker/jvm-entrypoint.sh /tmp/ctx/jvm-entrypoint.sh

# 4. Build Docker image
docker build --platform linux/arm64 \
  --build-arg JAVA_VERSION=25 \
  -t localhost/spring-framework-petclinic:java25-arm64 \
  -f /path/to/docker/Dockerfile \
  /tmp/ctx/

# 5. Load into Kind
kind load docker-image localhost/spring-framework-petclinic:java25-arm64 --name jvm-bench
```

## JVM Configuration Entrypoint

`jvm-entrypoint.sh` is copied into the image and runs before Tomcat starts.

### What it does

1. Runs `env -u JAVA_TOOL_OPTIONS java -XX:+PrintFlagsFinal -version` to probe JVM flags
   (unsetting `JAVA_TOOL_OPTIONS` to avoid loading the OTel agent during the short-lived probe)
2. Extracts: GC algorithm, heap sizes, GC pause target, GC threads, JIT settings, compressed OOPs, CPU count
3. Builds `OTEL_RESOURCE_ATTRIBUTES` string and appends to any existing attrs from the K8s manifest
4. Executes: `exec /opt/tomcat/bin/catalina.sh run` — Tomcat starts with OTel agent (JAVA_TOOL_OPTIONS restored)

### Why this matters

The OTel Collector converts resource attributes → Prometheus labels (`resource_to_telemetry_conversion: enabled: true`). Every JVM metric then carries `jvm_config_gc`, `jvm_config_heap_max`, etc. The Grafana JVM Overview dashboard uses these to display a per-pod configuration table without hardcoding.

## Using Custom Images with setup.sh

```bash
./setup.sh --app petclinic --java-version 25
```

`setup.sh` detects the non-default Java version, checks for the local image, and:
- If missing: prompts to build it (calls `build-images.sh` automatically)
- Substitutes `localhost/spring-framework-petclinic:java25-<arch>` into the manifest
- Sets `imagePullPolicy: Never` to prevent Docker Hub pulls

## Verification

```bash
# Check Java version in running pod
kubectl exec -n microservices-demo deployment/petclinic -- java -version

# Expected (Java 25):
# openjdk version "25" 2025-09-16
# OpenJDK Runtime Environment Temurin-25+...

# Verify Tomcat is running
kubectl exec -n microservices-demo deployment/petclinic -- \
  /opt/tomcat/bin/catalina.sh version
```

## Troubleshooting

### Maven Build Fails: OutOfMemoryError

Increase Maven heap inside the Docker build:

```bash
docker run --rm -e MAVEN_OPTS="-Xmx2g" \
  -v /tmp/petclinic-build:/workspace -v ~/.m2:/root/.m2 \
  -w /workspace maven:3.9-eclipse-temurin-25 \
  mvn clean package -DskipTests
```

### Pod Startup Slow / StartupProbe Fails

On arm64 with official image (QEMU), or with any image under heavy OTel agent init:

- Startup probe `failureThreshold: 36` allows up to 6 minutes (36 × 10 s)
- If still failing, check logs: `kubectl logs -n microservices-demo deployment/petclinic`

### Image Not Found in Kind

```bash
# Verify local image exists
docker images | grep spring-framework-petclinic

# Reload manually
kind load docker-image localhost/spring-framework-petclinic:java25-arm64 --name jvm-bench
```

## References

- spring-framework-petclinic: https://github.com/spring-petclinic/spring-framework-petclinic
- Eclipse Temurin images: https://hub.docker.com/_/eclipse-temurin
- Apache Tomcat 11: https://tomcat.apache.org/tomcat-11.0-doc/
- Kind loading images: https://kind.sigs.k8s.io/docs/user/quick-start/#loading-an-image-into-your-cluster
