"""``compute_demo_main_kpis_payload``: LIVE hours and CTOR from analytics intervals.

Grain filtering is the load-bearing rule. ``live_hours`` sums *shop*-grain rows
only and ``ctor`` is the GMV-weighted ``click_order_rate`` over *product*-grain
rows only. The production dump has four grains per shop (product, live, shop,
catalog_daily); widening either filter produces a plausible wrong number, not a
failure. An honest measurement of zero is ``available`` with ``value: 0.0``;
no rows, or a zero GMV denominator, is ``unavailable`` with no value (ADR-044).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.services.gold_kpi_envelope_contract import build_honest_unavailable_shell_payload
from juli_backend.services.gold_kpi_envelope_serving import (
    compute_demo_main_kpis_payload,
    seed_unavailable_shell,
)

DAY = date(2026, 8, 1)


async def add_interval(session, shop, grain: str, **measures: Any) -> AnalyticsPerformanceInterval:
    row = AnalyticsPerformanceInterval(
        shop_id=shop.id,
        snapshot_key=f"{shop.id}:{grain}:{DAY}:{uuid.uuid4().hex[:6]}",
        grain=grain,
        start_date=DAY,
        end_date=DAY,
        update_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        **measures,
    )
    session.add(row)
    await session.flush()
    return row


def test_unavailable_shell_marks_every_kpi_unavailable():
    payload = build_honest_unavailable_shell_payload(
        shop_id=uuid.uuid4(), computed_at=datetime(2026, 7, 30, 6, 0, tzinfo=UTC)
    )

    assert len(payload["kpis"]) >= 5
    assert all(entry["availability"] == "unavailable" for entry in payload["kpis"].values())
    assert all("label" in entry for entry in payload["kpis"].values())


async def test_seeding_the_shell_is_idempotent(session, shop):
    first = await seed_unavailable_shell(session, shop.id)
    second = await seed_unavailable_shell(session, shop.id)

    assert first.shop_id == second.shop_id
    assert first.payload["kpis"] == second.payload["kpis"]


class TestLiveHours:
    async def test_sums_shop_grain_rows(self, session, shop):
        await add_interval(session, shop, "shop", live_hours=Decimal("12.5"))

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["live_hours"]

        assert (kpi["availability"], kpi["value"], kpi["label"]) == (
            "available",
            12.5,
            "LIVE hours",
        )

    async def test_zero_is_an_honest_measurement_not_unavailable(self, session, shop):
        await add_interval(session, shop, "shop", live_hours=Decimal("0"))

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["live_hours"]

        assert (kpi["availability"], kpi["value"]) == ("available", 0.0)

    async def test_ignores_live_grain_rows(self, session, shop):
        """Live sessions are the wrong grain; counting them double counts LIVE hours."""
        await add_interval(session, shop, "shop", live_hours=Decimal("12.3289"))
        await add_interval(session, shop, "live", live_hours=Decimal("5.5"))

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["live_hours"]

        assert kpi["value"] == pytest.approx(12.3289)


class TestCtor:
    async def test_is_gmv_weighted_over_product_grain_rows(self, session, shop):
        await add_interval(
            session, shop, "product", gmv=Decimal("100"), click_order_rate=Decimal("0.05")
        )
        await add_interval(
            session, shop, "product", gmv=Decimal("200"), click_order_rate=Decimal("0.10")
        )

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["ctor"]

        assert kpi["availability"] == "available"
        assert float(kpi["value"]) == pytest.approx((100 * 0.05 + 200 * 0.10) / 300)
        assert kpi["label"] == "CTOR (click→đơn)"

    async def test_zero_rate_with_gmv_is_available_zero(self, session, shop):
        await add_interval(
            session, shop, "product", gmv=Decimal("100"), click_order_rate=Decimal("0")
        )

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["ctor"]

        assert (kpi["availability"], kpi["value"]) == ("available", 0.0)

    async def test_zero_gmv_denominator_is_unavailable(self, session, shop):
        await add_interval(
            session, shop, "product", gmv=Decimal("0"), click_order_rate=Decimal("0.05")
        )

        kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]["ctor"]

        assert kpi["availability"] == "unavailable"
        assert "value" not in kpi


@pytest.mark.parametrize("kpi_name", ["live_hours", "ctor"])
async def test_no_rows_is_unavailable_without_a_value(session, shop, kpi_name):
    kpi = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"][kpi_name]

    assert kpi["availability"] == "unavailable"
    assert "value" not in kpi


async def test_grain_filters_hold_against_the_real_four_grain_shape(session, shop):
    """Reference shop in the 2026-07-30 dump: product, live, shop and catalog_daily rows."""
    await add_interval(
        session,
        shop,
        "shop",
        gmv=Decimal("6114649"),
        live_hours=Decimal("12.3289"),
        live_sessions=8,
    )
    await add_interval(session, shop, "live", live_hours=Decimal("5.5"))
    await add_interval(
        session, shop, "product", gmv=Decimal("100"), click_order_rate=Decimal("0.05")
    )
    await add_interval(
        session, shop, "product", gmv=Decimal("200"), click_order_rate=Decimal("0.10")
    )
    await add_interval(session, shop, "catalog_daily", active_products=42, new_products=3)

    kpis = (await compute_demo_main_kpis_payload(session, shop.id))["kpis"]

    assert kpis["live_hours"]["value"] == pytest.approx(12.3289)
    assert kpis["ctor"]["value"] == pytest.approx((100 * 0.05 + 200 * 0.10) / 300)
