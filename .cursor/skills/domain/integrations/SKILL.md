---
name: integrations-executor
description: >-
  Executor Agent domain skill for platform-agnostic commerce integrations
  (vendor clients, webhooks, polling/sync, analytics backfill). Use when
  implementing external platform I/O — not Juli product /v1 routes or schema/ETL durability.
---

# Integrations Executor

Platform-agnostic external commerce I/O. Built-in TDD and artifact handoff:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| Vendor HTTP client, signing, OAuth | `reliability.mdc`, `observability.mdc`, `python-patterns` |
| Inbound webhook receiver | `reliability.mdc`, `observability.mdc`, ETL handoff `MODULE.md` |
| Scheduled poll / incremental sync | `reliability.mdc`, `data-sources.md` |
| Analytics fetch / historical backfill | `reliability.mdc`, partition + budget `MODULE.md` |
| Vendor-specific issue | `docs/integrations/<vendor>_api/` (issue-specific, not skill identity) |

## Owns / Does not own

**Owns:** vendor clients (auth, signing, rate limits, retries), inbound webhooks
(verify → accept → handoff), polling/sync cursors, analytics fetch and partition
backfill.

**Does not own — defer to sibling domains (no overlap):**

- **`backend`** — Juli `/v1/*` product API, scoring, copy, action cards, aggregates,
  Juli JWT/session auth. Integration code uses injected ports; never embed product rules.
- **`data-platform`** — schema, migrations, repositories, ETL consumer durability,
  webhook dedup persistence. Integrations pass bytes/events via `handoff_fn`; no direct
  durable DB writes.

## Required context

- `MODULE.md` for affected modules (`integrations/<vendor>/`, `services/webhook/`,
  `workers/services/polling/`, `services/analytics_backfill/`)
- [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md)
- `docs/integrations/<vendor>_api/` when vendor-specific
- [ADR-031](../../../docs/adr/031-integrations-executor-domain.md)

## Juli recipes

**Vendor client** — `integrations/<vendor>/`: signing/auth/rate-limit; thin
`resources/`; typed exceptions; leaf module (no internal Juli imports).

**Webhooks** — verify → idempotent accept within ACK window →
`handoff_fn(channel, shop_key, payload_bytes)`; optional raw audit; no product logic
or direct DB.

**Polling** — cursor/watermark per shop + endpoint; shop-isolated limiter buckets;
resumable `run_*_poll_cycle` / `sync_*`; advance cursor only after handoff; rate-limit
exhaustion → log and skip.

**Analytics sync/backfill** — partition `(shop, bucket, date)`; soft/hard call-budget
caps; skip completed; budget pause must not mark incomplete partitions complete; resume
without double-count.

Deeper patterns: [`REFERENCE.md`](REFERENCE.md).

## Domain test surfaces

Signed webhook fixtures; fake/in-memory rate limiter; partition resume (budget pause,
skip-complete); shop isolation (credentials, cursors, limiter keys). Vertical RED→GREEN
slices; prefer public client boundaries over mocking vendor internals.

## Implementation artifact (required handoff)

Record TDD cycles in `redGreenRefactorEvidence` per
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

```bash
python agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain integrations
```

Write `agent-runtime/artifacts/implementations/implementation-issue-<n>.json` before
Review Agent. Schema:
[`implementation-artifact.schema.json`](../../../agent-runtime/docs/schemas/implementation-artifact.schema.json).

## Review focus

Signature verification, replay/idempotency at accept, retry classification, secrets
redaction, shop scoping, handoff contract, call-budget pause/resume.

## Validation

`pytest` (webhook/poll/backfill modules); `ruff check .`; `mypy backend/` when Python
changes.

## Must not

- Juli product `/v1` routes, scoring, copy, or Juli JWT/session auth
- Schema migrations, ETL durability, or webhook dedup persistence
- Log tokens, signing secrets, or raw credentials
- Ship or validate — hand off to Review Agent
