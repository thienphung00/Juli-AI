"""Juli Ops Shopee dashboards on real Postgres, as ``juli_app`` under RLS (ADR-117 step 4).

The queries use ``date_trunc`` / ``jsonb_typeof`` and read five tenant tables; they must
return the same numbers through the app role with the shop's scope set, never see another
shop's rows, and keep the G3 rule (a child flow is never added to a total) end to end.

Synthetic rows only; the rows belong to throwaway contract shops on the shared database.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.api.routes import ops_shopee_dashboards as routes
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import (
    PlatformItem,
    PlatformPeriodMetric,
    PlatformProductFlag,
    PlatformPromotion,
)
from juli_backend.services.ops import contract_shops
from juli_backend.services.ops import shopee_dashboards as dash
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime.now(UTC).replace(tzinfo=None)
DAY0 = date(2026, 10, 1)


@asynccontextmanager
async def app_session():
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _source(*, confidence=False, **values):
    return {
        "platform": "shopee",
        **({"confidence": "high"} if confidence else {}),
        "source": "file",
        "source_rank": 1,
        "source_version": "test",
        "captured_at": NOW,
        "updated_at": NOW,
        **values,
    }


def _daily(
    shop_id,
    day,
    stream,
    segment,
    *,
    gmv,
    orders,
    cost=None,
    dataset="traffic_overview",
    ot="confirmed",
):
    extra = {"ads_expense": cost} if cost is not None else {}
    return PlatformDailyMetric(
        shop_id=shop_id,
        dataset=dataset,
        day=day,
        stream=stream,
        segment=segment,
        order_type=ot,
        gmv=Decimal(gmv),
        orders=Decimal(orders),
        extra=extra,
        **_source(confidence=True),
    )


def _period(shop_id, item, start, end, *, dataset="product_period", stream="total", **metrics):
    return PlatformPeriodMetric(
        shop_id=shop_id,
        dataset=dataset,
        period_start=start,
        period_end=end,
        item_id=item,
        variation_id="",
        stream=stream,
        segment="all",
        order_type="confirmed",
        extra={},
        **{k: Decimal(v) for k, v in metrics.items()},
        **_source(confidence=True),
    )


async def _seed(session, shop_id):
    for i in range(6):
        day = DAY0 + timedelta(days=i)
        session.add_all(
            [
                _daily(shop_id, day, "product_card", "all", gmv=1000, orders=10),
                _daily(shop_id, day, "product_card", "shop_page", gmv=300, orders=3),
                _daily(shop_id, day, "seller_video", "all", gmv=200, orders=2),
                # the ads section counts placed orders; the confirmed copy feeds the flow overlay
                _daily(
                    shop_id, day, "ads", "ads_auto_bid", gmv=120, orders=2, cost=100, ot="placed"
                ),
                _daily(shop_id, day, "ads", "ads_shop", gmv=900, orders=9, cost=100, ot="placed"),
                _daily(shop_id, day, "ads", "ads_shop", gmv=80, orders=1, cost=100),
                _daily(shop_id, day, "total", "all", gmv=1200, orders=12, dataset="shop_overview"),
            ]
        )
    # August: only a monthly period row exists, the rest of the history comes from the days.
    session.add(
        _period(
            shop_id,
            "",
            date(2026, 8, 1),
            date(2026, 8, 31),
            dataset="traffic_overview_period",
            stream="product_card",
            gmv=5000,
            orders=50,
        )
    )
    # Jan-Sep history that came as monthly roll-ups (P90 step 6): the shop-level month.
    session.add(
        _period(
            shop_id,
            "",
            date(2026, 8, 1),
            date(2026, 8, 31),
            dataset="shop_overview_period",
            gmv=9000,
            orders=90,
        )
    )
    session.add(
        PlatformItem(
            shop_id=shop_id, item_id="111", variation_id="", name="Synthetic item", **_source()
        )
    )
    for item, gmv in (("111", 800), ("222", 200)):
        session.add(
            _period(
                shop_id,
                item,
                date(2026, 9, 29),
                date(2026, 10, 28),
                impressions=1000,
                clicks=50,
                visitors=40,
                add_to_cart=10,
                orders=5,
                gmv=gmv,
            )
        )
        session.add(
            _period(shop_id, item, date(2026, 10, 1), date(2026, 10, 28), gmv=gmv, orders=5)
        )
    session.add(
        _period(
            shop_id,
            "111",
            date(2026, 9, 29),
            date(2026, 10, 28),
            dataset="item_by_source_period",
            stream="product_card",
            gmv=600,
            orders=4,
        )
    )
    session.add(
        PlatformProductFlag(
            shop_id=shop_id,
            item_id="111",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 28),
            flag="ads_optimize",
            extra={},
            **_source(),
        )
    )
    session.add(
        PlatformPromotion(
            shop_id=shop_id,
            promo_type="discount",
            program_name="Synthetic sale",
            starts_at=datetime(2026, 10, 2),
            ends_at=datetime(2026, 10, 5),
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 28),
            order_type="confirmed",
            gmv=Decimal(700),
            orders=Decimal(7),
            extra={},
            **_source(),
        )
    )
    await session.flush()


async def _make_shop(session):
    shop = await contract_shops.create_contract_shop(
        session, shop_name=f"Synthetic {uuid.uuid4().hex[:6]}", shopee_shop_id=None, now=NOW
    )
    await session.commit()
    return shop.id


async def test_dashboards_aggregate_under_rls_and_keep_children_out_of_totals():
    async with app_session() as session:
        mine = await _make_shop(session)
        other = await _make_shop(session)
        async with with_shop_scope(session, mine):
            await _seed(session, mine)
            await session.commit()
        async with with_shop_scope(session, other):
            await _seed(session, other)
            session.add(_daily(other, DAY0, "seller_live", "all", gmv=7777, orders=1))
            await session.commit()

        window = dash.DateRange(DAY0, DAY0 + timedelta(days=5))
        async with with_shop_scope(session, mine):
            flows = await dash.flows(session, mine, window)
            ads = await dash.ads(session, mine, window)
            products = await dash.products(session, mine)
            promos = await dash.promotions(session, mine, window)
            await session.commit()

    # Flows: 6 days x (1000 card + 200 video); Trang shop (300/day) is a child only.
    assert flows["total_gmv"] == 7200
    card = next(f for f in flows["flows"] if f["stream"] == "product_card")
    assert card["gmv"] == 6000
    assert [(c["segment"], c["gmv"]) for c in card["children"]] == [("shop_page", 1800)]
    assert [f["stream"] for f in flows["flows"]] == ["product_card", "seller_video"]  # no 7777 live
    assert flows["ads_overlay"]["in_total"] is False
    months = {m["month"]: m for m in flows["monthly"]}
    assert months["2026-08-01"]["streams"]["product_card"] == 5000  # period row fills the month
    assert months["2026-10-01"]["streams"]["product_card"] == 6000
    assert months["2026-10-01"]["shop_page_gmv"] == 1800
    assert flows["shop_monthly"][-1] == {"month": "2026-10-01", "gmv": 7200, "orders": 72}
    # the month with only a roll-up shows, and a month with day rows is not added to it
    assert flows["shop_monthly"][0] == {"month": "2026-08-01", "gmv": 9000, "orders": 90}
    assert [m["month"] for m in flows["shop_monthly"]] == ["2026-08-01", "2026-10-01"]

    # Ads: per type and total; auto bid is at ROAS 1.2 for 6 straight days -> alert.
    by_type = {t["ad_type"]: t for t in ads["by_type"]}
    assert by_type["ads_auto_bid"]["cost"] == 600 and by_type["ads_auto_bid"]["roas"] == 1.2
    assert by_type["ads_shop"]["roas"] == 9.0 and by_type["ads_shop"][
        "cost_per_order"
    ] == pytest.approx(11.1111, abs=1e-3)
    assert ads["total"]["cost"] == 1200 and ads["total"]["roas"] == 5.1
    assert [a["ad_type"] for a in ads["alerts"]] == ["ads_auto_bid"]
    assert len(ads["daily"]) == 6 and ads["campaigns_available"] is False
    assert ads["monthly"][-1]["month"] == "2026-10-01"

    # Products: the exact period, the month-to-date row feeds the history only.
    assert products["period"] == {"from": "2026-09-29", "to": "2026-10-28"}
    assert products["items_total"] == 2 and products["totals"]["gmv"] == 1000
    first = products["products"][0]
    assert first["item_id"] == "111" and first["name"] == "Synthetic item"
    assert first["ctr"] == 0.05 and first["add_to_cart_rate"] == 0.25
    assert first["click_to_order"] == 0.1
    assert first["by_flow"] == {"product_card": {"gmv": 600.0, "orders": 4.0}}
    assert first["history"] == [{"month": "2026-10-01", "gmv": 800.0, "orders": 5.0}]
    assert [f["flag"] for f in first["flags"]] == ["ads_optimize"]
    assert products["products"][1]["name"] is None and products["products"][1]["flags"] == []

    assert [p["name"] for p in promos["programs"]] == ["Synthetic sale"]
    assert promos["programs"][0]["gmv"] == 700 and promos["programs"][0]["type_label"]


async def test_an_empty_shop_answers_empty_states_and_a_tiktok_shop_is_refused(two_tenants):
    async with app_session() as session:
        shop_id = await _make_shop(session)
        window = dash.DateRange(DAY0, DAY0 + timedelta(days=5))
        async with with_shop_scope(session, shop_id):
            assert (await dash.flows(session, shop_id, window))["has_data"] is False
            assert (await dash.ads(session, shop_id, window))["has_data"] is False
            assert (await dash.products(session, shop_id))["has_data"] is False
            assert (await dash.promotions(session, shop_id, window))["has_data"] is False
            assert await dash.latest_day(session, shop_id, "traffic_overview") is None
            await session.commit()
        await routes._shopee_shop(session, shop_id)  # a Shopee shop passes
        with pytest.raises(HTTPException) as refused:
            await routes._shopee_shop(session, two_tenants[0].shop_id)
        assert refused.value.status_code == 409
