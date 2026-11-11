"""Protect portable labels, chronology, and the evidence supplied for comparison."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "examples" / "comparison" / "pack"
spec = importlib.util.spec_from_file_location("comparison_generate", PACK.parent / "generate.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def data(case):
    return read_csv(PACK / "data" / f"{case}.csv")


def baseline(case):
    return read_csv(PACK / "baseline" / f"{case}.csv")


def test_pack_covers_every_readme_chapter_and_archive_is_complete():
    manifest = read_csv(PACK / "manifest.csv")
    assert {int(row["readme_chapter"]) for row in manifest} == set(range(1, 28))
    assert len({row["case_id"] for row in manifest}) == 53
    checksums = json.loads((PACK / "checksums.json").read_text())
    with zipfile.ZipFile(PACK / "comparison-cases.zip") as archive:
        assert set(archive.namelist()) == set(checksums["sha256"]) | {"checksums.json"}
        for name, expected_hash in checksums["sha256"].items():
            content = (PACK / name).read_bytes()
            assert hashlib.sha256(content).hexdigest() == expected_hash, name
            assert archive.read(name) == content, name
    for case in manifest:
        rows = data(case["case_id"])
        assert len(rows) == int(case["rows"])
        assert len({(r["series_id"], r["index"]) for r in rows}) == len(rows)
        assert all(r["is_anomaly"] in ("true", "false") for r in rows)
        assert sum(r["is_anomaly"] == "true" for r in rows) == int(case["anomaly_rows"])
        assert (PACK / case["request_file"]).is_file()
        if case["baseline_file"]:
            assert (PACK / case["baseline_file"]).is_file()


def test_truth_is_independent_of_flags_and_accepted_regimes():
    include, robust = data("08_spike_include"), data("08_spike_robust")
    assert [{k: v for k, v in r.items() if k != "anomaly_id"} for r in include] == [
        {k: v for k, v in r.items() if k != "anomaly_id"} for r in robust]
    assert [int(r["index"]) for r in include if r["is_anomaly"] == "true"] == [65]
    assert any(r["index"] == "72" and r["point_flag"] == "true" for r in baseline("08_spike_include"))
    assert not any(r["index"] == "72" and r["point_flag"] == "true" for r in baseline("08_spike_robust"))
    assert all(r["is_anomaly"] == "false" for r in data("05_reviewed_regimes"))
    assert sum(r["is_anomaly"] == "true" for r in data("05_unreviewed_regimes")) == 100
    assert [int(r["index"]) for r in data("05_reviewed_regimes") if r["reset_before"] == "true"] == [50, 100]
    assert data("01_linear_trend")[65]["anomaly_id"] != data("01_linear_trend")[78]["anomaly_id"]


def test_shift_first_detection_is_not_backdated_to_interval_start():
    rows = data("07_location_shift_up")
    assert rows[60]["is_anomaly"] == "true" and rows[59]["is_anomaly"] == "false"
    evidence = baseline("07_location_shift_up")
    assert not any(r["point_flag"] == "true" for r in evidence)
    location_rules = {"nelson_rule_2", "nelson_rule_5", "nelson_rule_6", "cusum"}
    assert min(int(r["index"]) for r in evidence
               if location_rules.intersection(r["pattern_first_detection"].split(";"))) == 61
    assert not any("nelson_rule_2" in r["pattern_first_detection"] for r in baseline("19_pattern_gap"))
    gap = data("19_pattern_gap")
    assert gap[11]["score_anomaly"] == "false"
    assert gap[10]["anomaly_id"] != gap[12]["anomaly_id"]


def test_missing_zero_incomplete_and_revised_measurements_survive_export():
    preserved, zeroed = data("14_preserve"), data("14_zero_empty")
    for i in (4, 6, 9, 12):
        assert preserved[i]["value"] == "" and preserved[i]["score_anomaly"] == "false"
        assert float(zeroed[i]["value"]) == 0 and zeroed[i]["reported_value"] == ""
        assert zeroed[i]["value_origin"] == "policy_zero"
    partial = data("15_statuses")[-1]
    assert float(partial["value"]) == 3 and partial["score_anomaly"] == "false"
    assert len(data("17_cost_calendar")) == 431 and len(data("17_cost_events")) == 12
    before, after = data("24_identified_before_correction"), data("24_identified_corrected")
    assert before[7]["event_id"] == after[7]["event_id"] == "call-07"
    assert before[7]["timestamp"] == after[7]["timestamp"] == after[8]["timestamp"]
    assert float(before[7]["value"]) == .80 and float(after[7]["value"]) == .85
    assert after[7]["revision_id"] == "corrected-cost-1"
    assert not any(r["score_anomaly"] == "true" for r in data("24_identified_retry"))


def test_relationship_truth_and_unavailable_ratios():
    conversion = data("12_conversion")
    flagged = [r for r in conversion if r["is_anomaly"] == "true"]
    assert [(r["series_id"], r["index"]) for r in flagged] == [("conversion", "14")]
    assert float(flagged[0]["value"]) == pytest.approx(8/130)
    ratios = [r for r in data("21_relationships") if r["series_id"] == "unit-cost"]
    assert [int(r["index"]) for r in ratios if r["value"] == ""] == [1, 2, 4, 9]
    rule = baseline("20_first_rule")
    assert len(rule) == 1 and rule[0]["classifications"] == "criterion_violation"
    assert rule[0]["point_flag"] == "false" and rule[0]["target_status"] == "insufficient_history"


def test_forecasts_cannot_see_test_values_and_losses_match_actuals():
    case = next(c for c in generator.scenarios() if c["id"] == "01_linear_trend")
    before = generator.forecast_rows(case)
    case["request"]["datasets"][0]["values"][60:] = [999999.0]*30
    after = generator.forecast_rows(case)
    assert [r["anomalyzer_predicted"] for r in before] == [r["anomalyzer_predicted"] for r in after]
    for case in read_csv(PACK / "manifest.csv"):
        if not case["forecast_file"]:
            continue
        truth = data(case["case_id"])
        forecast = read_csv(PACK / case["forecast_file"])
        assert all(r["split"] == ("train" if int(r["index"]) < 60 else "test") for r in truth)
        assert [int(r["index"]) for r in forecast] == list(range(60, len(truth)))
        mae = sum(abs(float(r["actual"])-float(r["anomalyzer_predicted"])) for r in forecast)/len(forecast)
        assert mae == pytest.approx(float(case["forecast_mae"]))


def test_population_labels_do_not_claim_individual_point_anomalies():
    shape = data("25_numeric_shape")
    reference = [float(r["value"]) for r in shape if r["population"] == "reference"]
    current = [float(r["value"]) for r in shape if r["population"] == "current"]
    assert sum(reference)/len(reference) == sum(current)/len(current) == .5
    assert all(r["score_anomaly"] == "false" for r in shape)
    assert all(r["anomaly_scope"] == "population" for r in shape if r["is_anomaly"] == "true")
    assert not any(r["is_anomaly"] == "true" for r in data("25_numeric_ordinary"))
    monitor = json.loads((PACK / "baseline" / "25_numeric_monitor.json").read_text())
    assert next(int(r["index"]) for r in data("25_numeric_monitor") if r["is_anomaly"] == "true") == 160
    assert monitor["first_detection"]["index"] == 182
    seasonal = json.loads((PACK / "baseline" / "27_seasonal_morning.json").read_text())
    assert seasonal["change_detected"] is False
    assert any(r["population"] == "future_excluded" for r in data("27_seasonal_morning"))


def test_generation_reproduces_every_delivered_file(tmp_path):
    generator.generate(tmp_path)
    for path in PACK.rglob("*"):
        if path.is_file():
            relative = path.relative_to(PACK)
            assert (tmp_path / relative).read_bytes() == path.read_bytes(), relative
