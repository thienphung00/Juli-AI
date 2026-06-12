# ADR 011: Buyer-Behavior Anomaly Scope (Phase 1.5)

## Status
Accepted

## Context

Revenue Leakage Detection originally scoped the **anomaly detector** to returns,
affiliate fraud, commission disputes, and balance withholding. Product rescope
(June 2026) narrows **ML anomaly detection in Phase 1.5** to buyer-behavior
patterns that directly bleed seller GMV through returns:

1. **Item swap** — buyer returns a different item than shipped (wardrobing / swap).
2. **Empty return** — buyer returns an empty parcel or packaging without the product.

Affiliate fraud detection is **removed** from the anomaly ML suite. Commission
disputes, balance withholding, and VP/AHR milestones remain **deterministic
platform-policy rules** in Phase 2 (not ML).

Phase 1.5 trains on parquet/synthetic data with **no live API**. Phase 2 polls
TikTok Orders (and return/refund edges). Schema drift between P1.5 backtest and
P2 API mapping causes rework — field names and enums must be fixed in docs now.

## Decision

- **We will:** Train the Phase 1.5 anomaly detector only on **buyer-behavior**
  signals derived from **TikTok Orders + return/refund records** — classes
  `item_swap` and `empty_return`.
- **We will:** Document a single schema contract in `system-design.md` and
  `tiktok_api/endpoints.md` that maps P1 mock → P1.5 parquet → P2 Postgres →
  TikTok API fields.
- **We will not:** Include affiliate cancellation patterns, creator-attributed
  refund spikes, or affiliate commission fraud in the anomaly ML training set
  or validation ground truth.
- **We will not:** Remove TikTok Affiliate from Phase 2 polling — it still powers
  commission-dispute **policy alerts** and Growth context, but not the anomaly model.

## Why this architecture

- **Speed:** One orders/returns schema path from mock through parquet to API
  reduces P2-1 mapping errors.
- **Cost:** Smaller feature space (two anomaly classes + buyer aggregates) trains
  faster on backtest data.
- **Scalability:** Buyer-level aggregates (`buyer_id` masked) compose cleanly with
  daily batch inference.
- **Reliability:** Platform-policy signals (VP, withholding, disputes) stay
  deterministic — no ML false positives on account health.

## Options considered

- **Option A: Keep affiliate fraud in anomaly ML** — broader leakage coverage but
  needs affiliate + orders join features, noisy ground truth, and duplicates
  policy-rule signals. **Rejected.**
- **Option B: Buyer-behavior only (chosen)** — focused GMV leakage via returns;
  affiliate fraud deferred to platform enforcement + policy rules.
- **Option C: Rules-only for all leakage** — no ML in P1.5. **Rejected** — EXECUTION.md
  still requires three model suites; seller stage + ad models unchanged.

## Consequences

- **Positive:** Clear P1.5 validation set (labeled item_swap / empty_return cases);
  P2 order ETL can be validated against documented field map.
- **Negative:** Affiliate-driven GMV loss is surfaced via policy/commission alerts,
  not ML anomaly scores, until a future phase rescopes.
- **Follow-ups:** P1.5-1 parquet generator must emit `return_type` enum; canonical schemas in
  [`docs/data-models/`](../data-models/README.md); P2-1 must confirm return/refund reason fields
  in Partner Center API Reference.

## Rollout / Migration plan

1. Update canonical docs (this ADR session).
2. P1.5-1: backtest parquet uses schema contract; synthetic generator labels
   `item_swap` / `empty_return`.
3. P1.5-3: train anomaly detector; ground truth = buyer-behavior labels only.
4. P2-1: map TikTok order/return API fields to contract; extend `Order` ETL if
   return edges require separate persistence.
