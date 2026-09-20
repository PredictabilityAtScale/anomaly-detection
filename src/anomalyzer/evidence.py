"""Group consecutive residual departures into inspectable episodes."""


def episodes(methods, dataset):
    samples = {}
    completed = [m.id for m in methods if m.status == "completed"]
    for method in methods:
        for item in method.evidence:
            if item["triggers"]:
                samples.setdefault(item["index"], []).append(item)
    groups = []
    for index in sorted(samples):
        if not groups or index > groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(index)
    output = []
    for group in groups:
        evidence = [e for index in group for e in samples[index]]
        supporting = sorted({e["method"] for e in evidence})
        peak = max(evidence, key=lambda e: abs(e["residual"]))
        directions = {"increase" if e["residual"] > 0 else "decrease" for e in evidence}
        interval = [evidence[0]["timestamp"], evidence[-1]["timestamp"]]
        if interval[0] is None:
            interval = [evidence[0]["index"], evidence[-1]["index"]]
        output.append(dict(id=f"episode-{len(output)+1}", dataset=dataset, interval=interval, direction=next(iter(directions)) if len(directions) == 1 else "mixed", magnitude=abs(peak["residual"]), observed_statistic=peak["observed"], reference=peak["expected"], triggering_samples=sorted(group), evidence_refs=[e["id"] for e in evidence], supporting_methods=supporting, quiet_methods=[m for m in completed if m not in supporting], business_impact="unresolved"))
    return output


def _interval(evidence):
    interval = [evidence[0]["timestamp"], evidence[-1]["timestamp"]]
    return ([evidence[0]["index"], evidence[-1]["index"]]
            if interval[0] is None else interval)


def _sequences(method):
    calibrated = [item for item in method.evidence
                  if item["signal_maturity"] == "calibrated"
                  and item["standardized_residual"] is not None]
    sequences = []
    for item in calibrated:
        if not sequences or item["index"] != sequences[-1][-1]["index"] + 1:
            sequences.append([])
        sequences[-1].append(item)
    return sequences


def _merge_windows(windows):
    merged = []
    for start, stop, direction in windows:
        if merged and direction == merged[-1][2] and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(stop, merged[-1][1]),
                          direction, merged[-1][3])
        else:
            merged.append((start, stop, direction, stop))
    return merged


def _description(rule, direction, criterion):
    if rule in ("nelson_rule_2", "nelson_rule_5", "nelson_rule_6"):
        shift = "upward" if direction == "increase" else "downward"
        side = "above" if direction == "increase" else "below"
        interpretation = (
            f"The run remains {side} the seasonal/trend expectation."
            if rule == "nelson_rule_2" else
            f"The qualifying residuals are concentrated {side} the seasonal/trend expectation."
        )
        return (f"Possible {shift} location shift: {criterion}. {interpretation} "
                "This is evidence about the center of the residual process; it does not "
                "establish that the full distribution changed.")
    if rule == "nelson_rule_3":
        direction_word = "increased" if direction == "increase" else "decreased"
        return (f"Possible residual trend: {criterion}; the residuals {direction_word}. "
                "This can indicate a changing slope or model drift relative to the "
                "seasonal/trend expectation, not a location-shift or full-distribution claim.")
    if rule == "nelson_rule_4":
        return (f"Possible systematic oscillation: {criterion}. This can indicate missed "
                "periodic structure, baseline echo, or overcorrection; it is not a "
                "location-shift or full-distribution claim.")
    if rule == "nelson_rule_8":
        return (f"Possible residual mixture: {criterion}. This can indicate mixed regimes, "
                "stratification, or missed structure; it is not a location-shift or proof "
                "that the full distribution changed.")
    raise ValueError(f"unsupported pattern rule: {rule}")


