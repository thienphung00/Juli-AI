# Canonical Entities

> **Authority:** `EXECUTION.md` > `system-design.md` > **this file** > `tiktok_api/endpoints.md` (ingestion only).
> This is the **source of truth** for entity schemas used in mock data generation,
> ML training, feature engineering, inference pipelines, and future multi-platform
> expansion (Shopee/Lazada — Phase 3+).
>
> `docs/integrations/tiktok_api/endpoints.md` is the **ingestion layer** — it maps raw TikTok API
> responses onto these canonical entities. Keep `endpoints.md` unchanged; extend
> it only when a new API field must be surfaced here.

---

## Architecture: API → Canonical → ML

```
TikTok API (endpoints.md — ingestion layer, unchanged)
        │
        ▼
Raw Events / Responses
        │  ETL (field rename, enum derivation, masking)
        ▼
Canonical Entities  ◄── THIS FILE
        │
        ├──► Mock Data (P1 fixtures)
        ├──► Backtest Parquet (historical ML prep — Phase 4)
        ├──► Postgres (P2 OLTP — ETL #299)
        └──► Feature Store (feature-store-schema.md)
                │
                ▼
        ML Training Pipelines
                │
                ▼
        Inference Services
```

**Old flow (vendor lock-in — being superseded):**

```
TikTok API → endpoints.md → direct to ML
```

**Why the change:** The old flow couples feature engineering to TikTok response
schemas. Canonical entities decouple ingestion from ML, enable synthetic data
generation without API access (historical backtest prep), and allow Shopee/Lazada adapters to feed
the same feature store without rewriting ML code.

---

## Field type conventions

| Type string | Meaning |
|---|---|
| `string` | UTF-8 text |
| `string (uuid)` | Canonical Juli-internal ID — not the vendor's raw ID |
| `string (masked)` | Vendor-supplied ID with PII stripped (buyer_id). Store as-is — do not decode |
| `string (enum)` | Closed set of values listed in the schema |
| `integer` | Whole number |
| `float` | IEEE 754 double |
| `Numeric(18,2)` | Fixed-precision monetary value (VND). Never use float for money |
| `timestamp` | ISO-8601 UTC datetime string in canonical form; Unix int in transit, converted in ETL |
| `boolean` | `true` / `false` |
| `UNKNOWN` | Field exists in policy docs but API exposure is unverified (P2-A1 gate) |

---

## Entity 1 — Shop

**Refresh:** Daily (account health proxies), on OAuth grant (shop metadata)  
**History:** Current state only; health snapshots kept 90 days for trend analysis  
**Data lineage:** `GET /authorization/202309/shops` (shop metadata); Account Health
endpoint — **UNKNOWN** until P2-A1 API verification (see `endpoints.md` §Account Health)

```json
{
  "id": "string (uuid)",
  "tiktok_shop_id": "string",
  "shop_cipher": "string",
  "name": "string",
  "region": "string",
  "seller_type": "string (enum: individual | business)",
  "created_at": "timestamp",

  // Account health — three-tier contract (data-sources.md §Operational rules)
  // health_data_source determines which downstream fields are populated
  "health_data_source": "string (enum: api | proxy | unavailable)",

  // Tier 1: populated only when health_data_source = 'api' and API exposes these fields
  "vp_score": "UNKNOWN — not confirmed in Partner API; do NOT fabricate in mock data",
  "ahr_score": "UNKNOWN — not confirmed in Partner API; do NOT fabricate in mock data",
  "withholding_active": "UNKNOWN — not confirmed in Partner API",
  "violation_events": "UNKNOWN — webhook catalog not extracted",

  // Tier 2: proxy signals — always computable from Orders + Products + Affiliate polling
  "sfcr_proxy": "float | null",        // seller-fault cancel rate (proxy, not API field)
  "ldr_proxy": "float | null",         // late dispatch rate (proxy)
  "return_rate_proxy": "float | null", // return/refund rate (proxy)
  "listing_audit_status": "string (enum: clean | under_audit | suspended | null)",

  // Settlement tier — four-tier framework (data-sources.md §Operational rules)
  // Default = standard for unknown/new shops
  "settlement_tier": "string (enum: express | accelerated | standard | extended)",
  "settlement_hold_days": "integer",   // 1 | 3 | 8 | 15 (up to 30 for extended/risk)

  // Metadata
  "store_rating": "float | null",
  "adjustment_period_complete": "boolean"
}
```

