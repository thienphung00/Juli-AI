---
name: restructure
description: >-
  Execute mechanical codebase moves when target structure is already decided — same tests
  must pass before and after every issue. Use when the user says "restructure", "v1A to
  v1B", or when invoked by the refactor pipeline in core-orchestration.mdc. For
  architecture discovery or "leaner codebase" exploration, use
  improve-codebase-architecture instead.
---

# restructure

**Phase:** Ad-hoc

**Authoritative body:** [`.cursor/skills/standalone/restructure/SKILL.md`](../../../.cursor/skills/standalone/restructure/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

## Contract

Mechanical moves only, when the target structure is already decided. The same tests must pass before and after every issue.
