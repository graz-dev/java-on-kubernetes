#!/usr/bin/env bash
set -euo pipefail

# Spring PetClinic Microservices - Build Script for Java 25 + arm64
#
# Usage:
#   ./build-images.sh                    # Build all services
#   ./build-images.sh --load-to-kind     # Build and load to Kind cluster
#   ./build-images.sh api-gateway        # Build specific service only

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="/tmp/petclinic-build-$$"
REPO_URL="https://github.com/spring-petclinic/spring-petclinic-microservices.git"
JAVA_VERSION="25"
ARCH=$(uname -m)

# Service list
ALL_SERVICES=(
  "spring-petclinic-discovery-server"
  "spring-petclinic-api-gateway"
  "spring-petclinic-customers-service"
  "spring-petclinic-visits-service"
  "spring-petclinic-vets-service"
)

# Parse arguments
LOAD_TO_KIND=false
SERVICES_TO_BUILD=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --load-to-kind)
      LOAD_TO_KIND=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS] [SERVICES...]"
      echo ""
      echo "Build Spring PetClinic microservices with Java 25 for native architecture."
      echo ""
      echo "Options:"
      echo "  --load-to-kind    Load built images into Kind cluster 'jvm-bench'"
      echo "  --help, -h        Show this help message"
      echo ""
      echo "Services (build specific services, or all if none specified):"
      echo "  discovery-server, api-gateway, customers-service, visits-service, vets-service"
      echo ""
      echo "Examples:"
      echo "  $0                              # Build all services"
      echo "  $0 --load-to-kind               # Build all and load to Kind"
      echo "  $0 api-gateway customers-service # Build specific services"
      exit 0
      ;;
    *)
      # Assume it's a service name (short form)
      SERVICES_TO_BUILD+=("spring-petclinic-$1")
      shift
      ;;
  esac
done

# If no services specified, build all
if [ ${#SERVICES_TO_BUILD[@]} -eq 0 ]; then
  SERVICES_TO_BUILD=("${ALL_SERVICES[@]}")
fi

# Detect architecture and set platform
case "$ARCH" in
  x86_64|amd64)
    PLATFORM="linux/amd64"
    echo "Architecture: x86_64 (Intel/AMD)"
    ;;
  arm64|aarch64)
    PLATFORM="linux/arm64"
    echo "Architecture: arm64 (Apple Silicon)"
    ;;
  *)
    echo "❌ ERROR: Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

echo ""
echo "=== Spring PetClinic Build for Java $JAVA_VERSION ==="
echo ""
echo "Services to build: ${SERVICES_TO_BUILD[*]}"
echo "Platform: $PLATFORM"
echo "Build directory: $BUILD_DIR"
echo "Load to Kind: $LOAD_TO_KIND"
echo ""

# Check prerequisites
echo "[1/6] Checking prerequisites..."

if ! command -v java &> /dev/null; then
  echo "❌ ERROR: Java not found. Install Java 25: brew install openjdk@25"
  exit 1
fi

JAVA_INSTALLED=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)
if [ "$JAVA_INSTALLED" -lt 17 ]; then
  echo "⚠️  WARNING: Java $JAVA_INSTALLED detected. Java 25 recommended for builds."
fi

if ! command -v mvn &> /dev/null; then
  echo "❌ ERROR: Maven not found. Install: brew install maven"
  exit 1
fi

if ! command -v docker &> /dev/null; then
  echo "❌ ERROR: Docker not found. Install: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ "$LOAD_TO_KIND" = true ] && ! command -v kind &> /dev/null; then
  echo "❌ ERROR: Kind not found but --load-to-kind specified. Install: brew install kind"
  exit 1
fi

echo "✓ All prerequisites satisfied"

# Clone repository
echo ""
echo "[2/6] Cloning repository..."
mkdir -p "$BUILD_DIR"
git clone --depth 1 "$REPO_URL" "$BUILD_DIR"
cd "$BUILD_DIR"

echo "✓ Repository cloned to $BUILD_DIR"

# Update Dockerfiles to Java 25
echo ""
echo "[3/6] Updating Dockerfiles to Java $JAVA_VERSION..."

for service in "${SERVICES_TO_BUILD[@]}"; do
  if [ -f "$service/Dockerfile" ]; then
    sed -i.bak "s/eclipse-temurin:[0-9]*-jre/eclipse-temurin:${JAVA_VERSION}-jre/g" "$service/Dockerfile"
    echo "  ✓ Updated $service/Dockerfile"
  else
    echo "  ⚠️  WARNING: $service/Dockerfile not found, skipping"
  fi
done

# Build with Maven
echo ""
echo "[4/6] Building with Maven (this may take 15-20 minutes)..."
echo "  → Running: mvn clean package -DskipTests"

# Build only the specified services
SERVICE_MODULES=$(printf ",%s" "${SERVICES_TO_BUILD[@]}")
SERVICE_MODULES=${SERVICE_MODULES:1}  # Remove leading comma

mvn clean package -DskipTests -pl "$SERVICE_MODULES" -am

echo "✓ Maven build complete"

# Build Docker images
echo ""
echo "[5/6] Building Docker images..."

BUILT_IMAGES=()

for service in "${SERVICES_TO_BUILD[@]}"; do
  if [ ! -f "$service/target/"*.jar ]; then
    echo "  ⚠️  WARNING: JAR not found for $service, skipping Docker build"
    continue
  fi

  IMAGE_TAG="localhost/${service}:java${JAVA_VERSION}-${ARCH}"
  echo "  → Building: $IMAGE_TAG"

  docker build \
    --platform "$PLATFORM" \
    -t "$IMAGE_TAG" \
    "$service/" \
    --quiet

  echo "  ✓ Built: $IMAGE_TAG"
  BUILT_IMAGES+=("$IMAGE_TAG")
done

# Load to Kind
if [ "$LOAD_TO_KIND" = true ]; then
  echo ""
  echo "[6/6] Loading images to Kind cluster 'jvm-bench'..."

  # Check if Kind cluster exists
  if ! kind get clusters | grep -q "^jvm-bench$"; then
    echo "  ⚠️  WARNING: Kind cluster 'jvm-bench' not found"
    echo "  Create cluster with: ./setup.sh"
    echo ""
    echo "  Skipping Kind load step."
  else
    for image in "${BUILT_IMAGES[@]}"; do
      echo "  → Loading: $image"
      kind load docker-image "$image" --name jvm-bench
    done
    echo "✓ All images loaded to Kind cluster"
  fi
else
  echo ""
  echo "[6/6] Skipping Kind load (use --load-to-kind to enable)"
fi

# Summary
echo ""
echo "=== Build Complete ==="
echo ""
echo "Built images:"
for image in "${BUILT_IMAGES[@]}"; do
  echo "  - $image"
done
echo ""
echo "Next steps:"
echo "  1. Update applications/petclinic/kubernetes-manifests/petclinic.yaml to use these images"
echo "  2. Run: ./setup.sh --app petclinic"
echo ""
echo "To verify Java version in running pods:"
echo "  kubectl exec -n microservices-demo deployment/customers-service -- java -version"
echo ""
echo "To clean up build directory:"
echo "  rm -rf $BUILD_DIR"
