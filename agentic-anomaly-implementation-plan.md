# Anomalyzer agentic evidence implementation plan

## 1. Objective

Build Anomalyzer into a deterministic numerical evidence layer for agentic
applications.

The implementation should:

- produce useful evidence from the earliest viable observations, including the
  third or fourth sample;
- strengthen that evidence as more history becomes available;
- add seasonality only when the data supports it;
- distinguish exact calculations from model-conditional conclusions and
  real-world confirmation;
- analyze several explicitly related datasets without hiding alignment, unit,
  or lag assumptions;
- return structured evidence that an agent can investigate without asking the
  language model to perform the statistical analysis itself; and
- demonstrate the design with a small set of convincing cross-dataset examples.

The first release is an embedded Python and JSON component. An MCP adapter is a
distribution layer over the same contracts, not a separate implementation.

## 2. Product contract

### 2.1 Core promise

> Anomalyzer turns short numerical histories and declared relationships into
> inspectable, time-correct evidence for agents. It starts with limited early
> evidence, improves as observations accumulate, and never presents more
> certainty than its inputs and assumptions support.

### 2.2 Meaning of "small data"

Small data means that the application should receive useful output before a
conventional training and calibration window exists.

- One sample establishes an observation, not a comparison.
- Two samples establish an exact change and direction.
- Three or four samples can establish descriptive departures from a simple
  reference, or exact violations of caller-supplied rules.
- Additional samples support progressively better estimates of local level,
  variation, trend, and eventually seasonality.
- A short history never silently acquires statistical calibration it does not
  have.

### 2.3 Certainty contract

Absolute certainty that a real-world event is an anomaly is not available from
the numbers alone. The API must instead state what kind of claim is justified.

Keep these dimensions separate:

1. **Calculation certainty** — exact arithmetic such as change, ratio,
   residual, or a rule boundary crossing.
2. **Evidence maturity** — how much history supports the reference model.
3. **Evidence strength** — magnitude under the declared reference and its
   documented semantics; never an invented probability.
4. **Claim scope** — what the result establishes and does not establish.
5. **Review state** — whether a person or external system has confirmed an
   expected event, incident, or new regime.

The public result must not expose a context-free `anomaly: true`. Early and
provisional statistical evidence cannot create an anomaly episode or authorize
an action. An explicit deterministic rule can report `criterion_met: true`, but
must say that it proves a rule violation rather than a real-world cause.

Recommended assessment vocabulary:

| Field | Initial values |
|---|---|
| `classification` | `observation`, `change`, `departure_candidate`, `supported_departure`, `criterion_violation` |
| `maturity` | `observation_only`, `early`, `provisional`, `calibrated` |
| `basis` | `descriptive`, `explicit_rule`, `statistical_baseline`, `declared_relationship` |
| `action_eligible` | Boolean set by deterministic policy, never inferred from prose |
| `review_state` | `unreviewed`, `expected_change`, `confirmed_incident`, `new_regime` |

Every assessment must include:

- the comparison population and sample count;
- the baseline or rule used;
- assumptions required for the claim;
- a plain statement of what is established; and
- a plain statement of what is not established.

## 3. Scope and non-goals

### 3.1 In scope

- Backward-compatible single-series analysis.
- Descriptive early evidence before statistical calibration.
- Multiple named datasets in one request.
- Exact timestamp alignment at a shared fixed cadence.
- Explicit relationship definitions across two to four datasets.
- Derived relationship series with complete lineage.
- Ratio, difference, normalized residual, lagged response, and bounded joint
  condition primitives.
- Causal evaluation using only information available at each observation.
- Relationship-level evidence, observations, cases, and chronological replay.
- Three or four checked-in cross-dataset demonstrations.
- A thin agent adapter after the core contracts are stable.

### 3.2 Deferred

- Automatic relationship or causal discovery.
- Arbitrary joins and semantic mapping.
- Interpolation, resampling, or implicit unit conversion.
- Multiple unrelated cadences in one relationship.
- High-dimensional black-box multivariate models.
- Learned universal confidence percentages.
- LLM-generated mathematical conclusions.
- Autonomous production actions.
- A hosted ingestion, scheduling, or dashboard platform.

## 4. Architectural direction

### 4.1 Preserve the single-series engine

