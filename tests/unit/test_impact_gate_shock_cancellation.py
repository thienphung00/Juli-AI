"""ADR-077 §6 gate suite — shock cancellation, the design's thesis as a test
(#1045, issue area 2).

A shop-wide x1.5 post-window shock (applied identically to the treated
product AND every control sibling, from the same date — a genuinely
external event, unrelated to the specific write) must read ~0
control-adjusted, while the SAME target's naive pre/post reads +50%.

**Both numbers are asserted**, for all three ADR-077 decision-1 metric
families (revenue_orders/gmv, impressions_ctr/impressions, conversion/
conversion_rate) — not GMV alone, the gap this re-run exists to close (see
`_impact_gate_support.py`'s module docstring and this issue's comment
thread). The naive number is computed independently, directly off the
target's own raw daily series through the pure `services.impact.windows`
helpers (`pre_window`/`post_window`/`mean_over_window` — the same window
arithmetic the real compute path uses, imported read-only, never
re-implemented) — it never reads the persisted control-adjusted row.
Asserting only the control-adjusted ~0 number would pass even if the
control path were entirely inert (e.g. a control series that was always
constant `1`, which is exactly the *fallback* path's own degenerate case)
— the naive +50% assertion is what proves a real, moving control cohort is
what cancelled the shock, not an accident of the formula.

**`used_fallback is False` is asserted explicitly** on every metric family
below (issue #1045's "Also required" note): a sibling slice (#1043) shipped
a "non-fallback" composed test that was silently running the fallback
branch because constant-valued fixture candidates degenerate Pearson
correlation to `0.0` and drop below the `0.2` quality bar. Every control
sibling here carries genuine day-to-day weekday-pattern variation (never a
flat constant), so correlation against the target is a real, non-degenerate
`~1.0` — not the constant-series degenerate case.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.impact import mean_over_window, post_window, pre_window
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from tests.unit._impact_gate_support import (
    REFERENCE_DATE,
    add_control_siblings,
    add_daily_rows,
    anchor_conversion_rate_proxy,
    anchor_gmv_per_order,
    daily_int_value,
    daily_rate_value,
    daily_value,
    impressions_base_default,
    make_execution,
    make_product,
    make_shop,
    readings_for,
)

pytestmark = pytest.mark.asyncio

_T = REFERENCE_DATE - timedelta(days=7)
_SERIES_START = _T - timedelta(days=14)
_SERIES_END = _T + timedelta(days=14)
_SHOCK = Decimal("1.5")
_SHOCK_FROM = _T + timedelta(days=1)
_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]
_NAIVE_TOLERANCE = Decimal("0.02")
_ADJUSTED_TOLERANCE = Decimal("0.02")


def _naive_pct(series: dict) -> Decimal:
    pre_start, pre_end = pre_window(_T)
    post_start, post_end = post_window(_T, "preliminary")
    naive_pre = mean_over_window(series, pre_start, pre_end, exclude=_T)
    naive_post = mean_over_window(series, post_start, post_end, exclude=_T)
    assert naive_pre is not None and naive_post is not None
    return (naive_post - naive_pre) / naive_pre


async def test_shopwide_shock_cancels_control_adjusted_but_not_naive_revenue_orders(
    session: AsyncSession,
):
    shop = await make_shop(session, phone_suffix="1045shockrev", name="Shock Shop Rev")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-shock-rev"

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="shock-rev"
    )
    # The treated product gets the SAME shop-wide shock as everyone else —
    # nothing about it is special beyond having a Juli execution recorded.
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        gmv_base=gmv_base,
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )
    # Every control sibling ALSO gets the same x1.5 shock from the same
    # date — a genuinely shop-wide event, not something isolated to the
    # target write.
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=gmv_base,
        family="gmv",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-shock-rev",
        created=_T - timedelta(days=60),
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )

    # --- Number 1: naive pre/post, off the raw target series directly. ---
    target_series: dict = {}
    current = _SERIES_START
    while current <= _SERIES_END:
        active_shock = _SHOCK if current >= _SHOCK_FROM else Decimal(1)
        target_series[current] = daily_value(current, gmv_base, active_shock)
        current += timedelta(days=1)
    naive_pct = _naive_pct(target_series)
    assert abs(naive_pct - Decimal("0.50")) < _NAIVE_TOLERANCE, (
        f"[gmv] naive pre/post must read ~+50% under the shop-wide x1.5 shock, got {naive_pct}"
    )

    # --- Number 2: control-adjusted, through the real pipeline. ---
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    control_set = json.loads(gmv_rows[0].control_set_json)
    assert control_set["used_fallback"] is False, (
        "the control path must genuinely run — a fallback reading would make the ~0 result "
        "meaningless as evidence"
    )

    control_adjusted_pct = None
    for row in gmv_rows:
        assert row.confidence not in ("suppressed", "confounded")
        assert row.impact_pct is not None
        control_adjusted_pct = row.impact_pct
        assert abs(row.impact_pct) < _ADJUSTED_TOLERANCE, (
            f"[gmv] control-adjusted reading must cancel the shop-wide shock to ~0, "
            f"got {row.impact_pct}"
        )

    print(
        f"\nSHOCK CANCELLATION [revenue_orders/gmv] — naive_pct={naive_pct} (expected ~+0.50), "
        f"control_adjusted_pct={control_adjusted_pct} (expected ~0)"
    )


async def test_shopwide_shock_cancels_control_adjusted_but_not_naive_impressions_ctr(
    session: AsyncSession,
):
    shop = await make_shop(session, phone_suffix="1045shockimp", name="Shock Shop Imp")
    impressions_base = impressions_base_default()
    product_id = "prod-shock-imp"

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="shock-imp",
        price_update=False,
        title="Áo thun cotton cao cấp - tiêu đề mới",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        impressions_base=impressions_base,
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=impressions_base,
        family="impressions",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-shock-imp",
        created=_T - timedelta(days=60),
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )

    target_series: dict = {}
    current = _SERIES_START
    while current <= _SERIES_END:
        active_shock = _SHOCK if current >= _SHOCK_FROM else Decimal(1)
        target_series[current] = Decimal(daily_int_value(current, impressions_base, active_shock))
        current += timedelta(days=1)
    naive_pct = _naive_pct(target_series)
    assert abs(naive_pct - Decimal("0.50")) < _NAIVE_TOLERANCE, (
        f"[impressions] naive pre/post must read ~+50% under the shop-wide x1.5 shock, "
        f"got {naive_pct}"
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    imp_rows = [r for r in rows if r.metric == "impressions"]
    assert imp_rows
    control_set = json.loads(imp_rows[0].control_set_json)
    assert control_set["used_fallback"] is False, (
        "[impressions] the control path must genuinely run (this is exactly the #1062 seam: a "
        "rate/volume metric silently falling back would make the ~0 result meaningless)"
    )

    control_adjusted_pct = None
    for row in imp_rows:
        assert row.confidence not in ("suppressed", "confounded")
        assert row.impact_pct is not None
        control_adjusted_pct = row.impact_pct
        assert abs(row.impact_pct) < _ADJUSTED_TOLERANCE, (
            f"[impressions] control-adjusted reading must cancel the shop-wide shock to ~0, "
            f"got {row.impact_pct}"
        )

    print(
        f"\nSHOCK CANCELLATION [impressions_ctr/impressions] — naive_pct={naive_pct} "
        f"(expected ~+0.50), control_adjusted_pct={control_adjusted_pct} (expected ~0)"
    )


async def test_shopwide_shock_cancels_control_adjusted_but_not_naive_conversion(
    session: AsyncSession,
):
    shop = await make_shop(session, phone_suffix="1045shockcv", name="Shock Shop Conv")
    conversion_base = anchor_conversion_rate_proxy()
    product_id = "prod-shock-conv"

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="shock-cv",
        price_update=False,
        description="Mô tả sản phẩm cập nhật, chất liệu cao cấp.",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        conversion_rate_base=conversion_base,
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=conversion_base,
        family="conversion_rate",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-shock-cv",
        created=_T - timedelta(days=60),
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )

    target_series: dict = {}
    current = _SERIES_START
    while current <= _SERIES_END:
        active_shock = _SHOCK if current >= _SHOCK_FROM else Decimal(1)
        target_series[current] = daily_rate_value(current, conversion_base, active_shock)
        current += timedelta(days=1)
    naive_pct = _naive_pct(target_series)
    assert abs(naive_pct - Decimal("0.50")) < _NAIVE_TOLERANCE, (
        f"[conversion_rate] naive pre/post must read ~+50% under the shop-wide x1.5 shock, "
        f"got {naive_pct}"
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    conv_rows = [r for r in rows if r.metric == "conversion_rate"]
    assert conv_rows
    control_set = json.loads(conv_rows[0].control_set_json)
    assert control_set["used_fallback"] is False, (
        "[conversion_rate] the control path must genuinely run — this is exactly the rate-metric "
        "seam #1062 broke (a count-calibrated floor compared against the rate's own ~0.0x-0.3x "
        "values disqualifies every candidate and silently forces this branch)"
    )

    control_adjusted_pct = None
    for row in conv_rows:
        assert row.confidence not in ("suppressed", "confounded")
        assert row.impact_pct is not None
        control_adjusted_pct = row.impact_pct
        assert abs(row.impact_pct) < _ADJUSTED_TOLERANCE, (
            f"[conversion_rate] control-adjusted reading must cancel the shop-wide shock to ~0, "
            f"got {row.impact_pct}"
        )

    print(
        f"\nSHOCK CANCELLATION [conversion/conversion_rate] — naive_pct={naive_pct} "
        f"(expected ~+0.50), control_adjusted_pct={control_adjusted_pct} (expected ~0)"
    )
