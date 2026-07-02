"""Synthetic backtest data generator — no TikTok API, no PII."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any


ANOMALY_BASE_RATE = 0.05
ITEM_SWAP_RATIO = 0.60
REPEAT_BUYER_RATE = 0.15


def masked_buyer_id() -> str:
    return f"buyer_{uuid.uuid4().hex[:6]}"


def vnd(amount: float) -> str:
    return str(Decimal(str(amount)).quantize(Decimal("0.01")))


def rand_timestamp(rng: random.Random, days_ago_min: int, days_ago_max: int) -> str:
    delta = rng.randint(days_ago_min * 86400, days_ago_max * 86400)
    return (datetime.now(UTC) - timedelta(seconds=delta)).isoformat().replace("+00:00", "Z")


def rand_status(rng: random.Random, weights: dict[str, float]) -> str:
    choices = list(weights.keys())
    probabilities = list(weights.values())
    return rng.choices(choices, weights=probabilities, k=1)[0]


def generate_shop(rng: random.Random) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tiktok_shop_id": f"shop_{uuid.uuid4().hex[:12]}",
        "name": f"Shop {uuid.uuid4().hex[:6]}",
        "region": "VN",
    }


def generate_order(
    rng: random.Random,
    shop_id: str,
    buyer_id: str,
    days_window: int = 90,
) -> dict[str, Any]:
    status = rand_status(
        rng,
        {
            "delivered": 0.65,
            "shipped": 0.10,
            "confirmed": 0.08,
            "cancelled": 0.10,
            "returned": 0.07,
        },
    )
    return {
        "id": str(uuid.uuid4()),
        "tiktok_order_id": f"ord_{uuid.uuid4().hex[:16]}",
        "shop_id": shop_id,
        "buyer_id": buyer_id,
        "status": status,
        "order_value": vnd(rng.uniform(50_000, 5_000_000)),
        "currency": "VND",
        "payment_time": rand_timestamp(rng, 1, days_window)
        if status != "cancelled"
        else None,
        "ship_time": rand_timestamp(rng, 1, max(2, days_window - 2))
        if status in ("shipped", "delivered", "returned")
        else None,
        "delivery_time": rand_timestamp(rng, 1, max(2, days_window - 5))
        if status in ("delivered", "returned")
        else None,
        "created_at": rand_timestamp(rng, 1, days_window),
        "cancel_reason": None,
        "is_seller_fault": None,
    }


def generate_order_item(rng: random.Random, order: dict[str, Any]) -> dict[str, Any]:
    sku_id = f"sku_{uuid.uuid4().hex[:8]}"
    quantity = rng.randint(1, 5)
    unit_price = round(rng.uniform(50_000, 2_000_000), 2)
    return {
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "tiktok_order_id": order["tiktok_order_id"],
        "product_id": f"prod_{uuid.uuid4().hex[:12]}",
        "sku_id": sku_id,
        "quantity": quantity,
        "unit_price": vnd(unit_price),
        "line_total": vnd(unit_price * quantity),
    }


def generate_return(
    rng: random.Random,
    order: dict[str, Any],
    returned_sku_id: str,
    return_type: str,
    return_condition: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "tiktok_return_id": f"ret_{uuid.uuid4().hex[:12]}",
        "order_id": order["id"],
        "tiktok_order_id": order["tiktok_order_id"],
        "shop_id": order["shop_id"],
        "buyer_id": order["buyer_id"],
        "product_id": f"prod_{uuid.uuid4().hex[:12]}",
        "sku_id": returned_sku_id,
        "return_type": return_type,
        "return_condition": return_condition,
        "return_reason": rng.choice(
            [
                "wrong item received",
                "empty package",
                "changed mind",
                "size doesn't fit",
                "product defective",
            ]
        ),
        "refund_amount": vnd(float(order["order_value"]) * rng.uniform(0.5, 1.0)),
        "status": rand_status(
            rng,
            {"approved": 0.75, "pending_review": 0.15, "rejected": 0.10},
        ),
        "created_at": rand_timestamp(rng, 0, 30),
    }


def generate_ads(
    rng: random.Random,
    shops: list[dict[str, Any]],
    days: int = 30,
    campaigns_per_shop: int = 3,
) -> list[dict[str, Any]]:
    ads: list[dict[str, Any]] = []
    for shop in shops:
        for campaign_idx in range(campaigns_per_shop):
            campaign_id = f"camp_{uuid.uuid4().hex[:10]}"
            campaign_name = f"Campaign {campaign_idx + 1} — {shop['name']}"
            base_roas = rng.uniform(0.8, 5.0)
            for day_offset in range(days):
                spend = rng.uniform(100_000, 5_000_000)
                clicks = rng.randint(10, 500)
                conversions = rng.randint(0, max(1, clicks // 5))
                impressions = clicks * rng.randint(5, 20)
                roas = round(base_roas * rng.uniform(0.7, 1.3), 2)
                cpc = spend / clicks if clicks else 0.0
                ads.append(
                    {
                        "shop_id": shop["id"],
                        "campaign_id": campaign_id,
                        "campaign_name": campaign_name,
                        "date": (
                            datetime.now(UTC).date() - timedelta(days=day_offset)
                        ).isoformat(),
                        "spend_vnd": vnd(spend),
                        "impressions": impressions,
                        "clicks": clicks,
                        "conversions": conversions,
                        "roas": roas,
                        "cpc_vnd": vnd(cpc),
                    }
                )
    return ads


def generate_synthetic_dataset(
    *,
    seed: int,
    n_shops: int = 5,
    orders_per_shop: int = 100,
    return_rate: float = 0.08,
    ads_days: int = 30,
) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    shops = [generate_shop(rng) for _ in range(n_shops)]
    orders: list[dict[str, Any]] = []
    order_items: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    buyer_pool = [masked_buyer_id() for _ in range(max(20, n_shops * 10))]
    anomalous_buyers = set(
        rng.sample(buyer_pool, k=max(1, int(len(buyer_pool) * REPEAT_BUYER_RATE)))
    )

    for shop in shops:
        for _ in range(orders_per_shop):
            buyer_id = rng.choice(buyer_pool)
            order = generate_order(rng, shop_id=shop["id"], buyer_id=buyer_id)
            orders.append(order)

            item = generate_order_item(rng, order)
            order_items.append(item)

            if rng.random() >= return_rate:
                continue

            is_anomalous_buyer = buyer_id in anomalous_buyers
            anomaly_probability = ANOMALY_BASE_RATE * 3 if is_anomalous_buyer else ANOMALY_BASE_RATE
            is_anomaly = rng.random() < anomaly_probability

            if is_anomaly:
                if rng.random() < ITEM_SWAP_RATIO:
                    return_type = "item_swap"
                    returned_sku_id = f"sku_{uuid.uuid4().hex[:8]}"
                    return_condition = "wrong_item"
                else:
                    return_type = "empty_return"
                    returned_sku_id = item["sku_id"]
                    return_condition = "empty_parcel"
            else:
                return_type = "other"
                returned_sku_id = item["sku_id"]
                return_condition = "correct_item"

            ret = generate_return(
                rng,
                order=order,
                returned_sku_id=returned_sku_id,
                return_type=return_type,
                return_condition=return_condition,
            )
            returns.append(ret)
            labels.append(
                {
                    "return_id": ret["id"],
                    "ground_truth_anomaly": return_type in ("item_swap", "empty_return"),
                    "return_type": return_type,
                }
            )

    ads = generate_ads(rng, shops, days=ads_days)

    return {
        "orders": orders,
        "order_items": order_items,
        "returns": returns,
        "labels": labels,
        "ads": ads,
    }