**Operational rules:**
- Never populate `vp_score` / `ahr_score` / `withholding_active` from proxy computation — these are API-only fields.
- If `health_data_source = 'unavailable'`, surface "health score unavailable" in UI; do not emit a numeric estimate.
- VP → AHR transition (May–July 2026): dual-read `vp_score` and `ahr_score` when `health_data_source = 'api'` ([ADR-006](../adr/006-dual-read-vp-ahr-transition.md)).
- Do not gate affiliate recommendations when `health_data_source != 'api'` — use `listing_audit_status` and known eligibility rules instead.
- `settlement_tier = standard` (8 days) is the default for any shop where the tier is unknown.

---

## Entity 2 — Product

**Refresh:** Hourly (audit status, inventory); Daily (sales aggregates)  
**History:** 30-day rolling window for sales_30d, returns_30d; point-in-time snapshot at daily batch  
**Data lineage:** `POST /product/202309/products/search` + `GET /product/202309/products/{product_id}` (see `endpoints.md` §Products; verified #282, #294)

**P2-A2 persistence (#299):** ETL writes `tiktok_product_id`, `title`, `category`, `category_id`,
`price`, `price_currency`, `inventory`, `audit_status`, `tiktok_created_at`. Legacy API columns
`name`, `status`, `revenue`, `units_sold` remain for backward compatibility. Sales aggregates
(`sales_7d`, `sales_30d`, etc.) are **deferred to P2-A3** feature build.

```json
{
  "id": "string (uuid)",
  "tiktok_product_id": "string",      // endpoints.md: products[].id
  "shop_id": "string (uuid)",
  "title": "string",
  "category": "string",               // primary category label
  "category_id": "string",

  // Pricing
  "price": "Numeric(18,2)",           // current listed price (VND)
  "price_currency": "string",         // always 'VND' for VN region

  // Inventory
  "inventory": "integer",             // units in stock across all SKUs

  // Sales aggregates — computed in feature build step (06:00–07:00 UTC, P2-A3)
  // P1: seeded from mock fixtures; historical backtest parquet; P2-A2: polled product metadata only
  "sales_7d": "integer",              // units sold in last 7 days
  "sales_30d": "integer",             // units sold in last 30 days
  "sales_prev_7d": "integer",         // units sold in the 7 days before sales_7d window (for growth calc)
  "revenue_7d": "Numeric(18,2)",      // GMV last 7 days (VND)
  "revenue_30d": "Numeric(18,2)",     // GMV last 30 days (VND)

  // Return aggregates
  "returns_30d": "integer",           // return events in last 30 days
  "return_rate_30d": "float",         // returns_30d / sales_30d; null if sales_30d = 0

  // Creator and livestream signals (forward-looking — P2+ recommendation context)
  "creator_count": "integer",         // affiliated creators promoting this product
  "livestream_count": "integer",      // post-stream sessions featuring this product (last 30d)

  // Platform status
  "audit_status": "string (enum: active | under_audit | suspended | delisted)",
  // endpoints.md: products[].audit.status

  "created_at": "timestamp",          // endpoints.md: products[].create_time (unix → datetime)
  "updated_at": "timestamp"
}
```

**Null handling:**
- `sales_7d`, `sales_30d`, `sales_prev_7d` default to `0` for new products with no orders.
- `return_rate_30d` is `null` when `sales_30d = 0` — never compute `0/0`.
- `creator_count` / `livestream_count` are `0` until affiliate polling populates them (P2).
- `inventory` is `null` when not yet synced (P2 — `sync_inventory` out of P2 core scope per `map.md`).

---

## Entity 3 — Order

**Refresh:** Daily polling (incremental via `update_time_from` cursor)  
**History:** ~90-day bounded history (TikTok API operational constraint; see `data-sources.md`)  
**Data lineage:** `POST /order/202309/orders/search` + `GET /order/202507/orders?ids=...` (see `endpoints.md` §Orders; verified #284, #285, #294)

**P2-A2 persistence (#299):** ETL maps TikTok operational statuses to canonical enum
(`pending | confirmed | shipped | delivered | cancelled | returned`). `order_value` is the canonical
monetary field; `total_amount` is populated with the same value for legacy API routes.
`is_seller_fault` is derived from `cancellation_initiator = SELLER` when status is `CANCELLED`.

```json
{
  "id": "string (uuid)",
  "tiktok_order_id": "string",        // endpoints.md: order_id
  "shop_id": "string (uuid)",
  "buyer_id": "string (masked)",      // masked buyer_*** — no PII stored (Forbidden #17)

  "status": "string (enum: pending | confirmed | shipped | delivered | cancelled | returned)",

  // Financial
  "order_value": "Numeric(18,2)",     // total order value (VND)
  "currency": "string",               // always 'VND' for VN region

  // Timestamps
  "payment_time": "timestamp | null",
  "ship_time": "timestamp | null",    // when seller dispatches
  "delivery_time": "timestamp | null",// when buyer confirms receipt
  "created_at": "timestamp",          // ETL: tiktok_created_at from create_time (unix → datetime)
  "update_time": "timestamp",         // reconciliation key for idempotent upserts

  // Cancellation signals (used in seller_fault_cancel_rate_30d feature)
  "cancel_reason": "string | null",   // verified: cancel_reason on cancelled orders (#299)
  "is_seller_fault": "boolean | null" // ETL-derived from cancellation_initiator (#299)
}
```

**Operational rules:**
- `buyer_id` must remain masked at all layers — never store full buyer identity ([Forbidden #17](../architecture/data-sources.md)).
- ETL maps `user_id` → `buyer_id` and `order_status` → canonical `status` per `mapping.py`.
- `is_seller_fault` defaults to `null` when `cancellation_initiator` is absent; do not infer from `cancel_reason` text alone.

---

## Entity 4 — OrderItem

**Refresh:** Populated from `line_items[]` in order search/detail responses  
**History:** Same as parent `Order` (~90-day bounded)  
**Data lineage:** `line_items[]` inside `POST /order/202309/orders/search` and `GET /order/202507/orders` responses (see `endpoints.md` §Orders; expanded by `mapping.expand_order_line_items`)

> **Critical:** Without `OrderItem`, anomaly detection for `item_swap` returns is
> impossible — you cannot compare ordered SKU vs returned SKU without the line-item
> record. Populated in P2-A2 ETL (#299). See `system-design.md` §Return schema contract and ADR-008.

```json
{
  "id": "string (uuid)",
  "order_id": "string (uuid)",        // FK → Order.id
  "tiktok_order_id": "string",        // denormalized for join efficiency
  "tiktok_product_id": "string",      // line_items[].product_id
  "tiktok_sku_id": "string",          // line_items[].sku_id — ordered SKU
  "quantity": "integer",
  "unit_price": "Numeric(18,2)",      // price per unit at time of order (VND)
  "line_total": "Numeric(18,2)"       // unit_price × quantity
}
```

**Anomaly detection use:**
- `item_swap` detection: compare `OrderItem.tiktok_sku_id` (ordered) vs `Return.tiktok_sku_id` (returned).
- If SKU values differ → ETL promotes `return_type` to `item_swap` (`consumer._derive_return_type`, #299).
- `unit_price` is required for revenue-leakage magnitude calculation (how much GMV was lost per swap event).

**Null handling:**
- `unit_price` must never be `null` — default to `0` only when order was free/promo; log a warning.
- `tiktok_sku_id` must not be `null` — missing SKU makes item_swap detection impossible; emit a data quality alert.

---

## Entity 5 — Return

**Refresh:** Daily (aligned with Order polling)  
**History:** 30-day rolling window for feature aggregation; raw records kept 90 days  
**Data lineage:** `POST /return_refund/202602/returns/search` + `POST /return_refund/202309/cancellations/search` (see `endpoints.md` §Returns; verified #286, #288, #294)

```json
{
  "id": "string (uuid)",
  "tiktok_return_id": "string",
  "order_id": "string (uuid)",        // FK → Order.id
  "tiktok_order_id": "string",
  "shop_id": "string (uuid)",
  "buyer_id": "string (masked)",      // masked — no PII (Forbidden #17)

  // Line-item identifiers (critical for item_swap detection)
  "tiktok_product_id": "string",      // which product was returned
  "tiktok_sku_id": "string",          // which SKU was returned — compare vs OrderItem.tiktok_sku_id

  // Classification (ETL-derived in P2-A2; ML label deferred to Phase 4)
  // Enum is the ground truth used in system-design.md §Return schema contract
  "return_type": "string (enum: item_swap | empty_return | other)",

  // Detection inputs
  "return_condition": "string (enum: wrong_item | empty_parcel | correct_item | unknown)",
  // item_swap  → return_condition = 'wrong_item' OR tiktok_sku_id ≠ OrderItem.tiktok_sku_id
  // empty_return → return_condition = 'empty_parcel'

  "return_reason": "string | null",   // free text or platform enum — confirm in P2-1

  // Financial
  "refund_amount": "Numeric(18,2)",   // VND

  // Status lifecycle
  "status": "string (enum: pending_review | approved | rejected)",

  "created_at": "timestamp"
}
```

**Derivation rules for `return_type` (ETL layer — #299):**
1. `item_swap`: `return_condition = 'wrong_item'` **OR** `Return.tiktok_sku_id ≠ OrderItem.tiktok_sku_id` for the parent order line (requires OrderItem ingested first).
2. `empty_return`: `return_condition = 'empty_parcel'`.
3. `other`: all remaining — legitimate returns (size, SNAD, change-of-mind). Negative class for Phase 4 anomaly training.

**Null handling:**
- `return_condition = 'unknown'` when inspection outcome is not exposed by the API — do not infer `return_type` from `return_reason` text alone.
- `tiktok_sku_id = null` blocks item_swap SKU-edge detection — emit data quality alert; label `return_type = other` conservatively.

---

## Entity 6 — Creator

**Refresh:** Daily (P2 affiliate polling)  
**History:** Current snapshot; 30-day rolling for gmv_generated aggregation  
**Data lineage:** `POST /api/affiliate/creators/search` + `GET /api/affiliate/creators/details` (see `endpoints.md` §Affiliate — Creators)

> **Scope note:** `Creator` is **not an input** to the Phase 2 MVP Milestone A anomaly ML model
> (ADR-008). It powers
> commission-dispute **policy alerts** (Phase 2) and is forward-looking context
> for Growth Copilot / creator matching (Phase 3+).

```json
{
  "id": "string (uuid)",
  "tiktok_creator_id": "string",
  "shop_id": "string (uuid)",         // which shop this creator is affiliated with

  // Audience
  "follower_count": "integer",
  "avg_views": "float | null",        // average views per video/LIVE session (post-stream)

  // Category
  "category": "string",               // primary content category

  // Affiliate terms
  "commission_rate": "float",         // as a decimal (e.g. 0.18 = 18%)
  "collab_type": "string (enum: open | targeted)",
  // 'targeted' rate overrides 'open' per cross-cutting.md

  // Performance (30-day rolling)
  "conversion_rate": "float | null",  // orders / clicks — null until sufficient data
  "gmv_generated": "Numeric(18,2)",   // total GMV attributed to this creator in last 30d (VND)

  // Creator tier (affiliate eligibility)
  // Link-Share Only: follower_count < 1000 — no video/LIVE commission
  // Affiliate Creator: follower_count >= 1000 — full commission eligible
  "creator_tier": "string (enum: link_share_only | affiliate_creator)",

  // KYC status (VN region — REGION-VARIANT, ADR-007)
  // VN only since Jul 1, 2025: CCCD + tax code required to withdraw commissions
  "kyc_complete": "boolean | null",   // null for non-VN regions

  "created_at": "timestamp"
}
```

**Operational rules:**
- `commission_rate` for `collab_type = targeted` takes precedence over `open` rate for the same product ([cross-cutting.md](../tiktok_platform/cross-cutting.md)).
- `kyc_complete = false` for VN creators means commission cannot be paid out — surface as a Revenue Leakage alert for affiliated shops.
- Creator commissions are payable only after seller settlement period completes — apply `Shop.settlement_hold_days` delay for any payout estimate.
- CHR scoring and creator matching are **Phase 3+** — do not add CHR fields here until rescoped.

---

## Entity 7 — Livestream

**Refresh:** Daily (post-stream summaries only)  
**History:** 30-day rolling window  
**Data lineage:** `POST /api/affiliate/livestreams/search` + `GET /api/affiliate/livestreams/details` (see `endpoints.md` §Affiliate — Livestreams)

> **Forward-looking:** Livestream is out of P2 core scope (polling worker slated for
> removal per `map.md`). Schema is defined now so P2/P3 recommendation systems can
> ingest it without a schema migration. Do NOT include in Phase 2 MVP Milestone A anomaly training data.
>
> **Constraint:** Post-stream summaries only. Realtime in-stream telemetry is
> **permanently forbidden** (Forbidden #8 — ToS risk).

```json
{
  "id": "string (uuid)",
  "tiktok_livestream_id": "string",
  "creator_id": "string (uuid)",      // FK → Creator.id
  "shop_id": "string (uuid)",

  // Session timing
  "start_time": "timestamp",
  "end_time": "timestamp",
  "duration_minutes": "integer",      // derived: (end_time - start_time) / 60

  // Audience (post-stream aggregate — NOT realtime)
  "viewers": "integer",               // peak or total viewers (confirm metric in P2 API docs)

  // Commerce outcomes (post-stream)
  "orders": "integer",                // orders placed during session
  "gmv": "Numeric(18,2)",             // gross merchandise value from session (VND)

  "created_at": "timestamp"           // when the record was ingested
}
```

**Null handling:**
- `viewers = null` when the API does not expose viewer count — do not impute; flag in data quality log.
- `orders = 0` and `gmv = 0` are valid for a session with no conversions.

---

## Entity 8 — Settlement

**Refresh:** Daily (aligned with TikTok settlement cycle — 3rd and 15th day after delivery)  
**History:** 90-day rolling; point-in-time snapshot for revenue tracking  
**Data lineage:** `POST /api/finance/settlements/search` (see `endpoints.md` §Finance — Settlements)

> **Canonical form:** Settlement is the canonical entity for TikTok's Finance Signal.
> Raw settlement amounts must be held as `pending` for the duration of `Shop.settlement_hold_days`
> before being treated as final. See four-tier framework in `data-sources.md` §Operational rules.
>
> **P2 scope note:** `sync_settlements` is slated for removal from polling workers
> per `map.md`. Settlement data is used as a **Revenue Leakage signal** (balance
> withholding, commission dispute holds) — not a standalone financial dashboard.

```json
{
  "id": "string (uuid)",
  "tiktok_settlement_id": "string",
  "shop_id": "string (uuid)",

  // Financial
  "amount": "Numeric(18,2)",          // settlement amount (VND)
  "currency": "string",               // always 'VND' for VN region
  "fee_deducted": "Numeric(18,2)",    // platform fees deducted
  "net_amount": "Numeric(18,2)",      // amount - fee_deducted

  // Status lifecycle
  // 'pending' — within hold window (use Shop.settlement_hold_days)
  // 'processing' — past hold window, in transit
  // 'settled' — funds released
  // 'frozen' — enforcement withholding (DISTINCT from pending; up to 180 days)
  "status": "string (enum: pending | processing | settled | frozen)",

  // Tier applied to this settlement (copied from Shop.settlement_tier at settle time)
  "settlement_tier": "string (enum: express | accelerated | standard | extended)",
  "hold_days": "integer",             // 1 | 3 | 8 | 15 (up to 30 for extended/risk)

  // Timing
  "settle_date": "timestamp",         // when TikTok releases the funds
  "period_start": "timestamp",        // order window covered by this settlement
  "period_end": "timestamp",

  "created_at": "timestamp"
}
```

**Operational rules:**
- `status = frozen` is **not** the same as `pending` — frozen balance is an enforcement action (up to 180 days from enforcement notification). Never merge these statuses.
- Commission dispute holds: creator commission held `pending` on disputed orders — flag as Revenue Leakage signal; not an ML input.
- Do not mark `settled` until `settle_date <= now()` AND `hold_days` have elapsed from order delivery.

---

## Workflow entities (New Seller Copilot)

Juli-internal workflow schemas — **not** TikTok API entities. Used in listing workflow (pre-MVP) mock
fixtures and Phase 2 Postgres persistence. Authority: ADR-016.

### ProductDraft

**Refresh:** On seller edit / generation complete  
**History:** Retain drafts until published or explicitly discarded (P2+)  
**P1.6:** Mock JSON in `web/src/lib/mock-data/`; **P2:** Postgres `product_drafts`

```json
{
  "draft_id": "string (uuid)",
  "seller_id": "string (uuid)",
  "shop_id": "string (uuid)",
  "status": "string (enum: in_progress | ready_for_export | blocked)",
  "source_type": "string (enum: manual_form | url_stub | opportunity_card)",
  "product_info": {
    "product_name": "string",
    "brand": "string | null",
    "category": "string",
    "price": "Numeric(18,2)",
    "variants": "array",
    "description": "string | null"
  },
  "listing_content": {
    "title": "string",
    "description": "string",
    "bullet_points": "string[]",
    "seo_keywords": "string[]",
    "hashtags": "string[]"
  },
  "compliance": {
    "status": "string (enum: approved | warning | blocked)",
    "warnings": "string[]",
    "blocking_issues": "string[]"
  },
  "readiness": {
    "overall_score": "integer (0-100)",
    "suggested_improvements": "string[]"
  },
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

### Distributor (curated catalog)

**P1.6:** Mock fixtures; **P2:** curated internal table; **P3+:** optional marketplace API

```json
{
  "distributor_id": "string (uuid)",
  "name": "string",
  "category_coverage": "string[]",
  "moq": "integer",
  "lead_time_days": "integer",
  "reliability_score": "float (0-1)",
  "source": "string (enum: internal_curated | marketplace_api | research)",
  "verification_status": "string (enum: verified | unverified | flagged)"
}
```

### Opportunity (curated catalog)

**P1.6:** Mock fixtures with deterministic filter fields; **P2:** curated internal table

```json
{
  "opportunity_id": "string (uuid)",
  "product_name": "string",
  "category": "string",
  "estimated_demand": "integer (1-10)",
  "competition_level": "string (enum: low | medium | high)",
  "margin_potential": "float",
  "trend_score": "integer (1-10)",
  "suggested_supplier_ids": "string[]",
  "confidence": "float (0-1)",
  "source": "string (enum: internal_curated | seller_center | marketplace_api | research)"
}
```

---

## Workflow entities (Revenue Leakage)

Juli-internal workflow schemas — **not** TikTok API entities. Used in leakage workflow (pre-MVP) mock
fixtures and Phase 2 Postgres persistence. Authority:
ADR-013.

### LeakageWorkflowTask

**Refresh:** On inference batch (P2) or fixture load (P1.7)  
**P1.7:** Extends `MockTask` in `web/src/lib/mock-data/leakage-workflow/`; **P2:** API
envelope from inference + rules engine

```json
{
  "id": "string (uuid)",
  "workflow": "leakage",
  "type": "string (enum: return_spike | buyer_cancellation_cluster | refund_cluster | return_window_policy)",
  "severity": "string (enum: high | medium | low | info)",
  "title": "string",
  "body": "string",
  "cta_label": "string",
  "estimated_impact_vnd": "Numeric(18,2) | null",
  "evidence_refs": "string[]",
  "copy_source": "string (enum: mock | rules | ollama)",
  "workflow_status": "string (enum: new | in_review | evidence_reviewed | ready_to_execute | executing | completed | skipped)",
  "detail": {
    "summary_vi": "string",
    "charts": "object[]",
    "benchmarks": "object[]",
    "affected_product_ids": "string[]",
    "estimated_gmv_leakage_vnd": "Numeric(18,2) | null"
  },
  "evidence_bundle": {
    "orders": "MockOrder[]",
    "returns": "MockReturn[]",
    "order_items": "OrderItem[]",
    "profile_metrics": "object[]",
    "timeline_events": "object[]"
  },
  "root_cause": {
    "classification": "string (enum: seller_optimization | buyer_risk | undetermined | shop_config)",
    "confidence": "float (0-1)",
    "summary_vi": "string",
    "possible_causes": "string[]"
  },
  "recommended_action": {
    "action_type": "string (enum: listing_update | investigation_package | monitoring | shop_settings)",
    "summary_vi": "string",
    "checklist": "string[]"
  },
  "execution_plan": {
    "steps": [
      {
        "id": "string",
        "title_vi": "string",
        "description_vi": "string",
        "mock_duration_ms": "integer | null"
      }
    ]
  },
  "success": {
    "headline_vi": "string",
    "metrics_vi": "string[]"
  },
  "skip_reason": "string (enum: false_positive | already_handled | not_relevant | other) | null",
  "skip_note": "string | null"
}
```

**Operational rules:**
- `evidence_bundle` entities must use masked `buyer_id` (`buyer_***`) only — Forbidden #17.
- `order_items[]` reserved for P2 `item_swap` SKU comparison; may be empty in P1.7 mocks.
- Optional P1.7 stretch: add `return_type` on linked `MockReturn` rows (`item_swap` |
  `empty_return` | `other`) per § Return entity — UI preview only, not ML inference.
- `affiliate_fraud` is **not** a valid `type` — affiliate patterns are policy alerts in P2.

### LeakageExecutionResult (P2+)

Mock stub in P1.7; persisted outcome in P2.

```json
{
  "task_id": "string (uuid)",
  "action_type": "string",
  "status": "string (enum: pending | succeeded | failed)",
  "executed_at": "timestamp | null",
  "artifact_refs": "string[]",
  "error_code": "string | null"
}
```

---

## Multi-platform expansion note (Shopee / Lazada — Phase 3+)

These canonical entities are designed to be **platform-agnostic**. A Shopee or
Lazada adapter would populate the same entity schema by mapping its own API
response fields, using the same ETL derivation rules (especially for `return_type`
derivation and masked `buyer_id`).

- Add a `platform` field (`tiktok | shopee | lazada`) to each entity when
  multi-platform work begins (Phase 3+).
- Do not add `platform` now — it would be YAGNI and requires schema migration.
- The feature store (`feature-store-schema.md`) already uses canonical entity
  field names, so ML features compose correctly across platforms once the adapters exist.

---

## P2-A2 ETL implementation reference (#299)

**Code:** `backend/src/juli_backend/integrations/tiktok/mapping.py` (vendor JSON normalization) →
`backend/src/juli_backend/services/etl/transform.py` (canonical upsert kwargs) →
`backend/src/juli_backend/services/etl/consumer.py` (idempotent upserts + `item_swap` edge derivation).

**Migration:** `010_canonical_product_fields` adds nullable canonical columns on `products` and `orders`.

| Entity | Persisted in P2-A2 | Deferred |
|--------|-------------------|----------|
| **Product** | `tiktok_product_id`, `title`, `category`, `category_id`, `price`, `price_currency`, `inventory`, `audit_status`, `tiktok_created_at`; legacy `name`, `status`, `revenue`, `units_sold` | `sales_7d`, `sales_30d`, return aggregates, `creator_count` (P2-A3 feature build) |
| **Order** | `tiktok_order_id`, canonical `status`, `buyer_id`, `order_value`, `currency`, `payment_time`, `ship_time`, `delivery_time`, `tiktok_created_at`, `cancel_reason`, `is_seller_fault`; legacy `total_amount` | — |
| **OrderItem** | `tiktok_order_id`, `tiktok_product_id`, `tiktok_sku_id`, `quantity`, `unit_price`, `line_total` | — |
| **Return** | `tiktok_return_id`, `tiktok_order_id`, `buyer_id`, `tiktok_product_id`, `tiktok_sku_id`, `return_type`, `return_condition`, `return_reason`, `refund_amount`, `status` | — |

**Idempotency:** Natural-key upserts on `(shop_id, tiktok_*_id)`; `update_time` drives re-poll updates.

**Tests:** `tests/unit/test_etl.py` — canonical product/order re-poll, `item_swap` edge derivation.

---

## Unknown fields — do NOT fabricate

The following are in policy documentation but their API exposure is **unverified**
as of P2-A1 gate. Mark these `UNKNOWN` in mock fixtures — never generate plausible
numeric values.

| Field | Entity | Why UNKNOWN |
|---|---|---|
| `vp_score` | Shop | API endpoint not confirmed in Partner Center |
| `ahr_score` | Shop | API endpoint not confirmed; VN transition May–July 2026 |
| `withholding_active` | Shop | Enforcement API field not extracted |
| `violation_events` | Shop | Webhook catalog not extracted |
| Ads API fields | — (separate entity TBD) | No `AdsResource` exists yet; confirm official path before P2-A3 |

> **Verified in P2-A2 (#299):** `cancel_reason`, `is_seller_fault` (Order); product audit
> status and pricing fields (Product); return classification inputs (Return).
>
> **Action:** When Partner API Reference confirms remaining UNKNOWN fields, update this file,
> `endpoints.md` §Account Health, and `data-sources.md`.
