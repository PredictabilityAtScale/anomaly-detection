# Anomalyzer — initial product brief (working title)

**Proposal context:** Originally prepared under the provisional name Golden Anomalies. The current working name is **Anomalyzer**, with a local Python CLI as the first implementation direction; see the [CLI plan](cli-plan.md). Earlier references to Golden Anomalies below describe the broader proposal. Final naming and any partnership remain open. UsageTap provides an existing reference application and candidate implementation foundation.

**Working proposition:** What changed? So what? Now what? Turn signals across your data into the right action, faster.

**Status:** Product proposal, revision 13. The current open-source implementation is a local anomaly-detection CLI; see README.md for its supported baseline, residual checks, and limits. Section 14 retains broader toolkit proposals. The problem framing emphasizes early signals independent of chart aggregation; see section 6 and the CLI plan. Cheap agent investigation is a central product hypothesis: weaker signals can initiate research without interrupting people; see section 8. The broader platform remains a proposal based on the supplied MVP slide, UsageTap screenshots, and agents as primary operational consumers. Cross-dataset policies, complementary detectors, signal strength, cost of delay, and timing feedback remain longer-term design goals. Scope, adoption thesis, commercial model, and pilot targets are hypotheses to validate. UsageTap's code and backend capabilities have not been assessed here.

**Market-review checkpoint:** The [skeptical market review](market-review.md) finds substantial existing coverage of this category and challenges broad novelty. Its recommendation is to validate a focused cost-of-delay and timing-feedback workflow against installed alternatives before committing to the general platform. The capabilities below remain a product design, not demonstrated competitive advantages.

## 1. Product thesis

Golden Anomalies helps analysts and AI agents act faster on meaningful changes across multiple datasets. Users annotate connected charts, describe concerns in ordinary language, and define policies over relationships between measurements, populations, and events. The platform combines fast statistical signals, historical relationships, and business context to identify what changed, establish why it matters, and initiate the appropriate response through a visual workspace, chat, an API, and an MCP server.

**Strategic thesis:** Routine monitoring will increasingly be performed by agents consuming data, with people spending less time watching charts. Design for that shift: agents consume structured observations, retrieve relevant evidence, and initiate actions within explicit authority. People define concerns, policies, and permissions; inspect unfamiliar situations; and improve the response through feedback. Charts remain useful for teaching, investigation, and review, but opening a chart must not be required for the operational loop to work.

**Product promise:** Give agents the evidence, context, and policy decisions they need to take the right permitted action at the right time. Deliver the same what / so what / now what record to a human when attention is needed.

The core product is a shared **anomaly case** organized around **what, so what, and now what**. A case can span several datasets and detectors. It accumulates evidence, impact, decisions, and outcomes as the situation develops.

Every case answers three questions:

1. **What:** What changed in a measurement, distribution, or relationship? When did it begin, and what evidence supports it?
2. **So what:** Which policy or objective is affected? What is the exposure, urgency, and historical precedent? What remains uncertain?
3. **Now what:** Which action should happen next, who or which agent owns it, by when, and how will its result be checked?

A real anomaly can be expected. A material problem can develop gradually. A suppressed notification must not erase evidence that something happened.

**Operating principle:** Act on the evidence appropriate to the **cost of delay**. Weak signals can warrant action when policy and historical experience justify it. Signal strength informs the decision; policy determines the response. The response must also account for the cost of acting unnecessarily and whether the action is reversible.

**Why AI changes the economics: Lower investigative cost means weaker signals can be used to explore.** Separate the triggers for agent investigation, human notification, and consequential action. A weak signal can start a quiet, bounded investigation that gathers context before policy decides whether to escalate. Lower investigation cost does not make the original evidence stronger; it makes examining that evidence more affordable.

**Primary outcome:** Reduce elapsed time from the first observable actionable signal to the first appropriate action. Detection accuracy, explanation quality, and automation serve this outcome. Track subsequent resolution and effectiveness to ensure faster action is also useful action.

## 2. Audience and initial use

**Primary operational consumer:** An agent or workflow that continuously consumes observations and cases, gathers evidence, and initiates permitted responses.

**Human owner:** An analyst or domain owner who understands the process, defines concerns and acceptable tradeoffs, grants action authority, and reviews exceptions and outcomes.

**Builder:** An agent or workflow developer integrating datasets, the evidence service, and action executors through explicit contracts.

**Likely buyer:** A data, analytics, or operations leader seeking less manual monitoring and faster, more consistent investigations.

Keep the platform domain-neutral, but constrain the initial workflow: recurring numerical datasets, identifiable owners, accessible history, and a repeatable response. Example applications include conversion, demand, service latency, processing times, defects, and cost per transaction. These are validation scenarios, not separate MVPs.

**Job to be done:** “When the way my business behaves starts to change, connect the evidence across my data, tell me why it matters, and get the right response underway before the consequence grows.”

## 3. Positioning

Position Golden Anomalies as a platform that turns signals across analytical data into timely action. Single-dataset detectors are components; policies describe the behavior of a process spanning datasets.

The core deliverable is an evidence and response service that agents can use without a dashboard session. The visual product gives people a way to teach, inspect, and govern that service. MCP and API access are core product interfaces from the first operational release.

