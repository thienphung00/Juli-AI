---
name: guardrails
description: >-
  Enforces reliability, security, observability, and performance checklists; suggests
  patches; maps acceptance-criteria coverage; emits the ADR-003 review artifact. Use after
  intent-review in the Review Agent phase, or when checking engineering Guardrails on
  proposed code — not for Spec intent-match or Fowler smell blocking judgment.
---

# guardrails

**Phase:** Review

**Authoritative body:** [`.cursor/skills/standalone/guardrails/SKILL.md`](../../../.cursor/skills/standalone/guardrails/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`anti-patterns.md`](../../../.cursor/skills/standalone/guardrails/anti-patterns.md)

## Contract

Consumes the intent-review artifact and emits the ADR-003 review artifact.
