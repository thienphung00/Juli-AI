---
name: to-issues
description: >-
  Breaks a plan, spec, or PRD into independently-grabbable GitHub issues using
  tracer-bullet vertical slices. Use when the user wants implementation tickets created
  from a plan, wants a spec decomposed into reviewable issues, or wants integration bugs
  split into one-test-per-behavior slices with TDD-style acceptance criteria.
---

# to-issues

**Phase:** Planning (Architect)

**Authoritative body:** [`.cursor/skills/standalone/to-issues/SKILL.md`](../../../.cursor/skills/standalone/to-issues/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`README.md`](../../../.cursor/skills/standalone/to-issues/README.md)

## Contract

Tracer-bullet vertical slices. Record child slice IDs in `agent-runtime/config/agent-runtime.config.yml` `epicRegistry` when opening a new epic.
