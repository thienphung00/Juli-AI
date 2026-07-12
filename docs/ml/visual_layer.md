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

> **Phase 2 data gap:** Shop Status Partner API fields are not available to retrieve or
> extract. Home renders these KPIs from **mock / fixture data** with **no workflow
> mapping** until a live source exists. Do not route SPS/AHR/VP signals to Process Order,
> Prevent Cancellation, or Customer Service workflows in Phase 2.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **SPS** (main) | Horizontal health bar | T3 policy rule (mock) | SPS ↓ 4.6→4.4 · risk: performance deteriorating | — (no workflow; mock only) |
| AHR | Horizontal health bar | T3 policy rule (mock) | AHR ↓ 96%→92% · risk: account health weakening | — (no workflow; mock only) |
| Violation Points | Trend line | T3 policy rule (mock) | VP ↑ 2→5 · risk: penalties / reduced visibility | — (no workflow; mock only) |

## 2. Revenue

Business growth and revenue quality.

> **Bundle note:** Multi-SKU / bundle listing edits are a step inside **Optimize Product (2)**
> (`Edit Product` partial) — not a separate catalog workflow. See
> [`execution_layer.md`](../product/execution_layer.md) §2.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Net Revenue** (main) | Forecast line (Actual vs Forecast + interval) | T1 forecaster | Net Revenue ↑ 15% / 30d · opportunity: growth accelerating | Create Hero Product (1) · Optimize Product (2) |
| AOV | Trend line + forecast overlay | T1 forecaster | AOV $18→$24 · opportunity: higher spend/order | Create Hero Product (1) · Optimize Product (2) |
| Revenue by SKU | SKU ranking bar | T1 + T7 ranker | Product A +35% · opportunity: scale winners | Optimize Product (2) · Create Hero Product (1) |
| Conversion Rate by Category | Category ranking | T1 + T7 ranker | category listing effectiveness | Optimize Product (2) |
| Repeat Purchase Rate | Product cohort chart | T1 + T7 ranker | retention / hero products | Create Hero Product (1) · Optimize Product (2) |

## 3. Ads

Traffic acquisition efficiency and profitability. Powered by the recycled
ad-performance suite (T2) with a T1 forecast overlay.

> **Phase 2 execution surface:** Ads KPI signals route to **Promotion** workflows
> (Create / Update / Delete Activity — §7 in [`execution_layer.md`](../product/execution_layer.md)).
> Shop Ads **Marketing API** budget/bid writes (`business-api.tiktok.com`) remain out of
> Phase 2 Partner scope; Promotion API is the live approval-gated lever for conversion
> and traffic efficiency in Phase 2.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **ROAS** (main) | Forecast line (Actual vs Forecast) | T2 (+ T1 overlay) | ROAS 3.2→5.1 · opportunity: scale profitable campaigns | Create Activity (7a) · Update Activity (7c) · Delete Activity (7b) |
| CAC | Trend line | T2 | CAC ↑ 18% · risk: efficiency declining | Delete Activity (7b) · Update Activity (7c) |
| CTR | Campaign ranking | T2 + T7 ranker | CTR 1.8%→2.7% · opportunity: scale winners | Create Activity (7a) · Update Activity (7c) |

## 4. Inventory

Inventory efficiency and cash-flow health.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Inventory Turnover** (main) | Trend line + forecast | T1 forecaster | turnover 5.4x→3.1x · risk: cash trapped | Replenish Inventory (3) · Clear Excess Inventory (4) |
| DSI | Inventory age trend + forecast | T1 forecaster | DSI 42→71 days · risk: aging | Clear Excess Inventory (4) |
| Stockout Rate | Stockout risk forecast (Actual vs Forecast) | T1 forecaster | stockout 2%→8% · risk: lost sales | Replenish Inventory (3) |

## 5. Operations

Fulfillment quality and execution efficiency.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **Fulfillment Accuracy Rate** (main) | Gauge | T4 anomaly | 98.6%→95.2% · risk: errors rising | Process Order (5) · Prevent Cancellation (8a) |
| Orders at SLA Risk | Risk distribution bar | T5 deadline rule | 12→47 at risk · risk: late-ship penalties | Process Order (5) |
| Seller-Fault Cancellation Rate | Forecast trend line | T4 anomaly | 1.8%→4.7% · risk: SPS deterioration | Prevent Cancellation (8a) |

## 6. Customer Service

Customer satisfaction and post-purchase experience. **Buyer-messaging execution
(Resolve Recurring Customer Complaints) remains deferred to Phase 3** — Phase 2 shows
its KPI signals and workflow links for advisory routing only. Return/refund/cancellation
handling is a separate, **live** Phase 2 workflow (**Prevent Return (8b)** — formerly bundled
here as "Prevent Product Returns"); see [`execution_layer.md`](../product/execution_layer.md)
Post-sales and Customer Service sections.

| KPI | Graph type | ML feed | Signal example | Maps to |
|-----|-----------|---------|----------------|---------|
| **CSAT** (main) | Gauge | Deferred → proxy / "unavailable" (no text source in MVP) | shown as proxy or unavailable | Resolve Recurring Customer Complaints (deferred) — no live workflow |
| After-Sales Handling Time | Trend line | T4 anomaly | 8h→21h · risk: dissatisfaction | Prevent Return (8b) |
| Return Request Rate by SKU/Category | SKU/Category ranking | T7 ranker + T6 fraud | category X returns +28% | Prevent Return (8b) |

## KPI → workflow mapping (summary)

| Component | KPI | Workflow |
|-----------|-----|----------|
| Revenue | Net Revenue | Create Hero Product (1) · Optimize Product (2) |
| Revenue | AOV | Create Hero Product (1) · Optimize Product (2) |
| Revenue | Revenue by SKU | Optimize Product (2) · Create Hero Product (1) |
| Revenue | Conversion Rate by Category | Optimize Product (2) |
| Revenue | Repeat Purchase Rate | Create Hero Product (1) · Optimize Product (2) |
| Ads | ROAS (opportunity) | Create Activity (7a) · Update Activity (7c) |
| Ads | ROAS (risk) | Delete Activity (7b) · Update Activity (7c) |
| Ads | CAC | Delete Activity (7b) · Update Activity (7c) |
| Ads | CTR | Create Activity (7a) · Update Activity (7c) |
| Inventory | Inventory Turnover | Replenish Inventory (3) · Clear Excess Inventory (4) |
| Inventory | Stockout Rate | Replenish Inventory (3) |
| Inventory | DSI | Clear Excess Inventory (4) |
| Operations | Fulfillment Accuracy Rate | Process Order (5) · Prevent Cancellation (8a) |
| Operations | Orders at SLA Risk | Process Order (5) |
| Operations | Seller-Fault Cancellation Rate | Prevent Cancellation (8a) |
| Customer Service | After-Sales Handling Time | Prevent Return (8b) |
| Customer Service | Return Request Rate | Prevent Return (8b) |
| Customer Service | CSAT | — (deferred; Resolve Recurring Customer Complaints only) |
| Shop Status | SPS / AHR / Violation Points | — (mock only; no workflow) |

> **Authoritative taxonomy:** the workflows referenced above are owned by
> [`execution_layer.md`](../product/execution_layer.md), the single source of truth for the
> workflow → action taxonomy (ADR-011
> Decision #6). The former 3-Copilot / "exactly six validated workflows" framing is
> retired.
