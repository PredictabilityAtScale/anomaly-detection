"""Project native historical evidence without a second fit or detector run."""
from __future__ import annotations

import hashlib
import json

from ._version import __version__
from .forecast_contracts import (
    HistoricalAnomalies, HistoricalAnomalyPoint, HistoricalCalibration,
    HistoricalPattern, HistoricalReferenceAdjustment,
    HistoricalDetectorSettings,
)
from .robust import EXTREME_Z


def historical_anomalies(data, config, selection, training_window, inference, analysis, budget):
    """Keep point-time evidence and freeze pattern summaries at first detection.

    The analysis engine's merged intervals can extend into a later suffix. Only
    the prefix through detection_index is published here. Exclusion annotations
    are retrospective and are deliberately absent from point detections.
    """
    method = analysis.methods[0] if analysis is not None else None
    training = (training_window[1] + 1 if training_window is not None else
                min(config.max_training_points, config.max_inference_points)
                if config.seasonality == "auto" else max(56 if config.baseline == "recent-level-v1" and config.seasonality.period == 1 and config.trend in ("auto", "none") else 28, config.seasonality.period))
    calibrated_at = training + 14
    settings = HistoricalDetectorSettings(forecast_baseline=config.baseline,
                    level_baseline=method.diagnostics.get("level_baseline") if method else None, recipe="seasonal-residual-v1", training_size=training,
                    calibration_size=14, trend=config.trend,
                    season_length=inference["selected_lag"] if inference else None,
                    outlier_handling=config.outlier_handling, robust_reference_seasons=4,
                    reference_exclusion_threshold=EXTREME_Z if config.outlier_handling == "robust" else None,
                    **config.historical_anomalies.model_dump(exclude={"schema_version"})).model_dump(mode="json")
    origin = None
    if training_window is not None:
        origin = hashlib.sha256(json.dumps(dict(
            engine_version=__version__, settings=settings,
            dataset=dict(id=data.id, interval=data.interval, timezone=data.timezone,
                         values=data.values[:training],
                         timestamps=data.timestamps[:training] if data.timestamps else None)),
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    native = {p["index"]: p for p in method.evidence} if method else {}
    points = []
    for index, (observed, status) in enumerate(zip(data.values, data.period_statuses)):
        budget.check()
        item = native.get(index) if index >= training and status == "complete" else None
        if item is None:
            points.append(HistoricalAnomalyPoint(index=index, period_status=status,
                observed=observed, availability="unavailable",
                unavailable_reason="partial" if status == "partial" else "warmup",
                score_semantics="No historical detector reference is available."))
            continue
        maturity = item["signal_maturity"]
        samples = item["calibration_samples"]
        points.append(HistoricalAnomalyPoint(index=index, period_status=status,
            observed=observed, availability="available", available_from_index=index,
            reference_cutoff_index=index - 1, expected=item["expected"],
            residual=item["residual"], standardized_score=item["standardized_residual"],
            score_semantics=item["score_semantics"], triggers=item["triggers"],
            direction="increase" if item["residual"] > 0 else "decrease" if item["residual"] < 0 else "flat",
            maturity=maturity, calibration_samples=samples,
            calibration_cutoff_index=(calibrated_at - 1 if maturity == "calibrated"
                                      else index - 1 if samples else None)))
    patterns = []
    if analysis is not None:
        for pattern in analysis.anomaly_patterns:
            budget.check()
            detection = pattern["detection_index"]
            indices = [i for i in pattern["triggering_samples"] if i <= detection]
            # Recompute descriptive summaries only, never scores or thresholds.
            # In particular a later opposite point must not rewrite run direction.
            direction = pattern["direction"]
            if pattern["rule"] == "adjacent_point_anomalies":
                directions = {points[i].direction for i in indices}
                direction = next(iter(directions)) if len(directions) == 1 else "mixed"
            patterns.append(HistoricalPattern(
                id=f"{pattern['rule']}:{indices[0]}:{detection}:{direction}",
                rule=pattern["rule"], kind=pattern["kind"], direction=direction,
                start_index=indices[0], detection_index=detection,
                available_from_index=detection, triggering_indices=indices,
                peak_standardized_score=max(abs(points[i].standardized_score) for i in indices)))
    patterns.sort(key=lambda p: (p.detection_index, p.id))
    adjustments = []
    for index, item in native.items():
        budget.check()
        if not item.get("excluded_from_model"):
            continue
        reason = item["exclusion_reason"]
        available = (training if reason == "extreme_training_residual" else
                     calibrated_at if reason == "extreme_calibration_residual" else index)
        adjustments.append(HistoricalReferenceAdjustment(index=index,
            available_from_index=available, reason=reason,
            observed=item["observed"], replacement=item["model_value"]))
    diagnostics = method.diagnostics if method else {}
    segment = next(iter(diagnostics.get("segments", [])), {})
    calibration = None
    calibration_fingerprint = None
    if "calibration_center" in segment:
        calibration = HistoricalCalibration(available_from_index=calibrated_at,
            cutoff_index=calibrated_at - 1, samples=segment["calibration_used_count"],
            center=segment["calibration_center"], scale=segment["calibration_scale"],
            raw_scale=segment["raw_scale"])
        calibration_fingerprint = hashlib.sha256(json.dumps(dict(
            origin_fingerprint=origin, values=data.values[training:calibrated_at]),
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return HistoricalAnomalies(availability="available" if any(p.availability == "available" for p in points) else "unavailable",
        unavailable_reason=None if any(p.availability == "available" for p in points) else "warmup",
        engine_version=__version__, origin_fingerprint=origin,
        calibration_fingerprint=calibration_fingerprint, resolved_settings=settings,
        training_window=training_window, selection_window=selection,
        frozen_trend=diagnostics.get("trend"), calibration=calibration,
        readiness=diagnostics.get("detection_readiness", {"status": "not_assessed"}),
        readiness_available_from_index=calibrated_at if calibration else None,
        points=points, patterns=patterns, reference_adjustments=adjustments,
        limitations=[
            "Scores use signed native expected, not lower-bounded forecast-v1 display expected; score direction is centered residual, point direction is raw residual.",
            "Only calibrated point triggers qualify statistically; provisional scores are non-triggering diagnostics, not probabilities.",
            "Pattern snapshots stop at first detection; later merged interval/peak diagnostics are deliberately omitted.",
            "Reference adjustments are model operations available at their stated index, never anomaly labels.",
            "Readiness is a training/calibration diagnostic, not health, confidence, accuracy or business severity.",
            *([] if method is None else method.limitations)])
