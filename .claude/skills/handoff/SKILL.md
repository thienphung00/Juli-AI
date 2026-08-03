---
name: handoff
description: >-
  Compacts the current conversation and session state into a handoff document at
  docs/handoffs/ so the next session can continue without re-discovering context. Use when
  the user says "handoff", "end session", "wrap up", "close out", or when invoked at the
  end of a Planning or implementation session.
---

# handoff

**Phase:** Any phase — session boundary

**Authoritative body:** [`.cursor/skills/standalone/handoff/SKILL.md`](../../../.cursor/skills/standalone/handoff/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.