The existing seasonal residual implementation remains one detector. Refactor it
so it operates on one prepared dataset rather than reaching through a request
that is structurally limited to `datasets[0]`.

Target internal boundary:

```python
analyze_dataset(
    dataset: Dataset,
    settings: Settings,
    context: Context,
    budget: RuntimeBudget,
) -> DatasetResult
```

The current public `analyze(...) -> Result` remains compatible for schema 1.0
single-dataset requests.

### 4.2 Add an orchestration layer

Introduce an orchestrator that:

1. validates all datasets and relationship declarations;
2. prepares each dataset independently;
3. aligns only the datasets required by each relationship;
4. analyzes source datasets when requested;
5. constructs derived relationship series with lineage;
6. analyzes each derived series with the same causal evidence machinery;
7. composes related evidence into cases without treating correlated checks as
   independent confirmation; and
8. returns a single deterministic result and fingerprint.

Suggested modules:

```text
src/anomalyzer/
  contracts.py        existing contracts plus versioned additions
  recipes.py          dataset-scoped detector recipes
  early.py            early descriptive evidence
  alignment.py        exact cadence, timestamp, entity, and completeness checks
  relationships.py    derived-series construction and lineage
  cases.py            evidence composition without causal claims
  orchestrator.py     multi-dataset request execution
  policy.py           explicit action-eligibility evaluation
  evaluation/
    relationships.py  chronological relationship replay summaries
```

Do not split the package into many subpackages until these boundaries are proven
useful in code. The important first refactor is eliminating hidden dependence on
the first dataset.

### 4.3 Derived relationship series as the initial cross-data mechanism

Whenever possible, reduce an explicit relationship to a derived series, then
apply the existing evidence pipeline to that series.

Examples:

```text
conversion[t] = orders[t] / visits[t]
margin[t] = revenue[t] - cost[t]
response_residual[t] = orders[t] - beta * leads[t-lag]
unit_cost[t] = infrastructure_cost[t] / successful_requests[t]
```

Each derived observation must retain:

- source dataset IDs;
- source sample indexes and timestamps;
- exact formula and parameters;
- unit derivation;
- alignment rule and lag;
- missing or incomplete inputs;
- whether any coefficient was supplied or estimated; and
- the latest source cutoff used.

This makes a relationship result inspectable and lets prefix-invariance tests
prove that future data did not affect earlier evidence.

## 5. Contract evolution

### 5.1 Compatibility strategy

- Continue accepting schema `1.0` exactly as today.
- Introduce schema `1.1` for multiple datasets, relationships, assessments, and
  cases.
- Keep `analyze(list, settings)` as the convenient single-series API.
- Generate and check in separate `1.0` and `1.1` schemas during the transition.
- Do not silently reinterpret a 1.0 request as a multi-dataset request.

### 5.2 Proposed request additions

```json
{
  "schema_version": "1.1",
  "task": "analyze",
  "datasets": [
    {"id": "visits", "timestamps": [], "values": [], "frequency": "1d", "units": "visits"},
    {"id": "orders", "timestamps": [], "values": [], "frequency": "1d", "units": "orders"}
  ],
  "relationships": [
    {
      "id": "conversion",
      "kind": "ratio",
      "numerator": "orders",
      "denominator": "visits",
      "alignment": "exact",
      "units": "orders_per_visit",
      "zero_denominator": "inapplicable"
    }
  ],
  "config": {},
  "context": {}
}
```

Initial relationship kinds:

- `ratio`
- `difference`
- `normalized_residual`
- `lagged_response`
- `joint_condition`

Require explicit fields for each kind. Reject ambiguous or unused fields.

### 5.3 Proposed result additions

```json
{
  "dataset_results": [],
  "relationship_results": [],
  "cases": [],
  "limitations": []
}
```

A `relationship_result` contains its definition, lineage, applicability,
data-quality state, derived-series evidence, and assessments.

A `case` is a deterministic grouping record, not an LLM explanation. It contains:

- stable case and revision IDs;
- contributing dataset and relationship IDs;
- event time, detection time, and source-availability cutoff;
- supporting, conflicting, and unavailable evidence;
- evidence references;
- assessment maturity and action eligibility;
- business impact set to `unresolved` unless supplied externally;
- suggested investigation questions; and
- explicit non-claims, especially that correlation does not establish cause.

