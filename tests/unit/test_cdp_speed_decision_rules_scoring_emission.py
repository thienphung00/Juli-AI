"""Issue #716 (B-4) — Meta routing correction, backend increment.

B-4 shipped the emission/surfacing budget
(``services/action_cards/emission_budget.py::apply_emission_budget``) but the
data-platform Executor that built it could not wire it in — ``services/
cdp_speed/`` was outside its authorized paths. Nothing on the compute path
called it, so no Action Card ever got ``surfaced_at`` set. This module closes
that gap by wiring ``decision_rules_scoring_stage`` to ``apply_emission_budget``
immediately after ``persist_scoring_result``, so surfacing is decided on the
same compute run that produced the candidates (PRD #599: "candidate upsert ->
emission filter").

AC1 → a compute run through ``decision_rules_scoring_stage`` results in the
      emission budget being applied — at most the configured active cap ends
      up with ``surfaced_at`` set.
AC2 → candidates beyond the cap are still persisted (dual cadence — this is
      the entire point of the slice), but suppressed with a recorded
      ``suppressed_reason``.
AC3 → an emission-budget failure does not discard the candidates
      ``persist_scoring_result`` already wrote — recomputation persistence
      and the surfacing decision are on independent durability boundaries,
      not the same all-or-nothing transaction. The failure is not silently
      swallowed either: it still propagates out of the stage.

Scope: this module exercises the wiring only. B-4's own gate logic
(cooldown / novelty / active-cap math) is covered by
``test_decision_emission_budget.py`` and is not re-tested here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Order, Product, Return, Shop, User
from juli_backend.services.cdp_speed.decision_rules_scoring import decision_rules_scoring_stage
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.cdp_speed.targeted_fetch_planner import TargetedFetchPlan

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
    """Same fixture shape as the B-2/B-3 continuous-trigger tests — produces
    exactly 4 ranked recommendations (verified against the shared rules
    pipeline): priorities 1-4 for prevent_return_8b / optimize_product_2 /
    create_hero_product_1 / process_order_5."""
    user = User(id=user_id, phone="+84901716716")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="B-4 Emission Wiring Shop",
        tiktok_shop_id="tiktok_shop_716_emission_wiring",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add_all([user, shop])
    now = COMPUTED_AT
    products = [
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-716-a",
            name="Widget A",
            status="ACTIVE",
            revenue=Decimal("800000"),
            units_sold=40,
            update_time=now,
        ),
        Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="prod-716-b",
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
            tiktok_order_id=f"ord-716-{index}",
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
            tiktok_return_id="ret-716-1",
            tiktok_order_id="ord-716-1",
            return_type="refund",
            refund_amount=Decimal("10000"),
            status="COMPLETED",
            update_time=now,
        ),
    ]
    session.add_all([*products, *orders, *returns])
    await session.flush()
    return shop


async def _seed_extra_active_candidate(
    session, shop_id: uuid.UUID, *, workflow_key: str, priority: int
) -> ActionCard:
    """Seed a pre-existing 'active' candidate row directly (bypassing the
    scoring pipeline) so a shop can be pushed past the active cap
    deterministically, independent of how many workflows the rules pipeline
    itself ranks for the fixture."""
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key,
        priority=priority,
        severity="warning",
        title=f"Seeded candidate {workflow_key}",
        status="active",
    )
    session.add(card)
    await session.flush()
    return card


async def _cards_for(session, shop_id: uuid.UUID) -> list[ActionCard]:
    stmt = select(ActionCard).where(ActionCard.shop_id == shop_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


class TestEmissionBudgetAppliedOnTheComputePath:
    """AC1 + AC2 — the stage applies the real emission budget end to end,
    proving dual cadence through the stage itself (not the emission_budget
    unit)."""

    @pytest.mark.asyncio
    async def test_stage_caps_surfaced_candidates_at_the_active_cap(
        self, session, shop_with_synced_data, monkeypatch
    ):
        # Weekly novelty cap defaults to 3 — push it well above the candidate
        # count so only the active cap (default 5) is the constraint under
        # test here; the novelty gate itself is B-4's own scope.
        monkeypatch.setenv("CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP", "10")

        shop = shop_with_synced_data
        # Fixture's own rules pipeline ranks 4 workflows at priority 1-4.
        # Seed 3 more pre-existing candidates at lower priority (10-12) so
        # the shop has 7 active candidates total against a default cap of 5.
        for index, priority in enumerate((10, 11, 12), start=1):
            await _seed_extra_active_candidate(
                session,
                shop.id,
                workflow_key=f"seed_extra_{index}",
                priority=priority,
            )

        job = _make_job(shop, idempotency_key="job-716-emission-cap")
        result = await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        assert len(result.recommendations.recommended_workflows) == 4, (
            "fixture assumption drifted — update the seeded priorities/count"
        )

        cards = await _cards_for(session, shop.id)
        assert len(cards) == 7

        surfaced = [card for card in cards if card.surfaced_at is not None]
        suppressed = [card for card in cards if card.surfaced_at is None]

        assert len(surfaced) == 5, "at most the configured active cap (5) may be surfaced"
        assert len(suppressed) == 2

        # The 4 fixture-ranked candidates (priority 1-4) plus the best
        # seeded one (priority 10) fill the 5 surfaced slots; the two
        # lowest-priority seeded candidates are suppressed by the cap.
        surfaced_keys = {card.workflow_key for card in surfaced}
        assert surfaced_keys == {
            "prevent_return_8b",
            "optimize_product_2",
            "create_hero_product_1",
            "process_order_5",
            "seed_extra_1",
        }

        for card in suppressed:
            assert card.workflow_key in {"seed_extra_2", "seed_extra_3"}
            assert card.suppressed_reason == "active_cap"

    @pytest.mark.asyncio
    async def test_stage_persists_suppressed_candidates_not_just_surfaced_ones(
        self, session, shop_with_synced_data, monkeypatch
    ):
        """Dual cadence: recomputation persistence must not be gated by
        surfacing — a suppressed candidate is still a durable, queryable
        Action Card row, just not in the surfaced set."""
        monkeypatch.setenv("CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP", "10")
        shop = shop_with_synced_data
        for index, priority in enumerate((10, 11, 12), start=1):
            await _seed_extra_active_candidate(
                session,
                shop.id,
                workflow_key=f"seed_extra_{index}",
                priority=priority,
            )

        job = _make_job(shop, idempotency_key="job-716-emission-persist")
        await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        cards = await _cards_for(session, shop.id)
        suppressed = [c for c in cards if c.suppressed_reason == "active_cap"]
        assert len(suppressed) == 2
        for card in suppressed:
            # Still an "active" candidate row, content intact — recomputation
            # and surfacing are independently gated.
            assert card.status == "active"


class TestEmissionFailureContainment:
    """AC3 — an emission-budget exception must not roll back the candidates
    persist_scoring_result already committed, and must not be silently
    swallowed either."""

    @pytest.mark.asyncio
    async def test_emission_failure_does_not_discard_persisted_candidates(
        self, session, shop_with_synced_data, monkeypatch, caplog
    ):
        import juli_backend.services.cdp_speed.decision_rules_scoring as stage_mod

        async def _boom(*args, **kwargs):
            raise RuntimeError("emission budget exploded")

        monkeypatch.setattr(stage_mod, "apply_emission_budget", _boom)

        job = _make_job(shop_with_synced_data, idempotency_key="job-716-emission-fail")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError, match="emission budget exploded"):
                await decision_rules_scoring_stage(session, job, computed_at=COMPUTED_AT)

        # Not silently swallowed: the failure was logged.
        assert any(
            "decision_rules_scoring_stage_emission_failed" in record.message
            or "decision_rules_scoring_stage_emission_failed" in record.getMessage()
            for record in caplog.records
        )

        # Not discarded: the candidates persist_scoring_result wrote before
        # the emission budget ran are still durable in the DB.
        cards = await _cards_for(session, shop_with_synced_data.id)
        persisted_keys = {card.workflow_key for card in cards}
        assert persisted_keys == {
            "prevent_return_8b",
            "optimize_product_2",
            "create_hero_product_1",
            "process_order_5",
        }
        for card in cards:
            assert card.status == "active"
            assert card.computed_at is not None
