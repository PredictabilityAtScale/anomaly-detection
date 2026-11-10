"""Deterministic anonymous synthetic fixtures, independent of customer values."""
import math
import random


def synthetic_cases():
    rng = random.Random(1729)
    noise = [rng.uniform(-1, 1) for _ in range(112)]
    series = {
        "flat": [20.] * 112,
        "zero": [0.] * 112,
        "linear_up": [10 + .4 * i for i in range(112)],
        "linear_down_signed": [20 - .4 * i for i in range(112)],
        "exponential": [10 * math.exp(.012 * i) for i in range(112)],
        "weekly": [30 + [-3, -1, 1, 2, 4, -1, -2][i % 7] for i in range(112)],
        "no_stable_season": [20 + v for v in noise],
        "isolated_spikes": [20 + .2 * i + (120 if i in (54, 68, 82) else 0) for i in range(112)],
        "sustained_shift": [10. if i < 65 else 30. for i in range(112)],
        "changing_slope": [10 + .1 * i + .7 * max(0, i - 65) for i in range(112)],
    }
    for name, values in series.items():
        yield {"name": name, "values": values, "origins": [56, 70, 84], "horizon": 14,
               "config": {}, "baseline_period": 7 if name == "weekly" else 1}
    yield {"name": "hourly_daily", "values": [20 + i % 24 for i in range(264)],
           "origins": [168, 192, 216], "horizon": 24,
           "config": {"max_training_points": 192}, "baseline_period": 24}
    yield {"name": "monthly_annual", "values": [20 + 5 * math.sin(2 * math.pi * i / 12) for i in range(84)],
           "origins": [48, 60, 72], "horizon": 12,
           "config": {"seasonality": {"period": 12}, "max_training_points": 72}, "baseline_period": 12}
    yield {"name": "daily_annual_positional", "values": [20 + 5 * math.sin(2 * math.pi * i / 365) for i in range(1530)],
           "origins": [1095, 1200, 1460], "horizon": 30,
           "config": {"seasonality": {"period": 365}, "max_training_points": 1460, "trend": "none"}, "baseline_period": 365}

    # Declared stress cases; selection sees only each outer training prefix.
    for seed in (42, 1729, 123):
        generator = random.Random(seed)
        stationary = [100 + generator.uniform(-10, 10) for _ in range(112)]
        yield {"name": f"stationary_seed_{seed}", "values": stationary,
               "origins": [56, 70, 84], "horizon": 7, "config": {"trend": "none"}, "baseline_period": 1}
    generator = random.Random(42)
    stationary = [100 + generator.uniform(-10, 10) for _ in range(112)]
    stress = {
        "noisy_endpoint_spikes": [v + (200 if i in (55, 69, 83) else 0) for i, v in enumerate(stationary)],
        "noisy_recent_step": [v + (100 if i >= 54 else 0) for i, v in enumerate(stationary)],
        "random_walk": [],
    }
    generator = random.Random(314)
    value = 100.
    for _ in range(112):
        value += generator.uniform(-5, 5)
        stress["random_walk"].append(value)
    for name, values in stress.items():
        yield {"name": name, "values": values, "origins": [56, 70, 84], "horizon": 7,
               "config": {"trend": "none"}, "baseline_period": 1}
