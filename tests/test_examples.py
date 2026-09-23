import subprocess
import sys
from pathlib import Path


def test_demo_checks_all_cases():
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / "examples" / "run_demo.py")],
                            cwd=root, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    for case in ("ordinary", "spike", "drop", "shift", "growth_up", "growth_down",
                 "compound", "compound_down", "location_shift_up",
                 "location_shift_down", "steps", "steps_reset"):
        assert f"PASS {case}:" in result.stdout


def test_agentic_demo_checks_all_cases():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "examples" / "run_agentic_demo.py")],
        cwd=root, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    for case in ("conversion.json", "lagged-response.json", "unit-cost.json",
                 "incomplete-usage.json"):
        assert f"PASS {case}:" in result.stdout
