# Anomalyzer — CLI implementation plan

> **Scope revision:** The current implementation is intentionally limited to anomaly detection with one seasonal baseline, conservative linear/compound trend adjustment, one calibrated residual threshold, descriptive consecutive-anomaly runs, and explicit manual regime resets. Forecasts are internal expectations only. The ensemble, CUSUM, automatic change-point retraining, heavyweight forecasting dependencies, standalone forecasting, and distribution comparison below are historical proposals, not the current implementation scope. See README.md for the supported interface.

**Status:** Milestones 1–2 implemented, September 19, 2026; see README.md for setup, contracts, verification, and limitations. The project is published as **Anomalyzer** under the MIT License, with `anomalyzer` as the command. Package-index name availability has not been checked. Subsequent milestones remain planned; UsageTap validation awaits supplied data.

**Core principle:** Lower investigative cost means weaker signals can be used to explore.

**Problem framing — aggregation should not set the response time:** People often roll charts up by day or week to avoid routine nighttime and weekend triggers. That can also hide emerging divergence and delay investigation. Communicate the value of comparing observations with seasonal expectations at the supplied data cadence: keep the chart aggregated for readability while making the underlying evidence available to AI agents and notification workflows as divergence develops. A rising raw value is not necessarily anomalous; the relevant signal is departure from expected behavior.

The current core already scores each eligible observation at the declared cadence, independently of any chart, and returns observed values, seasonal expectations, residuals, scores, and trigger flags through Python and JSON. Evidence includes samples below the anomaly threshold, so consumers can inspect a developing signal before an episode is flagged. Applications use that evidence for investigation and notification policies; chart granularity need not gate either. Notification delivery and monitoring schedules remain application responsibilities. Earlier evidence still requires sufficiently fine source data and a suitable seasonal baseline.

This clarifies the problem and existing separation of responsibilities; it does not introduce a new implementation milestone, schema expansion, or detector commitment.

## 1. Purpose and first release

Build a local Python library and CLI that accepts numerical datasets, assembles applicable forecasting and detection methods, and returns reproducible evidence that a person or agent can investigate. Existing Python libraries provide the numerical foundations. Anomalyzer provides consistent inputs, method selection, evidence records, and fair comparison.

The initial user is a developer or agent investigating supplied data. UsageTap is the intended first reference application; its code and datasets still need to be inspected. Keep the core independent of UsageTap and any partner.

The first release should answer:

- Is this time series behaving unexpectedly relative to a declared baseline?
- Is there evidence of an abrupt departure or a persistent change?
- What supports that observation, what is uncertain, and what should be checked next?

Start with `analyze` and `methods`. Add forecasting, distribution comparison, relationship analysis, and evaluation through the same core in subsequent milestones. A small evaluation harness is required from the beginning, even before it becomes a public command.

The first release runs on demand, locally, without a model API. The calling agent interprets evidence and chooses further investigations. Continuous monitoring, chat, a blotter UI, learned policy changes, and external action execution remain application responsibilities. An optional MCP adapter can expose the same core later.

## 2. Proposed command interface

These examples define the intended interface; they are not working commands yet. CSV uses explicit column mappings. JSON on stdin uses the canonical input schema described below. Default output is a readable summary; `--format json` emits one machine-readable result.

```bash
# First release: inspect daily usage with an explicit weekly seasonal period.
anomalyzer analyze usage.csv --time timestamp --value calls --frequency 1d --season-length 7 --format json

# Canonical JSON supplied through stdin.
anomalyzer analyze - --input-format json --format json

# Discover installed methods and their requirements.
anomalyzer methods --format json

# Subsequent commands.
anomalyzer forecast usage.csv --time timestamp --value calls --frequency 1d --horizon 14 --format json
anomalyzer compare before.csv after.csv --value latency --format json
anomalyzer analyze --config checkout.json --format json
anomalyzer evaluate usage.csv --config evaluation.json --format json
```

| Command | Contract |
|---|---|
| `analyze` | Validate input, run a declared method recipe, and return observations with evidence. Multiple datasets are introduced through configuration in the relationship milestone. |
| `methods` | List installed adapters, supported tasks, input requirements, score semantics, and batch or online capability. |
| `forecast` | Return future point forecasts, supported intervals, horizon, training cutoff, and assumptions. |
| `compare` | Compare two samples or windows: location, spread, tails, effect sizes, and applicable statistical tests. No timestamps are required for independent samples. |
| `evaluate` | Compare individual methods and recipes using chronological replay and explicit evaluation objectives. |

Shared options should include `--config`, `--format`, and `--output`. Add `--seed` for stochastic methods and explicit runtime/data-size limits. CLI options override configuration; the result records the fully resolved settings. Unknown options, configuration keys, and methods fail clearly. Never silently substitute a method after failure.

