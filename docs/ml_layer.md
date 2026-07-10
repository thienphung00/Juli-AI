# ML Layer

> **Tier 1 — T1–T10 technique catalog.** Read [`EXECUTION.md`](../EXECUTION.md) first.  
> **Owns:** per-KPI technique mapping, phasing status, promotion gates.  
> **Does not own:** promotion threshold numbers (`system-design.md` §3), schemas (`data-models/`), ADR rationale.

Governed by ADR-011. Promotion thresholds: [`system-design.md`](system-design.md) §3.

## MVP model selection (locked)

**Verdict: Adopt** the T1–T10 catalog below for MVP. Evaluated against phase gates
([`EXECUTION.md`](../EXECUTION.md)), data availability
([`architecture/data-sources.md`](architecture/data-sources.md)), and promotion
baselines in [`src/modules/ml/artifacts/thresholds.py`](../src/modules/ml/artifacts/thresholds.py).

| Proposal | Verdict | Authority |
|----------|---------|-----------|
| One trained model per Home KPI (~19) | **Reject** | ADR-005 — sprawl, vetting cost, collides with explainability |
| Prophet / LSTM / heavy holiday forecasters | **Reject** | ADR-005 — marginal benefit at ~90d bounded history |
| XGBoost / LightGBM / neural nets as default | **Defer** | `RandomForest*` sufficient at current backtest N; revisit with live volume |
| Learned-to-rank (T7) | **Reject** | ADR-005 — deterministic ranker for seller transparency |
| Isolation Forest / autoencoder (T4) | **Reject** | EWMA/z-score adequate for display-grade advisory |
| Sentiment / CSAT model | **Defer Phase 3** | No legal buyer text source (`data-sources.md` #17) |
| sklearn for T1 Home KPI forecasts | **Reject** | T1 is statsmodels ETS — shared across KPI series, not per-KPI RF |
| ML dynamic pricing model | **Defer** | T9 is deterministic rule engine for MVP; ML pricing requires price-elasticity data at scale |
| ML demand-based reorder quantity | **Defer** | T10 is deterministic ROP/EOQ for MVP; T1 ETS covers the display-grade demand signal |

**Simplest adequate stack:** rules (T3, T5, T9, T10) → EWMA/z-score (T4) → ETS (T1) →
deterministic rank (T7) → three recycled `RandomForest*` suites (T2, T6, T8) only
where tabular labels exist.

## Display-grade vs promotion gates

Every technique here is **display-grade**: it powers Home charts and advisory copy;
nothing in this layer executes a workflow. T2, T6, and T8 are **recycled** from the
former decision suites — they remain `sklearn` artifacts with backtest promotion
gates before Phase 2 MVP Milestone B inference load (Product sign-off #142).

| Tier | Meaning | Techniques |
|------|---------|------------|
| **Display-only** | No serialized model; auditable math/rules | T1, T3, T4, T5, T7, T9, T10 |
| **Display + promoted artifact** | Trained model; gate in `thresholds.py` | T2, T6, T8 |

## Technique catalog

Every KPI is powered by one of these shared building blocks.

| # | Technique | MVP algorithm (locked) | Min data / signals | Promotion gate | Code (Milestone A) |
|---|-----------|------------------------|--------------------|----------------|------------------|
| T1 | **Forecaster** | `statsmodels` ETS / Holt-Winters (additive; weekly seasonality when ≥2 full weekly cycles) + **naive-seasonal fallback** for short/sparse series | Daily KPI series; ≥14 points; seasonality only when ≥2 weekly cycles | None — report interval coverage vs naive-seasonal baseline | `src/modules/ml/forecaster/` *(planned)* |
| T2 | **Ads regressor** | `RandomForestRegressor` (ROAS) + `RandomForestClassifier(class_weight="balanced")` (scale/cut/hold); T1 overlay on chart series | Backtest ad spend + ROAS window | ROAS MAPE ≤ **50%** | `src/modules/ml/ad_performance/` |
| T3 | **Policy rules** | Deterministic VP/AHR thresholds ([`system-design.md`](system-design.md) §5) | Platform health fields (API or proxy) | Never ML | `seller_stage/rules.py`, platform-policy modules |
| T4 | **Statistical anomaly** | EWMA / rolling z-score vs baseline + configurable threshold | Stable rolling window (default ≥14 daily points) | None — display advisory only | `src/modules/ml/display_anomaly/` *(planned)* |
| T5 | **Deadline rule** | Per-order SLA countdown (`deadline − now` vs processing time) | Order timestamps + SLA config | Never ML | Operations fixtures / order SLA helpers |
| T6 | **Return-fraud detector** | `RandomForestClassifier(class_weight="balanced")` — `item_swap` / `empty_return` only (ADR-008) | Labeled returns + buyer aggregate features (Group A) | Per-class precision & recall ≥ **0.50** on `item_swap` + `empty_return` | `src/modules/ml/anomaly/` |
| T7 | **Ranker** | Deterministic weighted score-sort; weights in config; **no training** | Normalized KPI signals per entity | None | Config + rank helper *(planned under `src/modules/ml/ranker/`)* |
| T8 | **Router classifier** | `RandomForestClassifier(class_weight="balanced")` → `NEW_SHOP` \| `MID_LARGE_SHOP` + fixed rule set | Shop lifecycle features (Group B) | Precision ≥ **0.50** AND macro recall ≥ **0.50** | `src/modules/ml/seller_stage/` |
| T9 | **Pricing Engine** | Deterministic rule engine — inputs: Revenue by SKU delta, Conversion Rate by Category delta, competitor price signal (optional), configured margin floor. Rule set: (1) if conversion rate drops > threshold while session traffic is stable AND margin > floor → recommend price reduction (direction + Δ%); (2) if conversion rate + revenue rising → recommend price hold or marginal increase. No training. | SKU-level conversion rate trend (≥7d); revenue delta (≥7d); configured margin floor; competitor price signal (optional) | Never ML | `src/modules/ml/pricing/` *(planned)* |
| T10 | **Inventory Reorder Engine** | Deterministic reorder rule — Reorder Point (ROP) = (average daily sales × lead time days) + safety stock; recommended order quantity = EOQ or configured multiple. No training. | Average daily sales velocity (≥14d); configured lead time (days); configured safety stock; current inventory level | Never ML | `src/modules/ml/inventory_reorder/` *(planned)* |

> **Workflow-scoped techniques (T9, T10):** Unlike T1–T8, which power Home KPI
> tiles, T9 and T10 generate advisory output *inside* an execution workflow
> (pre-execution recommendation step). They do not appear in the per-KPI mapping
> table and do not render a Home chart.

**Outputs (common):**

| Technique | Consumer output |
|-----------|-----------------|
| T1 | Point forecast + prediction interval → Actual-vs-Forecast overlay; Growth/Risk from forecast vs actual |
| T2 | Efficiency signal + scale/cut/hold recommendation |
| T3 | Health-bar state + threshold gap |
| T4 | Risk flag + severity |
| T5 | Count of at-risk orders + priority order |
| T6 | Fraud-type label feeding return signals |
| T7 | Ordered list (SKU / Category / Product / Campaign) |
| T8 | Profile + rule set for copilot routing |
| T9 | Price recommendation (direction + Δ%) → pre-execution advisory inside Optimize Product and Create Hero Product workflows (formerly Update Product Listing / Create New Product Listing) |
| T10 | Reorder point signal + recommended order quantity → pre-execution advisory inside the Replenish Inventory workflow (Supplier / ERP path — formerly two separate workflows) |

Compare all trained techniques to **rules baselines** before promotion:
`seller_stage/rules.py`, `ad_performance/rules.py`. If rules meet the workflow need,
ship rules-only signals until backtest gates pass.

**Deferred (Phase 3):** sentiment / complaint analysis and CSAT modeling — no buyer
review/comment/chat text source exists in MVP and buyer chat is forbidden
(`architecture/data-sources.md` #17). The only legal free-text is `return_reason`.
CSAT renders as a deterministic proxy or "unavailable", never a model.

## Per-KPI mapping

| Component | KPI / Sub-KPI | Technique | Output signal | Ranking |
|-----------|---------------|-----------|---------------|---------|
| Revenue | Net Revenue (main) | T1 Forecaster | Growth / Risk | — |
| Revenue | AOV | T1 Forecaster | Growth / Risk | — |
| Revenue | Revenue by SKU | T1 + T7 | Growth / Risk | SKU |
| Revenue | Conversion Rate by Category | T1 + T7 | Growth / Risk | Category |
| Revenue | Repeat Purchase Rate | T1 + T7 | Growth / Risk | Product |
| Ads | ROAS (main) | T2 (+ T1 overlay) | Growth / Risk | Campaign |
| Ads | CAC | T2 (+ T1 overlay) | Growth / Risk | Campaign |
| Ads | CTR | T2 (+ T1 overlay) | Growth / Risk | Campaign |
| Inventory | Inventory Turnover (main) | T1 Forecaster | Growth / Risk | SKU |
| Inventory | DSI | T1 Forecaster | Growth / Risk | SKU |
| Inventory | Stockout Rate | T1 Forecaster | Risk | SKU |
| Operations | Fulfillment Accuracy Rate (main) | T4 Anomaly | Risk | — |
| Operations | Orders at SLA Risk | T5 Deadline rule | Risk | Order priority |
| Operations | Seller-Fault Cancellation Rate | T4 Anomaly | Risk | SKU |
| Customer Service | CSAT (main) | Deferred → deterministic proxy / unavailable | Growth / Risk | — |
| Customer Service | After-Sales Handling Time | T4 Anomaly | Risk | Ticket |
| Customer Service | Return Request Rate by SKU/Category | T7 + T6 (fraud) | Growth / Risk | SKU / Category |
| Shop Status | SPS (main) | T3 Policy rules | Risk | — |
| Shop Status | AHR | T3 Policy rules | Risk | — |
| Shop Status | Violation Points | T3 Policy rules | Risk | — |

> **Shop routing (T8):** runs ahead of the per-KPI signals and selects the rule
> set — NEW_SHOP (probation, not graduated) prioritizes creating new products +
> optimizing shop metrics; MID_LARGE_SHOP (graduated) uses the regular growth +
> loss-prevention rules.

## Intelligence track (not T1–T8)

Post-stream livestream and SKU depletion heuristics live under
`src/modules/catalog/domain/intelligence/` — **not** the Home KPI ML layer.

| Module | Method | Data | Notes |
|--------|--------|------|-------|
| `intelligence/forecasting` | Linear regression (≥30d) or moving average | Completed orders → SKU velocity | Read-only; equal SKU attribution MVP proxy |
| `intelligence/scoring` | Weighted score, ≥2σ anomaly, lexicon sentiment | Post-stream summary API | Not buyer-behavior anomaly (T6); no realtime telemetry |

Do not promote intelligence heuristics to T1/T4 without ADR-011 amendment and workflow
traceability.

## Phasing ([ADR-011](decisions/011-display-grade-analytics-layer.md))

| Phase | ML/analytics behavior | Data |
|-------|-----------------------|------|
| **Completed (pre-MVP)** | UI rendered mock/fixture forecasts, rankings, and risk flags | Mock JSON only |
| **Phase 2 MVP Milestone A** | Implement T1–T8 on backtest / synthetic parquet ([ADR-010](decisions/010-ml-module-tree-and-trainers.md)) | Parquet manifest; no live API |
| **Phase 2 MVP Milestone B** | Serve live at the **08:00 UTC** daily batch, **after API approval** | TikTok polling → feature build → inference |
| **Phase 3** | Sentiment / CSAT modeling; **Customer Service workflow execution** (Customer Service API + Return/Refund API); complaint text pattern mining; root-cause classification; buyer risk scoring; advanced return segmentation; ML dynamic pricing (upgrade T9 rules → elasticity model); ML demand-based reorder (upgrade T10 deterministic → ML forecast); polyglot store ([ADR-012](decisions/012-architecture-reconciliation-mvp-vs-target.md)) | Legal text sources TBD; CS API scopes TBD |

### Milestone A implementation status

| Technique | Status | EXECUTION slice |
|-----------|--------|-----------------|
| Backtest parquet + manifest | ✅ Shipped | P2-A1 (#136) |
| T8 Router classifier | 🔲 Open | P2-A2 (#138) |
| T6 Return-fraud detector | 🔲 Open | P2-A3 (#139) |
| T2 Ads regressor | ✅ Shipped | P2-A4 (#140) |
| Feature specs + inference signatures | 🔲 Open | P2-A5 (#142) |
| Artifact publish / metadata | ✅ Shipped | P2-A6 (#141) |
| T1 Forecaster (`statsmodels`) | 🔲 Not started | *Add slice before Milestone B* |
| T4 EWMA / z-score serving | 🔲 Not started | *Add slice before Milestone B* |
| T7 Deterministic ranker config | 🔲 Not started | *Add slice before Milestone B* |
| T3 / T5 rules wiring to Home KPIs | 🔲 Partial (orchestration mocks shipped pre-MVP) | pre-MVP |
| T9 Pricing Engine (deterministic rules) | 🔲 Not started | *Add slice before Milestone B* |
| T10 Inventory Reorder Engine (deterministic rules) | 🔲 Not started | *Add slice before Milestone B* |

**Backtest reference (seed 142, synthetic):** router 1.00/1.00 ✓; ads ROAS MAPE 0.54% ✓;
`empty_return` 0.00/0.00 ✗ (sparse labels — report per-class support, do not hide behind
macro averages). Full table: [`system-design.md`](system-design.md) §3.

## Boundaries

- Advisory only — the ML layer never executes; it emits signals consumed by the
  visual layer and routes the seller to a workflow in
  [`execution_layer.md`](execution_layer.md).
- Financial PII stays off any LLM prompt — pass tiers / deltas / trend direction
  only (`core-safety.mdc`, mle-agent).
- Features stay Python ([ADR-010](decisions/010-ml-module-tree-and-trainers.md)); SQL
  views are serving conveniences only ([ADR-012](decisions/012-architecture-reconciliation-mvp-vs-target.md)).
- Feature column names: [`data-models/feature-store-schema.md`](data-models/feature-store-schema.md)
  only; build via `src/modules/ml/features/`.
- Algorithm vetting before new techniques: [`.cursor/skills/domain/data-scientist/SKILL.md`](../.cursor/skills/domain/data-scientist/SKILL.md).
- Trainer implementation: [`.cursor/skills/domain/mle-agent.md`](../.cursor/skills/domain/mle-agent.md).
