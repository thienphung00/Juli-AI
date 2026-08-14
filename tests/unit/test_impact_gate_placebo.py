"""ADR-077 §6 gate suite — placebo battery (#1045, issue area 3).

Fabricated-T fixtures, each an otherwise-ordinary product whose weekday
pattern continues undisturbed straight through a fabricated execution date
T (no real event happens at T; a `ToolExecution` is recorded purely so the
reader has something to compute against). Every resulting reading must read
~0 impact, AND — the acceptance criterion this file exists to prove — `Cao`
confidence must never be awarded anywhere in the battery. That is asserted
as an explicit negative property (`confidence != "cao"` on every placebo
row), not inferred from "the numbers happen to be small".

**Three T variants on the revenue/orders family** (`gmv`, via a price
mutation): one at an ordinary freshly-elapsed T, one old enough for the
final window to have elapsed too, and one at an arbitrary, made-up T with
no narrative behind it at all.

**A rate metric runs its own placebo scenario** (`conversion_rate`, via a
description mutation) — the acceptance criterion added on this issue's
re-run: "at least one placebo scenario runs on a rate metric, so a
rate-specific null result is proven rather than assumed from the GMV case."
A rate metric's placebo behaviour is not guaranteed by the GMV case: it is
exactly the family the #1062 defect silently disabled (a rate's own values
can never clear a count-calibrated volume floor), so a placebo test that
only ever exercised `gmv` would not have caught it — `gmv` IS a count, so
the comparison was "coincidentally harmless" there (see
`control_pool.py`'s module docstring).

**A fourth family — impressions/CTR (`impressions`, via an SEO/title
mutation) — also gets a placebo scenario**, closing out all three ADR-077
decision-1 metric families for this gate.
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
_NULL_TOLERANCE = Decimal("0.02")

#: label -> fabricated execution date T. "near" is an ordinary just-elapsed
#: T; "old" is old enough that the final window has elapsed too; "arbitrary"
#: is a deliberately made-up date, unmoored from any real narrative — the
#: literal "fabricated T" the issue names.
_PLACEBO_TS: dict[str, timedelta] = {
    "near": timedelta(days=7),
    "old": timedelta(days=14),
    "arbitrary": timedelta(days=30),
}


def _assert_never_cao_and_near_zero(rows, *, metric_label: str) -> None:
    assert rows, f"the placebo battery must actually produce {metric_label} readings"
    for row in rows:
        # The negative property the issue calls out by name.
        assert row.confidence != "cao", (
            f"[{metric_label}] Cao must never be awarded in the placebo battery — got a cao "
            f"reading for execution={row.tool_execution_id} kind={row.kind} "
            f"impact_pct={row.impact_pct}"
        )
        if row.impact_pct is not None:
            assert abs(row.impact_pct) < _NULL_TOLERANCE, (
                f"[{metric_label}] a placebo reading with no real event should read ~0 impact, "
                f"got {row.impact_pct}"
            )


async def test_placebo_battery_reads_near_zero_and_never_awards_cao_revenue_orders(
    session: AsyncSession,
):
    shop = await make_shop(session, phone_suffix="1045plreve", name="Placebo Shop Rev")
    gmv_base = anchor_gmv_per_order() * Decimal(8)

    execution_ids = []
    for label, delta in _PLACEBO_TS.items():
        t = REFERENCE_DATE - delta
        product_id = f"prod-plreve-{label}"
        series_start = t - timedelta(days=14)
        series_end = t + timedelta(days=14)
        await make_product(session, shop, product_id, created=t - timedelta(days=90))
        execution = await make_execution(
            session, shop, tiktok_product_id=product_id, t=t, approval_suffix=f"plreve-{label}"
        )
        # No real event: the product's series just continues its ordinary
        # weekday pattern straight through T, undisturbed.
        await add_daily_rows(session, shop, product_id, series_start, series_end, gmv_base=gmv_base)
        await add_control_siblings(
            session,
            shop,
            scales=_SCALES,
            base=gmv_base,
            family="gmv",
            start=series_start,
            end=series_end,
            name_prefix=f"ctrl-plreve-{label}",
            created=t - timedelta(days=90),
        )
        execution_ids.append(execution.id)

    await run_daily_impact_reader(session, REFERENCE_DATE)

    all_rows = []
    for execution_id in execution_ids:
        all_rows.extend(await readings_for(session, execution_id))
    gmv_rows = [r for r in all_rows if r.metric == "gmv"]
    assert len(gmv_rows) >= len(_PLACEBO_TS), "expected at least one reading per placebo fixture"
    _assert_never_cao_and_near_zero(gmv_rows, metric_label="gmv")


async def test_placebo_reads_near_zero_and_never_awards_cao_impressions_ctr(
    session: AsyncSession,
):
    t = REFERENCE_DATE - timedelta(days=7)
    shop = await make_shop(session, phone_suffix="1045plimp", name="Placebo Shop Imp")
    impressions_base = impressions_base_default()
    product_id = "prod-placebo-imp"
    series_start = t - timedelta(days=14)
    series_end = t + timedelta(days=14)

    await make_product(session, shop, product_id, created=t - timedelta(days=90))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=t,
        approval_suffix="pl-imp",
        price_update=False,
        title="Tiêu đề sản phẩm ổn định, không thay đổi thực chất",
    )
    await add_daily_rows(
        session, shop, product_id, series_start, series_end, impressions_base=impressions_base
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=impressions_base,
        family="impressions",
        start=series_start,
        end=series_end,
        name_prefix="ctrl-pl-imp",
        created=t - timedelta(days=90),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    imp_rows = [r for r in rows if r.metric == "impressions"]
    _assert_never_cao_and_near_zero(imp_rows, metric_label="impressions")


async def test_placebo_reads_near_zero_and_never_awards_cao_conversion_rate_metric(
    session: AsyncSession,
):
    """The rate-metric scenario the re-run's acceptance criteria require: a
    rate-specific null result on `conversion_rate`, proven independently of
    the GMV case above — not assumed from it."""
    t = REFERENCE_DATE - timedelta(days=7)
    shop = await make_shop(session, phone_suffix="1045plconv", name="Placebo Shop Conv")
    conversion_base = anchor_conversion_rate_proxy()
    product_id = "prod-placebo-conv"
    series_start = t - timedelta(days=14)
    series_end = t + timedelta(days=14)

    await make_product(session, shop, product_id, created=t - timedelta(days=90))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=t,
        approval_suffix="pl-conv",
        price_update=False,
        description="Mô tả sản phẩm không đổi qua thời gian.",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        series_start,
        series_end,
        conversion_rate_base=conversion_base,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=conversion_base,
        family="conversion_rate",
        start=series_start,
        end=series_end,
        name_prefix="ctrl-pl-conv",
        created=t - timedelta(days=90),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    conv_rows = [r for r in rows if r.metric == "conversion_rate"]
    _assert_never_cao_and_near_zero(conv_rows, metric_label="conversion_rate")
