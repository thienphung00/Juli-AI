"""Bronze -> silver promotion for ctor (A-34) / live_hours (A-28), #880.

AC (issue #880): bronze -> silver promotion writes rows to
``analytics_performance_intervals`` and is idempotent on replay (no
duplicates) — replaying the same bronze row must upsert the same
``(shop_id, snapshot_key)`` row, never insert a second one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    Shop,
    User,
)
from juli_backend.services.etl.silver_promotion import SilverAnalyticsPromoter

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84901112299")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Silver Analytics Promotion Shop",
        tiktok_shop_id="tts_silver_analytics_880",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _ctor_payload(*, gmv: str = "1000000.00", click_order_rate: str = "0.1200") -> dict:
    return {
        "grain": "product",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": 1_754_800_000,
        "snapshot_key": "product|2026-08-10|2026-08-11||prod-880||",
        "product_id": "prod-880",
        "gmv": gmv,
        "gmv_currency": "VND",
        "orders_count": 5,
        "sku_orders": 6,
        "customers": 4,
        "ctr": "0.0800",
        "click_order_rate": click_order_rate,
    }


def _live_session_payload(*, sku_orders: int = 3) -> dict:
    return {
        "grain": "live",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": 1_754_800_000,
        "snapshot_key": "live|2026-08-10|2026-08-11|||live-880-session",
        "live_id": "live-880-session",
        "gmv": "250000.00",
        "gmv_currency": "VND",
        "sku_orders": sku_orders,
        "click_through_rate": "0.0500",
        "click_to_order_rate": "0.0700",
    }


def _live_shop_rollup_payload(*, live_hours: str = "3.2500") -> dict:
    return {
        "grain": "shop",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": 1_754_800_000,
        "snapshot_key": "shop|2026-08-10|2026-08-11||||",
        "live_hours": live_hours,
        "live_sessions": 2,
        "visitors": 120,
        "impressions": 340,
    }


async def test_promote_ctor_writes_product_grain_interval_row(
    session: AsyncSession, shop: Shop
) -> None:
    bronze_row = BronzeCtorPerformanceRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_ctor_payload(),
        tiktok_product_id="prod-880",
        source_event_id="job-1:ctor:prod-880:2026-08-10",
    )
    session.add(bronze_row)
    await session.flush()

    promoter = SilverAnalyticsPromoter(session)
    row = await promoter.promote_ctor(bronze_row)

    assert row.shop_id == shop.id
    assert row.grain == "product"
    assert row.tiktok_product_id == "prod-880"
    assert row.gmv == Decimal("1000000.00")
    assert row.click_order_rate == Decimal("0.1200")

    result = await session.execute(
        select(AnalyticsPerformanceInterval).where(AnalyticsPerformanceInterval.shop_id == shop.id)
    )
    assert len(result.scalars().all()) == 1


async def test_promote_ctor_is_idempotent_on_replay_no_duplicates(
    session: AsyncSession, shop: Shop
) -> None:
    bronze_row = BronzeCtorPerformanceRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_ctor_payload(),
        tiktok_product_id="prod-880",
        source_event_id="job-1:ctor:prod-880:2026-08-10",
    )
    session.add(bronze_row)
    await session.flush()

    promoter = SilverAnalyticsPromoter(session)
    first = await promoter.promote_ctor(bronze_row)
    second = await promoter.promote_ctor(bronze_row)

    assert first.id == second.id

    result = await session.execute(
        select(AnalyticsPerformanceInterval).where(AnalyticsPerformanceInterval.shop_id == shop.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].click_order_rate == Decimal("0.1200")


async def test_promote_live_hours_session_row_writes_live_grain_interval(
    session: AsyncSession, shop: Shop
) -> None:
    bronze_row = BronzeLiveHoursRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_live_session_payload(),
        tiktok_live_id="live-880-session",
        source_event_id="job-1:live_hours:live-880-session:2026-08-10",
    )
    session.add(bronze_row)
    await session.flush()

    promoter = SilverAnalyticsPromoter(session)
    row = await promoter.promote_live_hours(bronze_row)

    assert row.grain == "live"
    assert row.tiktok_live_id == "live-880-session"
    assert row.sku_orders == 3


async def test_promote_live_hours_shop_rollup_populates_live_hours_field(
    session: AsyncSession, shop: Shop
) -> None:
    """The live_hours Demo KPI reads grain=='shop' rows and sums ``live_hours``
    (see ``gold_kpi_envelope_serving.py``) — the shop-grain rollup row must
    therefore carry that field through promotion, not just per-session rows."""
    bronze_row = BronzeLiveHoursRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_live_shop_rollup_payload(),
        tiktok_live_id=None,
        source_event_id="job-1:live_hours:shop:2026-08-10",
    )
    session.add(bronze_row)
    await session.flush()

    promoter = SilverAnalyticsPromoter(session)
    row = await promoter.promote_live_hours(bronze_row)

    assert row.grain == "shop"
    assert row.live_hours == Decimal("3.2500")
    assert row.live_sessions == 2


async def test_promote_live_hours_is_idempotent_on_replay_no_duplicates(
    session: AsyncSession, shop: Shop
) -> None:
    bronze_row = BronzeLiveHoursRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_live_shop_rollup_payload(),
        tiktok_live_id=None,
        source_event_id="job-1:live_hours:shop:2026-08-10",
    )
    session.add(bronze_row)
    await session.flush()

    promoter = SilverAnalyticsPromoter(session)
    first = await promoter.promote_live_hours(bronze_row)
    second = await promoter.promote_live_hours(bronze_row)

    assert first.id == second.id

    result = await session.execute(
        select(AnalyticsPerformanceInterval).where(AnalyticsPerformanceInterval.shop_id == shop.id)
    )
    assert len(result.scalars().all()) == 1
