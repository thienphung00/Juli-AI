"""Daily impact-reader pipeline — elapse boundaries, idempotency, and the
missing-daily-rows suppression trap (#1044, ADR-077 decision 5).

Every date in this module is derived from one injected anchor,
``REFERENCE_DATE`` — never ``date.today()``/``datetime.now()`` for anything
that participates in the elapsed-time logic under test — per the #1032
lesson: a frozen calendar date compared against real wall-clock time ages
out overnight and turns a passing suite red with no code change.
``REFERENCE_DATE`` IS the "now" the reader runs against (passed explicitly
as ``reference_date`` to ``run_daily_impact_reader``), so there is no wall
clock anywhere in this file's assertions.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    ImpactReading,
    Product,
    Shop,
    ToolExecution,
    User,
)

pytestmark = pytest.mark.asyncio

REFERENCE_DATE = date(2026, 3, 1)


def _anchor_dt(d: date = REFERENCE_DATE) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909991044")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Impact Reader Shop",
        tiktok_shop_id="tts_impact_reader",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


async def _make_product(
    session: AsyncSession, shop: Shop, tiktok_product_id: str, *, created: date
) -> Product:
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=tiktok_product_id,
        name=f"Product {tiktok_product_id}",
        status="active",
        tiktok_created_at=_anchor_dt(created),
        update_time=_anchor_dt(),
    )
    session.add(product)
    await session.flush()
    return product


async def _make_execution(
    session: AsyncSession,
    shop: Shop,
    *,
    tiktok_product_id: str,
    t: date,
    approval_suffix: str,
) -> ToolExecution:
    execution = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        approval_id=f"approval-1044-{approval_suffix}",
        tool_name="listing.optimize_product",
        payload_json=json.dumps(
            {
                "product_id": tiktok_product_id,
                "workflow_id": "optimize_product_2",
                "price_update": {"price": "19.99"},
            }
        ),
        status="succeeded",
        updated_at=_anchor_dt(t),
    )
    session.add(execution)
    await session.flush()
    return execution


async def _add_daily_rows(
    session: AsyncSession,
    shop: Shop,
    tiktok_product_id: str,
    start: date,
    end: date,
) -> None:
    current = start
    day_index = 0
    while current <= end:
        row = AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=shop.id,
            snapshot_key=f"impact-reader/{tiktok_product_id}/{current.isoformat()}",
            grain="product",
            start_date=current,
            tiktok_product_id=tiktok_product_id,
            gmv=Decimal("100.00") + Decimal(day_index % 3),
            sku_orders=5 + (day_index % 2),
            items_sold=10 + (day_index % 2),
            impressions=500 + day_index,
            ctr=Decimal("0.05"),
            conversion_rate=Decimal("0.10"),
            visitors=100 + day_index,
            update_time=_anchor_dt(current),
        )
        session.add(row)
        current += timedelta(days=1)
        day_index += 1
    await session.flush()


async def _readings_for(session: AsyncSession, execution_id: uuid.UUID) -> list[ImpactReading]:
    stmt = select(ImpactReading).where(ImpactReading.tool_execution_id == execution_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Elapse boundaries — both sides, both windows.
# ---------------------------------------------------------------------------


async def test_preliminary_not_due_at_t_plus_6(session: AsyncSession, shop: Shop):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=6)
    product = await _make_product(session, shop, "prod-t6", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="t6"
    )
    await _add_daily_rows(
        session,
        shop,
        product.tiktok_product_id,
        t - timedelta(days=14),
        t + timedelta(days=14),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)

    rows = await _readings_for(session, execution.id)
    assert rows == [], "T+6 must NOT be picked up — the preliminary window has not elapsed"


async def test_preliminary_due_at_t_plus_7(session: AsyncSession, shop: Shop):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=7)
    product = await _make_product(session, shop, "prod-t7", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="t7"
    )
    await _add_daily_rows(
        session,
        shop,
        product.tiktok_product_id,
        t - timedelta(days=14),
        t + timedelta(days=14),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)

    rows = await _readings_for(session, execution.id)
    assert rows, "T+7 MUST be picked up — the preliminary window has elapsed"
    assert all(r.kind == "preliminary" for r in rows)


async def test_final_not_due_at_t_plus_13(session: AsyncSession, shop: Shop):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=13)
    product = await _make_product(session, shop, "prod-t13", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="t13"
    )
    await _add_daily_rows(
        session,
        shop,
        product.tiktok_product_id,
        t - timedelta(days=14),
        t + timedelta(days=14),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)

    rows = await _readings_for(session, execution.id)
    assert not any(r.kind == "final" for r in rows), (
        "T+13 must NOT produce a final reading — the final window has not elapsed"
    )


async def test_final_due_at_t_plus_14(session: AsyncSession, shop: Shop):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=14)
    product = await _make_product(session, shop, "prod-t14", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="t14"
    )
    await _add_daily_rows(
        session,
        shop,
        product.tiktok_product_id,
        t - timedelta(days=14),
        t + timedelta(days=14),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)

    rows = await _readings_for(session, execution.id)
    assert any(r.kind == "final" for r in rows), (
        "T+14 MUST produce a final reading — the final window has elapsed"
    )


# ---------------------------------------------------------------------------
# Idempotency by execution — actually run the task twice.
# ---------------------------------------------------------------------------


async def test_running_reader_twice_writes_each_reading_once_and_raises_nothing(
    session: AsyncSession, shop: Shop
):
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=7)
    product = await _make_product(session, shop, "prod-idem", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="idem"
    )
    await _add_daily_rows(
        session,
        shop,
        product.tiktok_product_id,
        t - timedelta(days=14),
        t + timedelta(days=14),
    )

    await run_daily_impact_reader(session, REFERENCE_DATE)
    first_rows = await _readings_for(session, execution.id)
    assert first_rows, "first run should have written readings"
    first_pairs = sorted((r.metric, r.kind) for r in first_rows)

    # Must not raise — this is the actual assertion, not an inference from
    # the unique constraint's existence.
    await run_daily_impact_reader(session, REFERENCE_DATE)

    second_rows = await _readings_for(session, execution.id)
    second_pairs = sorted((r.metric, r.kind) for r in second_rows)
    assert second_pairs == first_pairs, "re-run must not write duplicate or extra readings"
    assert len(second_rows) == len(first_rows)


# ---------------------------------------------------------------------------
# The reference-shop gap: missing daily rows -> suppressed, never a crash.
# ---------------------------------------------------------------------------


async def test_missing_daily_rows_produce_suppressed_not_crash_not_fabricate(
    session: AsyncSession, shop: Shop
):
    """The daily analytics top-up covers only the reference shop — every
    other shop's ``analytics_performance_intervals`` can be entirely absent
    for the treated product. The reader must degrade to ``suppressed``, not
    raise, and must not invent numbers."""
    from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

    t = REFERENCE_DATE - timedelta(days=7)
    product = await _make_product(session, shop, "prod-nodata", created=t - timedelta(days=60))
    execution = await _make_execution(
        session, shop, tiktok_product_id=product.tiktok_product_id, t=t, approval_suffix="nodata"
    )
    # Deliberately no AnalyticsPerformanceInterval rows at all for this product.

    result = await run_daily_impact_reader(session, REFERENCE_DATE)  # must not raise

    rows = await _readings_for(session, execution.id)
    assert rows, "a run with unwritten readings due must still write rows, just suppressed ones"
    for reading in rows:
        assert reading.confidence == "suppressed", (
            f"missing daily rows must land as suppressed, got {reading.confidence!r}"
        )
        assert reading.pre is None
        assert reading.post is None
        assert reading.incremental is None
        assert reading.impact_pct is None
    assert result.readings_written >= len(rows)
