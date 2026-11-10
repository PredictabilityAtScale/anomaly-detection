# Historical anomalies: review validation

Review build **0.7.0.dev0**, based on current main/released 0.6.0
`b30eec0cbce0c2e275b63943a2d4bd34c43f35ea`. These are development artifact
checks, not a released version, deployment certification or forecast accuracy
claim. No tags/releases/assets were created or replaced.

| Check | Observed result |
| --- | --- |
| Python 3.12.9 source suite | **417 passed in 47.52s**: all previous 381 tests plus 36 new evidence regressions. |
| Installed wheel, clean environment outside checkout | **36 passed in 6.47s**, plus public Guard/forecast/evidence smoke, entry points and dependency checks. |
| Installed sdist, separately built/installed outside checkout | **36 passed in 7.32s**, with the same smoke/entry/dependency checks. |
| Linux x86_64 Lambda / Python 3.12, network disabled | Hash-required offline installation and Guard, forecast, evidence and sparse benchmark passed. Four bridge maximum-size evidence cases completed in **1.60s total**; each call plus serialization asserted under four seconds. |
| Metadata | Wheel/sdist passed `twine check --strict`. |
| CapabilityKit | Format, validate, compile and targeted review performed; status remains implemented and release/adoption gaps are explicit. |
| Publication gate | `scripts/release.py check-version --tag v0.7.0.dev0` refuses the development tag, as intended. |

The Linux runtime image was
`public.ecr.aws/lambda/python@sha256:21c21867e3c999a5b9471c16e089bb44a4da0e4e4104a26056799dacadeac278`,
executed with `--platform linux/amd64 --network none`. Runtime dependencies
were installed from a wheelhouse using the exported lock and `--require-hashes`.
No source package was mounted into the runtime; only the installed package and
public smoke scripts were supplied. This Windows host used equivalent native
Docker invocations to the checked-in Linux CI script.

The tested development wheel SHA-256 is
`858cb2168fdbeb933532d696295b468bfbc219775192c94848009a8778330d17`;
sdist is `add86f43f04d7df9775649b4cf33121c945e84e3d4c215c0c24e842204c93b9f`.
These identify local review artifacts only. Future CI/release builds must record
their own source revision and hashes; these are not consumer adoption pins.

## Reproduce

```text
uv sync --locked --extra dev --python 3.12
uv run python scripts/export_forecast_schemas.py
uv run pytest -q -p no:cacheprovider
uv build
uv export --locked --no-dev --no-emit-project --output-file dist/runtime-dependencies.txt
uv run python scripts/verify_distribution.py --python 3.12
```

The normal CI build also records its exact source/checksums, executes installed
checks on supported Python versions and runs `bash scripts/verify_lambda.sh`.
The new evidence smoke is included in those installed and offline checks. Local
test logs and bundles are under ignored `.tmp`; customer evidence is absent
from artifacts and publication inputs. The first local full-suite attempt had
a missing temporary parent directory; creating it resolved fixture setup errors.
A checksum test was made independent of the stable-tag gate so development
versions can test byte-integrity failures without authorizing a release.

## What the regressions establish

The public real-library tests cover auto and explicit seasonality, include and
robust, changed targets/suffixes, appends, frozen origin, reference-only and
provisional scores, calibrated triggers, first availability of every native
pattern rule, quiet/zero/spike/drop/sustained changes, baseline caution,
calibration exclusions, signed versus clamped expectations, partial tails,
missing/internal gaps, all four bridge interval/horizon/training caps at 6000
positions, deterministic output, schemas, adapter version refusal, one-analysis
reuse, unchanged forward arrays and failures before/during evidence projection.

The manual source review checked calibration rebuild timing and exclusion
annotations against `recipes.py`, merged-window/first-detection behavior against
`evidence.py`, and the new projection against those primitives. Earlier point
rows retain native point-time scores; retrospective annotations are separate.
Pattern peak/direction summaries stop at first detection. This is the primary
agent's self-review, not an independent reviewer approval.

Representative reconciled customer histories, detection outcomes, real UsageTap
transport/UI tests and a separately verified stable 0.7.0 release are still
needed for adoption. Nothing here changes Current + UsageTap defaults or saved
Guard/notification preferences, establishes detection precision/recall, or proves
forecast accuracy. See the [API spec](historical-anomalies.md) and
[consumer migration](usagetap-forecast-migration.md).
