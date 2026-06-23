# System Design

> Single technical-design doc for Juli-AI. Sections map directly to the phase gates
> in [`../EXECUTION.md`](../EXECUTION.md). For deployed reality see
> [`architecture/map.md`](architecture/map.md); for data status see
> [`architecture/data-sources.md`](architecture/data-sources.md).
>
> **Authority:** `EXECUTION.md` > this file > `map.md`. If this file disagrees with
> EXECUTION.md, EXECUTION.md wins and this file is corrected in the same PR.

## North star

Juli AI is a **Decision Copilot** for TikTok Shop sellers — an AI Operations
System that analyzes shop data, surfaces opportunities and risks, recommends
validated high-impact workflows with impact estimates and reasoning, collects
user decisions and inputs, and executes **only after explicit approval**
([ADR-028](decisions/028-decision-copilot-app-structure.md)). The backend spine
remains: profile classification → health evaluation → ranked recommendation →
reasoning → user approval → Copilot execution → outcome tracking
([ADR-026](decisions/026-operations-system-orchestration.md)).

**Copilot surfaces** (UI pillars — not an open-ended workflow catalog):

| Profile | Surface | Workflows |
|---------|---------|-----------|
| **NEW_SHOP** | New Seller Copilot | NPL; Minimize Violations |
| **MID_LARGE_SHOP** | Growth Copilot | Budget Optimization; Product Scaling |
| **MID_LARGE_SHOP** | Revenue Leakage (loss prevention) | Refund Spike Detection; Stockout Prevention |

Phase progression: UI-first (Phase 1), ML (Phase 1.5), executable mock workflows
(Phase 1.6–1.7), mock operations orchestration spine (Phase 1.8), live data (Phase 2).

---

## Phase capability matrix

Each subsystem evolves across phases. This table is the index; details follow below.

| Subsystem | Phase 1 (UI) | Phase 1.5 (ML) | Phase 1.6 (listing) | Phase 1.7 (leakage) | Phase 1.8 (orchestration) | Phase 2 (APIs) |
|-----------|--------------|----------------|---------------------|---------------------|---------------------------|----------------|
| **Agent decision tree** | Rules-based seller-stage detection | ML classifier | (unchanged) | (unchanged) | 2-profile classification + ranking (rules, mock) | Live daily scoring |
| **Data pipeline** | Mock JSON | Backtest (parquet) | Listing workflow fixtures | Leakage workflow fixtures | `unified_operational_data_model` fixtures | TikTok API polling |
| **Health check** | implicit (per-workflow) | — | — | — | `health_check_results` indicators (mock) | Live health scoring |
| **ML models** | none | Trained, serialized | none | none (optional `return_type` preview on mocks) | none | Production inference |
| **Copy / reasoning layer** | Hardcoded mock copy | Rules-only templates | Rules-only draft copy | Rules-only root-cause / action copy | Rules-only reasoning (Why / Impact / Next steps) | Ollama + rules fallback |
| **Executor** | Approve/dismiss (no-op) | (no changes) | Mock export (`list_products`) | Mock execute (4 leakage types) | Unified approval gate + routing (NPL + Refund Spike executable; 4 workflows no-op) | Real task triggers |
| **Outcome tracking** | UX engagement only | model metrics | — | — | `workflow_outcome_metrics` (mock) | Real outcome metrics |
| **Workflow UI** | Task cards only | (no changes) | `ListingWorkflowPanel` modal | `LeakageWorkflowPanel` modal | 3-tab Decision Copilot IA (Home / Decisions / Chat — ADR-028) + operations pipeline + design-system tokens (ADR-027) | Live inference + same modals |

---

## Operations-system pipeline (Phase 1.8)

Phase 1.8 introduces a single orchestration spine over the three workflows. Each
stage has an explicit output envelope; Phase 2 swaps mock loaders for live data /
inference / Ollama without changing the stage shapes
([ADR-026](decisions/026-operations-system-orchestration.md)).

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

### Shop profiles & validated workflow catalog (no others)

`shop_profile ∈ {NEW_SHOP, MID_LARGE_SHOP}`. Exactly **six** validated workflows;
no expansion without explicit evaluation ([ADR-026](decisions/026-operations-system-orchestration.md)).

