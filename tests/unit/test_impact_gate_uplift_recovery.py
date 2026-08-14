"""ADR-077 §6 gate suite — synthetic-uplift recovery (#1045, issue area 1).

A known injected uplift must be recovered by the control-adjusted formula,
and a zero-uplift twin (identical fixture, no injected change) must recover
~0. Both go through the real `run_daily_impact_reader` pipeline against a
target product plus five correlated same-shop siblings (the full control
path, not the fallback) — see `_impact_gate_support.py` for fixture
provenance.

**All three ADR-077 decision-1 metric families, not GMV alone.** The
reference implementation of this gate suite (`feature/agent-w2-pim-wave`,
`cb4e949a`) drove uplift recovery through `gmv` only — the exact gap named
in this issue's re-run scope (#1062's own regression docstring: "every test
in the block ... drove only the GMV/PRICE family"). This file recovers a
known uplift on `impressions` (SEO/title mutation) and `conversion_rate`
(description mutation) as well, each through its own correlated control
cohort — proving `select_control_pool`'s `volume_of` handling is exercised
for a *rate* metric on the recovery path itself, not only in the
suppression matrix's dedicated floor test.
"""

from __future__ import annotations

import json
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
    anchor_conversion_rate_proxy,
    anchor_ctr,
    anchor_gmv_per_order,
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
_TOLERANCE = Decimal("0.01")  # 1 percentage point
_SCALES = [Decimal("0.6"), Decimal("0.8"), Decimal("1.0"), Decimal("1.2"), Decimal("1.4")]
_INJECTED_UPLIFT = Decimal("1.30")  # a known +30% incremental impact
_NO_UPLIFT = Decimal("1.00")


async def _setup_revenue_orders(
    session: AsyncSession, *, approval_suffix: str, product_id: str, uplift: Decimal
) -> ToolExecution:
    """revenue/orders family: `gmv`, driven by a price mutation."""
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
        base=gmv_base,
        family="gmv",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix=f"ctrl-{approval_suffix}",
        created=_T - timedelta(days=60),
    )
    return execution


async def _setup_impressions_ctr(
    session: AsyncSession, *, approval_suffix: str, product_id: str, uplift: Decimal
) -> ToolExecution:
    """impressions/CTR family: `impressions`, driven by an SEO/title
    mutation (ADR-077 decision 1's SEO row: primary `impressions`)."""
    shop = await make_shop(
        session, phone_suffix=f"1045{approval_suffix}", name=f"Uplift Shop {approval_suffix}"
    )
    impressions_base = impressions_base_default()

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix=approval_suffix,
        price_update=False,
        title="Áo thun cotton cao cấp - phiên bản mới",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        impressions_base=impressions_base,
        shock_from=_T + timedelta(days=1),
        shock=uplift,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=impressions_base,
        family="impressions",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix=f"ctrl-{approval_suffix}",
        created=_T - timedelta(days=60),
    )
    return execution


async def _setup_ctr(
    session: AsyncSession, *, approval_suffix: str, product_id: str, uplift: Decimal
) -> ToolExecution:
    """impressions/CTR family: `ctr` itself (a *rate* metric, distinct from
    `impressions` — a count) — driven by an image mutation (ADR-077
    decision 1's Image row: primary `ctr`). `#1062`'s regression docstring
    names `ctr` and `conversion_rate` explicitly as the two metrics whose
    own values can never clear a count-calibrated volume floor; the
    `impressions` variant above shares this family's floor config but is
    itself a count, so it does not exercise this specific failure mode —
    this function closes that gap directly."""
    shop = await make_shop(
        session, phone_suffix=f"1045{approval_suffix}", name=f"Uplift Shop {approval_suffix}"
    )
    ctr_base = anchor_ctr()

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix=approval_suffix,
        price_update=False,
        image=True,
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        ctr_base=ctr_base,
        shock_from=_T + timedelta(days=1),
        shock=uplift,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=ctr_base,
        family="ctr",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix=f"ctrl-{approval_suffix}",
        created=_T - timedelta(days=60),
    )
    return execution


async def _setup_conversion(
    session: AsyncSession, *, approval_suffix: str, product_id: str, uplift: Decimal
) -> ToolExecution:
    """conversion family: `conversion_rate` (a *rate* metric), driven by a
    description mutation (ADR-077 decision 1's Description row: primary
    `conversion_rate`)."""
    shop = await make_shop(
        session, phone_suffix=f"1045{approval_suffix}", name=f"Uplift Shop {approval_suffix}"
    )
    conversion_base = anchor_conversion_rate_proxy()

    await make_product(session, shop, product_id, created=_T - timedelta(days=60))
    execution = await make_execution(
        session,
        shop,
        tiktok_product_id=product_id,
        t=_T,
        approval_suffix=approval_suffix,
        price_update=False,
        description="Chất liệu cotton 100%, thoáng mát, form rộng rãi.",
    )
    await add_daily_rows(
        session,
        shop,
        product_id,
        _SERIES_START,
        _SERIES_END,
        conversion_rate_base=conversion_base,
        shock_from=_T + timedelta(days=1),
        shock=uplift,
    )
    await add_control_siblings(
        session,
        shop,
        scales=_SCALES,
        base=conversion_base,
        family="conversion_rate",
        start=_SERIES_START,
        end=_SERIES_END,
        name_prefix=f"ctrl-{approval_suffix}",
        created=_T - timedelta(days=60),
    )
    return execution


