"""W3 t1 (M-2): the TikTok layer-4 work leaves every Shopee row byte-identical.

The digest below was taken from the synthetic Shopee shop (``tests.support.shopee_analytics``)
on the base commit, before any W3 change: every shop / product / source column the rebuild
writes, except the row id and ``built_at``. A W3 change that moves one Shopee number fails here.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from juli_backend.models.shopee_metrics import (
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.services.shopee_analytics import materialize
from tests.support.shopee_analytics import seed_shopee_shop

#: sha256 of the rows on the base commit (866ba281) was 07cd6d48…652a2d7. Re-pinned on
#: batch-1124-a for owner decisions #39 (one product ad cost: a product-day with ad spend and no
#: sale now gets its own order_lines row, profit = -ad cost; 8 such rows in the fixture) and
#: #39/#50 (ROWS_VERSION 2 -> 4 in every shop row's ``detail.rows_v``). Every other row and
#: every source row is unchanged against 3ff94165.
#: Re-pinned on batch-1125 r1-dec (owner #103, 8a): the day 2026-10-05 holds only cancelled-after-
#: confirmation lines, so product 1002 now has gmv / orders / units / line_gmv / line_orders = 0 and
#: its 275.000 GMV sits in that day's ``__residual__`` row (the shop row is unchanged). Nothing else
#: moved (dump diff against the base, all three tables).
#: Re-pinned again (owners #99 / #103, 10a + 4a): ROWS_VERSION 4 -> 5 (every shop row's
#: ``detail.rows_v``) and the day 2026-10-05 gains ``detail.cancelled_gmv`` = 275000 /
#: ``cancelled_orders`` = 1. Dump diff against the previous pin: only those ``detail`` values.
BASE_DIGEST = "4ffcffa5dfb8b2c99a2e39b4804daca07da443509db4b5cde0dd23e98539f7c7"
_SKIP = {"id", "shop_id", "built_at"}
#: the columns migration 140 added, which nothing writes since #2367 was taken out: they must be
#: empty, and the digest of every other column is the one from before it
_UNWRITTEN_140 = {
    "ShopeeShopMetricsDaily": frozenset(
        {
            "ads_clicks",
            "ads_gmv_confirmed",
            "ads_gmv_direct",
            "ads_orders",
            "ads_spend_known",
            "ads_views",
            "affiliate_commission",
            "affiliate_commission_known",
            "affiliate_gmv",
            "cogs",
            "cogs_known_gmv",
            "derivation_version",
            "fees",
            "net_revenue",
            "net_revenue_known",
            "offer_combo",
            "offer_promo",
            "offer_voucher",
            "other_marketing",
            "packaging",
            "shipping_net",
        }
    ),
    "ShopeeProductMetricsDaily": frozenset(
        {
            "ads_clicks",
            "ads_gmv",
            "ads_gmv_confirmed",
            "ads_gmv_direct",
            "ads_orders",
            "ads_spend_known",
            "ads_views",
            "affiliate_commission",
            "affiliate_commission_known",
            "affiliate_gmv",
            "cogs",
            "cogs_known_gmv",
            "derivation_version",
            "fees",
            "net_revenue",
            "net_revenue_known",
            "offer_combo",
            "offer_promo",
            "offer_voucher",
            "packaging",
            "shipping_net",
        }
    ),
    "ShopeeSourceMetricsDaily": frozenset({"derivation_version"}),
}


def _plain(row) -> dict:
    out = {}
    for col in type(row).__table__.columns:
        if col.name in _SKIP:
            continue
        if col.name in _UNWRITTEN_140[type(row).__name__]:
            assert getattr(row, col.name) is None, col.name
            continue
        out[col.name] = getattr(row, col.name)
    return out


async def rows_digest(session, shop_id) -> str:
    parts = []
    for model, order in (
        (ShopeeShopMetricsDaily, (ShopeeShopMetricsDaily.day,)),
        (
            ShopeeProductMetricsDaily,
            (ShopeeProductMetricsDaily.day, ShopeeProductMetricsDaily.item_id),
        ),
        (
            ShopeeSourceMetricsDaily,
            (
                ShopeeSourceMetricsDaily.day,
                ShopeeSourceMetricsDaily.item_id,
                ShopeeSourceMetricsDaily.source,
            ),
        ),
    ):
        rows = (
            await session.execute(select(model).where(model.shop_id == shop_id).order_by(*order))
        ).scalars()
        parts.append([_plain(r) for r in rows])
    blob = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def test_the_shopee_fixture_rows_are_byte_identical_to_the_base(session):
    seeded = await seed_shopee_shop(session, materialized=False)
    report = await materialize.backfill_shop(session, seeded.shop_id)
    assert report.days_written > 0
    assert await rows_digest(session, seeded.shop_id) == BASE_DIGEST
