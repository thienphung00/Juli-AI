"""ADR-077 §6 gate suite — placebo battery (#1045, issue area 3).

Three placebo fixtures, each an otherwise-ordinary product whose weekday
pattern continues undisturbed straight through a fabricated execution date
T (no real event happens at T; a `ToolExecution` is recorded purely so the
reader has something to compute against) — one at an ordinary freshly-
elapsed T, one old enough for the final window to have elapsed too, and one
at an arbitrary, made-up T with no narrative behind it at all. Every
resulting reading must read ~0 impact, AND — the acceptance criterion this
file exists to prove — `Cao` confidence must never be awarded anywhere in
the battery. That is asserted as an explicit negative property
(`confidence != "cao"` on every placebo row), not inferred from "the
numbers happen to be small".
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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

#: label -> fabricated execution date T. "near" is an ordinary just-elapsed
#: T; "old" is old enough that the final window has elapsed too; "arbitrary"
#: is a deliberately made-up date, unmoored from any real narrative — the
#: literal "fabricated T" the issue names.
_PLACEBO_TS: dict[str, timedelta] = {
    "near": timedelta(days=7),
    "old": timedelta(days=14),
    "arbitrary": timedelta(days=30),
}


async def test_placebo_battery_reads_near_zero_and_never_awards_cao(session: AsyncSession):
    shop = await make_shop(session, phone_suffix="1045placebo", name="Placebo Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)

    execution_ids = []
    for label, delta in _PLACEBO_TS.items():
        t = REFERENCE_DATE - delta
        product_id = f"prod-placebo-{label}"
        series_start = t - timedelta(days=14)
        series_end = t + timedelta(days=14)
        await make_product(session, shop, product_id, created=t - timedelta(days=90))
        execution = await make_execution(
            session, shop, tiktok_product_id=product_id, t=t, approval_suffix=f"placebo-{label}"
        )
        # No real event: the product's series just continues its ordinary
        # weekday pattern straight through T, undisturbed — the actual
        # "untouched" / null-effect scenario a placebo test requires.
        await add_daily_rows(session, shop, product_id, series_start, series_end, gmv_base=gmv_base)
        await add_control_siblings(
            session,
            shop,
            scales=_SCALES,
            gmv_base=gmv_base,
            start=series_start,
            end=series_end,
            name_prefix=f"ctrl-placebo-{label}",
            created=t - timedelta(days=90),
        )
        execution_ids.append(execution.id)

    await run_daily_impact_reader(session, REFERENCE_DATE)

    all_rows = []
    for execution_id in execution_ids:
        all_rows.extend(await readings_for(session, execution_id))
    gmv_rows = [r for r in all_rows if r.metric == "gmv"]
    assert gmv_rows, "the placebo battery must actually produce readings to test anything"
    assert len(gmv_rows) >= len(_PLACEBO_TS), "expected at least one reading per placebo fixture"

    for row in gmv_rows:
        # The negative property the issue calls out by name.
        assert row.confidence != "cao", (
            "Cao must never be awarded in the placebo battery — got a cao reading for "
            f"execution={row.tool_execution_id} kind={row.kind} impact_pct={row.impact_pct}"
        )
        if row.impact_pct is not None:
            assert abs(row.impact_pct) < Decimal("0.02"), (
                f"a placebo reading with no real event should read ~0 impact, got {row.impact_pct}"
            )
