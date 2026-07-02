# src/ingestion

## Purpose

Shared contracts and wiring helpers for the validation → ETL → Postgres ingest path.
Producers (webhook, polling) do not import broker clients; they call an injected
`HandoffFn` that typically delegates to `EtlConsumer.ingest`.

## Public API

- `HandoffFn` — `async (channel, shop_key, payload: bytes) -> None`
- `DlqHandoffFn` — same signature for DLQ envelopes
- `make_etl_handoff(consumer, *, clock=time.time) -> HandoffFn`
- `PublishFn` — deprecated alias for `HandoffFn`

## Dependencies

- `src/etl.consumer.EtlConsumer` (lazy import inside `make_etl_handoff` only)
- `src/etl.record.IngestRecord`

## Key Behaviors

- Keeps webhook/polling modules free of SQLAlchemy and transform logic
- Production wiring: one `EtlConsumer` per session + `make_etl_handoff` passed into
  `create_app` and polling runners