| Profile | Validated workflow | Copilot surface | P1.8 status | Real execution |
|---------|--------------------|-----------------|-------------|----------------|
| NEW_SHOP | Add New Product Listings (NPL) | New Seller | Executable — P1.6 `ListingWorkflowPanel` | P2-7 / P2-8 |
| NEW_SHOP | Minimize Violations | New Seller | Card + reasoning; approve = no-op | P2-13 |
| MID_LARGE_SHOP | Budget Optimization | Growth | Card + reasoning; approve = no-op | P2-14 |
| MID_LARGE_SHOP | Product Scaling | Growth | Card + reasoning; approve = no-op | P2-14 |
| MID_LARGE_SHOP | Refund Spike Detection | Revenue Leakage (loss) | Executable — P1.7 `LeakageWorkflowPanel` (4 sub-journeys) | P2-9 / P2-10 |
| MID_LARGE_SHOP | Stockout Prevention | Revenue Leakage (loss) | Card + reasoning; approve = no-op | P2-12 / P2-15 |

**Refund Spike sub-journeys (P1.7 task types under one validated workflow):**
`return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy`.
Ranking may surface any sub-journey; approval routes to the matching leakage panel flow.

**Growth Copilot (P1-4):** reference mock UI from Phase 1 — P1.8 does **not** route
approved Budget Optimization or Product Scaling into that panel; cards + no-op only.

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
> (§ Platform policy signals; [ADR-009](decisions/009-dual-read-vp-ahr-transition.md)).
> Both are mock in P1.8; real exposure is gated by P2-1 verification.

### Recommendation & ranking (mock in P1.8)

`workflow_recommendations` per [ADR-026](decisions/026-operations-system-orchestration.md):
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
**Next Steps** — rules-only templates in P1.8, Ollama + rules fallback in P2. The
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

### Decision Copilot app structure (P1.8-9)

The seller web app exposes exactly **three main tabs** ([ADR-028](decisions/028-decision-copilot-app-structure.md)).
Each screen answers one user question; workflow complexity stays hidden by default.

| Tab | Route | Question | Seller actions |
|-----|-------|----------|----------------|
| **Home** | `/` | What is happening? | Read-only |
| **Decisions** | `/decisions` | What should I do? | Review, approve, configure |
| **Juli AI Chat** | `/ai-chat` | Help me understand and complete this. | Contextual Q&A |

**Primary UI object: Decision** — a seller-facing recommendation wrapping one
validated `workflow_id` (ADR-026 catalog), plus title, estimated impact, confidence,
reasoning, required user inputs, and lifecycle status. Workflows are execution
templates behind decisions; sellers never interact with a raw workflow catalog as
the primary experience.

#### Home (`/`)

Three sections, **no approvals or execution** on Home:

1. **Shop Status (hero)** — Shop Health Score, Account Health Rating (AHR/VP when
   available), platform alerts/messages/violations. Answers shop visibility on the
   platform right now. Reuses `ShopHealthHero` + `health_check_results`.
2. **Today's Report** — single container with animated domain switching:
   Revenue Growth · Revenue Protection · Product Listings · Advertising · Refunds.
   Each domain card: current status, trend vs prior period, metric deltas. Domain
   summaries aggregate signals from `unified_operational_data_model` (not a sixth
   workflow).
3. **Recommended Decisions Preview** — top **3** decisions by impact from
   `workflow_recommendations`; title + estimated impact + revenue gain or
   loss-prevention value. CTA **View All Decisions** → `/decisions`.

#### Decisions (`/decisions`)

Three sub-tabs:

| Sub-tab | Content | Statuses |
|---------|---------|----------|
| **Recommended** | Full ranked decision cards: title, impact, confidence, reasoning, required inputs, Review CTA | `recommended` |
| **In Progress** | Approved decisions awaiting input or execution | `needs_input`, `executing`, `completed` |
| **Workflow Templates** | Advanced settings — thresholds, automation rules, per-workflow configuration (Budget Optimization, Stockout Prevention, Product Scaling, Refund Spike, etc.) | N/A (settings) |

Hosts the unified **approval gate** (P1.8-6), full **reasoning expansion**
(P1.8-5), **outcome tracking** entry (P1.8-7), and routes approval to existing
P1.6/P1.7 modal executors or no-op per ADR-026.

