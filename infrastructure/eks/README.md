# EKS Cluster — jvm-bench

Provisions a 3-node EKS cluster for running the java-on-kubernetes benchmarking
platform on AWS. Each node has a dedicated role and is selected via `nodeSelector`
(`node-role` label).

| Node group | Instance | vCPU | RAM | Role |
|------------|----------|------|-----|------|
| `workload` | m6i.2xlarge | 8 | 32 GB | Benchmark application (PetClinic) + Locust load generator |
| `tools` | m6i.xlarge | 4 | 16 GB | Prometheus + Grafana + OTel Collector |
| `akamas` | r6i.xlarge | 4 | 32 GB | Akamas offline (small tier) |

## Files

```
infrastructure/eks/
├── cluster.yaml        eksctl ClusterConfig — cluster + 3 managed node groups
├── storageclass.yaml   GP3 EBS StorageClass (default, used by Prometheus and Akamas PVCs)
└── provision.sh        Creates the cluster, updates kubeconfig, applies StorageClass
```

## Prerequisites

| Tool | Purpose |
|------|---------|
| [`eksctl`](https://eksctl.io) ≥ 0.190 | Cluster provisioning |
| [`kubectl`](https://kubernetes.io/docs/tasks/tools/) | Cluster interaction |
| [`aws` CLI](https://aws.amazon.com/cli/) v2 | Auth, kubeconfig update |
| [`helm`](https://helm.sh) ≥ 3.14 | Monitoring stack install |

AWS credentials must be configured and have permissions to create EKS clusters,
EC2 instances, IAM roles, and EBS volumes.

## 1 — Configuration

Before running anything, open `cluster.yaml` and set the correct region:

```yaml
metadata:
  name: jvm-bench
  region: eu-west-1   # ← change this
```

Set the matching value in `provision.sh` (or pass it via `--region`):

```bash
AWS_REGION="eu-west-1"   # must match cluster.yaml
```

## 2 — Provision the cluster

```bash
cd infrastructure/eks

# Default region (eu-west-1)
./provision.sh

# Override region
./provision.sh --region us-east-1

# With a named AWS profile
./provision.sh --region us-east-1 --profile my-profile
```

The script:
1. Creates the EKS cluster and the 3 managed node groups (≈ 15–20 min)
2. Updates your local `kubeconfig` and sets the current context to `jvm-bench`
3. Applies the GP3 `StorageClass`

Verify the nodes are ready and correctly labelled:

```bash
kubectl get nodes -L node-role
```

Expected output:
```
NAME            STATUS   ROLES    AGE   VERSION   NODE-ROLE
ip-10-x-x-x    Ready    <none>   5m    v1.31.x   workload
ip-10-x-x-x    Ready    <none>   5m    v1.31.x   tools
ip-10-x-x-x    Ready    <none>   5m    v1.31.x   akamas
```

## 3 — Deploy the monitoring stack

```bash
# Add the Prometheus community Helm repo (once)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack on the tools node
helm upgrade --install kube-prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --values monitoring/kube-prometheus-values.yaml \
  --wait
```

```bash
# Deploy the OTel Collector
kubectl apply -f monitoring/otel-collector.yaml
kubectl apply -f monitoring/servicemonitors.yaml
```

Verify:

```bash
kubectl get pods -n monitoring
```

## 4 — Deploy the benchmark application

> **Note:** `setup.sh` is designed for the local Kind cluster (it calls `kind load`
> and checks for the `kind` binary). On EKS, apply the manifests directly.

### PetClinic with the official image (Java 17, amd64)

```bash
kubectl create namespace microservices-demo --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f applications/petclinic/kubernetes-manifests/
```

### PetClinic with a custom Java version (requires ECR or a registry)

Build the image locally, push it to ECR (or any registry accessible from EKS),
then update the image reference in `petclinic.yaml` before applying:

```bash
# Build the image
./applications/petclinic/docker/build-images.sh --java-version 25

# Push to ECR (replace with your account/region)
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=eu-west-1
ECR_REPO="$AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/jvm-bench/spring-framework-petclinic"

aws ecr create-repository --repository-name jvm-bench/spring-framework-petclinic --region $REGION 2>/dev/null || true
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

ARCH=$(uname -m)
docker tag localhost/spring-framework-petclinic:java25-${ARCH} "$ECR_REPO:java25"
docker push "$ECR_REPO:java25"

# Apply manifests substituting the image reference
sed "s|springcommunity/spring-framework-petclinic:latest|$ECR_REPO:java25|g" \
  applications/petclinic/kubernetes-manifests/petclinic.yaml | kubectl apply -f -
```

Wait for the pod to become ready (Tomcat startup takes ~60–90 s):

```bash
kubectl get pods -n microservices-demo -w
```

## 5 — Access the services

EKS nodes are not directly reachable from localhost. Use `kubectl port-forward`
to access the UIs:

```bash
# Grafana  →  http://localhost:3000  (admin / admin)
kubectl port-forward -n monitoring svc/kube-prometheus-grafana 3000:80 &

# PetClinic  →  http://localhost:8081
kubectl port-forward -n microservices-demo svc/petclinic 8081:8080 &

# Locust  →  http://localhost:8089
kubectl port-forward -n microservices-demo svc/ak-loadgenerator 8089:8089 &
```

## 6 — Run the HPA autoscaling study

```bash
./studies/hpa-autoscaling/run-study.sh
```

The study applies an HPA on the `petclinic` deployment (70% CPU, 1–5 replicas),
switches the load generator to the intensive locustfile, and watches scaling:

```bash
kubectl get hpa -n microservices-demo -w
```

## 7 — Install Akamas

Follow the official Akamas offline installation guide targeting the `akamas` node:

- Docs: https://docs.akamas.io/akamas-docs/installing/kubernetes/
- Use `nodeSelector: { node-role: akamas }` in the Akamas Helm values
- The GP3 StorageClass applied in step 2 satisfies Akamas PVC requirements (70 GB)

## 8 — Tear down

```bash
# Delete application and monitoring resources first
kubectl delete namespace microservices-demo monitoring

# Delete the EKS cluster (removes all node groups, VPC, IAM roles)
eksctl delete cluster --name jvm-bench --region eu-west-1
```

> EBS volumes created by PVCs with `reclaimPolicy: Retain` are **not** deleted
> automatically. Delete them manually from the AWS Console or with:
> ```bash
> aws ec2 describe-volumes --filters Name=tag:kubernetes.io/created-for/pvc/namespace,Values=monitoring \
>   --query 'Volumes[].VolumeId' --output text | xargs -n1 aws ec2 delete-volume --volume-id
> ```
