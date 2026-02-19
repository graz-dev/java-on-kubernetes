"""Phase-concat builder for scenarios like 1h_spike and linear_ramp."""

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass
class Phase:
    """A single phase in a phase-concat scenario.

    kind="flat":  generate normal(target, sigma, duration_min)
    kind="ramp":  generate linspace(start, target, duration_min) + normal(0, sigma, duration_min)
    """

    kind: Literal["flat", "ramp"]
    duration_min: int
    target: float
    start: float | None = None  # only used for ramp
    sigma: float = 3.0


def build_phase_values(
    phases: list[Phase],
    spike_prob: float = 0.0,
    spike_mult: float = 1.0,
    load_threshold: float = 200,
    min_value: float = 1,
    seed: int | None = None,
) -> np.ndarray:
    """Build a 1-D values array by concatenating phases.

    Parameters
    ----------
    phases : list[Phase]
        Ordered list of phases to concatenate.
    spike_prob : float
        Per-minute probability of a spike during high-load minutes.
    spike_mult : float
        Multiplicative factor for spikes.
    load_threshold : float
        Boundary for spike eligibility.
    min_value : float
        Floor clamp.
    seed : int | None
        RNG seed for reproducibility.
    """
    if seed is not None:
        np.random.seed(seed)

    segments: list[np.ndarray] = []

    for phase in phases:
        if phase.kind == "flat":
            vals = np.random.normal(phase.target, phase.sigma, phase.duration_min)
        elif phase.kind == "ramp":
            start = phase.start if phase.start is not None else 0
            base = np.linspace(start, phase.target, phase.duration_min)
            vals = base + np.random.normal(0, phase.sigma, phase.duration_min)
        segments.append(vals)

    values = np.clip(np.concatenate(segments), min_value, None)

    # --- spike injection ---
    if spike_prob > 0:
        for i in range(len(values)):
            if values[i] > load_threshold and np.random.random() < spike_prob:
                values[i] *= spike_mult
        values = np.clip(values, min_value, None)

    return values
