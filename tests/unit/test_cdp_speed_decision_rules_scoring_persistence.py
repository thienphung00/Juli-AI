"""Issue #715 (B-3) — wiring the continuous-trigger seam to persistence.

Meta routing correction on #715: B-3 shipped ``persist_scoring_result`` as an
idempotent, status-preserving persistence boundary
(``services/action_cards/persist.py``), but nothing on the continuous path
(``decision_rules_scoring_stage``) called it — candidates scored by a webhook
or reconcile run were computed and thrown away. This module closes that gap by
wiring ``decision_rules_scoring_stage`` to ``persist_scoring_result``, so
#715's own acceptance criteria are provable end to end:

AC1 → repeated webhook bursts for the same ``workflow_key`` do not duplicate
      Action Card rows (idempotent upsert on the continuous path).
AC3 → ``computed_at`` is persisted and queryable per card, sourced from the
      continuous-trigger scoring run.

Scope: persistence only. The emission budget (active cap / cooldown /
novelty) is #716 (B-4) and is not exercised here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Order, Product, Return, Shop, User
from juli_backend.services.aggregates.types import HealthDataSource, ShopLifecycleContext
from juli_backend.services.cdp_speed.decision_rules_scoring import decision_rules_scoring_stage
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan
from juli_backend.services.scoring.types import DailyScoringResult

COMPUTED_AT = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)


def _empty_fetch_plan(shop_key: str) -> TargetedFetchPlan:
    return TargetedFetchPlan(catalog_id=None, shop_id=shop_key, resources=())


def _make_job(shop: Shop, *, idempotency_key: str) -> SharedComputeJob:
    return SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="webhook_catalog:1",
        fetch_plan=_empty_fetch_plan(shop.tiktok_shop_id),
        idempotency_key=idempotency_key,
    )


@pytest_asyncio.fixture
async def shop_with_synced_data(session, user_id):
    """Same fixture shape as the B-2 golden-parity tests (mid/large shop)."""
    user = User(id=user_id, phone="+84901715715")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="B-3 Wiring Shop",
        tiktok_shop_id="tiktok_shop_715_wiring",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add_all([user, shop])
    now = COMPUTED_AT
    products = [
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-715-a",
            name="Widget A",
            status="ACTIVE",
            revenue=Decimal("800000"),
            units_sold=40,
            update_time=now,
        ),
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-715-b",
            name="Widget B",
            status="ACTIVE",
            revenue=Decimal("200000"),
            units_sold=10,
            update_time=now,
        ),
    ]
    orders = [
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id=f"ord-715-{index}",
            status="COMPLETED",
            total_amount=Decimal("150000"),
            currency="VND",
            update_time=now,
        )
        for index in range(1, 6)
    ]
    returns = [
        Return(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_return_id="ret-715-1",
            tiktok_order_id="ord-715-1",
            return_type="refund",
            refund_amount=Decimal("10000"),
            status="COMPLETED",
            update_time=now,
        ),
    ]
    session.add_all([*products, *orders, *returns])
    await session.flush()
    return shop


async def _cards_for(session, shop_id: uuid.UUID) -> list[ActionCard]:
    stmt = select(ActionCard).where(ActionCard.shop_id == shop_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


class TestContinuousTriggerPersistsScoringCandidates:
    """The scoring stage now durably persists what it computes."""

    @pytest.mark.asyncio
    async def test_scoring_stage_persists_action_cards(self, session, shop_with_synced_data):
        lifecycle = ShopLifecycleContext(
            probation_status="graduated",
            health_data_source=HealthDataSource.PROXY,
        )
        job = _make_job(shop_with_synced_data, idempotency_key="job-715-persist")

        result = await decision_rules_scoring_stage(
            session, job, lifecycle=lifecycle, computed_at=COMPUTED_AT
        )
        await session.flush()

        assert len(result.recommendations.recommended_workflows) > 0, (
            "fixture must produce at least one ranked card"
        )

        cards = await _cards_for(session, shop_with_synced_data.id)
        persisted_keys = {card.workflow_key for card in cards}
        expected_keys = {rec.workflow_key for rec in result.recommendations.recommended_workflows}
        assert persisted_keys == expected_keys

    @pytest.mark.asyncio
    async def test_scoring_stage_still_returns_the_daily_scoring_result(
        self, session, shop_with_synced_data
    ):
        """Persistence must not change the stage's return contract — the
        orchestrator seam and B-2's golden-parity tests depend on the raw
        DailyScoringResult still coming back unchanged."""
        job = _make_job(shop_with_synced_data, idempotency_key="job-715-return-contract")

        result = await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        assert isinstance(result, DailyScoringResult)


class TestBurstIdempotencyOnTheContinuousPath:
    """AC1 — repeated webhook bursts for the same workflow_key do not
    duplicate Action Card rows, proven through the continuous-trigger seam
    itself (not just direct calls to persist_scoring_result)."""

    @pytest.mark.asyncio
    async def test_repeated_scoring_stage_runs_do_not_duplicate_rows(
        self, session, shop_with_synced_data
    ):
        job_1 = _make_job(shop_with_synced_data, idempotency_key="job-715-burst-1")
        job_2 = _make_job(shop_with_synced_data, idempotency_key="job-715-burst-2")
        job_3 = _make_job(shop_with_synced_data, idempotency_key="job-715-burst-3")

        for job in (job_1, job_2, job_3):
            await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)
            await session.flush()

        cards = await _cards_for(session, shop_with_synced_data.id)
        workflow_keys = [card.workflow_key for card in cards]
        assert len(workflow_keys) == len(set(workflow_keys)), (
            f"duplicate Action Card rows for the same workflow_key: {workflow_keys}"
        )
        assert len(cards) > 0


class TestComputedAtStampedOnTheContinuousPath:
    """AC3 — computed_at is persisted and queryable per card when the card
    was produced via the continuous-trigger seam."""

    @pytest.mark.asyncio
    async def test_computed_at_is_stamped_from_the_scoring_run(
        self, session, shop_with_synced_data
    ):
        job = _make_job(shop_with_synced_data, idempotency_key="job-715-computed-at")

        await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)
        await session.flush()

        cards = await _cards_for(session, shop_with_synced_data.id)
        assert cards, "fixture must produce at least one ranked card"
        for card in cards:
            assert card.computed_at is not None
            stamped = card.computed_at
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=UTC)
            assert stamped == COMPUTED_AT

        # Queryable directly via a column filter, per ADR-038 freshness semantics.
        stmt = select(ActionCard).where(ActionCard.computed_at == COMPUTED_AT)
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == len(cards)