Stdout contains only the requested result. Progress and diagnostics go to stderr. Do not overwrite an existing output file without an explicit overwrite option. Exit code 0 means evaluation completed, including when anomalies were found; 2 means invalid input/configuration; 1 means execution failed. A completed run with insufficient history reports that state in the result rather than claiming normality. Preserve per-method failures and mark partial results explicitly.

## 3. Input and output contracts

### Inputs

Support local CSV and canonical JSON initially. Add Parquet only when actual input volume justifies it. Files and stdin avoid requiring the agent to reproduce large arrays in conversation.

Canonical inputs carry a schema version, named datasets, and task configuration. A time-series dataset includes an identifier, timestamps and values, optional units and entity/cohort keys, frequency, and timezone where needed. Distribution datasets carry values and their population/window definitions. Optional context includes known events, a concern, and an as-of cutoff.

Define and validate these semantics explicitly:

- Timestamps must be unambiguous; local timestamps require a timezone. Sort order and any normalization are reported.
- Duplicate timestamps require an explicit aggregation rule or produce a validation error.
- Missing is distinct from zero. Do not silently fill, interpolate, resample, or mix units.
- Each adapter declares regularity and minimum-history requirements. Sparse or irregular data can make a method inapplicable.
- A forecast horizon is a number of periods at the declared cadence. A seasonal period is measured in observations.
- Multi-entity data must be grouped explicitly; do not combine customers into a single accidental series.
- For replay, distinguish event time from arrival time where available. If arrival history is absent, disclose the assumption that data was available at its event time.

Natural-language concerns are context, not executable instructions or validated policy. The caller can use AI to draft a configuration; the CLI validates and executes the explicit numerical specification. Do not accept arbitrary Python expressions in configuration.

### Outputs

Use a versioned JSON envelope shared by the Python API, CLI, and future MCP adapter. It should contain:

- Run ID, task, overall status, input fingerprint, and resolved configuration.
- Data-quality findings, transformations, observation counts, and applicable time windows.
- Method identifiers, dependency versions, parameters, applicability, runtime, and per-method status.
- Observations with affected datasets/intervals, direction, magnitude, observed statistic, reference, triggering samples, and evidence references.
- Detector-specific score semantics, conflicting evidence, limitations, and suggested follow-up checks.
- Forecasts or comparison results where requested, plus paths to detailed artifacts when output is large.

Keep statistical evidence, business impact, and authority separate. Do not convert a p-value, forecast interval, or arbitrary anomaly score into a universal probability of a business problem. Initially, preserve native evidence rather than inventing a single confidence percentage. Any later weak/moderate/strong labels require explicit, versioned criteria and evaluation.

Readable summaries should support what / so what / now what. The CLI can identify what changed and suggest checks; it must mark business consequences or recommended interventions as unresolved when the necessary context is absent.

## 4. Python architecture and dependencies

```text
Calling person or agent
        |
CLI: files/stdin -> validated request -> result formatter
        |
Python core: data checks -> recipe runner -> evidence records
        |
Adapters: existing forecasting and statistical libraries

Later MCP adapter -> the same Python core
```

Proposed package layout:

```text
src/anomalyzer/
  cli.py
  contracts.py
  io.py
  validation.py
  registry.py
  recipes.py
  evidence.py
  adapters/
  evaluation/
tests/
  reference_cases/
examples/
```

