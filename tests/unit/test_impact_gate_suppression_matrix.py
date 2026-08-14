"""ADR-077 §6 gate suite — suppression/fallback matrix (#1045, issue area 4).

Every one of the five states ADR-077 decision 4 names must be independently
reachable and asserted: below-floor, <3 controls, <0.2 correlation,
confounded, pre=0. All five are reached below — none are skipped as
unreachable.

**Family coverage — the acceptance criterion this re-run adds.** The
reference implementation drove every one of these five states through
`gmv`/`revenue_orders` alone (4/5 states) with `conversion_rate` appearing
only in the `pre=0` case. In particular the **below-floor state never
exercised the `impressions_ctr` volume floor at all** — the exact gap this
issue names: "the suppression matrix exercises the `impressions_ctr` volume
floor (≥50 impressions/day) directly, not only the revenue floor."

Where a state is genuinely metric-family-agnostic by construction (its
trigger condition never reads the metric's own values, only candidate
*counts* or the reading's `status`), this file says so explicitly in a
comment rather than tripling identical test bodies with no new signal:

- **<3 controls** (`fewer_than_three_controls_falls_back`) triggers on
  `len(scored) < MIN_CANDIDATES` in `control_pool.select_control_pool` —
  purely a candidate-*count* check, evaluated identically regardless of
  which metric is being read. Demonstrated once, on `revenue_orders`.
- **confounded** blanks every numeric field via `reading.compute_metric_reading`'s
  `confounded: bool` branch — a per-`(execution, window)` flag, not a
  per-metric one. Demonstrated once, but on a **multi-mutation execution**
  so `gmv`, `impressions`, and `conversion_rate` readings all confound in
  the same run — proving the state is genuinely family-independent rather
  than assuming it from one metric.

**below-floor**, **<0.2 correlation**, and **pre=0** are NOT
family-agnostic in this sense (their trigger reads a metric-specific column
— the family's volume indicator, the metric's own pre-period values, or
the metric's own `pre` — respectively) and are each demonstrated on more
than one family below.
"""

from __future__ import annotations

import json
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
    make_execution,
    make_product,
    make_shop,
    readings_for,
)

pytestmark = pytest.mark.asyncio

_T = REFERENCE_DATE - timedelta(days=7)
_SERIES_START = _T - timedelta(days=14)
_SERIES_END = _T + timedelta(days=14)


# ---------------------------------------------------------------------------
# below-floor — target's own pre-period VOLUME (not the metric's own value)
# sits under the family's floor. Demonstrated on revenue_orders (>=1
# order/day) AND impressions_ctr (>=50 impressions/day, the acceptance
# criterion this file adds) AND conversion (>=20 visitors/day).
# ---------------------------------------------------------------------------


async def test_below_floor_state_is_reached_revenue_orders(session: AsyncSession):
    """`sku_orders` (the gmv family's volume indicator) sits under the
    floor (`>= 1 order/day`) — must land as `suppressed`. `gmv` itself is a
    real, nonzero, flat daily figure — deliberately decoupled from `pre =
    0` (its own, separately-tested suppression axis) so this test isolates
    the volume-floor gate specifically."""
    shop = await make_shop(session, phone_suffix="1045bflrev", name="Below Floor Shop Rev")
    product_id = "prod-below-floor-rev"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="bflr"
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        gmv_constant=Decimal("50000.00"),  # nonzero — below-floor is about volume, not pre=0
        sku_orders_per_day=0,  # the gmv family's volume indicator — under the >=1 floor
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.confidence == "suppressed"
        assert row.pre == Decimal("50000.00")
        assert row.impact_pct is not None, (
            "pre is nonzero here — the % form is NOT suppressed, only the confidence tier is"
        )


