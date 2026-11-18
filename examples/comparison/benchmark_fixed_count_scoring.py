"""Swap only the point scorer on the existing five-minute integer fixtures."""

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha1
import json
import math
from pathlib import Path
from statistics import NormalDist, mean, median, variance
import sys

from anomalyzer import __version__
from anomalyzer.baseline import robust_expected_value
from anomalyzer.contracts import Settings
from anomalyzer.trend import Trend
from benchmark_five_minute_counts import (
    BUCKETS_PER_DAY, HOLDOUT, ORIGIN, START, SUITES, TRAIN, analyze_fixture, write_csv,
)
from benchmark_posthog import POSTHOG_BANDS, POSTHOG_BANDS_BLOB, POSTHOG_REVISION


ALPHA = NormalDist().cdf(-Settings().point_threshold)
METHODS = ("residual", "count_band")


def fitted_dispersion(fixture, method):
    """Fit NB2 overdispersion to the same retained, centered calibration misses."""
    segment, = method.diagnostics["segments"]
    center = segment["calibration_center"]
    history = {e["index"]: e for e in method.evidence if e["index"] < ORIGIN}
    if "calibration_indexes" in segment:
        excluded = set(segment.get("excluded_calibration_indexes", ()))
        calibration = [history[i] for i in segment["calibration_indexes"] if i not in excluded]
        expected = [e["expected"] for e in calibration]
    else:
        excluded = set(segment["calibration_excluded_positions"])
        # The dense recipe can rebuild calibration after screening. Its saved
        # model values give the exact prior references used in that rebuild.
        refs = [history[i]["model_value"] if i in history else value
                for i, value in enumerate(fixture.values[:ORIGIN])]
        calibration = [history[i] for i in range(TRAIN, ORIGIN) if i not in excluded]
        expected = [robust_expected_value(refs, e["index"], BUCKETS_PER_DAY, 0, Trend(),
                                          Settings().robust_reference_seasons) for e in calibration]
    residuals = [e["observed"] - mu for e, mu in zip(calibration, expected, strict=True)]
    if not math.isclose(mean(residuals), center, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"Calibration reconstruction disagrees with Anomalyzer in {fixture.name}")
    if not math.isclose(max(math.sqrt(variance(residuals)), Settings().scale_floor),
                        segment["calibration_scale"], rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError(f"Calibration scale disagrees with Anomalyzer in {fixture.name}")
    rates = [max(1.0, mu + center) for mu in expected]
    dispersion = max(0.0, (variance(residuals) - mean(rates)) / mean(mu**2 for mu in rates))
    return center, dispersion, len(rates)


def replay_fixture(fixture, timestamps, band_model, moments, suite):
    result = analyze_fixture(fixture, timestamps)
    method, = result.methods
    center, dispersion, calibration_count = fitted_dispersion(fixture, method)
    points = {e["index"]: e for e in method.evidence if e["signal_maturity"] == "calibrated" and e["index"] >= ORIGIN}
    # The native band implementation estimates its own mean and variance.
    # Supply fixed-reference moments so the only changed decision is the
    # point rule. Retain its one-count rate floor and Poisson/NB switch.
    inputs = []
    for point in points.values():
        expectation = point["expected"] + center
        rate = max(band_model.rate_floor, expectation)
        inputs.append(moments(mean=expectation, variance=rate + dispersion * rate**2, expected=expectation))
    bands = dict(zip(points, band_model.compute_many(inputs, ALPHA), strict=True))

    pattern_starts = defaultdict(set)
    for pattern in result.anomaly_patterns:
        index = pattern["detection_index"]
        # Adjacent point runs are derived from the point flags themselves.
        # Their first detection is already in the point set in either arm.
        if index in points and pattern["rule"] != "adjacent_point_anomalies":
            pattern_starts[index].add(pattern["rule"])
    flags = {
        "residual": {i for i, e in points.items() if "point" in e["triggers"]},
        "count_band": {i for i, band in bands.items() if not band.lower <= points[i]["observed"] <= band.upper},
    }
    truth = {i: incident for incident in fixture.incidents for i in range(incident.start, incident.stop)}
    tag = dict(suite=suite, case=fixture.name)
    buckets = [dict(**tag, index=i, timestamp=timestamps[i], observed=fixture.values[i],
                    incident=truth[i].kind if i in truth else None,
                    expected=points[i]["expected"] if i in points else None,
                    calibrated_center=points[i]["expected"] + center if i in points else None,
                    lower=bands[i].lower if i in bands else None, upper=bands[i].upper if i in bands else None,
                    residual_flag=i in flags["residual"] if i in points else None,
                    count_flag=i in flags["count_band"] if i in points else None,
                    common_patterns=";".join(sorted(pattern_starts.get(i, ()))),
                    scored=i in points) for i in range(ORIGIN, ORIGIN + HOLDOUT)]
    cases, incidents = [], []
    for scorer, point_flags in flags.items():
        for policy, alerts in (("point_only", point_flags), ("point_and_patterns", point_flags | pattern_starts.keys())):
            false = sorted(alerts - truth.keys())
            cases.append(dict(**tag, scorer=scorer, policy=policy, scored=len(points), unscored=HOLDOUT-len(points),
                scored_normal=len(points.keys() - truth.keys()), false_alert_buckets=len(false),
                false_alert_runs=sum(j == 0 or i != false[j-1] + 1 for j, i in enumerate(false)),
                calibration_count=calibration_count, fitted_dispersion=dispersion))
            for event in fixture.incidents:
                window = range(event.start, event.stop)
                first = next((i for i in window if i in alerts), None)
                status = "detected" if first is not None else "missed" if any(i in points for i in window) else "unassessed"
                incidents.append(dict(**tag, scorer=scorer, policy=policy, incident=event.kind,
                    onset=event.start, stop=event.stop, onset_time=timestamps[event.start],
                    boundary=event.boundary, status=status, first_detection=first,
                    delay_minutes=5 * (first - event.start) if first is not None else None))
    return cases, incidents, buckets


def aggregate(cases, incidents):
    delays = [row["delay_minutes"] for row in incidents if row["status"] == "detected"]
    status = Counter(row["status"] for row in incidents)
    return dict(**{k: sum(row[k] for row in cases)
                   for k in ("scored_normal", "unscored", "false_alert_buckets", "false_alert_runs")},
                **{k: status[k] for k in ("detected", "missed", "unassessed")},
                median_delay_minutes=median(delays) if delays else None, longest_delay_minutes=max(delays, default=None))


def run(output, band_model, moments):
    timestamps = [(START + timedelta(minutes=5*i)).isoformat() for i in range(ORIGIN + HOLDOUT)]
    cases, incidents, buckets = [], [], []
    for suite, source in SUITES.items():
        for fixture in source():
            case, incident, bucket = replay_fixture(fixture, timestamps, band_model, moments, suite)
            cases.extend(case)
            incidents.extend(incident)
            buckets.extend(bucket)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("cases", cases), ("incidents", incidents), ("buckets", buckets)):
        write_csv(output / f"{name}.csv", rows)
    summary = {"anomalyzer": __version__, "posthog": POSTHOG_REVISION, "nominal_per_tail_alpha": ALPHA, "results": {}}
    for suite in (*SUITES, "all"):
        summary["results"][suite] = {}
        for policy in ("point_only", "point_and_patterns"):
            summary["results"][suite][policy] = {}
            for method in METHODS:
                def selected(rows):
                    return [r for r in rows if r["policy"] == policy and r["scorer"] == method
                            and (suite == "all" or r["suite"] == suite)]
                summary["results"][suite][policy][method] = aggregate(selected(cases), selected(incidents))
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary["results"]["all"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posthog-source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = (args.posthog_source / POSTHOG_BANDS).read_bytes().replace(b"\r\n", b"\n")
    blob = sha1(f"blob {len(source)}\0".encode() + source).hexdigest()
    if blob != POSTHOG_BANDS_BLOB:
        parser.error(f"PostHog band source differs from the pinned revision {POSTHOG_REVISION}")
    sys.path.insert(0, str(args.posthog_source.resolve()))
    from products.apm.backend.logic.anomaly_detection.bands import NegativeBinomialBandModel, _CountMoments

    class FixedReferenceBand(NegativeBinomialBandModel):
        def _moments(self, fixed):
            return fixed

    print(json.dumps(run(args.output, FixedReferenceBand(), _CountMoments), indent=2))


if __name__ == "__main__":
    main()
