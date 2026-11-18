"""Replay the comparison pack against PostHog's portable count band.

Requires NumPy, SciPy and the PostHog Python source at POSTHOG_REVISION.
The scan's native five-minute input is not available in this pack. This
adapter evaluates its original negative-binomial band on declared pack
phases. It has no log-specific traffic, silence or issue lifecycle rules.
"""

import argparse
from collections import Counter, defaultdict, deque
import csv
from datetime import datetime, timedelta
from hashlib import sha1
import json
import math
from pathlib import Path
from statistics import median
import sys

from generate import analyze, baseline_rows, __version__


POSTHOG_REVISION = "52bb99139083f5734383b2059440ff047163744d"
POSTHOG_BANDS = "products/apm/backend/logic/anomaly_detection/bands.py"
POSTHOG_BANDS_BLOB = "55614e9e16f60de825efe2cbf014349928cb6020"
PACK = Path(__file__).with_name("pack")
COUNT_UNITS = {"calls", "visits", "orders", "leads", "requests", "events"}
BUCKETS_PER_DAY = {"1h": 24, "1d": 1}
MIN_REFERENCE = 4
REFERENCE_SIZE = 28
DAILY_TAIL_BUDGET = 0.05  # Per-sided nominal budget from PostHog's scan config.


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def coverage_usable(row):
    return row["coverage"] in {"complete", "revised", "empty"} and bool(row["value"])


def scope(series, cadence):
    if series[0]["observation_basis"] in {"population_event", "aggregate_category"}:
        return "population_comparison"
    if cadence not in BUCKETS_PER_DAY or series[0]["observation_basis"] != "calendar":
        return "unsupported_cadence_or_basis"
    if series[0]["units"] not in COUNT_UNITS:
        return "non_count_units"
    values = [float(row["value"]) for row in series if coverage_usable(row)]
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        return "no_nonnegative_counts"
    return "integer" if all(value.is_integer() for value in values) else "rounded"


def rounded_count(value):
    return math.floor(float(value) + 0.5) if value is not None else None


def count_scores(series, cadence, season, band_model, as_array):
    references = defaultdict(lambda: deque(maxlen=REFERENCE_SIZE))
    alpha = DAILY_TAIL_BUDGET / BUCKETS_PER_DAY[cadence]
    step = timedelta(days=1 / BUCKETS_PER_DAY[cadence])
    start = datetime.fromisoformat(series[0]["timestamp"])
    for row in series:
        offset, remainder = divmod(datetime.fromisoformat(row["timestamp"]) - start, step)
        if remainder:
            raise ValueError("Count replay requires the declared time grid")
        if row["reset_before"] == "true":
            references.clear()
        samples = references[offset % season]
        if not coverage_usable(row):
            yield None, "source_unavailable"
            continue
        observed = rounded_count(row["value"])
        if len(samples) < MIN_REFERENCE:
            yield None, "fewer_than_four_prior_phase_observations"
        else:
            band = band_model.compute(as_array(samples, dtype=float), observed, alpha)
            yield band, "scored"
        samples.append(observed)


def anomalyzer_scores(case, rounded_ids):
    if not case["baseline_file"].endswith(".csv"):
        return {}
    if rounded_ids:
        request = json.loads((PACK / case["request_file"]).read_text(encoding="utf-8"))
        for dataset in request["datasets"]:
            if dataset.get("id", "series") in rounded_ids:
                dataset["values"] = [rounded_count(value) for value in dataset["values"]]
                for revision in dataset.get("revisions", []):
                    revision["value"] = rounded_count(revision.get("value"))
        result = analyze(request).model_dump(mode="json")
        if result["status"] == "failed":
            raise RuntimeError(f"Anomalyzer failed on {case['case_id']}")
        rows = baseline_rows(result)
    else:
        rows = read_csv(PACK / case["baseline_file"])
    return {
        (row["series_id"], int(row["index"])): row
        for row in rows if row["resolution"] != "completed_period"
    }


