---
name: capabilitykit
description: Work with CapabilityKit capabilities as code. Use when creating, editing, validating, compiling, reviewing, or comparing .capability.yaml files against agent.implementation.references.
---

# CapabilityKit

Use CapabilityKit to keep product intent, acceptance criteria, agent-maintained implementation references, and verification checks close to the code.

## Human-owned vs derived fields

- Human-authored capability content should focus on: `title`, `status`, `summary`, `intent`, `acceptance`, optional `guidance`, optional `planning.story_map`, optional `agent`, and optional `replacement`.
- `id` and `area` are derived from the capability file path and should normally be omitted from YAML files.
- Supported `status` values are `planned`, `in-progress`, `implemented`,
  `verified`, and `deprecated`.
- Run `capabilitykit check --fix` to remove non-custom `id`/`area` fields,
  keep canonical section order, and refresh compiled output.
- `capabilitykit validate` reports warnings when explicit `id` or `area` fields are present.

## Creating capability files

When asked to create a new capability file from product intent, write only the
human-authored spec by default:

- `title`
- `status`
- `summary`
- `intent`
- `acceptance`
- optional `guidance`
- optional `planning.story_map`
- optional `replacement`

Do not invent `agent.inputs`, `agent.outputs`, implementation references,
verification checks, dependencies, review results, or other agent metadata while
drafting a new capability. Add an `agent` section only when it comes from
concrete implementation evidence, an explicit dependency relationship, or a
real verification/review workflow.

When a repository has no CapabilityKit project yet, run `capabilitykit init`
first. It creates `.capabilities/capabilitykit.yaml` and a starter capability.
Use `capabilitykit skill` after install or dependency updates to refresh
AGENTS.md, CLAUDE.md, Codex skill wrappers, and Claude slash-command wrappers
that point agents back to this package guide.

## Capability Structure

Write capability files as behavior contracts, not task logs:

- `summary` should state the observable capability in one or two sentences.
- `intent` should explain why the capability exists and what outcome it
  protects.
- `acceptance` should be specific, reviewable behavior. Avoid vague criteria
  such as "works well" unless the capability also defines concrete evidence.
- `guidance` is for human-authored constraints, tradeoffs, and implementation
  cautions that should remain close to the behavior.
- `replacement` is for deprecated capabilities and should point to the successor
  capability or migration path.

Use `agent` metadata only when there is evidence or a real workflow to record:

```yaml
agent:
  depends_on:
    - core/model/define-capability-format
  implementation:
    references:
      - packages/core/src/schema.ts
      - packages/core/tests/parser.test.ts
  verification:
    automated:
      - id: parser-tests
        description: Parser tests cover the capability schema.
        command: npm test -- packages/core/tests/parser.test.ts
    manual:
      - Inspect generated YAML after formatting.
    gaps:
      - Add end-to-end coverage before marking this verified.
```

Best practices:

- `agent.depends_on` is the source of truth for impact analysis. Use it for
  behavior dependencies, not for directory ownership or incidental imports.
- `agent.implementation.references` should point to concrete source, test,
  documentation, or generated output files that a reviewer can inspect.
- `agent.verification.automated` should use commands that can be run from the
  repository root. Include focused commands when possible.
- `agent.verification.manual` should describe checks that automation cannot
  prove, such as copy quality, generated viewer readability, or workflow fit.
- `agent.verification.gaps` should make missing confidence explicit. Do not hide
  known gaps by omitting verification metadata.
- Use `agent.verification.ignore_gaps` or `agent.review.ignore_findings` only
  with a concrete reason when the warning is intentionally accepted.

## Story Map Planning

Use `planning.story_map` when a capability belongs to a product planning slice.
Story-map metadata is human-authored planning context, not agent-derived
implementation evidence. It should describe where the capability fits in the
release narrative while the capability file continues to own the behavior
contract, acceptance criteria, implementation references, and verification.

```yaml
planning:
  story_map:
    backbone: Project communication
    step: Explain core concepts
    release: website
    order: 30
```

Field guidance:

- `release` is the named release slice or outcome, such as `mvp`,
  `website`, or `todo-views`. If `.capabilities/capabilitykit.yaml`
  configures `planning.releases`, use one of those configured values.
- `backbone` is the user journey, workflow, or product activity this
  capability supports. Use stable product language rather than code module
  names.
