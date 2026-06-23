# System Design

> **Tier 1 — subsystem envelopes.** Read [`EXECUTION.md`](../EXECUTION.md) first for slices and routing.  
> **Owns:** pipeline stage shapes, subsystem phase matrix, ML promotion thresholds, JSON envelopes.  
> **Does not own:** module paths (`map.md`), data-source phase gates (`data-sources.md`), MVP diagram/schedule (`phase-2-mvp.md`), ADR rationale (`decisions/`).

**Authority:** `EXECUTION.md` > this file > `map.md`.

## Scope pointer

Product summary and documentation routing: [`EXECUTION.md`](../EXECUTION.md).  
UI / IA detail: ADR-014 · Design tokens: ADR-015 · Pipeline constraints: ADR-013 · Layer model: ADR-011.

---

## Phase capability matrix

Pre-MVP work is summarized in [`phase-1-completed.md`](phases/phase-1-completed.md).

| Subsystem | Completed (pre-MVP) | Phase 2 MVP Milestone A | Phase 2 MVP Milestone B | Phase 3 |
|-----------|---------------------|-------------------------|-------------------------|---------|
| **Agent decision tree** | Rules-based classification (mock) | Router classifier (backtest) | Live daily scoring | Real-time scoring |
| **Data pipeline** | Mock JSON fixtures | Backtest parquet | TikTok API polling → Postgres | Event streams + polyglot |
| **Health check** | Mock indicators | — | Live health scoring | Real-time alerts |
| **ML models** | Mock/fixture signals | Trained, serialized (T1–T8) | Production inference (08:00 UTC) | Expanded techniques |
| **Copy / reasoning** | Rules-only templates | Rules-only templates | Haiku + rules fallback | DSPy optimization |
| **Executor** | Mock export / mock execute | (no changes) | Real task triggers | Expanded executors |
| **Outcome tracking** | Mock metrics | Model metrics | Real outcome metrics | Real-time status |
| **Workflow UI** | 3-tab IA + modals (ADR-014, ADR-015) | (no changes) | Live inference + same modals | Real-time updates |

---

## Operations-system pipeline (Phase 2 MVP)

The orchestration spine runs over the operational workflow subset. Each stage has an
explicit output envelope; Milestone B swaps mock loaders for live data / inference /
Haiku copy without changing the stage shapes (ADR-013).

```
Data Collection (unified_operational_data_model)
  ↓
Health Check (health_check_results)
  ↓
Shop Profile Classification (shop_profile)
  ↓
Workflow Recommendation & Ranking (workflow_recommendations)
  ↓
LLM Reasoning (reasoning_summary — copy layer)
  ↓
User Approval (approved_workflows)
  ↓
Copilot Execution (workflow_results — mock in P1.8)
  ↓
Outcome Tracking (workflow_outcome_metrics)
```

### Shop profiles & workflow taxonomy

