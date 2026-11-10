# UsageTap: independent forecast and anomaly detector

This is a consumer migration handoff. Library publication does not deploy UsageTap;
consumer integration belongs in a separate UsageTap PR.
UsageTap deployed Anomalyzer **0.6.0** through PRs #461/#462 and master merge
`bc6bc783b300c4b4665594fb4697f5ee281846bf`. Its existing Python statistics Lambda
calls one public `forecast_series`; there is no hosted API service. Keep that
deployment and `usage-forecast-v1` usable while reviewing this extension.

## Artifact and compatibility contract

Use **0.7.0**, an additive minor release: `forecast-v1` plus opt-in
`historical-anomalies-v1`. The adapter refuses the earlier **0.7.0.dev0**
review build. Verify the immutable stable release before adoption. Preserve
v0.6.0 at `b30eec0cbce0c2e275b63943a2d4bd34c43f35ea`, its immutable assets and
all prior releases. Never replace a 0.6.0 asset to add this feature.

Before adoption, verify the published release with exact source
revision, `anomalyzer-0.7.0-py3-none-any.whl`, sdist, `SHA256SUMS`,
`release-manifest.json`, `runtime-dependencies.txt`, `requirements-offline.txt`
and `requirements-guard-py312-linux-x86_64.txt`. Verify installed wheel/sdist,
supported Python CI and offline Linux x86_64/Python 3.12 Lambda checks. Pin the
actual downloaded bytes and every transitive dependency hash. No provisional
hash or development artifact is a release pin. See the [release guide](releases/README.md).

Existing callers may omit `historical_anomalies`. Forecast arrays, decomposition,
horizon prefixes and adjustment semantics stay unchanged; the new result member
is null. Default native settings reproduce the historical analysis already used
in 0.6.0. Existing analysis/distribution APIs, Guard recipes, profiles, saved
evidence and notification preferences retain their behavior. Fingerprints and
engine provenance are versioned metadata, not cross-version numeric identity.
Old 0.6.0 request models reject the new config: negotiate support and coordinate
the exact engine pin. Never silently ignore the requested extension.

## One-call compatibility adapter and schemas

The concrete [adapter example](../examples/library/usagetap_forecast.py) keeps
`usage-forecast-v1`. Without `historicalAnomalies`, successful keys remain exactly
contract, status, expected[N], eligible[N], predicted[H], trend[N+H], outlierIndices
and model. Model retains method, label, engineVersion, trendKind, seasonLength,
seasonalityStatus and notes. Failure remains
`{contract:"usage-forecast-v1",status:"unavailable",reason:CODE}`. The example
pins **0.7.0** and may be copied after that release is verified; the currently
deployed 0.6.0 bridge remains usable until then.

Explicit opt-in request with anonymous synthetic observations:

```python
event = {
    "operation": "forecast", "contract": "usage-forecast-v1",
    "values": [100.] * 80 + [400.] + [100.] * 9,
    "interval": "day", "horizon": 30, "trendAdjustmentPct": 0,
    "excludeExtremeOutliers": True,
    "historicalAnomalies": {
        "schema_version": "historical-anomalies-v1",
        "point_threshold": 3, "cusum_k": .5, "cusum_h": 5,
        "moving_range_threshold": 3.686, "scale_floor": 1e-8,
    },
}
# After verified release adoption, in the existing statistics Lambda:
# response = forecast_usage(event, context)
# response["historicalAnomalies"]["points"][80]["triggers"] == ["point"]
```

The adapter maps this member to `config.historical_anomalies` in ONE public
`forecast_series` call and appends `historicalAnomalies` with
`result.historical_anomalies.model_dump(mode="json")` only on explicit opt-in.
Use the [forecast request schema](../schemas/forecast-request.schema.json) and
[result schema](../schemas/forecast-result.schema.json). The bridge opt-in object
is exactly the [extension request schema](../schemas/historical-anomalies-request.schema.json);
its response member is exactly the [extension result schema](../schemas/historical-anomalies-result.schema.json).
The [field/threshold/causality specification](historical-anomalies.md) is normative.
No private imports, second `analyze` call or consumer residual-scale estimation.

The example preserves horizon caps **168/90/26/24**, forward training caps
**1344/56/52/36**, inference cap **768**, max points **6000**, lower bound **0**,
adjustment **-50..200**, and the **2.5-second** cooperative/context budget.
TS retains **maxAttempts:1**, **4000ms** abort and explicit failure messages.
Historical auto selection still starts at the supplied original origin, with
K=768/56/52/36; expected is absent before K and calibrated maturity starts K+14.
Do not cut input to latest30 or invent a missing training prefix.

Legacy null tails are assumed partial only in this compatibility adapter.
Internal nulls return missing_history. The public API requires explicit
period_statuses for nulls and rejects missing periods without filling. A separate
transport extension is needed for actual aggregator completeness, bucket
starts and timezone. Complete zero stays zero; numeric partial tails remain
partial in the public API. Do not infer missing/partial from absent call rows.

## Exact UsageTap changes after release

