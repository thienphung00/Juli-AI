"""End-to-end: a frozen orders feed must show up in the envelope it produced.

Exercises compute_demo_main_kpis_payload against real rows rather than the freshness
helper in isolation, so a wiring mistake (capturing the wrong column, stamping the
wrong KPI) fails here even though the unit tests pass.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.services.gold_kpi_envelope_serving import compute_demo_main_kpis_payload

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_and_shop():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS bronze"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS silver"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS gold"))
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[
                    User.__table__,
                    Shop.__table__,
                    Order.__table__,
                    AnalyticsPerformanceInterval.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84900000853", display_name="Freshness Test User")
        session.add(user)
        await session.flush()
        shop = Shop(user_id=user.id, shop_name="Freshness Shop", tiktok_shop_id="shop_853")
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


async def _add_order(session, shop, *, update_time: datetime, amount: str = "100.00"):
    session.add(
        Order(
            shop_id=shop.id,
            tiktok_order_id=f"o-{update_time.isoformat()}",
            status="COMPLETED",
            total_amount=Decimal(amount),
            currency="VND",
            update_time=update_time,
            tiktok_created_at=update_time,
        )
    )
    await session.flush()


async def _add_interval(session, shop, *, grain: str, start: date):
    session.add(
        AnalyticsPerformanceInterval(
            shop_id=shop.id,
            snapshot_key=f"{grain}-{start.isoformat()}",
            grain=grain,
            start_date=start,
            end_date=start,
            gmv=Decimal("1000.00"),
            click_order_rate=Decimal("0.25"),
            live_hours=Decimal("4.0"),
            update_time=datetime.combine(start, datetime.min.time()),
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_a_frozen_orders_feed_marks_only_the_orders_kpis_stale(session_and_shop):
    """The exact production shape: orders stopped days ago, interval rows are current."""
    session, shop = session_and_shop
    await _add_order(session, shop, update_time=NOW.replace(tzinfo=None) - timedelta(days=2))
    await _add_interval(session, shop, grain="product", start=NOW.date())
    await _add_interval(session, shop, grain="shop", start=NOW.date())

    payload = await compute_demo_main_kpis_payload(session, shop.id, computed_at=NOW)

    freshness = payload["source_freshness"]
    assert freshness["silver.orders"]["stale"] is True
    assert freshness["analytics_performance_intervals"]["stale"] is False

    kpis = payload["kpis"]
    # Every KPI still reports available — staleness is a separate axis, not a
    # downgrade of ADR-044 availability.
    assert all(k["availability"] == "available" for k in kpis.values())
    assert kpis["gmv_tiktok"]["stale"] is True
    assert kpis["aov"]["stale"] is True
    assert kpis["cancellation_rate"]["stale"] is True
    assert kpis["ctor"]["stale"] is False
    assert kpis["live_hours"]["stale"] is False


@pytest.mark.asyncio
async def test_recent_orders_are_not_flagged(session_and_shop):
    """Mutation guard — proves the flag tracks age rather than being always-on."""
    session, shop = session_and_shop
    await _add_order(session, shop, update_time=NOW.replace(tzinfo=None) - timedelta(minutes=10))

    payload = await compute_demo_main_kpis_payload(session, shop.id, computed_at=NOW)

    assert payload["source_freshness"]["silver.orders"]["stale"] is False
    assert payload["kpis"]["gmv_tiktok"]["stale"] is False


@pytest.mark.asyncio
async def test_computed_at_stays_fresh_while_the_data_does_not(session_and_shop):
    """The precise failure this signal exists to catch."""
    session, shop = session_and_shop
    await _add_order(session, shop, update_time=NOW.replace(tzinfo=None) - timedelta(days=5))

    payload = await compute_demo_main_kpis_payload(session, shop.id, computed_at=NOW)

    assert payload["computed_at"] == NOW.isoformat()  # gold ran just now
    assert payload["source_freshness"]["silver.orders"]["age_seconds"] == 5 * 86400
    assert payload["kpis"]["gmv_tiktok"]["stale"] is True


@pytest.mark.asyncio
async def test_empty_shop_reports_no_rows_rather_than_stale(session_and_shop):
    session, shop = session_and_shop

    payload = await compute_demo_main_kpis_payload(session, shop.id, computed_at=NOW)

    for entry in payload["source_freshness"].values():
        assert entry["row_count"] == 0
        assert entry["as_of"] is None
        assert entry["stale"] is False
    assert payload["kpis"]["gmv_tiktok"]["availability"] == "unavailable"
