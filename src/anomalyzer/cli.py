import argparse
import json
import re
import sys
from pathlib import Path
from pydantic import ValidationError
from .contracts import Request, RequestV11, Settings
from .io import read_text, load_json, csv_dataset, write_result
from .recipes import analyze
from .registry import methods


def parser():
    formatter = argparse.RawDescriptionHelpFormatter
    exit_codes = """Exit codes:
  0  Analysis completed (including anomalies), insufficient history, or
     inapplicable data; also successful help, version, or method listing.
  1  Execution failure, interruption, or partial/budget-limited analysis.
  2  Invalid input, configuration, or command-line options."""
    root = argparse.ArgumentParser(
        prog="anomalyzer", formatter_class=formatter,
        description="Produce inspectable single-series or declared-relationship evidence locally, without a model API.",
        epilog="""Quick start:
  anomalyzer analyze examples/spike.csv --time timestamp --value calls --frequency 1d
  anomalyzer analyze examples/spike.json --format json
  anomalyzer methods --format json

Run 'anomalyzer analyze --help' for input rules, tuning, and more examples.
Run 'anomalyzer methods --help' for method discovery.

""" + exit_codes)
    root.add_argument("--version", action="version", version="anomalyzer 0.1.0")
    commands = root.add_subparsers(dest="command", required=True, title="commands")
    defaults = Settings()
    for command in ("analyze", "methods"):
        is_analysis = command == "analyze"
        sub = commands.add_parser(
            command, formatter_class=formatter,
            help="Analyze CSV or schema-1.0/1.1 canonical JSON evidence" if is_analysis
            else "List installed analysis methods and detectors",
            description="Compare each observation with a seasonal baseline adjusted for linear or exponential trend.\n"
            "Early evidence is non-triggering; calibrated departures can form anomaly episodes."
            if is_analysis else
            "Discover installed analysis methods and their requirements.\n"
            "Use JSON for detectors, parameters, score semantics, and dependency versions.",
        )
        output = sub.add_argument_group("output")
        output.add_argument("--format", choices=["text", "json"], default="text",
                            help="Result format: readable summary or full structured JSON (default: text)")
        output.add_argument("--output", metavar="PATH",
                            help="Write UTF-8 output to PATH instead of stdout; diagnostics use stderr")
        output.add_argument("--overwrite", action="store_true",
                            help="Allow --output to replace an existing file (default: refuse)")
        if command == "methods":
            sub.epilog = """Examples:
  anomalyzer methods
  anomalyzer methods --format json
  anomalyzer methods --format json --output methods.json

""" + exit_codes
            continue
        sub.add_argument("input", nargs="?", metavar="INPUT",
                         help="CSV or canonical JSON path, or '-' for stdin; omit if --config supplies the dataset")
        source = sub.add_argument_group("input and configuration")
        source.add_argument("--input-format", choices=["csv", "json"],
                            help="Input encoding (default: json for paths ending in '.json', csv otherwise; set explicitly for JSON stdin)")
        source.add_argument("--config", metavar="PATH",
                            help="JSON settings or complete canonical request; a request with datasets cannot be combined with INPUT")
        source.add_argument("--time", metavar="COLUMN", help="CSV timestamp column; omit together with --frequency for positional values")
        source.add_argument("--value", metavar="COLUMN", help="CSV numeric value column name (required for CSV)")
        source.add_argument("--frequency", metavar="DURATION",
                            help="Fixed cadence, e.g. 15min, 1h, 1d, 1w; required with --time and omitted without it")
        source.add_argument("--timezone", metavar="ZONE",
                            help="IANA timezone for timestamps without offsets, e.g. America/Los_Angeles; overrides JSON timezone")
        source.add_argument("--units", metavar="LABEL",
                            help="Value unit label, e.g. calls; overrides JSON units; performs no conversion")
        tuning = sub.add_argument_group("analysis settings", "Defaults below apply unless supplied by JSON configuration.")
        limits = sub.add_argument_group("resource limits", "Defaults below apply unless supplied by JSON configuration.")
        tuning.add_argument("--recipe", choices=["seasonal-residual-v1", "multi-resolution-v1"],
                            help="Analysis recipe; multi-resolution derives finalized 24-hour aggregates and an intraday view")
        tuning.add_argument("--aggregate-function", choices=["sum", "mean", "last"],
                            help="How multi-resolution-v1 combines finalized subperiods (default: sum)")
        tuning.add_argument("--aggregate-anchor", metavar="TIMESTAMP",
                            help="Start of the fixed 24-hour aggregation grid; defaults to 00:00 UTC on the first observation date")
        tuning.add_argument("--completed-period-season-length", type=int, metavar="PERIODS",
                            help="Seasonal lag for completed 24-hour aggregates (default: 7)")
        tuning.add_argument("--intraday-season-length", type=int, metavar="SAMPLES",
                            help="Seasonal lag for the sub-day view (default: seven 24-hour periods)")
        settings = [
            (tuning, "season-length", int, "SAMPLES", "Baseline lag in samples; positional input infers a stable lag when omitted, then falls back to 1 (1..10000)"),
            (tuning, "training-size", int, "SAMPLES", "Initial samples reserved before calibration; effective size is max(training-size, season-length) (at least 2)"),
            (tuning, "calibration-size", int, "SAMPLES", "Following samples used to estimate and freeze residual mean and standard deviation (at least 3)"),
            (tuning, "point-threshold", float, "SCORE", "Flag when absolute standardized residual exceeds this positive threshold; not a probability"),
            (tuning, "cusum-k", float, "SCORE", "Positive CUSUM allowance in standardized-residual units; 0.5 targets shifts near 1 sigma"),
            (tuning, "cusum-h", float, "SCORE", "Positive decision threshold for upward and downward residual CUSUMs"),
            (tuning, "moving-range-threshold", float, "SCORE", "Flag adjacent standardized-residual ranges above this positive threshold"),
            (tuning, "scale-floor", float, "VALUE", "Positive minimum residual standard deviation, in input units; controls sensitivity when calibration variance is tiny"),
            (limits, "max-points", int, "COUNT", "Maximum input observations (1..1000000)"),
            (limits, "max-bytes", int, "BYTES", "Maximum INPUT file/stdin bytes (1..100000000); --config has a separate fixed 10000000-byte limit"),
            (limits, "max-runtime-seconds", float, "SECONDS", "Cooperative analysis budget checked between samples, not a hard timeout (greater than 0, at most 3600)"),
        ]
        for group, flag, kind, metavar, help_text in settings:
            default = getattr(defaults, flag.replace("-", "_"))
            if flag == "season-length":
                default = "infer for positional input; 1 otherwise"
            group.add_argument("--" + flag, type=kind, metavar=metavar,
                               help=f"{help_text} (default: {default})")
        tuning.add_argument("--duplicate-policy", choices=["error", "mean", "sum"],
                            help=f"Handle duplicate timestamps: reject, average, or sum; missing values propagate (default: {defaults.duplicate_policy})")
        tuning.add_argument("--trend", choices=["auto", "none", "linear", "exponential"],
                            help="Training-only trend model; auto chooses conservatively (default: auto)")
        tuning.add_argument("--outlier-handling", choices=["robust", "include"],
                            help=("Protect trend, calibration, and future seasonal references from extreme residuals, or include every observation unchanged "
                                  f"(default: {defaults.outlier_handling})"))
        tuning.add_argument("--reset-point", dest="reset_points", action="append",
                            type=lambda value: int(value) if re.fullmatch(r"[0-9]+", value) else value,
                            metavar="POSITION_OR_TIMESTAMP",
                            help="Start a new manual regime at a zero-based position, date, or exact timestamp; repeat for multiple resets")
        sub.epilog = """Input rules:
  CSV supplies one series. Canonical schema-1.1 JSON can supply up to four
  named datasets and four explicit relationships. CSV always needs --value.
  Supply --time and --frequency
  together for timestamped data, or omit both for ordered positional values.
  Empty values mean missing, never zero; extra varying columns are rejected.
  JSON may be a canonical request object or a bare array of ordered values.
  Dataset timestamps and frequency are both optional for positional data.
  Timestamps need an explicit UTC offset or an IANA timezone. Ambiguous or
  nonexistent local DST times require explicit offsets.
  Missing values or irregular cadence make analysis inapplicable; no filling
  or resampling is performed.
  JSON datasets may align period_statuses with values. A trailing incomplete
  suffix is reported in data_quality and excluded from finalized scoring.

Configuration:
  Precedence (highest first): CLI flags > settings file > embedded JSON
  config > defaults. Settings JSON uses underscore keys, e.g. season_length.
  Positional input infers season_length when it is omitted. Inference requires
  a stable candidate across at least three cycles in a training prefix and a
  separate calibration/evaluation tail; otherwise lag 1 is disclosed and used.
  Automatic candidates are bounded to lag 512 and 4096 selection values.
  Raw reference evidence starts after season_length observations. Provisional
  standardized evidence starts after at least 3 earlier calibration residuals.
  Only fully calibrated evidence can trigger; that needs
  max(training_size, season_length) + calibration_size + 1 observations: 43
  with defaults. Shorter series return non-triggering evidence when possible
  and an insufficient_history status.
  Robust outlier handling is enabled by default. Actual observations remain
  visible and scoreable; only an extreme point's influence on trend,
  calibration, and future seasonal references is reduced. Use
  --outlier-handling include to reproduce the unprotected baseline and its
  possible one-season echo. Robust handling never creates a regime reset.
  Adjacent calibrated point anomalies remain individual evidence and also form
  a consecutive_run entry in anomaly_patterns when the run has at least two
  samples. Two-sided CUSUM and Nelson Rules 2, 5, and 6 inspect calibrated
  residuals for possible location shifts. Nelson Rules 3, 4, and 8 describe
  residual trend, oscillation, and mixture patterns; moving range describes
  possible short-term variation increases. Patterns never retrain automatically.
  Repeat --reset-point to declare known regime boundaries. A reset starts a new
  training/calibration sequence and prevents references from crossing the
  boundary. Positions refer to the prepared chronological series after sorting,
  duplicate handling, and as_of filtering. Dates must identify one observed
  sample; full timestamps must match one. Each segment reuses season_length but
  rebuilds its seasonal history and refits trend. Short segments remain
  non-triggering until their own calibration completes.
  multi-resolution-v1 requires regular timestamped sub-day input whose cadence
  divides 24 hours. It analyzes finalized source samples at their native cadence,
  separately aggregates complete fixed 24-hour periods, and explicitly reports
  the trailing incomplete aggregate without treating it as a completed day.

Examples (from the repository root, with anomalyzer on PATH):
  # Daily CSV with weekly seasonality
  anomalyzer analyze examples/spike.csv --time timestamp --value calls --frequency 1d --season-length 7

  # Value-only CSV, explicit lag; omit --season-length to infer or fall back
  anomalyzer analyze values.csv --value calls --season-length 7

  # Canonical JSON, or a complete request supplied as configuration
  anomalyzer analyze examples/spike.json --format json
  anomalyzer analyze --config examples/shift.json

  # Known regime changes at a position and date
  anomalyzer analyze examples/steps.csv --time timestamp --value calls --frequency 1d --season-length 7 --reset-point 50 --reset-point 2026-04-11

  # Pipe JSON using PowerShell (use cat in a Unix shell)
  Get-Content -Raw examples/spike.json | anomalyzer analyze - --input-format json --format json

  # Save full evidence; add --overwrite to replace an existing file
  anomalyzer analyze examples/spike.json --format json --output result.json

""" + exit_codes
    return root