`shop_profile ∈ {NEW_SHOP, MID_LARGE_SHOP}`. The **T8 router** selects the rule set per
profile; the workflow taxonomy itself is owned by [`execution_layer.md`](execution_layer.md)
(domain-organized; each action owned by exactly one workflow). The closed "exactly six /
Copilot surface" framing is **retired** ([ADR-011](decisions/011-display-grade-analytics-layer.md)
Decision #6). New display-grade techniques/workflows may be added when they map to a
visual-layer KPI and are advisory-only (constraint #3).

The operational subset wired through the pre-MVP pipeline (and its shipped/deferred
execution status) is:

| Profile | Operational workflow | Execution-layer home | P1.8 status | Real execution |
|---------|----------------------|----------------------|-------------|----------------|
| NEW_SHOP | Add New Product Listings (NPL) | Create New Product Listing | Executable — P1.6 `ListingWorkflowPanel` | P2-B7 / P2-B8 |
| NEW_SHOP | Minimize Violations | Operations / Customer Service rules | Card + reasoning; approve = no-op | P2-B13 |
| MID_LARGE_SHOP | Budget Optimization | Increase Ad Budget / Reduce Ad Spend | Card + reasoning; approve = no-op | P2-B14 |
| MID_LARGE_SHOP | Product Scaling | Update Product Listing / Replenish Inventory | Card + reasoning; approve = no-op | P2-B14 |
| MID_LARGE_SHOP | Refund Spike Detection | Prevent Product Returns / Prevent Order Cancellations | Executable — P1.7 `LeakageWorkflowPanel` (4 sub-journeys) | P2-B9 / P2-B10 |
| MID_LARGE_SHOP | Stockout Prevention | Replenish Inventory | Card + reasoning; approve = no-op | P2-B12 / P2-B15 |

**Refund Spike sub-journeys (P1.7 task types under one operational workflow):**
`return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy`.
Ranking may surface any sub-journey; approval routes to the matching leakage panel flow.

**Growth mock UI (P1-4):** reference UI from pre-MVP — P1.8 does **not** route approved
Budget Optimization or Product Scaling into that panel; cards + no-op only.

**Classification criteria (rules, mock in P1.8):**

- **NEW_SHOP** — active shop in probation OR has not met graduation requirements.
  Focus: probation completion (maximize SPS + AHR).
- **MID_LARGE_SHOP** — graduated probation, 90+ days active, or ≥2 GMV metrics
  tracked. Focus: revenue growth + loss prevention.

Do **not** recommend growth/loss-prevention workflows to NEW_SHOP, or probation
workflows to MID_LARGE_SHOP.

### Health Check indicators (mock in P1.8)

`health_check_results` is keyed by indicator; each indicator must inform ≥1 workflow.

| Indicator | Used by | Output |
|-----------|---------|--------|
| Probation progress | NPL, Minimize Violations | % toward graduation, days remaining |
| SPS health | NEW_SHOP, probation decision | current SPS, threshold gap |
| AHR health | NEW_SHOP, probation decision | current AHR, threshold gap |
| Ad ROAS efficiency | Budget Optimization | ROAS by campaign, % below target |
| Inventory health | Stockout Prevention | days of inventory remaining, lead-time coverage |
| Refund spike indicator | Refund Spike Detection | refund rate 7d vs 30d, % change, severity flag |
| Product scaling opportunity | Product Scaling | top SKUs by growth potential |

> **SPS vs VP/AHR:** SPS (Shop Performance Score) is a **probation/graduation
> progress** indicator, **distinct** from the VP/AHR **account-health** contract
> (§ Platform policy signals; [ADR-006](decisions/006-dual-read-vp-ahr-transition.md)).
> Both are mock in P1.8; real exposure is gated by P2-B1 verification.

### Recommendation & ranking (mock in P1.8)

`workflow_recommendations` per [ADR-013](decisions/013-operations-pipeline-spine.md):
each item carries `workflow_id`, `workflow_name`, `priority`, `rationale`,
`expected_impact {metric, value, confidence}`, `preconditions_met`,
`user_action_required`.

**Output envelope (`workflow_recommendations`):**

```json
{
  "shop_profile": "NEW_SHOP | MID_LARGE_SHOP",
  "recommended_workflows": [
    {
      "workflow_id": "string",
      "workflow_name": "string",
      "priority": 1,
      "rationale": "string",
      "expected_impact": {
        "metric": "string",
        "value": 0,
        "confidence": "high | medium | low"
      },
      "preconditions_met": true,
      "user_action_required": true
    }
  ]
}
```

**Ranking logic (rules, mock in P1.8):**

- **NEW_SHOP:** determine probation requirement status (NPL, Minimize Violations) →
  identify incomplete requirements → rank by probation timeline urgency. Do **not**
  recommend growth or loss-prevention workflows.
- **MID_LARGE_SHOP:** score Budget Optimization (ROAS efficiency), Product Scaling
  (scaling potential), Refund Spike (severity + corrective feasibility), Stockout
  Prevention (inventory risk) → rank by expected revenue impact / urgency → filter
  where expected impact > threshold (**numeric threshold: Product lead — required
  before P1.8-4 ships**; mock may skip filter until set).

### LLM reasoning (copy layer)

Maps onto the **copy layer** (§4). For each recommendation the layer renders **Why**
(triggering health signals), **Expected Impact** (quantified), **Priority**, and
**Next Steps** — rules-only templates in pre-MVP; Haiku + rules fallback in Phase 2 MVP Milestone B.
layer **never** invents workflows or claims capabilities beyond the validated catalog.

### Approval, execution & outcome tracking

- **Approval gate:** approve-all / selective / reject-with-reason / request-details.
  Rejections log a reason and recommend re-evaluation in 7 days.
- **Execution (mock in P1.8):** approved workflows route to their existing panel
  (listing / leakage / growth) or **no-op** for deferred workflows; validate
  preconditions; capture `workflow_results` (success / partial / failed). No retries
  without explicit approval; no escalation to other workflows.
- **Outcome tracking (mock in P1.8):** `workflow_outcome_metrics` per workflow with
  success criteria + cadence (real-time execution status → daily preliminary →
  weekly full assessment → monthly aggregate).

| Workflow | Metric | Period | Success criteria |
|----------|--------|--------|------------------|
| NPL | SPS change | 7d post-publish | ≥ +5 SPS points |
| Minimize Violations | AHR / violation count | 7d | ≥ +10 AHR points OR violations ↓ |
| Budget Optimization | ROAS / revenue | 7d | ROAS +15% OR revenue +10% |
| Product Scaling | Revenue per scaled SKU | 14d | ≥ +20% for scaled products |
| Refund Spike Detection | Refund rate | 7d | Returns to baseline |
| Stockout Prevention | Stockouts avoided | 30d | 0 unplanned stockouts |

### Unified operational data model (P1.8 fixtures)

Collect **only** data required by the six workflows. Output:
`unified_operational_data_model` (JSON; schema in P1.8-2 fixtures).

| Data set | Key fields | Workflows powered |
|----------|------------|-------------------|
| Shop metadata | `shop_id`, `profile`, `probation_status`, `graduation_date` | All (routing) |
| New Shop probation | probation dates, SPS, SPS threshold, AHR, AHR threshold, violations | NPL, Minimize Violations |
| Ad campaign performance | campaign id/name/status, spend, impressions, clicks, CTR, conversions, revenue, ROAS, CPC, CPM | Budget Optimization |
| Product performance | product/SKU, category, units/revenue (24h/7d/30d), price, margin, sell-through | Product Scaling, NPL gaps |
| Inventory & logistics | inventory level, sales velocity, reorder lead time | Stockout, Product Scaling |
| Returns & refunds | refund count/rate, top reasons, return authorization status | Refund Spike |

> SPS is Seller Center UI today — mock in P1.8; P2 uses `health_data_source`
> contract ([`integration-audit-2026-06.md`](tiktok_api/integration-audit-2026-06.md) §7).

### UI & design (ADR-owned — not duplicated here)

- **App structure, tabs, RRAA journey:** ADR-014
- **Design tokens:** ADR-015
- **Listing workflow implementation:** ADR-016

Runtime code references these decisions; envelope shapes for pipeline stages are below.

### Architecture constraints (ADR-013, ADR-011)

Traceability and display-grade vs decision-grade rules are ADR-owned. Subsystem sections below assume those constraints.

---

## Subsystems

### 1. Agent decision tree

Routes a seller to the right workflow and the right next action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Rules-based seller-stage detection from mock seller profile (e.g. order count, shop age thresholds → `NEW_SHOP` vs `MID_LARGE_SHOP`). Deterministic, hand-tuned. |
| **Phase 2 MVP Milestone A** | Train **router classifier** (T8) on backtest data; compare against rules baseline (§3). |
| pre-MVP | Extend to `shop_profile ∈ {NEW_SHOP, MID_LARGE_SHOP}` and feed the recommendation & ranking stage (§ Operations-system pipeline). Rules-based, mock input. |
| **Phase 2 MVP** | Live daily scoring — router runs on real polled seller data each morning; decision tree consumes model output to select profile, workflows + ranked tasks. |

### 2. Data pipeline

| Phase | Source | Mechanism |
|-------|--------|-----------|
| **Phase 1** | Mock JSON | Fixtures generated from [`data-models/canonical-entities.md`](data-models/canonical-entities.md) via [`mock-data-generator.md`](data-models/mock-data-generator.md). No network. |
| **Phase 2 MVP Milestone A** | Backtest data (parquet) | Canonical entity parquet + labeled returns; synthetic when historical data unavailable. Feature build uses [`feature-store-schema.md`](data-models/feature-store-schema.md). |
| **Phase 2 MVP** | TikTok API polling | Raw responses ingested per [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md); ETL normalizes to canonical entities → Postgres; daily feature build → inference. |

**Schema authority:** [`docs/data-models/`](data-models/README.md) defines platform-agnostic
entities and ML features. [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md) is the
**ingestion layer** only — vendor field maps, not ML schema source of truth
([ADR-009](decisions/009-entity-centric-data-model.md)).

```
TikTok API (endpoints.md)
        │  poll / webhook
        ▼
Raw responses
        │  ETL: vendor map, enum derivation, buyer_id masking
        ▼
Canonical entities (data-models/canonical-entities.md)
        │  06:00–07:00 UTC feature build
        ▼
Feature store (data-models/feature-store-schema.md)
        │  08:00 UTC batch inference
        ▼
Model outputs → agent decision tree → copy layer → UI / executor
```

Pipeline jobs (feature build → train → inference) are kept as **separate,
runner-agnostic jobs** so the Phase 2 MVP scheduler is a runner swap, not a rewrite.
Phase 2 MVP uses a simple daily scheduler (cron / APScheduler). Celery / Kafka are
**out of scope** (Phase 3+, see EXECUTION.md → Explicitly out).

### 3. ML models

> **Authority:** [`ml_layer.md`](ml_layer.md) technique catalog + per-KPI mapping;
> [ADR-011](decisions/011-display-grade-analytics-layer.md) display-grade vs
> decision-grade split.

**Not built in Phase 1** (UI renders mock/fixture forecasts, rankings, and risk
flags). Techniques implemented + validated on backtest data in **Phase 2 MVP Milestone A**;
served at the **08:00 UTC** daily batch in **Phase 2 MVP** (after TikTok API approval).

#### Display-grade vs decision-grade

| Tier | Purpose | Vet gate |
|------|---------|----------|
| **Display-grade** | Powers Home KPI charts + one-line advisory signals; never executes | Lightweight; maps to ≥1 workflow; constraint #3 + ADR-011 |
| **Decision-grade** | Gates a money-moving action behind the approval gate | Explicit vetting + promotion thresholds (#142) |

The former "three vetted suites" framing is **retired** — logic is recycled into
the display-grade layer (seller-stage → **router classifier** T8; anomaly →
**return-fraud detector** T6; ad-performance → **ads regressor** T2). Promotion
targets below apply to those **decision-grade** recycled techniques.

#### Technique catalog (T1–T8)

See [`ml_layer.md`](ml_layer.md) for the full per-KPI mapping, locked MVP algorithms,
and rejection table. Shared building blocks:

| ID | Technique | Implementation (Phase 2 MVP Milestone A) | Serve (Phase 2 MVP) |
|----|-----------|------------------------------|---------------------|
| T1 | Forecaster | `statsmodels` ETS / Holt-Winters + naive-seasonal fallback | Point forecast + interval |
| T2 | Ads regressor | `RandomForestRegressor` + `RandomForestClassifier` (recycled ad-performance suite) | Efficiency signal |
| T3 | Policy rules | Deterministic platform-policy thresholds (§5) | Health-bar state |
| T4 | Statistical anomaly | EWMA / rolling z-score vs baseline | Risk flag + severity |
| T5 | Deadline rule | Per-order SLA countdown | At-risk order count |
| T6 | Return-fraud detector | `RandomForestClassifier` — `item_swap` / `empty_return` (recycled anomaly suite) | Fraud-type label |
| T7 | Ranker | Deterministic weighted score-sort; config weights | Ordered SKU/Category/Campaign list |
| T8 | Router classifier | `RandomForestClassifier` — `NEW_SHOP` \| `MID_LARGE_SHOP` rule-set routing (recycled seller-stage) | Profile + rule set |

**Deferred (Phase 3):** sentiment / CSAT — no buyer review/chat source in MVP
(`data-sources.md` #17); CSAT renders as deterministic proxy or "unavailable".

**Backtest protocol (Phase 2 MVP Milestone A):** train on a historical window, evaluate on a
held-out Q4 / Q1 window; report precision/recall (and ROAS error for the ads
regressor) against ground truth. Record target thresholds **here** before promoting
to Phase 2 MVP.

> **Promotion targets (Phase 2 MVP gate — Product sign-off #142):**
> - Router classifier (seller stage): precision ≥ **0.50**, macro recall ≥ **0.50**
> - Return-fraud detector (anomaly): per-class precision ≥ **0.50** and recall ≥ **0.50** on labeled `item_swap` + `empty_return` set (ADR-008)
> - Ads regressor (ad performance): ROAS MAPE ≤ **50.0%** on held-out backtest window
>
> Thresholds are encoded in `src/modules/ml/artifacts/thresholds.py` and evaluated by
> `evaluate_promotion_status`. Sub-threshold runs serialize as `experimental` only.

**Phase 2 MVP Milestone A backtest reference run** (synthetic dataset, seed 142 — trainers #138–#140):

| Technique | Metric | Reference value | Meets gate |
|-----------|--------|-----------------|------------|
| Router (seller stage) | precision / recall_macro | 1.00 / 1.00 | ✓ |
| Return-fraud (anomaly) | item_swap precision / recall | 1.00 / 1.00 | ✓ |
| Return-fraud (anomaly) | empty_return precision / recall | 0.00 / 0.00 | ✗ (sparse labels) |
| Ads regressor | ROAS MAPE | 0.54% | ✓ |

**Outputs:** serialized models (pickle / joblib), feature specs, inference
signatures. Each artifact carries metadata: train date, row count, feature schema
hash, metrics snapshot.

**Inference signatures:** input schema, output schema, and model version pointer
for each recycled technique are documented in
[`data-models/feature-store-schema.md`](data-models/feature-store-schema.md)
§ Inference signatures. Phase 2 MVP batch inference (08:00 UTC) loads artifacts from
`models/{suite}/{version}/` and validates `feature_schema_hash` at load time.

```
models/
  seller_stage/{version}/model.joblib + metadata.json   # T8 router classifier
  anomaly/{version}/model.joblib + metadata.json        # T6 return-fraud detector
  ad_performance/{version}/model.joblib + metadata.json # T2 ads regressor
```

#### Return schema contract (P1 → P2.0 → P2.5)

Cross-phase field alignment index for **Return**, **Order**, and **OrderItem**.
Full entity JSON schemas, lineage, and refresh rules live in
[`data-models/canonical-entities.md`](data-models/canonical-entities.md).
Ingestion field maps remain in [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md)
§ Orders. Affiliate data is **out of scope** for the anomaly model
(ADR-008).

**Anomaly classes (ML labels):**

| `return_type` | Definition | Example signals |
|---------------|------------|-----------------|
| `item_swap` | Returned SKU/item does not match shipped line item | Wrong product in parcel; size/color mismatch vs order line |
| `empty_return` | Parcel received with no product or filler only | Empty box; packaging-only return |
| `other` | Legitimate returns (size, SNAD, change-of-mind) | Not scored as anomaly; used as negative class |

**Core entities:**

| Field | P1 mock (`schemas.ts`) | P2.0 parquet | P2.5 Postgres | TikTok API (target) | Notes |
|-------|------------------------|--------------|-------------|---------------------|-------|
| `order_id` | `MockOrder.id` | `order_id` | `Order.tiktok_order_id` | `order_id` | Shop-scoped unique |
| `return_id` | `MockReturn.id` | `return_id` | `Return.tiktok_return_id` *(P2 table TBD)* | return/refund id | Confirm path in API Reference |
| `shop_id` | `SellerProfile.shop_id` | `shop_id` | `Order.shop_id` | via `shop_cipher` | FK to `Shop` |
| `buyer_id` | masked `buyer_***` | `buyer_id` | `Order.buyer_id` | `buyer_id` | Masked only — no PII (#17) |
| `product_id` | — *(add in P2.0)* | `product_id` | line-item FK | `line_items[].product_id` | Required for swap detection |
| `sku_id` | — *(add in P2.0)* | `sku_id` | line-item FK | `line_items[].sku_id` | Ordered vs returned SKU compare |
| `return_reason` | `MockReturn.reason` | `return_reason` | `Return.reason` | `return_reason` / reason code | Free text or enum — confirm in P2-B1 |
| `return_type` | — *(add in P2.0)* | `return_type` | `Return.return_type` | derived from reason + inspection | Enum: `item_swap` \| `empty_return` \| `other` |
| `return_condition` | — *(add in P2.0)* | `return_condition` | `Return.return_condition` | inspection outcome if exposed | `empty_parcel` \| `wrong_item` \| `correct_item` \| `unknown` |
| `refund_amount` | `MockReturn.refund_vnd` | `refund_amount` | `Return.refund_amount` | refund amount field | VND; `Numeric(18,2)` |
| `status` | `MockReturn.status` | `status` | `Return.status` | return status | `pending_review` \| `approved` \| `rejected` |
| `created_at` | ISO string | `created_at` | `created_at` | `create_time` | Unix → datetime in ETL |

**Buyer aggregate features (anomaly model inputs):**

Defined in [`data-models/feature-store-schema.md`](data-models/feature-store-schema.md)
§ Group A — `buyer_return_count_30d`, `buyer_item_swap_count_30d`,
`buyer_empty_return_count_30d`, `buyer_repeat_anomaly_flag`, `return_rate_30d`,
`seller_fault_cancel_rate_30d`.

**P2.0 parquet layout (minimum):**

See [`data-models/mock-data-generator.md`](data-models/mock-data-generator.md) § Dataset 2
(Revenue Leakage Detection) and § Saving to parquet. Minimum files:

```
backtest/revenue_leakage/
  orders.parquet
  order_items.parquet   # required for item_swap sku_id comparison
  returns.parquet
  labels.parquet        # return_id, ground_truth_anomaly, return_type
```

Synthetic generator must produce labeled `item_swap` and `empty_return` rows when
historical TikTok data is unavailable. P2.0-5 documents feature specs in
[`feature-store-schema.md`](data-models/feature-store-schema.md) (no drift at P2.5).

**Platform-policy signals (not ML):** VP/AHR milestones, balance withholding,
commission dispute holds, and SNAD enforcement remain deterministic rules in
§ Platform policy signals — fed separately into loss-prevention tasks, not the
anomaly model.

### 4. Copy layer

Turns structured ML/rules output into seller-facing copy for the UI and alerts.
The LLM **never** decides what to recommend — it only summarizes and localizes
copy from deterministic signals.

```
ML / rules → structured signals
        → lightweight LLM (summarize + localize copy)
        → UI / alerts
        → rules fallback if LLM fails or budget exceeded
```

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Hardcoded mock copy in fixtures; no LLM. |
| **Phase 2 MVP Milestone A** | Rules-only templates generated from backtest signals; validates copy quality offline. |
| pre-MVP | Rules-only **reasoning** templates — per-recommendation Why / Expected Impact / Next Steps from deterministic signals (§ Operations-system pipeline). No LLM. |
| **Phase 2 MVP** | **Claude Haiku 3.5** ([ADR-012](decisions/012-architecture-reconciliation-mvp-vs-target.md)) renders copy + reasoning from live signals — summarize + localize (Vietnamese); **rules fallback** on timeout, error, or daily token budget exceeded. |

**Haiku copy layer (Phase 2 MVP):**

- Hosted API call (no self-hosted inference node required at MVP volume).
- Input: structured signal JSON from ML/rules (signal type, severity, metrics, recommended action).
- Output: localized task title, body, and CTA for UI / alerts.
- The model **never** decides recommendations — only rewrites deterministic signals.
- Enforce a per-shop (or global) daily token budget; log `copy_source: haiku | rules_fallback`.

**Rules fallback:** Pre-authored templates keyed by signal type (e.g. `anomaly:item_swap`,
`anomaly:empty_return`,
`ad:scale_candidate`). Same structured input Haiku receives; no silent degradation to
generic text. Missing Haiku must not block API writes or task execution.

### 5. Platform policy signals (Phase 2 MVP)

Deterministic rules derived from TikTok Shop seller/creator policy — not ML.
Sourced from [`tiktok_platform/seller/implementation-hooks.md`](tiktok_platform/seller/implementation-hooks.md)
and [`tiktok_platform/creator/implementation-hooks.md`](tiktok_platform/creator/implementation-hooks.md).

**Data availability contract (Phase 2 MVP):** Policy thresholds (VP/AHR/withholding/appeal windows) are
authoritative in platform docs, but **API exposure is not assumed**. Phase 2 MVP must track
`health_data_source: api | proxy | unavailable` (per [`architecture/data-sources.md`](architecture/data-sources.md))
and degrade explicitly — no Seller Center scraping.

| Signal | Threshold | Consumer | Action |
|--------|-----------|----------|--------|
| Seller VP warning | VP ≥ 7 | Loss prevention / Alerts | Warn before 12-VP affiliate block |
| Seller VP milestone | VP ≥ 12 | Loss prevention | Block affiliate enrollment recommendations; alert 7-day suspension |
| Seller VP severe | VP ≥ 24 | Loss prevention | Alert listing/LIVE suspension; prioritize stabilization tasks |
| Seller AHR Orange | AHR ≤ 199 | Loss prevention / Alerts | Post-July 2026; dual-read with VP during transition |
| Seller AHR Red | AHR ≤ 150 | Loss prevention | Escalate to critical-risk band |
| Balance withholding | Enforcement active | Loss prevention | Treat balance as `frozen` (not `pending`); alert seller |
| Commission dispute hold | Order in dispute | Loss prevention | Policy alert — not anomaly ML input |
| Appeal window | ≤ 7 days to deadline | Alerts | Surface appeal urgency in UI |
| Creator KYC incomplete (VN) | No CCCD + tax code | Loss prevention (affiliate context) | Flag linked creators blocking commission payout |

**Affiliate enrollment gate (seller):** Suppress affiliate recruitment for the NEW_SHOP
rule set when VP ≥ 12 (or AHR unhealthy post-July 2026). Commission priority: Targeted
Collaboration overrides Open Collaboration rate ([`cross-cutting.md`](tiktok_platform/cross-cutting.md)).

**VP → AHR transition:** If VP/AHR fields are exposed via official APIs, dual-read both systems
May–July 2026; feature-flag switch to AHR-only after July 2026
([ADR-006](decisions/006-dual-read-vp-ahr-transition.md)). If not exposed, remain in
`proxy`/`unavailable` mode and do **not** fabricate numeric VP/AHR.
Milestone alerts must fire on threshold hits — not silent degradation
([ADR-005](decisions/005-alert-vp-ahr-milestones.md)).

**Out of Phase 2 MVP:** Creator CHR scoring, creator matching filters, LIVE commerce
attribution — Phase 3+ per EXECUTION.md. VN-specific thresholds (follower count,
tax code, CHR zones) are region-variant config ([ADR-007](decisions/007-vn-regional-platform-config.md)).

### 6. Executor

Turns an approved recommendation into action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | UI approval flow is a **no-op** — seller approves/dismisses a task; nothing executes. Captures intent + engagement only. |
| **Phase 2 MVP Milestone A** | No changes — UX still mocked. |
| **listing workflow (pre-MVP)** | **`list_products` only** — approve opens `ListingWorkflowPanel`; execute exports CSV/JSON (client-side). Other task types remain no-op. |
| **leakage workflow (pre-MVP)** | **All four leakage task types** — approve opens `LeakageWorkflowPanel`; mock execute per `MockTask.type`. **Global skip-with-reason** on dismiss (all workflows). Session state in `task-executor/session-store`. |
| pre-MVP | **Unified approval gate + routing** — approve-all / selective / reject-with-reason; route **NPL** → listing panel, **Refund Spike** → leakage panel (by task type), or **no-op** for Violations, Stockout, Budget Optimization, Product Scaling. Captures mock `workflow_results`. |
| **Phase 2 MVP** | **Real task triggers** — P2-B5 generic executor; P2-B7/P2-B8 listing publish queue; P2-B9/P2-B10 leakage executors; P2-B13/P2-B14/P2-B15 new-shop, growth, and stockout executors. |

### 7. Executable workflow UIs (listing workflow (pre-MVP) / 1.7)

Client-side modal workflows launched from `useTaskExecutor` after task approve.
No new App Router routes. State machines persist step + payload in `sessionStorage`.

| Shipped workflow UI | Entry task | Panel | Steps (summary) | P2 executor |
|---------------------|------------|-------|-----------------|-------------|
| Create New Product Listing (P1.6) | `list_products` | `ListingWorkflowPanel` | path → form/discovery → draft → export | P2-B7 queue → P2-B8 Products API |
| Loss prevention (P1.7) | `return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy` | `LeakageWorkflowPanel` | detail → evidence → root cause → action → execute → success | P2-B9 queue → P2-B10 APIs |

**Leakage step graph** ([ADR-013](decisions/013-operations-pipeline-spine.md)):

```
TaskCard (alert)
  → approve → detail ↔ evidence ↔ root_cause ↔ recommended_action
  → execution (stepper) → success → completed (removed from active queue)
```

**Leakage task status** (per task, session-persisted): `new` → `in_review` →
`evidence_reviewed` → `ready_to_execute` → `executing` → `completed` | `skipped`.

**Signal classes in P1.7** (mock rules aggregates — not ML inference):

| `MockTask.type` | Signal class | Mock execution |
|-----------------|--------------|----------------|
| `return_spike` | Return-rate aggregate | Listing update draft → apply |
| `buyer_cancellation_cluster` | Buyer cancellation aggregate | Investigation report → support case draft |
| `refund_cluster` | Refund concentration aggregate | Refund report → watchlist |
| `return_window_policy` | Shop policy / config | Settings review → apply config |

Affiliate cancellation and commission-dispute patterns are **policy-rule alerts** in
Phase 2 MVP ([ADR-008](decisions/008-buyer-behavior-anomaly-scope.md)) — not leakage workflow
types. `affiliate_fraud` is removed from the leakage persona in P1.7-1.

---

## End-to-end flow (Phase 2 MVP target)

```
[TikTok API: Orders · Products · Affiliate · Ads · (optional) Shop Account health]
        │  daily poll (ingestion: tiktok_api/endpoints.md)
        ▼
   Raw API responses
        │  ETL → canonical entities (data-models/canonical-entities.md)
        ▼
   Postgres (canonical entity tables + policy state)
        │  06:00–07:00 UTC feature build (data-models/feature-store-schema.md)
        ▼
   feature tables (+ platform policy rule inputs)
        │  08:00 UTC daily batch inference
        ▼
   model outputs (stage · anomalies · ad diagnosis)
        │  + deterministic policy signals (VP/AHR · disputes · withholding)
        ▼
   agent decision tree → workflow + ranked tasks
        │
        ▼
   structured signals → copy layer (Haiku summarize + localize · rules fallback)
        │
        ▼
   UI / alerts (real inferences replace mock)
        │  seller approves
        ▼
   executor → real task trigger
        │  outcome
        ▼
   revenue-impact metrics (recovered refunds · avoided cancellations · ROAS lift)
```

pre-MVP runs the same shape with **mock JSON** standing in for everything left of
the copy layer, **hardcoded copy** standing in for the LLM, and the executor as a
no-op.

---

## Metrics by phase

| Phase | What we measure | Why |
|-------|-----------------|-----|
| **Phase 1** | UX engagement — task clicks, approval-flow completions | Validate workflows resonate before building ML |
| **Phase 2 MVP Milestone A** | Model performance — precision/recall on backtest | Confirm recycled techniques are accurate enough to ship |
| pre-MVP | Pipeline completion rate, classification distribution, approve/reject/selective rates + reject reasons | Validate the operations-system UX end-to-end on mock data |
| **Phase 2 MVP** | Revenue impact — recovered refunds, avoided cancellations, improved ROAS | Prove the product makes sellers money |

---

## Dependencies (Phase 2 MVP Milestone A+)

| Library | Use | Version policy |
|---------|-----|----------------|
| scikit-learn | Router classifier, return-fraud detector, preprocessing | pin in requirements |
| xgboost | Ads regressor (if used) | pin in requirements |
| statsmodels | T1 Forecaster — ETS / Holt-Winters | pin in requirements |
| pandas / pyarrow | Backtest parquet handling | pin in requirements |
| anthropic | Phase 2 MVP copy layer — Claude Haiku 3.5 | pin in requirements |

Confirm versions via Context7 / PyPI at implementation time. Haiku API key in server-side
env only (`ANTHROPIC_API_KEY`); rules fallback when unavailable or budget exceeded.

---

## Out of scope (see EXECUTION.md)

Celery / multi-node workers, Kafka streams, creator↔shop matching, vendor scrapers,
Seller Center scraping, buyer PII, realtime unofficial streams, `src/` folder
reshaping. The Phase 2 MVP target architecture (real APIs + inference pipeline) is
detailed in [`phases/phase-2-mvp.md`](phases/phase-2-mvp.md), **published at the end of Phase 2 MVP Milestone A**.
