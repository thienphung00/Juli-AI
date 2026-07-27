"""P2.10-A2 (#526) — GMV (TikTok) precompute from shop-grain intervals."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from juli_backend.integrations.tiktok.mapping import analytics_snapshot_key
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User
from juli_backend.repositories.repos import AnalyticsKpiEnvelopesRepo


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000526")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="GMV Precompute Shop 526",
        tiktok_shop_id="tiktok_shop_526",
    )
    session.add(s)
    await session.flush()
    return s


def _shop_interval_row(
    *,
    shop_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    gmv: Decimal | None = Decimal("6408074.00"),
) -> AnalyticsPerformanceInterval:
    start = start or date(2026, 7, 13)
    end = end or date(2026, 7, 14)
    return AnalyticsPerformanceInterval(
        shop_id=shop_id,
        snapshot_key=analytics_snapshot_key(
            grain="shop",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        ),
        grain="shop",
        start_date=start,
        end_date=end,
        gmv=gmv,
        gmv_currency="VND",
        update_time=datetime.now(tz=UTC),
    )


def _assert_gmv_tiktok_label_law(payload: dict) -> None:
    kpis = payload["kpis"]
    assert "gmv_tiktok" in kpis
    assert "net_revenue" not in kpis
    assert "net-revenue" not in kpis
    assert kpis["gmv_tiktok"]["label"] == "GMV (TikTok)"


def _assert_no_fabricated_gmv_series(gmv_kpi: dict) -> None:
    series = gmv_kpi.get("series")
    assert series in (None, []), f"unexpected fabricated series: {series!r}"


@pytest.mark.asyncio
async def test_precompute_gmv_available_from_shop_intervals(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add(_shop_interval_row(shop_id=shop.id))
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    gmv_kpi = envelope.payload["kpis"]["gmv_tiktok"]
    assert gmv_kpi["availability"] == "available"
    _assert_gmv_tiktok_label_law(envelope.payload)
    assert gmv_kpi["series"] == [{"t": "2026-07-13", "v": 6408074.0}]

    fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload == envelope.payload


@pytest.mark.asyncio
async def test_precompute_gmv_unavailable_when_no_shop_intervals(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    gmv_kpi = envelope.payload["kpis"]["gmv_tiktok"]
    assert gmv_kpi["availability"] == "unavailable"
    _assert_gmv_tiktok_label_law(envelope.payload)
    _assert_no_fabricated_gmv_series(gmv_kpi)

    fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload == envelope.payload


@pytest.mark.asyncio
async def test_precompute_gmv_unavailable_when_gmv_null_only(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add(_shop_interval_row(shop_id=shop.id, gmv=None))
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)

    gmv_kpi = envelope.payload["kpis"]["gmv_tiktok"]
    assert gmv_kpi["availability"] == "unavailable"
    _assert_gmv_tiktok_label_law(envelope.payload)
    _assert_no_fabricated_gmv_series(gmv_kpi)

    fetched = await AnalyticsKpiEnvelopesRepo(session).get_by_kind(shop.id, "analytics")
    assert fetched is not None
    assert fetched.payload == envelope.payload
