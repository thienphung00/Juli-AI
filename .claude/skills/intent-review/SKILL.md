---
name: intent-review
description: >-
  Judges Spec fidelity (intent-to-code match), Fowler smells, and light convention/pattern
  citations against the diff since a fixed point. Emits an intent-review artifact that
  Guardrails must consume as given. Use when the Review Agent runs, or when reviewing a
  branch, PR, or "review since X" for design-fit and structure — not for
  reliability/security domain checklists.
---

# intent-review

**Phase:** Review

**Authoritative body:** [`.cursor/skills/standalone/intent-review/SKILL.md`](../../../.cursor/skills/standalone/intent-review/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`BOUNDARY.md`](../../../.cursor/skills/standalone/intent-review/BOUNDARY.md)
- [`REFERENCE.md`](../../../.cursor/skills/standalone/intent-review/REFERENCE.md)

## Contract

First step of Review. Emits the intent-review artifact that `guardrails` must consume — do not skip to guardrails.
