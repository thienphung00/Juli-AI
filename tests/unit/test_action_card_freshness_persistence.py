"""Action Card persistence-on-compute + freshness metadata — Issue #715 (B-3, ADR-038).

AC1 → idempotent upsert: repeated scoring runs for the same workflow_key do not
      duplicate Action Card rows.
AC2 → status-preservation: a card already in an in-flight status (approved /
      dismissed / executing) is not overwritten by a new candidate row from
      re-scoring.
AC3 → `computed_at` persisted as a real, queryable column (not only inside
      metadata_json), aligned with Analytics envelope freshness semantics
      (ADR-038 — see GoldKpiEnvelope.computed_at / AnalyticsKpiEnvelope.computed_at).
AC4 → negative: a failure partway through a scoring-triggered persistence run
      leaves last-good persisted cards untouched (no partial/corrupt writes).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Shop, User
from juli_backend.services.action_cards.persist import (
    IN_FLIGHT_STATUSES,
    persist_scoring_result,
)
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)
from juli_backend.services.scoring.types import (
    DailyScoringResult,
    ScoringSignals,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)


def _snapshot(shop_id: uuid.UUID) -> FeatureAggregateSnapshot:
    return FeatureAggregateSnapshot(
        shop_id=shop_id,
        shop_profile=ShopProfile.NEW_SHOP,
        health_data_source=HealthDataSource.PROXY,
        sps_score=None,
        vp_score=None,
        ahr_score=None,
        order_count=10,
        product_count=5,
        return_count=1,
        total_order_value=Decimal("100000"),
        total_product_revenue=Decimal("100000"),
        total_units_sold=10,
        return_rate_proxy=0.1,
        data_sources=["orders", "returns"],
    )


def _result(
    shop_id: uuid.UUID,
    computed_at: datetime,
    *,
    workflow_key: str = "reorder_sku_1",
    workflow_name: str = "Reorder SKU",
    priority: int = 1,
) -> DailyScoringResult:
    return DailyScoringResult(
        aggregates=_snapshot(shop_id),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis={},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.NEW_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key=workflow_key,
                    workflow_name=workflow_name,
                    priority=priority,
                    rationale="Test rationale",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                )
            ],
        ),
        reasoning_summaries=(),
    )


@pytest.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849150000715")
    s = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="B-3 Freshness Shop",
        tiktok_shop_id="tiktok_shop_715",
    )
    session.add_all([user, s])
    await session.flush()
    return s


async def _fetch(session, shop_id: uuid.UUID, workflow_key: str) -> ActionCard | None:
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == workflow_key,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_repeated_webhook_bursts_do_not_duplicate_rows(session, shop):
    """AC1: three back-to-back scoring runs for the same workflow_key upsert in place."""
    computed_at = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)

    for _ in range(3):
        result = _result(shop.id, computed_at)
        await persist_scoring_result(session, shop.id, result)
        await session.flush()

    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.workflow_key == "reorder_sku_1",
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1


@pytest.mark.parametrize("in_flight_status", ["approved", "executing", "dismissed"])
@pytest.mark.asyncio
async def test_inflight_status_not_overwritten_by_rescoring(session, shop, in_flight_status):
    """AC2: a card already approved/executing/dismissed is not clobbered by a re-score."""
    first_computed_at = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
    first_result = _result(shop.id, first_computed_at)
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, "reorder_sku_1")
    assert card is not None
    card.status = in_flight_status
    approved_marker = datetime(2026, 8, 8, 9, 30, tzinfo=UTC)
    card.approved_at = approved_marker
    await session.flush()

    second_computed_at = datetime(2026, 8, 8, 11, 0, tzinfo=UTC)
    second_result = _result(
        shop.id,
        second_computed_at,
        priority=5,
        workflow_name="Reorder SKU (rescored)",
    )
    cards = await persist_scoring_result(session, shop.id, second_result)
    await session.flush()

    # Still exactly one row for the workflow_key — the candidate was not
    # inserted as a duplicate alongside the in-flight card.
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.workflow_key == "reorder_sku_1",
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1

    persisted = rows[0]
    assert persisted.status == in_flight_status
    assert persisted.priority == 1  # unchanged from the original candidate
    assert persisted.title == "Reorder SKU"  # unchanged
    assert persisted.approved_at == approved_marker  # unchanged

    # persist_scoring_result still surfaces the (untouched) card in its return
    # value so callers can see the full candidate set for the run.
    assert any(c.workflow_key == "reorder_sku_1" for c in cards)


@pytest.mark.asyncio
async def test_computed_at_persisted_and_queryable(session, shop):
    """AC3: computed_at lands on a real column, independent of metadata_json."""
    computed_at = datetime(2026, 8, 8, 12, 34, 56, tzinfo=UTC)
    result = _result(shop.id, computed_at)

    await persist_scoring_result(session, shop.id, result)
    await session.flush()

    card = await _fetch(session, shop.id, "reorder_sku_1")
    assert card is not None
    assert card.computed_at is not None
    stored = card.computed_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert stored == computed_at

    # Queryable directly via a column filter — not just parseable out of JSON.
    stmt = select(ActionCard).where(ActionCard.computed_at == card.computed_at)
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == card.id


@pytest.mark.asyncio
async def test_scoring_failure_leaves_last_good_cards_untouched(session, shop):
    """AC4: a failure mid-run rolls back cleanly — no partial/corrupt writes.

    Seeds two already-persisted cards from a prior successful run, then a new
    scoring run: the first recommendation updates one of them in place, the
    second is malformed and blows up mid-persist. After the caller rolls back
    on that failure, neither the in-run update nor the untouched sibling card
    may show any trace of the failed run — the whole run is all-or-nothing.
    """
    # Capture the id before any rollback: session.rollback() expires ORM
    # instances, and a bare attribute access on an expired instance outside
    # of an active async round trip raises MissingGreenlet.
    shop_id = shop.id

    seed_computed_at = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    seed_result = DailyScoringResult(
        aggregates=_snapshot(shop_id),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=seed_computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis={},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.NEW_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key="last_good_key",
                    workflow_name="Last Good",
                    priority=1,
                    rationale="ok",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                ),
                WorkflowRecommendation(
                    workflow_key="rescored_key",
                    workflow_name="Original Title",
                    priority=1,
                    rationale="ok",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                ),
            ],
        ),
        reasoning_summaries=(),
    )
    await persist_scoring_result(session, shop_id, seed_result)
    await session.commit()

    last_good_before = await _fetch(session, shop_id, "last_good_key")
    rescored_before = await _fetch(session, shop_id, "rescored_key")
    assert last_good_before is not None
    assert rescored_before is not None
    snapshot = {
        "last_good_priority": last_good_before.priority,
        "last_good_computed_at": last_good_before.computed_at,
        "last_good_updated_at": last_good_before.updated_at,
        "rescored_priority": rescored_before.priority,
        "rescored_title": rescored_before.title,
        "rescored_computed_at": rescored_before.computed_at,
        "rescored_updated_at": rescored_before.updated_at,
    }

    # New scoring run: first recommendation updates "rescored_key" in place,
    # second is malformed (no workflow_key) and blows up mid-persist.
    bad_computed_at = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
    bad_result = DailyScoringResult(
        aggregates=_snapshot(shop_id),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=bad_computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis={},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.NEW_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key="rescored_key",
                    workflow_name="Rescored Title",
                    priority=9,
                    rationale="rescored",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                ),
                WorkflowRecommendation(
                    workflow_key=None,  # type: ignore[arg-type]
                    workflow_name="Broken Candidate",
                    priority=2,
                    rationale="boom",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                ),
            ],
        ),
        reasoning_summaries=(),
    )

    with pytest.raises(Exception):
        await persist_scoring_result(session, shop_id, bad_result)

    await session.rollback()

    # The in-run update to "rescored_key" must not have survived the
    # rollback — no partial write from the failed run leaks through.
    rescored_after = await _fetch(session, shop_id, "rescored_key")
    assert rescored_after is not None
    assert rescored_after.priority == snapshot["rescored_priority"]
    assert rescored_after.title == snapshot["rescored_title"]
    assert rescored_after.computed_at == snapshot["rescored_computed_at"]
    assert rescored_after.updated_at == snapshot["rescored_updated_at"]

    # The untouched sibling last-good card is exactly as it was before.
    last_good_after = await _fetch(session, shop_id, "last_good_key")
    assert last_good_after is not None
    assert last_good_after.priority == snapshot["last_good_priority"]
    assert last_good_after.computed_at == snapshot["last_good_computed_at"]
    assert last_good_after.updated_at == snapshot["last_good_updated_at"]


def test_in_flight_statuses_exported_and_cover_approved_dismissed_executing():
    assert IN_FLIGHT_STATUSES == frozenset({"approved", "dismissed", "executing"})
