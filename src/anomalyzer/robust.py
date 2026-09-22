"""Small dependency-free robust statistics used by model fitting.

These helpers identify extreme contamination in a completed fitting window. They
do not classify incidents and must not be used to suppress anomaly evidence.
"""

from __future__ import annotations

import math
import statistics


MAD_TO_SIGMA = 1.4826
EXTREME_Z = 4.5
HUBER_C = 1.5


def median_scale(values, scale_floor):
    """Return a median center and normal-consistent MAD scale."""
    if not values:
        raise ValueError("robust statistics require at least one value")
    center = statistics.median(values)
    mad = statistics.median(abs(value - center) for value in values)
    raw_scale = MAD_TO_SIGMA * mad
    scale = max(raw_scale, scale_floor)
    if not math.isfinite(center) or not math.isfinite(scale):
        raise RuntimeError("nonfinite robust statistics")
    return center, scale, raw_scale


def extreme_indices(values, scale_floor, threshold=EXTREME_Z, minimum_retained=3):
    """Find extreme values without allowing filtering to empty a small window."""
    if len(values) < minimum_retained + 1:
        return [], {"center": None, "scale": None, "raw_scale": None,
                    "threshold": threshold, "reason": "too_few_samples"}
    center, scale, raw_scale = median_scale(values, scale_floor)
    excluded = [index for index, value in enumerate(values)
                if abs(value - center) / scale > threshold]
    if len(values) - len(excluded) < minimum_retained:
        return [], {"center": center, "scale": scale, "raw_scale": raw_scale,
                    "threshold": threshold,
                    "reason": "minimum_retained_samples_would_be_violated"}
    return excluded, {"center": center, "scale": scale,
                      "raw_scale": raw_scale, "threshold": threshold}


def huber_weights(residuals, scale_floor, tuning=HUBER_C):
    """Return bounded-influence weights centered on the residual median."""
    if not residuals:
        return []
    center, scale, _ = median_scale(residuals, scale_floor)
    limit = tuning * scale
    weights = []
    for residual in residuals:
        distance = abs(residual - center)
        weights.append(1.0 if distance <= limit else limit / distance)
    return weights