- `step` is the specific user-visible step inside that backbone. Keep it
  outcome-oriented and small enough that several capabilities can form a
  progressive slice.
- `order` is an optional integer for story-map sequencing. Use gaps such as
  `10`, `20`, `30` so future capabilities can be inserted without renumbering.

Best practices:

- Add story-map metadata only when the release/backbone/step is known from
  product intent or existing project planning. Do not invent a story-map
  assignment just to fill the field.
- Prefer release slices that can be delivered and reviewed end to end. A story
  map should explain progressive delivery, not mirror the repository folder
  structure.
- Keep `acceptance` focused on behavior. Use `planning.story_map` for
  sequencing and narrative, and use `agent.implementation.references` and
  `agent.verification` for implementation evidence once it exists.
- When adding or changing story-map metadata, run
  `capabilitykit status --story-map` and, when useful,
  `capabilitykit status --story-map --recommend-order --show-coverage` to check
  whether the release slice still reads coherently.
- Use `capabilitykit story-map-viewer` when you need a shareable HTML view of
  the release story.

After creating or editing capability files:

1. Run `capabilitykit check --fix` to format capability files, validate them,
   and refresh the configured compiled capability map.
2. Run `capabilitykit next` when the check finds issues and you need the most
   useful follow-up actions.
3. Use `capabilitykit verify <capability-id>` when deterministic
   implementation evidence should be generated and saved.
4. Add `--agent codex --arg exec --handoff stdin` only for targeted semantic coding-agent review, such as
   release-critical capabilities, high-dependency capabilities, or capabilities
   moving to `verified`. Use `--no-save`/`--dry-run` when you only want to
   inspect the result.

## Workflow

1. Read `.capabilities/capabilitykit.yaml` to understand project settings.
2. Read the relevant `*.capability.yaml` files before editing code for that behavior.
3. When behavior changes, update the matching capability spec in the same change.
4. Run `capabilitykit check` to catch formatting, schema, dependency,
   verification, and implementation-reference gaps without writing files.
5. Run `capabilitykit check --fix` to apply formatting and update the compiled
   capability map.
6. Use `capabilitykit diff --base <ref>` during review to summarize capability
   intent, acceptance, verification, implementation-reference, and dependency
   changes.
7. Use `capabilitykit graph-viewer` or `capabilitykit story-map-viewer` when a
   visual review surface would help reviewers understand dependencies or
   release slices.

## Reporting and Viewers

- `capabilitykit check` runs the cheap daily health check: formatting check,
  validation, in-memory compile, and status summary.
- `capabilitykit check --fix` applies formatting and refreshes compiled output.
- `capabilitykit next` summarizes the next most useful maintenance actions
  from validation, status, deterministic advice, and semantic-review
  candidates.
- `capabilitykit status` summarizes capabilities into ok, needs-review,
  needs-action, and planned buckets.
- `capabilitykit status <capability-id>` narrows the health summary to one
  capability.
- `capabilitykit status --story-map` groups by release, backbone, and step.
- Add `--release <release>` to focus story-map output on one configured release.
- Add `--recommend-order --show-coverage` when reviewing delivery sequence and
  verification health for a release slice.
- `capabilitykit inspect <capability-id>` prints one capability, dependencies,
  dependents, and verification gaps.
- `capabilitykit impact <capability-id>` traverses `agent.depends_on` and lists
  downstream capabilities plus suggested verification.
- `capabilitykit graph` writes `.capabilities/dependency-graph.svg`.
- `capabilitykit graph-viewer` writes `.capabilities/dependency-viewer.html`
  and the SVG fallback.
- `capabilitykit story-map-viewer` writes
  `.capabilities/story-map-viewer.html`.
- Commands that support `--json` should be used when another tool or agent needs
  structured output instead of prose.

## Implementation Review

When the user wants a progress overview, start with `capabilitykit status`.
It shows green, amber, and red evidence signals without running an external
agent. Keep review and verification detail available through `status <id>`.
Do not launch a repository-wide semantic review merely to refresh map colours
or regenerate a viewer. Target changed or unconfirmed capabilities instead.

Semantic `verify --agent`, `review --agent`, and `agent-review` use focused
completion prompts by default. They retain criterion-level file evidence while
omitting whole-file content and the large deterministic report. Return concise
JSON, with short reasons for gaps and uncertainty. Use `--detailed` when the
user needs the full report, and `--detailed --no-references` to omit file content.

