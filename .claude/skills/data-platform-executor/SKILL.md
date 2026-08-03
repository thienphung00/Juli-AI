---
name: data-platform-executor
description: >-
  Executor Agent domain skill for Postgres schema, migrations, repositories, and ETL
  consumer durability. Use when implementing persistence, Alembic, or ingest dedup — not
  vendor I/O or Juli /v1 product logic.
---

# data-platform-executor

**Phase:** Implementation (Executor)

**Authoritative body:** [`.cursor/skills/domain/data-platform/SKILL.md`](../../../.cursor/skills/domain/data-platform/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/domain/data-platform/REFERENCE.md)

## Contract

Postgres schema, Alembic migrations, repositories, ETL consumer durability.
