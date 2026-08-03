---
name: qa
description: >-
  Runs an interactive QA session where the user reports bugs conversationally and the
  agent files durable, user-focused GitHub issues using the project’s domain language. Use
  when the user wants to report bugs, do QA, file issues conversationally, or mentions “QA
  session”.
---

# qa

**Phase:** Ad-hoc / Implementation intake

**Authoritative body:** [`.cursor/skills/standalone/qa/SKILL.md`](../../../.cursor/skills/standalone/qa/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`README.md`](../../../.cursor/skills/standalone/qa/README.md)