def build_request(args):
    document = {}
    config = {}
    if args.config:
        supplied = load_json(read_text(args.config, 10000000))
        if not isinstance(supplied, dict):
            raise ValueError("configuration must be a JSON object")
        if "datasets" in supplied:
            document = supplied
        else:
            config = supplied
    if args.input:
        if document:
            raise ValueError("supply datasets through input or configuration, not both")
        input_format = args.input_format or ("json" if args.input.endswith(".json") else "csv")
        limit = args.max_bytes if args.max_bytes is not None else config.get("max_bytes", Settings().max_bytes)
        limit = Settings.model_validate({"max_bytes": limit}).max_bytes
        raw = read_text(args.input, limit)
        if input_format == "json":
            document = load_json(raw)
            if isinstance(document, list):
                document = {"datasets": [{"values": document}]}
            elif not isinstance(document, dict):
                raise ValueError("JSON input must be a canonical request object or an array of values")
        else:
            document = {"datasets": [csv_dataset(raw, args.time, args.value, args.frequency, args.timezone, args.units).model_dump()]}
    if not document:
        raise ValueError("supply an input file, stdin '-', or a canonical request with --config")
    embedded = document.get("config", {})
    if not isinstance(embedded, dict):
        raise ValueError("config must be an object")
    merged = {**embedded, **config}
    for key in Settings.model_fields:
        value = getattr(args, key, None)
        if value is not None:
            merged[key] = value
    document["config"] = merged
    datasets = document.get("datasets", [])
    if not isinstance(datasets, list):
        raise ValueError("datasets must be an array")
    for ds in datasets:
        for key in ("frequency", "timezone", "units"):
            value = getattr(args, key)
            if value is not None and isinstance(ds, dict):
                ds[key] = value
    contract = RequestV11 if document.get("schema_version") == "1.1" else Request
    return contract.model_validate(document)