Start with one forecasting dependency and SciPy for statistical foundations. **StatsForecast is the provisional first forecasting adapter**, because the initial scope is classical forecasting on usage series. Validate installation, dependency footprint, license compatibility, and suitability before committing. Its documented features include classical methods, intervals, and cross-validation. [StatsForecast](https://nixtlaverse.nixtla.io/statsforecast/index.html).

Darts and sktime remain alternatives if their composition or evaluation facilities remove substantial custom work. Both already provide shared forecasting interfaces and evaluation support; do not rebuild those features unnecessarily. Add River when a real streaming requirement arises. [Darts](https://github.com/unit8co/darts), [sktime](https://www.sktime.org/en/stable/api_reference/forecasting.html), [River](https://riverml.xyz/latest/api/overview/).

Each adapter declares supported tasks, required input properties, parameter schema, score meaning, and update semantics. Register adapters explicitly. Keep optional heavy dependencies separate. Do not create parallel implementations of existing algorithms without a demonstrated gap and reference validation.

## 5. Assemble a small ensemble

The first recipe should include a naive or seasonal-naive forecasting baseline, one alternative classical forecaster, and complementary checks for a point departure and an accumulating shift. A candidate pair is a forecast-residual departure check plus CUSUM, subject to suitable residual behavior and independent reference validation. A poor residual model must be visible as a limitation.

The sequence is:

1. Check applicability and establish a training/calibration window.
2. Generate expectations using only earlier information.
3. Evaluate the next observation before updating the baseline.
4. Record each detector's evidence and group related observations into episodes.
5. Return the episode, including disagreement and method limitations.

Begin with fixed, inspectable recipes. A recipe chooses methods for a task; it does not automatically run everything. Forecast averaging and combining anomaly evidence are distinct operations. Detectors sharing a forecast or residual stream are not independent votes. One early signal may be worth exploring even if other methods remain quiet.

Compare each recipe with its strongest simple component. Keep additional methods only when they improve the target outcome enough to justify runtime and complexity. Automatic weighting, broad algorithm search, and learned method selection are later work.

## 6. Extend to relationships and distributions

For relationships, begin with user-declared, testable comparisons rather than automatic causal discovery. The first demonstration should examine usage relative to incoming demand, with explicit entity alignment, frequency, lag, and expected relationship. Ratios must handle zero or small denominators. Conditional forecasts must not receive future covariates that would have been unavailable at prediction time.

For distributions, return meaningful effect sizes as well as test results. Show whether a change affects location, spread, or tails, with sample sizes and assumptions. Choose methods appropriate to independent samples versus temporally dependent windows; do not treat repeated observations as independent by default.

An initial cross-dataset recipe should demonstrate a case where individual values appear ordinary but their relationship has changed. Include a counterexample caused by missing or delayed data.

Simulation follows when a forecast use case needs it, such as allowance exhaustion before renewal. Report model assumptions, horizon, seed, and path count, preserving relevant temporal and cross-variable dependence. Simulated event probabilities remain separate from anomaly evidence.

## 7. Cheap exploration and policy boundaries

Anomalyzer's first job is to make numerical investigation easy to call and inspect. The caller can respond to a weak observation by collecting context and invoking another comparison, without notifying a person. The CLI does not require an LLM and does not itself execute business actions.

Use separate policy requirements for investigation, notification, and consequential action. Record computational cost and stop reasons so an agent can operate within a budget. Bound automatic method selection and support interruption; avoid unbounded searches hidden inside a single call.

Future application workflows should measure whether investigation produces useful evidence sooner at an acceptable cost. Reduced human interruptions and earlier appropriate action are both relevant; simply generating more observations is not success.

## 8. Evaluation and acceptance

Use chronological training, calibration, and held-out evaluation windows. Keep tuning out of the final evaluation period and record baseline-update behavior. Offline methods cannot claim live detection at a timestamp before the required later evidence existed.

Measure forecasting error and interval coverage separately from episode-level detection delay, missed episodes, false episodes, runtime, and memory. Without labeled incidents, report forecasting and statistical diagnostics but do not claim detection precision or recall. Without observed action records, report simulated action eligibility rather than actual time saved.

Meaningful verification should cover:

- Numerical agreement with independent reference cases and documented algorithm definitions.
- Seasonal variation, a point spike, a persistent shift, and an expected contextual change.
- A relationship failure and a data-arrival failure once cross-dataset analysis is introduced.
- Constant data, insufficient history, missing values, duplicate timestamps, irregular cadence, and invalid units/configuration.
- JSON schema validity, exit behavior, stdin/file equivalence, and reproducible numerical results for fixed data/configuration/versions and seeds.
- At least one supplied UsageTap case, including an ordinary period, once data is available. Synthetic cases validate behavior but do not establish product effectiveness.

## 9. Delivery milestones

| Milestone | Deliverable and exit condition |
|---|---|
| 1. Contracts and foundation | Confirm the first input shape; define schemas, adapter protocol, dependency choice, and independent evaluation fixtures. Inspect UsageTap when its code/data is supplied. Synthetic fixtures allow work to proceed meanwhile. |
| 2. First useful CLI | Ship `analyze` and `methods`, CSV/JSON input, one small recipe, readable/JSON results, provenance, and explicit insufficient-data behavior. Demonstrate a spike and accumulating change against an ordinary baseline. |
| 3. Forecast and distribution comparison | Expose `forecast` and `compare`; validate intervals and effect sizes on held-out/reference data. Add a second forecasting adapter only if justified. |
| 4. Cross-dataset exploration and evaluation | Add declared relationships and public `evaluate`; demonstrate relationship failure, honest replay, and recipe-versus-component comparison. |
| 5. Agent integration | Show an agent using CLI evidence to conduct a bounded follow-up investigation. Measure useful findings, cost, and human interruptions. Add MCP only when a target client needs it. |

Before public release: settle package/command availability, choose the license after checking dependencies, document supported environments and assumptions, and provide runnable examples. Packaging choices do not establish a commercial product; adoption and repeated useful investigations remain the validation goal.

## 10. Immediate implementation slice

Implement milestones 1 and 2 first. The concrete deliverable is an installable local package with `anomalyzer analyze`, `anomalyzer methods`, validated CSV/JSON input, structured evidence, and a small reproducible example set. Keep the core directly callable from Python. No hosted service, credentials, or publication is needed to validate this slice.
