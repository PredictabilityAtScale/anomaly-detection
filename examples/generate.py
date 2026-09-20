"""Generate deterministic, synthetic demonstrations; no production effectiveness claim."""
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

base = Path(__file__).parent
ordinary = [100 + [0, 10, -5, 8, 2, -12, -8][i % 7] + [0.2, -0.4, 0.6, -0.3, 0.1][i % 5] for i in range(90)]
for name in ("ordinary", "spike", "drop", "shift", "growth_up", "growth_down",
             "compound", "compound_down", "location_shift_up", "location_shift_down",
             "steps", "steps_reset"):
    count = 150 if name.startswith("steps") else 90
    times = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).isoformat() for i in range(count)]
    values = ordinary.copy()
    if name == "spike":
        values[65] += 40
    if name == "drop":
        values[65] -= 40
    if name == "shift":
        values[60:] = [v + 4 for v in values[60:]]
    if name == "growth_up":
        values = [round(v + 0.6 * i, 4) for i, v in enumerate(values)]
    if name == "growth_down":
        values = [round(v - 0.6 * i, 4) for i, v in enumerate(values)]
    if name == "compound":
        # Compound the underlying level; keep the weekly variation additive.
        values = [round(100 * 1.012 ** i + v - 100, 4) for i, v in enumerate(values)]
    if name == "compound_down":
        values = [round(100 * 0.988 ** i + v - 100, 4) for i, v in enumerate(values)]
    if name.startswith("location_shift_"):
        # A 30-sample seasonal reference with a calibrated residual scale. The
        # final residuals are all 2.28 sigma in one direction: none crosses the
        # point threshold, while Nelson location-shift rules do signal.
        values = [round(100 + 8 * math.sin(2 * math.pi * i / 30), 4)
                  for i in range(30)]
        calibration = [-1, 1, -.5, .5, -1.2, 1.2, -.8, .8,
                       -.3, .3, -1.1, 1.1, -.6, .6]
        ordinary_tail = ([.4, -.4] * 8 if name.endswith("_up")
                         else [-.4, .4] * 8)
        residuals = calibration + ordinary_tail
        values += [round(values[i] + residuals[i], 4) for i in range(30)]
        shift = 2 if name.endswith("_up") else -2
        values += [round(values[i] + shift, 4) for i in range(30, 60)]
    if name.startswith("steps"):
        weekly = [0, 10, -5, 8, 2, -12, -8]
        values = []
        for i in range(count):
            level = (100 + 0.3*i if i < 50 else
                     150 - 0.4*(i-50) if i < 100 else
                     105 * 1.01**(i-100))
            values.append(round(level + weekly[i % 7] + [0.2, -0.4, 0.6, -0.3, 0.1][i % 5], 4))
    config = {"season_length": 7, "max_runtime_seconds": 120}
    if name.startswith("compound"):
        # Five complete seasonal cycles make the synthetic exponential rate
        # identifiable despite the small deterministic variation.
        config["training_size"] = 35
    if name.startswith("location_shift_"):
        config.update(season_length=30, training_size=30,
                      calibration_size=14, trend="none")
    if name == "steps_reset":
        config["reset_points"] = [50, "2026-04-11"]
    request = {"schema_version": "1.0", "task": "analyze", "datasets": [{"id": "series", "timestamps": times, "values": values, "frequency": "1d", "units": "calls"}], "config": config}
    (base / f"{name}.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    with (base / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "calls"])
        writer.writerows(zip(times, values))
