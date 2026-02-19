# Load Generator

Locust-based load generator for Online Boutique, designed to produce realistic and reproducible traffic patterns for benchmarking.

## How It Works

The load generator runs [Locust](https://locust.io/) inside Kubernetes and targets the frontend service. A sidecar container exports Locust metrics to Prometheus.

There are three operation modes:

1. **Manual mode** (default): Locust starts idle. Control tests via the Web UI or REST API.
2. **Online Random mode**: Set `RUN_ONLINE=True` — Locust starts immediately with a randomly varying workload.
3. **Online Scenario mode**: Set `RUN_ONLINE=True` and `SCENARIO_JSON=scenario.json` — Locust follows a predefined load scenario from a mounted ConfigMap.

## Applying a Scenario

Each study provides its own scenario as a Kubernetes ConfigMap named `test-scenario`. To apply:

```bash
kubectl apply -f studies/<study-name>/scenario-config.yaml
# Restart the pod to pick up the new ConfigMap
kubectl delete pod -l app=ak-loadgenerator -n microservices-demo
```

### Scenario Format

A scenario is a JSON array of workload phases:

```json
[
  {"n_users": 50, "spawn_rate": 10, "duration": 10},
  {"n_users": 200, "spawn_rate": 5, "duration": 20}
]
```

Fields:
- `n_users`: number of concurrent users
- `duration`: duration of this phase in minutes
- `spawn_rate`: users spawned per second
- `days` (optional): array of day numbers (1-7) when this phase runs. One simulated day = 3 real hours.

## Generating Scenarios

Use the scenario generator to create complex, reproducible load patterns:

```bash
cd scenario_generator_scripts
python generate.py --list                    # List available presets
python generate.py 1h_spike --output-dir .   # Generate a 1-hour spike scenario
python generate.py linear_ramp --seed 42     # Reproducible generation
```

See `scenario_generator_scripts/scenariogen/presets.py` for available presets.

## Accessing the UI

```bash
kubectl port-forward -n microservices-demo svc/ak-loadgenerator 8089:8089
# Open http://localhost:8089
```

## Locust APIs

```bash
# Start a test
curl -X POST -d 'user_count=100' -d 'spawn_rate=10' -d 'host=http://frontend:80' http://localhost:8089/swarm

# Stop a test
curl http://localhost:8089/stop

# Reset stats
curl http://localhost:8089/stats/reset
```

## References

- [Locust Documentation](https://docs.locust.io/en/stable/api.html)
- [Locust Prometheus Exporter](https://github.com/ContainerSolutions/locust_exporter)