Unchanged fingerprinted coding-agent or human reviews are reused automatically.
Fingerprints track the contract, referenced implementation, cited evidence, and
declared dependencies. A changed input requires a new review; unrelated files
outside that evidence scope are not tracked. Existing reviews without a
fingerprint must run once before they can be reused. Use `--force` to reassess.
Quick reviews are not reused for a `--detailed` request.

Semantic runs have a 120-second default time limit. Use `--timeout <seconds>`
to adjust it or `--timeout 0` to disable it. A timeout reports amber/unconfirmed,
exits with code 124, and saves no partial output. `--no-save` and `--dry-run`
remain available. Local `verify` and `review` preserve saved semantic evidence;
use `sync-review` when explicitly replacing it with a deterministic snapshot.

When asked whether a capability matches implementation behavior:

1. Treat the capability file as the source of truth.
2. Inspect every path in `agent.implementation.references`.
3. Compare each acceptance criterion with concrete code, test, or documentation evidence.
4. Report each criterion as `covered`, `partially covered`, `not covered`, or `uncertain`.
5. Do not infer coverage from filenames alone.
6. Recommend the smallest code, test, or capability-spec change for each gap.

Use the review commands according to the evidence needed:

- `capabilitykit verify <capability-id>` is the recommended happy path for
  deterministic implementation review; it saves `agent.review` by default.
- `capabilitykit verify <capability-id> --agent <command>` opts into semantic
  coding-agent review and saves valid structured output by default.
- `capabilitykit verify --recommended` or `capabilitykit verify --stale` lists
  high-value candidates for semantic review without running an agent.
- `capabilitykit assess <capability-id>` performs deterministic
  criterion-by-criterion evidence matching.
- `capabilitykit advise [capability-id]` groups assessment findings into
  recommended next actions.
- `capabilitykit review [capability-id]` saves deterministic review evidence by
  default; add `--no-save` or `--dry-run` to inspect without writing.
- `capabilitykit review <capability-id> --agent <command>` asks an external
  coding agent for semantic review and saves valid structured output by default.
- If the external agent cannot read stdin in the current environment, use
  `--handoff prompt-file --prompt-file tmp/review-prompt.md` or
  `--output-prompt tmp/review-prompt.md` and then save the resulting JSON with
  `capabilitykit review-result <capability-id> --input <path>`.
- If `codex` is installed but not visible on `PATH`, pass its executable path
  with `--agent <path>`/`--command <path>` or set `CAPABILITYKIT_CODEX_COMMAND`
  to the Codex executable path.
- GitHub Copilot CLI semantic review is also supported with
  `--agent copilot`. CapabilityKit defaults to `copilot -s -p "{prompt}"` with
  argument handoff. Override with explicit `--arg` and `--handoff` values when
  needed, or set `CAPABILITYKIT_COPILOT_COMMAND` when `copilot` is not visible
  on `PATH`.
- Pi Coding Agent semantic review is supported with `--agent pi`.
  CapabilityKit defaults to `pi -p "{prompt}" --no-session` with argument
  handoff. Override with explicit `--arg` and `--handoff` values when needed,
  or set `CAPABILITYKIT_PI_COMMAND` when `pi` is not visible on `PATH`.
- Claude Code semantic review is supported with `--agent claude`.
  CapabilityKit defaults to `claude -p "{prompt}"` with argument handoff.
  Override with explicit `--arg` and `--handoff` values when needed, or set
  `CAPABILITYKIT_CLAUDE_COMMAND` when `claude` is not visible on `PATH`.
- Cursor CLI semantic review is supported with `--agent cursor-agent`.
  CapabilityKit defaults to `cursor-agent -p "{prompt}"` with argument handoff
  and does not add Cursor's `--force` flag during assessment. Override with
  explicit `--arg` and `--handoff` values when needed, or set
  `CAPABILITYKIT_CURSOR_COMMAND` when `cursor-agent` is not visible on `PATH`.
- `capabilitykit agent-task <capability-id>` creates an inspectable implement or
  review prompt bundle for external agents.
- `capabilitykit agent-run <capability-id> --command <command>` runs an external
  agent with an implementation or review task bundle.
- `capabilitykit agent-review <capability-id> --command <command>` runs a
  semantic review prompt and prints the external agent result.
- `capabilitykit sync-review [capability-id]` refreshes saved review evidence
  from deterministic assessment without changing capability status.

