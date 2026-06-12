# Mock Data Generator

> **Purpose:** Pseudocode and reference implementation guidance for generating
> synthetic datasets that conform to schemas in [`canonical-entities.md`](canonical-entities.md).
>
> **When to use this document:**
> - **Phase 1 (P1):** Generating hardcoded mock fixtures for UI (seller profiles, sample orders, returns).
> - **Phase 1.5 (P1.5):** Generating `backtest/*.parquet` training datasets when historical TikTok data is unavailable.
>
> `canonical-entities.md` is the **schema authority** — this document only shows how
> to populate those schemas synthetically. If a schema field changes there, update
> generator logic here too.
>
> **Do NOT fabricate:** `vp_score`, `ahr_score`, `withholding_active`, `violation_events`,
> Ads API fields. Leave these `null` in all synthetic data. See §Unknown fields section
> in `canonical-entities.md`.

---

## Generator design principles

1. **Schema-first:** Every generated record must validate against the canonical entity JSON schema.
2. **Labeled anomalies:** P1.5 synthetic data must include `return_type` labels (`item_swap`, `empty_return`, `other`) at a realistic base rate — not all returns are anomalous.
3. **Referential integrity:** Foreign key chains must be consistent (`Return.order_id` → valid `Order.id`, etc.).
4. **Masked PII:** `buyer_id` must always be masked (e.g. `buyer_a1b2c3`). Never generate realistic names, emails, or phone numbers.
5. **Realistic distributions:** Skew toward the `other` (negative) class — anomaly prevalence in real data is typically 2–8% of returns. Oversampling for training is done in the ML pipeline, not the generator.
6. **Unknown fields → null:** Fields marked UNKNOWN in `canonical-entities.md` are always `null` in synthetic data.

---

## Base utilities (pseudocode)

```python
import uuid
import random
from datetime import datetime, timedelta
from decimal import Decimal

def new_id() -> str:
    return str(uuid.uuid4())

def masked_buyer_id() -> str:
    # Format: buyer_ + 6-char hex — no real PII
    return f"buyer_{uuid.uuid4().hex[:6]}"

def vnd(amount: float) -> str:
    # Always store as Numeric(18,2) — never use float for money in production
    return str(Decimal(str(amount)).quantize(Decimal("0.01")))

def rand_timestamp(days_ago_min: int, days_ago_max: int) -> str:
    delta = random.randint(days_ago_min * 86400, days_ago_max * 86400)
    return (datetime.utcnow() - timedelta(seconds=delta)).isoformat() + "Z"

def rand_status(weights: dict) -> str:
    choices = list(weights.keys())
    probabilities = list(weights.values())
    return random.choices(choices, weights=probabilities, k=1)[0]
```

---

## Dataset 1 — Product Growth Prediction

**Purpose:** Train the seller stage classifier to distinguish growing products
from stagnating or declining ones. Feeds the Growth Copilot workflow.

**Entities joined:** `Product` + `Livestream` + `Creator` + `Order`

**Target label:** `product_trajectory` (growing | stagnating | declining) — derived
from `sales_growth_7d` thresholds. This is **not** stored on the canonical entity;
it is computed in the feature build step.

