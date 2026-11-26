"""Owner #99 item 6: the exclusions screens read Tổng quan's ``kpi_strip.gmv``; it is the same
field as the Tổng quan headline (``shop_metrics.gmv``, the stored daily rows), never the raw
window total (``PeriodView.shop_gmv``: Shopee's period-file / raw daily total), which can differ
when a period file stands in for the window. Synthetic data only."""

from __future__ import annotations

from decimal import Decimal

from juli_backend.services.shopee_analytics import materialize, queries
from juli_backend.services.shopee_analytics.overview import build_overview
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop


async def test_kpi_strip_gmv_is_the_headline_gmv_even_when_the_raw_total_differs(session):
    seeded = await seed_shopee_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    ctx, now, before = await queries._views(
        session, seeded.shop_id, period="7d", month=None, start=None, end=None, as_of=CUR_END
    )
    headline_gmv, headline_orders = now.metrics.gmv, now.metrics.orders
    assert headline_gmv and headline_orders
    # the fixture case: the raw window total says something else (a period file's whole total)
    now.shop_gmv = headline_gmv * Decimal("2.18")
    now.shop_orders = headline_orders * 2
    body = build_overview(ctx, now, before)
    sm, strip = body["shop_metrics"], body["kpi_strip"]
    assert strip["gmv"]["value"] == sm["gmv"] == float(headline_gmv)
    assert strip["orders"]["value"] == sm["orders"] == headline_orders
    assert body["gmv"]["shopee_gmv"] == sm["gmv"]
    assert body["gmv"]["shopee_orders"] == sm["orders"]
    assert strip["gmv"]["previous"] == before.metrics.gmv