def readable(result):
    if "detectors" in result:
        return "Installed analysis methods\n" + "\n".join(f"  {m['id']}: {m['update_semantics']}" for m in result["methods"])
    if result.get("schema_version") == "1.1":
        lines = [
            f"Analysis: {result['status']}",
            (f"Datasets: {len(result['dataset_results'])}; relationships: "
             f"{len(result['relationship_results'])}; cases: {len(result['cases'])}"),
        ]
        for item in result["dataset_results"]:
            lines.append(
                f"  dataset {item['dataset_id']}: {item['status']}; "
                f"assessments={len(item['assessments'])}" +
                (f" — {item['error']}" if item["error"] else ""))
        for item in result["relationship_results"]:
            lines.append(
                f"  relationship {item['relationship_id']} ({item['kind']}): "
                f"{item['status']}; assessments={len(item['assessments'])}" +
                (f" — {item['error']}" if item["error"] else ""))
        lines.append("Business impact: unresolved. Relationship evidence does not establish cause.")
        return "\n".join(lines)
    lines = [f"Analysis: {result['status']}",
             f"Samples: {result['data_quality']['observation_count']}; episodes: {len(result['observations'])}; patterns: {len(result['anomaly_patterns'])}"]
    incomplete = result["data_quality"].get("incomplete_period")
    if incomplete:
        lines.append(
            "Incomplete period: "
            f"{incomplete['start']} through {incomplete['observed_through']} "
            f"({incomplete['completed_subperiods']}/{incomplete['expected_subperiods']} finalized subperiods; excluded from completed-period scoring)")
    elif result["data_quality"].get("incomplete_count"):
        lines.append(
            f"Incomplete source periods: {result['data_quality']['incomplete_count']} "
            "trailing sample(s), explicitly excluded from finalized scoring")
    for method in result["methods"]:
        lines.append(f"  {method['id']}: {method['status']}" + (f" — {method['error']}" if method["error"] else ""))
        counts = method.get("diagnostics", {}).get("maturity_counts")
        if counts:
            lines.append("    evidence: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
        handling = method.get("diagnostics", {}).get("outlier_handling")
        if handling:
            lines.append(
                f"    model protection: {handling['mode']}; "
                f"training exclusions={len(handling['training_excluded_positions'])}, "
                f"calibration exclusions={len(handling['calibration_excluded_positions'])}, "
                f"future reference replacements={len(handling['evaluation_reference_replacements'])}")
    for episode in result["observations"]:
        lines.append(f"  {episode['interval'][0]} to {episode['interval'][1]}: {episode['direction']}, peak departure {episode['magnitude']:.6g}")
    for pattern in result["anomaly_patterns"]:
        lines.append(f"  {pattern['interval'][0]} to {pattern['interval'][1]}: {pattern['description']} Detection first became possible at sample {pattern['detection_index']}.")
    if result["status"] != "completed":
        lines.append("This run does not establish normality. Inspect method applicability and status.")
    lines.extend(["Business impact: unresolved.", "Next: " + " ".join(result["suggested_checks"])])
    return "\n".join(lines)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.output and Path(args.output).exists() and not args.overwrite:
            raise ValueError("output exists; use --overwrite to replace it")
        result = methods() if args.command == "methods" else analyze(build_request(args)).model_dump(mode="json")
        text = json.dumps(result, indent=2, allow_nan=False) if args.format == "json" else readable(result)
        write_result(text, args.output, args.overwrite)
        return 1 if result.get("status") in ("failed", "partial") else 0
    except (ValueError, ValidationError, UnicodeError, FileExistsError) as exc:
        print(f"Invalid input/configuration: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Execution interrupted", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Execution failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
