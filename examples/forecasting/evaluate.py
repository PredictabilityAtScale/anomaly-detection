"""Chronological fixed-origin evaluation; private data output is confined to .tmp.

Run: python examples/forecasting/evaluate.py --output docs/forecast-evaluation.json
Optional --private-evidence <forecast-cases.json> --output .tmp/forecast-private.json
Never selects settings using held-out values; no data is imputed or combined.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from anomalyzer import forecast_series
from fixtures import synthetic_cases

ROOT = Path(__file__).resolve().parents[2]


def evaluate_case(case):
    results = []
    for policy, handling in ((p, h) for p in ("legacy", "recent-level-v1") for h in ("include", "robust")):
        folds, errors, baseline_errors, actual_absolute = [], [], [], []
        for origin in case["origins"]:
            horizon = case["horizon"]
            # End is exclusive. Every fitted value precedes every held-out one.
            history = case["values"][:origin]
            actual = case["values"][origin:origin + horizon]
            assert len(actual) == horizon
            result = forecast_series(history, {**case["config"], "outlier_handling": handling,
                                               "horizon": horizon, "baseline": policy, "max_runtime_seconds": 30})
            if result.status != "completed":
                folds.append({"origin": origin, "status": result.status, "reason": result.reason})
                continue
            period = case["baseline_period"]
            baseline = [history[len(history) - period + i % period] for i in range(horizon)]
            fold_errors = [abs(a - b) for a, b in zip(actual, result.predicted)]
            errors.extend(fold_errors)
            baseline_errors.extend(abs(a - b) for a, b in zip(actual, baseline))
            actual_absolute.extend(abs(a) for a in actual)
            folds.append({"origin": origin, "status": result.status,
                          "training_window": [0, origin - 1], "holdout_window": [origin, origin + horizon - 1],
                          "mae": math.fsum(fold_errors) / horizon,
                          "trend": result.model.trend_kind, "season_length": result.model.season_length,
                          "level_selection": ({k: result.model.level_baseline[k] for k in ("kind", "alpha", "status", "selection_window")} if getattr(result.model, "level_baseline", None) else None),
                          "one_step_absolute_error": fold_errors[0]})
        results.append({"case": case["name"], "outlier_handling": handling, "baseline_policy": policy,
            "evaluated_points": len(errors), "folds": folds,
            "mae": math.fsum(errors) / len(errors) if errors else None,
            "one_step_mae": math.fsum(f["one_step_absolute_error"] for f in folds if f["status"] == "completed") / sum(f["status"] == "completed" for f in folds) if errors else None,
            "baseline_mae": math.fsum(baseline_errors) / len(errors) if errors else None,
            "wape": math.fsum(errors) / math.fsum(actual_absolute) if math.fsum(actual_absolute) else None})
    return results


def private_evidence(path):
    raw = path.read_bytes()
    evidence = json.loads(raw)
    points = evidence["originalSnapshot"]["visibleActual"]
    assert len(points) == 30 and all(point["is_partial"] is False for point in points)
    values = [point["value"] for point in points]
    cases = [{"name": "private_visible_chart_only", "values": values,
              "origins": [16, 20, 24], "horizon": 6, "baseline_period": 1, "config": {"lower_bound": 0}}]
    sensitivity = []
    for replay in evidence["anomalyzerReplays"]:
        event = replay["request"]
        handling = "robust" if event["excludeExtremeOutliers"] else "include"
        result = forecast_series(values, {"horizon": event["horizon"], "lower_bound": 0,
                                          "outlier_handling": handling})
        sensitivity.append({"handling": handling, "legacy_total": replay["forecastTotal"],
            "public_total": math.fsum(result.predicted) if result.predicted else None,
            "status": result.status, "reason": result.reason,
            "model": result.model.model_dump(mode="json") if result.model else None})
    return cases, {"evidence_sha256": hashlib.sha256(raw).hexdigest(), "sensitivity": sensitivity,
        "coverage": "Only 30 displayed chart buckets; hidden 86-bucket fit unavailable. Raw call totals not merged or backtested: completeness/timezone/filter scope unknown, six overlapping daily totals conflict. No future actual outcomes for supplied 30-day scenarios."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--private-evidence", type=Path)
    args = parser.parse_args()
    metadata = {}
    if args.private_evidence:
        if not args.output.resolve().is_relative_to((ROOT / ".tmp").resolve()):
            parser.error("private evidence output must remain inside this repository's ignored .tmp directory")
        cases, metadata = private_evidence(args.private_evidence)
    else:
        cases = list(synthetic_cases())
        metadata["fixture_hash_encoding"] = "UTF-8 with LF line endings"
        metadata["fixture_sha256"] = hashlib.sha256(Path(__file__).with_name("fixtures.py").read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    report = {"method": "Nested chronological origins: each forecast selects only within its observed prefix; outer hold-outs never select parameters. Fixed candidate grid and thresholds; overlapping folds are not independent samples.",
              "source": "private local evidence" if args.private_evidence else "anonymous deterministic synthetic fixtures",
              "limitations": "MAE/WAPE are held-out errors, not fit diagnostics or calibrated uncertainty. WAPE is null for all-zero actuals. Synthetic performance does not establish customer accuracy or justify changing the default. Results include all declared seeds, endpoint spikes, real steps and a random walk; no statistical significance or universal improvement is claimed.",
              **metadata, "results": [row for case in cases for row in evaluate_case(case)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(report['results'])} policy/case evaluations to {args.output}")


if __name__ == "__main__":
    main()