```python
def generate_product_growth_dataset(
    n_shops: int = 50,
    products_per_shop: int = 20,
    orders_per_product: int = 100,
    livestreams_per_product: int = 5,
) -> dict[str, list[dict]]:
    """
    Returns: {
        "products": [...],
        "orders": [...],
        "order_items": [...],
        "creators": [...],
        "livestreams": [...],
        "labels": [...]     # product_id -> trajectory label
    }
    """
    shops = [generate_shop() for _ in range(n_shops)]
    products, orders, order_items, creators, livestreams, labels = [], [], [], [], [], []

    for shop in shops:
        shop_creators = [generate_creator(shop_id=shop["id"]) for _ in range(5)]
        creators.extend(shop_creators)

        for _ in range(products_per_shop):
            product = generate_product(shop_id=shop["id"])
            products.append(product)

            # Simulate two 7-day sales windows for growth calculation
            period_orders = generate_orders_for_product(
                product_id=product["tiktok_product_id"],
                shop_id=shop["id"],
                n_orders=orders_per_product,
                days_window=60,  # 60-day history
            )
            orders.extend(period_orders)
            order_items.extend([
                generate_order_item(order, product)
                for order in period_orders
            ])

            # Attach a few post-stream livestream sessions
            for _ in range(livestreams_per_product):
                creator = random.choice(shop_creators)
                livestreams.append(
                    generate_livestream(
                        creator_id=creator["id"],
                        shop_id=shop["id"],
                    )
                )

            # Derive trajectory label from simulated sales aggregates
            sales_7d = product["sales_7d"]
            sales_prev_7d = product["sales_prev_7d"]
            if sales_prev_7d == 0:
                trajectory = "stagnating"
            elif (sales_7d - sales_prev_7d) / sales_prev_7d > 0.1:
                trajectory = "growing"
            elif (sales_7d - sales_prev_7d) / sales_prev_7d < -0.1:
                trajectory = "declining"
            else:
                trajectory = "stagnating"

            labels.append({
                "product_id": product["id"],
                "feature_date": datetime.utcnow().date().isoformat(),
                "product_trajectory": trajectory,
            })

    return {
        "products": products,
        "orders": orders,
        "order_items": order_items,
        "creators": creators,
        "livestreams": livestreams,
        "labels": labels,
    }


def generate_product(shop_id: str) -> dict:
    sales_prev_7d = random.randint(0, 300)
    growth_factor = random.gauss(mu=1.05, sigma=0.3)  # roughly centered on slight growth
    sales_7d = max(0, int(sales_prev_7d * growth_factor))
    sales_30d = sales_prev_7d * 4 + sales_7d  # rough monthly total

    return {
        "id": new_id(),
        "tiktok_product_id": f"prod_{uuid.uuid4().hex[:12]}",
        "shop_id": shop_id,
        "title": f"Product {uuid.uuid4().hex[:6]}",
        "category": random.choice(["Fashion", "Electronics", "FMCG", "Lifestyle"]),
        "category_id": f"cat_{random.randint(100, 999)}",
        "price": vnd(random.uniform(50_000, 2_000_000)),
        "price_currency": "VND",
        "inventory": random.randint(0, 1000),
        "sales_7d": sales_7d,
        "sales_30d": sales_30d,
        "sales_prev_7d": sales_prev_7d,
        "revenue_7d": vnd(sales_7d * random.uniform(50_000, 500_000)),
        "revenue_30d": vnd(sales_30d * random.uniform(50_000, 500_000)),
        "returns_30d": int(sales_30d * random.uniform(0.02, 0.12)),
        "return_rate_30d": None if sales_30d == 0 else round(
            int(sales_30d * random.uniform(0.02, 0.12)) / sales_30d, 4
        ),
        "creator_count": random.randint(0, 20),
        "livestream_count": random.randint(0, 10),
        "audit_status": rand_status({
            "active": 0.88, "under_audit": 0.07, "suspended": 0.03, "delisted": 0.02
        }),
        "created_at": rand_timestamp(30, 365),
        "updated_at": rand_timestamp(0, 7),
    }
```

**Parquet output layout:**

```
backtest/product_growth/
  products.parquet
  orders.parquet
  order_items.parquet
  creators.parquet
  livestreams.parquet
  labels.parquet          # product_id, feature_date, product_trajectory
```

---

## Dataset 2 — Revenue Leakage Detection

**Purpose:** Train the anomaly detector to classify `item_swap`, `empty_return`,
and `other` returns. This is the **primary P1.5 training dataset** per
[ADR-011](../decisions/011-buyer-behavior-anomaly-scope.md).

**Entities joined:** `Order` + `OrderItem` + `Return` + `Settlement`

**Target label:** `return_type` (item_swap | empty_return | other)

> **Critical:** The `OrderItem` entity is **mandatory** for this dataset. Without
> `sku_id` comparison, `item_swap` detection is impossible. Every `Return` must
> have a parent `Order` with at least one `OrderItem`.

