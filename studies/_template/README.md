# Study: [Study Name]

## Objective

<!-- What question does this study answer? -->

## Hypothesis

<!-- What do you expect to observe? -->

## Setup

### Prerequisites

- Base platform is running (`./setup.sh` completed successfully)

### Study-Specific Resources

<!-- List what this study deploys on top of the base platform (HPA, custom configs, etc.) -->

## Methodology

### Load Profile

<!-- Describe the load pattern and why it was chosen -->

### Duration

<!-- How long should the study run? -->

### Metrics to Observe

<!-- Which dashboards and panels should be monitored -->

## How to Run

```bash
# 1. Apply study resources
./run-study.sh

# 2. Monitor via Grafana (port-forward if not already done)
kubectl port-forward -n monitoring svc/kube-prometheus-grafana 3000:80

# 3. When done, clean up study resources
./run-study.sh teardown
```

## Results

<!-- Post-study: paste screenshots, data, observations -->

## Conclusions

<!-- What was learned? Did the hypothesis hold? What are the recommendations? -->