async def test_below_floor_state_is_reached_impressions_ctr(session: AsyncSession):
    """The impressions/CTR family's volume indicator IS `impressions`
    itself here (the metric under test is `impressions`) — sits under the
    `>= 50 impressions/day` floor. This is the direct proof that the
    suppression matrix exercises the impressions/CTR floor, not only the
    revenue floor: `confidence.pre_period_volume` must read through
    `_VOLUME_INDICATOR[IMPRESSIONS_CTR]` (`day.impressions`) and correctly
    land `suppressed` at 30/day (below 50), never silently treating some
    other column as the indicator."""
    shop = await make_shop(session, phone_suffix="1045bflimp", name="Below Floor Shop Imp")
    product_id = "prod-below-floor-imp"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="bfli",
        price_update=False,
        title="Tiêu đề cập nhật cho sản phẩm lưu lượng thấp",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        impressions_per_day=30,  # under the >=50/day impressions_ctr floor
        ctr=Decimal("0.055000"),  # a real, nonzero ctr value — never itself compared to 50
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    imp_rows = [r for r in rows if r.metric == "impressions"]
    assert imp_rows
    for row in imp_rows:
        assert row.confidence == "suppressed", (
            f"expected below-floor (persisted as 'suppressed') at 30 impressions/day < the "
            f"50/day floor, got confidence={row.confidence!r}"
        )
        # impressions IS the volume indicator for this family, so pre being
        # a real number and the floor gate still firing both hold at once —
        # unlike the conversion_rate case, there's no separate axis here.
        assert row.pre == Decimal("30.00")


async def test_below_floor_state_is_reached_conversion(session: AsyncSession):
    """`visitors` (the conversion family's volume indicator — deliberately
    distinct from `impressions`, see `confidence.py`'s module docstring) sits
    under the `>= 20 visitors/day` floor, while `conversion_rate` itself is
    a real, nonzero, flat daily figure — proving the floor reads `visitors`,
    never the rate metric's own ~0.01-0.30 values (the #1062 seam)."""
    shop = await make_shop(session, phone_suffix="1045bflcv", name="Below Floor Shop Conv")
    product_id = "prod-below-floor-conv"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="bflc",
        price_update=False,
        description="Mô tả cập nhật cho sản phẩm lưu lượng thấp",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        visitors_per_day=10,  # under the >=20/day conversion floor
        conversion_rate=Decimal("0.080000"),  # a real, nonzero conversion_rate value
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    conv_rows = [r for r in rows if r.metric == "conversion_rate"]
    assert conv_rows
    for row in conv_rows:
        assert row.confidence == "suppressed"
        assert row.pre == Decimal("0.080000")
        assert row.impact_pct is not None


# ---------------------------------------------------------------------------
# <3 controls — a candidate-COUNT gate, evaluated before any metric value is
# read. Family-agnostic by construction; demonstrated once (see module
# docstring).
# ---------------------------------------------------------------------------


async def test_fewer_than_three_controls_falls_back(session: AsyncSession):
    """Only 2 same-shop siblings exist — below `MIN_CANDIDATES=3` — must
    fall back to plain pre/post, capped at `thap`, with
    `fallback_reason == "insufficient_candidates"` on the audit JSON."""
    shop = await make_shop(session, phone_suffix="1045few", name="Few Controls Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-few-controls"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="few"
    )
    await add_daily_rows(session, shop, product_id, _SERIES_START, _SERIES_END, gmv_base=gmv_base)
    await add_control_siblings(
        session,
        shop,
        scales=[Decimal("0.8"), Decimal("1.2")],  # only 2 — below MIN_CANDIDATES
        base=gmv_base,
        family="gmv",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-few",
        created=_T - timedelta(days=60),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.confidence == "thap"
        control_set = json.loads(row.control_set_json)
        assert control_set["used_fallback"] is True
        assert control_set["fallback_reason"] == "insufficient_candidates"


# ---------------------------------------------------------------------------
# <0.2 mean correlation — degenerate (flat/constant) candidate series.
# Demonstrated on revenue_orders AND conversion (a rate family), so the
# degenerate-correlation fallback is proven independent of the metric's own
# unit, not assumed from the count case.
# ---------------------------------------------------------------------------


async def test_low_mean_correlation_falls_back_revenue_orders(session: AsyncSession):
    """>=3 candidates exist, but each is a flat (zero-variance) series over
    the pre-period — Pearson correlation degenerates to `0.0` for each, so
    the mean of the top-K falls under `MIN_MEAN_CORRELATION=0.2` — must
    fall back with `fallback_reason == "low_mean_correlation"`, distinct
    from the insufficient-candidates trigger above even though both reach
    the same `thap`-capped fallback state."""
    shop = await make_shop(session, phone_suffix="1045corrrev", name="Low Correlation Shop Rev")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-low-correlation-rev"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="corrr"
    )
    await add_daily_rows(session, shop, product_id, _SERIES_START, _SERIES_END, gmv_base=gmv_base)
    for i in range(4):
        pid = f"ctrl-flat-rev-{i}"
        await make_product(session, shop, pid, created=_T - timedelta(days=60))
        await add_daily_rows(
            session,
            shop,
            pid,
            _SERIES_START,
            _SERIES_END,
            gmv_constant=gmv_base,  # perfectly flat — zero variance, correlation 0.0
        )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.confidence == "thap"
        control_set = json.loads(row.control_set_json)
        assert control_set["used_fallback"] is True
        assert control_set["fallback_reason"] == "low_mean_correlation"
        # A "perfectly flat" fixture is float-constant, not necessarily
        # bit-exact after `fsum(y) / n` rounding inside stdlib
        # `statistics.correlation` — that can leave a ~1e-16-scale residual
        # instead of tripping the ZeroDivisionError `_safe_correlation`
        # catches (see this module's docstring). The real, meaningful
        # assertion is the near-zero magnitude and the fallback outcome
        # above, not float bit-equality with a stdlib implementation detail.
        assert abs(control_set["mean_correlation"]) < 1e-9


