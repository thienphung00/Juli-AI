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
path.

**All three metric families, in one multi-mutation execution.** Rather than
tripling every boundary/idempotency test per family (no new signal — the
elapse-boundary and idempotency logic in `pipeline.py` operates identically
regardless of which metrics a given execution classifies to), each fixture
below is a single price+title+description run so `gmv`, `impressions`, and
`conversion_rate` readings are all produced — and the "run the reader
twice" assertion is checked across every one of those metrics at once,
proving idempotency is a property of the whole multi-family write, not
assumed from one metric in isolation.

Dates are derived from the single injected `REFERENCE_DATE` anchor
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
    anchor_conversion_rate_proxy,
    anchor_gmv_per_order,
    impressions_base_default,
    make_execution,
    make_product,
    make_shop,
    readings_for,
)

pytestmark = pytest.mark.asyncio

_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]

_THREE_FAMILY_METRICS = {"gmv", "impressions", "conversion_rate"}


async def _build_full_path_fixture(session: AsyncSession, *, t: date, suffix: str) -> ToolExecution:
    """A price+title+description run so all three ADR-077 decision-1 metric
    families produce readings, each backed by five correlated same-shop
    siblings PER FAMILY (a separate control cohort is selected per metric,
    per `control_pool.py`'s own contract — `gmv`'s correlated siblings need
    not be `conversion_rate`'s)."""
    shop = await make_shop(session, phone_suffix=f"1045{suffix}", name=f"Boundary Shop {suffix}")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    impressions_base = impressions_base_default()
    conversion_base = anchor_conversion_rate_proxy()
    product_id = f"prod-{suffix}"
    series_start = t - timedelta(days=14)
    series_end = t + timedelta(days=14)

    await make_product(session, shop, product_id, created=t - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=t,
        approval_suffix=suffix,
        price_update=True,
        title="Tiêu đề cập nhật",
        description="Mô tả cập nhật",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        series_start,
        series_end,
        gmv_base=gmv_base,
        impressions_base=impressions_base,
        conversion_rate_base=conversion_base,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=gmv_base,
        family="gmv",
        start=series_start,
        end=series_end,
        name_prefix=f"ctrl-gmv-{suffix}",
        created=t - timedelta(days=60),
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=impressions_base,
        family="impressions",
        start=series_start,
        end=series_end,
        name_prefix=f"ctrl-imp-{suffix}",
        created=t - timedelta(days=60),
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=conversion_base,
        family="conversion_rate",
        start=series_start,
        end=series_end,
        name_prefix=f"ctrl-cv-{suffix}",
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

    metrics_seen = {r.metric for r in rows}
    assert _THREE_FAMILY_METRICS <= metrics_seen, (
        f"expected all three metric families, got {metrics_seen}"
    )
    for metric in _THREE_FAMILY_METRICS:
        metric_row = next(r for r in rows if r.metric == metric)
        control_set = json.loads(metric_row.control_set_json)
        assert control_set["used_fallback"] is False, (
            f"[{metric}] must exercise the real control path, not the fallback"
        )


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
    final_rows = [r for r in rows if r.kind == "final"]
    assert final_rows, "T+14 MUST produce a final reading — the final window has elapsed"
    metrics_seen = {r.metric for r in final_rows}
    assert _THREE_FAMILY_METRICS <= metrics_seen


async def test_running_reader_twice_on_full_path_writes_each_reading_once_across_all_families(
    session: AsyncSession,
):
    """The reader is actually RUN twice and the two result sets compared —
    per this issue's acceptance criteria, idempotency must not be inferred
    from the `(tool_execution_id, metric, kind)` unique constraint's mere
    existence."""
    t = REFERENCE_DATE - timedelta(days=7)
    execution = await _build_full_path_fixture(session, t=t, suffix="idemfull")

    first_result = await run_daily_impact_reader(session, REFERENCE_DATE)
    await session.commit()
    assert first_result.readings_written > 0
    first_rows = await readings_for(session, execution.id)
    assert first_rows, "first run should have written readings"
    metrics_seen = {r.metric for r in first_rows}
    assert _THREE_FAMILY_METRICS <= metrics_seen

    first_snapshot = {
        (r.metric, r.kind): (r.pre, r.post, r.expected, r.incremental, r.impact_pct, r.confidence)
        for r in first_rows
    }
    first_row_count = len(first_snapshot)

    # Actually run it again — not merely relying on the unique constraint.
    second_result = await run_daily_impact_reader(session, REFERENCE_DATE)
    await session.commit()

    second_rows = await readings_for(session, execution.id)
    second_snapshot = {
        (r.metric, r.kind): (r.pre, r.post, r.expected, r.incremental, r.impact_pct, r.confidence)
        for r in second_rows
    }

    assert second_result.readings_written == 0, (
        "a second run over identical state must write nothing new"
    )
    assert len(second_rows) == first_row_count, "row count must be unchanged across the re-run"
    assert second_snapshot == first_snapshot, (
        "every (metric, kind) value must be unchanged, across all three metric families"
    )