```python
ANOMALY_BASE_RATE = 0.05     # ~5% of returns are item_swap or empty_return
ITEM_SWAP_RATIO = 0.60       # of anomalies: 60% item_swap, 40% empty_return
REPEAT_BUYER_RATE = 0.15     # 15% of anomalous buyers are repeat offenders

def generate_leakage_dataset(
    n_shops: int = 30,
    orders_per_shop: int = 500,
    return_rate: float = 0.08,  # 8% of orders generate a return
) -> dict[str, list[dict]]:
    """
    Returns: {
        "orders": [...],
        "order_items": [...],
        "returns": [...],
        "settlements": [...],
        "labels": [...]     # return_id -> return_type (ground truth)
    }
    """
    shops = [generate_shop() for _ in range(n_shops)]
    orders, order_items, returns, settlements, labels = [], [], [], [], []

    # Pre-generate a pool of buyers: most normal, some repeat anomaly actors
    buyer_pool = [masked_buyer_id() for _ in range(200)]
    anomalous_buyers = random.sample(buyer_pool, k=int(len(buyer_pool) * REPEAT_BUYER_RATE))

    for shop in shops:
        for _ in range(orders_per_shop):
            buyer_id = random.choice(buyer_pool)
            order = generate_order(shop_id=shop["id"], buyer_id=buyer_id)
            orders.append(order)

            # Every order has at least 1 line item
            item = generate_order_item_for_order(order)
            order_items.append(item)

            # Simulate settlements for each order (not all orders settle immediately)
            if random.random() < 0.7:  # 70% of orders have a settlement record
                settlements.append(
                    generate_settlement(shop_id=shop["id"], order_value=order["order_value"])
                )

            # Generate a return for ~8% of orders
            if random.random() < return_rate:
                is_anomalous_buyer = buyer_id in anomalous_buyers
                is_anomaly = random.random() < (ANOMALY_BASE_RATE * 3 if is_anomalous_buyer
                                                 else ANOMALY_BASE_RATE)

                if is_anomaly:
                    if random.random() < ITEM_SWAP_RATIO:
                        return_type = "item_swap"
                        # item_swap: returned sku_id differs from ordered sku_id
                        returned_sku_id = f"sku_{uuid.uuid4().hex[:8]}"  # different SKU
                        return_condition = "wrong_item"
                    else:
                        return_type = "empty_return"
                        returned_sku_id = item["sku_id"]  # same SKU declared, but empty parcel
                        return_condition = "empty_parcel"
                else:
                    return_type = "other"
                    returned_sku_id = item["sku_id"]      # correct SKU returned
                    return_condition = "correct_item"

                ret = generate_return(
                    order=order,
                    ordered_sku_id=item["sku_id"],
                    returned_sku_id=returned_sku_id,
                    return_type=return_type,
                    return_condition=return_condition,
                )
                returns.append(ret)
                labels.append({
                    "return_id": ret["id"],
                    "ground_truth_anomaly": return_type in ("item_swap", "empty_return"),
                    "return_type": return_type,
                })

    return {
        "orders": orders,
        "order_items": order_items,
        "returns": returns,
        "settlements": settlements,
        "labels": labels,
    }


def generate_return(
    order: dict,
    ordered_sku_id: str,
    returned_sku_id: str,
    return_type: str,
    return_condition: str,
) -> dict:
    return {
        "id": new_id(),
        "tiktok_return_id": f"ret_{uuid.uuid4().hex[:12]}",
        "order_id": order["id"],
        "tiktok_order_id": order["tiktok_order_id"],
        "shop_id": order["shop_id"],
        "buyer_id": order["buyer_id"],          # already masked
        "product_id": f"prod_{uuid.uuid4().hex[:12]}",
        "sku_id": returned_sku_id,              # the SKU the buyer returned
        "return_type": return_type,             # ground truth label
        "return_condition": return_condition,
        "return_reason": random.choice([
            "wrong item received", "empty package", "changed mind",
            "size doesn't fit", "product defective",
        ]),
        "refund_amount": vnd(float(order["order_value"]) * random.uniform(0.5, 1.0)),
        "status": rand_status({"approved": 0.75, "pending_review": 0.15, "rejected": 0.10}),
        "created_at": rand_timestamp(0, 30),
    }
```

**Parquet output layout:**

```
backtest/revenue_leakage/
  orders.parquet
  order_items.parquet      # MANDATORY — required for sku_id comparison
  returns.parquet
  settlements.parquet
  labels.parquet           # return_id, ground_truth_anomaly (bool), return_type
```

> **P1.5-1 requirement:** The parquet generator must emit `return_type` enum in
> `labels.parquet`. The anomaly detector (P1.5-3) trains on `returns.parquet` joined
> with `order_items.parquet` using `return_type` as the classification target.
> See `system-design.md` §P1.5 parquet layout.

---

