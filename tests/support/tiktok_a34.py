"""A synthetic A-34 list row (``GET /analytics/202605/shop_products/performance``), W3 t1.

Same block and field names as the real 202605 response (checked against a stored daily capture
and ``services/shop_diagnosis/channels.py``); every number is invented. The four sources
(product card, seller video, seller LIVE, affiliate) add up to ``total_performance`` exactly, as
TikTok's do; the shop tab overlaps them.
"""

from __future__ import annotations

from typing import Any


def _money(amount: int) -> dict[str, str]:
    return {"amount": f"{amount}", "currency": "VND"}


def _source(impressions: int, clicks: int, orders: int, gmv: int, *, cart: int = 0) -> dict:
    return {
        "product_impressions": impressions,
        "product_clicks": clicks,
        "add_cart_count": cart,
        "attributed_orders": orders,
        "attributed_sku_orders": orders,
        "attributed_sold_items": orders,
        "attributed_gmv": _money(gmv),
        "ctr": "0.05",
        "click_order_rate": "0.10",
        "unique_clicks": clicks,
        "unique_product_impressions": impressions,
    }


def a34_row(
    product_id: str,
    *,
    card: tuple[int, int, int, int] = (1000, 50, 2, 200_000),
    video: tuple[int, int, int, int] = (400, 20, 1, 100_000),
    live: tuple[int, int, int, int] = (0, 0, 0, 0),
    affiliate: tuple[int, int, int, int] = (600, 30, 1, 150_000),
    shop_tab: tuple[int, int, int] = (300, 15, 120_000),
) -> dict[str, Any]:
    """One product's A-34 list row; each tuple is (impressions, clicks, orders, gmv)."""
    parts = (card, video, live, affiliate)
    total = tuple(sum(p[i] for p in parts) for i in range(4))
    tab_impressions, tab_clicks, tab_gmv = shop_tab
    return {
        "id": product_id,
        "seller_product_card_performance": _source(*card, cart=3),
        "seller_video_performance": _source(*video),
        "seller_live_performance": _source(*live),
        "affiliate_total_performance": _source(*affiliate),
        "affiliate_video_performance": {
            "product_impressions": affiliate[0],
            "product_clicks": affiliate[1],
            "add_cart_count": 0,
            "attributed_video_gmv": _money(affiliate[3]),
            "unique_clicks": affiliate[1],
        },
        "affiliate_live_performance": {
            "product_impressions": 0,
            "product_clicks": 0,
            "add_cart_count": 0,
            "live_attributed_gmv": _money(0),
        },
        "shop_tab_performance": {
            "shop_tab_product_impressions": tab_impressions,
            "shop_tab_product_clicks": tab_clicks,
            "shop_tab_gmv": _money(tab_gmv),
            "shop_tab_ctor_sku": "0.10",
            "shop_tab_sold_items": 1,
            "unique_shop_tab_product_clicks": tab_clicks,
        },
        "total_performance": {
            "product_impressions": total[0],
            "product_clicks": total[1],
            "add_cart_count": 3,
            "orders": total[2],
            "sku_orders": total[2],
            "items_sold": total[2],
            "gmv": _money(total[3]),
            "ctr": "0.05",
            "click_order_rate": "0.10",
            "estimated_customers": total[2],
            "unique_clicks": total[1],
        },
    }
