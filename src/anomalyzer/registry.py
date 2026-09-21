from importlib.metadata import version, PackageNotFoundError
import platform


def versions():
    result = {"python": platform.python_version()}
    for name in ("anomalyzer", "pydantic"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not installed"
    return result


def methods():
    return {
        "schema_version": "1.0", "dependencies": versions(),
        "methods": [{
            "id": "seasonal_trend", "tasks": ["analyze"],
            "provider": "python standard library", "installed": True,
            "requirements": {"regular": True, "complete": True,
                             "minimum_reference": "season_length + 1 observations",
                             "minimum_training": "max(training_size, season_length)",
                             "minimum_calibration": 3,
                             "minimum_calibrated": "max(training_size, season_length) + calibration_size + 1 observations"},
            "parameters": {"season_length": "positive integer sample lag; 1 uses the previous observation",
                           "trend": "auto (default), none, linear, exponential; none returns seasonal_naive",
                           "trend_training": "at least max(8, 4*season_length) samples; otherwise disclosed seasonal fallback",
                           "cusum": "two-sided standardized residual CUSUM; defaults k=0.5 and h=5",
                           "moving_range_threshold": "adjacent standardized-residual range threshold; default 3.686",
                           "reset_points": "manual segment starts as prepared zero-based positions, dates, or exact timestamps"},
            "coordinate_support": ["timestamp", "position"],
            "season_inference": "positional input only when season_length is omitted; stable three-cycle candidate up to lag 512 using at most 4096 selection values, or disclosed lag-1 fallback",
            "signal_maturities": {
                "reference_only": "raw residual and relative deviation; no standardized score or trigger",
                "provisional": "standardized by at least 3 earlier calibration residuals; never triggers",
                "calibrated": "standardized by the complete frozen calibration window; threshold-eligible"},
            "score_semantics": "causal seasonal residual evidence; standardized scores are not probabilities",
            "update_semantics": "within each manual segment, previous seasonal observation plus training-only linear/compound trend change; model frozen before calibration",
            "capability": "batch chronological replay"
        }, {
            "id": "multi_resolution", "tasks": ["analyze"],
            "provider": "python standard library", "installed": True,
            "requirements": {"coordinate": "timestamp",
                             "frequency": "regular sub-day cadence evenly dividing 24 hours",
                             "aggregation": "sum, mean, or last"},
            "parameters": {
                "completed_period_season_length": "default 7 fixed 24-hour periods",
                "intraday_season_length": "default seven 24-hour periods at source cadence",
                "aggregate_anchor": "fixed-period grid origin; default 00:00 UTC on the first observation date",
                "aggregate_function": "sum (default), mean, or last"},
            "score_semantics": "two correlated seasonal-residual views: finalized 24-hour aggregates and finalized source subperiods",
            "update_semantics": "a trailing partial aggregate is marked incomplete and excluded from completed-period scoring",
            "capability": "batch multi-resolution chronological replay"
        }],
        "detectors": [
            {"id": "point", "score_semantics": "absolute standardized residual > point_threshold"},
            {"id": "consecutive_run", "input": "binary point-anomaly stream",
             "minimum_run": 2,
             "score_semantics": "two or more adjacent point anomalies; descriptive second-order pattern, not a probability"},
            {"id": "nelson_rule_2", "input": "calibrated standardized residuals",
             "score_semantics": "9 consecutive residuals on one side of the frozen residual centerline; possible location shift, not a full-distribution change"},
            {"id": "nelson_rule_3", "input": "calibrated standardized residuals",
             "score_semantics": "6 residuals continually increasing or decreasing; possible residual trend or model drift, not a location shift"},
            {"id": "nelson_rule_4", "input": "calibrated standardized residuals",
             "score_semantics": "14 residuals alternating direction; possible systematic oscillation or missed structure"},
            {"id": "nelson_rule_5", "input": "calibrated standardized residuals",
             "score_semantics": "2 of 3 residuals beyond 2 standard deviations on one side; possible location shift, not a full-distribution change"},
            {"id": "nelson_rule_6", "input": "calibrated standardized residuals",
             "score_semantics": "4 of 5 residuals beyond 1 standard deviation on one side; possible location shift, not a full-distribution change"},
            {"id": "nelson_rule_8", "input": "calibrated standardized residuals",
             "score_semantics": "8 residuals beyond 1 standard deviation on both sides; possible mixture or missed structure"},
            {"id": "cusum", "input": "calibrated standardized residuals",
             "score_semantics": "two-sided cumulative sum with configurable k and h; possible location shift, not a probability"},
            {"id": "moving_range", "input": "adjacent calibrated standardized residuals",
             "score_semantics": "adjacent residual spread above a configurable threshold; possible short-term variation increase"}
        ]
    }
