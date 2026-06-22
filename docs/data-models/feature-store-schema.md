# Feature Store Schema

> **Authority:** `EXECUTION.md` > `system-design.md` > this file.  
> Feature definitions are tied to **Phase 2 MVP Milestone A** ML training (backtest/synthetic)
> and must align with `system-design.md` §Return schema contract.
>
> All features are derived from **canonical entities** defined in
> [`canonical-entities.md`](canonical-entities.md). Feature names here are the
> **authoritative identifiers** — Phase 2 MVP Milestone A parquet, P2 Postgres feature tables, and
> inference signatures must all use these exact names (no drift).

---

## Computation schedule (Phase 2 target)

```
06:00–07:00 UTC — feature build job
  Reads: canonical entity tables (Order, OrderItem, Return, Product, Creator, etc.)
  Writes: feature tables (one row per shop × feature × date)

08:00 UTC — batch inference job
  Reads: feature tables built in the 06:00 window
  Writes: model outputs (seller stage, anomaly flags, ad diagnoses)
```

In Phase 2 MVP Milestone A, the feature build runs on **backtest parquet** (batch, offline). The job
interface is kept runner-agnostic (plain Python functions) so Phase 2 swaps the
parquet reader for Postgres queries without rewriting feature logic.

---

## Feature conventions

| Property | Meaning |
|---|---|
| `update_frequency` | How often the feature value is recomputed |
| `valid_range` | Expected inclusive bounds; values outside should be flagged |
| `null_policy` | What to do when source data is missing |
| `ml_role` | Which model suite uses this feature and in what capacity |

---

## Group A — Anomaly Detector Features (buyer-behavior)

These features are the **primary inputs** to the Phase 2 MVP Milestone A anomaly detector
(`item_swap`, `empty_return` classification — [ADR-005](../decisions/008-buyer-behavior-anomaly-scope.md)).
They are derived from `Order`, `OrderItem`, and `Return` entities only.
Affiliate signals are **excluded** from this group per ADR-005.

---

### A1 — `return_rate_30d`

| Property | Value |
|---|---|
| **Description** | Proportion of delivered orders that resulted in a return in the last 30 days |
| **Grain** | Per shop |
| **Update frequency** | Daily (feature build) |
| **ML role** | Anomaly detector — baseline return behavior; seller stage classifier — health signal |
| **Valid range** | `[0.0, 1.0]` |
| **Null policy** | `null` when `delivered_orders_30d = 0`; never compute 0/0 |

**Formula:**

```
return_rate_30d =
    COUNT(Return WHERE created_at >= now() - 30d AND shop_id = X)
    ÷
    COUNT(Order WHERE delivery_time >= now() - 30d AND status = 'delivered' AND shop_id = X)
```

**Dependencies:** `Return.shop_id`, `Return.created_at`, `Order.delivery_time`, `Order.status`

**Edge cases:**
- New shops with zero delivered orders → `null` (not `0.0`).
- Returns with `status = 'rejected'` are **excluded** — only count accepted returns.

---

### A2 — `buyer_return_count_30d`

| Property | Value |
|---|---|
| **Description** | Number of return events initiated by a specific buyer in the last 30 days |
| **Grain** | Per buyer (masked buyer_id) |
| **Update frequency** | Daily |
| **ML role** | Anomaly detector — buyer-level repeat-behavior signal |
| **Valid range** | `[0, ∞)` — values ≥ 3 within 30d are a strong anomaly signal |
| **Null policy** | Default `0` for buyers with no returns in window |

**Formula:**

```
buyer_return_count_30d[buyer_id] =
    COUNT(Return WHERE buyer_id = X AND created_at >= now() - 30d)
```

**Dependencies:** `Return.buyer_id`, `Return.created_at`

---

### A3 — `buyer_item_swap_count_30d`

| Property | Value |
|---|---|
| **Description** | Number of confirmed `item_swap` returns by a specific buyer in the last 30 days |
| **Grain** | Per buyer (masked buyer_id) |
| **Update frequency** | Daily |
| **ML role** | Anomaly detector — primary item_swap signal per buyer |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Formula:**