## Dataset 3 — Shop Health Proxy

**Purpose:** Train the seller stage classifier to assess overall shop health
from orders, returns, and product metrics — without direct VP/AHR API access.
This dataset is used to build proxy health signals when `health_data_source = 'proxy'`.

**Entities joined:** `Order` + `Return` + `Product`

**Target label:** `health_band` (healthy | at_risk | critical) — derived from
composite proxy metrics. Not stored on canonical entities.

```python
def generate_shop_health_dataset(
    n_shops: int = 100,
    orders_per_shop: int = 300,
) -> dict[str, list[dict]]:
    """
    Returns: {
        "shops": [...],
        "products": [...],
        "orders": [...],
        "returns": [...],
        "labels": [...]     # shop_id -> health_band
    }
    """
    shops_data, products_data, orders_data, returns_data, labels = [], [], [], [], []

    for _ in range(n_shops):
        shop = generate_shop()
        shops_data.append(shop)

        shop_products = [generate_product(shop_id=shop["id"]) for _ in range(10)]
        products_data.extend(shop_products)

        shop_orders = [
            generate_order(shop_id=shop["id"], buyer_id=masked_buyer_id())
            for _ in range(orders_per_shop)
        ]
        orders_data.extend(shop_orders)

        # Generate returns at varying rates to simulate health states
        health_band = random.choices(
            ["healthy", "at_risk", "critical"],
            weights=[0.60, 0.30, 0.10],
            k=1
        )[0]

        # Tune return rate and seller-fault cancel rate by health band
        return_rate = {"healthy": 0.04, "at_risk": 0.09, "critical": 0.18}[health_band]
        seller_fault_rate = {"healthy": 0.01, "at_risk": 0.07, "critical": 0.15}[health_band]

        for order in shop_orders:
            if random.random() < return_rate:
                returns_data.append(
                    generate_return(
                        order=order,
                        ordered_sku_id=f"sku_{uuid.uuid4().hex[:8]}",
                        returned_sku_id=f"sku_{uuid.uuid4().hex[:8]}",
                        return_type=random.choices(
                            ["item_swap", "empty_return", "other"],
                            # At-risk and critical shops see more anomalous returns
                            weights={
                                "healthy": [0.01, 0.01, 0.98],
                                "at_risk": [0.08, 0.05, 0.87],
                                "critical": [0.20, 0.12, 0.68],
                            }[health_band],
                            k=1,
                        )[0],
                        return_condition=random.choice([
                            "wrong_item", "empty_parcel", "correct_item", "unknown"
                        ]),
                    )
                )

            # Simulate seller-fault cancellations
            if order["status"] == "cancelled" and random.random() < seller_fault_rate:
                order["is_seller_fault"] = True  # UNKNOWN in real API; simulated here

        labels.append({
            "shop_id": shop["id"],
            "feature_date": datetime.utcnow().date().isoformat(),
            "health_band": health_band,
            # NOTE: vp_score and ahr_score are NOT included — these are UNKNOWN
            # from the API and must never be fabricated in synthetic data.
        })

    return {
        "shops": shops_data,
        "products": products_data,
        "orders": orders_data,
        "returns": returns_data,
        "labels": labels,
    }
```

**Parquet output layout:**

```
backtest/shop_health/
  shops.parquet
  products.parquet
  orders.parquet
  returns.parquet
  labels.parquet           # shop_id, feature_date, health_band
```

---

## Shared entity generators (pseudocode)