Seasonality-aware detection and explanations are already available: Datadog documents trend and seasonal anomaly monitoring, and Power BI offers anomaly detection and potential explanations in line charts. These capabilities alone are insufficient differentiation. [Datadog documentation](https://docs.datadoghq.com/monitors/types/anomaly/), [Power BI documentation](https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-anomaly-detection).

The proposed product combines the following capabilities. Treat these as design goals; the market review identifies the narrower timing-feedback workflow as a hypothesis requiring competitive validation:

- Concerns expressed as “I worry when…” and converted into inspectable policies across datasets, with explicit relationships and time lags.
- Detection of missing expected responses and unusual combinations, including when individual measurements remain inside their normal ranges.
- Multiple complementary detectors that surface early evidence and strengthen or revise a case as observations arrive.
- Direct annotation of normal periods, unusual periods, cohorts, tails, and known changes.
- A consistent what / so what / now what experience connecting evidence, practical impact, and the next action.
- Organizational memory linking reviewed cases, causes, responses, and outcomes.
- One case model available to people and agents, with consistent permissions and policy enforcement.

This is a positioning hypothesis, not a claim that competitors lack every component. The potential durable advantage is the accumulated quality of policies, reviewed cases, and response outcomes.

### Existing foundation: UsageTap

The supplied screenshots show two complementary product surfaces already in UsageTap. Treat these as candidates for reuse or integration before planning replacement components. This inventory describes visible behavior and labels, not a code audit or verification of model performance.

| Existing surface | Visible capabilities | Proposed extension |
|---|---|---|
| Usage forecast timeline | Actual, expected, predicted, and model-trend series; excluded-model-point labeling; incident markers; Confirmed / All signals controls; displayed training context | Evolving signal strength, clear confirmation semantics, cross-dataset evidence, relationship annotations, and policy-linked actions |
| Customer health | Signal summaries for usage collapse, limits, growth, decline, activity, and new customers; customer filtering and grouping | Vital signs spanning multiple datasets, with separate magnitude, evidence strength, data quality, urgency, and action state |
| Customer usage intelligence | Current versus previous seven-day counts, momentum, last activity, attention labels, and a suggested next action | What / so what / now what cases with cost of delay, policy reasoning, historical precedent, and timing feedback |
| Customer controls | Visible status, replenishment, and plan-change controls | Explicit policy-governed action contracts shared by people and agents, with recorded execution and outcomes |

**What this changes:** UsageTap already demonstrates parts of detection, prioritization, and response presentation. Golden Anomalies's next step is to connect these through a reusable observation, evidence, policy, and action model. The architecture decision—extract a shared library/service or integrate through an API—requires code inspection. A separate application or rewrite is not yet a requirement.

Use UsageTap as the first end-to-end reference application while keeping the core domain-neutral. Its customer and usage context provides a practical workflow for testing cross-dataset policies, weak-signal responses, and the historical feedback loop.

**Example grounded in the supplied screen:** A customer has zero usage events in the latest seven-day window versus twelve in the previous window. The relative decline is 100%, but that magnitude alone does not establish strong evidence or urgency. A policy can ask whether this is unusual for that customer's history, whether an entitlement limit blocked activity, and whether other available data corroborates the concern. Entitlements, billing, support, and lifecycle data are candidate inputs to assess, not assumed connected capabilities. The resulting action could be an internal entitlement check, a reviewed outreach task, or continued observation with a deadline, depending on policy and cost of delay.

Preserve measurement semantics during reuse. The screenshot notes that the usage-event count combines calls and custom events without normalizing meter units. Such counts can be useful as an activity signal, but should not silently become comparable measures of consumption or financial exposure across customers and meters. Also define what “Confirmed” means: detector criteria satisfied, analyst-reviewed, and cause-confirmed are distinct states and should remain distinct from signal strength.

## 4. Core experience

**Continuous agent workflow:** New data produces observations; detectors and relationship models update evidence; policies evaluate response eligibility; an agent retrieves the case and relevant history; an authorized executor performs the permitted action; its result updates the case. Policy can route an unresolved question or approval requirement to a person. Routine pre-authorized work should complete without requiring someone to open the UI or reconfirm the same authority.

**Human workflow:** Establish intent and authority, inspect cases when useful, handle exceptions, and review whether actions were timely and effective. The following surfaces support that work.

**Connect and define.** Upload datasets or send records through an ingestion API. Define measurement units, row meaning, timestamps, dimensions, aggregation, and denominators. Declare how sources relate through shared entities, cohorts, or time windows. Link source dashboards. Use actual data behind charts; screenshot interpretation is outside the MVP.

**Describe and mark up.** Enter “I worry when…” and brush time intervals or select distribution regions/cohorts across linked charts. Mark “normal example,” “important deviation,” “expected change,” or “missed issue.” Annotate relationships such as “this usually follows that within two days.” Attach notes and known events. Users can create cases the detectors missed.

**Review the interpretation.** Show a readable policy card with source mappings, relationships, lags, comparisons, minimum evidence, exclusions, and actions. Highlight unresolved terms such as “consistent traffic.” Preview its effect on history, including when it would first gather evidence and when it would escalate.

**Investigate and act.** Select a marker to open a case with three visible sections: what changed across the linked data; so what it means for the policy and objective; and now what action, owner, deadline, and expected result are proposed. Chat answers questions using the case records and reproducible calculations. Evidence gathering can already be underway when the analyst opens the case.

**Respond and learn.** Assign an owner, acknowledge, request an approved workflow, and record the resolution. Offer direct feedback such as “we saw this too late,” “we saw it but acted too late,” and “this early action was worth it.” Let reviewers mark when a different response would have helped. Track later outcomes and replay proposed policy changes so the next response benefits from this experience.

The human interface needs three main views: a live observation blotter with vital signs and prioritized cases, a linked-chart workspace with policy editor, and a case detail view with chat and history. Notification suppression should remain visible in the case record. A case's next action must be visible without requiring a chat conversation. Agents consume the underlying observation stream and case records directly; the blotter is a human view of the same operational history.

### Live observation blotter and vital signs

Create a ticker-style, continuously updating blotter that answers “what are we observing right now?” It includes measured changes, weak signals, corroborating or conflicting evidence, known events, data-quality changes, and action updates. An observation is not necessarily an anomaly or an alert. Several observations can contribute to one case; notification remains a policy decision.

Each row shows event time and, when different, arrival time; entity or process; a short observation; linked datasets; signal strength and direction of change; data quality; urgency / cost of delay; and current action status. Show the reason a policy acted or chose to wait. Make rows selectable to open linked charts, the case, and its what / so what / now what explanation.

Above the blotter, show **vital signs** for user-selected measurements and relationships: current value, expected range where meaningful, recent direction, last update, and associated case/action state. Include relationship measures such as orders relative to demand, not just isolated metrics. Use explicit unknown or stale states; a missing signal must not appear as healthy.

Illustrative feed entries:

| Time | Observation | Evidence | Policy / response |
|---|---|---|---|
| 10:02 | Orders beginning to underperform traffic | Weak; data current | High cost of delay: approved diagnostics started |
| 10:03 | Payment failures now corroborate the change | Moderate; strengthening | Same case updated; owner notified |
| 10:04 | Supplier dataset missed its expected update | Undetermined; stale source | Data check started; dependent conclusion provisional |
| 10:07 | Owner acknowledged checkout case | Action update | Investigation underway; next review due at 10:12 |

Allow filtering by process, dataset, policy, signal strength, and action state, with grouping for repeated observations and a pause/follow control. A paused display does not pause monitoring. Keep urgent unresolved cases in a persistent area until their workflow advances; they must not scroll out of attention. Avoid mandatory moving text or color-only meaning. Preserve the feed as an inspectable timeline for later timing reviews.

## 5. “I worry when” becomes an explicit policy

Separate **concerns**, **context**, and **operating instructions** instead of treating every sentence as an alert rule.

| User statement | Product interpretation |
|---|---|
| “I worry when sales fall while incoming traffic is consistent.” | Monitor sales or conversion relative to traffic; define the traffic comparison and tolerances explicitly. |
| “Orders usually follow qualified leads within two weeks. I worry when that stops happening.” | Compare CRM lead cohorts with order outcomes over the learned and reviewed lag window; exclude cohorts that have not had time to mature. |
| “I worry when demand rises, inventory falls, and supplier lead times lengthen together.” | Evaluate a joint condition across demand, inventory, and supplier datasets, even if individual changes are moderate. |
| “Don’t alert on weekends.” | Continue detecting and recording; apply a notification schedule with a timezone and explicit exceptions. |
| “We launch in Europe on June 8.” | Add a scoped, dated event that may change expectations; ask for the year if unresolved. It does not automatically excuse every subsequent change. |
| “A large new client starts in August.” | Record a possible baseline transition and customer scope; evaluate whether a new baseline is warranted. |
| “I worry when the slowest requests worsen even if the average is stable.” | Monitor the latency tail and affected share, alongside the overall distribution. |
| “Last time we waited for confirmation and missed the useful response window. Act on the early pattern next time.” | Link the prior case, define the early evidence and scoped action, and replay a lower action threshold against incident and ordinary periods. |

A policy stores its source text, datasets and metrics, entity/cohort mappings, reference populations, time alignment and lag windows, relationship definition, direction, duration, materiality, action-specific evidence requirements, data-quality requirements, consequence of delay, cost and reversibility of acting, tolerated unnecessary actions, context dependencies, notification rules, owner, permitted actions, escalation criteria, supporting historical cases, and version.

Language models propose the policy; deterministic code evaluates its explicit conditions. Ambiguous policies remain drafts. Policies can return **insufficient evidence**, rather than treating missing data as healthy. Conflicts between policies must be visible and resolved with documented precedence before activation.

### Cost of delay determines the response window

A policy describes how consequences change if action is delayed: the useful response window, the cost or severity of missing it, and whether the situation is recoverable. Cost can be operational, financial, or human; use meaningful qualitative categories where a monetary estimate would be inappropriate or unsupported.

Describe two things separately: **how safe it is to let the situation fail**, and **how safe it is to take the proposed action unnecessarily**. A recoverable situation may justify waiting; a cheap, reversible action may justify responding early. A potentially life-threatening situation may require an immediate, predefined escalation on weak evidence, while an intervention that itself carries serious risk can require different evidence or authorization. There is no single universal signal threshold or “lower every threshold” setting.

| Policy context | Illustrative trigger design |
|---|---|
| Safe-to-fail experiment; inexpensive delay | Observe until evidence strengthens, or take a cheap reversible step if explicitly permitted. |
| Recoverable operation with rapidly accumulating losses | Trigger a scoped response on early evidence; reassess at a defined interval. |
| Potentially life-threatening situation | Use domain-authorized triggers for immediate notification or escalation; evaluate intervention separately according to its risk and authority. |

Life-critical deployment is a distinct validation and operating scope beyond the general MVP. The platform must support domain-defined rules and escalation paths without treating a learned historical pattern as authority to invent or relax such triggers. Historical timing reviews can propose improvements for the responsible domain owner to validate.

### Cross-dataset relationships are a first-class capability

Support three forms of monitoring from the start:

- **Combined conditions:** Several observations together satisfy a concern or action policy.
- **Broken expectations:** A metric behaves differently from what related measurements normally imply, including an expected response that fails to arrive after a defined lag.
- **Joint behavior:** A combination is unusual relative to historical relationships even when individual values look ordinary. Start with a small, user-selected set of measurements and a validated conditional or multivariate model.

AI helps map concerns to available metrics, propose plausible relationships and lag ranges, and retrieve similar historical episodes. Numerical analysis tests those suggestions, accounting for seasonality, trends, and shared drivers. Relationships require held-out validation and user review before driving active policies. Store whether each relationship was user-specified, historically estimated, or inferred from prior cases; correlation supports investigation and prediction, not a confirmed causal explanation.

The MVP supports user-defined relationships and bounded historical suggestions within selected datasets. Broad automatic discovery across all connected data is a later capability.

Cross-dataset evaluation needs a data contract: entity keys or comparable aggregate populations, compatible grain and units, event time versus arrival time, timezones, update cadence, and allowed lateness. Aggregate before joining where needed to prevent row multiplication. Keep immature outcome windows and delayed sources from appearing as broken business relationships. Record provisional cases and revisions when late data arrives. Both source data and derived cross-source evidence must respect access permissions.

Multivariate statistical monitoring already exists; for example, Hotelling's T-squared combines information across variables. The product opportunity is making such evidence usable through concerns, historical context, and action policies. [NIST multivariate control charts](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc34.htm).

## 6. Detection and quantification

### The problem: readable charts can hide the first useful signal

People often aggregate charts by day or week to avoid triggers from normal nighttime or weekend behavior. The tradeoff is that emerging divergence can disappear inside the aggregate until the useful response window has narrowed. Our message should make the alternative clear: account for expected seasonality in detection, keep charts at the granularity people prefer, and give agents and notification workflows the underlying signals as the departure develops.

For example, a weekly usage chart can remain weekly while hourly observations show usage increasingly exceeding its expected Monday-morning pattern. An agent can inspect the early evidence and a notification policy can respond when its requirements are met, without waiting for the weekly total. Expected seasonal increases are not themselves divergence. Quiet hours concern human notification delivery; they need not stop detection or permitted agent investigation.

The local core already separates numerical evidence from presentation: it scores supplied observations at their declared cadence and exposes observed values, seasonal expectations, residuals, scores, and trigger flags through Python and JSON, including evidence below the anomaly threshold. Applications consume those results for agent investigation and notification decisions. The core does not itself schedule monitoring or deliver notifications. Its fixed seasonal lag and source-data resolution determine what it can detect; this framing does not claim every gradual change will be caught or that finer observations can be recovered from daily or weekly totals.

This is communication of the problem and the evidence-consumer architecture, not an additional feature milestone.

Run a portfolio of complementary detectors with different sensitivities and evidence requirements. The same case can receive a fast initial signal, a sustained-change signal, and cross-dataset corroboration. Select applicable detectors by measurement type, baseline quality, cadence, and concern; retain simple baselines as evaluation comparators.

| Data/problem | Initial approach | Evidence presented |
|---|---|---|
| Fast changes in ordered observations | Shewhart and selected Nelson patterns against established limits, using appropriate residuals or subgroup statistics | Triggering observations, control limits, pattern, and baseline quality |
| Time-series spikes or drops | Seasonal baseline and prediction intervals appropriate to the metric | Expected range, actual value, deviation, duration, and interval coverage in backtests |
| Persistent deterioration or level changes | CUSUM or EWMA on appropriately modeled residuals; benchmark which complements the fast detector | Accumulated deviation, detection time, and estimated onset |
| Distribution shifts | Compare a current cohort/window with a suitable reference; inspect median, spread, tails, and distribution distance | Effect magnitude, sample sizes, uncertainty, and affected fraction |
| Cross-dataset relationship changes | Conditional baselines, lagged residuals, and a small joint model where supported by history | Expected relationship, observed departure, lag, and contributing measurements |
| Data problems | Freshness, completeness, duplicates, missingness, and denominator checks | A data-quality case or insufficient-evidence state |

For distribution comparisons, Wasserstein distance is one possible magnitude measure; a two-sample KS test can provide evidence of a difference when its assumptions fit. KS assumes independent samples from continuous distributions, so it is not a universal test for counts, categories, or dependent observations. [SciPy Wasserstein documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wasserstein_distance.html), [SciPy KS documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ks_2samp.html).

CUSUM and EWMA are candidates for sensitivity to small sustained changes. Their applicability and operating parameters require validation on the target data. [NIST CUSUM reference](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc323.htm), [NIST EWMA reference](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm).

**Preserve the fast-signal intent of the slide.** Nelson rules belong in the detector portfolio: some patterns signal with only a few new observations relative to established limits, such as two of three beyond two sigma on the same side. Distinguish the short triggering window from the history needed to estimate dependable limits. These tests detect particular changes in an ordered process, while distribution comparisons cover additional changes in spread, tails, and shape. Select tests deliberately because running more increases false-signal opportunities. [Minitab special-cause tests](https://support.minitab.com/en-us/minitab/help-and-how-to/quality-and-process-improvement/control-charts/supporting-topics/basics/using-tests-for-special-causes/).

### Combine evidence and vary the response

Detector outputs feed a shared evidence record containing the baseline, triggering window, magnitude, applicability, and uncertainty. Begin with transparent combination rules, calibrated through replay. Learn weights or ranking only after sufficient reviewed examples exist. Do not average incompatible scores or count closely related detectors as independent votes.

Evidence accumulation and action proceed together. Evaluate permitted actions at every case revision, including the first weak signal. Policy can authorize diagnostics, notification, or a scoped precautionary response before statistical confirmation when the consequence of waiting warrants it. A strong individual signal can also justify immediate escalation. If evidence fades, close or downgrade the provisional case and review any action already taken.

The policy sets how much evidence each action needs. Optimize detection delay at an agreed false-action burden, rather than demanding unanimous detector agreement. Compare the ensemble with its strongest individual detector to establish whether the extra complexity actually helps. Evaluate on each completed observation or ingestion event, subject to source cadence; fast computation cannot overcome slow source updates.

### Show signal strength without making it an action gate

Give every case a visible **signal strength** label—weak, moderate, strong, or undetermined—with a history showing strengthening, weakening, or conflicting evidence. Explain the label using deviation, persistence, corroboration, detector applicability, and evidence against the concern. Use versioned criteria validated for the monitored context. Do not display a probability of a business problem unless that specific probability has been calibrated; an ordinal label is not a universal score across datasets.

Show **data quality** separately: freshness, completeness, sample sufficiency, and baseline reliability. Weak but trustworthy evidence differs from an apparent strong change based on incomplete data. Neither automatically determines the action: a policy may require a data check or a precautionary response while uncertainty remains. The blotter and vital signs use these same definitions as case details and MCP responses.

Beside these, show **urgency / consequence of waiting** and **the policy-selected action**. For example:

| Case state | Policy response example |
|---|---|
| Weak signal, reliable data, expensive delay, established early-response playbook | Start the scoped response now; state the uncertainty and when to reassess. |
| Weak signal, reliable data, low consequence of waiting | Gather more evidence and set the next evaluation time. |
| Strong signal, known expected change | Record the change and follow the event policy. |
| Uncertain signal, incomplete source, potentially material exposure | Check the source and apply any explicitly authorized precautionary action. |

An illustrative case card might read: **Signal: weak, strengthening. Data: current; only three new observations. Urgency: high. Now what: notify the owner and start the approved diagnostics. Why now: policy P7 cites a similar incident where waiting missed the response window.** Link the prior case and policy version; the historical outcome must not inflate the displayed current evidence strength.

Comparison quality matters as much as detector choice. Match seasonality and cohort composition, account for exposure and sample size, check serial dependence, and keep known incidents from silently becoming the new normal. Where composition changes, distinguish a mix shift from deterioration within comparable groups. Monitor selected dimensions first; unrestricted segment searches create a multiple-comparison problem.

Every case separates:

- **Statistical evidence:** Detector score, reference, uncertainty, and applicable assumptions. A p-value is not the probability that a business problem exists.
- **Magnitude:** Absolute and relative change, persistence, affected volume, and distribution movement.
- **Business exposure:** Optional conversion into user-defined units such as delayed orders, excess processing hours, or revenue at risk, with formula and assumptions.
- **Response priority:** Materiality, policy, urgency, ownership, and investigation status.

Do not compress these into an unexplained “AI confidence” number. Group adjacent and cross-source detections into episodes where the evidence supports a common situation, retaining individual detector results and alternative explanations.

## 7. Concrete demonstration

*Illustrative numbers, not measured product performance.*

An analyst connects web sessions, order records, payment-processing telemetry, and deployment events. They write: “I worry when orders underperform the traffic we receive and checkout problems rise. Start investigating early; escalate to the commerce owner when the likely exposure is material.” They annotate a prior launch and an earlier incident across the linked charts.

The policy preview maps sessions to eligible order outcomes, accounts for order-arrival delay, defines the checkout-error comparison, and separates evidence-gathering from escalation criteria. The analyst reviews and activates it. A fast detector starts a case as the relevant observations arrive; the system checks other sources without waiting for all detectors to agree.

**What:** In a completed comparison window, 10,000 eligible sessions produce 240 conversions. The conditional baseline predicts 300, with an illustrative prediction interval of 270–330. Checkout errors have also increased, and a deployment occurred before the change. These facts arrive from separate datasets; the deployment is a possible contributor, not a proven cause.

**So what:** Conversion is down 0.6 percentage points, a 20% relative decline, with an estimated shortfall of 60 conversions against the baseline. The case shows whether that exposure satisfies the user's materiality policy. “Shortfall” is a model comparison, not proven causal loss. Chat retrieves a similar reviewed incident and distinguishes its confirmed cause from the current hypothesis.

**Now what:** An agent has fetched the case through MCP and gathered permitted checkout diagnostics. The case names the commerce owner, the next investigation step, its policy-defined deadline, and the criteria for escalation. A proposed production change follows its configured approval. Action status, the eventual resolution, and whether the metrics recovered return to the case.

A second demonstration uses request latency: the median remains stable while the upper tail worsens. The analyst selects the tail in a distribution view, and the system reports the change, sample sizes, and affected share even though a chart of the average looks normal.

## 8. Chat, Jev, and numerical models

Use three complementary components:

**Numerical models** calculate baselines, intervals, distribution changes, cross-dataset relationships, and impact estimates. An evidence-combination layer reconciles detector results into evolving cases.

**A conversational model** helps clarify concerns, map datasets, propose relationships and lag windows for testing, draft policies, explain computed evidence, and retrieve prior investigations. Numerical claims must come from calculations; causal explanations must identify their supporting records or remain hypotheses.

**An optional decision model such as Jev** evaluates bounded contextual questions over the combined evidence: whether a case resembles a known event, which review category fits, which playbook is relevant, or whether additional investigation is advisable. It receives detector provenance and conflicting evidence rather than only a list of scores.

TypeSafe describes Jev as an early-access System One model returning typed decisions with probabilities rather than generated prose. That makes contextual classification a plausible role to test; the published description does not establish superior time-series anomaly detection for this product. Valid output types do not establish factual correctness or in-domain calibration. [TypeSafe announcement](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

Keep the decision-model interface replaceable. Benchmark Jev against explicit rules and another structured classifier on held-out cases. Evaluate decision quality, abstention, calibration, cost, and latency before making it a dependency. Model advice cannot override action permissions.

### Interpretation and agentic investigation

**Interpretation** connects computed evidence to business meaning. AI helps translate an “I worry when…” concern into an inspectable policy, identifying datasets, expected relationships, lags, missing definitions, and permitted responses. It explains what changed, why it might matter, and what evidence would distinguish competing hypotheses. An association with a deployment or a similar past incident remains a hypothesis until supported by further evidence.

**Agentic investigation** carries that inquiry forward without requiring someone to watch a chart or ask the next question. Within explicit authority, an agent checks source freshness, queries related metrics and affected cohorts, retrieves earlier cases, runs applicable follow-up comparisons, and records its findings. The ensemble measures; AI interprets and investigates; policy controls authority; agents execute and verify; outcomes inform improvement. MCP exposes the necessary tools and evidence, while the workflow supplies scheduling, state, and execution records.

| Situation | Policy-controlled response |
|---|---|
| Weak signal with little urgency | Record in the observation blotter and monitor for change |
| Weak signal where investigation may reduce costly delay | Start a quiet investigation within a time, query, and compute budget |
| Evidence or urgency warrants human attention | Notify the responsible person with findings and a concrete next step |
| A remedy meets its action-specific evidence and authority requirements | Execute the permitted action and verify its outcome, or obtain the configured approval |

These are separate response decisions, not a mandatory ladder: an urgent policy can notify immediately while investigation continues. A weak signal can justify research without authorizing a production change. Preserve quiet investigations in the blotter and case history without sending a notification for every step.

Bound investigation cost through deduplication, shared evidence, cooldowns, and explicit stop conditions. Stop when the question is resolved, escalation criteria are met, or the budget is exhausted; record unresolved cases and apply their urgency policy. Cheap research is a hypothesis to measure, not an assumption of free or infallible reasoning.

Evaluate this approach against direct-to-human alerting on the same cases: time to useful evidence and appropriate action, human interruptions, investigation cost, unnecessary actions, and missed or late incidents. Track whether quiet investigations resolve concerns or uncover actionable cases. Historical feedback such as “we saw this too late” can propose revised investigation or escalation triggers, followed by as-of replay and versioned activation under explicit authority.

## 9. Historical memory and feedback

Replace a single upvote/downvote with a few useful distinctions:

- Was the observation real, a data problem, or unresolved?
- Was it expected or unexpected, and was it worth investigating?
- Is the cause confirmed, suspected, or unknown?
- Which relationships and early signals proved informative?
- What action was taken, how quickly, and what outcome followed?
- Was the signal surfaced too late, or did recognition, routing, approval, or execution happen too late?
- What earlier action would have been useful, and what evidence was actually available then?

Store reviewer, timestamp, supporting evidence, and revisions. Treat this as reviewed history with varying certainty, rather than unquestioned historical truth. Multiple reviewers may disagree.

Initially, feedback improves case retrieval, explicit policies, and reviewed baseline selection. Learned ranking or custom models come later, when enough reliable labels exist. Review a sample of suppressed and unflagged periods to discover missed incidents and avoid learning only from cases the system chose to show.

### “We saw this too late” closes the policy loop

Keep an as-of timeline of source availability, detector evidence, displayed signal strength, policy decisions, notification, acknowledgment, action, and outcome. Retain below-notification evidence for configured monitors under a defined retention policy so reviews can inspect what was visible before escalation. Preserve revisions rather than rewriting the original decision with later knowledge.

When a reviewer marks a case late:

1. **Locate the missed window.** Mark the desired earlier action time or latest useful response time, the proposed action, and the supporting rationale. Preserve uncertainty in this retrospective judgment.
2. **Identify the delay.** Determine whether the cause was unavailable data, missed detection, policy thresholds, suppression, routing, approval, or execution. Lowering detection thresholds does not fix every delay.
3. **Propose a specific change.** Examples include acting on weaker evidence for a named pattern, shortening persistence, adding another dataset, changing an owner, or pre-authorizing a bounded response. Link the proposal to the case.
4. **Replay the tradeoff.** Show when the proposed policy would have acted using only evidence available at that time, alongside additional actions it would have triggered during ordinary periods. Evaluate on separate cases or a later holdout before claiming general improvement.
5. **Activate a reviewed policy version and follow its outcomes.** Track whether the next similar event receives a useful response sooner and whether the extra action burden stays within the owner's tolerance.

Measure estimated earlier eligibility separately from actual time saved. A replay cannot prove an intervention would have prevented loss. Likewise, an incident failing to materialize after early action does not by itself make that action a false positive; record whether prevention, spontaneous recovery, or an unresolved explanation best fits the evidence.

## 10. MCP and workflow integration

Expose one versioned anomaly service through the UI, API, and MCP. MCP provides tools and contextual resources to agent clients; monitoring schedules and downstream execution still belong to application services or an external orchestrator. [MCP server primitives](https://modelcontextprotocol.io/specification/2025-06-18/server).

The agent receives structured what / so what / now what fields, evidence references, signal strength, data quality, cost of delay, relevant policy decisions, and action eligibility. A chart image or prose summary is optional context. New observations and material case revisions can wake the external workflow through events; MCP supports its evidence retrieval and tool interactions.

**Authority is explicit and enforced at execution.** The policy owner defines which actions an agent may initiate, for which entities, within what limits and duration, and which require approval. The service or action executor checks current permissions, policy version, case freshness, and action limits before execution. Model confidence and prior successful actions do not grant new authority. Return distinct permitted, approval-required, denied, or insufficient-evidence results, and record execution success or failure separately from the request. Revocation, retries, and changed evidence must be handled without duplicating an action or using obsolete approval.

Proposed first tools:

| Tool | Purpose |
|---|---|
| `list_observations` | Read the blotter incrementally with a cursor, including weak signals, revisions, and action updates. |
| `get_vital_signs` | Retrieve selected measurement and relationship summaries, expected ranges, freshness, and linked case states. |
| `list_anomalies` | Retrieve cases by dataset, time, priority, and status. |
| `get_anomaly` | Return what / so what / now what, signal-strength history, data quality, linked evidence, policy decisions, and action status. |
| `find_similar_cases` | Retrieve reviewed historical cases and outcomes. |
| `preview_policy` | Replay a proposed cross-dataset policy; show first-signal and action-eligible times and additional action burden without activating it. |
| `record_feedback` | Append a scoped, attributed review, late-response annotation, desired action time, or outcome. |
| `request_action` | Submit a permitted action and return its approval or execution status. |

An agent-facing case includes stable IDs, event and detection times, references to all contributing datasets and cohorts, alignment and lag definitions, observations, baseline and detector versions, relationship provenance, policy version, statistical evidence, signal-strength history, data quality, impact and delay assumptions, context links, review status, next action, owner, deadline, verification criteria, action history, and attributed timing feedback. Expose the reason for acting under uncertainty so an agent does not infer that a weak signal requires waiting.

Use scoped authentication and dataset permissions consistently across interfaces. Distinguish read, review, and action permissions. Record actor identity and make action requests idempotent so retries do not duplicate work. Return an explicit abstention or insufficient-evidence result where appropriate.

For the MVP, deliver new and materially updated case events through a webhook and demonstrate one approved investigation workflow. Include case revision IDs so agents can recheck current evidence before acting. Automatically collecting evidence can be pre-authorized; production-changing actions require the configured approval. External notes and retrieved text remain evidence, not authority to change policies or permissions.

## 11. MVP boundaries

**Include:** CSV and API ingestion; evaluation on completed observations or a source-appropriate schedule; a live observation blotter and vital signs; linked charts and relationship annotations; cross-dataset policy preview with cost of delay and action-specific triggers; complementary detectors and transparent evidence combination; visible signal strength and data quality; what / so what / now what cases; timing feedback and replay; historical retrieval; grounded chat; MCP access; webhook delivery; one action workflow; and an audit history.

**Bound the first cross-dataset implementation:** Two to four explicitly selected datasets per pilot workflow, with reviewed entity/time alignment, combined-condition policies, one validated lagged or conditional relationship, and bounded historical relationship suggestions. Include a replay where each individual metric is ordinary but their relationship warrants action. This cap is a proposed implementation boundary, not the long-term product scope.

**First reference application:** Extend or integrate with UsageTap's usage anomalies and customer signals after assessing its existing implementation. Use one customer-response policy to demonstrate observation → evolving evidence → policy decision → action → timing feedback. Map its current signal cards to vital signs and its events/cases to the observation blotter before building duplicate surfaces.

**Integration approach:** Start with charts rendered from supplied data, source-dashboard links, and a documented annotation format. Add one chart adapter or embeddable overlay after validating the workflow. Supporting arbitrary existing BI charts in the first release would create substantial integration scope.

**Defer:** Universal dashboard overlays, image-only chart extraction, unrestricted relationship searches across every source, arbitrary causal discovery, categorical and high-dimensional distribution coverage, bespoke model training per customer, sub-second streaming, and unrestricted autonomous remediation.

The MVP detects and supports response to newly observed anomalies. Forecasting the probability of future incidents is a separate capability that needs separate validation.

## 12. Validation and release gates

Recruit three to five design partners across different domains but the same monitoring workflow. Each supplies a small set of related datasets, historical examples, explicit concerns, and a response process. Broader generality must be demonstrated rather than assumed.

Run chronological replay, then shadow monitoring, then a limited live pilot. Replay with only data, policies, and context available at each historical decision time, including actual source arrival delays; keep later labels for evaluation and reserve a later period as a holdout. Fit relationship selection, lag choices, and ensemble parameters before the holdout. Include missing data, baseline changes, changed correlations, shared seasonal drivers, detector disagreement, and late-arriving outcomes. Synthetic incidents supplement real cases, not replace them.

Compare against fixed thresholds, a seasonal baseline, the strongest individual detector, and each partner's current process. Compare cross-dataset policies with their single-dataset equivalents. Measure at the **incident/episode level**, not by counting every anomalous point as a separate success.

Proposed pilot gates, to agree with partners before evaluation:

| Outcome | Initial target hypothesis |
|---|---|
| Time to appropriate action — primary | At least 30% reduction in median elapsed time from the first retrospectively reviewed, observable actionable signal to an appropriate action actually starting; report tail latency and never-acted cases too. |
| Setup | First reviewed monitor within 30 minutes once usable data is connected. |
| Relevance | For routine policies, an initial target of 80% of reviewed surfaced episodes judged worth investigating; policies for costly delays can explicitly accept lower precision. |
| Coverage | At least 80% of independently labeled material incidents detected; report uncertainty and sample size. |
| Action burden | Stay within each policy's agreed budget for notifications, unnecessary actions, and investigation effort. For routine policies, test a 30% notification reduction at comparable recall; early-response policies may intentionally trade extra actions for lead time. |
| Action quality | Reduce action delay within the policy's action-cost and outcome tolerances; review effectiveness after a defined follow-up window. |
| Timing feedback loop | Demonstrate a late-response review producing a versioned change, an as-of replay with lead-time and extra-action comparisons, and prospective tracking. |
| Agent integration | Complete detection → retrieval → permitted action → recorded outcome, including a duplicate-delivery retry. |
| Operation without a dashboard | Complete the pre-authorized reference workflow with no chart interaction; demonstrate that an unauthorized action is blocked and an approval-required action waits. |

Also report detection delay, ingestion-to-case latency, investigation and approval wait time, execution time, resolution time, calibration where probabilities are used, compute cost per monitor, and results by anomaly type and partner. Decompose source freshness, detector delay, and workflow delay to identify where time is lost. Small samples cannot substantiate general accuracy claims. Measure policy suppression separately from detection misses. A drafted recommendation is not an action taken; record execution or the start of a justified investigation separately.

Track appropriate completed responses, human effort per case, and the share of pre-authorized workflows completed without human intervention. Evaluate automation alongside action quality and timing; dashboard views, chart interactions, and raw action counts are not success measures on their own.

## 13. Delivery and commercial hypotheses

**First milestone — assess and extend the existing foundation:** Inspect UsageTap's detector outputs, event records, customer signals, annotations, and action interfaces; identify reusable components and missing contracts. Connect a small set of related datasets, annotate relationships, replay complementary detectors, preview cross-dataset concerns, and generate what / so what / now what cases. Exit when analysts can explain and correct the system's decisions, including a relationship anomaly missed by individual charts. Validate distribution support separately where current implementation does not establish it.

**Second milestone — operational pilot:** Add evaluation as data becomes available, inbox, historical retrieval, chat, MCP, webhook delivery, and one response loop. Demonstrate action on a policy-authorized weak signal and a late-response review feeding a replayed policy revision. Exit when quality gates pass and the live pilot demonstrates faster appropriate action.

**Third milestone — paid deployment:** Harden permissions, retention, reliability, and the most valuable chart/data integration. Add learned ranking only if the evidence supports it.

Test a workspace subscription with usage tied to active policies and evaluation volume. Define a monitor as a policy over a declared set of metrics, relationships, and cohorts at an agreed cadence, and expose costs from added datasets and segments. Include agent access; charging per detected anomaly would make successful adoption unpredictable.

The next product decisions should come from partner evidence: which cross-dataset concerns recur, which early signals save time, what makes relationships trustworthy, whether annotations are sustainable, and which response workflow measurably shortens time to appropriate action.

## 14. Smaller first deliverable: an open-source forecasting and detection toolkit

**Agreed technical direction — assemble the ensemble:** Build on existing libraries to select, run, compare, and combine complementary forecasting methods, simulations, and anomaly detectors. Golden Anomalies supplies the integration and evidence contracts that let applications and agents use their results. UsageTap would be its first integration. Publishing this layer as an open-source toolkit remains under consideration; a hosted platform or paid service would require separate demand validation.

### What assembling the ensemble means

1. **Select applicable methods.** Use the data's cadence, history, seasonality, missingness, and declared relationships to choose a small set of candidates. Make method requirements and insufficient-data states explicit.
2. **Run complementary methods.** Combine fast process signals, forecast departures, distribution comparisons, and relationship checks where they serve the concern. Preserve each method's evidence and timing.
3. **Combine evidence explicitly.** Start with inspectable composition rules. Retain disagreement and avoid treating several closely related detectors as independent corroboration. Forecast averaging and combining anomaly evidence are separate operations; raw detector scores must not be averaged into an invented probability.
4. **Evaluate the resulting decisions.** Compare individual methods and the assembled system using historical replay and held-out cases. Assess forecasting quality separately from detection delay, missed episodes, unnecessary actions, and compute cost. Require a measurable benefit over a simple baseline before adding complexity.
5. **Apply policy and learn from outcomes.** Let the application determine the permitted response from evidence, cost of delay, and action risk. A single early signal may justify a reversible investigation. Historical feedback can propose changes to method selection or policy, which must be replayed and versioned before activation.

The initial ensemble should be deliberately small. Automatic weighting or learned selection is a later option if enough representative outcomes support it. The product's value hypothesis is better evidence and earlier appropriate action across datasets, rather than the number of algorithms it can invoke.

### Existing foundations to reuse or extend

The mathematics and much of the implementation already exist. SciPy provides statistical tests and summary statistics; statsmodels covers statistical modeling and time-series analysis. River includes online anomaly and drift detection, while ruptures focuses on offline change-point detection. ADTK already provides a composable time-series detection toolkit. JavaScript also has foundational libraries such as Simple Statistics. These are candidates for reuse or comparison, not a completed dependency or maintenance assessment. [SciPy](https://docs.scipy.org/doc/scipy/reference/stats.html), [statsmodels](https://www.statsmodels.org/stable/index.html), [River](https://riverml.xyz/latest/api/overview/), [ruptures](https://centre-borelli.github.io/ruptures-docs/), [ADTK](https://adtk.readthedocs.io/en/stable/), [Simple Statistics](https://simple-statistics.github.io/).

Before creating a new package, assess whether an adapter or contribution to an existing project would meet the need. Decide the first implementation language after inspecting UsageTap and intended adopters. Avoid maintaining parallel language implementations at the outset.

**A particularly close existing toolkit is Darts:** it already combines forecasting, anomaly detection, model ensembles, probabilistic forecasts, external covariates, and backtesting behind common interfaces. StatsForecast is another foundation for classical forecasting, and statsmodels includes model-based simulation. A new algorithm collection or uniform fit/predict interface would therefore not be novel. The first evaluation should test whether existing packages plus thin adapters meet our needs. [Darts](https://unit8co.github.io/darts/), [StatsForecast](https://nixtlaverse.nixtla.io/statsforecast/index.html), [statsmodels simulation](https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAXResults.simulate.html).

### Proposed modules and scope

| Module | Question answered | Candidate methods |
|---|---|---|
| Describe | What does the observed data look like? | Summary statistics, robust dispersion, quantiles, and rolling windows |
| Forecast | What values or ranges should we expect next? | Seasonal naive, local trend, exponential smoothing, ARIMA/SARIMA, and regression with related measurements |
| Simulate | What future paths are plausible under stated assumptions? | Monte Carlo sampling from a fitted model, appropriately structured bootstrap samples, and specified scenarios |
| Detect | What observed behavior departs from the reference? | Shewhart/Nelson, CUSUM/EWMA, residual-based detection, and distribution comparisons |
| Compare and replay | Which method helps for this dataset and response objective? | Walk-forward evaluation, interval coverage, episode-level detection delay, false-action burden, and runtime |

Monte Carlo here means the simulation technique, not the vendor reviewed earlier. It samples from a specified model or uncertainty assumptions; it is not by itself a forecasting model or proof of an anomaly. Simulated trajectories can estimate quantities such as the chance of exhausting an allowance before replenishment or a distribution of time until a limit is reached. Preserve relevant temporal and cross-variable dependencies in those trajectories. Report model assumptions and simulation uncertainty, and validate estimated probabilities against subsequent observations.

Keep a **forecast interval**, a **simulated event probability**, and **current anomaly evidence strength** distinct. None automatically determines business urgency or authorizes an action.

Start with the rules needed by UsageTap, then add methods when a concrete use case and reference test justify them:

- Descriptive foundations: mean, variance, quantiles, median absolute deviation, and rolling windows, reusing established implementations where practical.
- Forecasting: a seasonal-naive comparator, UsageTap's existing forecast if reusable, and one alternative statistical model through an adapter.
- Simulation: one model-based or suitably structured bootstrap sampler with a reproducible seed, forecast paths, quantiles, and an explicit horizon.
- Process signals: Shewhart limits and the eight Nelson rules, with explicit baseline definitions and triggering observations.
- Accumulated change: CUSUM and EWMA with documented initialization and parameter meanings.
- Distribution comparison: location/spread/tail changes, a supported two-sample test, and an effect-size measure such as Wasserstein distance through suitable implementations.
- Relationship primitives: rates, ratios, and residuals against an externally supplied expected value. Dataset joins and automatic relationship discovery stay outside the initial core.

This is a candidate roadmap, not a requirement to ship all methods in the first release. Keep implementations behind adapters so consumers can swap methods without adopting unrelated heavy dependencies. Select or combine methods based on held-out performance and applicability, rather than assuming a larger ensemble is always better. Forecast error and anomaly detection quality require separate evaluation.

### The contribution: inspectable forecast, simulation, and detection contracts

Forecast outputs identify the training cutoff, forecast origin, horizon, expected values, prediction intervals where supported, and any assumed future inputs. Simulation outputs add the sampling method, seed, path count, model assumptions, and event definitions. Replay must not supply a model with future measurements that would have been unknown at the forecast origin.

Every detector should return a structured observation describing the method and version, affected interval or samples, observed statistic, reference or control limits, direction, magnitude, sample counts, and applicability. Include detector-specific evidence strength where justified, with a reason and score semantics. Report warm-up, insufficient data, and invalid baseline states explicitly. Do not manufacture a universal confidence percentage from incompatible statistics.

Define whether the current observation is evaluated before updating the baseline, how missing and repeated timestamps are handled, and whether a detector supports streaming or only batch evaluation. For streaming-capable methods, historical replay must use the same update semantics as live evaluation. Offline change-point methods must not be presented as having detected a change before later evidence arrived.

The package should work locally without a model API or hosted service. Charts, the observation blotter, chat, MCP, business policies, and action execution consume its results through separate adapters or application layers. This preserves the earlier distinction: the library reports evidence; an application decides what action the evidence warrants.

An additional adoption hypothesis is affordability: let an existing application add forecasting, simulation, and signals without adopting a separate analytics platform or its capacity minimum. Compare total operating and integration cost against both existing platform capacity and established open-source packages. See the [market review](market-review.md) for the Fabric pricing scenario; algorithm availability alone does not establish this advantage.

### First acceptance criteria

Extract or adapt one UsageTap forecast and detector, compare with a simple forecasting baseline, add one supported simulation method, and integrate their structured outputs back into the existing view. Demonstrate both unexpected observed usage and a prospective allowance-exhaustion scenario. Validate statistics against independent reference fixtures and applicable published definitions; check interval coverage on held-out history and reproducibility of seeded simulations. Add boundary cases for constant data, missing values, insufficient baseline history, and exact rule thresholds. Then show that another small application can consume the same outputs without importing UsageTap's UI or business logic.

The open-source release includes readable examples, documented assumptions, an
MIT license, constrained dependencies, and a public contribution workflow.
Useful adoption and successful integrations matter more than the number of
algorithms in the package.
