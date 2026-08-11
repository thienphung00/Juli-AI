# ADR-063: T10 Inventory Reorder Engine — promote `ai/forecasting` into pre-execution advisory

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-011](011-display-grade-analytics-layer.md) (ml_layer.md T1–T10 catalog),
[ADR-021](021-manual-refresh-pipeline-and-action-card-persistence.md) (action-card pipeline).
**Does not change:** `services/scoring` daily signal computation; `WorkflowRecommendation` /
`ScoringSignals` schemas; `services/execution/inventory_leakage.py` execution logic; the
`replenish_inventory_3` → `inventory.replenish` workflow/tool mapping.

## Context

`docs/ml/ml_layer.md` locks a T10 "Inventory Reorder Engine" (deterministic ROP/EOQ) as a
workflow-scoped pre-execution advisory for the Replenish Inventory workflow, but its
Milestone A status is "🔲 Not started." Today `run_replenish_inventory_chain`
(`services/execution/inventory_leakage.py`) takes `quantity = payload["quantity"]`
verbatim — no algorithm recommends a number; the seller (or UI stub) supplies it blind.

Separately, `backend/src/juli_backend/ai/forecasting/forecaster.py` already implements
real, tested per-SKU sales-velocity forecasting (`get_forecast`, `get_low_stock_risks`,
`get_velocity_changes`) against `Order`/`InventoryItem` — linear regression at ≥30 days
of history, moving-average fallback otherwise, equal-attribution proxy across a shop's
active SKUs (no per-SKU line items yet). This module has **zero callers** outside its own
tests; it was built for a since-abandoned Creator↔Shop Matching direction
(`ai/recommendations/MODULE.md`) and never wired into the live action-card pipeline.

The live pipeline (`services/aggregates/computed_kpis.py`) only computes **shop-level**
inventory_turnover/DSI/stockout — sufficient to flag "stockout risk" but not which SKU or
how much to reorder. No schema field exists anywhere for supplier lead time or safety
stock; per ml_layer.md's own T10 spec, these are configured constants, not DB reads.

## Decision

**Promote `ai/forecasting`'s velocity/depletion math into T10, computed lazily at
Inputs-review time — not as a new daily `ScoringSignals` field.**

- **Trigger:** when a seller opens the Inputs step of the Replenish Inventory five-stage
  review (Why → Analytics → Inputs → Preview → Approve), not during the daily batch scan.
  `WorkflowRecommendation` / `ScoringSignals` are unchanged.
- **SKU targeting:** default to the top-urgency SKU from `get_low_stock_risks(shop_id)`;
  seller may swap SKU via the existing product/SKU picker.
- **Algorithm:** `daily_velocity` from `get_forecast(shop_id, sku_id)`; then
  `ROP = daily_velocity × lead_time_days + safety_stock`,
  `recommended_qty = max(0, ROP − current_quantity)`.
- **Constants (no real data source exists for these — configured, not derived):**
  `lead_time_days = 7` (flat; no per-supplier config yet); `safety_stock = 3 ×
  daily_velocity` (scales with SKU sell-through instead of a flat unit count).
- **UI contract:** prefilled `quantity` + `sku_id`, editable, with the locked "Gợi ý bởi
  Juli" glow pattern (PRD #600) — never a silent auto-fill.
- **Execution:** `POST /v1/executions` carries whatever quantity the seller confirms.
  `run_replenish_inventory_chain` needs **zero code changes** — it already executes
  `payload["quantity"]` as given.

## Consequences

- `ai/forecasting` becomes a live dependency of the product surface for the first time;
  its docstring lineage ("legacy signal," Creator-matching pivot) is now stale for this
  path and should be corrected when the code moves/is referenced from the advisory layer.
- Per ml_layer.md's own rule, promoting an "intelligence" heuristic into a T-catalog slot
  requires ADR + workflow traceability — this ADR is that record. Milestone A status for
  T10 moves from "Not started" to "Shipped (rule-based, lazy compute)."
- `lead_time_days`/`safety_stock` are global constants at launch; a per-shop or
  per-supplier config surface is deferred until real lead-time data exists.
- The equal-attribution velocity proxy (documented limitation in `forecaster.py`) carries
  over: `daily_velocity` divides shop order-count evenly across active SKUs until
  per-SKU order line items exist. Recommended quantities inherit this imprecision.
- **Flagged, not resolved here:** `CONTEXT.md` § Inventory still documents "Supplier-sourced
  replenishment" and "ERP-sourced replenishment" as two distinct workflows; the code and
  `ml_layer.md` (T10 row) already collapsed these into one `replenish_inventory_3`
  workflow. CONTEXT.md needs a follow-up correction pass — out of scope for this ADR.

## Options considered

| Option | Outcome |
|--------|---------|
| Write a fresh T10 implementation directly in `services/scoring`, no `ai/` reuse | Rejected — duplicates tested velocity/depletion math for no benefit; contradicts "actual algorithm on actual data, doesn't need to be complex" goal |
| Bake T10 into the daily `compute_scoring_signals` batch, add a per-SKU field to `WorkflowRecommendation` | Rejected — reshapes shared dataclasses consumed by every other KPI/workflow for one workflow's benefit; T9/T10 are explicitly workflow-scoped, not visual-layer, per ml_layer.md |
| Add real `lead_time_days`/`safety_stock` columns + a seller-facing config UI now | Rejected for this pass — no data pipeline feeds real lead-time data yet; premature UI surface for a v1 |
| **Lazy per-SKU compute at Inputs-review, reuse `ai/forecasting`, config constants (chosen)** | Real algorithm on real data, minimal blast radius, zero execution-layer changes |
