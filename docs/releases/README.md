# Release and use Anomalyzer

Anomalyzer is a normal Python dependency. This checkout prepares version
**0.5.0** ([release notes](0.5.0.md), [UsageTap distribution-detector handoff](../distribution-detection.md)).
The latest published release at preparation time is 0.3.0; the new version is
a source/build candidate until the publication workflow below completes.
Nothing is uploaded to PyPI by this workflow. GitHub Releases is the
initial distribution channel. Publishing the library does not integrate it into
UsageTap Guard.

The original `v0.2.0` tag remains an unpublished candidate after a draft-lookup
failure. Its tag and draft are retained; the fixed publication helper ships in
`v0.2.1`; that was the first published release.

## Four terms

| Term | Meaning |
| --- | --- |
| Wheel (`.whl`) | Ready-to-install Python package. Use this for Guard. Anomalyzer's wheel works across supported operating systems; its dependencies may need platform-specific wheels. |
| Source distribution (`.tar.gz`, or sdist) | Source needed to build the package. Useful for rebuilding and inspection; installation also needs the declared build backend. |
| Version tag (`v0.5.0`) | Permanent Git name for the exact source revision released. It must match `_version.py`; never move or reuse it. |
| Dependency pin | An exact version or artifact URL, plus a SHA-256 fingerprint. A hash checks that downloaded bytes match the intended artifact. Pin transitive dependencies too. |

The package supports Python 3.11, 3.12 and 3.13. Version lives only in
[`src/anomalyzer/_version.py`](../../src/anomalyzer/_version.py); Hatchling reads
it for package metadata and the public `__version__` imports it.

## One-time owner setup

