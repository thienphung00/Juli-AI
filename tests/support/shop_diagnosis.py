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


#: Buyer-level values planted in the fake orders; a stored report must never contain them.
BUYER_MARKERS = ("buyer-marker@example.invalid", "Người Mua Bí Mật")


def synthetic_rows(day: date, products: int = 6) -> list[DayRow]:
    """A stable synthetic catalogue for one day (no randomness)."""
    return [
        DayRow(
            f"p{n}",
            card=Block(400 + 10 * n, 40 + n, 8, 2 + n % 3, 150_000 * (n + 1)),
            tab=TabBlock(50, 5, "0.2", 20_000),
            seller_video=Block(200, 10, 2, 1, 90_000),
            affiliate_video=Block(300, 12, 3, 1, 80_000),
        )
        for n in range(products)
    ]


class FakeTikTokReadResources:
    """Production-read resources shaped like the guarded client, for the daily job.

    Records every call in ``calls``; only read methods exist. ``fail_a34`` makes
    the A-34 list raise, to prove a failed build stores nothing. ``videos`` lists
    that many seller videos (posted long before both windows, GMV descending)
    in every video list, with per-day details over any range (P8-B's windows);
    ``video_error`` makes every video list and details call raise.
    """

    def __init__(
        self,
        *,
        end: date = END,
        fail_a34: bool = False,
        videos: int = 0,
        video_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple] = []
        self.end = end
        self.fail_a34 = fail_a34
        outer = self
        listed = [
            {
                "id": f"v{n}",
                "title": f"Video {n}",
                "video_post_time": "2025-01-01 10:00:00",
                "gmv": _money(1_000_000 - n),
                "sku_orders": 5,
                "views": 1_000,
                "items_sold": 5,
            }
            for n in range(videos)
        ]

        class Analytics:
            def list_product_performance_all(self, *, start_date_ge: str, end_date_lt: str):
                outer.calls.append(("a34", start_date_ge))
                if outer.fail_a34:
                    raise RuntimeError("analytics unavailable")
                return [a34_row(r) for r in synthetic_rows(date.fromisoformat(start_date_ge))]

            def list_live_performance_all(self, **_kwargs: str):
                outer.calls.append(("live",))
                return []

            def get_live_products_performance(self, **_kwargs: str):
                raise AssertionError("no LIVE was listed")

            def list_video_performance_all(self, **kwargs: str):
                outer.calls.append(("videos", kwargs.get("start_date_ge")))
                if video_error is not None:
                    raise video_error
                return listed

            def get_video_products_performance(self, **kwargs: str):
                if not listed:
                    raise AssertionError("no video was listed")
                outer.calls.append(("video_products", kwargs["video_id"]))
                return {"data": {"products": []}}

            def get_video_performance(self, **kwargs: str):
                outer.calls.append(("video_details", kwargs["video_id"]))
                if video_error is not None:
                    raise video_error
                first = date.fromisoformat(kwargs["start_date_ge"])
                stop = date.fromisoformat(kwargs["end_date_lt"])
                n = int(kwargs["video_id"].removeprefix("v"))
                intervals = [
                    {
                        "start_date": (first + timedelta(days=i)).isoformat(),
                        "end_date": (first + timedelta(days=i + 1)).isoformat(),
                        "sales": {
                            "overall": {
                                "product_impressions": 2_000 + 100 * n + 10 * i,
                                "product_clicks": 40 + n + i % 7,
                                "gmv": _money(30_000 + 1_000 * i),
                                "items_sold": 1,
                            }
                        },
                        "traffic": {"views": 500},
                    }
                    for i in range((stop - first).days)
                ]
                return {"data": {"performance": {"intervals": intervals}}}

        class Orders:
            def search_all(self, *, create_time_from: int, create_time_to: int):
                outer.calls.append(("orders", create_time_from))
                day = datetime.fromtimestamp(create_time_from, ZONE).date()
                placed = order(f"o-{day.isoformat()}", day, ["p0", "p1"], 300_000)
                placed["buyer_email"] = BUYER_MARKERS[0]
                placed["recipient_address"] = {"name": BUYER_MARKERS[1]}
                return [placed]

        class Promotion:
            def search_activities_all(self, *, status: str):
                outer.calls.append(("activities", status))
                return []

            def search_coupons_all(self):
                outer.calls.append(("coupons",))
                return []

            def get_activity(self, activity_id: str):
                raise AssertionError("no activity was listed")

        class Products:
            def get_details(self, product_id: str):
                outer.calls.append(("product", product_id))
                return {"data": {"id": product_id, "title": f"Sản phẩm {product_id}"}}

        self.analytics = Analytics()
        self.orders = Orders()
        self.promotion = Promotion()
        self.products = Products()
