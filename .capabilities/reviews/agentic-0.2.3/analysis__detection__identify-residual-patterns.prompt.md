# CapabilityKit Agent Task



Mode: review



## Instructions

Review whether the current implementation satisfies the capability described below.
First summarize the capability intent in your own words.
For each acceptance criterion, mark it as covered, partial, uncovered, or uncertain.
Provide concrete file-path evidence for covered or partially covered criteria.
Do not mark the capability verified solely from prose; report remaining gaps explicitly.

## Capability

Capability: Identify sustained shifts and other residual patterns (analysis/detection/identify-residual-patterns)
Status: implemented
Area: analysis

Residual rules identify location shifts, trends, oscillation, mixture patterns, and short-term variation beyond isolated point departures.

## Intent

Find accumulating changes and explain which numerical pattern was detected.

## Acceptance Criteria

1. Nelson location rules and CUSUM can identify a sustained residual location shift without any point-threshold crossing.
2. CUSUM reports the first detection position, direction, accumulated score, and configured threshold.
3. Trend, oscillation, and mixture findings retain their specific pattern meanings.
4. Moving-range findings identify variation changes separately from location changes.

## Guidance

- Pattern findings may overlap and are not independent confirmations.
- A residual location shift does not establish a change in the full distribution.

## Inputs

None.

## Outputs

None.

## Dependencies

- analysis/evidence/calibrate-departures

## Implementation References

- src/anomalyzer/evidence.py
- src/anomalyzer/recipes.py
- tests/test_analysis.py

## Automated Verification

- Find moderate increases and decreases without point anomalies. (location-shift)
   Command: `python -m pytest -q tests/test_analysis.py::test_nelson_patterns_describe_location_shift_without_point_anomaly`
- Detect a known CUSUM accumulation at the expected position. (accumulating-change)
   Command: `python -m pytest -q tests/test_analysis.py::test_cusum_detects_accumulated_moderate_location_shift`
- Distinguish residual trend, oscillation, and mixture rules. (diagnostic-patterns)
   Command: `python -m pytest -q tests/test_analysis.py::test_nelson_diagnostics_have_specific_semantics`
- Describe a moving-range increase as variation rather than location. (variation)
   Command: `python -m pytest -q tests/test_analysis.py::test_moving_range_detects_short_term_variation_increase`

## Manual Verification

- Compare examples/location_shift_up.json with its point episodes and pattern findings, allowing for overlapping residual rules.

## Declared Verification Gaps

None.

## Referenced Implementation Content

- src/anomalyzer/evidence.py
- src/anomalyzer/recipes.py
- tests/test_analysis.py

## Required Review Output

Return a concise review with this JSON shape:

```json
{
  "source": "coding-agent",
  "intent_summary": "string",
  "criteria": [
    {
      "criterion": "string",
      "status": "covered | partial | uncovered | uncertain",
      "evidence": ["path:line"],
      "notes": "short gap or uncertainty; omit for covered criteria"
    }
  ],
  "verification_evidence": ["successful command or manual check"],
  "remaining_gaps": ["string"],
  "done": false
}
```

Act as a coding agent reviewing the repository, not as a text matcher.
Inspect the referenced source, tests, and related code paths directly before deciding whether each criterion is implemented.
Use the deterministic report only as a starting evidence bundle; do not trust it as proof.
Set `done` to true only when every criterion is covered with concrete file-path evidence. Residual verification gaps may remain when the implementation behavior is covered but confidence is not complete.
Record successful test commands, builds, and manual checks in `verification_evidence`. Record only unresolved risks or missing checks in `remaining_gaps`.
Use `partial` when only part of a behavior is implemented, `uncovered` when the code does not implement it, and `uncertain` only when the repository evidence is insufficient to decide.
Do not change capability status; this review is evidence for a human or policy-controlled acceptance step.
Return JSON only. Keep intent_summary to one sentence. Omit notes for covered criteria; give a short reason for partial, uncovered, or uncertain criteria.
Review only this capability. Inspect every implementation reference, following related code only as needed to decide the acceptance criteria.
Use the smallest concrete evidence set that supports each decision. Stop once every criterion has a status and sufficient evidence.
Search large reference files for relevant symbols and read focused sections instead of dumping entire files. Batch independent evidence reads.
Run focused verification only when needed to resolve uncertainty. Do not run repository-wide reviews, repeat already supplied successful checks, or fix code.
If a decision requires a long investigation or unavailable verification, report uncertain and the missing evidence instead of expanding the review.