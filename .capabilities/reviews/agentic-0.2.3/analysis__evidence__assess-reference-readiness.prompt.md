# CapabilityKit Agent Task



Mode: review



## Instructions

Review whether the current implementation satisfies the capability described below.
First summarize the capability intent in your own words.
For each acceptance criterion, mark it as covered, partial, uncovered, or uncertain.
Provide concrete file-path evidence for covered or partially covered criteria.
Do not mark the capability verified solely from prose; report remaining gaps explicitly.

## Capability

Capability: Explain whether the reference deserves confidence (analysis/evidence/assess-reference-readiness)
Status: implemented
Area: analysis

Readiness diagnostics report supported, caution, or not_assessed based on the training pattern and calibration evidence.

## Intent

Expose weak expectations even when no anomaly is detected.

## Acceptance Criteria

1. Repeating seasonal structure with stable calibration can yield supported readiness.
2. Unstable declared seasonality or a drifting calibration center yields caution without making an otherwise completed run fail.
3. Insufficient calibration support yields not_assessed, including when the run otherwise completes.
4. Later evaluation changes do not rewrite the segment's training-and-calibration readiness assessment.

## Guidance

- Readiness does not prove real-world effectiveness and is not an automatic action-policy gate.

## Inputs

None.

## Outputs

None.

## Dependencies

- analysis/evidence/calibrate-departures

## Implementation References

- src/anomalyzer/readiness.py
- src/anomalyzer/recipes.py
- tests/test_readiness.py

## Automated Verification

- Support repeated seasonality and preserve readiness under later changes. (supported-reference)
   Command: `python -m pytest -q tests/test_readiness.py::test_repeating_season_and_trend_support_reference`
- Warn on unstable seasonality even when no findings occur. (weak-season)
   Command: `python -m pytest -q tests/test_readiness.py::test_unstable_declared_season_warns_without_calling_series_inapplicable tests/test_readiness.py::test_documented_random_example_has_no_findings_but_warns_on_reference`
- Warn when residual calibration drifts despite a repeated training season. (calibration-drift)
   Command: `python -m pytest -q tests/test_readiness.py::test_calibration_drift_warns_even_when_training_season_repeats`
- Distinguish uncalibrated history and too few calibration samples. (not-assessed)
   Command: `python -m pytest -q tests/test_readiness.py::test_readiness_is_not_assessed_without_calibrated_evaluation tests/test_readiness.py::test_short_calibration_is_not_assessed_even_when_analysis_completes`

## Manual Verification

- Read readiness reasons alongside findings; a lack of findings alone does not establish a trustworthy reference.

## Declared Verification Gaps

None.

## Referenced Implementation Content

- src/anomalyzer/readiness.py
- src/anomalyzer/recipes.py
- tests/test_readiness.py

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