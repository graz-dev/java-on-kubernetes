"""All existing scenarios as preset parameter dicts.

Each preset has:
  "type"       : "core" (uses generate_values) or "phases" (uses build_phase_values)
  "spawn_rate" : int, used only by output functions
  + all kwargs for the corresponding generation function (except seed).
"""

from .phases import Phase

# --- shared data ---

_WEEK_AVG_VALUES = [
    [40, 650, 470, 800, 360, 40],  # Monday
    [40, 610, 430, 750, 320, 40],  # Tuesday
    [40, 680, 500, 820, 400, 40],  # Wednesday
    [40, 650, 470, 850, 360, 40],  # Thursday
    [40, 610, 430, 720, 320, 40],  # Friday
    [40, 570, 400, 680, 290, 40],  # Saturday
    [40, 540, 360, 650, 250, 40],  # Sunday
]

_STANDARD_DURATIONS = [6, 4, 2, 6, 2, 4]

# --- presets ---

PRESETS: dict[str, dict] = {
    # Original generator.py: 2 weeks, low load, single noise, no spikes
    "2weeks": {
        "type": "core",
        "avg_values": [
            [6, 400, 100, 380, 200, 6],
            [6, 450, 120, 400, 180, 6],
            [6, 380, 200, 430, 220, 6],
            [6, 500, 150, 480, 230, 6],
            [6, 450, 100, 300, 150, 6],
            [6, 50, 30, 70, 9, 6],
            [6, 10, 10, 30, 50, 6],
        ],
        "durations": _STANDARD_DURATIONS,
        "day_length_hours": 3,
        "num_days": 14,  # 2 weeks — avg_values rows cycle via day % 7
        "spawn_rate": 1,
        "sigma_week": 0.1,
        "sigma_low": 10,
        "sigma_high": 10,  # same as sigma_low → uniform noise
        "spike_prob": 0,
    },
    # 7-day week compressed into 24 hours
    "7days": {
        "type": "core",
        "avg_values": _WEEK_AVG_VALUES,
        "durations": _STANDARD_DURATIONS,
        "day_length_hours": 24 / 7,
        "num_days": 7,
        "spawn_rate": 50,
        # uses defaults: sigma_week=0.15, sigma_low=3, sigma_high=80,
        # spike_prob=0.03, spike_mult=1.4, load_threshold=200
    },
    # HPA stress test — identical parameters to 7days (kept as alias)
    "hpa_stress": {
        "type": "core",
        "avg_values": _WEEK_AVG_VALUES,
        "durations": _STANDARD_DURATIONS,
        "day_length_hours": 24 / 7,
        "num_days": 7,
        "spawn_rate": 50,
    },
    # Thursday only, compressed to 3 hours (180 min)
    # Phases: 6 flat segments with 5-min ramps on big transitions only
    # 650→470 midday dip is minor (~180 users), so it transitions instantly
    "thursday_3h": {
        "type": "phases",
        "phases": [
            Phase("flat", 40, 40, sigma=3),          # night
            Phase("ramp", 5, 650, start=40, sigma=80),  # big ramp up
            Phase("flat", 27, 650, sigma=80),         # morning plateau
            Phase("flat", 13, 470, sigma=80),         # midday dip (instant)
            Phase("ramp", 5, 850, start=470, sigma=80),  # big ramp up
            Phase("flat", 40, 850, sigma=80),         # afternoon peak
            Phase("ramp", 5, 360, start=850, sigma=80),  # big ramp down
            Phase("flat", 13, 360, sigma=80),         # evening
            Phase("ramp", 5, 40, start=360, sigma=3),   # big ramp down
            Phase("flat", 27, 40, sigma=3),           # night
        ],
        "spawn_rate": 50,
        "spike_prob": 0.03,
        "spike_mult": 1.4,
    },
    # 1-hour spike: low → ramp up → sustained high → ramp down → low
    "1h_spike": {
        "type": "phases",
        "phases": [
            Phase("flat", 15, 50, sigma=3),
            Phase("ramp", 5, 850, start=50, sigma=80),
            Phase("flat", 20, 850, sigma=80),
            Phase("ramp", 5, 50, start=850, sigma=80),
            Phase("flat", 15, 50, sigma=3),
        ],
        "spawn_rate": 50,
        "spike_prob": 0.03,
        "spike_mult": 1.4,
    },
    # Simple 1-hour linear ramp, no noise
    "linear_ramp": {
        "type": "phases",
        "phases": [Phase("ramp", 60, 1500, start=10, sigma=0)],
        "spawn_rate": 50,
    },
}