def anomalyzer_flags(evidence, row):
    if not evidence:
        return None, None, "no_exported_assessment"
    timestamp = evidence["timestamp"]
    time_mismatch = timestamp and (not row["timestamp"] or
                                   datetime.fromisoformat(timestamp) != datetime.fromisoformat(row["timestamp"]))
    event_id = evidence["event_id"]
    if time_mismatch or (event_id and event_id != row["event_id"]):
        raise ValueError(f"Evidence does not match source row {row['series_id']}:{row['index']}")
    if evidence["signal_maturity"] != "calibrated" or evidence["method"] == "assessment_only":
        return None, None, evidence["signal_maturity"] or "no_calibrated_score"
    point = evidence["point_flag"] in (True, "true")
    return point, point or bool(evidence["pattern_first_detection"]), "scored"


def pack_predictions(band_model, as_array):
    for case in read_csv(PACK / "manifest.csv"):
        cadence = case["cadence"]
        if cadence == "5min":
            raise ValueError("This replay does not assess native five-minute scans")
        groups = defaultdict(list)
        for row in read_csv(PACK / case["data_file"]):
            groups[row["series_id"]].append(row)
        scopes = {series_id: scope(rows, cadence) for series_id, rows in groups.items()}
        rounded_ids = {series_id for series_id, tag in scopes.items() if tag == "rounded"}
        original = anomalyzer_scores(case, set())
        rounded = anomalyzer_scores(case, rounded_ids) if rounded_ids else {}
        for series_id, rows in groups.items():
            tag = scopes[series_id]
            if tag in {"integer", "rounded"}:
                season_text = case["season_length"]
                # The pack's sole inferred calendar series is the hourly view of
                # multi-resolution-v1, whose default season is 168 hourly samples.
                season = 168 if season_text == "inferred" and cadence == "1h" else int(season_text)
                bands = count_scores(rows, cadence, season, band_model, as_array)
            else:
                bands = [(None, tag)] * len(rows)
            for row, (band, posthog_status) in zip(rows, bands, strict=True):
                index = int(row["index"])
                key = series_id, index
                eligible = row["score_anomaly"] == "true"
                evidence = rounded if tag == "rounded" else original
                point, alert, status = anomalyzer_flags(evidence.get(key), row) if eligible else (None, None, "pack_excluded")
                original_point, original_alert, original_status = (
                    anomalyzer_flags(original.get(key), row) if eligible else (None, None, "pack_excluded")
                )
                observed = rounded_count(row["value"]) if tag in {"rounded", "integer"} and coverage_usable(row) else None
                yield dict(
                    case_id=case["case_id"], series_id=series_id, index=index, timestamp=row["timestamp"],
                    task=case["task"], cadence=cadence, cohort=tag, eligible=eligible,
                    incident_id=row["anomaly_id"], truth=row["is_anomaly"] == "true",
                    posthog_count=observed, posthog_status=posthog_status if eligible else "pack_excluded",
                    posthog_expected=band.expected if eligible and band else None,
                    posthog_lower=band.lower if eligible and band else None,
                    posthog_upper=band.upper if eligible and band else None,
                    posthog_alert=(observed < band.lower or observed > band.upper) if eligible and band else None,
                    anomalyzer_status=status, anomalyzer_alert=alert, anomalyzer_point=point,
                    anomalyzer_original_status=original_status, anomalyzer_original_alert=original_alert,
                    anomalyzer_original_point=original_point,
                )


