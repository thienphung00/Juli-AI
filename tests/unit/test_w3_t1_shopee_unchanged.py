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

#: sha256 of the rows on the base commit (866ba281).
BASE_DIGEST = "07cd6d48bf3ff5b42347fbe2cc79de1a6aafa230660d331c250473c1f652a2d7"
_SKIP = {"id", "shop_id", "built_at"}


def _plain(row) -> dict:
    out = {}
    for col in type(row).__table__.columns:
        if col.name in _SKIP:
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