## 6. Implementation sequence

### Milestone 0 — Freeze semantics and fixtures

Deliverables:

- Add enums/models for assessment classification, maturity, basis, and review
  state.
- Add contract examples showing early, provisional, calibrated, and explicit
  rule evidence.
- Record the current 1.0 schemas and representative result fixtures.
- Add a terminology document or README section prohibiting unqualified
  `certainty`, `confidence`, and `anomaly` claims.

Exit gate:

- Every public state has a single documented meaning.
- Existing tests and schemas remain unchanged.
- No field implies a probability unless a future method actually calibrates one.

### Milestone 1 — Extract the dataset-scoped engine

Deliverables:

- Refactor preparation and recipe execution to accept one `Dataset` directly.
- Add a shared runtime budget rather than creating an independent full budget
  per dataset.
- Preserve current single-series output byte-for-byte except for runtime and
  run IDs.
- Add golden fixtures for ordinary, spike, shift, incomplete-period, reset, and
  multi-resolution requests.

Exit gate:

- All existing tests pass.
- Golden single-series evidence is unchanged.
- No implementation path depends on `request.datasets[0]` outside the 1.0
  compatibility adapter.

### Milestone 2 — Early evidence before seasonality

Deliverables:

- Add descriptive evidence beginning with the second observation.
- At samples three and four, report prior median/range comparisons, absolute and
  relative change, and direction without claiming calibration.
- Support optional explicit acceptable ranges or maximum-change rules that can
  produce a precise `criterion_violation` immediately.
- Keep early statistical candidates non-triggering.
- Allow the seasonal/trend detector to take over progressively without deleting
  the earlier evidence.

Recommended behavior:

| Available samples | Output |
|---|---|
| 1 | `observation_only`; no reference |
| 2 | exact change from prior observation |
| 3–4 | `departure_candidate` under a named simple reference; no probability and no episode |
| sufficient calibration | `supported_departure` when a calibrated criterion is met |
| any count with explicit rule | `criterion_violation` when the exact rule is crossed |

Exit gate:

- Short-series tests prove useful evidence exists at samples two through four.
- Appending future samples cannot change earlier early-evidence records.
- No early or provisional record creates an anomaly episode.
- Every record declares its assumptions and non-claims.

### Milestone 3 — Multiple independent datasets

Deliverables:

- Accept two to four named datasets in schema 1.1.
- Produce one `dataset_result` per dataset.
- Use deterministic ordering and canonical fingerprinting independent of input
  dataset order.
- Report partial results when one dataset is invalid or inapplicable, without
  treating unavailable data as normal.
- Enforce unique dataset IDs and explicit entity metadata.

Exit gate:

- Analyzing N datasets together produces the same numerical evidence as N
  independent single-dataset calls.
- Runtime and point budgets apply to the complete request.
- Dataset failures and incomplete periods remain isolated and visible.

### Milestone 4 — Relationship primitives

Implement one primitive at a time in this order:

1. `ratio`
2. `difference`
3. `normalized_residual`
4. `lagged_response`
5. `joint_condition`

For the first release:

- timestamps must match exactly after UTC normalization;
- related datasets must declare the same cadence;
- differences require compatible units;
- ratios require explicit zero-denominator behavior;
- lags are explicit integer sample counts;
- learned coefficients use only a declared training prefix and are frozen
  before evaluation;
- missing or incomplete source values create unavailable relationship evidence,
  never zero; and
- relationship analysis can emit early evidence before it is calibrated.

Exit gate:

- Every derived value can be traced to exact source observations.
- Unit, alignment, lag, division-by-zero, and incomplete-period errors have
  specific contract responses.
- Prefix-invariance holds for derived values, learned parameters, and evidence.
- A relationship can surface a departure while both constituent series remain
  individually non-triggering.

### Milestone 5 — Case composition and policy boundary

Deliverables:

- Group temporally overlapping dataset and relationship evidence into a case.
- Preserve supporting, conflicting, missing, and correlated evidence separately.
- Add an explicit policy input for action eligibility.
- Separate `criterion_met`, `action_eligible`, `notification_eligible`, and
  external action execution.
- Add chronological replay summaries for first observation, first candidate,
  first supported departure, and first policy-eligible action.

