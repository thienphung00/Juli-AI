---
name: focus
description: >-
  Default context router — classifies tasks and produces a Context Plan for docs, rules,
  skills, MCPs, and agent phases. Invoke at conversation start and before implementation;
  also when switching features or context overload is detected.
---

# focus

**Phase:** All phases — router

**Authoritative body:** [`.cursor/skills/standalone/focus/SKILL.md`](../../../.cursor/skills/standalone/focus/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`routing-rules.md`](../../../.cursor/skills/standalone/focus/routing-rules.md)

## Contract

Run this **first** on every non-trivial task. Emit a Context Plan with an explicit *DO NOT load* list before touching anything else.
