# Module: etl

## Responsibility
Consumes raw TikTok Kafka topics (polling sync + webhook fan-out), deduplicates
by `event_id`, transforms payloads, and persists current-state entities through
`src/data` repositories. Malformed or unprocessable messages are published to
`tiktok.events.dlq` with error context.

## Public Interface

- `EtlConsumer` — async consumer with per-shop ordering and backpressure
  - `ingest(record: KafkaRecord) -> ProcessOutcome`
- `KafkaRecord` — `topic`, `partition_key` (TikTok shop id), `value`, optional
  `published_at` for latency checks
- `ProcessOutcome` — `PROCESSED` | `DUPLICATE` | `DLQ`
- `RAW_TOPICS`, `DLQ_TOPIC` — topic constants

## Dependencies
- `src/data` — `ShopsRepo`, `ProcessedEventsRepo`, commerce/analytics repos
- Standard library: `asyncio`, `json`, `logging`

Kafka clients are **not** imported — callers inject `publish_dlq` for testability.

## Invariants
- Partition key must match `shops.tiktok_shop_id` for persistence
- Duplicate `event_id` values are skipped without double-writing commerce rows
- Per-shop messages are processed serially (`asyncio.Lock` per shop key)
- Backpressure: when pending depth exceeds `max_pending_per_shop`, ingest waits
- Failed transforms after dedup claim still commit the claim and route to DLQ
- Latency budget defaults to 60 seconds (`LATENCY_BUDGET_SECONDS`)

## Owners
- domain: data
- code: `src/etl/`
- tests: `tests/unit/test_etl.py`