async def _assert_recovered(
    session: AsyncSession, execution: ToolExecution, *, metric: str, expected_pct: Decimal
) -> None:
    result = await run_daily_impact_reader(session, REFERENCE_DATE)
    assert result.readings_written > 0

    rows = await readings_for(session, execution.id)
    metric_rows = [r for r in rows if r.metric == metric]
    assert metric_rows, f"expected at least one {metric!r} reading"
    for row in metric_rows:
        assert row.confidence not in ("suppressed", "confounded")
        # The full K-nearest-correlated-siblings control path must actually
        # have run — a fallback (constant-1 control) reading recovers the
        # target's own raw pre/post delta by construction and would make
        # "recovery" meaningless as evidence for THIS metric's control-pool
        # selection specifically (the #1062 seam: a rate metric silently
        # falling back to plain pre/post because its own values, not the
        # family's volume indicator, got compared against the count floor).
        control_set = json.loads(row.control_set_json)
        assert control_set["used_fallback"] is False, (
            f"[{metric}] expected the real control path, got a fallback reading "
            f"(reason={control_set['fallback_reason']!r}) — recovery would be meaningless"
        )
        assert row.impact_pct is not None
        assert abs(row.impact_pct - expected_pct) < _TOLERANCE, (
            f"[{metric}] expected recovered impact_pct near {expected_pct}, got {row.impact_pct}"
        )


# ---------------------------------------------------------------------------
# revenue_orders (gmv)
# ---------------------------------------------------------------------------


async def test_known_injected_uplift_is_recovered_revenue_orders(session: AsyncSession):
    execution = await _setup_revenue_orders(
        session, approval_suffix="rev-up", product_id="prod-uplift-rev", uplift=_INJECTED_UPLIFT
    )
    await _assert_recovered(session, execution, metric="gmv", expected_pct=Decimal("0.30"))


async def test_zero_uplift_twin_recovers_approximately_zero_revenue_orders(session: AsyncSession):
    execution = await _setup_revenue_orders(
        session, approval_suffix="rev-no", product_id="prod-no-uplift-rev", uplift=_NO_UPLIFT
    )
    await _assert_recovered(session, execution, metric="gmv", expected_pct=Decimal("0.00"))


# ---------------------------------------------------------------------------
# impressions_ctr (impressions)
# ---------------------------------------------------------------------------


async def test_known_injected_uplift_is_recovered_impressions_ctr(session: AsyncSession):
    execution = await _setup_impressions_ctr(
        session, approval_suffix="imp-up", product_id="prod-uplift-imp", uplift=_INJECTED_UPLIFT
    )
    await _assert_recovered(session, execution, metric="impressions", expected_pct=Decimal("0.30"))


async def test_zero_uplift_twin_recovers_approximately_zero_impressions_ctr(
    session: AsyncSession,
):
    execution = await _setup_impressions_ctr(
        session,
        approval_suffix="imp-no",
        product_id="prod-no-uplift-imp",
        uplift=_NO_UPLIFT,
    )
    await _assert_recovered(session, execution, metric="impressions", expected_pct=Decimal("0.00"))


# ---------------------------------------------------------------------------
# impressions_ctr (ctr) — the family's OWN rate metric, distinct from the
# impressions count tested above. See `_setup_ctr`'s docstring for why this
# is not redundant with the impressions variant.
# ---------------------------------------------------------------------------


async def test_known_injected_uplift_is_recovered_ctr(session: AsyncSession):
    execution = await _setup_ctr(
        session, approval_suffix="ctr-up", product_id="prod-uplift-ctr", uplift=_INJECTED_UPLIFT
    )
    await _assert_recovered(session, execution, metric="ctr", expected_pct=Decimal("0.30"))


async def test_zero_uplift_twin_recovers_approximately_zero_ctr(session: AsyncSession):
    execution = await _setup_ctr(
        session, approval_suffix="ctr-no", product_id="prod-no-uplift-ctr", uplift=_NO_UPLIFT
    )
    await _assert_recovered(session, execution, metric="ctr", expected_pct=Decimal("0.00"))


# ---------------------------------------------------------------------------
# conversion (conversion_rate) — the rate family
# ---------------------------------------------------------------------------


async def test_known_injected_uplift_is_recovered_conversion(session: AsyncSession):
    execution = await _setup_conversion(
        session, approval_suffix="conv-up", product_id="prod-uplift-conv", uplift=_INJECTED_UPLIFT
    )
    await _assert_recovered(
        session, execution, metric="conversion_rate", expected_pct=Decimal("0.30")
    )


async def test_zero_uplift_twin_recovers_approximately_zero_conversion(session: AsyncSession):
    execution = await _setup_conversion(
        session,
        approval_suffix="conv-no",
        product_id="prod-no-uplift-conv",
        uplift=_NO_UPLIFT,
    )
    await _assert_recovered(
        session, execution, metric="conversion_rate", expected_pct=Decimal("0.00")
    )