#### Decision detail flow

Opened from **Review** on a decision card (`/decisions/[decisionId]` or equivalent
drawer/stepper):

1. **Why** — explain why the recommendation exists (reasoning + health signals)
2. **Analytics** — supporting charts/metrics for the decision domain
3. **User inputs** — product selection, budget limits, campaign goals, risk tolerance
4. **Execution preview** — expected revenue impact, loss prevention, confidence, risks
5. **Approve and execute** — approval gate → route to listing/leakage panel or no-op

#### Juli AI Chat (`/ai-chat`)

Contextual assistant connected to active/recent decisions — explain recommendations,
compare products, clarify metrics, assist decision completion, configure workflows,
answer platform questions. Not a generic chatbot; prompts and context derive from
the operations pipeline and open decision state.

#### Seller canvas (white)

Seller workspace uses a **white canvas** (`#FFFFFF`) for `--background`, header,
and muted surfaces — not the pink-tint `#FEF5F6` from ADR-027. Brand pink
`#F86BA5` is accent-only (health progress, primary CTAs). Affiliate workspace
stays dark per ADR-027.

#### Design principles (IA)

- Mobile-first · minimal cognitive load · recommendation-first
- Workflow complexity hidden by default (Templates sub-tab is advanced)
- Human approval required before execution (never from Home)
- Clear business impact on every recommendation; every recommendation explains why
- Every screen answers a specific user question (see table above)

> **Migration note:** P1.8 shipped `OperationsPipelineShell` on Home with approval
> on the landing page. P1.8-9 splits that shell: Home = summary; Decisions = action.

### Design system & token foundation (P1.8-8)

The orchestration surfaces (Shop Health hero, ranked "Clarity Card" recommendations,
reasoning panel, approval gate, outcome views) share one token foundation
([ADR-027](decisions/027-design-system-token-foundation.md)). Tokens live in
`web/src/app/globals.css` + `tailwind.config.ts`; surfaces compose from `var(--*)` and
`@layer components` utilities — never one-off theme hex.

| Dimension | Standard |
|-----------|----------|
| **Theme** | **Seller = light** (`#FEF5F6`/white canvas, charcoal text); **Affiliate = dark**. Swaps the prior mapping (`html.dark` semantics inverted). |
| **Typography** | One typeface (Inter). Single **≤6-size** scale; hierarchy from size + weight only — no serif/display or monospace fonts. |
| **Color (60/30/10)** | Neutral structure (60%) → Growth `#16A34A` / Loss `#E5484D` (30%) → Primary pink `#F86BA5` (5–10%). Warning `#F59E0B`, New/Info `#2563EB`. Each semantic ships a low-opacity **background tint**. Color is never the only signal (pair with text/icon). |
| **Interaction states** | Default (base, full opacity, standard border) · Hover (subtle color shift **or** shadow lift) · Active (darker fill + scale `0.98`) · Focus (3px visible ring + offset) · Disabled (muted fill, reduced contrast, `not-allowed`) · Loading (inline spinner + disabled). |
| **Elevation** | 3-step shadow scale — `sm` cards · `md` modals/popovers · `lg` toasts. |
| **Motion** | Card entry (fade + scale, staggered), metric counter on change, approval → success toast, loading shimmer/skeleton, tab/route fade. All gated by `prefers-reduced-motion`. |

Applied as the Phase 1.8 polish slice; `web/MODULE.md` dual-theme invariant and
`screenshots/` are re-baselined when the swap ships (code is authority).

### Architecture constraints (non-negotiable)

1. No new workflows without explicit necessity + fit evaluation.
2. No new shop profiles without a business case.
3. No additional ML models unless required by an existing workflow and vetted.
4. **Data traceability:** every collected datum maps to ≥1 workflow.
5. **Metric traceability:** every health indicator informs ≥1 workflow decision.
6. **Recommendation traceability:** every recommendation maps to ≥1 validated workflow.
7. Prefer explicit rules over implicit inference.
8. Explainability: every recommendation includes Why + Expected Impact.

---

## Subsystems

### 1. Agent decision tree

