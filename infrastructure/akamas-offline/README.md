# Akamas Installation — EKS

Installs Akamas on the dedicated `akamas` node of the `jvm-bench` EKS cluster.
Images are pulled directly from the Akamas public registry — no private registry needed.

**Tier:** Small (up to 3 concurrent optimization studies)
**Node:** `r6i.xlarge` — 4 vCPU, 32 GB RAM, labelled `node-role: akamas`
**Namespace:** `akamas`
**Helm chart:** `akamas` v1.7.0 from `http://helm.akamas.io/charts`

## Files

```
infrastructure/akamas-offline/
├── akamas.yaml    Helm values (fill in placeholders before use)
└── README.md      This file
```

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| `kubectl` | ≥ 1.24 | Check pods, manage secrets |
| `helm` | ≥ 3.0 | Install the Akamas chart |
| `python` | ≥ 3.10 | Akamas CLI (step 4) |

The EKS cluster must already be running with:
- The `akamas` node group ready (`kubectl get nodes -L node-role`)
- The `gp3` StorageClass applied (`kubectl get storageclass`)

Both are provisioned by `infrastructure/eks/provision.sh`.

---

## Step 1 — Configure `akamas.yaml`

Edit `akamas.yaml` and replace every `<PLACEHOLDER>`:

| Placeholder | Value |
|---|---|
| `CUSTOMER_NAME` | Your customer name from the Akamas license |
| `ADMIN_PASSWORD` | Initial admin password |
| `INSTANCE_HOSTNAME` | Use `http://localhost` if accessing via port-forward |

---

## Step 2 — Install the Helm chart

```bash
cd infrastructure/akamas-offline

helm upgrade --install \
  --create-namespace --namespace akamas \
  --repo http://helm.akamas.io/charts \
  --version '1.7.0' \
  -f .akamas.values.yaml \
  akamas akamas
```

Monitor pod startup (~5–10 min):

```bash
kubectl get pods -n akamas -w
```

All 19 pods should reach `Running` status:
`airflow`, `analyzer`, `campaign`, `database`, `elasticsearch`, `keycloak`,
`kibana`, `kong`, `license`, `log`, `logstash`, `metrics`, `optimizer`,
`orchestrator`, `store`, `system`, `telemetry`, `ui`, `users`.

---

## Step 3 — Install the Akamas CLI

```bash
curl -o akamas_cli \
  https://s3.us-east-2.amazonaws.com/akamas/cli/$(curl -s https://s3.us-east-2.amazonaws.com/akamas/cli/stable.txt)/linux_64/akamas

sudo mv akamas_cli /usr/local/bin/akamas
chmod 755 /usr/local/bin/akamas

akamas version
```

---

## Step 4 — Access Akamas

Port-forward the Akamas UI:

```bash
kubectl port-forward service/ui 9000:http
```

The UI is now available at **http://localhost:9000**.

Configure the CLI:

```bash
mkdir -p ~/.akamas
cat > ~/.akamas/akamasconf <<EOF
apiAddress: http://localhost:8080/akapi
verifySsl: false
workspace: default
EOF
```

Verify the server is up:

```bash
akamas status
# Expected: OK
```

---

## Step 5 — Install the license

You cannot log in until the license is installed.

```bash
akamas install license <path-to-license-file>
```

Then log in:

```bash
akamas login -u admin -p <ADMIN_PASSWORD> -w default
```

Retrieve the admin password if needed:

```bash
kubectl get secret -n akamas akamas-admin-credentials \
  -o go-template='{{.data.password | base64decode}}'
```

---

## Uninstall

```bash
helm uninstall akamas --namespace akamas
kubectl delete namespace akamas
```

> PersistentVolumes created with `reclaimPolicy: Retain` (the `gp3` StorageClass
> default) are **not** deleted automatically. Remove them with:
> ```bash
> kubectl get pv | grep akamas
> kubectl delete pv <PV_NAME>
> ```
> Then delete the corresponding EBS volumes from the AWS Console.
