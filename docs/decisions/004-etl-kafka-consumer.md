# ADR-004: Kafka ETL consumer module

**Status:** Accepted

## Context

Webhook and polling services publish raw TikTok payloads to Kafka. Downstream
persistence must be idempotent (duplicate webhooks and at-least-once delivery),
route poison messages to a DLQ, and preserve per-shop ordering.

## Decision

Introduce `src/etl` with an injectable `EtlConsumer` that:

- Resolves `shops.tiktok_shop_id` from the Kafka partition key
- Claims `event_id` in a `processed_events` table before writing
- Transforms payloads and upserts through existing `src/data` repos
- Publishes failures to `tiktok.events.dlq` via an injected `publish_dlq` fn

## Rationale

Keeping Kafka clients out of `etl` mirrors `services/webhook` testability. Dedup
state lives in Postgres alongside commerce data so restarts do not replay events.

## Consequences

- New Alembic revision `003` for `processed_events`
- `docs/architecture/map.md` lists `src/etl` as Tier 1
- Runtime wiring (aiokafka / confluent consumer) remains deployment-specific