```python
def generate_shop() -> dict:
    return {
        "id": new_id(),
        "tiktok_shop_id": f"shop_{uuid.uuid4().hex[:12]}",
        "shop_cipher": f"cipher_{uuid.uuid4().hex[:16]}",
        "name": f"Shop {uuid.uuid4().hex[:6]}",
        "region": "VN",
        "seller_type": random.choice(["individual", "business"]),
        "created_at": rand_timestamp(30, 730),
        "health_data_source": "proxy",       # Always 'proxy' in synthetic data
        # UNKNOWN fields — always null; never fabricate
        "vp_score": None,
        "ahr_score": None,
        "withholding_active": None,
        "violation_events": None,
        # Proxy signals (computable from orders/products)
        "sfcr_proxy": round(random.uniform(0.0, 0.15), 4),
        "ldr_proxy": round(random.uniform(0.0, 0.10), 4),
        "return_rate_proxy": round(random.uniform(0.01, 0.15), 4),
        "listing_audit_status": rand_status({
            "clean": 0.88, "under_audit": 0.07, "suspended": 0.03, "null": 0.02
        }),
        "settlement_tier": rand_status({
            "standard": 0.60, "accelerated": 0.25, "express": 0.10, "extended": 0.05
        }),
        "settlement_hold_days": None,  # derived from settlement_tier in real code
        "store_rating": round(random.uniform(3.0, 5.0), 1),
        "adjustment_period_complete": random.choice([True, False]),
    }


def generate_order(shop_id: str, buyer_id: str) -> dict:
    status = rand_status({
        "delivered": 0.65, "shipped": 0.10, "confirmed": 0.08,
        "cancelled": 0.10, "returned": 0.07,
    })
    return {
        "id": new_id(),
        "tiktok_order_id": f"ord_{uuid.uuid4().hex[:16]}",
        "shop_id": shop_id,
        "buyer_id": buyer_id,               # already masked
        "status": status,
        "order_value": vnd(random.uniform(50_000, 5_000_000)),
        "currency": "VND",
        "payment_time": rand_timestamp(1, 60) if status != "cancelled" else None,
        "ship_time": rand_timestamp(1, 45) if status in ("shipped", "delivered", "returned") else None,
        "delivery_time": rand_timestamp(1, 30) if status in ("delivered", "returned") else None,
        "created_at": rand_timestamp(1, 90),
        # UNKNOWN fields — null in synthetic data; annotated during shop health sim when needed
        "cancel_reason": None,
        "is_seller_fault": None,
    }


def generate_order_item_for_order(order: dict) -> dict:
    sku_id = f"sku_{uuid.uuid4().hex[:8]}"
    quantity = random.randint(1, 5)
    unit_price = round(random.uniform(50_000, 2_000_000), 2)
    return {
        "id": new_id(),
        "order_id": order["id"],
        "tiktok_order_id": order["tiktok_order_id"],
        "product_id": f"prod_{uuid.uuid4().hex[:12]}",
        "sku_id": sku_id,
        "quantity": quantity,
        "unit_price": vnd(unit_price),
        "line_total": vnd(unit_price * quantity),
    }


def generate_orders_for_product(product_id: str, shop_id: str, n_orders: int, days_window: int) -> list:
    return [
        {
            "id": new_id(),
            "tiktok_order_id": f"ord_{uuid.uuid4().hex[:16]}",
            "shop_id": shop_id,
            "buyer_id": masked_buyer_id(),
            "status": rand_status({"delivered": 0.70, "cancelled": 0.12, "returned": 0.08, "shipped": 0.10}),
            "order_value": vnd(random.uniform(50_000, 3_000_000)),
            "currency": "VND",
            "payment_time": rand_timestamp(1, days_window),
            "ship_time": rand_timestamp(1, days_window - 2),
            "delivery_time": rand_timestamp(1, days_window - 5),
            "created_at": rand_timestamp(1, days_window),
            "cancel_reason": None,
            "is_seller_fault": None,
        }
        for _ in range(n_orders)
    ]


def generate_order_item(order: dict, product: dict) -> dict:
    quantity = random.randint(1, 3)
    unit_price = float(product["price"])
    return {
        "id": new_id(),
        "order_id": order["id"],
        "tiktok_order_id": order["tiktok_order_id"],
        "product_id": product["tiktok_product_id"],
        "sku_id": f"sku_{uuid.uuid4().hex[:8]}",
        "quantity": quantity,
        "unit_price": vnd(unit_price),
        "line_total": vnd(unit_price * quantity),
    }


def generate_creator(shop_id: str) -> dict:
    follower_count = random.randint(100, 500_000)
    tier = "affiliate_creator" if follower_count >= 1000 else "link_share_only"
    commission_rate = round(random.uniform(0.10, 0.50), 2)
    gmv = round(random.uniform(0, 50_000_000), 2)
    return {
        "id": new_id(),
        "tiktok_creator_id": f"creator_{uuid.uuid4().hex[:12]}",
        "shop_id": shop_id,
        "follower_count": follower_count,
        "avg_views": round(random.uniform(500, 200_000), 1),
        "category": random.choice(["Fashion", "Electronics", "FMCG", "Lifestyle"]),
        "commission_rate": commission_rate,
        "collab_type": random.choice(["open", "targeted"]),
        "conversion_rate": round(random.uniform(0.01, 0.15), 4) if tier == "affiliate_creator" else None,
        "gmv_generated": vnd(gmv),
        "creator_tier": tier,
        "kyc_complete": random.choice([True, False]) if True else None,  # VN region only
        "created_at": rand_timestamp(30, 365),
    }


def generate_livestream(creator_id: str, shop_id: str) -> dict:
    start_days_ago = random.randint(1, 30)
    duration_minutes = random.randint(30, 240)
    return {
        "id": new_id(),
        "tiktok_livestream_id": f"live_{uuid.uuid4().hex[:12]}",
        "creator_id": creator_id,
        "shop_id": shop_id,
        "start_time": rand_timestamp(start_days_ago, start_days_ago),
        "end_time": rand_timestamp(start_days_ago - 1, start_days_ago - 1),  # simplified
        "duration_minutes": duration_minutes,
        "viewers": random.randint(100, 50_000),
        "orders": random.randint(0, 500),
        "gmv": vnd(random.uniform(0, 10_000_000)),
        "created_at": rand_timestamp(start_days_ago, start_days_ago),
    }


def generate_settlement(shop_id: str, order_value: str) -> dict:
    amount = float(order_value) * random.uniform(0.85, 0.95)  # after fees
    fee = float(order_value) - amount
    tier = rand_status({"standard": 0.60, "accelerated": 0.25, "express": 0.10, "extended": 0.05})
    hold_days = {"express": 1, "accelerated": 3, "standard": 8, "extended": 15}[tier]
    status = rand_status({"pending": 0.30, "processing": 0.25, "settled": 0.40, "frozen": 0.05})
    return {
        "id": new_id(),
        "tiktok_settlement_id": f"settle_{uuid.uuid4().hex[:12]}",
        "shop_id": shop_id,
        "amount": vnd(amount),
        "currency": "VND",
        "fee_deducted": vnd(fee),
        "net_amount": vnd(amount - fee),
        "status": status,
        "settlement_tier": tier,
        "hold_days": hold_days,
        "settle_date": rand_timestamp(0, 30),
        "period_start": rand_timestamp(30, 60),
        "period_end": rand_timestamp(1, 30),
        "created_at": rand_timestamp(1, 30),
    }
```

