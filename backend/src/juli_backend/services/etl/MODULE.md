# backend/src/juli_backend/services/etl

## Purpose

Ingestion consumer: deduplicates by `event_id`, transforms payloads, persists via
`juli_backend.repositories` and `juli_backend.models`. Webhook and polling services
hand off validated payloads directly (no message bus). See [`EXECUTION.md`](../../../../../EXECUTION.md).

## Public Interface

Import from the package root only:

```python
from juli_backend.services.etl import EtlConsumer, IngestRecord, ...
```

### Package facade (`__init__.py`)

Matches ``__all__`` — re-exports only:

- ``EtlConsumer`` — async consumer with per-shop ordering and backpressure
  (lazy export; ``ingest(record: IngestRecord) -> ProcessOutcome``)
- ``IngestRecord`` — ``channel``, ``shop_key`` (TikTok shop id), ``value``, optional
  ``received_at`` for latency checks
- ``ProcessOutcome`` — ``processed`` | ``duplicate`` | ``dlq`` (lazy export)
- ``transform_for_channel(channel, payload)`` — map payload to entity upsert kwargs
- ``RAW_CHANNELS``, ``DLQ_CHANNEL`` — routing constants (``channels.py``)
- ``KafkaRecord`` — deprecated alias for ``IngestRecord``
- ``transform_for_topic`` — deprecated alias for ``transform_for_channel``

Producer wiring: ``make_etl_handoff(consumer)`` lives in
``juli_backend.services.ingestion`` (not re-exported from this package).

## Dependencies

- `juli_backend.database` — repos, `ProcessedEventsRepo`, shop resolution
- `juli_backend.services.ingestion` — `HandoffFn` type and `make_etl_handoff` helper only
  (no circular import at runtime)

## Key Behaviors

- Idempotency via `processed_events` table (`event_id` claim before write)
- Per-shop `asyncio.Lock` preserves ordering within a shop
- Malformed or unknown-shop messages → DLQ via injected `dlq_handoff` (testable stub)
- No broker client imported — callers inject handoff functions
- **Silver cutover (#607):** domain order/return upserts write `silver.orders` / `silver.returns`; bronze promotion via `SilverOrdersReturnsPromoter`

## Deprecated aliases

- `KafkaRecord` → `IngestRecord`
- `transform_for_topic` → `transform_for_channel`
- `publish_dlq` kwarg on `EtlConsumer` → `dlq_handoff`