async def test_low_mean_correlation_falls_back_conversion(session: AsyncSession):
    """The same degenerate-correlation trigger, on `conversion_rate` — a
    rate metric — so the low-correlation fallback is proven on a rate
    family too, not only on the count/currency `gmv` case."""
    shop = await make_shop(session, phone_suffix="1045corrcv", name="Low Correlation Shop Conv")
    conversion_base = anchor_conversion_rate_proxy()
    product_id = "prod-low-correlation-conv"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="corrc",
        price_update=False,
        description="Mô tả cập nhật, tương quan kiểm soát thấp",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        conversion_rate_base=conversion_base,
    )
    for i in range(4):
        pid = f"ctrl-flat-conv-{i}"
        await make_product(session, shop, pid, created=_T - timedelta(days=60))
        await add_daily_rows(
            session,
            shop,
            pid,
            _SERIES_START,
            _SERIES_END,
            conversion_rate=conversion_base,  # perfectly flat — zero variance, correlation 0.0
        )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    conv_rows = [r for r in rows if r.metric == "conversion_rate"]
    assert conv_rows
    for row in conv_rows:
        assert row.confidence == "thap"
        control_set = json.loads(row.control_set_json)
        assert control_set["used_fallback"] is True
        assert control_set["fallback_reason"] == "low_mean_correlation"
        # A "perfectly flat" fixture is float-constant, not necessarily
        # bit-exact after `fsum(y) / n` rounding inside stdlib
        # `statistics.correlation` — that can leave a ~1e-16-scale residual
        # instead of tripping the ZeroDivisionError `_safe_correlation`
        # catches (see this module's docstring). The real, meaningful
        # assertion is the near-zero magnitude and the fallback outcome
        # above, not float bit-equality with a stdlib implementation detail.
        assert abs(control_set["mean_correlation"]) < 1e-9


# ---------------------------------------------------------------------------
# confounded — a second Juli run inside the window. Family-agnostic by
# construction (blanks every metric on the execution, not a per-metric
# state) — proven on a multi-mutation execution touching all three families
# at once rather than assumed from one.
# ---------------------------------------------------------------------------


