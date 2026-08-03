---
name: prompt-caching
description: >-
  Manages the two-tier workflow prompt cache (parent constant + child unique) for
  implement issue #N through Meta → Executor → Review → Validate. Use when loading,
  validating, injecting, or writing parent-cache and issue-context-cache artifacts before
  or during agent phases.
---

# prompt-caching

**Phase:** Meta

**Authoritative body:** [`.cursor/skills/standalone/prompt-caching/SKILL.md`](../../../.cursor/skills/standalone/prompt-caching/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/standalone/prompt-caching/REFERENCE.md)

## Contract

Governs the two-tier workflow prompt cache. Meta owns it; Executors consume the injected blocks and must not rewrite them.
