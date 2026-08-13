"""ADR-077 §6 gate suite — suppression/fallback matrix (#1045, issue area 4).

Every one of the five states ADR-077 decision 4 names must be independently
reachable and asserted: below-floor, <3 controls, <0.2 correlation,
confounded, pre=0. All five are reached below — none are skipped as
unreachable.
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


async def test_below_floor_state_is_reached(session: AsyncSession):
    """The target's own pre-period volume indicator (`sku_orders`, for the
    gmv family) sits under the floor (`>= 1 order/day`) — the reading must
    land as `suppressed`, the persisted vocabulary's below-floor state (see
    `workers/impact_reader/pipeline.py`'s `_PERSISTED_CONFIDENCE` map,
    which folds `TierOutcome.below_floor` into the `suppressed` column
    value). ``gmv`` itself is a real, nonzero, flat daily figure —
    deliberately decoupled from ``pre = 0`` (its own, separately-tested
    suppression axis below) so this test isolates the volume-floor gate
    specifically."""
    shop = await make_shop(session, phone_suffix="1045floor", name="Below Floor Shop")
    product_id = "prod-below-floor"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="floor"
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
        assert row.confidence == "suppressed", (
            "below-floor collapses into the persisted 'suppressed' confidence value"
        )
        # Below-floor is purely a confidence-tier decision layered on top of
        # `compute.py`'s numbers (`assign_confidence` never blanks a
        # `MetricReading`'s own fields — only `status == "confounded"` does
        # that, per `reading.compute_metric_reading`) — `pre` stays a real,
        # nonzero number here, proving the suppression is genuinely about
        # volume, not a `pre = 0` coincidence.
        assert row.pre == Decimal("50000.00")
        assert row.impact_pct is not None, (
            "pre is nonzero here — the % form is NOT suppressed, only the "
            "confidence tier is; below-floor and pre=0 are independent axes"
        )


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
        gmv_base=gmv_base,
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


async def test_low_mean_correlation_falls_back(session: AsyncSession):
    """>=3 candidates exist, but each is a flat (zero-variance) series over
    the pre-period — Pearson correlation degenerates to `0.0` for each
    (`control_pool._safe_correlation`'s documented degenerate case), so the
    mean of the top-K falls under `MIN_MEAN_CORRELATION=0.2` — must fall
    back with `fallback_reason == "low_mean_correlation"`, distinct from the
    insufficient-candidates trigger above even though both reach the same
    `thap`-capped fallback state."""
    shop = await make_shop(session, phone_suffix="1045corr", name="Low Correlation Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-low-correlation"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="corr"
    )
    await add_daily_rows(session, shop, product_id, _SERIES_START, _SERIES_END, gmv_base=gmv_base)
    for i in range(4):
        pid = f"ctrl-flat-{i}"
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
        assert control_set["mean_correlation"] == 0.0


async def test_confounded_state_is_reached(session: AsyncSession):
    """A second Juli run against the same product, inside the first
    execution's post window, marks the reading `confounded` — every
    numeric field goes `None`, not merely percent-suppressed."""
    shop = await make_shop(session, phone_suffix="1045conf", name="Confounded Shop")
    gmv_base = anchor_gmv_per_order() * Decimal(8)
    product_id = "prod-confounded"
    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session, shop, tiktok_product_id=product_id, t=_T, approval_suffix="conf-1"
    )
    # A second run on the SAME product, inside execution's post window.
    await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T + timedelta(days=3),
        approval_suffix="conf-2",
    )
    await add_daily_rows(session, shop, product_id, _SERIES_START, _SERIES_END, gmv_base=gmv_base)
    await add_control_siblings(
        session,
        shop,
        scales=[Decimal("0.8"), Decimal("1.0"), Decimal("1.2")],
        gmv_base=gmv_base,
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix="ctrl-conf",
        created=_T - timedelta(days=60),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    rows = await readings_for(session, execution.id)
    gmv_rows = [r for r in rows if r.metric == "gmv"]
    assert gmv_rows
    for row in gmv_rows:
        assert row.confidence == "confounded"
        assert row.pre is None
        assert row.post is None
        assert row.incremental is None
        assert row.impact_pct is None


async def test_pre_zero_suppresses_the_percent_form_only(session: AsyncSession):
    """`pre = 0`: plenty of visitor volume (clears the conversion family's
    `>= 20 visitors/day` floor) but a target `conversion_rate` of exactly
    `0.00` across the whole pre-period (a real, if unlucky, business
    scenario — traffic with zero purchases). `impact_pct` must suppress
    (reason `pre_zero` inside `compute.compute_impact_pct`, verified here
    indirectly: `impact_pct is None` while `pre == 0` and the reading is
    neither below-floor nor confounded) — a state distinct from both,
    per `compute.compute_impact_pct`'s own documented precedence rules."""
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
