---
name: api-docs
description: >-
  Converts official vendor API documentation into implementation-ready reference docs
  under docs/<vendor>_api/. Use when onboarding a new external API, refreshing stale
  integration docs, or preparing source-of-truth material for Architect planning, focus,
  to-prd, to-issues, Executor implementation, and review.
---

# api-docs

**Phase:** Planning / Implementation

**Authoritative body:** [`.cursor/skills/standalone/api-docs/SKILL.md`](../../../.cursor/skills/standalone/api-docs/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/standalone/api-docs/REFERENCE.md)

## Contract

Pair with the Context7 **CLI** (`npx ctx7@latest`) when SDK references are needed — Context7 is not an MCP in this repo.
