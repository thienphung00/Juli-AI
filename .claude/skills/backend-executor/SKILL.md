---
name: backend-executor
description: >-
  Executor Agent domain skill for Juli product logic and /v1/* FastAPI API. Use when
  implementing scoring, copy, action cards, aggregates, auth, or product services — not
  vendor I/O or schema/ETL durability.
---

# backend-executor

**Phase:** Implementation (Executor)

**Authoritative body:** [`.cursor/skills/domain/backend/SKILL.md`](../../../.cursor/skills/domain/backend/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/domain/backend/REFERENCE.md)

## Contract

Juli product logic and `/v1/*` FastAPI. **Not** vendor I/O (that is `integrations-executor`) and not schema/ETL durability (that is `data-platform-executor`).
