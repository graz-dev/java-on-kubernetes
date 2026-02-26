#!/usr/bin/env bash
set -euo pipefail

# Provision the jvm-bench EKS cluster.
#
# Creates 3 dedicated nodes:
#   workload  (m6i.2xlarge, 8 vCPU, 32 GB) — benchmark application + load generator
#   tools     (m6i.xlarge,  4 vCPU, 16 GB) — Prometheus / Grafana / OTel Collector
#   akamas    (r6i.xlarge,  4 vCPU, 32 GB) — Akamas offline (small tier)
#
# Usage:
#   ./provision.sh
#   ./provision.sh --region us-east-1
#   ./provision.sh --profile my-aws-profile

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLUSTER_CONFIG="$SCRIPT_DIR/cluster.yaml"
STORAGE_CLASS="$SCRIPT_DIR/storageclass.yaml"

# Must match metadata.name / metadata.region in cluster.yaml
CLUSTER_NAME="jvm-bench"
AWS_REGION="us-east-2"
AWS_PROFILE=""

# --- Argument parsing ---
while [[ $# -gt 0 ]]; do
  case $1 in
    --region)
      AWS_REGION="$2"
      shift 2
      ;;
    --profile)
      AWS_PROFILE="$2"
      shift 2
      ;;
    --help|-h)
      echo "Usage: $0 [--region <region>] [--profile <aws-profile>]"
      echo ""
      echo "Options:"
      echo "  --region <region>    AWS region (default: eu-west-1)"
      echo "                       Must also be set in cluster.yaml metadata.region"
      echo "  --profile <name>     AWS CLI profile to use"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1. Run $0 --help for usage."
      exit 1
      ;;
  esac
done

# --- Prerequisites ---
for cmd in eksctl kubectl aws; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not found"; exit 1; }
done

PROFILE_ARG=""
if [[ -n "$AWS_PROFILE" ]]; then
  PROFILE_ARG="--profile $AWS_PROFILE"
  CALLER=$(aws sts get-caller-identity $PROFILE_ARG --query 'Arn' --output text)
  echo "AWS profile : $AWS_PROFILE"
  echo "Identity    : $CALLER"
fi

echo ""
echo "=== jvm-bench EKS Cluster ==="
echo "Cluster : $CLUSTER_NAME"
echo "Region  : $AWS_REGION"
echo ""

# --- Create cluster ---
echo "[1/3] Cluster..."
if eksctl get cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" $PROFILE_ARG >/dev/null 2>&1; then
  echo "  Cluster '$CLUSTER_NAME' already exists — skipping creation."
else
  eksctl create cluster -f "$CLUSTER_CONFIG" $PROFILE_ARG
  echo "  Cluster created."
fi

# --- Update kubeconfig ---
echo ""
echo "[2/3] Updating kubeconfig..."
aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" $PROFILE_ARG
echo "  Context: $(kubectl config current-context)"

# --- Apply StorageClass ---
echo ""
echo "[3/3] Applying GP3 StorageClass..."
kubectl apply -f "$STORAGE_CLASS"

# --- Summary ---
echo ""
echo "=== Done ==="
echo ""
kubectl get nodes -L node-role
echo ""
echo "Next steps:"
echo "  Deploy monitoring:  kubectl apply -f monitoring/"
echo "  Deploy application: ./setup.sh --app petclinic"
echo "  Install Akamas:     https://docs.akamas.io/akamas-docs/installing/kubernetes/"
echo ""
echo "Tear down:"
echo "  eksctl delete cluster --name $CLUSTER_NAME --region $AWS_REGION $PROFILE_ARG"
