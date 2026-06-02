# ADR-004: ETL ingest consumer module

**Status:** Accepted (updated — ingest handoff replaces broker fan-out)

## Context

Webhook and polling services must persist TikTok payloads with idempotency
(duplicate webhooks and at-least-once handoffs), route poison messages to a DLQ,
and preserve per-shop ordering — without introducing a message bus in v1.5.

## Decision

Introduce `src/etl` with an injectable `EtlConsumer` that:

- Resolves `shops.tiktok_shop_id` from the ingest `shop_key`
- Claims `event_id` in a `processed_events` table before writing
- Transforms payloads and upserts through existing `src/data` repos
- Sends failures to the DLQ channel via an injected `dlq_handoff` function

Producers use `src/ingestion/handoff.make_etl_handoff(consumer)` so validated
payloads flow **webhook/polling → ETL → Postgres** in-process.

## Rationale

Keeping broker clients out of `etl`, `webhook`, and `polling` preserves testability
(in-memory handoff stubs in unit tests). Dedup state lives in Postgres alongside
commerce data so restarts do not replay events.

## Consequences

- Alembic revision `003` for `processed_events`
- `docs/architecture/map.md` lists `src/etl` and `src/ingestion`
- v2.0 may add Redis/Celery for async orchestration without changing `src/jobs/*` logic
- Deferred: dedicated stream processing until scale triggers in `migration_path.md`