---

## Saving to parquet

```python
import pandas as pd

def save_dataset(dataset: dict[str, list[dict]], output_dir: str) -> None:
    """
    Saves each entity list as a Parquet file.
    Preserves Decimal precision by converting to string first —
    downstream pandas/pyarrow code should read monetary columns as string
    then convert to Decimal for arithmetic.
    """
    import os
    os.makedirs(output_dir, exist_ok=True)
    for entity_name, records in dataset.items():
        if not records:
            continue
        df = pd.DataFrame(records)
        path = os.path.join(output_dir, f"{entity_name}.parquet")
        df.to_parquet(path, index=False, engine="pyarrow")
        print(f"Wrote {len(records)} rows to {path}")
```

**Example usage:**

```python
# Generate the Revenue Leakage detection dataset for P1.5 training
dataset = generate_leakage_dataset(n_shops=30, orders_per_shop=500)
save_dataset(dataset, "backtest/revenue_leakage/")

# Verify label distribution
labels_df = pd.read_parquet("backtest/revenue_leakage/labels.parquet")
print(labels_df["return_type"].value_counts(normalize=True))
# Expected:  other ~90–95%,  item_swap ~3–4%,  empty_return ~1–3%
```

---

## Validation checklist (before committing a dataset to backtest/)

- [ ] All `buyer_id` values are masked (`buyer_XXXXXX` format) — no real PII
- [ ] `vp_score`, `ahr_score`, `withholding_active` are `null` in all shop records
- [ ] Every `Return` record has a parent `Order` with a matching `OrderItem`
- [ ] `return_type` label distribution is realistic (anomaly < 10% of returns)
- [ ] `Numeric(18,2)` monetary fields are stored as strings (not floats) in parquet
- [ ] `sku_id` in `Return` differs from `OrderItem.sku_id` for all `item_swap` records
- [ ] `return_condition = 'empty_parcel'` for all `empty_return` records
- [ ] Column names match `system-design.md` §P1.5 parquet layout exactly
