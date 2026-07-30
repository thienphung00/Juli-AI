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

## One-writer map (CDP medallion — #608)

Post-cutover **one writer per medallion table** is documented in
[`database/MODULE.md`](../../database/MODULE.md) (authoritative map). This package owns:

| Responsibility | Tables / repos |
|----------------|----------------|
| **Bronze append** (orders/returns raw payloads) | `BronzeOrderRawPayloadsRepo`, `BronzeReturnRawPayloadsRepo` — batched `append_batch` only |
| **Silver domain upsert** | `OrdersRepo.upsert`, `ReturnsRepo.upsert` via `EtlConsumer` and `SilverOrdersReturnsPromoter` |

Readers (gold compute, ML) must not write silver. Bronze promotion reads bronze append
rows and writes silver only through the promoter — no reverse bronze writes from silver.

### Shared Compute Orchestrator — Q4 stage hooks (A1)

Full orchestrator runtime is **A1 Speed (#601)**; A0 seeds docs + repos only. Per material
trigger, one shop-scoped job runs **bronze append → silver upsert → gold envelope** in
order (ADR-046 Q4). Stage wiring targets:

1. **Bronze** — append via bronze repos in this package (webhook/fetch handoff).
2. **Silver** — `SilverOrdersReturnsPromoter.promote_order` / `promote_return`.
3. **Gold** — `services/gold_kpi_envelope_serving.py` shell today; A1 Shared Compute gold
   stage owns full `gold.kpi_envelopes` refresh.

Do **not** wire Celery material webhook enqueue or cross-shop batch jobs in A0 (#608).

## Deprecated aliases

- `KafkaRecord` → `IngestRecord`
- `transform_for_topic` → `transform_for_channel`
- `publish_dlq` kwarg on `EtlConsumer` → `dlq_handoff`