1. On a separately reviewed UsageTap branch, update monitoring-statistics
   requirements and reviewed lock hash, `LOCK_SHA256`, version checks,
   reviewed-lock error text and bundle engine metadata in
   `scripts/build-monitoring-statistics.py` and `scripts/verify-monitoring-statistics.py`.
   Rebuild the actual hashed offline Linux bundle. Copy the adapter or its small
   opt-in changes into `amplify/functions/monitoring-statistics/usage_forecast.py`.
2. Extend `amplify/functions/usage-forecast-function/anomalyzerForecast.ts`
   request/result types and validators for the exact nested evidence version;
   update its 0.6.0 pin to verified 0.7.0. Validate N rows/original indices,
   finite nullable scores, maturity/trigger rules, pattern detection/availability
   coordinates and resolved thresholds. Signed native expected/residual/score
   cannot use its current nonnegative forecast validator. Public trend stays
   signed; only the legacy chart copy is clamped. Missing/failed evidence means
   detector unavailable even when a forecast scenario is available.
3. Add independent exploratory detector selection in `shared/usageForecastModel.ts`,
   the forecast handler, `src/lib/usageForecastService.ts` and `src/app/usage/page.tsx`.
   For **Current forecast + Anomalyzer detector**, keep Current's scenario and
   make one statistics-Lambda call for native evidence. If both choose Anomalyzer,
   consume both from that same call. Anomalyzer forecast + UsageTap detector keeps
   the existing UsageTap statistical path. Current + UsageTap preserves deployed
   behavior. Include full original history once and record native settings.
4. Add a separate native evidence consumer adapter. Keep shared `detectAllAnomalies`
   and its Guard users unchanged. Native qualification requires available,
   complete, calibrated points with `"point"` in triggers. Retain minimum value,
   absolute deviation, percent movement and low-volume gates, with explicit
   warning/critical policy, using native observed/reference and returned score.
   Never recompute z-scores from forecast Expected. Preserve saved notifications.
5. Extend real-library Python/TS tests for opt-in/legacy shape, version refusal,
   indices, signed references, unavailable evidence and no silent fallback.
   Run full UsageTap tests/build and unchanged Guard fixtures. Verify response
   sizes and the four-second transport budget in the actual bundle. Update
   `ANOMALY_DETECTION.md`.

Native point_threshold defaults to 3; UsageTap's deployed warning z cutoff is
2.5 and critical cutoff 4, with adaptive low-volume thresholds. These are different
procedures. Choose the native threshold explicitly (for example 2.5 if that is
the reviewed policy), record it and use native triggers for qualification.
Applying native score >=4 for critical is consumer severity policy, not a
probability. Business percent/low-volume gates may remain stricter but cannot
create a native trigger. Keep percent denominators, zero and signed-baseline
policy explicit. Do not substitute display-clamped expected for native reference.
Patterns need their own presentation policy instead of a spike/drop-only adapter.

## Consumer UX, cache and export contract

Inside **collapsed Forecast assumptions**, use two compact vertically stacked
rows in the **same existing column**:

```text
Forecast method   [Current | Anomalyzer]
Anomaly detector  [UsageTap | Anomalyzer]
```

Do not add horizontal columns or combine every pairing into a long dropdown.
Defaults remain **Current forecast + UsageTap detector**. Selection is exploratory
and changes neither Guard nor saved notifications/preferences. Until a released
verified artifact supports this evidence API, keep Anomalyzer detector
**unavailable**, with an explanation. Never silently use UsageTap and label it
Anomalyzer, nor switch forecast methods on failure.

Frontend/backend cache keys and chart/export metadata must identify **both**
choices, exact versions, evidence contract, full input fingerprint/origin and
finalized statuses, resolved detector settings, native origin/calibration
fingerprints, forward/historical fit windows, lower bound and scenario adjustment.
Origin fingerprint alone does not identify later observations. Use identical
filters, dates, actuals and horizon for comparisons. Exports preserve original
indices and point/pattern availability, including hidden warmup history.

When references differ, label **“Anomalyzer historical detector reference”** and
show it in incident details/export, retaining selected forecast Expected as its
own series. Even an Anomalyzer scenario uses a separate trailing fit from its
historical detector. Do not imply displayed Expected is the detector reference
unless it actually is; lower-bounded display expectation can differ from signed
native expectation too. Label pattern onset and first detection separately, so
a completed window never appears known at its start.

## Evidence limits

Only anonymized synthetic inputs are committed. Local customer evidence has
conflicting raw/chart sources, missing earlier training history and different
coverage/completeness. Do not merge them, fabricate the earlier 56-bucket prefix
or infer forecast accuracy from a fitted scenario/screenshot. Chart context had
86 finalized daily buckets with latest30 displayed; it is not a reproducible
complete training fixture. No default change follows from that context.

Robust screening may mistake sustained changes for contamination; compare
include/robust and chronological outcomes. Readiness caution, evidence strength,
statistical qualification, business materiality, severity, confidence, accuracy
and health are distinct. No forced growth or calibrated forecast confidence
interval is claimed. Validation evidence accompanies the review PR; release
and consumer adoption remain separate reviewed actions.
