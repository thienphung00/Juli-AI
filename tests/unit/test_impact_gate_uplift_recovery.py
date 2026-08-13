"""ADR-077 §6 gate suite — synthetic-uplift recovery (#1045, issue area 1).

A known injected uplift must be recovered by the control-adjusted formula,
and a zero-uplift twin (identical fixture, no injected change) must recover
~0. Both go through the real `run_daily_impact_reader` pipeline against a
target product plus five correlated same-shop siblings (the full control
path, not the fallback) — see `_impact_gate_support.py` for fixture
provenance.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from tests.unit._impact_gate_support import (
    REFERENCE_DATE,
    add_control_siblings,
    add_daily_rows,
    anchor_gmv_per_order,
    make_execution,
    make_product,
    make_shop,
    readings_for,
)

pytestmark = pytest.mark.asyncio

_T = REFERENCE_DATE - timedelta(days=7)
_SERIES_START = _T - timedelta(days=14)
_SERIES_END = _T + timedelta(days=14)
_TOLERANCE = Decimal("0.01")  # 1 percentage point
_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]


async def _setup_target_and_controls(
    session: AsyncSession, *, approval_suffix: str, product_id: str, uplift: Decimal
) -> ToolExecution:
    shop = await make_shop(
        session, phone_suffix=f"1045{approval_suffix}", name=f"Uplift Shop {approval_suffix}"
    )
    gmv_base = anchor_gmv_per_order() * Decimal(8)  # ~8 orders/day baseline

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix=approval_suffix
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        gmv_base=gmv_base,
        shock_from=_T + timedelta(days=1),
        shock=uplift,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        gmv_base=gmv_base,
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix=f"ctrl-{approval_suffix}",
        created=_T - timedelta(days=60),
    )
    return execution


async def test_known_injected_uplift_is_recovered(session: AsyncSession):
    injected = Decimal("1.30")  # a known +30% incremental impact
    execution = await _setup_target_and_controls(
        session, approval_suffix="uplift", product_id="prod-uplift", uplift=injected
    )
    result = await run_daily_impact_reader(session, REFERENCE_DATE)
    assert result.readings_written > 0

    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows, "expected a gmv reading for the price mutation's primary metric"
    for row in gmv_rows:
        assert row.confidence not in ("suppressed", "confounded")
        assert row.impact_pct is not None
        assert abs(row.impact_pct - Decimal("0.30")) < _TOLERANCE, (
            f"expected recovered impact_pct near the injected +0.30 uplift, got {row.impact_pct}"
        )


async def test_zero_uplift_twin_recovers_approximately_zero(session: AsyncSession):
    execution = await _setup_target_and_controls(
        session,
        approval_suffix="notuplift",
        product_id="prod-no-uplift",
        uplift=Decimal("1.00"),
    )
    await run_daily_impact_reader(session, REFERENCE_DATE)

    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.impact_pct is not None
        assert abs(row.impact_pct) < _TOLERANCE, (
            f"the zero-uplift twin must recover ~0 impact_pct, got {row.impact_pct}"
        )
