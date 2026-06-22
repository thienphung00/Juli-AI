# ADR 005: Buyer-behavior anomaly scope

## Status
Accepted

## Context

The anomaly detector scores buyer return patterns that directly bleed seller GMV:

- **`item_swap`** — buyer returns a different item than shipped
- **`empty_return`** — buyer returns an empty parcel or packaging without the product

Affiliate fraud, creator-attributed refund spikes, and commission disputes are
**excluded** from anomaly ML. Those signals surface via deterministic platform-policy
rules in Phase 2 MVP.

## Decision

- **We will:** Train and serve the anomaly detector only on buyer-behavior signals
  from Orders + return/refund records — classes `item_swap` and `empty_return`.
- **We will:** Document schema contract in `system-design.md` and `tiktok_api/endpoints.md`
  mapping mock → backtest parquet → Postgres → TikTok API fields.
- **We will not:** Include affiliate cancellation patterns or creator-attributed
  refund spikes in anomaly ML training or inference.
- **We will not:** Remove TikTok Affiliate from polling — it powers commission-dispute
  **policy alerts** and growth context, but not the anomaly model.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Backtest parquet uses `return_type` enum with synthetic `item_swap` / `empty_return` labels.
- Phase 2 MVP ETL maps TikTok order/return API fields to the canonical contract.