Routes a seller to the right workflow and the right next action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Rules-based seller-stage detection from mock seller profile (e.g. order count, shop age thresholds → New Seller vs Growth). Deterministic, hand-tuned. |
| **Phase 1.5** | Replace rules with the trained **seller stage classifier** (see Models); run against backtest data offline to compare against the rules baseline. |
| **Phase 1.8** | Extend to `shop_profile ∈ {NEW_SHOP, MID_LARGE_SHOP}` and feed the recommendation & ranking stage (§ Operations-system pipeline). Rules-based, mock input. |
| **Phase 2** | Live daily scoring — classifier runs on real polled seller data each morning; decision tree consumes model output to select profile, workflows + ranked tasks. |

### 2. Data pipeline

| Phase | Source | Mechanism |
|-------|--------|-----------|
| **Phase 1** | Mock JSON | Fixtures generated from [`data-models/canonical-entities.md`](data-models/canonical-entities.md) via [`mock-data-generator.md`](data-models/mock-data-generator.md). No network. |
| **Phase 1.5** | Backtest data (parquet) | Canonical entity parquet + labeled returns; synthetic when historical data unavailable. Feature build uses [`feature-store-schema.md`](data-models/feature-store-schema.md). |
| **Phase 2** | TikTok API polling | Raw responses ingested per [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md); ETL normalizes to canonical entities → Postgres; daily feature build → inference. |

**Schema authority:** [`docs/data-models/`](data-models/README.md) defines platform-agnostic
entities and ML features. [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md) is the
**ingestion layer** only — vendor field maps, not ML schema source of truth
([ADR-012](decisions/012-entity-centric-data-model.md)).

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
runner-agnostic jobs** so the Phase 2 scheduler is a runner swap, not a rewrite.
Phase 2 uses a simple daily scheduler (cron / APScheduler). Celery / Kafka are
**out of scope** (Phase 3+, see EXECUTION.md → Explicitly out).

### 3. ML models

Three model suites. **Not built in Phase 1.** Trained + serialized in Phase 1.5;
served in Phase 2.

| Suite | Purpose | Powers workflow | Validation (Phase 1.5) |
|-------|---------|-----------------|------------------------|
| **Seller stage classifier** | Classify seller lifecycle stage | New Seller Copilot, decision tree routing | Precision/recall vs labeled historical stages |
| **Anomaly detector** | Detect buyer-behavior return anomalies: **item swap**, **empty return** | Revenue Leakage Detection | Precision/recall vs labeled `item_swap` / `empty_return` ground truth on backtest returns data ([ADR-011](decisions/011-buyer-behavior-anomaly-scope.md)) |
| **Ad performance analyzer** | Diagnose spend efficiency, flag scale/cut | Growth Copilot | Backtest ROAS predictions vs realized |

**Backtest protocol (Phase 1.5):** train on a historical window, evaluate on a
held-out Q4 / Q1 window; report precision/recall (and ROAS error for the ad model)
against ground truth. Record target thresholds **here** before promoting to Phase 2.

