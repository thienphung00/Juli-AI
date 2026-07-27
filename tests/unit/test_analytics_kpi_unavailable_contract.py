"""P2.10-A4 (#528) — unavailable Ads/Shop Status/T1 forecast envelope contract."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from juli_backend.integrations.tiktok.mapping import analytics_snapshot_key
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User

_ADS_KEYS = ("roas", "cac", "ctr")
_SHOP_STATUS_KEYS = ("sps", "ahr", "violation_points")
_PHASE_210A_UNAVAILABLE_KEYS = _ADS_KEYS + _SHOP_STATUS_KEYS


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849305000528")
    session.add(user)
    await session.flush()
    s = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Unavailable Contract Shop 528",
        tiktok_shop_id="tiktok_shop_528",
    )
    session.add(s)
    await session.flush()
    return s


def _product_interval(
    *,
    shop_id: uuid.UUID,
    start_date: date,
    gmv: Decimal,
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
        gmv_currency="VND",
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


def _assert_unavailable_kpi(kpi: dict, *, label: str) -> None:
    assert kpi["availability"] == "unavailable"
    assert kpi["label"] == label
    assert kpi.get("series") in (None, [])


# --- Slice 1: unit-test contract builders (no DB) ---


@pytest.mark.parametrize(
    ("kpi_id", "label"),
    [
        ("roas", "ROAS (Ads)"),
        ("cac", "CAC (Ads)"),
        ("ctr", "CTR (Ads)"),
        ("sps", "Shop Performance Score (SPS)"),
        ("ahr", "Account Health Rating (AHR)"),
        ("violation_points", "Violation Points (VP)"),
    ],
)
def test_build_unavailable_kpi_entry(kpi_id: str, label: str) -> None:
    from juli_backend.services.analytics_kpi_precompute.unavailable_contract import (
        build_unavailable_kpi_entry,
    )

    entry = build_unavailable_kpi_entry(kpi_id)
    assert entry.availability == "unavailable"
    assert entry.label == label
    assert entry.series == []


def test_build_phase_210a_unavailable_kpis_covers_all_keys() -> None:
    from juli_backend.services.analytics_kpi_precompute.unavailable_contract import (
        build_phase_210a_unavailable_kpis,
    )

    kpis = build_phase_210a_unavailable_kpis()
    assert set(kpis.keys()) == set(_PHASE_210A_UNAVAILABLE_KEYS)
    for key in _PHASE_210A_UNAVAILABLE_KEYS:
        assert kpis[key].availability == "unavailable"
        assert kpis[key].series == []


def test_build_t1_forecast_overlay_unavailable() -> None:
    from juli_backend.services.analytics_kpi_precompute.unavailable_contract import (
        build_t1_forecast_overlay,
    )

    overlay = build_t1_forecast_overlay()
    assert overlay == {"availability": "unavailable", "label": "T1 forecast overlay"}


# --- Slice 2: precompute merges unavailable contract when live KPIs available ---


@pytest.mark.asyncio
async def test_precompute_unavailable_contract_when_gmv_product_live_available(
    session, shop
) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add_all(
        [
            _shop_interval(
                shop_id=shop.id,
                start_date=date(2026, 7, 13),
                gmv=Decimal("6408074.00"),
                live_hours=Decimal("3.0000"),
                live_sessions=2,
            ),
            _product_interval(
                shop_id=shop.id,
                start_date=date(2026, 7, 13),
                gmv=Decimal("500000.00"),
            ),
        ]
    )
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)
    kpis = envelope.payload["kpis"]

    assert kpis["gmv_tiktok"]["availability"] == "available"
    assert kpis["product_funnel"]["availability"] == "available"
    assert kpis["live_performance"]["availability"] == "available"

    for key in _PHASE_210A_UNAVAILABLE_KEYS:
        assert key in kpis, f"missing unavailable contract key: {key}"
        _assert_unavailable_kpi(kpis[key], label=_expected_label(key))

    overlay = envelope.payload["overlays"]["t1_forecast"]
    assert overlay["availability"] == "unavailable"
    assert overlay["label"] == "T1 forecast overlay"

    partitions = envelope.payload["meta"]["source_partitions"]
    for unavailable_partition in ("A-ads", "A-shop-status", "A-t1-forecast"):
        assert unavailable_partition not in partitions


def _expected_label(key: str) -> str:
    labels = {
        "roas": "ROAS (Ads)",
        "cac": "CAC (Ads)",
        "ctr": "CTR (Ads)",
        "sps": "Shop Performance Score (SPS)",
        "ahr": "Account Health Rating (AHR)",
        "violation_points": "Violation Points (VP)",
    }
    return labels[key]


# --- Slice 3: GMV label law — no net_revenue alias ---


@pytest.mark.asyncio
async def test_precompute_no_net_revenue_alias(session, shop) -> None:
    from juli_backend.services.analytics_kpi_precompute import precompute_shop_analytics_kpis

    session.add(
        _shop_interval(
            shop_id=shop.id,
            start_date=date(2026, 7, 13),
            gmv=Decimal("1000000.00"),
        )
    )
    await session.flush()

    envelope = await precompute_shop_analytics_kpis(session, shop.id)
    kpis = envelope.payload["kpis"]

    assert "net_revenue" not in kpis
    assert "net-revenue" not in kpis
    assert kpis["gmv_tiktok"]["label"] == "GMV (TikTok)"
