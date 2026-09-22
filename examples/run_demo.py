"""Run the checked-in synthetic cases and verify their expected behavior.

Run from the project root: .venv/Scripts/python examples/run_demo.py
No new dependencies; exit 1 if any example behaves unexpectedly.
"""
import json
from pathlib import Path

from anomalyzer import analyze


def main():
    directory = Path(__file__).parent
    # Zero-based indices; trend cases include their trend during calibration.
    cases = {
        "ordinary": (set(), "Weekly seasonality and small deterministic variation"),
        "spike": ({65}, "+40 calls at index 65; robust history prevents the echo at 72"),
        "drop": ({65}, "-40 calls at index 65; robust history prevents the echo at 72"),
        "shift": (set(range(60, 90)), "+4 calls from index 60 onward; remains abnormal until a reviewed reset"),
        "growth_up": (set(), "+0.6 calls/day throughout; calibration captures the weekly increase"),
        "growth_down": (set(), "-0.6 calls/day throughout; calibration captures the weekly decrease"),
        "compound": (set(), "Underlying level grows 1.2% daily; compound trend is accounted for"),
        "compound_down": (set(), "Underlying level declines 1.2% daily; compound trend is accounted for"),
        "location_shift_up": (set(), "+2 residual location shift; Nelson patterns signal without point anomalies"),
        "location_shift_down": (set(), "-2 residual location shift; Nelson patterns signal without point anomalies"),
        "steps": (set(range(50, 98)) | set(range(100, 127)) | {130} | set(range(132, 150)),
                  "Two unmarked regime changes remain abnormal rather than silently retraining"),
        "steps_reset": (set(), "The same changes are manually declared at position 50 and date 2026-04-11"),
    }
    expected_patterns = {
        "ordinary": set(),
        "spike": {
            ("cusum", "increase", 65),
            ("moving_range", "mixed", 65),
        },
        "drop": {
            ("cusum", "decrease", 65),
            ("moving_range", "mixed", 65),
        },
        "shift": {
            ("adjacent_point_anomalies", "increase", 61),
            ("nelson_rule_2", "increase", 68),
            ("nelson_rule_5", "increase", 61),
            ("nelson_rule_6", "increase", 63),
            ("nelson_rule_8", "mixed", 66),
            ("cusum", "increase", 60),
            ("moving_range", "mixed", 60),
            ("moving_range", "mixed", 72),
            ("moving_range", "mixed", 78),
        },
        "growth_up": set(),
        "growth_down": set(),
        "compound": set(),
        "compound_down": set(),
        "location_shift_up": {
            ("cusum", "increase", 62),
            ("nelson_rule_2", "increase", 68),
            ("nelson_rule_4", "mixed", 57),
            ("nelson_rule_5", "increase", 61),
            ("nelson_rule_6", "increase", 63),
        },
        "location_shift_down": {
            ("cusum", "decrease", 62),
            ("nelson_rule_2", "decrease", 68),
            ("nelson_rule_4", "mixed", 57),
            ("nelson_rule_5", "decrease", 61),
            ("nelson_rule_6", "decrease", 63),
        },
        "steps": {
            ("adjacent_point_anomalies", "increase", 51),
            ("adjacent_point_anomalies", "decrease", 101),
            ("nelson_rule_2", "increase", 58),
            ("nelson_rule_2", "decrease", 108),
            ("nelson_rule_5", "increase", 51),
            ("nelson_rule_5", "decrease", 101),
            ("nelson_rule_6", "increase", 53),
            ("nelson_rule_6", "decrease", 103),
            ("nelson_rule_8", "mixed", 56),
            ("nelson_rule_8", "mixed", 100),
            ("cusum", "increase", 50),
            ("cusum", "decrease", 100),
            ("moving_range", "mixed", 50),
            ("moving_range", "mixed", 100),
        },
        "steps_reset": set(),
    }
    passed = True
    for name, (expected, description) in cases.items():
        request = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        result = analyze(request)
        evidence = result.methods[0].evidence
        flagged = [e for e in evidence if e["triggers"]]
        actual = {e["index"] for e in flagged}
        actual_patterns = {
            (pattern["rule"], pattern["direction"], pattern["detection_index"])
            for pattern in result.anomaly_patterns
        }
        expected_case_patterns = expected_patterns[name]
        patterns_ok = ((actual_patterns == expected_case_patterns
                        if not expected_case_patterns
                        else expected_case_patterns.issubset(actual_patterns))
                       and len(actual_patterns) == len(result.anomaly_patterns))
        ok = result.status == "completed" and actual == expected and patterns_ok
        passed = passed and ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: {description}")
        print(f"  {len(flagged)} flagged samples, {len(result.observations)} episodes, "
              f"{len(result.anomaly_patterns)} anomaly patterns")
        for pattern in result.anomaly_patterns:
            if pattern["kind"] == "location_shift":
                print(f"  {pattern['rule']} at index {pattern['detection_index']}: "
                      f"{pattern['description']}")
        for sample in flagged[:10]:
            print(f"  {sample['timestamp'][:10]}  observed={sample['observed']:6.1f}"
                  f"  expected={sample['expected']:6.1f}"
                  f"  residual={sample['residual']:+6.1f}"
                  f"  score={sample['standardized_residual']:+7.2f}")
        if len(flagged) > 10:
            print(f"  ... {len(flagged)-10} more flagged samples")
        if not ok:
            print(f"  Expected indices: {sorted(expected)}; actual: {sorted(actual)}; status: {result.status}")
            print(f"  Expected patterns: {sorted(expected_case_patterns)}; "
                  f"actual: {sorted(actual_patterns)}")
    print("\nRobust mode keeps actual incidents visible while preventing their seasonal echoes.")
    print("These synthetic checks demonstrate behavior, not real-world detection accuracy.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
