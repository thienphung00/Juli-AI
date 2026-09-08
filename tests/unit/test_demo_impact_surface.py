"""RED: Demo impact surface wires real package with synthetic series (issue #1768, ADR-099).

This test implements the acceptance criteria:
1. Every number on the demo's impact surface is traceable to a compute.py call
2. A seeded product whose cohort fails the control pool renders the refusal, not a placeholder
3. Readiness is checked before the surface promises anything
4. Copy strings come from copy.py, not the frontend
5. Swapping the series source requires touching exactly one function
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import Product, Shop
from juli_backend.models.models import ImpactReading
from juli_backend.services.impact import render_reading
from juli_backend.services.impact.confidence import ConfidenceResult
from juli_backend.services.impact.metric_map import (
    METRIC_MAP,
    MutationKind,
    RawDailyRecord,
)
from juli_backend.services.seeds.demo_cohort import seed_demo_cohort_for_impact


async def _seed_tool_execution(session, shop_id):
    """A reading hangs off a tool execution — `tool_execution_id` is NOT NULL.

    That is the schema stating something real: an impact reading answers "what did
    THIS write do", so a reading with no execution would be a measurement of
    nothing. The demo's execution row is as real as production's; only the SERIES
    it is measured over are synthetic.
    """
    import uuid as _uuid
    from datetime import UTC
    from datetime import datetime as _dt

    from juli_backend.models.models import ToolExecution

    execution = ToolExecution(
        id=_uuid.uuid4(),
        shop_id=shop_id,
        approval_id="agent-ledger:demo-impact-surface",
        tool_name="update_product_price",
        payload_json="{}",
        status="succeeded",
        created_at=_dt.now(UTC),
        updated_at=_dt.now(UTC),
    )
    session.add(execution)
    await session.flush()
    return execution.id


@pytest_asyncio.fixture
async def demo_shop(session: AsyncSession, monkeypatch) -> tuple[uuid.UUID, Shop]:
    """Seed a demo shop with cohort."""
    demo_shop_id_str = str(uuid.uuid4())
    monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id_str)
    demo_shop_id = uuid.UUID(demo_shop_id_str)

    await seed_demo_cohort_for_impact(session)

    shop_result = await session.execute(select(Shop).where(Shop.id == demo_shop_id))
    shop = shop_result.scalar()
    assert shop, "Demo shop must exist after seed"
    return demo_shop_id, shop


@pytest_asyncio.fixture
async def target_product(session: AsyncSession, demo_shop: tuple) -> Product:
    """Get the target product from the seeded cohort."""
    demo_shop_id, _ = demo_shop
    result = await session.execute(
        select(Product).where(
            (Product.shop_id == demo_shop_id) & (Product.tiktok_product_id == "cohort-target")
        )
    )
    product = result.scalar()
    assert product, "Target product must exist"
    return product


@pytest.mark.asyncio
async def test_demo_impact_surface_computes_readings_from_synthetic_series(
    session: AsyncSession, demo_shop: tuple, target_product: Product
) -> None:
    """AC1: Every number is traceable to compute.py call — readings are persisted."""
    demo_shop_id, _ = demo_shop

    # This is the spec: call one function that does everything
    # RED: this function does not exist yet
    from juli_backend.services.demo_decisions.impact_surface import (
        compute_and_persist_demo_readings,
    )

    t = date.today()

    # Compute readings for the target product
    tool_execution_id = await _seed_tool_execution(session, demo_shop_id)
    await compute_and_persist_demo_readings(
        session,
        shop_id=demo_shop_id,
        tool_execution_id=tool_execution_id,
        mutation_kind=MutationKind.PRICE,
        reference_date=t,
    )

    # Verify readings were persisted
    readings_result = await session.execute(
        select(ImpactReading)
        .where(ImpactReading.tool_execution_id == tool_execution_id)
        .order_by(ImpactReading.computed_at.desc())
    )
    readings = readings_result.scalars().all()

    # At minimum, readings should exist
    assert len(readings) > 0, "Demo readings must be persisted"

    # All persisted readings must carry series_source='synthetic'
    for reading in readings:
        assert reading.series_source == "synthetic", (
            f"Reading must have series_source='synthetic', got {reading.series_source}"
        )

    # The tier must come from `confidence.py`, not from a literal in the wiring.
    # `confidence` is assigned PER METRIC, so a real computation over one product
    # yields more than one tier across its metrics — today `gmv` tiers higher than
    # `sku_orders` and `gmv_per_order` on the same series. A hardcoded tier cannot
    # produce that spread. Verified by mutation: replacing `confidence=tier.tier`
    # with a constant passes every other assertion in this file and fails only here.
    tiers = {r.confidence for r in readings}
    assert len(tiers) > 1, (
        f"every metric tiered identically ({tiers}) — confidence is computed per "
        f"metric, so one tier across all of them means the wiring is not calling "
        f"compute_confidence"
    )


@pytest.mark.asyncio
async def test_demo_readiness_check_honored_before_promising_reading(
    session: AsyncSession, demo_shop: tuple
) -> None:
    """AC3: Readiness is checked first; if not ready, no promise is made."""
    demo_shop_id, _ = demo_shop

    # Try to compute readings for a product that doesn't exist
    # This should fail the readiness check, not produce a placehoder number
    fake_product_id = "nonexistent-product"
    t = date.today()

    # Readiness should return not-ready for nonexistent product
    from juli_backend.services.impact import check_readiness

    result = await check_readiness(
        session, shop_id=demo_shop_id, tiktok_product_id=fake_product_id, reference_date=t
    )
    assert not result.is_ready, "Nonexistent product should not be ready"


@pytest.mark.asyncio
async def test_demo_copy_comes_from_copy_py_not_frontend(
    session: AsyncSession, demo_shop: tuple, target_product: Product
) -> None:
    """AC4: Seller-facing copy comes from copy.py, not the UI layer."""
    demo_shop_id, _ = demo_shop

    from juli_backend.services.demo_decisions.impact_surface import (
        compute_and_persist_demo_readings,
    )

    t = date.today()

    tool_execution_id = await _seed_tool_execution(session, demo_shop_id)
    await compute_and_persist_demo_readings(
        session,
        shop_id=demo_shop_id,
        tool_execution_id=tool_execution_id,
        mutation_kind=MutationKind.PRICE,
        reference_date=t,
    )

    # Fetch readings
    readings_result = await session.execute(
        select(ImpactReading)
        .where(ImpactReading.tool_execution_id == tool_execution_id)
        .order_by(ImpactReading.computed_at.desc())
    )
    readings = readings_result.scalars().all()

    # Seller-facing copy must come from `copy.py`, which is the single source of
    # truth for what each tier says. The earlier version of this test called
    # `render_reading(reading)` and asserted the result was a `str` — the real
    # signature is `(metric, confidence, incremental)` and it returns a
    # `RenderedReadingCopy`, so that test could never have run. It passed review
    # by looking like coverage.
    spec_by_key = {
        m.key: m
        for m in [METRIC_MAP[MutationKind.PRICE].primary, *METRIC_MAP[MutationKind.PRICE].secondary]
    }

    assert readings, "no readings persisted, so this proves nothing about copy"
    for reading in readings:
        spec = spec_by_key[reading.metric]
        rendered = render_reading(
            spec,
            ConfidenceResult(
                metric=reading.metric,
                tier=reading.confidence,
                volume=None,
                noise_band=None,
                used_fallback=False,
                fallback_reason=None,
            ),
            Decimal(reading.incremental) if reading.incremental is not None else None,
        )
        assert rendered.metric == reading.metric
        assert rendered.tier == reading.confidence, (
            f"copy.py rendered tier {rendered.tier!r} for a reading persisted as "
            f"{reading.confidence!r} — the surface would tell the seller the wrong thing"
        )
        # A refusal tier must still say something. An empty string here is the UI
        # being handed nothing and inventing its own fallback, which is the exact
        # failure this slice exists to prevent.
        assert rendered.text.strip(), (
            f"copy.py returned empty text for tier {reading.confidence!r}; "
            f"a refusal must still be legible to a seller"
        )


@pytest.mark.asyncio
async def test_series_source_isolation_function_exists(
    session: AsyncSession, demo_shop: tuple
) -> None:
    """AC5: Swapping synthetic for real requires changing exactly one function."""
    # This documents the ONE function that needs to change on migration
    from juli_backend.services.demo_decisions.impact_surface import (
        synthetic_series_for,
    )

    demo_shop_id, _ = demo_shop
    target_product_result = await session.execute(
        select(Product).where(
            (Product.shop_id == demo_shop_id) & (Product.tiktok_product_id == "cohort-target")
        )
    )
    target_product = target_product_result.scalar()
    assert target_product, "Target must exist"

    # This function is the ONLY seam that needs to change when migrating from synthetic to real
    daily_series = await synthetic_series_for(session, target_product, reference_date=date.today())

    # Should return RawDailyRecord mapping
    assert isinstance(daily_series, dict), "synthetic_series_for must return dict"
    for date_key, record in daily_series.items():
        assert isinstance(date_key, date), "Keys must be dates"
        assert isinstance(record, RawDailyRecord), "Values must be RawDailyRecord"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product", "why"),
    [
        ("cohort-below-floor", "volume is under the metric's floor"),
        ("cohort-degenerate", "the arithmetic has no denominator"),
    ],
)
async def test_refusals_are_persisted_as_refusals_not_as_confident_numbers(
    session: AsyncSession, demo_shop: tuple, product: str, why: str
) -> None:
    """ADR-099 decision 4: the cohort deliberately contains products the algorithm
    must refuse, and the demo shows those refusals.

    This is the test that catches a tier that does not come from `confidence.py`.
    The sibling tests above assert readings exist and carry `series_source`, which
    a hardcoded ``confidence="cao"`` passes cleanly — verified by mutation. Only a
    product whose *correct* answer is a refusal can tell a computed tier apart
    from a constant one.
    """
    demo_shop_id, _ = demo_shop
    from juli_backend.services.demo_decisions.impact_surface import (
        compute_and_persist_demo_readings,
    )

    tool_execution_id = await _seed_tool_execution(session, demo_shop_id)
    readings = await compute_and_persist_demo_readings(
        session,
        shop_id=demo_shop_id,
        tool_execution_id=tool_execution_id,
        mutation_kind=MutationKind.PRICE,
        reference_date=date.today(),
        tiktok_product_id=product,
    )

    assert readings, f"{product} produced no reading at all; a refusal is still a reading"

    refusal_tiers = {"below_floor", "suppressed", "confounded", "thap"}
    tiers = {r.confidence for r in readings}
    assert tiers & refusal_tiers, (
        f"{product} was persisted as {tiers} — but {why}, so the algorithm cannot "
        f"honestly claim confidence. A tier that never varies is a hardcoded tier."
    )

    # A refusal must not smuggle a number through alongside it.
    for reading in readings:
        if reading.confidence in refusal_tiers - {"thap"}:
            assert reading.impact_pct is None, (
                f"{product} refused with tier {reading.confidence!r} but still "
                f"persisted impact_pct={reading.impact_pct} — a refusal that carries "
                f"a number is the placeholder ADR-099 forbids"
            )
