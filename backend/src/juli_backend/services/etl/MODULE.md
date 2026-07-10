# backend/integrations/ordering/use_cases/etl

## Purpose

Ingestion consumer: deduplicates by `event_id`, transforms payloads, persists via
`backend/database` repositories. Webhook and polling services hand off validated payloads
directly (no message bus). See [`EXECUTION.md`](../../../../../EXECUTION.md).

## Public API

- `EtlConsumer` — async consumer with per-shop ordering and backpressure
  - `ingest(record: IngestRecord) -> ProcessOutcome`
- `IngestRecord` — `channel`, `shop_key` (TikTok shop id), `value`, optional
  `received_at` for latency checks
- `ProcessOutcome` — `processed` | `duplicate` | `dlq`
- `transform_for_channel(channel, payload)` — map payload to entity upsert kwargs
- `RAW_CHANNELS`, `DLQ_CHANNEL` — routing constants in `channels.py`
- `make_etl_handoff(consumer)` in `backend/integrations/ordering/api/ingestion/handoff.py` — wires producers to
  `EtlConsumer.ingest`

## Dependencies

- `backend/database` — repos, `ProcessedEventsRepo`, shop resolution
- `backend/integrations/ordering/api/ingestion/handoff` — `HandoffFn` type and `make_etl_handoff` helper only
  (no circular import at runtime)

## Key Behaviors

- Idempotency via `processed_events` table (`event_id` claim before write)
- Per-shop `asyncio.Lock` preserves ordering within a shop
- Malformed or unknown-shop messages → DLQ via injected `dlq_handoff` (testable stub)
- No broker client imported — callers inject handoff functions

## Deprecated aliases

- `KafkaRecord` → `IngestRecord`
- `transform_for_topic` → `transform_for_channel`
- `publish_dlq` kwarg on `EtlConsumer` → `dlq_handoff`
