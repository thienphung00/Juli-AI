"""ADR-077 §6 gate suite — reader idempotency + elapse-boundary logic on the
FULL control-adjusted path (#1045, issue area 5).

`tests/unit/test_worker_impact_reader_pipeline.py` (#1044) already covers
this area thoroughly, but every one of its fixtures has zero same-shop
sibling products, so `select_control_pool` always falls back to plain
pre/post there (`used_fallback=True` on every reading it writes) —
idempotency and the elapse boundaries were never actually exercised on the
full, control-adjusted compute path. This file closes that gap using the
gate suite's own golden-shaped fixture builder (five correlated siblings
per target), re-proving both properties hold when `select_control_pool`
genuinely selects a control cohort, not only on the degenerate fallback
path. Dates are derived from the single injected `REFERENCE_DATE` anchor
throughout — never `date.today()`/`datetime.now()` (#1032).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
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

_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]


async def _build_full_path_fixture(session: AsyncSession, *, t: date, suffix: str) -> ToolExecution:
    shop = await make_shop(session, phone_suffix=f"1045{suffix}", name=f"Boundary Shop {suffix}")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = f"prod-{suffix}"
    series_start = t - timedelta(days=14)
    series_end = t + timedelta(days=14)
    await make_product(session, shop, product_id, created=t - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=t, approval_suffix=suffix
    )
    await add_daily_rows(session, shop, product_id, series_start, series_end, gmv_base=gmv_base)
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        gmv_base=gmv_base,
        start=series_start,
        end=series_end,
        name_prefix=f"ctrl-{suffix}",
        created=t - timedelta(days=60),
    )
    return execution


async def test_preliminary_not_due_at_t_plus_6_full_path(session: AsyncSession):
    t = REFERENCE_DATE - timedelta(days=6)
    execution = await _build_full_path_fixture(session, t=t, suffix="t6full")
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    assert rows == [], "T+6 must NOT be picked up on the full control path either"


async def test_preliminary_due_at_t_plus_7_full_path(session: AsyncSession):
    t = REFERENCE_DATE - timedelta(days=7)
    execution = await _build_full_path_fixture(session, t=t, suffix="t7full")
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    assert rows
    assert all(r.kind == "preliminary" for r in rows)

    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    control_set = json.loads(gmv_rows[0].control_set_json)
    assert control_set["used_fallback"] is False, "must exercise the real control path"


async def test_final_not_due_at_t_plus_13_full_path(session: AsyncSession):
    t = REFERENCE_DATE - timedelta(days=13)
    execution = await _build_full_path_fixture(session, t=t, suffix="t13full")
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    assert not any(r.kind == "final" for r in rows), (
        "T+13 must NOT produce a final reading — the final window has not elapsed"
    )


async def test_final_due_at_t_plus_14_full_path(session: AsyncSession):
    t = REFERENCE_DATE - timedelta(days=14)
    execution = await _build_full_path_fixture(session, t=t, suffix="t14full")
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    assert any(r.kind == "final" for r in rows), (
        "T+14 MUST produce a final reading — the final window has elapsed"
    )


async def test_running_reader_twice_on_full_path_writes_each_reading_once(
    session: AsyncSession,
):
    t = REFERENCE_DATE - timedelta(days=7)
    execution = await _build_full_path_fixture(session, t=t, suffix="idemfull")

    await run_daily_impact_reader(session, REFERENCE_DATE)
    first_rows = await readings_for(session, execution.id)
    assert first_rows, "first run should have written readings"
    first_pairs = sorted((r.metric, r.kind) for r in first_rows)

    # Must not raise — this is the actual assertion, not an inference from
    # the unique constraint's existence.
    await run_daily_impact_reader(session, REFERENCE_DATE)

    second_rows = await readings_for(session, execution.id)
    second_pairs = sorted((r.metric, r.kind) for r in second_rows)
    assert second_pairs == first_pairs, "re-run must not write duplicate or extra readings"
    assert len(second_rows) == len(first_rows)
