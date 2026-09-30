<!-- capabilitykit:start -->
# capabilitykit

This project uses **CapabilityKit** to manage capabilities as code.
Read the full guide at `docs/capabilitykit/SKILL.md` before creating,
editing, validating, reviewing, or implementing capability files.
When drafting new capability files from product intent, write the human-authored
spec first and do not invent agent metadata. Use `capabilitykit format`,
`capabilitykit validate`, `capabilitykit compile`, and the review commands in
the full guide to refresh generated metadata and review evidence.
<!-- capabilitykit:end -->

## Project capability conventions

- Organize `.capabilities/` by observable behavior in logical area/subarea folders.
- Describe what Anomalyzer does for users and callers; source modules are evidence,
  not the organizing structure. Historical plans are not implemented capabilities.
- Keep 3–5 concrete acceptance criteria and 3–5 representative automated checks
  per capability. Reuse existing tests where they establish the behavior.
- Include one focused manual review step for interpretation and evidence limits.
- Use `implemented` until verification warrants a stronger status. Record real
  dependencies and source/test references; do not invent review evidence.
