---
name: validate
description: >-
  Deterministically validates an issue's implementation before ship by running every
  agent-runtime/scripts/validate/*.py gate and emitting
  agent-runtime/artifacts/validation/validation-issue-<n>.json. Use when the review
  handoff is complete and the next step would be ship, when CI fails on artifact gates, or
  when an agent needs a machine-verifiable PASS before merging.
---

# validate

**Phase:** Review

**Authoritative body:** [`.cursor/skills/standalone/validate/SKILL.md`](../../../.cursor/skills/standalone/validate/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`checks.md`](../../../.cursor/skills/standalone/validate/checks.md)

## Contract

Runs every `agent-runtime/scripts/validate/*.py` gate and emits `agent-runtime/artifacts/validation/validation-issue-<n>.json`. Deterministic — do not summarise gate output, run the gates.
