"""Internal harness; no incident labels means no precision/recall claims."""
from ..contracts import Request
from ..recipes import analyze


def replay(request: Request | dict):
    result = analyze(request)
    pattern_counts = {}
    first_detections = {}
    for pattern in result.anomaly_patterns:
        pattern_counts[pattern["rule"]] = pattern_counts.get(pattern["rule"], 0) + 1
        first_detections.setdefault(pattern["rule"], pattern["detection_index"])
        first_detections[pattern["rule"]] = min(
            first_detections[pattern["rule"]], pattern["detection_index"])
    return {"status": result.status, "methods": [{"id": m.id, "status": m.status, "mae": m.diagnostics.get("held_out_mae"), "rmse": m.diagnostics.get("held_out_rmse"), "triggered_samples": sum(bool(e["triggers"]) for e in m.evidence), "runtime_seconds": m.runtime_seconds} for m in result.methods], "recipe_episodes": len(result.observations), "pattern_counts": pattern_counts, "first_detection_by_rule": first_detections, "detection_precision": None, "detection_recall": None, "limitation": "Synthetic and unlabeled replay does not establish product effectiveness or calibrated false-alarm rates."}
