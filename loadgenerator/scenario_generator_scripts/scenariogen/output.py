"""Serialization and plotting utilities."""

import json
import os

import matplotlib.pyplot as plt
import numpy as np


def to_scenario_json(values: np.ndarray, spawn_rate: int) -> list[dict]:
    """Convert values array to [{"n_users": ..., "spawn_rate": ..., "duration": 1}, ...]."""
    return [{"n_users": int(v), "spawn_rate": spawn_rate, "duration": 1} for v in values]


def to_configmap_yaml(
    scenario_json: list[dict],
    name: str = "test-scenario",
    namespace: str = "microservices-demo",
) -> str:
    """Wrap scenario JSON in a Kubernetes ConfigMap YAML string.

    Matches the format in loadgenerator/scenarios/generated_scenarios/generated.yaml.
    """
    json_str = json.dumps(scenario_json, indent=2)
    indented = "\n".join("    " + line for line in json_str.split("\n"))
    return (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        f"  name: {name}\n"
        f"  namespace: {namespace}\n"
        "data:\n"
        "  scenario.json: |\n"
        f"{indented}\n"
    )


def save_plots(values: np.ndarray, output_dir: str, name: str) -> None:
    """Save CDF + timeseries plots to output_dir."""
    os.makedirs(output_dir, exist_ok=True)

    # CDF plot
    percentiles = np.linspace(0, 100, len(values))
    plt.plot(percentiles, sorted(values), ".")
    plt.xlabel("Percentile")
    plt.ylabel("Number of Users")
    plt.title(f"Workload Distribution ({name})")
    plt.savefig(os.path.join(output_dir, f"workload_sorted_{name}.png"))
    plt.clf()

    # Timeseries plot
    plt.figure(figsize=(16, 6))
    plt.plot(values)
    plt.xlabel("Time (minutes)")
    plt.ylabel("Number of Users")
    plt.title(f"Workload Timeseries ({name})")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"workload_timeseries_{name}.png"), dpi=150)
    plt.clf()
