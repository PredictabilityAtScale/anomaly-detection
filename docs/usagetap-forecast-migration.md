# UsageTap migration to public forecasting

This is an implementation handoff, not an authorized UsageTap edit, deployment,
release or switch of default engine. Reference snapshot:
`b8b54412f550a3509bffe2ceb9dc1361c1ef37be`, promotion
[PR 460](https://github.com/PredictabilityAtScale/usagetap/pull/460).
Leave that release branch untouched. Apply migration in a separately reviewed
UsageTap change after the upstream forecast release exists.

## Required upstream release

Use **Anomalyzer 0.6.0**, an additive minor release with `forecast-v1`.
Keep analysis schema 1.0/1.1, distribution-v1 and existing Guard recipes compatible.
An existing 0.5.0 artifact cannot acquire this API retroactively. Verify the
0.6.0 immutable release, supported-Python checks, installed wheel/sdist checks
and offline Lambda evidence through [the release guide](releases/README.md)
before adopting the downloaded assets.

The upstream release must provide the reviewed immutable source revision,
`anomalyzer-0.6.0-py3-none-any.whl`, sdist, `SHA256SUMS`,
`release-manifest.json`, `runtime-dependencies.txt`,
`requirements-offline.txt` and
`requirements-guard-py312-linux-x86_64.txt`. The last asset pins the release URL
and wheel SHA-256 plus every runtime dependency's reviewed hashes. Use
`scripts/release.py create/verify` with the exact revision after the build;
never invent or copy a hash from another artifact/version. Verify offline Linux
x86_64 / Python 3.12 bundling and the four-second transport budget on the built
artifact. Current local Windows timing is not Lambda certification. No new
runtime dependency is required by forecasting.

## Exact code migration

1. In UsageTap's **new migration branch**, replace
   `amplify/functions/monitoring-statistics/requirements.txt` with the new
   reviewed release lock. Check its SHA-256 against the downloaded immutable
   asset, including transitive hashes. Update `LOCK_SHA256`, expected version,
   reviewed-lock error text and `bundle.json` engine metadata in
   `scripts/build-monitoring-statistics.py`. Update version checks in
   `scripts/verify-monitoring-statistics.py` and provenance documentation.
   Rebuild the Linux asset with hashes required and verify it offline.
2. Replace the manual inference/analyze/refit/projection implementation in
   `amplify/functions/monitoring-statistics/usage_forecast.py` with the reviewed
   [`examples/library/usagetap_forecast.py`](../examples/library/usagetap_forecast.py).
   It validates the same transport, maintains the expected 0.6.0 engine pin,
   and makes **one** `forecast_series` call. It keeps interval caps hour 168,
   day 90, week 26, month 24; training windows 1344/56/52/36; max points 6000;
   adjustment -50 through +200; lower bound zero and the existing 2.5-second
   cooperative/context budget. Remove all bridge imports of private inference,
   trend and baseline primitives and its direct `analyze` call.
3. Update the strict `result.model.engineVersion` check from 0.5.0 to the
   reviewed 0.6.0 pin in
   `amplify/functions/usage-forecast-function/anomalyzerForecast.ts`. Preserve
   array/type/index/method validation, authenticated numeric-only Lambda
   transport, `maxAttempts: 1`, `AbortSignal.timeout(4_000)` and explicit failure.
   The legacy successful response still has exactly `contract`, `status`,
   `expected`, `eligible`, `predicted`, `trend`, `outlierIndices`, `model`, with
   N/N/H/N+H lengths. The legacy model has method, label, engineVersion,
   trendKind, seasonLength, seasonalityStatus and notes. Unavailable remains
   `{contract: "usage-forecast-v1", status: "unavailable", reason: CODE}`.
4. Update real-library forecast tests in
   `amplify/functions/monitoring-statistics/test_usage_forecast.py` for the
   new engine version and deliberate historical selection semantics below.
   Keep tests for insufficient history, original-index alignment, zero,
   fixed-horizon prefixes and scenario adjustment. Add changed-suffix and
   appended-prefix cases across lag selection, bounded training and calibration.
   Exercise all horizon maxima and explicit unavailable reasons through the
   TypeScript adapter, then rebuild and reverify the actual Lambda asset.
5. Keep method handling in `shared/usageForecastModel.ts`,
   `amplify/functions/usage-forecast-function/handler.ts`,
   `src/lib/usageForecastService.ts` and `src/app/usage/page.tsx`. Both methods
   must use identical filters, dates, actual values and horizon; include engine
   selection in frontend/backend caches and chart/export provenance. Preserve
   the Current comparison default, the selector beside Forecast assumptions,
   and explicit unavailable UI. Carry fingerprint and limitations through
   legacy notes or an explicitly reviewed metadata extension. Reconcile
   customer history before comparing outputs. Update `ANOMALY_DETECTION.md`.
6. Run full UsageTap tests/build and offline verification, including unchanged
   Guard regression fixtures. Keep Guard profiles, recipes, saved notification
   rules and `shared/anomalyDetection.ts` semantics unchanged. Do not silently
   substitute Current when Anomalyzer fails. Comparison rollout continues;
   changing the default requires representative chronological outcome evidence.

The [standalone installed forecast smoke](../examples/library/forecast_smoke.py)
also runs from `scripts/verify_distribution.py`, alongside the existing Guard
smoke. The migration example intentionally refuses a 0.5.0 runtime. Tests exercise
its pin against the versioned source checkout.

## Intended numerical and historical differences

The public forward scenario fits only the latest bounded observations, with no
historical detector replacements fed back into it. Robust trend screening and
trimmed reference construction remain distinct and inspectable. Discovery uses
the bounded selection before one reserved point, rather than the old bridge's
14-calibration-plus-one reserved tail and 28-point confirmation. Inferred lag,
screening and predictions can therefore differ; old scenario arrays are not a
permanent numerical contract. The private 30-bucket full-scenario replay happens
to retain both old policy totals; that is sensitivity evidence, not accuracy.

Historical selection now freezes at the **original supplied history origin**,
instead of selecting from a moving trailing fit and back-applying that lag.
Auto history publishes no expected values until
`K=min(max_training_points,max_inference_points)` complete buckets; eligibility
starts at K+14. With bridge settings K is 768 hourly, 56 daily, 52 weekly and
36 monthly. A shorter series may return a scenario with all historical
expectations null/eligible false. Earlier plotted trend remains a fitted current
model component and is never used to fabricate historical evidence. The public
trend is signed; the bridge clamps its chart copy to zero. Seasonal offsets are
signed and intentionally absent from the legacy response shape. All outlier
indices refer to full original input positions, including hidden warm-up.

## Transport changes needed for distinct completeness

No wire-shape change is required for the compatibility migration above, apart
from coordinating the engine version pin. It must retain the existing limitation:
trailing nulls are assumed partial, internal nulls unavailable. The public library
itself never assumes null means partial.

To gain the full public completeness/calendar contract, UsageTap must separately
version or explicitly extend its bridge. Transmit `period_statuses` alongside
numeric/null values using actual `DatedSeriesPoint.dataStatus`/`isPartial`, and
include bucket starts, timezone and interval from the authorized aggregator.
Complete zero is zero; missing is null/missing; known unfinished periods are
partial with optional numeric actual. Do not log or transmit identities merely
to forecast. The Python bridge can pass those fields directly to
`ForecastDataset`; a missing tail then correctly returns `missing_history`.
Update TS/Python validators, caches/provenance, UI reason messages and export
tests together. A future gap model must declare a supported method; this release
neither fills gaps nor infers completeness from reduced raw-call exports.