> **Promotion targets (Phase 2 gate — Product sign-off #142):**
> - Seller stage classifier: precision ≥ **0.50**, macro recall ≥ **0.50**
> - Anomaly detector: per-class precision ≥ **0.50** and recall ≥ **0.50** on labeled `item_swap` + `empty_return` set ([ADR-011](decisions/011-buyer-behavior-anomaly-scope.md))
> - Ad performance analyzer: ROAS MAPE ≤ **50.0%** on held-out backtest window
>
> Thresholds are encoded in `src/modules/ml/artifacts/thresholds.py` and evaluated by
> `evaluate_promotion_status`. Sub-threshold runs serialize as `experimental` only.

**Phase 1.5 backtest reference run** (synthetic dataset, seed 142 — trainers #138–#140):

| Suite | Metric | Reference value | Meets gate |
|-------|--------|-----------------|------------|
| Seller stage | precision / recall_macro | 1.00 / 1.00 | ✓ |
| Anomaly | item_swap precision / recall | 1.00 / 1.00 | ✓ |
| Anomaly | empty_return precision / recall | 0.00 / 0.00 | ✗ (sparse labels) |
| Ad performance | ROAS MAPE | 0.54% | ✓ |

**Outputs:** serialized models (pickle / joblib), feature specs, inference
signatures. Each artifact carries metadata: train date, row count, feature schema
hash, metrics snapshot.

**Inference signatures:** input schema, output schema, and model version pointer
for each suite are documented in
[`data-models/feature-store-schema.md`](data-models/feature-store-schema.md)
§ Inference signatures. Phase 2 batch inference (08:00 UTC) loads artifacts from
`models/{suite}/{version}/` and validates `feature_schema_hash` at load time.

```
models/
  seller_stage/{version}/model.joblib + metadata.json
  anomaly/{version}/model.joblib + metadata.json
  ad_performance/{version}/model.joblib + metadata.json
```

#### Return schema contract (P1 → P1.5 → P2)

Cross-phase field alignment index for **Return**, **Order**, and **OrderItem**.
Full entity JSON schemas, lineage, and refresh rules live in
[`data-models/canonical-entities.md`](data-models/canonical-entities.md).
Ingestion field maps remain in [`tiktok_api/endpoints.md`](tiktok_api/endpoints.md)
§ Orders. Affiliate data is **out of scope** for the anomaly model
([ADR-011](decisions/011-buyer-behavior-anomaly-scope.md)).

**Anomaly classes (ML labels):**

| `return_type` | Definition | Example signals |
|---------------|------------|-----------------|
| `item_swap` | Returned SKU/item does not match shipped line item | Wrong product in parcel; size/color mismatch vs order line |
| `empty_return` | Parcel received with no product or filler only | Empty box; packaging-only return |
| `other` | Legitimate returns (size, SNAD, change-of-mind) | Not scored as anomaly; used as negative class |

**Core entities:**

| Field | P1 mock (`schemas.ts`) | P1.5 parquet | P2 Postgres | TikTok API (target) | Notes |
|-------|------------------------|--------------|-------------|---------------------|-------|
| `order_id` | `MockOrder.id` | `order_id` | `Order.tiktok_order_id` | `order_id` | Shop-scoped unique |
| `return_id` | `MockReturn.id` | `return_id` | `Return.tiktok_return_id` *(P2 table TBD)* | return/refund id | Confirm path in API Reference |
| `shop_id` | `SellerProfile.shop_id` | `shop_id` | `Order.shop_id` | via `shop_cipher` | FK to `Shop` |
| `buyer_id` | masked `buyer_***` | `buyer_id` | `Order.buyer_id` | `buyer_id` | Masked only — no PII (#17) |
| `product_id` | — *(add in P1.5)* | `product_id` | line-item FK | `line_items[].product_id` | Required for swap detection |
| `sku_id` | — *(add in P1.5)* | `sku_id` | line-item FK | `line_items[].sku_id` | Ordered vs returned SKU compare |
| `return_reason` | `MockReturn.reason` | `return_reason` | `Return.reason` | `return_reason` / reason code | Free text or enum — confirm in P2-1 |
| `return_type` | — *(add in P1.5)* | `return_type` | `Return.return_type` | derived from reason + inspection | Enum: `item_swap` \| `empty_return` \| `other` |
| `return_condition` | — *(add in P1.5)* | `return_condition` | `Return.return_condition` | inspection outcome if exposed | `empty_parcel` \| `wrong_item` \| `correct_item` \| `unknown` |
| `refund_amount` | `MockReturn.refund_vnd` | `refund_amount` | `Return.refund_amount` | refund amount field | VND; `Numeric(18,2)` |
| `status` | `MockReturn.status` | `status` | `Return.status` | return status | `pending_review` \| `approved` \| `rejected` |
| `created_at` | ISO string | `created_at` | `created_at` | `create_time` | Unix → datetime in ETL |

**Buyer aggregate features (anomaly model inputs):**

Defined in [`data-models/feature-store-schema.md`](data-models/feature-store-schema.md)
§ Group A — `buyer_return_count_30d`, `buyer_item_swap_count_30d`,
`buyer_empty_return_count_30d`, `buyer_repeat_anomaly_flag`, `return_rate_30d`,
`seller_fault_cancel_rate_30d`.

**P1.5 parquet layout (minimum):**

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
historical TikTok data is unavailable. P1.5-5 documents feature specs in
[`feature-store-schema.md`](data-models/feature-store-schema.md) (no drift at P2).

**Platform-policy signals (not ML):** VP/AHR milestones, balance withholding,
commission dispute holds, and SNAD enforcement remain deterministic rules in
§ Platform policy signals — fed separately into Revenue Leakage tasks, not the
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
| **Phase 1.5** | Rules-only templates generated from backtest signals; validates copy quality offline. |
| **Phase 1.8** | Rules-only **reasoning** templates — per-recommendation Why / Expected Impact / Next Steps from deterministic signals (§ Operations-system pipeline). No LLM. |
| **Phase 2** | **Ollama** (local) renders copy + reasoning from live signals — summarize + localize (Vietnamese); **rules fallback** on timeout, error, or daily token budget exceeded. |

**Ollama implementation (Phase 2):**

- Runs on a **local inference node** (cost-optimized; no cloud GPU required for copy).
- Input: structured signal JSON from ML/rules (signal type, severity, metrics, recommended action).
- Output: localized task title, body, and CTA for UI / alerts.
- The model **never** decides recommendations — only rewrites deterministic signals.
- Enforce a per-shop (or global) daily token budget; log `copy_source: ollama | rules_fallback`.

**Rules fallback:** Pre-authored templates keyed by signal type (e.g. `anomaly:item_swap`,
`anomaly:empty_return`,
`ad:scale_candidate`). Same structured input Ollama receives; no silent degradation to
generic text. Missing Ollama must not block API writes or task execution.

### 5. Platform policy signals (Phase 2)

Deterministic rules derived from TikTok Shop seller/creator policy — not ML.
Sourced from [`tiktok_platform/seller/implementation-hooks.md`](tiktok_platform/seller/implementation-hooks.md)
and [`tiktok_platform/creator/implementation-hooks.md`](tiktok_platform/creator/implementation-hooks.md).

**Data availability contract (Phase 2):** Policy thresholds (VP/AHR/withholding/appeal windows) are
authoritative in platform docs, but **API exposure is not assumed**. Phase 2 must track
`health_data_source: api | proxy | unavailable` (per [`architecture/data-sources.md`](architecture/data-sources.md))
and degrade explicitly — no Seller Center scraping.

| Signal | Threshold | Workflow | Action |
|--------|-----------|----------|--------|
| Seller VP warning | VP ≥ 7 | Revenue Leakage / Alerts | Warn before 12-VP affiliate block |
| Seller VP milestone | VP ≥ 12 | Revenue Leakage | Block affiliate enrollment recommendations; alert 7-day suspension |
| Seller VP severe | VP ≥ 24 | Revenue Leakage | Alert listing/LIVE suspension; prioritize stabilization tasks |
| Seller AHR Orange | AHR ≤ 199 | Revenue Leakage / Alerts | Post-July 2026; dual-read with VP during transition |
| Seller AHR Red | AHR ≤ 150 | Revenue Leakage | Escalate to critical-risk band |
| Balance withholding | Enforcement active | Revenue Leakage | Treat balance as `frozen` (not `pending`); alert seller |
| Commission dispute hold | Order in dispute | Revenue Leakage | Policy alert — not anomaly ML input |
| Appeal window | ≤ 7 days to deadline | Alerts | Surface appeal urgency in UI |
| Creator KYC incomplete (VN) | No CCCD + tax code | Revenue Leakage (affiliate context) | Flag linked creators blocking commission payout |

**Affiliate enrollment gate (seller):** Suppress affiliate recruitment in New Seller Copilot
when VP ≥ 12 (or AHR unhealthy post-July 2026). Commission priority: Targeted Collaboration
overrides Open Collaboration rate ([`cross-cutting.md`](tiktok_platform/cross-cutting.md)).

**VP → AHR transition:** If VP/AHR fields are exposed via official APIs, dual-read both systems
May–July 2026; feature-flag switch to AHR-only after July 2026
([ADR-009](decisions/009-dual-read-vp-ahr-transition.md)). If not exposed, remain in
`proxy`/`unavailable` mode and do **not** fabricate numeric VP/AHR.
Milestone alerts must fire on threshold hits — not silent degradation
([ADR-008](decisions/008-alert-vp-ahr-milestones.md)).

**Out of Phase 2:** Creator CHR scoring, creator matching filters, LIVE commerce
attribution — Phase 3+ per EXECUTION.md. VN-specific thresholds (follower count,
tax code, CHR zones) are region-variant config ([ADR-010](decisions/010-vn-regional-platform-config.md)).

### 6. Executor

Turns an approved recommendation into action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | UI approval flow is a **no-op** — seller approves/dismisses a task; nothing executes. Captures intent + engagement only. |
| **Phase 1.5** | No changes — UX still mocked. |
| **Phase 1.6** | **`list_products` only** — approve opens `ListingWorkflowPanel`; execute exports CSV/JSON (client-side). Other task types remain no-op. |
| **Phase 1.7** | **All four leakage task types** — approve opens `LeakageWorkflowPanel`; mock execute per `MockTask.type`. **Global skip-with-reason** on dismiss (all workflows). Session state in `task-executor/session-store`. |
| **Phase 1.8** | **Unified approval gate + routing** — approve-all / selective / reject-with-reason; route **NPL** → listing panel, **Refund Spike** → leakage panel (by task type), or **no-op** for Violations, Stockout, Budget Optimization, Product Scaling. Captures mock `workflow_results`. |
| **Phase 2** | **Real task triggers** — P2-5 generic executor; P2-7/P2-8 listing publish queue; P2-9/P2-10 leakage executors; P2-13/P2-14/P2-15 new-shop, growth, and stockout executors. |

### 7. Executable workflow UIs (Phase 1.6 / 1.7)

Client-side modal workflows launched from `useTaskExecutor` after task approve.
No new App Router routes. State machines persist step + payload in `sessionStorage`.

| Workflow | Entry task | Panel | Steps (summary) | P2 executor |
|----------|------------|-------|-----------------|-------------|
| New Seller listing | `list_products` | `ListingWorkflowPanel` | path → form/discovery → draft → export | P2-7 queue → P2-8 Products API |
| Revenue Leakage | `return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy` | `LeakageWorkflowPanel` | detail → evidence → root cause → action → execute → success | P2-9 queue → P2-10 APIs |

**Leakage step graph** ([ADR-025](decisions/025-revenue-leakage-workflow-scope.md)):

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
Phase 2 ([ADR-011](decisions/011-buyer-behavior-anomaly-scope.md)) — not P1.7 workflow
types. `affiliate_fraud` is removed from the leakage persona in P1.7-1.

---

## End-to-end flow (Phase 2 target)

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
   structured signals → copy layer (Ollama summarize + localize · rules fallback)
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

Phase 1 runs the same shape with **mock JSON** standing in for everything left of
the copy layer, **hardcoded copy** standing in for the LLM, and the executor as a
no-op.

---

## Metrics by phase

| Phase | What we measure | Why |
|-------|-----------------|-----|
| **Phase 1** | UX engagement — task clicks, approval-flow completions | Validate workflows resonate before building ML |
| **Phase 1.5** | Model performance — precision/recall on backtest | Confirm models are accurate enough to ship |
| **Phase 1.8** | Pipeline completion rate, classification distribution, approve/reject/selective rates + reject reasons | Validate the operations-system UX end-to-end on mock data |
| **Phase 2** | Revenue impact — recovered refunds, avoided cancellations, improved ROAS | Prove the product makes sellers money |

---

## Dependencies (Phase 1.5+)

| Library | Use | Version policy |
|---------|-----|----------------|
| scikit-learn | Classifier, anomaly detection, preprocessing | pin in requirements |
| xgboost | Ad performance regressor (if used) | pin in requirements |
| pandas / pyarrow | Backtest parquet handling | pin in requirements |
| ollama (Python client) | Phase 2 copy layer — local LLM inference | pin in requirements |

Confirm versions via Context7 / PyPI at implementation time. Ollama server runs
alongside the app stack on the local inference node (`OLLAMA_HOST`, model tag in env).

---

## Out of scope (see EXECUTION.md)

Celery / multi-node workers, Kafka streams, creator↔shop matching, vendor scrapers,
Seller Center scraping, buyer PII, realtime unofficial streams, `src/` folder
reshaping. The Phase 2 target architecture (real APIs + inference pipeline) is
detailed in [`architecture/target-v2.md`](architecture/target-v2.md), **published at the end of Phase 1.5**.