async def test_confounded_state_is_reached_across_all_three_families(session: AsyncSession):
    """A second Juli run against the same product, inside the first
    execution's post window, marks the reading `confounded` — every
    numeric field goes `None`, not merely percent-suppressed. The first
    execution is a price+title+description run so `gmv` (revenue_orders),
    `impressions` (impressions_ctr), and `conversion_rate` (conversion) all
    confound together in the same run — proving the state truly is
    per-execution, not something only demonstrated on one metric."""
    shop = await make_shop(session, phone_suffix="1045confall", name="Confounded Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-confounded-all"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="confa1",
        price_update=True,
        title="Tiêu đề mới cho sản phẩm",
        description="Mô tả mới cho sản phẩm",
    )
    # A second run on the SAME product, inside execution's post window.
    await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T + timedelta(days=3),
        approval_suffix="confa2",
    )
    await add_daily_rows(session, shop, product_id, _SERIES_START, _SERIES_END, gmv_base=gmv_base)
    await add_control_siblings(
        session,
        shop,
        scales=[Decimal("0.8"), Decimal("1.0"), Decimal("1.2")],
        base=gmv_base,
        family="gmv",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-confa",
        created=_T - timedelta(days=60),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    metrics_seen = {r.metric for r in rows}
    assert {"gmv", "impressions", "conversion_rate"} <= metrics_seen, (
        f"expected all three metric families' readings on this multi-mutation run, "
        f"got {metrics_seen}"
    )
    for row in rows:
        assert row.confidence == "confounded"
        assert row.pre is None
        assert row.post is None
        assert row.incremental is None
        assert row.impact_pct is None


# ---------------------------------------------------------------------------
# pre = 0 — the target's OWN pre-period value is zero (a distinct axis from
# below-floor: volume can clear the floor while the metric itself is
# silent). Demonstrated on conversion_rate (a rate family, ADR-077's own
# named scenario: real traffic, zero purchases) AND revenue_orders (a real
# order/impression volume with zero currency GMV recorded).
# ---------------------------------------------------------------------------


async def test_pre_zero_suppresses_the_percent_form_only_conversion(session: AsyncSession):
    """`pre = 0`: plenty of visitor volume (clears the conversion family's
    `>= 20 visitors/day` floor) but a target `conversion_rate` of exactly
    `0.00` across the whole pre-period (a real, if unlucky, business
    scenario — traffic with zero purchases). `impact_pct` must suppress
    while confidence stays neither `suppressed` nor `confounded` — a state
    distinct from both, per `compute.compute_impact_pct`'s own documented
    precedence rules."""
    shop = await make_shop(session, phone_suffix="1045prezero", name="Pre Zero Shop")
    product_id = "prod-pre-zero"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix="prezero",
        price_update=False,
        description="Updated description copy",
    )
    conversion_by_day: dict = {}
    current = _SERIES_START
    while current <= _SERIES_END:
        conversion_by_day[current] = Decimal("0.00") if current < _T else Decimal("0.02")
        current += timedelta(days=1)
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        visitors_per_day=25,
        conversion_rate=conversion_by_day,
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    conv_rows = [r for r in rows if r.metric == "conversion_rate"]
    assert conv_rows, "expected a conversion_rate reading for the description mutation"
    for row in conv_rows:
        assert row.pre == Decimal("0.00")
        assert row.impact_pct is None
        assert row.confidence not in ("suppressed", "confounded"), (
            "pre=0 is a distinct suppression axis from below-floor/confounded — "
            f"got confidence={row.confidence!r}, which would collapse the distinction"
        )


async def test_pre_zero_suppresses_the_percent_form_only_revenue_orders(session: AsyncSession):
    """Same axis, on `gmv`: plenty of order volume (clears the revenue
    family's `>= 1 order/day` floor via `sku_orders`) but `gmv` itself is
    exactly `0.00` across the whole pre-period — e.g. every pre-period
    order was fully refunded/voided at zero net value, a real if unusual
    business scenario, structurally distinct from having no orders at
    all."""
    shop = await make_shop(session, phone_suffix="1045przrev", name="Pre Zero Shop Rev")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-pre-zero-rev"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="przrev"
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _T - timedelta(days=1),
        gmv_constant=Decimal("0.00"),
        sku_orders_per_day=8,  # clears the >=1/day floor even though gmv itself is 0
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _T + timedelta(days=1),
        _SERIES_END,
        gmv_base=gmv_base,
        sku_orders_per_day=8,
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.pre == Decimal("0.00")
        assert row.impact_pct is None
        assert row.confidence not in ("suppressed", "confounded"), (
            "pre=0 is a distinct suppression axis from below-floor/confounded — "
            f"got confidence={row.confidence!r}, which would collapse the distinction"
        )