## Useful Commands

```bash
capabilitykit init
capabilitykit create "User login" --area account
capabilitykit check
capabilitykit check --fix
capabilitykit next
capabilitykit format
capabilitykit format --check
capabilitykit validate
capabilitykit status
capabilitykit status core/example
capabilitykit status --story-map
capabilitykit status --story-map --release story-mapping
capabilitykit status --story-map --recommend-order --show-coverage
capabilitykit inspect account/user-login
capabilitykit impact account/user-login
capabilitykit diff --base HEAD
capabilitykit diff account/user-login --base main
capabilitykit diff --base HEAD --verbose --include-review
capabilitykit graph
capabilitykit graph-viewer
capabilitykit verify account/user-login
capabilitykit verify account/user-login --agent codex --arg exec --handoff stdin
capabilitykit verify account/user-login --agent copilot
capabilitykit verify account/user-login --agent pi
capabilitykit verify account/user-login --agent claude
capabilitykit verify account/user-login --agent cursor-agent
capabilitykit verify --recommended --limit 5
capabilitykit review account/user-login
capabilitykit review account/user-login --agent codex --arg exec --handoff stdin
capabilitykit assess account/user-login
capabilitykit advise account/user-login
capabilitykit review-noisy --limit 5
capabilitykit sync-review account/user-login --dry-run
capabilitykit compile
capabilitykit story-map-viewer
capabilitykit skill
```

## Review and Agent Commands

Use these commands when assessing implementation coverage or handing work to an
external coding agent:

```bash
capabilitykit review core/example
capabilitykit review core/example --no-save
capabilitykit review core/example --agent codex --arg exec --handoff stdin
capabilitykit review core/example --agent codex --arg exec --handoff stdin --no-save
capabilitykit verify core/example
capabilitykit verify core/example --no-save
capabilitykit verify core/example --agent codex --arg exec --handoff stdin
capabilitykit verify core/example --agent copilot
capabilitykit verify core/example --agent pi
capabilitykit verify core/example --agent claude
capabilitykit verify core/example --agent cursor-agent
capabilitykit verify --stale --limit 5
capabilitykit assess core/example
capabilitykit assess core/example --json
capabilitykit advise
capabilitykit advise core/example --json
capabilitykit review-noisy --command codex --limit 5
capabilitykit sync-review core/example
capabilitykit agent-task core/example --mode implement --output tmp/capability-task.md
capabilitykit agent-task core/example --mode review --no-references
capabilitykit agent-run core/example --command codex --arg exec --handoff prompt-file --prompt-file tmp/capability-task.md --dry-run
capabilitykit agent-review core/example --command codex --arg exec --handoff stdin --dry-run --no-references
capabilitykit review-result core/example --input tmp/review.json
capabilitykit review-result core/example --input tmp/review.json --no-save
capabilitykit agent-run core/example --command codex --arg exec --handoff stdin --mode implement --dry-run
```

- `verify` is the recommended happy path; it saves deterministic `agent.review`
  evidence by default.
- `verify --agent <command>` is the targeted, opt-in semantic review path for
  expensive external coding-agent checks.
- `verify --recommended` and `verify --stale` list high-value candidates before
  you spend time or tokens on semantic review.
- `review` is the lower-level review command; it saves `agent.review` by default.
- `review --no-save` validates or previews review output without writing.
- `review --deterministic-only` uses the local deterministic assessor even when
  an agent command is available.
- `review --agent <command>` runs semantic coding-agent review and saves valid
  structured output by default.
- `assess` produces deterministic criterion-by-criterion implementation evidence.
- `advise` turns coverage findings into grouped recommended actions and confidence notes.
- `status` summarizes the capability map into ok, needs-review, needs-action, and planned buckets.
- `diff` compares current capability intent against a Git base and summarizes added, changed, or removed capabilities.
- `review-noisy` lists high-value capabilities for semantic human or Codex review.
- `sync-review` updates `agent.review` from deterministic implementation evidence while leaving status and gaps explicit.
- `impact` reports direct and transitive downstream capabilities plus suggested verification.
- `agent-task` creates an inspectable implementation or review prompt bundle.
- `agent-review` combines a review bundle with the deterministic coverage report.
- `review-result` saves valid structured review JSON under `agent.review` by
  default; use `--no-save` to validate without writing.
- `agent-run` executes an external CLI with stdin, argument, or prompt-file handoff.
