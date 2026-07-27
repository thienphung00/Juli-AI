"""P2.10-A3 product funnel KPI pure builder (#527 wave 2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.services.analytics_kpi_precompute.product_live import (
    build_product_funnel_kpi,
)


def _product_interval(
    *,
    start_date: date,
    gmv: Decimal | None,
    product_id: str = "prod-1",
    shop_id: uuid.UUID | None = None,
) -> AnalyticsPerformanceInterval:
    sid = shop_id or uuid.uuid4()
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=sid,
        snapshot_key=f"product:{product_id}:{start_date.isoformat()}",
        grain="product",
        start_date=start_date,
        end_date=None,
        tiktok_product_id=product_id,
        gmv=gmv,
        gmv_currency="VND" if gmv is not None else None,
        update_time=datetime(2026, 7, 13, tzinfo=UTC),
    )


def test_build_product_funnel_kpi_available_sums_gmv_by_day() -> None:
    intervals = [
        _product_interval(
            start_date=date(2026, 7, 13), gmv=Decimal("500000.00"), product_id="prod-1"
        ),
        _product_interval(
            start_date=date(2026, 7, 13), gmv=Decimal("300000.00"), product_id="prod-2"
        ),
        _product_interval(
            start_date=date(2026, 7, 14), gmv=Decimal("100000.00"), product_id="prod-1"
        ),
    ]

    entry = build_product_funnel_kpi(intervals)

    assert entry.availability == "available"
    assert entry.label == "Product funnel (GMV)"
    assert entry.series == [
        {"t": "2026-07-13", "v": 800000.0},
        {"t": "2026-07-14", "v": 100000.0},
    ]


def test_build_product_funnel_kpi_zero_gmv_is_valid() -> None:
    entry = build_product_funnel_kpi(
        [_product_interval(start_date=date(2026, 7, 13), gmv=Decimal("0.00"))]
    )

    assert entry.availability == "available"
    assert entry.series == [{"t": "2026-07-13", "v": 0.0}]


def test_build_product_funnel_kpi_unavailable_empty() -> None:
    entry = build_product_funnel_kpi([])

    assert entry.availability == "unavailable"
    assert entry.label == "Product funnel (GMV)"
    assert entry.series == []


def test_build_product_funnel_kpi_unavailable_null_gmv() -> None:
    entry = build_product_funnel_kpi(
        [_product_interval(start_date=date(2026, 7, 13), gmv=None, product_id="prod-1")]
    )

    assert entry.availability == "unavailable"
    assert entry.series == []


def test_build_product_funnel_kpi_ignores_non_product_grain() -> None:
    shop_id = uuid.uuid4()
    shop_row = AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key="shop:2026-07-13:2026-07-14",
        grain="shop",
        start_date=date(2026, 7, 13),
        end_date=date(2026, 7, 14),
        gmv=Decimal("9999999.00"),
        gmv_currency="VND",
        update_time=datetime(2026, 7, 13, tzinfo=UTC),
    )

    entry = build_product_funnel_kpi([shop_row])

    assert entry.availability == "unavailable"
    assert entry.series == []