Exit gate:

- A case never upgrades maturity merely because several correlated derived
  signals agree.
- A case never asserts a cause.
- Policy output is reproducible without an LLM.
- Replay uses the same update semantics as live analysis.

### Milestone 6 — Agent adapter

Deliverables:

- Add Python functions with strict Pydantic inputs and outputs:
  `analyze_series`, `analyze_relationships`, `get_case`, and `replay_policy`.
- Expose the same functions through a local stdio MCP server.
- Add Streamable HTTP only after authentication and tenant boundaries are
  specified.
- Return structured content first; prose summaries are optional and derived
  from structured fields.
- Keep the adapter read-only. Production actions remain outside Anomalyzer.

Exit gate:

- Direct Python, CLI JSON, and MCP calls return the same semantic result.
- Tool descriptions state when to use each tool and what it cannot establish.
- Agent examples repeat material assumptions and limitations rather than hiding
  them in tool metadata.

## 7. Future phase — interview-authored circumstance memory

This phase is intentionally additive. The numerical evidence layer remains
deterministic and does not acquire conversational state, business meaning, or
LLM-authored statistical conclusions. The memory system consumes stable
assessment, lineage, relationship, case, and replay contracts produced by the
earlier milestones.

### 7.1 Product role and boundary

The LLM acts as an interviewer and compiler, not as the detector or policy
engine. It should help a person generalize from actual events by:

1. anchoring the discussion to an entity and approximate event time;
2. retrieving the relevant Anomalyzer evidence and showing the numerical
   timeline rather than asking the person to remember exact values;
3. asking what normally leads or follows, the acceptable lag range, what
   absence becomes meaningful, and which exceptions apply;
4. asking what made the event interesting, urgent, or misleading;
5. separating observed evidence, participant statements, external business
   context, and LLM proposals;
6. compiling a structured circumstance draft;
7. replaying the draft against the source event, ordinary periods, near misses,
   incomplete-data periods, and known exceptions; and
8. requiring explicit review before activation.

The LLM may retrieve evidence, propose selectors and questions, summarize replay
results, and draft investigation guidance. It must not invent numerical facts,
upgrade evidence maturity, infer causality from correlation, or make a draft
action-eligible without deterministic policy and review.

### 7.2 Memory layers

Keep five kinds of memory separate:

1. **Evidence memory** — an immutable ledger of assessments, observations,
   relationship values, lineage, data-quality states, event times, detection
   times, and source-availability cutoffs. Evidence is appended, never rewritten
   by later human interpretation.
2. **Circumstance memory** — versioned, reviewed definitions of situations
   people consider interesting or urgent. A definition references evidence
   selectors and relationship IDs rather than copying or modifying evidence.
3. **Working memory** — active temporal watches such as "a leading signal was
   observed; wait two to four days for the expected response." It contains
   deadlines, gates, expected lagging signals, and expiry conditions.
4. **Case memory** — immutable case revisions showing supporting, conflicting,
   correlated, missing, and unavailable evidence together with the policy
   decision made at that revision.
5. **Outcome memory** — external review such as `expected_change`,
   `confirmed_incident`, `new_regime`, `false_interpretation`, or `unresolved`,
   plus externally established cause, impact, action, and outcome.

Outcome memory may propose a new circumstance revision. It must not silently
relabel historical evidence, change thresholds, refit coefficients, or rewrite
an active definition.

### 7.3 Circumstance model

A circumstance is a versioned temporal graph:

- nodes select named assessments or externally supplied events;
- edges express `precedes`, `expected_within`, `absent_after`,
  `concurrent_with`, `correlated_with`, `anti_correlated_with`, `gates`, or
  `conflicts_with`;
- lag bounds are explicit durations or sample counts;
- grouping keys declare the entity scope in which events may be related;
- absence becomes evaluable only after its deadline;
- exceptions and termination events are explicit;
- interest, urgency, notification, and action remain separate decisions; and
- correlation edges always carry a non-claim that association does not establish
  cause.

Illustrative human-authored form:

