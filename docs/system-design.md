# System Design

> Single technical-design doc for Juli-AI. Sections map directly to the phase gates
> in [`../EXECUTION.md`](../EXECUTION.md). For deployed reality see
> [`architecture/map.md`](architecture/map.md); for data status see
> [`architecture/data-sources.md`](architecture/data-sources.md).
>
> **Authority:** `EXECUTION.md` > this file > `map.md`. If this file disagrees with
> EXECUTION.md, EXECUTION.md wins and this file is corrected in the same PR.

## North star

Juli-AI helps TikTok Shop sellers **make and keep more money** via three agentic
workflows: **New Seller Copilot**, **Revenue Leakage Detection**, **Growth Copilot**.
The product is built UI-first (Phase 1), then ML (Phase 1.5), then live data (Phase 2).

---

## Phase capability matrix

Each subsystem evolves across phases. This table is the index; details follow below.

| Subsystem | Phase 1 (UI) | Phase 1.5 (ML) | Phase 2 (APIs) |
|-----------|--------------|----------------|----------------|
| **Agent decision tree** | Rules-based seller-stage detection | ML classifier | Live daily scoring |
| **Data pipeline** | Mock JSON | Backtest data (parquet) | TikTok API polling |
| **ML models** | none | Trained, serialized | Production inference |
| **Copy layer** | Hardcoded mock copy | Rules-only templates from signals | Ollama (local) + rules fallback |
| **Executor** | UI approval flow (no-op) | (no changes) | Real task triggers |

---

## Subsystems

### 1. Agent decision tree

Routes a seller to the right workflow and the right next action.

| Phase | Behavior |
|-------|----------|
| **Phase 1** | Rules-based seller-stage detection from mock seller profile (e.g. order count, shop age thresholds → New Seller vs Growth). Deterministic, hand-tuned. |
| **Phase 1.5** | Replace rules with the trained **seller stage classifier** (see Models); run against backtest data offline to compare against the rules baseline. |
| **Phase 2** | Live daily scoring — classifier runs on real polled seller data each morning; decision tree consumes model output to select workflow + tasks. |

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
| **Phase 2** | **Ollama** (local) renders copy from live signals — summarize + localize (Vietnamese); **rules fallback** on timeout, error, or daily token budget exceeded. |

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
| **Phase 2** | **Real task triggers** — an approved task fires the corresponding action against TikTok APIs / seller tooling. |

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