def anomaly_patterns(methods, dataset, minimum_run=2, cusum_k=0.5, cusum_h=5.0,
                     moving_range_threshold=3.686):
    """Identify extreme runs, CUSUM shifts, variation, and Nelson residual patterns."""
    samples = {}
    for method in methods:
        for item in method.evidence:
            if item["triggers"]:
                samples.setdefault(item["index"], []).append(item)
    groups = []
    for index in sorted(samples):
        if not groups or index != groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(index)
    output = []
    for group in (group for group in groups if len(group) >= minimum_run):
        evidence = [item for index in group for item in samples[index]]
        directions = {"increase" if item["residual"] > 0 else "decrease"
                      for item in evidence}
        output.append(dict(
            id=f"anomaly-pattern-{len(output)+1}", dataset=dataset,
            kind="consecutive_run", rule="adjacent_point_anomalies",
            description=(f"Consecutive extreme departures: {len(group)} adjacent calibrated "
                         "point anomalies exceeded the point threshold. This is not a Nelson "
                         "location-shift rule or an independent probability."),
            interval=_interval(evidence),
            sample_count=len(group), triggering_samples=group,
            detection_index=group[minimum_run-1],
            peak_standardized_residual=max(
                abs(item["standardized_residual"]) for item in evidence),
            direction=(next(iter(directions)) if len(directions) == 1 else "mixed"),
            evidence_refs=[item["id"] for item in evidence]))

    directional_rules = (
        ("nelson_rule_2", "location_shift", 9,
         lambda scores, sign: all(sign * score > 0 for score in scores),
         "9 consecutive calibrated residuals on the same side of the frozen residual centerline"),
        ("nelson_rule_3", "residual_trend", 6,
         lambda scores, sign: all(sign * (scores[i] - scores[i-1]) > 0
                                  for i in range(1, len(scores))),
         "6 consecutive calibrated residuals continually moved in one direction"),
        ("nelson_rule_5", "location_shift", 3,
         lambda scores, sign: sum(sign * score > 2 for score in scores) >= 2,
         "2 of 3 consecutive calibrated residuals beyond 2 standard deviations on the same side"),
        ("nelson_rule_6", "location_shift", 5,
         lambda scores, sign: sum(sign * score > 1 for score in scores) >= 4,
         "4 of 5 consecutive calibrated residuals beyond 1 standard deviation on the same side"),
    )
    mixed_rules = (
        ("nelson_rule_4", "systematic_oscillation", 14,
         lambda scores: all((scores[i] - scores[i-1]) *
                            (scores[i-1] - scores[i-2]) < 0
                            for i in range(2, len(scores))),
         "14 consecutive calibrated residuals alternated direction"),
        ("nelson_rule_8", "mixture_pattern", 8,
         lambda scores: (all(abs(score) > 1 for score in scores)
                         and any(score > 0 for score in scores)
                         and any(score < 0 for score in scores)),
         "8 consecutive calibrated residuals were all beyond 1 standard deviation, with values on both sides of the centerline"),
    )
    for method in methods:
        for sequence in _sequences(method):
            for rule, kind, width, matches, criterion in directional_rules:
                windows = []
                for start in range(len(sequence) - width + 1):
                    window = sequence[start:start+width]
                    scores = [item["standardized_residual"] for item in window]
                    for sign, direction in ((1, "increase"), (-1, "decrease")):
                        if matches(scores, sign):
                            windows.append((start, start+width-1, direction))
                for start, stop, direction, first_detection in _merge_windows(windows):
                    evidence = sequence[start:stop+1]
                    output.append(dict(
                        id=f"anomaly-pattern-{len(output)+1}", dataset=dataset,
                        kind=kind, rule=rule,
                        description=_description(rule, direction, criterion),
                        interval=_interval(evidence), sample_count=len(evidence),
                        triggering_samples=[item["index"] for item in evidence],
                        detection_index=sequence[first_detection]["index"],
                        peak_standardized_residual=max(
                            abs(item["standardized_residual"]) for item in evidence),
                        direction=direction,
                        evidence_refs=[item["id"] for item in evidence]))
            for rule, kind, width, matches, criterion in mixed_rules:
                windows = []
                for start in range(len(sequence) - width + 1):
                    scores = [item["standardized_residual"]
                              for item in sequence[start:start+width]]
                    if matches(scores):
                        windows.append((start, start+width-1, "mixed"))
                for start, stop, direction, first_detection in _merge_windows(windows):
                    evidence = sequence[start:stop+1]
                    output.append(dict(
                        id=f"anomaly-pattern-{len(output)+1}", dataset=dataset,
                        kind=kind, rule=rule,
                        description=_description(rule, direction, criterion),
                        interval=_interval(evidence), sample_count=len(evidence),
                        triggering_samples=[item["index"] for item in evidence],
                        detection_index=sequence[first_detection]["index"],
                        peak_standardized_residual=max(
                            abs(item["standardized_residual"]) for item in evidence),
                        direction=direction,
                        evidence_refs=[item["id"] for item in evidence]))

            for sign, direction in ((1, "increase"), (-1, "decrease")):
                cumulative = 0.0
                excursion_start = detection = None
                peak = 0.0

                def finish_cusum(stop):
                    if detection is None:
                        return
                    evidence = sequence[excursion_start:stop+1]
                    shift = "upward" if direction == "increase" else "downward"
                    side = "positive" if direction == "increase" else "negative"
                    output.append(dict(
                        id=f"anomaly-pattern-{len(output)+1}", dataset=dataset,
                        kind="location_shift", rule="cusum",
                        description=(f"Possible {shift} location shift: the {side} residual "
                                     f"CUSUM crossed h={cusum_h:g} using k={cusum_k:g}. "
                                     "This accumulates moderate same-direction departures "
                                     "from the seasonal/trend expectation; it is evidence "
                                     "about process location, not proof that the full "
                                     "distribution changed."),
                        interval=_interval(evidence), sample_count=len(evidence),
                        triggering_samples=[item["index"] for item in evidence],
                        detection_index=sequence[detection]["index"],
                        peak_standardized_residual=max(
                            abs(item["standardized_residual"]) for item in evidence),
                        peak_cusum=peak, detector_threshold=cusum_h,
                        direction=direction,
                        evidence_refs=[item["id"] for item in evidence]))

                for position, item in enumerate(sequence):
                    score = item["standardized_residual"]
                    updated = max(0.0, cumulative + sign * score - cusum_k)
                    if updated == 0:
                        finish_cusum(position - 1)
                        cumulative = peak = 0.0
                        excursion_start = detection = None
                        continue
                    if cumulative == 0:
                        excursion_start = position
                    cumulative = updated
                    peak = max(peak, cumulative)
                    if detection is None and cumulative > cusum_h:
                        detection = position
                finish_cusum(len(sequence) - 1)

            moving_windows = []
            for position in range(1, len(sequence)):
                moving_range = abs(sequence[position]["standardized_residual"] -
                                   sequence[position-1]["standardized_residual"])
                if moving_range > moving_range_threshold:
                    moving_windows.append((position-1, position, "mixed"))
            for start, stop, direction, first_detection in _merge_windows(moving_windows):
                evidence = sequence[start:stop+1]
                ranges = [abs(evidence[i]["standardized_residual"] -
                              evidence[i-1]["standardized_residual"])
                          for i in range(1, len(evidence))]
                peak_range = max(ranges)
                output.append(dict(
                    id=f"anomaly-pattern-{len(output)+1}", dataset=dataset,
                    kind="variation_shift", rule="moving_range",
                    description=(f"Possible short-term variation increase: an adjacent "
                                 f"standardized-residual moving range reached {peak_range:.3g}, "
                                 f"above the configured threshold {moving_range_threshold:g}. "
                                 "This concerns adjacent residual spread, not process location "
                                 "or proof that the full distribution changed."),
                    interval=_interval(evidence), sample_count=len(evidence),
                    triggering_samples=[item["index"] for item in evidence],
                    detection_index=sequence[first_detection]["index"],
                    peak_standardized_residual=max(
                        abs(item["standardized_residual"]) for item in evidence),
                    peak_moving_range=peak_range,
                    detector_threshold=moving_range_threshold,
                    direction=direction,
                    evidence_refs=[item["id"] for item in evidence]))
    return output