def grade(rows, alert_column, shared=False):
    counts = Counter()
    incidents = defaultdict(list)
    previous_false = None
    for row in rows:
        if not row["eligible"]:
            continue
        index = row["index"]
        alert = row[alert_column]
        if shared and (row["posthog_alert"] is None or row["anomalyzer_alert"] is None):
            alert = None
        if row["incident_id"]:
            incidents[row["incident_id"]].append((index, alert, row["cadence"]))
        counts["eligible"] += 1
        if alert is None:
            counts["unscored"] += 1
        else:
            counts["scored"] += 1
            if not row["truth"]:
                counts["scored_normal"] += 1
        if alert and not row["truth"]:
            counts["false_alert_rows"] += 1
            key = row["case_id"], row["series_id"]
            if previous_false != (key, index - 1):
                counts["false_alert_runs"] += 1
            previous_false = (key, index)
    results = []
    for incident_id, observations in incidents.items():
        start, _, cadence = observations[0]
        first = next((index for index, alert, _ in observations if alert), None)
        scored = sum(alert is not None for _, alert, _ in observations)
        status = "detected" if first is not None else "missed" if scored else "unassessed"
        delay = first - start if first is not None else None
        counts[status] += 1
        results.append(dict(incident_id=incident_id, cadence=cadence, onset=start, first_detection=first,
                            delay_buckets=delay, scored_incident_buckets=scored,
                            total_incident_buckets=len(observations), status=status))
    delays = [r["delay_buckets"] for r in results if r["delay_buckets"] is not None]
    fields = ("eligible", "scored", "unscored", "scored_normal", "false_alert_rows", "false_alert_runs",
              "detected", "missed", "unassessed")
    normal_days = sum(1 / BUCKETS_PER_DAY[row["cadence"]] for row in rows
                      if row["eligible"] and not row["truth"] and row[alert_column] is not None
                      and (not shared or (row["posthog_alert"] is not None and row["anomalyzer_alert"] is not None)))
    return (dict(**{field: counts[field] for field in fields},
                 false_alert_rows_per_scored_normal_series_day=counts["false_alert_rows"] / normal_days if normal_days else None,
                 median_delay_buckets=median(delays) if delays else None,
                 max_delay_buckets=max(delays, default=None)), results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--posthog-source", type=Path, required=True, help=f"Source root at {POSTHOG_REVISION}")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = (args.posthog_source / POSTHOG_BANDS).read_bytes().replace(b"\r\n", b"\n")
    blob = sha1(f"blob {len(source)}\0".encode() + source).hexdigest()
    if blob != POSTHOG_BANDS_BLOB:
        parser.error(f"PostHog band source differs from the pinned revision {POSTHOG_REVISION}")
    sys.path.insert(0, str(args.posthog_source.resolve()))
    import numpy as np
    import scipy
    from products.apm.backend.logic.anomaly_detection.bands import NegativeBinomialBandModel

    rows = list(pack_predictions(NegativeBinomialBandModel(), np.asarray))
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "predictions.csv", rows)
    summaries, incidents, cases = [], [], []
    for cohort in ("integer", "rounded"):
        for cadence in BUCKETS_PER_DAY:
            group = [row for row in rows if (row["cohort"], row["cadence"]) == (cohort, cadence)]
            for tool in ("posthog_alert", "anomalyzer_alert", "anomalyzer_point"):
                for shared in (False, True):
                    key = dict(cohort=cohort, cadence=cadence, detector=tool, shared_scoring=shared)
                    summary, details = grade(group, tool, shared)
                    summaries.append(dict(**key, **summary))
                    incidents.extend(key | row for row in details)
    write_csv(args.output / "incidents.csv", incidents)
    by_series = defaultdict(list)
    for row in rows:
        by_series[row["case_id"], row["series_id"]].append(row)
    for (case_id, series_id), group in by_series.items():
        first = group[0]
        eligible = [row for row in group if row["eligible"]]
        cases.append(dict(case_id=case_id, series_id=series_id, task=first["task"], cadence=first["cadence"],
                          cohort=first["cohort"], rows=len(group), eligible=len(eligible),
                          posthog_native_scored=0,
                          posthog_scored=sum(row["posthog_alert"] is not None for row in eligible),
                          anomalyzer_scored=sum(row["anomalyzer_alert"] is not None for row in eligible),
                          anomalyzer_original_scored=sum(row["anomalyzer_original_alert"] is not None for row in eligible),
                          posthog_unscored_reasons=dict(Counter(row["posthog_status"] for row in eligible
                                                               if row["posthog_alert"] is None)),
                          anomalyzer_unscored_reasons=dict(Counter(row["anomalyzer_status"] for row in eligible
                                                                  if row["anomalyzer_alert"] is None))))
    write_csv(args.output / "cases.csv", cases)
    write_csv(args.output / "summary.csv", summaries)
    (args.output / "versions.json").write_text(json.dumps(dict(posthog=POSTHOG_REVISION, anomalyzer=__version__,
        numpy=np.__version__, scipy=scipy.__version__), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
