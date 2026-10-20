# backend/src/juli_backend/services/product_history

## Purpose

Product history (fast track P23, D30.1a / D30.4): product snapshots when a
product's state changed, promotion activities, the `external_changes` log of
what changed on a product and who changed it, run baselines, and the overlap
annotation of a measurement window. Since P60-1b (ADR-107 "Amendment
2026-10-20" §6, §8; migration 096) every change is attributed **per field**.

## Public API

| Where | What |
|---|---|
| `normalize.field_value_hash(field, value)` | sha256 of a listing field in the form `product_snapshots` hashes it (title / description stripped text, ordered image URIs, sorted `[sku_id, list_price]`). The one helper the recorder, the attribution, the revert check and migration 096 share. |
| `normalize.ProductFields` | a read (`ProductFields.of(normalized)`) or a snapshot (`store.product_fields_of_snapshot`) hashable per field; `price` is hashed over the SKUs a write named. |
| `attribution.label_fields(kind, fields, state, writes, *, occurred_at, known_at)` | pure: `{field: juli / seller_revert / seller_change}`; `summarize` -> the row's `attribution` (or `mixed`). |
| `store.attribute_fields(session, ...)` | loads the product's `run_write_values` and labels a `Change`. |
| `store.matches_juli_write(...)` | unchanged signature: `all(label == 'juli')`. |
| `store.record_read(...)` / `store.record_change(...)` | store a read / one change with `attribution` + `field_attribution`; a change not entirely Juli's also writes its `seller_change` `card_events` row (`card_events.natural.record_seller_change`, never raises). |

## Attribution (§8)

Per field: the value now on TikTok hashes to the `after_hash` of a Juli write
of that product and field recorded in `[occurred_at - JULI_WRITE_LOOKBACK (72 h),
occurred_at + JULI_WRITE_LOOKAHEAD (1 h)]` -> `juli`; else it hashes to the
`before_hash` of the most recent Juli write of that (product, field), any age ->
`seller_revert`; else, or a field Juli never writes (attributes, category,
status, creation, promotion) -> `seller_change`. A price change is attributed on
Juli's one `price` field. Only writes known when the change was detected count
(`known_at`), so the live path and the backfill agree. A promotion row is all
`juli` or all `seller_change` by `promotions.is_juli_activity`.

## Invariants

- `external_changes` and `product_snapshots` stay append-only for `juli_app`
  (SELECT, INSERT); attribution is computed before the INSERT, never updated.
  Pre-096 rows were filled by migration 096's owner-run data step.
- `juli_write` is kept and equals "every field `juli`" for existing readers
  (`overlap.py`, measurement bodies).
- Nothing commits; under Postgres the caller holds the shop's scope (ADR-089).

## Dependencies

`models.history`, `models.run_changes`, `services.card_events.natural` (lazy, for
`seller_change`), TikTok reads only in `job.py`.
