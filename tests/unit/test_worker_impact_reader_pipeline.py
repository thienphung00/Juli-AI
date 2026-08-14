"""Daily impact-reader pipeline — ADR-077 decision 5 (#1044).

Exercises `workers.impact_reader.pipeline.run_daily_impact_reader` end to
end against realistic `ToolExecution` / `AnalyticsPerformanceInterval` rows
(sqlite in-memory `session`/`engine` fixtures from `tests/unit/conftest.py`)
rather than hand-built `MetricReading`/`MutationKind` values — the classifier
(`classify.py`) matters more than it looks (issue #1044 body): if it
misclassifies a real payload, a reading is computed correctly against the
wrong metric and looks entirely plausible, so this suite drives the pipeline
from realistic `listing.optimize_product` request payloads, the same shape
`services/execution/listing.py` actually dispatches.

**Single reference point (architect lock).** Every date in this file is
derived from one `REFERENCE_T` via `timedelta` — no `datetime.now()` is ever
mixed with a hardcoded calendar date.

**Deterministic confidence, by design of the fixtures, not by luck.** No
sibling `Product` rows are seeded, so `select_control_pool` always falls back
(`insufficient_candidates`) and `assign_confidence` caps every clearing-floor
reading at `"thap"` unconditionally — this suite is not re-testing #1041's
DiD math or #1043's tier boundaries (those have their own dedicated suites),
it is proving the I/O layer classifies, windows, and persists correctly.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    ImpactReading,
    Shop,
    ToolExecution,
    User,
)
from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader

# ---------------------------------------------------------------------------
# The one reference point every date in this file derives from.
# ---------------------------------------------------------------------------
REFERENCE_T = date(2026, 1, 15)

_PRE_START = REFERENCE_T - timedelta(days=14)
_PRE_END = REFERENCE_T - timedelta(days=1)
_POST_END_FINAL = REFERENCE_T + timedelta(days=14)

_TARGET_PRODUCT = "tt-target-multi"


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909991144")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Impact Reader Shop",
        tiktok_shop_id="tts_impact_reader",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _make_execution(
    shop_id: uuid.UUID,
    *,
    approval_id: str,
    payload: dict,
    t: date,
) -> ToolExecution:
    """A `listing.optimize_product` execution with `updated_at` pinned to
    `t` (ADR-077 decision 2's T) — see `queries.execution_t`'s documented
    `updated_at`-as-T proxy."""
    stamp = datetime(t.year, t.month, t.day, 12, 0, tzinfo=UTC)
    return ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop_id,
        approval_id=approval_id,
        tool_name="listing.optimize_product",
        payload_json=json.dumps(payload),
        status="succeeded",
        updated_at=stamp,
    )


def _daily_row(
    shop_id: uuid.UUID,
    product_id: str,
    day: date,
    *,
    gmv: str,
    sku_orders: int,
    items_sold: int,
    impressions: int,
    ctr: str,
    conversion_rate: str,
    visitors: int,
) -> AnalyticsPerformanceInterval:
    stamp = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"product:{product_id}:{day.isoformat()}",
        grain="product",
        start_date=day,
        tiktok_product_id=product_id,
        gmv=Decimal(gmv),
        gmv_currency="VND",
        ctr=Decimal(ctr),
        conversion_rate=Decimal(conversion_rate),
        sku_orders=sku_orders,
        items_sold=items_sold,
        impressions=impressions,
        visitors=visitors,
        update_time=stamp,
    )


def _seed_constant_series(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_id: str,
    *,
    start: date,
    end: date,
    pre_values: dict,
    post_values: dict,
) -> None:
    """Seed one product's daily series over `[start, end]`, excluding `T`
    itself (day T is never a real analytics row this reader would read from
    a pre/post window — ADR-077 decision 2 excludes it everywhere).

    Every pre day carries the identical `pre_values` and every post day the
    identical `post_values` — a deliberately *constant* daily series so the
    noise band (stddev of the pre-period treated-vs-scaled-control gap)
    always resolves to a real ``0`` rather than ``None``, keeping every
    fixture's confidence outcome pinned to the fallback-capped ``"thap"``
    rather than depending on emergent variance.
    """
    day = start
    while day <= end:
        if day != REFERENCE_T:
            values = pre_values if day < REFERENCE_T else post_values
            session.add(_daily_row(shop_id, product_id, day, **values))
        day += timedelta(days=1)


_PRE_VALUES = dict(
    gmv="100.00",
    sku_orders=5,
    items_sold=10,
    impressions=200,
    ctr="0.050000",
    conversion_rate="0.100000",
    visitors=50,
)
_POST_VALUES = dict(
    gmv="120.00",
    sku_orders=6,
    items_sold=12,
    impressions=220,
    ctr="0.060000",
    conversion_rate="0.110000",
    visitors=55,
)

_MULTI_MUTATION_PAYLOAD = {
    "product_id": _TARGET_PRODUCT,
    "price_update": {"price": "199000", "currency": "VND"},
    "image_uri": "https://cdn.example/tt-target-multi/hero.jpg",
    "edit_body": {
        "title": "Áo thun cotton cao cấp",
        "description": "Chất liệu cotton 100%, thoáng mát.",
    },
}


async def _readings(session: AsyncSession, execution_id: uuid.UUID) -> list[ImpactReading]:
    stmt = select(ImpactReading).where(ImpactReading.tool_execution_id == execution_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# All three ADR-077 decision-4 metric families, from one multi-mutation run.
# ---------------------------------------------------------------------------


async def test_multi_mutation_run_covers_all_three_metric_families(session: AsyncSession, shop):
    """A single price+image+title+description run must classify all four
    mutation kinds and persist readings spanning the revenue/orders,
    impressions/CTR, and conversion families — not GMV alone (the gap that
    let a HIGH-severity classification/volume-floor defect survive review
    on the reference implementation, ADR-079/#1062)."""
    execution = _make_execution(
        shop.id,
        approval_id="approval-multi-1",
        payload=_MULTI_MUTATION_PAYLOAD,
        t=REFERENCE_T,
    )
    session.add(execution)
    _seed_constant_series(
        session,
        shop.id,
        _TARGET_PRODUCT,
        start=_PRE_START,
        end=_POST_END_FINAL,
        pre_values=_PRE_VALUES,
        post_values=_POST_VALUES,
    )
    await session.flush()

    result = await run_daily_impact_reader(session, REFERENCE_T + timedelta(days=14))
    await session.commit()

    assert result.executions_scanned == 1
    assert result.executions_skipped_unclassified == 0

    readings = await _readings(session, execution.id)
    preliminary = {r.metric: r for r in readings if r.kind == "preliminary"}
    final = {r.metric: r for r in readings if r.kind == "final"}

    expected_metrics = {
        "gmv",  # PRICE primary, and the rollup (classify order: PRICE first)
        "sku_orders",  # PRICE secondary
        "gmv_per_order",  # PRICE secondary (derived)
        "ctr",  # IMAGE primary / SEO secondary
        "conversion_rate",  # IMAGE secondary / DESCRIPTION primary
        "impressions",  # SEO primary
        "items_sold",  # DESCRIPTION secondary
    }
    assert set(preliminary) == expected_metrics
    assert set(final) == expected_metrics

    # revenue/orders family
    assert preliminary["gmv"].pre == Decimal("100.00")
    assert preliminary["gmv"].post == Decimal("120.00")
    assert preliminary["gmv"].incremental == Decimal("20.00")
    assert preliminary["gmv"].confidence == "thap"
    # impressions/CTR family
    assert preliminary["impressions"].pre == Decimal("200.00")
    assert preliminary["impressions"].incremental == Decimal("20.00")
    assert preliminary["impressions"].confidence == "thap"
    # conversion family
    assert preliminary["conversion_rate"].pre == Decimal("0.100000")
    assert preliminary["conversion_rate"].confidence == "thap"

    # Every persisted confidence value is one of the five the model's CHECK
    # constraint allows (never the raw six-value TierOutcome's "below_floor").
    for row in readings:
        assert row.confidence in ("cao", "trung_binh", "thap", "suppressed", "confounded")
        assert row.control_set_json  # required column, always populated


# ---------------------------------------------------------------------------
# Idempotency — proven by actually running the pipeline twice.
# ---------------------------------------------------------------------------


async def test_pipeline_run_twice_writes_no_new_rows_and_values_unchanged(
    session: AsyncSession, shop
):
    execution = _make_execution(
        shop.id,
        approval_id="approval-idempotent-1",
        payload=_MULTI_MUTATION_PAYLOAD,
        t=REFERENCE_T,
    )
    session.add(execution)
    _seed_constant_series(
        session,
        shop.id,
        _TARGET_PRODUCT,
        start=_PRE_START,
        end=_POST_END_FINAL,
        pre_values=_PRE_VALUES,
        post_values=_POST_VALUES,
    )
    await session.flush()

    reference_date = REFERENCE_T + timedelta(days=14)

    first = await run_daily_impact_reader(session, reference_date)
    await session.commit()
    assert first.readings_written > 0

    first_snapshot = {
        (r.metric, r.kind): (r.pre, r.post, r.expected, r.incremental, r.impact_pct, r.confidence)
        for r in await _readings(session, execution.id)
    }
    first_row_count = len(first_snapshot)

    # Actually run it again — not merely relying on the unique constraint.
    second = await run_daily_impact_reader(session, reference_date)
    await session.commit()

    second_rows = await _readings(session, execution.id)
    second_snapshot = {
        (r.metric, r.kind): (r.pre, r.post, r.expected, r.incremental, r.impact_pct, r.confidence)
        for r in second_rows
    }

    assert second.readings_written == 0, "a second run over identical state must write nothing new"
    assert len(second_rows) == first_row_count, "row count must be unchanged across the re-run"
    assert second_snapshot == first_snapshot, "every (metric, kind) value must be unchanged"


# ---------------------------------------------------------------------------
# Elapse boundaries (ADR-077 decision 2's post windows: T+1..T+7 / T+1..T+14).
# ---------------------------------------------------------------------------


async def _run_boundary_case(session: AsyncSession, shop, reference_date: date):
    execution = _make_execution(
        shop.id,
        approval_id=f"approval-boundary-{reference_date.isoformat()}",
        payload={"product_id": _TARGET_PRODUCT, "price_update": {"price": "1"}},
        t=REFERENCE_T,
    )
    session.add(execution)
    await session.flush()
    await run_daily_impact_reader(session, reference_date)
    await session.commit()
    return execution


async def test_preliminary_not_due_at_t_plus_6(session: AsyncSession, shop):
    execution = await _run_boundary_case(session, shop, REFERENCE_T + timedelta(days=6))
    assert await _readings(session, execution.id) == []


async def test_preliminary_due_at_t_plus_7(session: AsyncSession, shop):
    execution = await _run_boundary_case(session, shop, REFERENCE_T + timedelta(days=7))
    readings = await _readings(session, execution.id)
    kinds = {r.kind for r in readings}
    assert "preliminary" in kinds
    assert "final" not in kinds


async def test_final_not_due_at_t_plus_13(session: AsyncSession, shop):
    execution = await _run_boundary_case(session, shop, REFERENCE_T + timedelta(days=13))
    readings = await _readings(session, execution.id)
    kinds = {r.kind for r in readings}
    assert "final" not in kinds


async def test_final_due_at_t_plus_14(session: AsyncSession, shop):
    execution = await _run_boundary_case(session, shop, REFERENCE_T + timedelta(days=14))
    readings = await _readings(session, execution.id)
    kinds = {r.kind for r in readings}
    assert "final" in kinds


# ---------------------------------------------------------------------------
# Confounded — a second Juli run inside the window.
# ---------------------------------------------------------------------------


async def test_second_run_inside_post_window_marks_reading_confounded(session: AsyncSession, shop):
    execution = _make_execution(
        shop.id,
        approval_id="approval-confounded-1",
        payload={"product_id": _TARGET_PRODUCT, "price_update": {"price": "1"}},
        t=REFERENCE_T,
    )
    second_touch = _make_execution(
        shop.id,
        approval_id="approval-confounded-touch",
        payload={"product_id": _TARGET_PRODUCT, "price_update": {"price": "2"}},
        t=REFERENCE_T + timedelta(days=3),  # inside [T+1, T+7]
    )
    session.add_all([execution, second_touch])
    _seed_constant_series(
        session,
        shop.id,
        _TARGET_PRODUCT,
        start=_PRE_START,
        end=_POST_END_FINAL,
        pre_values=_PRE_VALUES,
        post_values=_POST_VALUES,
    )
    await session.flush()

    await run_daily_impact_reader(session, REFERENCE_T + timedelta(days=7))
    await session.commit()

    readings = await _readings(session, execution.id)
    assert readings, "a confounded execution must still get a row, never silently skipped"
    for row in readings:
        assert row.confidence == "confounded"
        assert row.pre is None
        assert row.post is None
        assert row.incremental is None
        assert row.impact_pct is None


# ---------------------------------------------------------------------------
# Suppressed — the designed below-floor state, never an error.
# ---------------------------------------------------------------------------


async def test_missing_daily_rows_suppress_never_crash(session: AsyncSession, shop):
    """The reference-shop-only daily topup gap: a target product with zero
    `AnalyticsPerformanceInterval` rows must land as a real `ImpactReading`
    row with confidence='suppressed' and every numeric field `None` — never
    a crash and never a fabricated number."""
    execution = _make_execution(
        shop.id,
        approval_id="approval-suppressed-1",
        payload={"product_id": "tt-no-analytics-data", "price_update": {"price": "1"}},
        t=REFERENCE_T,
    )
    session.add(execution)
    await session.flush()

    result = await run_daily_impact_reader(session, REFERENCE_T + timedelta(days=7))
    await session.commit()

    assert result.readings_written > 0
    readings = await _readings(session, execution.id)
    assert readings
    for row in readings:
        assert row.confidence == "suppressed"
        assert row.pre is None
        assert row.incremental is None


# ---------------------------------------------------------------------------
# Unclassifiable payloads are skipped, never guessed.
# ---------------------------------------------------------------------------


async def test_unclassifiable_payload_is_skipped(session: AsyncSession, shop):
    execution = _make_execution(
        shop.id,
        approval_id="approval-unclassifiable-1",
        payload={"product_id": _TARGET_PRODUCT, "edit_body": {"category_id": "600001"}},
        t=REFERENCE_T,
    )
    session.add(execution)
    await session.flush()

    result = await run_daily_impact_reader(session, REFERENCE_T + timedelta(days=7))
    await session.commit()

    assert result.executions_skipped_unclassified == 1
    assert await _readings(session, execution.id) == []