```
buyer_item_swap_count_30d[buyer_id] =
    COUNT(Return WHERE buyer_id = X
                   AND return_type = 'item_swap'
                   AND created_at >= now() - 30d)
```

**Dependencies:** `Return.buyer_id`, `Return.return_type`, `Return.created_at`

**Derivation dependency:** `return_type` is derived in ETL — requires `OrderItem.sku_id`
comparison. Missing `OrderItem` data makes this feature unreliable.

---

### A4 — `buyer_empty_return_count_30d`

| Property | Value |
|---|---|
| **Description** | Number of confirmed `empty_return` events by a specific buyer in the last 30 days |
| **Grain** | Per buyer (masked buyer_id) |
| **Update frequency** | Daily |
| **ML role** | Anomaly detector — primary empty_return signal per buyer |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Formula:**

```
buyer_empty_return_count_30d[buyer_id] =
    COUNT(Return WHERE buyer_id = X
                   AND return_type = 'empty_return'
                   AND created_at >= now() - 30d)
```

**Dependencies:** `Return.buyer_id`, `Return.return_type`, `Return.created_at`

---

### A5 — `buyer_repeat_anomaly_flag`

| Property | Value |
|---|---|
| **Description** | Boolean flag — buyer has ≥ 2 anomalous returns (item_swap or empty_return) in 30 days |
| **Grain** | Per buyer (masked buyer_id) |
| **Update frequency** | Daily |
| **ML role** | Anomaly detector — high-confidence fraud signal for known-bad buyers |
| **Valid range** | `{0, 1}` (boolean as integer for ML compatibility) |
| **Null policy** | Default `0` |

**Formula:**

```
buyer_repeat_anomaly_flag[buyer_id] =
    1 IF (buyer_item_swap_count_30d[buyer_id] + buyer_empty_return_count_30d[buyer_id]) >= 2
    ELSE 0
```

**Dependencies:** `A3 (buyer_item_swap_count_30d)`, `A4 (buyer_empty_return_count_30d)`

**Note:** Uses derived features A3 and A4 as inputs — compute A3 and A4 first.

---

### A6 — `seller_fault_cancel_rate_30d`

| Property | Value |
|---|---|
| **Description** | Proportion of cancelled orders where `is_seller_fault = true` in last 30 days |
| **Grain** | Per shop |
| **Update frequency** | Daily |
| **ML role** | Anomaly detector — seller operational health proxy; seller stage classifier |
| **Valid range** | `[0.0, 1.0]` |
| **Null policy** | `null` when `is_seller_fault` is UNKNOWN (P2-1 gate); `null` when total orders = 0 |

**Formula:**

```
seller_fault_cancel_rate_30d =
    COUNT(Order WHERE status = 'cancelled'
                  AND is_seller_fault = true
                  AND created_at >= now() - 30d
                  AND shop_id = X)
    ÷
    COUNT(Order WHERE created_at >= now() - 30d AND shop_id = X)
```

**Dependencies:** `Order.status`, `Order.is_seller_fault`, `Order.created_at`, `Order.shop_id`

> **UNKNOWN gate:** `is_seller_fault` is not confirmed in Partner API (see
> `canonical-entities.md` §Unknown fields). In Phase 2 MVP Milestone A synthetic data, simulate with
> a boolean sampled from a realistic base rate (~5%). In P2, emit a data quality
> warning and set feature to `null` if the field is absent.

---

## Group B — Product / Growth Features

Used by the **seller stage classifier** and **ad performance analyzer**.

---

### B1 — `sales_growth_7d`