```yaml
title: Qualified-lead response fails to arrive
id: lead-response-failure
version: 1
status: draft

scope:
  entity_type: sales_region
  group_by: [sales_region, lead_source]
  exclusions:
    - lead_source: partner

signals:
  lead_increase:
    target: qualified_leads
    classification: [criterion_violation, supported_departure]
    direction: increase
  order_response:
    target: lead_response
    classification: [criterion_violation, supported_departure]

temporal_relationship:
  type: expected_within
  from: lead_increase
  to: order_response
  minimum_lag: 2d
  maximum_lag: 4d
  missing_after_deadline: interesting

gates:
  - target: order_ingestion_completeness
    condition: {gte: 0.99}
    otherwise: insufficient_evidence

urgency:
  when:
    expected_response_missing: true
    pipeline_value: {gte: 500000}
    minimum_evidence_maturity: calibrated
  result: urgent

non_claims:
  - Lead changes are not proven to cause order changes.
  - A missing response does not identify the responsible system.
```

The canonical contract must also retain `derived_from` case IDs, interview IDs,
open questions, investigation guidance, owner, reviewer, effective interval,
superseded version, and deterministic policy references.

### 7.4 Authorship provenance

Every authored field that can affect matching or urgency must retain provenance:

```json
{
  "field": "temporal_relationship.maximum_lag",
  "value": "4d",
  "source_type": "participant_statement",
  "source_ref": "interview:answer-17",
  "supported_by_evidence": ["case:west-region-2026-02-12"],
  "review_state": "approved",
  "approved_by": "sales-operations-owner"
}
```

Initial source types:

- `observed_evidence`
- `participant_statement`
- `external_business_context`
- `llm_proposal`
- `historical_replay`
- `reviewer_decision`

An `llm_proposal` is never treated as an observed fact or reviewed policy. If a
value has no source, it remains an explicit open question rather than receiving a
plausible default.

### 7.5 Standards and language influences

Borrow proven semantics without making any external language the core contract:

| Source | Reuse |
|---|---|
| CloudEvents | Portable event envelope fields such as ID, source, type, subject, event time, and data schema |
| OpenTelemetry | Common telemetry/entity naming and event, log, metric, and trace correlation fields |
| Sigma correlations | Human-readable rule metadata, named detections, grouping, time spans, ordered correlations, severity, and known false positives |
| EQL | Ordered sequences, shared entity keys, maximum spans, missing events, repetition, and termination events |
| Esper EPL, Flink CEP, and Drools CEP | Runtime temporal-matching semantics and possible future compilation targets |
| STIX 2.1 | Versioned knowledge objects, relationships, sightings, external references, and review metadata |
| W3C PROV-O and OWL-Time | Provenance and temporal vocabulary without requiring RDF in the core runtime |
| DMN/FEEL | Auditable business decision tables for interest and urgency |
| OPA/Rego | Optional developer-controlled policy-as-code adapter |

The Anomalyzer circumstance schema remains domain-neutral and intentionally
smaller than these source systems. External adapters must preserve the native
evidence certainty and non-claim semantics.

### 7.6 Canonical files and storage

Use each file type for one clear purpose:

| Artifact | Canonical form | Purpose |
|---|---|---|
| Analysis requests and results | JSON plus checked-in JSON Schema | Machine API, CLI, Python, and MCP interchange |
| Circumstance definitions | YAML for review; canonicalized JSON for hashing and execution | Human-authored, version-controlled situation definitions |
| Evidence and case export | JSON Lines using a CloudEvents-compatible envelope | Append-only streaming, audit, and bulk transfer |
| Local durable memory | SQLite | Embedded indexes, active watches, case revisions, outcomes, and transactional updates |
| Small demonstration inputs | CSV plus canonical JSON | Inspectable examples; CSV is not a semantic authoring format |
| Policy interchange | Native JSON first; optional DMN XML or Rego adapters | Deterministic interest, urgency, notification, and action policy |
| Provenance interchange | Native JSON first; optional JSON-LD/PROV-O export | Graph integration without imposing RDF on embedded users |

YAML is an authoring view, not the runtime source of truth. Normalize it to the
strict JSON contract, reject unknown fields, preserve the reviewed source, and
hash the canonical JSON. Do not store active watches or mutable case state in
YAML files.

### 7.7 Interview and definition lifecycle

Use two independent maturity axes:

```text
circumstance: captured -> evidence_bound -> draft -> replayed -> reviewed -> active -> revised/retired
evidence:      observation_only -> early -> provisional -> calibrated
```

An active circumstance may consume early evidence without upgrading it. A
calibrated assessment does not make an unreviewed circumstance definition safe.

Recommended future agent functions:

- `start_circumstance_interview`
- `retrieve_event_evidence`
- `record_interview_answer`
- `propose_circumstance`
- `replay_circumstance`
- `revise_circumstance`
- `approve_circumstance`
- `record_case_outcome`

These functions belong above the read-only numerical adapter. Approval and
activation are explicit state changes with identified reviewers; numerical
analysis remains read-only.

### 7.8 Compatibility with the current evidence approach

The current design already provides the required lower-level seams:

- assessments separate classification, maturity, basis, review state,
  assumptions, established claims, and non-claims;
- relationship results preserve definitions and source lineage;
- cases carry revisions, evidence references, event/detection/source-cutoff
  times, correlated evidence groups, investigation questions, and non-claims;
- deterministic policy can be replayed without recomputing evidence; and
- relationship definitions are declared rather than inferred as causes.

Preserve those boundaries. The future memory layer should be additive and
reference stable IDs. Two existing placeholders require real implementations in
that phase: source-availability cutoff must use actual arrival information rather
than assuming event-time availability, and the minimal Boolean action policy must
grow into reviewed circumstance-specific interest and urgency decisions.

### 7.9 Validation gates for the memory phase

- A circumstance can be traced to the actual cases, interview answers, evidence,
  replay results, and reviewers that produced it.
- A field proposed by an LLM cannot become active without review.
- Replay uses the same temporal and data-availability semantics as live matching.
- Missing expected events are evaluated only after an explicit deadline.
- Unavailable gated evidence produces `insufficient_evidence`, not a successful
  match or a healthy result.
- Updating a circumstance creates a new version and does not change historical
  case revisions.
- Semantic retrieval can suggest candidate definitions, but deterministic
  selectors and temporal rules decide whether they match.
- Correlated evidence never becomes causal proof or multiple independent votes.
- Urgency depends on reviewed policy and externally supplied impact, not on an
  LLM adjective or a context-free anomaly score.
- At least one actual event, one ordinary control period, one near miss, one
  incomplete-data period, and one reviewed exception are shown before activation.

## 8. Cross-dataset demonstration suite

Each demonstration must contain:

- small CSV and canonical JSON inputs;
- a runnable example script;
- expected JSON output checked by tests;
- a short human-readable walkthrough;
- independent single-series results for comparison;
- the relationship result and its lineage;
- an agent investigation prompt and a bounded expected conclusion; and
- an explicit statement of what the evidence does not prove.

### Example 1 — Conversion relationship breaks while volumes look ordinary

Datasets:

- `qualified_visits`
- `orders`

Relationship:

```text
conversion = orders / qualified_visits
```

Story:

Both volumes remain within their broad individual histories, but their ratio
drops sharply. The example demonstrates why two individually ordinary series
can contain an unusual relationship.

Agent investigation:

- inspect checkout errors, traffic mix, and experiment changes;
- do not claim checkout failure solely from the relationship evidence.

Primary primitive: `ratio`.

### Example 2 — Expected lagged response fails to arrive

Datasets:

- `qualified_leads`
- `orders`

Relationship:

```text
expected_orders[t] = beta * qualified_leads[t-2]
response_residual[t] = orders[t] - expected_orders[t]
```

Story:

Leads rise, but the historically expected order response does not arrive two
periods later. Neither the lead increase nor current order level alone is the
important signal.

The initial example uses an explicit reviewed lag and coefficient. A later
variant may estimate `beta` from a frozen training prefix.

Agent investigation:

- inspect lead-source mix, sales-processing delay, and order ingestion;
- do not describe the lag relationship as causal proof.

Primary primitive: `lagged_response`.

### Example 3 — Unit economics diverge before either total is extreme

Datasets:

- `infrastructure_cost`
- `successful_requests`

Relationship:

```text
unit_cost = infrastructure_cost / successful_requests
```

Story:

Infrastructure cost rises moderately while successful requests fall moderately.
Each individual movement is plausible; cost per successful request departs much
more strongly and merits a cheap investigation.

Agent investigation:

