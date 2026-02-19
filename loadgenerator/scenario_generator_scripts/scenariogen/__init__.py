"""Scenario generator module.

Usage::

    from scenariogen import run_preset

    run_preset("7days", output_dir="output", seed=42)
"""

import json
import os

import numpy as np

from .core import generate_values
from .output import save_plots, to_configmap_yaml, to_scenario_json
from .phases import Phase, build_phase_values
from .presets import PRESETS

__all__ = [
    "generate",
    "run_preset",
    "generate_values",
    "build_phase_values",
    "Phase",
    "to_scenario_json",
    "to_configmap_yaml",
    "save_plots",
    "PRESETS",
]


def generate(preset_name: str, seed: int | None = None) -> np.ndarray:
    """Generate a scenario from a named preset. Returns 1-D array of user counts."""
    preset = dict(PRESETS[preset_name])  # shallow copy to avoid mutation
    ptype = preset.pop("type")
    preset.pop("spawn_rate", None)  # only used by output functions
    preset["seed"] = seed

    if ptype == "core":
        return generate_values(**preset)
    elif ptype == "phases":
        return build_phase_values(**preset)
    else:
        raise ValueError(f"Unknown preset type: {ptype}")


def run_preset(
    preset_name: str,
    output_dir: str = "output",
    seed: int | None = None,
    configmap_name: str = "test-scenario",
    namespace: str = "microservices-demo",
) -> None:
    """Run a preset end-to-end: generate values, write JSON, YAML ConfigMap, and plots."""
    preset = PRESETS[preset_name]
    spawn_rate = preset["spawn_rate"]

    values = generate(preset_name, seed=seed)
    scenario_json = to_scenario_json(values, spawn_rate)

    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, f"{preset_name}.json")
    with open(json_path, "w") as f:
        json.dump(scenario_json, f, indent=2)

    yaml_path = os.path.join(output_dir, f"{preset_name}.yaml")
    with open(yaml_path, "w") as f:
        f.write(to_configmap_yaml(scenario_json, name=configmap_name, namespace=namespace))

    save_plots(values, output_dir, preset_name)

    print(f"{preset_name}: {len(values)} minutes, wrote {json_path}, {yaml_path}, and plots")
