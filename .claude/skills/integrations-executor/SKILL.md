---
name: integrations-executor
description: >-
  Executor Agent domain skill for platform-agnostic commerce integrations (vendor clients,
  webhooks, polling/sync, analytics backfill). Use when implementing external platform I/O
  — not Juli product /v1 routes or schema/ETL durability.
---

# integrations-executor

**Phase:** Implementation (Executor)

**Authoritative body:** [`.cursor/skills/domain/integrations/SKILL.md`](../../../.cursor/skills/domain/integrations/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/domain/integrations/REFERENCE.md)

## Contract

Vendor clients, webhooks, polling/sync, analytics backfill — platform-agnostic commerce I/O.
