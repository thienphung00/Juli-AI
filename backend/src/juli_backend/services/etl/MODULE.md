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

### Ingest persistence (`persistence.ingest`)

The idempotency ledger and its epoch. Import from
``juli_backend.services.etl.persistence.ingest``:

- ``ProcessedEvent`` — the ledger row; the dedup key is ``(event_id, epoch)`` (#1968)
- ``ProcessedEventsRepo`` — ``claim(*, event_id, shop_id, epoch=INITIAL_EPOCH) -> bool``;
  ``False`` means the id was already processed *in that epoch*
- ``IngestDedupEpoch`` — current epoch for one ``(shop_id, channel)`` plus
  ``advanced_at`` / ``advanced_by`` / ``reason``
- ``IngestDedupEpochsRepo`` — ``current(*, shop_id, channel) -> int`` (read-only; an
  absent row means ``INITIAL_EPOCH``) and ``advance(*, shop_id, channel, operator,
  reason) -> int``, the operator action described under *Recovering lost history*.
  ``advance`` raises ``ValueError`` on a blank operator, a blank reason, or a
  ``channel`` outside ``RAW_CHANNELS``, and logs ``etl_dedup_epoch_advanced`` at
  WARNING when it moves one
- ``INITIAL_EPOCH`` — ``0``; the epoch every row written before #1968 belongs to

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

## Ledger retention (fast track P62-B, D72.2)

`processed_events` is no longer permanent. The nightly `processed_events_retention` beat
(20:37 UTC, `workers/tasks/processed_events_retention.py`) calls
`persistence.ingest.retention.purge_processed_events`, which deletes rows older than
`PROCESSED_EVENTS_RETENTION_DAYS` (30) in committed batches of `PROCESSED_EVENTS_PURGE_BATCH`
(5,000), at most `PROCESSED_EVENTS_MAX_BATCHES_PER_RUN` (40) a night, through the owner-role
`public.purge_processed_events(retention_days, batch_size)` (migration 098, SECURITY DEFINER,
EXECUTE to `juli_app` only, refuses `retention_days < 14`). `juli_app` itself still has no
DELETE. Why 30 days is safe: re-presentation of the same `(event_id, epoch)` happens within
hours (poll overlap, retries) or days (history walk: 60 -> 180 days in 4 nights; webhook
redelivery); past the window a re-presented event is a no-op anyway because every silver
upsert refuses an `update_time` at or before the stored one. An epoch advance (below) is
unaffected: it never relied on old rows existing.

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

Operator and reason are recorded on the row alongside `advanced_at`, and the move is
logged as `etl_dedup_epoch_advanced` at WARNING, so a re-ingest is explainable months
later. The `channel` must be one the consumer actually reads (`RAW_CHANNELS`) — a
near-miss such as `tiktok.order.raw` for `tiktok.orders.raw` is refused rather than
returning an epoch for a channel nobody ingests, which would look like a successful
recovery and recover nothing. **Do not clear or delete ledger rows.** A `DELETE` is
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
   Since fast track P62-B (D72.3) `compute_demo_main_kpis_payload` aggregates in SQL (one
   row per order day + two single-row interval aggregates) instead of loading every
   `silver.orders` and product/shop-grain interval row of the shop on each recompute; the
   five KPI values are unchanged (all-time by contract, so aggregated rather than windowed).

Do **not** wire Celery material webhook enqueue or cross-shop batch jobs in A0 (#608).

## Deprecated aliases

- `KafkaRecord` → `IngestRecord`
- `transform_for_topic` → `transform_for_channel`
- `publish_dlq` kwarg on `EtlConsumer` → `dlq_handoff`