1. Review and merge the packaging PR into `main` after CI passes.
2. In GitHub **Settings → General → Releases**, enable **release immutability**.
   The owner's final publish command refuses to proceed without it. On publication GitHub seals
   the tag and assets. See [GitHub's instructions](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes).
3. Ensure GitHub Actions is enabled and permitted to use the actions listed in
   `.github/workflows/ci.yml` and `release.yml`. The checks use `contents: read`;
   only the final publish job uses `contents: write` through GitHub's automatic,
   short-lived `GITHUB_TOKEN`. No personal token, PyPI account or AWS credentials
   are required by CI. CI stages a draft; the final command below runs under the
   owner's existing GitHub CLI login. GitHub's immutability-settings endpoint
   needs admin-read access, which the minimal workflow token cannot obtain.
4. Recommended: add a repository tag ruleset for `v*` that restricts tag creation
   to release maintainers and blocks deletion/updates. Immutability protects the
   tag after publication; a ruleset protects it while checks are running too.
5. On your machine install Git, Python 3.12 and [uv](https://docs.astral.sh/uv/),
   and sign into GitHub CLI with your own account (`gh auth login`) if you use
   the optional CLI commands. Never paste credentials into this repository.

Before choosing a version, inspect existing tags/releases and the immutability
setting. Never reuse a published version or move a version tag.

## Release 0.5.0

Run these commands from a clean checkout of the merged `main` branch. Commands
work in PowerShell or Bash except where explicitly labelled.

```text
git switch main
git pull --ff-only
git status --short
git fetch --tags
git tag --list
gh release list --repo PredictabilityAtScale/anomaly-detection
uv sync --locked --extra dev
uv run pytest -q
uv run python examples/run_demo.py
uv run python examples/run_agentic_demo.py
uv run python scripts/release.py check-version --tag v0.5.0
```

`git status --short` must be empty. If `v0.5.0` already exists, stop and choose
the next unused version through a PR. Otherwise create an annotated tag on the
reviewed commit and push it (do not use `--force`):

```text
git tag -a v0.5.0 -m "Anomalyzer 0.5.0"
git push origin v0.5.0
```

Open the repository's **Actions → Release** run. It runs all tests on
3.11/3.12/3.13, builds the sdist and its wheel once, checks metadata and archive
contents, installs both artifacts in clean environments on all supported Python
versions, and tests a bundled Linux x86_64/Python 3.12 consumer in AWS's Lambda
image. The runtime container has networking disabled. Only after every job
passes does it create a draft and attach the tested files. Publication is one
explicit owner step, using the already tested files:

```text
git switch --detach v0.5.0
gh release download v0.5.0 --repo PredictabilityAtScale/anomaly-detection --dir release-v0.5.0
git rev-parse HEAD
python scripts/publish_release.py --dist release-v0.5.0 --tag v0.5.0 --revision <full-SHA-printed-above> --publish
git switch main
```

Replace `<full-SHA-printed-above>` with the commit printed by Git. The helper
requires the owner's authenticated `gh` session with admin-read access; it checks
the actual repository immutability setting, remote tag, checksums and existing
draft bytes before publishing. It never rebuilds. GitHub then seals the tag and
all assets together. If GitHub CLI reports a permission problem, use the owner
account (`gh auth switch`) or sign in as that owner; do not add a token to CI.
Publication also triggers `verify-published`: it downloads and checks the sealed
assets, installs the exact public wheel URL with its hashes in a clean consumer,
and repeats the offline Linux/Python 3.12 bundle test. Check that job before
adopting the release. Transient download failures can be rerun without changing
any release asset.

Assets live under [GitHub Releases](https://github.com/PredictabilityAtScale/anomaly-detection/releases),
in the release for the selected tag:

- `anomalyzer-0.5.0-py3-none-any.whl` and `anomalyzer-0.5.0.tar.gz`.
- `release-manifest.json`: version, tag, full source commit, file sizes and hashes.
- `SHA256SUMS`: hashes of all assets including the manifest (except itself).
- `runtime-dependencies.txt`: exact dependency versions and accepted hashes
  exported from the repository lock, including platform markers.
- `requirements-guard-py312-linux-x86_64.txt`: those dependencies plus the exact
  GitHub wheel URL and its hash. This is an installable starting lock for Guard.
- `requirements-offline.txt`: the same pins using `anomalyzer==0.5.0` so pip can
  install entirely from a local wheelhouse.

CI's **Artifacts** section also holds `release-dist-<commit>` and the
`lambda-consumer-<commit>` verification report, including the actual container
image digest, chosen dependency wheel hashes and offline smoke result. CI artifacts expire; Release assets are
the durable distribution channel. Branch/PR artifacts are candidates, not
published releases; their manifest has a null tag and their prospective release
URL will not work until that version is released.

## Failures and reruns

Before publication, failures leave no release or an unpublished draft. Fix
environment/setup failures, then use **Re-run
failed jobs** on the same Actions run. The publish job downloads the already
tested CI artifact; it never rebuilds. A partial draft resumes by verifying
existing bytes and uploading only missing assets. It refuses mismatched or
unexpected assets. A complete matching immutable release is a successful no-op
on rerun. If the final owner command fails, fix its setup issue (for example
enable immutability) and rerun that command with the same downloaded assets.
Never delete/replace release assets to make a rerun pass.

If source changes are needed after a tag was pushed, use a new version/tag even
if the old tag failed; do not move the tag. If build/check jobs are rerun, every
new artifact goes through the checks again before publication. If CI artifacts
have expired, rerun the full workflow on the unchanged tag; if an existing
release's bytes differ, leave it untouched and create a new version.

## Subsequent releases

Create a branch/PR, change only `_version.py` to the next unused `X.Y.Z` version,
run `uv lock`, document changes in the PR, and run the same checks. Merge, then
follow the release steps with the new tag. The package is alpha: review
behavior and contracts before upgrading even a minor version. Avoid compatibility
promises that the current alpha API cannot support.

## Use the release from Guard

Guard's statistics Lambda uses Linux/Python 3.12. Keep installing packages in the
application build, and ship dependencies alongside its handler. Production
analysis needs no checkout, CLI, MCP server, hosted Anomalyzer service or network.

1. Download the chosen Release's assets and verify `SHA256SUMS`. For example:

   ```text
   gh release download v0.5.0 --repo PredictabilityAtScale/anomaly-detection --dir release
   ```

   In Linux/WSL/Bash: `(cd release && sha256sum --check SHA256SUMS)`.
   In PowerShell, `Get-FileHash release/anomalyzer-0.5.0-py3-none-any.whl -Algorithm SHA256`
   shows the wheel's hash; compare it with the manifest/checksum file. Also check
   the manifest's tag and commit against the intended release. Hashes identify
   bytes; use the trusted GitHub repository/release as their source.

2. Commit `requirements-guard-py312-linux-x86_64.txt` into Guard's dependency
   inputs. Its final requirement has this form, with a real generated hash:

   ```text
   anomalyzer @ https://github.com/PredictabilityAtScale/anomaly-detection/releases/download/v0.5.0/anomalyzer-0.5.0-py3-none-any.whl --hash=sha256:<generated-wheel-hash>
   ```

   Install the actual file, not this placeholder. It also pins Pydantic,
   pydantic-core, annotated-types, typing-extensions and typing-inspection.
   The pinned tzdata package also supplies timezone data on minimal Linux runtimes. When combining with Guard's
   other requirements, resolve one application lock with all requirements and
   hashes (for example `uv pip compile --python-version 3.12 --python-platform
   x86_64-manylinux_2_28 --generate-hashes requirements.in -o requirements.txt`).
   Review dependency conflicts instead of installing separate inconsistent sets.

3. Build in a **Linux container matching Python 3.12 and the Lambda architecture**.
   Pydantic uses the native `pydantic-core` extension. Do not copy a Windows
   `.venv` or dependency directory into Lambda. The tested example uses x86_64;
   confirm Guard's configured architecture. For arm64, change the build platform
   and verify on arm64 before deployment. See [AWS packaging guidance](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html).

   For an exact local reproduction in Linux/WSL, put the downloaded release
   assets in this repository's fresh `dist/` directory and run:

   ```bash
   bash scripts/verify_lambda.sh
   ```

   This uses Docker and writes `.tmp/lambda-consumer/package` and a hash-verified
   wheelhouse. The build has network access; the installed runtime check has
   `--network none`. The script deliberately refuses to reuse an existing package
   directory. The equivalent Guard build steps, inside a Linux/Python 3.12
   container, are:

   ```bash
   python -m pip download --only-binary=:all: --require-hashes \
     -r requirements-guard-py312-linux-x86_64.txt -d wheelhouse
   # Use the accompanying offline lock to avoid direct-URL downloads during install.
   python -m pip install --no-index --find-links wheelhouse --only-binary=:all: \
     --require-hashes -r requirements-offline.txt --target package --no-compile
   # Add Guard's handler and all its other locked dependencies to package/.
   # Zip the CONTENTS of package/, so imports and the handler are at zip root.
   ```

   Use the same complete application lock and offline equivalent when adding
   Guard's other dependencies. Retain the wheelhouse, lock, application source
   revision and deployment artifact for reproducible rebuilds and rollback.

4. Replace the vendored subset with imports from `anomalyzer`: `analyze`,
   `analyze_series`, `analyze_relationships`, `get_case`, `replay_policy` (also
   `analyze_dataset`). Typed request/result models are exported at package root;
   settings, datasets, policies and detailed contracts live in
   `anomalyzer.contracts`. See the self-contained
   [`guard_smoke.py`](../../examples/library/guard_smoke.py) for actual calls to
   all APIs, recipes, point/pattern evidence, relationships, cases and policy
   replay. Run it with `--expect-prefix <installed-environment-or-package-dir>`.
   It blocks socket access and verifies that imports come from the bundle.

   For 0.5.0 population detectors, import `compare_distributions`,
   `monitor_distributions` and `compare_seasonal_distributions`; their typed models also live at package root and in
   `anomalyzer.distribution_contracts` (seasonal models live in
   `anomalyzer.seasonal_distributions`). Follow the
   [UsageTap handoff](../distribution-detection.md) for call/report samples,
   quantity weights, fixed references, finite testing families and migration
   checks, plus the [explicit seasonal selection guide](../seasonal-distributions.md).
   Adoption does not require replacing the existing residual detectors.

5. Map Guard's metrics and explicitly declared relationships to requests; inspect
   result status, readiness, incomplete data and evidence limits. Guard retains
   scheduling, stored history/results, domain impact/severity, incident lifecycle
   and notifications. Case severity/eligibility are evidence to interpret, not
   authority to send a notification. Test the change against representative
   historical data before replacing the vendored implementation.

For rollback, restore the previous dependency lock and application source and
redeploy its saved bundle, or rebuild from its retained wheelhouse. Never modify
the old release. Retain the original vendored Guard deployment until the first
library migration is validated. This repository does not modify or deploy Guard.

## Build candidates locally

Use a fresh `dist/` directory:

```text
uv build
uv export --locked --no-dev --no-emit-project --output-file dist/runtime-dependencies.txt
uv run python scripts/release.py create --revision <full-committed-source-SHA>
uv run python scripts/verify_distribution.py --python 3.12
uv run python scripts/release.py verify --revision <full-committed-source-SHA>
uvx --from twine==6.1.0 twine check --strict dist/*.whl dist/*.tar.gz
```

Use a clean committed tree when recording a revision. These commands are a local
preflight, not a replacement for tag CI. Windows can verify Windows artifacts;
the Lambda check requires a running Linux Docker engine or the hosted CI job.
Python 3.14 is outside the supported range and is rejected by package metadata.

## Optional later: public PyPI

PyPI is unnecessary for this release channel. Later, reserve/check the package
name, create the PyPI project and configure a [Trusted Publisher](https://docs.pypi.org/trusted-publishers/)
bound to the repository, release workflow and a protected environment. Add a
separate publication job using short-lived OIDC (`id-token: write`) to upload the
same tested artifacts. Keep long-lived API tokens out of the repository. No PyPI
publication or account creation is performed by the current workflow.