| Property | Value |
|---|---|
| **Description** | Relative week-over-week sales unit growth for a product |
| **Grain** | Per product |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — growth trajectory; ad performance analyzer — momentum |
| **Valid range** | `(-1.0, ∞)` — values < -1 are impossible (can't lose more than 100%); clamp to `-1.0` floor |
| **Null policy** | `null` when `sales_prev_7d = 0` (new product or zero prior period) |

**Formula:**

```
sales_growth_7d =
    (Product.sales_7d - Product.sales_prev_7d) ÷ Product.sales_prev_7d
```

**Dependencies:** `Product.sales_7d`, `Product.sales_prev_7d`

**Edge cases:**
- `sales_prev_7d = 0` → `null` (division by zero; new product or gap in data).
- `sales_7d = 0, sales_prev_7d > 0` → `-1.0` (total drop — valid, not null).
- Extreme values (> 10.0 = 1000% growth) are possible for viral products; do not clamp at the top.

---

### B2 — `inventory_risk_score`

| Property | Value |
|---|---|
| **Description** | Days of inventory remaining at current 7-day sales rate; lower = higher stockout risk |
| **Grain** | Per product |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — operational risk; Growth Copilot — restock alert |
| **Valid range** | `[0, ∞)` — values ≤ 7 days are high risk; ≤ 0 means stockout |
| **Null policy** | `null` when `Product.inventory = null` (not yet synced); `null` when `sales_7d = 0` (no sales velocity) |

**Formula:**

```
daily_sales_rate = Product.sales_7d ÷ 7

inventory_risk_score =
    Product.inventory ÷ daily_sales_rate
    (result in days)
```

**Dependencies:** `Product.inventory`, `Product.sales_7d`

**Edge cases:**
- `sales_7d = 0` → `null` (no velocity signal; do not imply infinite stock).
- `inventory = 0` → `0` (stockout confirmed).
- `inventory = null` → `null` (sync_inventory out of P2 core scope — emit a gap warning).

---

## Group D — Seller Stage Classifier Features

Shop-level features for the **seller stage classifier** (`new` | `leakage` | `growth`).
Aligned with pre-MVP seller profile fields and `build_seller_stage_features` output
(#137). Grain: **shop × date**.

---

### D1 — `shop_age_days`

| Property | Value |
|---|---|
| **Description** | Days since the shop's earliest order `created_at` |
| **Grain** | Per shop |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — lifecycle maturity signal |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` when no orders exist |

**Formula:**

```
shop_age_days = (reference_date - MIN(Order.created_at WHERE shop_id = X)).days
```

**Dependencies:** `Order.created_at`, `Order.shop_id`

---

### D2 — `order_count_30d`

| Property | Value |
|---|---|
| **Description** | Count of orders created in the last 30 days |
| **Grain** | Per shop |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — volume signal for new vs growth routing |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Formula:**

```
order_count_30d = COUNT(Order WHERE created_at >= now() - 30d AND shop_id = X)
```

**Dependencies:** `Order.created_at`, `Order.shop_id`

---

### D3 — `return_rate_30d` *(shared with Group A)*

See **A1 — `return_rate_30d`**. Seller stage classifier reuses the shop-level
return rate as a leakage signal.

---

### D4 — `ad_spend_30d_vnd`

| Property | Value |
|---|---|
| **Description** | Total ad spend in VND over the last 30 days |
| **Grain** | Per shop |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — growth trajectory signal |
| **Valid range** | `[0, ∞)` VND |
| **Null policy** | Default `0.0` when no ad history |

**Formula:**

```
ad_spend_30d_vnd = SUM(ads.parquet.spend_vnd WHERE date >= now() - 30d AND shop_id = X)
```

**Dependencies:** `ads.parquet` — `spend_vnd`, `date`, `shop_id`

---

### D5 — `gmv_30d_vnd`

| Property | Value |
|---|---|
| **Description** | Gross merchandise value from delivered orders in the last 30 days |
| **Grain** | Per shop |
| **Update frequency** | Daily |
| **ML role** | Seller stage classifier — revenue scale signal |
| **Valid range** | `[0, ∞)` VND |
| **Null policy** | Default `0.0` |

**Formula:**

```
gmv_30d_vnd = SUM(Order.order_value WHERE status = 'delivered'
                              AND delivery_time >= now() - 30d
                              AND shop_id = X)
```

**Dependencies:** `Order.order_value`, `Order.status`, `Order.delivery_time`, `Order.shop_id`

---

## Group E — Ad Performance Features

Campaign/day features for the **ad performance analyzer** (scale / cut / hold).
Source columns align with `ads.parquet` contract in `src/modules/ml/dataset/schema.py`
(#136). Grain: **campaign × day**.

> **Parquet source columns:** `spend_vnd`, `impressions`, `clicks`, `conversions`,
> `roas`, `cpc_vnd` — plus join keys `shop_id`, `campaign_id`, `date`.

---

### E1 — `spend_vnd`

| Property | Value |
|---|---|
| **Description** | Daily ad spend in VND for the campaign |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — spend efficiency input |
| **Valid range** | `[0, ∞)` VND |
| **Null policy** | Default `0.0` |

**Dependencies:** `ads.parquet.spend_vnd`

---

### E2 — `roas`

| Property | Value |
|---|---|
| **Description** | Return on ad spend for the campaign/day |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — primary efficiency metric (regression target) |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0.0` when spend is zero |

**Dependencies:** `ads.parquet.roas`

---

### E3 — `cpc_vnd`

| Property | Value |
|---|---|
| **Description** | Cost per click in VND |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — bid efficiency signal |
| **Valid range** | `[0, ∞)` VND |
| **Null policy** | Default `0.0` |

**Dependencies:** `ads.parquet.cpc_vnd`

---

### E4 — `conversions`

| Property | Value |
|---|---|
| **Description** | Conversion count for the campaign/day |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — funnel depth signal |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Dependencies:** `ads.parquet.conversions`

---

### E5 — `impressions`

| Property | Value |
|---|---|
| **Description** | Impression count for the campaign/day |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — reach signal |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Dependencies:** `ads.parquet.impressions`

---

### E6 — `clicks`

| Property | Value |
|---|---|
| **Description** | Click count for the campaign/day |
| **Grain** | Per campaign × day |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — engagement signal |
| **Valid range** | `[0, ∞)` |
| **Null policy** | Default `0` |

**Dependencies:** `ads.parquet.clicks`

---

### E7 — `account_avg_roas_30d`

| Property | Value |
|---|---|
| **Description** | Shop-level average ROAS across all campaigns in the 30-day window |
| **Grain** | Per shop (joined to campaign rows) |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — account baseline for relative efficiency |
| **Valid range** | `[0, ∞)` |
| **Null policy** | `null` when shop has no ad history in window |

**Formula:**

```
account_avg_roas_30d = MEAN(ads.parquet.roas WHERE date >= now() - 30d AND shop_id = X)
```

**Dependencies:** `ads.parquet.roas`, `ads.parquet.date`, `ads.parquet.shop_id`

---

### E8 — `account_spend_velocity_30d`

| Property | Value |
|---|---|
| **Description** | Total shop ad spend in the 30-day window — spend velocity baseline |
| **Grain** | Per shop (joined to campaign rows) |
| **Update frequency** | Daily |
| **ML role** | Ad performance analyzer — account spend context |
| **Valid range** | `[0, ∞)` VND |
| **Null policy** | Default `0.0` |

**Formula:**

```
account_spend_velocity_30d = SUM(ads.parquet.spend_vnd WHERE date >= now() - 30d AND shop_id = X)
```

**Dependencies:** `ads.parquet.spend_vnd`, `ads.parquet.date`, `ads.parquet.shop_id`

---

## Group C — Creator / Affiliate Features

Used for **commission dispute detection** (Revenue Leakage) and
**Growth Copilot** context. Not inputs to the Phase 2 MVP Milestone A anomaly detector.

---

### C1 — `creator_efficiency_score`

| Property | Value |
|---|---|
| **Description** | GMV generated per follower — normalizes creator output across audience sizes |
| **Grain** | Per creator |
| **Update frequency** | Daily |
| **ML role** | Growth Copilot — creator performance ranking (Phase 2+); creator matching (Phase 3+) |
| **Valid range** | `[0, ∞)` VND per follower |
| **Null policy** | `null` when `Creator.follower_count = 0` or `null` |

**Formula:**

```
creator_efficiency_score =
    Creator.gmv_generated ÷ Creator.follower_count
```

**Dependencies:** `Creator.gmv_generated`, `Creator.follower_count`

**Edge cases:**
- `follower_count = 0` → `null` (Link-Share Only tier with no audience).
- `gmv_generated = 0` → `0.0` (valid — creator has audience but zero conversions).
- Result is in VND/follower; normalize per-category if comparing across niches.

---

### C2 — `creator_commission_pending_rate`

| Property | Value |
|---|---|
| **Description** | Fraction of this creator's commissions currently in `pending` state (held by settlement or dispute) |
| **Grain** | Per creator |
| **Update frequency** | Daily |
| **ML role** | Revenue Leakage Detection — commission dispute alert signal |
| **Valid range** | `[0.0, 1.0]` |
| **Null policy** | `null` when no commission history exists for this creator |

**Formula:**

```
creator_commission_pending_rate =
    SUM(Settlement.amount WHERE status = 'pending' AND creator_id = X AND period_end >= now() - 30d)
    ÷
    SUM(Settlement.amount WHERE creator_id = X AND period_end >= now() - 30d)
```

**Dependencies:** `Settlement.amount`, `Settlement.status`, `Settlement.creator_id` (to be confirmed — Settlement entity currently does not carry `creator_id`; link via `Order.creator_id` when available in P2)

> **Note:** This feature may require a join through Order → Settlement when the
> Settlement entity does not carry a direct `creator_id`. Confirm API schema in P2-1.

---

## Feature table layout (Phase 2 MVP Milestone A parquet → P2 Postgres)

### Buyer-level feature table

```
buyer_features.parquet (Phase 2 MVP Milestone A) / buyer_features (P2 Postgres)
─────────────────────────────────────────────────────
buyer_id            string (masked)       PK component
shop_id             string (uuid)         PK component
feature_date        date                  PK component (daily snapshot)
─────────────────────────────────────────────────────
buyer_return_count_30d          integer
buyer_item_swap_count_30d       integer
buyer_empty_return_count_30d    integer
buyer_repeat_anomaly_flag       integer (0 | 1)
```

### Shop-level feature table (seller stage)

```
shop_features_seller_stage.parquet (Phase 2 MVP Milestone A) / shop_features_seller_stage (P2 Postgres)
─────────────────────────────────────────────────────
shop_id             string (uuid)         PK component
feature_date        date                  PK component
─────────────────────────────────────────────────────
shop_age_days                   integer
order_count_30d                 integer
return_rate_30d                 float | null
ad_spend_30d_vnd                float
gmv_30d_vnd                     float
```

### Campaign-level feature table (ad performance)

```
ad_features.parquet (Phase 2 MVP Milestone A) / ad_features (P2 Postgres)
─────────────────────────────────────────────────────
shop_id             string (uuid)         PK component
campaign_id         string                PK component
date                date                  PK component
─────────────────────────────────────────────────────
spend_vnd                       float
roas                            float
cpc_vnd                         float
conversions                     integer
impressions                     integer
clicks                          integer
account_avg_roas_30d            float | null
account_spend_velocity_30d      float
```

### Shop-level feature table (anomaly shop aggregates)

```
shop_features.parquet (Phase 2 MVP Milestone A) / shop_features (P2 Postgres)
─────────────────────────────────────────────────────
shop_id             string (uuid)         PK component
feature_date        date                  PK component
─────────────────────────────────────────────────────
return_rate_30d                 float | null
seller_fault_cancel_rate_30d    float | null
```

### Product-level feature table

```
product_features.parquet (Phase 2 MVP Milestone A) / product_features (P2 Postgres)
─────────────────────────────────────────────────────
product_id          string                PK component
shop_id             string (uuid)         PK component
feature_date        date                  PK component
─────────────────────────────────────────────────────
sales_growth_7d         float | null
inventory_risk_score    float | null      (days)
```

### Creator-level feature table

```
creator_features.parquet (Phase 2 MVP Milestone A) / creator_features (P2 Postgres)
─────────────────────────────────────────────────────
creator_id          string (uuid)         PK component
shop_id             string (uuid)         PK component
feature_date        date                  PK component
─────────────────────────────────────────────────────
creator_efficiency_score        float | null
creator_commission_pending_rate float | null
```

---

## Feature schema hashes (artifact metadata)

Stable SHA-256 prefixes of the authoritative column tuples in
`src/modules/ml/features/schema.py`. Written to `metadata.json` by the artifact
publisher (#141) and validated at load time.

| Suite | `feature_schema_hash` | Column tuple source |
|-------|----------------------|---------------------|
| `seller_stage` | `a9752c5a8d1f5e9f` | `SELLER_STAGE_FEATURE_COLUMNS` |
| `anomaly` | `71b21e6d94257389` | `ANOMALY_FEATURE_COLUMNS` |
| `ad_performance` | `1287eca5ccbae7fe` | `AD_FEATURE_COLUMNS` |

---

## Inference signatures (ML artifact contract)

Each serialized model (Phase 2 MVP Milestone A → Phase 2) records the feature schema hash
alongside model weights so drift is caught at load time, not at prediction time.
Cross-linked from [`system-design.md`](../system-design.md) § ML models.

Model artifacts live at:

```
models/seller_stage/{version}/model.joblib + metadata.json
models/anomaly/{version}/model.joblib + metadata.json
models/ad_performance/{version}/model.joblib + metadata.json
```

### Seller stage classifier

```json
{
  "model": "seller_stage",
  "version": "v1.0",
  "model_path": "models/seller_stage/{version}/model.joblib",
  "train_date": "2026-06-06T08:00:00Z",
  "feature_schema_hash": "a9752c5a8d1f5e9f",
  "input_features": [
    "shop_age_days",
    "order_count_30d",
    "return_rate_30d",
    "ad_spend_30d_vnd",
    "gmv_30d_vnd"
  ],
  "output": {
    "stage": "string (enum: new | leakage | growth)",
    "confidence": "float [0.0, 1.0]"
  },
  "metrics": {
    "precision": 1.0,
    "recall_macro": 1.0
  }
}
```

Public inference entrypoint: `predict_seller_stage(model, features)`.

### Anomaly detector (buyer-behavior)

Per [ADR-005](../decisions/008-buyer-behavior-anomaly-scope.md): classes `item_swap`
and `empty_return` only. Affiliate and creator features are **excluded** from
training, labels, and inference.

```json
{
  "model": "anomaly",
  "version": "v1.0",
  "model_path": "models/anomaly/{version}/model.joblib",
  "train_date": "2026-06-06T08:00:00Z",
  "feature_schema_hash": "71b21e6d94257389",
  "input_features": [
    "buyer_return_count_30d",
    "buyer_item_swap_count_30d",
    "buyer_empty_return_count_30d",
    "buyer_repeat_anomaly_flag",
    "return_rate_30d",
    "seller_fault_cancel_rate_30d"
  ],
  "output": {
    "anomaly_class": "string | null (enum: item_swap | empty_return | null)",
    "confidence": "float [0.0, 1.0]",
    "feature_summary": "object — non-zero input features for UI evidence",
    "is_anomaly": "boolean"
  },
  "metrics": {
    "per_class": {
      "item_swap": { "precision": 1.0, "recall": 1.0 },
      "empty_return": { "precision": 0.0, "recall": 0.0 }
    }
  }
}
```

Public inference entrypoint: `predict_anomaly(model, features)`.

### Ad performance analyzer

```json
{
  "model": "ad_performance",
  "version": "v1.0",
  "model_path": "models/ad_performance/{version}/model.joblib",
  "train_date": "2026-06-06T08:00:00Z",
  "feature_schema_hash": "1287eca5ccbae7fe",
  "input_features": [
    "spend_vnd",
    "roas",
    "cpc_vnd",
    "conversions",
    "impressions",
    "clicks",
    "account_avg_roas_30d",
    "account_spend_velocity_30d"
  ],
  "output": {
    "action": "string (enum: scale | cut | hold)",
    "confidence": "float [0.0, 1.0]",
    "predicted_roas": "float"
  },
  "metrics": {
    "roas_mape": 0.54
  }
}
```

Public inference entrypoint: `predict_ad_action(model, features)`. Sparse ad history
returns low-confidence `hold` without raising.

---

Promotion targets and backtest reference metrics are recorded in
`system-design.md` § ML models before Phase 2 promotion.
