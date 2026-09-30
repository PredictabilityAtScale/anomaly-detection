# CapabilityKit Agent Task



Mode: review



## Instructions

Review whether the current implementation satisfies the capability described below.
First summarize the capability intent in your own words.
For each acceptance criterion, mark it as covered, partial, uncovered, or uncertain.
Provide concrete file-path evidence for covered or partially covered criteria.
Do not mark the capability verified solely from prose; report remaining gaps explicitly.

## Capability

Capability: Detect point departures and group adjacent episodes (analysis/detection/report-point-anomaly-episodes)
Status: implemented
Area: analysis

Calibrated point-threshold crossings become inspectable observations, with adjacent crossings grouped into episodes.

## Intent

Locate unusual values and keep isolated events distinct from sustained runs.

## Acceptance Criteria

1. A sufficiently extreme calibrated sample records a point trigger and the expectation it departed from.
2. Repeated runs of the same fixed request preserve numerical evidence; future samples do not change earlier scoring for declared settings.
3. Adjacent point departures form a consecutive-run pattern with the contributing sample positions.
4. Separated point departures remain separate episodes, and positional episode intervals use integer coordinates.

## Guidance

- Detection is a numerical departure from the selected expectation, not a claim about cause or business impact.

## Inputs

None.

## Outputs

None.

## Dependencies

- analysis/evidence/calibrate-departures

## Implementation References

- src/anomalyzer/recipes.py
- src/anomalyzer/evidence.py
- tests/test_analysis.py

## Automated Verification

- Detect an injected spike and retain deterministic earlier numerical evidence. (point-evidence)
   Command: `python -m pytest -q tests/test_analysis.py::test_spike_and_no_lookahead`
- Describe adjacent point triggers and their contributing positions. (adjacent-run)
   Command: `python -m pytest -q tests/test_analysis.py::test_anomaly_stream_detects_consecutive_run`
- Keep separated anomalies from becoming a consecutive-run pattern. (isolated-events)
   Command: `python -m pytest -q tests/test_analysis.py::test_isolated_anomalies_do_not_form_second_order_pattern`
- Use integer intervals for position-only episode evidence. (positional-episodes)
   Command: `python -m pytest -q tests/test_analysis.py::test_positional_episode_uses_integer_interval`

## Manual Verification

- Inspect observations and triggering_samples for examples/spike.json and distinguish episode grouping from pattern findings.

## Declared Verification Gaps

None.

## Referenced Implementation Content

- src/anomalyzer/recipes.py
- src/anomalyzer/evidence.py
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