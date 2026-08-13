"""ADR-077 §6 gate suite — shock cancellation, the design's thesis as a test
(#1045, issue area 2).

A shop-wide x1.5 post-window shock (applied identically to the treated
product AND every control sibling, from the same date — a genuinely
external event, unrelated to the specific write) must read ~0
control-adjusted, while the SAME target's naive pre/post reads +50%.

**Both numbers are asserted.** The naive number is computed independently,
directly off the target's own raw daily series through the pure
`services.impact.windows` helpers (`pre_window`/`post_window`/
`mean_over_window` — the same window arithmetic the real compute path uses,
imported read-only, never re-implemented) — it never reads the persisted
control-adjusted row. Asserting only the control-adjusted ~0 number would
pass even if the control path were entirely inert (e.g. a control series
that was always constant `1`, which is exactly the *fallback* path's own
degenerate case) — the naive +50% assertion is what proves a real, moving
control cohort is what cancelled the shock, not an accident of the formula.
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
    anchor_gmv_per_order,
    daily_value,
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


async def test_shopwide_shock_cancels_control_adjusted_but_not_naive(session: AsyncSession):
    shop = await make_shop(session, phone_suffix="1045shock", name="Shock Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-shock"

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="shock"
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
        gmv_base=gmv_base,
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-shock",
        created=_T - timedelta(days=60),
        shock_from=_SHOCK_FROM,
        shock=_SHOCK,
    )

    # --- Number 1: naive pre/post, computed independently straight off the
    # raw target series, never through the control-adjusted compute path. ---
    pre_start, pre_end = pre_window(_T)
    post_start, post_end = post_window(_T, "preliminary")
    target_series: dict = {}
    current = _SERIES_START
    while current <= _SERIES_END:
        active_shock = _SHOCK if current >= _SHOCK_FROM else Decimal(1)
        target_series[current] = daily_value(current, gmv_base, active_shock)
        current += timedelta(days=1)
    naive_pre = mean_over_window(target_series, pre_start, pre_end, exclude=_T)
    naive_post = mean_over_window(target_series, post_start, post_end, exclude=_T)
    assert naive_pre is not None and naive_post is not None
    naive_pct = (naive_post - naive_pre) / naive_pre

    assert abs(naive_pct - Decimal("0.50")) < Decimal("0.02"), (
        f"naive pre/post must read ~+50% under the shop-wide x1.5 shock, got {naive_pct}"
    )

    # --- Number 2: control-adjusted, through the real pipeline + persisted
    # row (proving the control path actually ran, not just that it exists). ---
    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    control_set = json.loads(gmv_rows[0].control_set_json)
    assert control_set["used_fallback"] is False, (
        "the control path must genuinely run — a fallback (constant-1 control) "
        "reading would make the ~0 result meaningless as evidence"
    )

    control_adjusted_pct = None
    for row in gmv_rows:
        assert row.confidence not in ("suppressed", "confounded")
        assert row.impact_pct is not None
        control_adjusted_pct = row.impact_pct
        assert abs(row.impact_pct) < Decimal("0.02"), (
            f"control-adjusted reading must cancel the shop-wide shock to ~0, got {row.impact_pct}"
        )

    # Reported for the PR/verification record — both numbers, side by side.
    print(
        f"\nSHOCK CANCELLATION — naive_pct={naive_pct} (expected ~+0.50), "
        f"control_adjusted_pct={control_adjusted_pct} (expected ~0)"
    )
