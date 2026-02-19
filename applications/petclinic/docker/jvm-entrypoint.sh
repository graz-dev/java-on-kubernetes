#!/bin/sh
# JVM Flags Entrypoint
#
# Runs java -XX:+PrintFlagsFinal at startup to capture the actual JVM configuration,
# then injects key flags as OTel resource attributes so they appear as Prometheus
# labels on every JVM metric — visible in Grafana without hardcoding.
#
# JAVA_TOOL_OPTIONS is unset for the flag capture run to avoid loading the OTel
# agent (slow, noisy) during a process that exits immediately.

FLAGS=$(env -u JAVA_TOOL_OPTIONS java -XX:+PrintFlagsFinal -version 2>&1)

# Extract a single flag value by exact name match on field 2
get_flag() {
  echo "$FLAGS" | awk -v f="$1" '$2 == f { print $4; exit }'
}

# GC algorithm — detect which collector is active
USE_G1=$(get_flag UseG1GC)
USE_ZGC=$(get_flag UseZGC)
USE_SHN=$(get_flag UseShenandoahGC)
USE_SER=$(get_flag UseSerialGC)
USE_PAR=$(get_flag UseParallelGC)

if   [ "$USE_ZGC" = "true" ]; then GC_NAME="ZGC"
elif [ "$USE_SHN" = "true" ]; then GC_NAME="Shenandoah"
elif [ "$USE_G1"  = "true" ]; then GC_NAME="G1GC"
elif [ "$USE_PAR" = "true" ]; then GC_NAME="Parallel"
elif [ "$USE_SER" = "true" ]; then GC_NAME="Serial"
else                                GC_NAME="unknown"
fi

# Memory configuration
MAX_HEAP=$(get_flag MaxHeapSize)
INIT_HEAP=$(get_flag InitialHeapSize)

# GC tuning
MAX_PAUSE=$(get_flag MaxGCPauseMillis)
PAR_THREADS=$(get_flag ParallelGCThreads)
CONC_THREADS=$(get_flag ConcGCThreads)
G1_REGION=$(get_flag G1HeapRegionSize)

# JIT compiler
TIERED=$(get_flag TieredCompilation)
CI_COMPILERS=$(get_flag CICompilerCount)

# Other
COMPRESSED_OOPS=$(get_flag UseCompressedOops)
CPU_COUNT=$(get_flag ActiveProcessorCount)

# Build the OTel resource attribute string
JVM_CONFIG="jvm.config.gc=${GC_NAME}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.heap.max=${MAX_HEAP}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.heap.init=${INIT_HEAP}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.gc.max.pause.ms=${MAX_PAUSE}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.gc.threads.parallel=${PAR_THREADS}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.gc.threads.concurrent=${CONC_THREADS}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.gc.g1.region.bytes=${G1_REGION}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.jit.tiered=${TIERED}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.jit.compilers=${CI_COMPILERS}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.compressed.oops=${COMPRESSED_OOPS}"
JVM_CONFIG="${JVM_CONFIG},jvm.config.cpu.count=${CPU_COUNT}"

# Append to any existing resource attributes from the Kubernetes manifest
if [ -n "$OTEL_RESOURCE_ATTRIBUTES" ]; then
  export OTEL_RESOURCE_ATTRIBUTES="${OTEL_RESOURCE_ATTRIBUTES},${JVM_CONFIG}"
else
  export OTEL_RESOURCE_ATTRIBUTES="${JVM_CONFIG}"
fi

exec /opt/tomcat/bin/catalina.sh run
