# ADR-065: Finance Statement mapping — capture real `fee_amount`/`shipping_cost_amount`, drop phantom platform/affiliate split

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-063](063-t10-inventory-reorder-engine.md), [ADR-064](064-product-performance-classifier.md)
(same "real algorithm, real data" bar).
**Blocks:** T9 fee-adjusted price rule (ADR-066) — that work is not buildable until this lands.
**Does not change:** `SettlementsResource.list`/`list_all` call shape or the `GET
/finance/202309/statements` endpoint/scope already in use — this is a mapping fix, not a
new integration.

## Context

Verified against the TikTok Partner corpus (`api-reference/finance/get-statements-202309.md`,
Architect catalog retrieval per ADR-051), the real `GET /finance/202309/statements`
response shape is:

```json
{ "id", "statement_time", "settlement_amount", "revenue_amount", "fee_amount",
  "adjustment_amount", "net_sales_amount", "shipping_cost_amount", "payment_status",
  "payment_id" }
```

Fees return as **one combined `fee_amount`** — there is no platform-vs-affiliate split
available from this endpoint. That split only exists at SKU level via `Get Transactions
by Order` (`revenue_breakdown`), which Juli does not ingest today (flagged as a separate,
larger future integration in ADR-066's context, out of scope here).

Juli's `Settlement` table (migration `004_add_livestream_creator_settlement_fields.py`)
has `platform_commission` and `affiliate_commission` columns, but grepping the codebase
confirms **no service, mapper, or ETL code ever assigns them a value** — they appear only
in the migration itself and in `ai/features/schema.py` (a synthetic backtest-parquet
column, unrelated to live ingestion). `FinanceStatement`
(`integrations/tiktok/schemas.py`) doesn't declare `fee_amount` or `shipping_cost_amount`
at all, and `normalize_statement` (`mapping.py`) only maps `settlement_id`, `amount`,
`settlement_time`, `update_time`. Result: `platform_commission` and `affiliate_commission`
are **always `Decimal("0")`** for every synced row — a schema default masquerading as real
data, discovered only by cross-checking the live table against the actual API docs before
building on it.

## Decision

**Fix the mapping to capture what the API actually returns; drop the columns that were
never populatable from this endpoint.**

- Add `fee_amount` to `FinanceStatement` (schemas.py) and `Settlement` (models.py) —
  named to match the real API field exactly, avoiding a repeat of the phantom-label
  problem (CONTEXT.md § Execution already forbids phantom integration labels).
- Fix `shipping_fee` mapping — wire `normalize_statement` to actually pull
  `shipping_cost_amount` into the existing (currently dead) `shipping_fee` column.
- Drop `platform_commission` and `affiliate_commission` — no live source can populate
  them from `Get Statements`; keeping unpopulatable columns is the same phantom-data risk
  that caused this ADR. Reintroduce only if/when SKU-level Finance ingestion
  (`Get Transactions by Order`) is built and can genuinely split the two.
- Store values as the API returns them (signed deductions, e.g. `"-30"`) — sign/abs
  handling is a consumer concern (ADR-066), not an ingestion concern, consistent with how
  the rest of `services/aggregates` treats raw synced values.
- No backfill required — statements are re-polled daily; the fix forward-fills on the
  next sync.

## Consequences

- `Settlement.platform_commission`/`affiliate_commission` are a breaking schema change
  (columns dropped), but nothing depends on real values from them — every existing
  consumer would only ever have seen `0`.
- T9 (ADR-066) becomes buildable on `fee_amount` + `shipping_fee` (now real).
- `ai/features/schema.py`'s `affiliate_commission` reference is unaffected (synthetic
  backtest parquet, not live DB) but now names a concept with no live-data counterpart —
  noted, not fixed here (legacy `ai/` track, out of scope).
- Sets a standing practice: before building a signal/algorithm on an existing synced
  table, verify the mapping against the vendor's real API docs rather than trusting the
  ORM field names — this is exactly the gap that would have shipped a permanently-zero
  T9 fee rule.

## Options considered

| Option | Outcome |
|--------|---------|
| Repurpose `platform_commission` to silently hold the combined `fee_amount` | Rejected — mislabeling a combined fee as "platform commission" is exactly the phantom-label problem this ADR exists to fix |
| Leave columns as-is, build T9 on a configured constant instead of `Settlement` | Rejected — user directive is real data over configured guesses whenever real data is reachable without new integration work; this fix needs no new endpoint/scope, only a mapping correction |
| **Add `fee_amount`, fix `shipping_fee` mapping, drop unpopulatable columns (chosen)** | Real data, honest schema, minimal-scope prerequisite for T9 |
