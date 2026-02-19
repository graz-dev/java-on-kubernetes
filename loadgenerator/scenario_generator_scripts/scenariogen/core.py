"""Core generation engine: time compaction, noise, and spike injection."""

import numpy as np


def generate_values(
    avg_values: np.ndarray,
    durations: list[int],
    day_length_hours: float,
    num_days: int,
    sigma_week: float = 0.15,
    sigma_low: float = 3,
    sigma_high: float = 80,
    load_threshold: float = 200,
    spike_prob: float = 0.03,
    spike_mult: float = 1.4,
    min_value: float = 1,
    seed: int | None = None,
) -> np.ndarray:
    """Core generation: time compaction + noise + spikes. Returns 1-D array of user counts.

    Parameters
    ----------
    avg_values : array of shape (num_rows, num_steps)
        Average user counts per (day, step). Rows are cycled if num_days > num_rows.
    durations : list[int]
        Step durations in hours (must sum to 24).
    day_length_hours : float
        How many real hours each simulated 24h day is compacted into.
    num_days : int
        Number of simulated days.
    sigma_week : float
        Relative std-dev for day-to-day variance (applied as sigma_week * avg).
    sigma_low : float
        Absolute noise std-dev for low-load periods (avg <= load_threshold).
    sigma_high : float
        Absolute noise std-dev for high-load periods (avg > load_threshold).
    load_threshold : float
        Boundary between low/high noise regimes.
    spike_prob : float
        Per-minute probability of a spike during high-load minutes.
    spike_mult : float
        Multiplicative factor for spikes.
    min_value : float
        Floor clamp for generated values.
    seed : int | None
        RNG seed for reproducibility.
    """
    if seed is not None:
        np.random.seed(seed)

    avg_values = np.asarray(avg_values, dtype=float)
    assert sum(durations) == 24
    assert len(durations) == avg_values.shape[1]

    # --- time compaction ---
    compaction_factor = 24 / day_length_hours
    step_length = 60 / compaction_factor
    durations_comp = (np.asarray(durations, dtype=int) * step_length).astype(int)

    actual_samples = num_days * int(sum(durations_comp))
    values = np.zeros(actual_samples)
    idx = 0

    # --- main generation loop ---
    num_rows = avg_values.shape[0]
    for day in range(num_days):
        row = day % num_rows
        for step in range(len(durations_comp)):
            avg = avg_values[row, step]
            this_avg = np.random.normal(avg, sigma_week * avg)
            duration = durations_comp[step]
            sigma = sigma_high if avg > load_threshold else sigma_low
            vals = np.random.normal(this_avg, sigma, duration)
            vals = np.clip(vals, min_value, None)
            values[idx : idx + duration] = vals
            idx += duration

    # --- spike injection ---
    if spike_prob > 0:
        for i in range(actual_samples):
            if values[i] > load_threshold and np.random.random() < spike_prob:
                values[i] *= spike_mult
        values = np.clip(values, min_value, None)

    return values
