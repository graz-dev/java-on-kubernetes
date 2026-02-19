#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="jvm-bench"

echo "Deleting Kind cluster '$CLUSTER_NAME'..."
kind delete cluster --name "$CLUSTER_NAME"
echo "Done. All resources have been removed."
