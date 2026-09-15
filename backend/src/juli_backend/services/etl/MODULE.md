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
- ``append_targeted_order_payload`` / ``append_targeted_return_payload`` — ETL-owned,
  shop-scoped append-only writers for targeted-fetch bronze rows
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

- Idempotency via `processed_events` table — the claim key is `(event_id, epoch)` (#1968)
- The claim and the destination write share **one savepoint**, so a failed transform or
  upsert can never leave an id marked processed with nothing persisted (#1968)
- Per-shop `asyncio.Lock` preserves ordering within a shop
- Malformed or unknown-shop messages → DLQ via injected `dlq_handoff` (testable stub)
- No broker client imported — callers inject handoff functions
- **Silver cutover (#607):** domain order/return upserts write `silver.orders` / `silver.returns`; bronze promotion via `SilverOrdersReturnsPromoter`

## Recovering lost history — advancing a dedup epoch (#1968)

The ledger used to outlive the data it protected. When a destination table lost its rows,
`processed_events` still claimed those events were processed, so the re-ingest appeared to
succeed and wrote nothing: the reference shop held `orders` = 0 while the vendor API served
3,581 orders. The watermark controls what is **fetched**; the ledger controls what is
**persisted**. Both must move.

`ingest_dedup_epochs` holds one epoch per `(shop_id, channel)`. A missing row means epoch
`0`, so every row written before #1968 is still treated as processed and nothing changes
for a channel nobody has recovered.

**The epoch never moves on its own.** Not on import, not on startup, not on migration, not
on deploy — an epoch that advanced on release would re-ingest all history every release.
The only way to move it is:

```python
epoch = await IngestDedupEpochsRepo(session).advance(
    shop_id=shop.id,
    channel="tiktok.orders.raw",
    operator="<who is doing this>",   # required — ValueError if blank
    reason="<why, with the issue number>",  # required — ValueError if blank
)
await session.commit()
```

Operator and reason are recorded on the row alongside `advanced_at`, so a re-ingest is
explainable months later. **Do not clear or delete ledger rows.** A `DELETE` is
irreversible and destroys the only record of what was ingested and when; the epoch is
additive and leaves that record standing.

Recovery procedure for one shop: reset the watermark for the affected channels (#1949),
then `advance` the epoch for those same channels, then re-run the poll. Advancing one
channel's epoch does not make another channel's ids re-ingestable.

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

1. **Bronze** — append through this package's targeted-fetch facade; callers never write
   bronze repositories directly.
2. **Silver** — `SilverOrdersReturnsPromoter.promote_order` / `promote_return`.
3. **Gold** — `services/gold_kpi_envelope_serving.py` shell today; A1 Shared Compute gold
   stage owns full `gold.kpi_envelopes` refresh.

Do **not** wire Celery material webhook enqueue or cross-shop batch jobs in A0 (#608).

## Deprecated aliases

- `KafkaRecord` → `IngestRecord`
- `transform_for_topic` → `transform_for_channel`
- `publish_dlq` kwarg on `EtlConsumer` → `dlq_handoff`
