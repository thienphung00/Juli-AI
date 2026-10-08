"""Synthetic shop snapshots for the shop diagnosis report (ADR-108).

Never real shop data: every row is generated here, shaped like the A-34 daily
rows the fetch saves (one block per channel, Shop Tab with its ``shop_tab_*``
keys, the total equal to the sum of the four additive channels — the identity
measured on live data).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ZONE = timezone(timedelta(hours=7))
END = date(2026, 10, 6)


@dataclass(frozen=True)
class Block:
    """One channel's counts for one product-day."""

    impressions: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    orders: int = 0
    gmv: int = 0


@dataclass(frozen=True)
class TabBlock:
    impressions: int = 0
    clicks: int = 0
    #: SKU orders ÷ clicks, as TikTok reports it for the Shop Tab.
    ctor: str = "0"
    gmv: int = 0


@dataclass(frozen=True)
class DayRow:
    product_id: str
    card: Block = field(default_factory=Block)
    tab: TabBlock = field(default_factory=TabBlock)
    seller_video: Block = field(default_factory=Block)
    seller_live: Block = field(default_factory=Block)
    affiliate_video: Block = field(default_factory=Block)
    affiliate_live: Block = field(default_factory=Block)
    refunds: int = 0


def _money(value: float) -> dict[str, str]:
    return {"amount": f"{value:.2f}", "currency": "VND"}


def _seller_block(b: Block) -> dict[str, Any]:
    return {
        "product_impressions": b.impressions,
        "product_clicks": b.clicks,
        "add_cart_count": b.add_to_cart,
        "attributed_sku_orders": b.orders,
        "attributed_orders": b.orders,
        "attributed_gmv": _money(b.gmv),
        # Decoys the reader must never sum.
        "unique_product_impressions": b.impressions * 7,
        "unique_clicks": b.clicks * 7,
        "ctr": "0.9999",
    }


def a34_row(row: DayRow) -> dict[str, Any]:
    """One A-34 product row; affiliate total = its video + LIVE branches."""
    aff = Block(
        row.affiliate_video.impressions + row.affiliate_live.impressions,
        row.affiliate_video.clicks + row.affiliate_live.clicks,
        row.affiliate_video.add_to_cart + row.affiliate_live.add_to_cart,
        row.affiliate_video.orders + row.affiliate_live.orders,
        row.affiliate_video.gmv + row.affiliate_live.gmv,
    )
    additive = (row.card, row.seller_video, row.seller_live, aff)
    orders = sum(b.orders for b in additive)
    return {
        "id": row.product_id,
        "seller_product_card_performance": _seller_block(row.card),
        "seller_video_performance": _seller_block(row.seller_video),
        "seller_live_performance": _seller_block(row.seller_live),
        "affiliate_total_performance": _seller_block(aff),
        "affiliate_video_performance": {
            "product_impressions": row.affiliate_video.impressions,
            "product_clicks": row.affiliate_video.clicks,
            "add_cart_count": row.affiliate_video.add_to_cart,
            "attributed_video_gmv": _money(row.affiliate_video.gmv),
        },
        "affiliate_live_performance": {
            "product_impressions": row.affiliate_live.impressions,
            "product_clicks": row.affiliate_live.clicks,
            "add_cart_count": row.affiliate_live.add_to_cart,
            "live_attributed_gmv": _money(row.affiliate_live.gmv),
        },
        "shop_tab_performance": {
            "shop_tab_product_impressions": row.tab.impressions,
            "shop_tab_product_clicks": row.tab.clicks,
            "shop_tab_ctor_sku": row.tab.ctor,
            "shop_tab_gmv": _money(row.tab.gmv),
            "shop_tab_ctr": "0.0100",
            "unique_shop_tab_product_clicks": row.tab.clicks * 7,
        },
        "total_performance": {
            "product_impressions": sum(b.impressions for b in additive),
            "product_clicks": sum(b.clicks for b in additive),
            "add_cart_count": sum(b.add_to_cart for b in additive),
            "sku_orders": orders,
            "orders": orders,
            "items_sold": orders,
            "gmv": _money(sum(b.gmv for b in additive)),
            "refunds": _money(row.refunds),
            "unique_product_impressions": 1,
        },
    }


def window_days(end: date = END, days: int = 60) -> list[date]:
    return [end - timedelta(days=days - 1 - i) for i in range(days)]


def seconds(day: date, hour: int = 0) -> int:
    return int(datetime(day.year, day.month, day.day, hour, tzinfo=ZONE).timestamp())


def order(order_id: str, day: date, product_ids: list[str], value: float) -> dict[str, Any]:
    """A kept order created at noon on ``day`` with one line per product id."""
    share = value / max(len(product_ids), 1)
    return {
        "id": order_id,
        "create_time": seconds(day, 12),
        "status": "COMPLETED",
        "payment": {"sub_total": f"{value:.0f}"},
        "line_items": [
            {
                "product_id": pid,
                "sale_price": f"{share:.0f}",
                "platform_discount": "1000" if i % 2 == 0 else "0",
                "seller_discount": "2000",
                "is_gift": False,
            }
            for i, pid in enumerate(product_ids)
        ],
    }


def write_snapshot(
    folder: Path,
    daily: dict[date, list[DayRow]],
    *,
    shop_name: str = "Shop Thử Nghiệm",
    end: date = END,
    orders: list[dict] | None = None,
    activities: list[dict] | None = None,
    details: dict[str, dict] | None = None,
    coupons: list[dict] | None = None,
    products: dict[str, dict] | None = None,
) -> Path:
    """Write the snapshot layout ``load_snapshot`` reads."""

    def dump(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    dump(folder / "meta.json", {"shop_name": shop_name, "end": end.isoformat(), "days": 60})
    for day, rows in daily.items():
        dump(
            folder / "daily" / f"a34_{day.isoformat()}.json",
            {"day": day.isoformat(), "products": [a34_row(r) for r in rows]},
        )
    if orders is not None:
        dump(folder / "orders.json", {"orders": orders})
    dump(folder / "promotions" / "activities.json", {"activities": activities or []})
    dump(folder / "promotions" / "activity_details.json", details or {})
    dump(folder / "promotions" / "coupons.json", {"coupons": coupons or []})
    for pid, detail in (products or {}).items():
        dump(folder / "products" / f"{pid}.json", {"data": detail})
    return folder
