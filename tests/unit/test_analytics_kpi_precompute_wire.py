"""P2.10-A3 (#527 wave 4) — wire product funnel + LIVE into precompute orchestrator."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from juli_backend.integrations.tiktok.mapping import analytics_snapshot_key
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000527")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Wire Precompute Shop 527",
        tiktok_shop_id="tiktok_shop_527",
    )
    session.add(s)
    await session.flush()
    return s


def _product_interval(
    *,
    shop_id: uuid.UUID,
    start_date: date,
    gmv: Decimal | None,
    product_id: str = "prod-1",
) -> AnalyticsPerformanceInterval:
    return AnalyticsPerformanceInterval(
        shop_id=shop_id,
        snapshot_key=f"product:{product_id}:{start_date.isoformat()}",
        grain="product",
        start_date=start_date,
        end_date=None,
        tiktok_product_id=product_id,
        gmv=gmv,
        gmv_currency="VND" if gmv is not None else None,
        update_time=datetime(2026, 7, 13, tzinfo=UTC),
    )


def _shop_interval(
    *,
    shop_id: uuid.UUID,
    start_date: date,
    gmv: Decimal | None = None,
    live_hours: Decimal | None = None,
    live_sessions: int | None = None,
) -> AnalyticsPerformanceInterval:
    end = start_date + timedelta(days=1)
    return AnalyticsPerformanceInterval(
        shop_id=shop_id,
        snapshot_key=analytics_snapshot_key(
            grain="shop",
            start_date=start_date.isoformat(),
            end_date=end.isoformat(),
        ),
        grain="shop",
        start_date=start_date,
        end_date=end,
        gmv=gmv,
        gmv_currency="VND" if gmv is not None else None,
        live_hours=live_hours,
        live_sessions=live_sessions,
        update_time=datetime(2026, 7, 13, tzinfo=UTC),
    )


def _assert_no_fabricated_series(kpi: dict) -> None:
    series = kpi.get("series")
    assert series in (None, []), f"unexpected fabricated series: {series!r}"


@pytest.mark.asyncio
async def test_precompute_product_funnel_available(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add_all(
        [
            _product_interval(
                shop_id=shop.id,
                start_date=date(2026, 7, 13),
                gmv=Decimal("500000.00"),
                product_id="prod-1",
            ),
            _product_interval(
                shop_id=shop.id,
                start_date=date(2026, 7, 13),
                gmv=Decimal("300000.00"),
                product_id="prod-2",
            ),
        ]
    )
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    product_kpi = envelope.payload["kpis"]["product_funnel"]
    assert product_kpi["availability"] == "available"
    assert product_kpi["label"] == "Product funnel (GMV)"
    assert product_kpi["series"] == [{"t": "2026-07-13", "v": 800000.0}]
    assert "A-34" in envelope.payload["meta"]["source_partitions"]

    fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload == envelope.payload


@pytest.mark.asyncio
async def test_precompute_missing_sources_yield_unavailable_not_fabricated(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    product_kpi = envelope.payload["kpis"]["product_funnel"]
    assert product_kpi["availability"] == "unavailable"
    assert product_kpi["label"] == "Product funnel (GMV)"
    _assert_no_fabricated_series(product_kpi)
    assert "A-34" not in envelope.payload["meta"]["source_partitions"]

    live_kpi = envelope.payload["kpis"]["live_performance"]
    assert live_kpi["availability"] == "unavailable"
    _assert_no_fabricated_series(live_kpi)


@pytest.mark.asyncio
async def test_precompute_live_performance_available(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add(
        _shop_interval(
            shop_id=shop.id,
            start_date=date(2026, 7, 13),
            gmv=Decimal("1200000.00"),
            live_hours=Decimal("3.0000"),
            live_sessions=2,
        )
    )
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    live_kpi = envelope.payload["kpis"]["live_performance"]
    assert live_kpi["availability"] == "available"
    assert live_kpi["label"] == "LIVE performance (GMV)"
    assert live_kpi["series"] == [{"t": "2026-07-13", "v": 1200000.0}]
    partitions = envelope.payload["meta"]["source_partitions"]
    assert "A-28" in partitions
    assert "A-29" in partitions


@pytest.mark.asyncio
async def test_precompute_live_performance_unavailable_revenue_only(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add(
        _shop_interval(
            shop_id=shop.id,
            start_date=date(2026, 7, 13),
            gmv=Decimal("9999999.00"),
        )
    )
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    live_kpi = envelope.payload["kpis"]["live_performance"]
    assert live_kpi["availability"] == "unavailable"
    assert live_kpi["label"] == "LIVE performance (GMV)"
    _assert_no_fabricated_series(live_kpi)
    assert "A-28" not in envelope.payload["meta"]["source_partitions"]
    assert "A-29" not in envelope.payload["meta"]["source_partitions"]


@pytest.mark.asyncio
async def test_precompute_inventory_ops_csat_unavailable_without_aggregate_builders(
    session, shop
) -> None:
    """Inventory/Ops/CSAT stay omitted when no daily aggregate series builders exist."""
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    envelope = await precompute_shop_analytics_kpis(session, shop.id)
    kpis = envelope.payload["kpis"]

    for key in (
        "inventory_turnover",
        "stockout_rate",
        "fulfillment_accuracy_rate",
        "csat_proxy",
        "csat",
    ):
        assert key not in kpis
        entry = kpis.get(key)
        if entry is not None:
            assert entry.get("availability") == "unavailable"
            _assert_no_fabricated_series(entry)