- inspect retries, regional routing, and deployment changes;
- keep financial materiality unresolved unless pricing and volume context are
  supplied.

Primary primitive: `ratio`, followed by an explicit policy threshold variant.

### Example 4 — Apparent usage collapse is actually insufficient evidence

Datasets:

- `usage_events`
- `ingestion_completeness`
- optionally `service_availability`

Relationship or joint condition:

```text
usage_drop AND ingestion_complete
```

Story:

Usage appears to fall, but the ingestion source is late or incomplete. The
correct result is not “healthy” or “anomaly”; it is `insufficient_evidence` with
a data-quality investigation suggested. A completed-source variant shows the
same usage drop becoming eligible for relationship analysis.

Agent investigation:

- check ingestion before contacting the customer;
- do not convert missing observations to zero.

Primary primitive: `joint_condition` plus data-quality gating.

This example is as important as a successful detection because it demonstrates
that the system resists false certainty.

## 9. Test and evaluation strategy

### 9.1 Invariants

Add tests for:

- prefix invariance: appending future data does not change prior evidence;
- dataset-order invariance;
- exact source lineage for every derived point;
- deterministic fingerprints and outputs;
- no trigger from early or provisional statistical evidence;
- explicit rules labeled as rule violations, not real-world truth;
- no implicit zero for missing or incomplete values;
- no implicit interpolation, resampling, or unit conversion;
- no cross-boundary seasonal or lag reference after a manual reset;
- correlated evidence not counted as independent votes; and
- partial failures preserved without suppressing valid sibling results.

### 9.2 Comparative evaluation

For every cross-dataset example, report:

- whether each source series triggered independently;
- when relationship evidence first became available;
- when it became provisional or calibrated;
- when any explicit rule was crossed;
- when policy first allowed investigation;
- additional investigations created during ordinary periods; and
- the strongest simple baseline comparison.

Do not report precision, recall, probability, or confidence without appropriate
labels and representative outcome data.

### 9.3 Performance budgets

Benchmark:

- 4, 50, 500, 1,000, and 10,000 observations;
- one through four datasets;
- one through four relationships;
- Python API and CLI serialization separately; and
- peak memory as well as runtime.

Publish environment information and percentile distributions. Treat current
single-machine timings as development observations, not product guarantees.

## 10. Recommended pull-request sequence

Keep changes reviewable and preserve behavior at each step:

1. Assessment terminology and schema fixtures.
2. Dataset-scoped refactor with no numerical changes.
3. Early descriptive evidence and explicit rules.
4. Schema 1.1 multi-dataset orchestration.
5. Exact alignment and ratio relationships.
6. Conversion and unit-cost examples.
7. Difference and normalized-residual relationships.
8. Lagged-response relationship and example.
9. Joint-condition/data-quality gating and insufficient-evidence example.
10. Case composition and chronological replay.
11. Python agent facade, then MCP adapter.

Each pull request must update schemas, help text, examples, and tests for the
behavior it introduces. Do not accumulate an undocumented contract delta for a
later cleanup.

## 11. Product validation gates

The implementation demonstrates technical feasibility, not market demand. After
the examples work, validate the agentic proposition with real workflows.

Proceed toward a commercial runtime when:

- at least two independent design partners use substantially the same
  relationship and case contracts;
- setup takes days rather than weeks;
- a relationship example finds a useful case missed by its constituent
  single-series checks;
- the agent begins an appropriate investigation earlier without exceeding the
  agreed unnecessary-investigation burden; and
- reviewers value the structured evidence, limitations, and replay rather than
  only the final notification.

If each deployment requires bespoke semantic mapping or a customer's installed
platform reproduces the result with modest configuration, retain Anomalyzer as
an embedded open-source component rather than expanding into a broad platform.

## 12. Immediate next step

Implement Milestones 0 and 1 before adding new algorithms. The first code change
should create the dataset-scoped execution boundary while proving that every
current single-series result remains stable. The second should add early
descriptive assessments without weakening the existing rule that only calibrated
statistical evidence can trigger an episode.

Once that base is stable, implement `ratio` as the first relationship primitive
and build the conversion-break example end to end. It exercises multiple
datasets, alignment, units, lineage, early evidence, mature evidence, and agent
interpretation with the least new mathematics.
