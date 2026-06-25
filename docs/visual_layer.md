# Visual Layer

> **Tier 1 — Home KPI rendering.** Read [`EXECUTION.md`](../EXECUTION.md) first.  
> **Owns:** chart types, advisory signal format, KPI → workflow links.  
> **Does not own:** technique definitions (`ml_layer.md`), workflow taxonomy (`execution_layer.md`), IA detail (ADR-014).

Governed by ADR-011.

## Rendering principles

- **Visualize the ML output, not just the raw metric.** Forecast KPIs (T1) render
  an **Actual-vs-Forecast** overlay with the prediction interval band. Ranking KPIs
  (T7) render ordered bars. Comparative KPIs render **Actual-vs-benchmark / peers**.
- Every KPI shows a one-line signal: **What changed → Risk/Opportunity → Action**,
  then links to a workflow. Home is read-only — no approvals/execution
  (ADR-014).
- Color is advisory and never the only signal: Growth `#16A34A` / Loss `#E5484D`
  paired with text + icon ([ADR-007](decisions/015-design-system-token-foundation.md)).

## 1. Shop Status

Platform health category. SPS/AHR/VP are **deterministic policy rules** (T3), not ML.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **SPS** (main) | Horizontal health bar | T3 policy rule | SPS ↓ 4.6→4.4 · risk: performance deteriorating · investigate fulfillment/cancellation/CS | Accelerate Order Fulfillment · Prevent Order Cancellations · Resolve Recurring Customer Complaints |
| AHR | Horizontal health bar | T3 policy rule | AHR ↓ 96%→92% · risk: account health weakening | (same) |
| Violation Points | Trend line | T3 policy rule | VP ↑ 2→5 · risk: penalties / reduced visibility | (same) |

## 2. Revenue

Business growth and revenue quality.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Net Revenue** (main) | Forecast line (Actual vs Forecast + interval) | T1 forecaster | Net Revenue ↑ 15% / 30d · opportunity: growth accelerating | All growth workflows |
| AOV | Trend line + forecast overlay | T1 forecaster | AOV $18→$24 · opportunity: higher spend/order | Create New Product Listing · Create Product Bundle |
| Revenue by SKU | SKU ranking bar | T1 + T7 ranker | Product A +35% · opportunity: scale winners | Update Product Listing · Create New Product Listing · Create Product Bundle |
| Conversion Rate by Category | Category ranking | T1 + T7 ranker | category listing effectiveness | Update Product Listing |
| Repeat Purchase Rate | Product cohort chart | T1 + T7 ranker | retention / hero products | Create New Product Listing · Create Product Bundle |

## 3. Ads

Traffic acquisition efficiency and profitability. Powered by the recycled
ad-performance suite (T2) with a T1 forecast overlay.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **ROAS** (main) | Forecast line (Actual vs Forecast) | T2 (+ T1 overlay) | ROAS 3.2→5.1 · opportunity: scale profitable campaigns | Increase Ad Budget · Reduce Ad Spend |
| CAC | Trend line | T2 | CAC ↑ 18% · risk: efficiency declining | Reduce Ad Spend |
| CTR | Campaign ranking | T2 + T7 ranker | CTR 1.8%→2.7% · opportunity: scale winners | Increase Ad Budget · Reduce Ad Spend |

## 4. Inventory

Inventory efficiency and cash-flow health.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Inventory Turnover** (main) | Trend line + forecast | T1 forecaster | turnover 5.4x→3.1x · risk: cash trapped | Replenish via Supplier · Replenish via ERP · Clear Excess Inventory |
| DSI | Inventory age trend + forecast | T1 forecaster | DSI 42→71 days · risk: aging | Clear Excess Inventory |
| Stockout Rate | Stockout risk forecast (Actual vs Forecast) | T1 forecaster | stockout 2%→8% · risk: lost sales | Replenish via Supplier · Replenish via ERP |

## 5. Operations

Fulfillment quality and execution efficiency.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Fulfillment Accuracy Rate** (main) | Gauge | T4 anomaly | 98.6%→95.2% · risk: errors rising | Accelerate Order Fulfillment · Prevent Order Cancellations |
| Orders at SLA Risk | Risk distribution bar | T5 deadline rule | 12→47 at risk · risk: late-ship penalties | Accelerate Order Fulfillment |
| Seller-Fault Cancellation Rate | Forecast trend line | T4 anomaly | 1.8%→4.7% · risk: SPS deterioration | Prevent Order Cancellations |

## 6. Customer Service

Customer satisfaction and post-purchase experience. **Execution deferred to Phase 3**
— Phase 2 shows KPI signals and workflow links for advisory routing only; see
[`execution_layer.md`](execution_layer.md) Customer Service section.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **CSAT** (main) | Gauge | Deferred → proxy / "unavailable" (no text source in MVP) | shown as proxy or unavailable | Resolve Recurring Customer Complaints · Prevent Product Returns |
| After-Sales Handling Time | Trend line | T4 anomaly | 8h→21h · risk: dissatisfaction | Prevent Product Returns |
| Return Request Rate by SKU/Category | SKU/Category ranking | T7 ranker + T6 fraud | category X returns +28% | Prevent Product Returns |

## KPI → workflow mapping (summary)

| Component | KPI | Workflow |
|-----------|-----|----------|
| Revenue | Revenue by SKU | Update Product Listing · Create New Product Listing |
| Revenue | Revenue by SKU | Create Product Bundle |
| Revenue | Conversion Rate by Category | Update Product Listing |
| Revenue | Repeat Purchase Rate | Create New Product Listing |
| Revenue | Repeat Purchase Rate | Create Product Bundle |
| Revenue | AOV | Create Product Bundle |
| Ads | ROAS | Increase Ad Budget · Reduce Ad Spend |
| Ads | CAC | Reduce Ad Spend |
| Ads | CTR | Increase Ad Budget |
| Inventory | Stockout Rate | Replenish via Supplier · Replenish via ERP |
| Inventory | DSI | Clear Excess Inventory |
| Operations | Orders at SLA Risk | Accelerate Order Fulfillment |
| Operations | Seller-Fault Cancellation Rate | Prevent Order Cancellations |
| Customer Service | After-Sales Handling Time | Prevent Product Returns |
| Customer Service | Return Request Rate | Prevent Product Returns |
| Shop Status | SPS / AHR / Violation Points | Fulfillment / Cancellation / Complaint workflows |

> **Authoritative taxonomy:** the workflows referenced above are owned by
> [`execution_layer.md`](execution_layer.md), the single source of truth for the
> workflow → action taxonomy (ADR-011
> Decision #6). The former 3-Copilot / "exactly six validated workflows" framing is
> retired.
