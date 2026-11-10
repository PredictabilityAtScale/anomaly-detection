"""Nested chronological evaluation; synthetic source, no customer observations.

Run: python examples/forecasting/select_models.py
Selection sees only each outer training prefix, never its following targets.
"""
import json
import math
import random

from anomalyzer import forecast_with_model, select_forecast


def evaluate():
    rng = random.Random(1729)
    noise = [rng.uniform(-4, 4) for _ in range(154)]
    cases = {
        "weekly_growth": [30 + .2*i + 5*math.sin(2*math.pi*i/7) + noise[i] for i in range(154)],
        "unseen_shift": [30 + noise[i] + (35 if i >= 115 else 0) for i in range(154)],
        "stationary": [30 + noise[i] for i in range(154)],
        "changing_direction": [30 + .2*i - .5*max(0, i-100) + noise[i] for i in range(154)],
    }
    report = []
    for name, values in cases.items():
        folds = []
        for origin in (98, 112, 126):
            selected = select_forecast(values[:origin], {"horizon": 14})
            if selected.status != "completed":
                raise RuntimeError(f"{name}: {selected.reason}")
            naive = forecast_with_model(values[:origin], {"id": "naive", "method": "naive"})
            actual = values[origin:origin+14]
            folds.append({
                "outer_training_window": [0, origin-1], "outer_holdout_window": [origin, origin+13],
                "selected_candidate": selected.selected_candidate.model_dump(mode="json"),
                "selection_mae": next(s.mae for s in selected.scores if s.candidate == selected.selected_candidate),
                "outer_mae": sum(abs(p-a) for p,a in zip(selected.forecast.predicted, actual))/14,
                "naive_outer_mae": sum(abs(p-a) for p,a in zip(naive.predicted, actual))/14,
            })
        report.append({"case": name, "folds": folds})
    return {"source": "deterministic synthetic observations", "horizon": 14, "results": report,
            "limitations": "Selection and outer losses differ. Retain losses and regressions; these fixtures do not establish production accuracy."}


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
