# ADR-004: ETL ingest consumer module

**Status:** Accepted (updated — ingest handoff replaces broker fan-out)

> **Naming note:** the filename retains the historical `kafka` slug, but no message
> broker was adopted. Ingestion flows in-process (webhook/polling → ETL → Postgres);
> all Kafka/broker references were removed. Kafka/streams are Phase 3+ (see
> [`EXECUTION.md`](../../EXECUTION.md) → Explicitly out).

## Context

Webhook and polling services must persist TikTok payloads with idempotency
(duplicate webhooks and at-least-once handoffs), route poison messages to a DLQ,
and preserve per-shop ordering — without introducing a message bus in v1.5.

## Decision

Introduce `src/modules/ordering/use_cases/etl` with an injectable `EtlConsumer` that:

- Resolves `shops.tiktok_shop_id` from the ingest `shop_key`
- Claims `event_id` in a `processed_events` table before writing
- Transforms payloads and upserts through existing `src/shared/utils/data` repos
- Sends failures to the DLQ channel via an injected `dlq_handoff` function

Producers use `src/modules/ordering/api/ingestion.make_etl_handoff(consumer)` so
validated payloads flow **webhook/polling → ETL → Postgres** in-process.

## Rationale

Keeping broker clients out of ETL, webhook, and polling preserves testability
(in-memory handoff stubs in unit tests). Dedup state lives in Postgres alongside
commerce data so restarts do not replay events.

## Consequences

- Alembic revision `003` for `processed_events`
- `docs/architecture/map.md` lists `src/modules/ordering/use_cases/etl` and `src/modules/ordering/api/ingestion`
- v2.0 may add Redis/Celery for async orchestration without changing `src/jobs/*` logic
- Deferred: dedicated stream processing until Phase 3+ (see [`EXECUTION.md`](../../EXECUTION.md))
