# CapabilityKit Agent Task



Mode: review



## Instructions

Review whether the current implementation satisfies the capability described below.
First summarize the capability intent in your own words.
For each acceptance criterion, mark it as covered, partial, uncovered, or uncertain.
Provide concrete file-path evidence for covered or partially covered criteria.
Do not mark the capability verified solely from prose; report remaining gaps explicitly.

## Capability

Capability: Accept numeric series and explicit analysis requests (data/inputs/accept-analysis-requests)
Status: implemented
Area: data

Callers can submit ordered numeric values or versioned requests containing datasets, settings, context, and declared relationships.

## Intent

Make the accepted data contract clear before any conclusions are drawn from the numbers.

## Acceptance Criteria

1. Ordered value lists work with separate settings, while schema 1.0 requests describe one dataset.
2. Schema 1.1 datasets declare a nonempty entity scope and support explicit relationships between named datasets.
3. Unknown settings, unsupported recipes, nonfinite values, booleans, and numeric strings are rejected.
4. Published schema 1.0 and 1.1 request and result schemas match the public Python contracts.

## Guidance

- Null observations represent missing values, never zero. Limits apply to the request as a whole.
- Describe current supported behavior; historical plans do not add accepted inputs.

## Inputs

None.

## Outputs

None.

## Dependencies

None.

## Implementation References

- src/anomalyzer/contracts.py
- src/anomalyzer/recipes.py
- tests/test_analysis.py
- tests/test_agentic.py
- schemas/request.schema.json
- schemas/result.schema.json
- schemas/request-1.1.schema.json
- schemas/result-1.1.schema.json

## Automated Verification

- Analyze a bare list and validate a canonical request and result. (input-forms)
   Command: `python -m pytest -q tests/test_analysis.py::test_bare_values_with_separate_settings tests/test_analysis.py::test_constant_and_schema`
- Reject schema 1.1 datasets without entity scope. (explicit-scope)
   Command: `python -m pytest -q tests/test_agentic.py::test_schema_11_requires_explicit_entity_scope`
- Reject unsupported settings and nonnumeric or nonfinite observations. (invalid-inputs)
   Command: `python -m pytest -q tests/test_analysis.py::test_invalid_config tests/test_analysis.py::test_invalid_values`
- Compare all four checked-in schemas with their public contracts. (published-schemas)
   Command: `python -m pytest -q tests/test_analysis.py::test_checked_in_schemas tests/test_agentic.py::test_v11_checked_in_schemas_exist`

## Manual Verification

- Review the input examples in README.md and confirm they describe the two supported schema versions and the four-dataset/four-relationship limit.

## Declared Verification Gaps

None.

## Referenced Implementation Content

- src/anomalyzer/contracts.py
- src/anomalyzer/recipes.py
- tests/test_analysis.py
- tests/test_agentic.py
- schemas/request.schema.json
- schemas/result.schema.json
- schemas/request-1.1.schema.json
- schemas/result-1.1.schema.json

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