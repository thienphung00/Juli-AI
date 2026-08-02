---
name: write-a-skill
description: >-
  Creates new agent skills with a consistent folder structure, progressive disclosure, and
  bundled resources. Use when a user asks to create/write/build a new skill, or when
  adding reusable agent capabilities.
---

# write-a-skill

**Phase:** Ad-hoc — requires explicit user request

**Authoritative body:** [`.cursor/skills/write-a-skill/SKILL.md`](../../../.cursor/skills/write-a-skill/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

## Contract

Skills governance: never scaffold a skill for convenience. When a new Cursor skill is approved, add its `.claude/skills/` pointer in the same change.
