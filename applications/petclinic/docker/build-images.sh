#!/usr/bin/env bash
set -euo pipefail

# Spring Framework PetClinic — Build Script
#
# Builds a single WAR image using Tomcat 11 + eclipse-temurin:<JAVA_VERSION>.
#
# Usage:
#   ./build-images.sh                       # Build with Java 17 (default)
#   ./build-images.sh --java-version 25     # Build with Java 25
#   ./build-images.sh --load-to-kind        # Build and load to Kind cluster

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="/tmp/petclinic-build-$$"
REPO_URL="https://github.com/spring-petclinic/spring-framework-petclinic.git"
JAVA_VERSION="17"
ARCH=$(uname -m)

# Parse arguments
LOAD_TO_KIND=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --load-to-kind)
      LOAD_TO_KIND=true
      shift
      ;;
    --java-version)
      JAVA_VERSION="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Build spring-framework-petclinic WAR image for native architecture."
      echo ""
      echo "Options:"
      echo "  --java-version <N>  Java version to use (default: 17)"
      echo "  --load-to-kind      Load built image into Kind cluster 'jvm-bench'"
      echo "  --help, -h          Show this help message"
      echo ""
      echo "Examples:"
      echo "  $0                               # Build with Java 17"
      echo "  $0 --java-version 25             # Build with Java 25"
      echo "  $0 --java-version 25 --load-to-kind"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1. Run $0 --help for usage."
      exit 1
      ;;
  esac
done

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
    echo "ERROR: Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

IMAGE_TAG="localhost/spring-framework-petclinic:java${JAVA_VERSION}-${ARCH}"

echo ""
echo "=== Spring Framework PetClinic Build (Java $JAVA_VERSION) ==="
echo ""
echo "Image tag:      $IMAGE_TAG"
echo "Platform:       $PLATFORM"
echo "Build dir:      $BUILD_DIR"
echo "Load to Kind:   $LOAD_TO_KIND"
echo ""

# Check prerequisites
echo "[1/5] Checking prerequisites..."

if ! command -v docker &>/dev/null; then
  echo "ERROR: Docker not found."
  exit 1
fi

if [ "$LOAD_TO_KIND" = true ] && ! command -v kind &>/dev/null; then
  echo "ERROR: kind not found but --load-to-kind requested."
  exit 1
fi

# Determine Maven build method: local or Docker-based
USE_DOCKER_BUILD=false
if command -v java &>/dev/null && command -v mvn &>/dev/null; then
  JAVA_INSTALLED=$(java -version 2>&1 | head -n 1 | cut -d'"' -f2 | cut -d'.' -f1)
  if [ "$JAVA_INSTALLED" -lt "$JAVA_VERSION" ]; then
    echo "  WARNING: Java $JAVA_INSTALLED detected, Java $JAVA_VERSION requested. Using Docker build."
    USE_DOCKER_BUILD=true
  else
    echo "  Local Java $JAVA_INSTALLED + Maven found"
  fi
else
  echo "  Local Java/Maven not found. Will use Docker for Maven build (maven:3.9-eclipse-temurin-${JAVA_VERSION})."
  USE_DOCKER_BUILD=true
fi

echo "Prerequisites OK"

# Clone repository
echo ""
echo "[2/5] Cloning repository..."
mkdir -p "$BUILD_DIR"
git clone --depth 1 "$REPO_URL" "$BUILD_DIR"
cd "$BUILD_DIR"
echo "Repository cloned to $BUILD_DIR"

# Build with Maven
echo ""
echo "[3/5] Building with Maven..."

if [ "$USE_DOCKER_BUILD" = true ]; then
  MAVEN_IMAGE="maven:3.9-eclipse-temurin-${JAVA_VERSION}"
  echo "  Running Maven inside Docker ($MAVEN_IMAGE)..."
  # Resolve real HOME (may be empty in non-login shells)
  REAL_HOME="${HOME:-$(eval echo ~)}"
  M2_CACHE="${REAL_HOME}/.m2"
  # No --platform: JARs/WARs are platform-independent bytecode
  docker run --rm \
    -v "$BUILD_DIR":/workspace \
    -v "${M2_CACHE}:/root/.m2" \
    -w /workspace \
    "$MAVEN_IMAGE" \
    mvn clean package -DskipTests
else
  echo "  Running: mvn clean package -DskipTests"
  mvn clean package -DskipTests
fi

echo "Maven build complete"

# Find WAR (finalName in pom.xml is "petclinic", so file is petclinic.war)
WAR_FILE=$(ls "${BUILD_DIR}/target/"*.war 2>/dev/null | grep -v "original" | head -1)
if [ -z "$WAR_FILE" ]; then
  echo "ERROR: WAR not found in $BUILD_DIR/target/"
  exit 1
fi
echo "  WAR: $WAR_FILE"

# Build Docker image
echo ""
echo "[4/5] Building Docker image ($IMAGE_TAG)..."

BUILD_CTX=$(mktemp -d)
cp "$WAR_FILE" "${BUILD_CTX}/spring-framework-petclinic.war"
cp "${SCRIPT_DIR}/jvm-entrypoint.sh" "${BUILD_CTX}/jvm-entrypoint.sh"

docker build \
  --platform "$PLATFORM" \
  -t "$IMAGE_TAG" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  --build-arg "JAVA_VERSION=${JAVA_VERSION}" \
  "$BUILD_CTX/"

rm -rf "$BUILD_CTX"
echo "Built: $IMAGE_TAG"

# Load to Kind
if [ "$LOAD_TO_KIND" = true ]; then
  echo ""
  echo "[5/5] Loading image into Kind cluster 'jvm-bench'..."

  if ! kind get clusters | grep -q "^jvm-bench$"; then
    echo "  WARNING: Kind cluster 'jvm-bench' not found. Create it first with: ./setup.sh"
    echo "  Skipping Kind load."
  else
    kind load docker-image "$IMAGE_TAG" --name jvm-bench
    echo "Image loaded to Kind cluster"
  fi
else
  echo ""
  echo "[5/5] Skipping Kind load (use --load-to-kind to enable)"
fi

# Summary
echo ""
echo "=== Build Complete ==="
echo ""
echo "Image: $IMAGE_TAG"
echo ""
echo "Next steps:"
echo "  ./setup.sh --app petclinic --java-version $JAVA_VERSION"
echo ""
echo "To verify Java version in running pod:"
echo "  kubectl exec -n microservices-demo deployment/petclinic -- java -version"
echo ""
echo "To clean up build directory:"
echo "  rm -rf $BUILD_DIR"
