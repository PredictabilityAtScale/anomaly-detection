"""Run checked-in population examples through the real public API."""
import json
from pathlib import Path

from anomalyzer import analyze


def main():
    directory = Path(__file__).resolve().parent / "distributions"
    for name, expected in (("numeric-shape", True), ("numeric-ordinary", False),
                           ("categorical-mix", True), ("weighted-composition", False), ("weighted-reports", True)):
        result = analyze(json.loads((directory / f"{name}.json").read_text()))
        assert result.change_detected is expected, result
        print(f"PASS {name}: {result.status}; effect={result.statistic:.6g}; p={result.p_value}")
    result = analyze(json.loads((directory / "numeric-monitor.json").read_text()))
    assert result.first_detection is not None
    assert result.first_detection["index"] >= 160
    print(f"PASS numeric-monitor: {result.status}; first detection={result.first_detection}")
    result = analyze(json.loads((directory / "seasonal-morning.json").read_text()))
    assert result.status == "completed" and not result.change_detected
    assert result.selection["reference_windows"] == 3
    assert result.comparison.p_value == 1
    print(f"PASS seasonal-morning: {result.status}; windows={result.selection['reference_windows']}; p={result.comparison.p_value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
