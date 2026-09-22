import json
import subprocess
import sys
import pytest
from anomalyzer.cli import main, build_request, parser
from anomalyzer.io import csv_dataset, load_json


def run(*args, stdin=None):
    return subprocess.run([sys.executable, "-m", "anomalyzer", *args], input=stdin, text=True, capture_output=True, timeout=120)


def test_stdin_file_equivalence(tmp_path, request_factory):
    text = json.dumps(request_factory([100] * 5))
    source = tmp_path / "case.json"
    source.write_text(text)
    file = run("analyze", str(source), "--format", "json")
    stdin = run("analyze", "-", "--input-format", "json", "--format", "json", stdin=text)
    assert file.returncode == stdin.returncode == 0
    a, b = json.loads(file.stdout), json.loads(stdin.stdout)
    assert a["input_fingerprint"] == b["input_fingerprint"]
    assert a["status"] == "insufficient_history"
    assert len(a["methods"][0]["evidence"]) == 4
    assert all(e["signal_maturity"] == "reference_only" for e in a["methods"][0]["evidence"])


def test_methods_and_invalid_options():
    result = run("methods", "--format", "json")
    assert result.returncode == 0
    assert {method["id"] for method in json.loads(result.stdout)["methods"]} == {
        "seasonal_trend", "multi_resolution"}
    assert [d["id"] for d in json.loads(result.stdout)["detectors"]] == [
        "point", "consecutive_run", "nelson_rule_2", "nelson_rule_3",
        "nelson_rule_4", "nelson_rule_5", "nelson_rule_6", "nelson_rule_8",
        "cusum", "moving_range"]
    assert not result.stderr
    assert run("methods", "--bad").returncode == 2
    assert run("analyze", "-", "--input-format", "json", stdin="{}").returncode == 2


def test_output_protection(tmp_path, capsys):
    output = tmp_path / "out.json"
    output.write_text("preserve")
    assert main(["methods", "--output", str(output)]) == 2
    assert output.read_text() == "preserve"
    assert main(["methods", "--format", "json", "--output", str(output), "--overwrite"]) == 0
    assert json.loads(output.read_text())["schema_version"] == "1.0"
    assert not capsys.readouterr().out


def test_csv_and_precedence(tmp_path, request_factory):
    source = tmp_path / "case.json"
    source.write_text(json.dumps(request_factory(season_length=2)))
    config = tmp_path / "settings.json"
    config.write_text('{"season_length": 3}')
    request = build_request(parser().parse_args(["analyze", str(source), "--config", str(config), "--season-length", "7"]))
    assert request.config.season_length == 7
    ds = csv_dataset("timestamp,calls\n2026-01-01T00:00:00Z,0\n2026-01-02T00:00:00Z,\n", "timestamp", "calls", "1d")
    assert ds.values == [0, None]
    positional = csv_dataset("calls\n10\n20\n", None, "calls", None)
    assert positional.timestamps is None
    assert positional.values == [10, 20]
    with pytest.raises(ValueError, match="together"):
        csv_dataset("timestamp,calls\n2026-01-01,1\n", "timestamp", "calls", None)
    with pytest.raises(ValueError, match="varying"):
        csv_dataset("t,v,customer\n2026-01-01,1,a\n2026-01-02,2,b\n", "t", "v", "1d")
    with pytest.raises(ValueError, match="duplicate"):
        load_json('{"config": {}, "config": {}}')


def test_bare_json_values_cli():
    values = [10, 20, 5, 15, 8, 30, 12] * 12
    result = run("analyze", "-", "--input-format", "json", "--format", "json",
                 stdin=json.dumps(values))
    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert body["data_quality"]["coordinate"] == "position"
    assert body["methods"][0]["parameters"]["season_length"] == 7
    assert body["methods"][0]["parameters"]["season_length_source"] == "inferred"


def test_manual_reset_cli():
    result = run("analyze", "examples/steps.csv", "--time", "timestamp",
                 "--value", "calls", "--frequency", "1d", "--season-length", "7",
                 "--reset-point", "50", "--reset-point", "2026-04-11",
                 "--format", "json")
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["methods"][0]["parameters"]["resolved_reset_positions"] == [50, 100]
    assert not body["observations"]
    assert not [pattern for pattern in body["anomaly_patterns"]
                if pattern["kind"] == "consecutive_run"]


def test_outlier_handling_cli():
    robust = run("analyze", "examples/spike.json", "--format", "json")
    included = run("analyze", "examples/spike.json", "--outlier-handling",
                   "include", "--format", "json")
    assert robust.returncode == included.returncode == 0
    robust_body, included_body = json.loads(robust.stdout), json.loads(included.stdout)
    assert robust_body["resolved_config"]["config"]["outlier_handling"] == "robust"
    assert {e["index"] for e in robust_body["methods"][0]["evidence"]
            if e["triggers"]} == {65}
    assert {e["index"] for e in included_body["methods"][0]["evidence"]
            if e["triggers"]} == {65, 72}


def test_size_limit_and_execution_exit(tmp_path, request_factory, capsys, monkeypatch):
    source = tmp_path / "case.json"
    source.write_text(json.dumps(request_factory()))
    assert main(["analyze", str(source), "--max-bytes", "1"]) == 2
    assert main(["analyze", str(source), "--max-runtime-seconds", "0.000000000001", "--format", "json"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "failed"
