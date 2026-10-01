"""Exercise the Skill's portable chart fallback with real analysis evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from anomalyzer import analyze


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/anomaly-detection/scripts/quick_chart.py"
SPEC = importlib.util.spec_from_file_location("skill_quick_chart", SCRIPT)
chart = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chart)
NS = {"svg": "http://www.w3.org/2000/svg"}


def result(name):
    request = json.loads((ROOT / "examples" / name).read_text())
    return analyze(request).model_dump(mode="json")


def test_quick_chart_preserves_real_point_evidence():
    data = result("spike.json")
    svg = ET.fromstring(chart.render(data, "Observed & expected"))
    evidence = data["methods"][0]["evidence"]
    flags = [sample for sample in evidence if sample["triggers"]]
    markers = svg.findall("svg:circle[svg:title]", NS)
    assert len(markers) == len(flags) == 1
    assert flags[0]["timestamp"] in markers[0].find("svg:title", NS).text
    assert "point" in markers[0].find("svg:title", NS).text
    text = [node.text for node in svg.findall("svg:text", NS)]
    assert {"Observed", "Expected", "Training", "Calibration", "calls"} <= set(text)
    assert svg.find("svg:title", NS).text == "Observed & expected"
    assert len(svg.findall("svg:polyline", NS)) >= 2


def test_provisional_scores_are_not_charted_as_triggers(request_factory):
    request = request_factory([0, 1, 3, 6, 10, 15], training_size=2,
                              calibration_size=5, point_threshold=1,
                              robust_reference_seasons=1)
    data = analyze(request).model_dump(mode="json")
    assert data["methods"][0]["evidence"][-1]["signal_maturity"] == "provisional"
    svg = ET.fromstring(chart.render(data, "Early evidence"))
    assert not svg.findall("svg:circle[svg:title]", NS)
    assert "insufficient_history" in " ".join(svg.itertext())


def test_quick_chart_marks_reviewed_resets():
    data = result("steps_reset.json")
    svg = ET.fromstring(chart.render(data, "Reviewed regimes"))
    boundaries = svg.findall("svg:line[@stroke='#6b7280']", NS)
    assert len(boundaries) == 2
    text = [node.text for node in svg.findall("svg:text", NS)]
    assert text.count("Training") == text.count("Calibration") == 3


def test_quick_chart_rejects_multiple_datasets():
    with pytest.raises(ValueError, match="exactly one resolved dataset"):
        chart.render(result("agentic/conversion.json"), "Different units")


def test_chart_cli_requires_explicit_overwrite(tmp_path):
    source = tmp_path / "result.json"
    source.write_text(json.dumps(result("spike.json")))
    output = tmp_path / "chart.svg"
    output.write_text("existing chart")
    command = [sys.executable, str(SCRIPT), str(source), "--output", str(output)]
    protected = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert protected.returncode == 2
    assert output.read_text() == "existing chart"
    assert "--overwrite" in protected.stderr
    replaced = subprocess.run(command + ["--overwrite"], capture_output=True,
                              text=True, timeout=30)
    assert replaced.returncode == 0
    assert not replaced.stderr
    assert str(output.resolve()) in replaced.stdout
    ET.fromstring(output.read_text())
