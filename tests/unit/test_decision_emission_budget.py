"""Decision emission/surfacing budget — Issue #716 (B-4, ADR-038 §6).

Throttles which persisted Action Card candidates *surface* into the Demo
active set, independently of recomputation/persistence (#715, B-3).

AC1 → active surfaced set capped at the config default of 5.
AC2 → 7-day per-workflow cooldown blocks re-surfacing after a terminal action.
AC3 → soft weekly novelty quota of 3 is enforced.
AC4 → candidates are still recomputed/persisted when the budget suppresses
      surfacing (dual cadence — surfacing != recomputation). This is also the
      resolution proof for Collision 1 (US-11 vs the in-flight skip).
AC5 → suppression reason is recorded and queryable.
AC6 → emission-drop reason codes are logged (structured, per-suppression, for
      on-call Decision-lag diagnosability) — without leaking PII, tokens, or
      raw financial values into the log line.

Two additional tests prove the Collision 2 resolution (the 7-day cooldown
starting on a dismiss but never completing, because B-3's IN_FLIGHT_STATUSES
skip freezes ``dismissed`` rows forever): a dismissed row stays frozen within
the cooldown window (unchanged B-3 behavior) but is legitimately superseded
by a fresh candidate once the cooldown has fully elapsed, while
``approved``/``executing`` are never time-boxed the same way.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.models.models import ActionCard, DecisionEmissionNoveltyLedger, Shop, User
from juli_backend.services.action_cards.emission_budget import (
    SUPPRESSED_REASON_ACTIVE_CAP,
    SUPPRESSED_REASON_COOLDOWN,
    SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP,
    apply_emission_budget,
)
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
    workflow_key: str,
    workflow_name: str = "Workflow",
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
    user = User(id=user_id, phone="+849160000716")
    s = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="B-4 Emission Budget Shop",
        tiktok_shop_id="tiktok_shop_716",
    )
    session.add_all([user, s])
    await session.flush()
    return s


def _make_card(
    shop_id: uuid.UUID,
    workflow_key: str,
    *,
    priority: int,
    status: str = "active",
    dismissed_at: datetime | None = None,
    approved_at: datetime | None = None,
    executed_at: datetime | None = None,
) -> ActionCard:
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key,
        priority=priority,
        severity="warning",
        title=f"Card {workflow_key}",
        description="",
        recommendation_payload="{}",
        status=status,
        dismissed_at=dismissed_at,
        approved_at=approved_at,
        executed_at=executed_at,
    )


async def _fetch(session, shop_id: uuid.UUID, workflow_key: str) -> ActionCard | None:
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == workflow_key,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# AC1 — active surfaced set capped at config default of 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_surfaced_set_capped_at_config_default_5(session, shop):
    for i in range(1, 8):  # 7 candidates, cap is 5
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.surfaced) == 5
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 2
    # Priority order wins the budget: 1..5 surfaced, 6..7 suppressed.
    surfaced_keys = {c.workflow_key for c in outcome.surfaced}
    assert surfaced_keys == {f"wf_{i}" for i in range(1, 6)}
    for card in outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]:
        assert card.workflow_key in {"wf_6", "wf_7"}
        assert card.surfaced_at is None
        assert card.suppressed_reason == SUPPRESSED_REASON_ACTIVE_CAP


# ---------------------------------------------------------------------------
# AC2 — 7-day per-workflow cooldown blocks re-surfacing after a terminal action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_blocks_resurfacing_within_seven_days(session, shop):
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    recently_dismissed = _make_card(
        shop.id,
        "wf_recent_dismiss",
        priority=1,
        dismissed_at=now - timedelta(days=2),
    )
    session.add(recently_dismissed)
    await session.flush()

    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert outcome.surfaced == []
    assert len(outcome.suppressed[SUPPRESSED_REASON_COOLDOWN]) == 1
    suppressed_card = outcome.suppressed[SUPPRESSED_REASON_COOLDOWN][0]
    assert suppressed_card.workflow_key == "wf_recent_dismiss"
    assert suppressed_card.surfaced_at is None
    assert suppressed_card.suppressed_reason == SUPPRESSED_REASON_COOLDOWN


@pytest.mark.asyncio
async def test_cooldown_expired_allows_resurfacing(session, shop):
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    long_dismissed = _make_card(
        shop.id,
        "wf_old_dismiss",
        priority=1,
        dismissed_at=now - timedelta(days=8),
    )
    session.add(long_dismissed)
    await session.flush()

    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.surfaced) == 1
    assert outcome.surfaced[0].workflow_key == "wf_old_dismiss"
    assert outcome.surfaced[0].surfaced_at == now
    assert outcome.suppressed[SUPPRESSED_REASON_COOLDOWN] == []


# ---------------------------------------------------------------------------
# AC3 — soft weekly novelty quota of 3 is enforced *as a churn target*
#
# Operator decision (#716 B-4, cycle 2): "soft" means fill-to-cap. The
# weekly novelty cap only orders *preference* among candidates competing for
# the active-cap slots — it never removes a candidate outright while a slot
# is still open under ``max_active``. ``SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP``
# therefore never gets assigned by current code (see
# ``test_weekly_novelty_cap_reason_is_structurally_unreachable`` below); the
# constant/frozenset member is retained for schema/API stability (the
# ``ActionCard.suppressed_reason`` column and MODULE.md contract) and in
# case a future slice reintroduces a hard-gate mode.
#
# ``test_weekly_novelty_cap_suppresses_new_workflows_beyond_quota`` below is
# the pre-existing AC3 test, updated in place (not test-weakening — an
# operator-decided requirement change): it keeps its original 4-novel/
# quota-3 setup but now uses a *tight* ``max_active`` so it still proves a
# real suppression happens, with the reason correctly re-attributed to
# ``active_cap`` instead of the now-unreachable ``weekly_novelty_cap``.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_novelty_cap_suppresses_new_workflows_beyond_quota(session, shop):
    """Updated for the fill-to-cap operator decision (#716 B-4, cycle 2).

    Same 4-brand-new-workflow_keys / novelty-cap-3 setup as before, but
    ``max_active`` is now tight (3, matching the quota) so the run still
    demonstrates a genuine suppression — just correctly attributed to
    ``active_cap`` (the true binding constraint under fill-to-cap) rather
    than ``weekly_novelty_cap``, which no candidate is ever suppressed by
    once room exists under the active cap.
    """
    for i in range(1, 5):  # 4 brand-new workflow_keys, novelty cap is 3
        session.add(_make_card(shop.id, f"wf_novel_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)  # Saturday
    config = DecisionEmissionConfig(max_active=3, cooldown_days=7, weekly_novelty_cap=3)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.surfaced) == 3
    assert {c.workflow_key for c in outcome.surfaced} == {
        "wf_novel_1",
        "wf_novel_2",
        "wf_novel_3",
    }
    # The 4th candidate is dropped by lack of *room*, not by the novelty
    # quota itself — weekly_novelty_cap stays empty.
    assert outcome.suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP] == []
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 1
    assert outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP][0].workflow_key == "wf_novel_4"

    # Durable, server-side (Postgres) — not only in Redis. Ledger only ever
    # records candidates that actually surfaced this week.
    ledger_rows = (
        (
            await session.execute(
                select(DecisionEmissionNoveltyLedger).where(
                    DecisionEmissionNoveltyLedger.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_rows) == 3
    assert {row.workflow_key for row in ledger_rows} == {"wf_novel_1", "wf_novel_2", "wf_novel_3"}


@pytest.mark.asyncio
async def test_weekly_novelty_quota_soft_fills_remaining_active_cap_slots(session, shop):
    """New for the fill-to-cap decision: once room exists under ``max_active``,
    novelty-overflow candidates surface too instead of being dropped — the
    quota is a churn target, not a supply ceiling. The ledger accounting
    stays truthful: it records all four novel surfacings this week,
    including the one that overflowed the quota."""
    for i in range(1, 5):  # 4 brand-new workflow_keys, novelty cap is 3
        session.add(_make_card(shop.id, f"wf_novel_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)  # Saturday
    config = DecisionEmissionConfig(max_active=10, cooldown_days=7, weekly_novelty_cap=3)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.surfaced) == 4
    assert {c.workflow_key for c in outcome.surfaced} == {
        "wf_novel_1",
        "wf_novel_2",
        "wf_novel_3",
        "wf_novel_4",
    }
    assert outcome.suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP] == []
    assert outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP] == []

    ledger_rows = (
        (
            await session.execute(
                select(DecisionEmissionNoveltyLedger).where(
                    DecisionEmissionNoveltyLedger.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_rows) == 4
    assert {row.workflow_key for row in ledger_rows} == {
        "wf_novel_1",
        "wf_novel_2",
        "wf_novel_3",
        "wf_novel_4",
    }


@pytest.mark.asyncio
async def test_worked_example_six_novel_candidates_default_config_fills_zero_idle_slots(
    session, shop
):
    """The exact worked example from the operator decision: defaults
    (max_active=5, cooldown_days=7, weekly_novelty_cap=3), 6 novel
    candidates in one week. Required (fill to cap): 5 surfaced, zero slots
    left idle, the 6th suppressed as ``active_cap`` (not
    ``weekly_novelty_cap``)."""
    for i in range(1, 7):  # 6 brand-new workflow_keys
        session.add(_make_card(shop.id, f"wf_worked_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=3)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.surfaced) == 5  # zero slots left idle
    assert {c.workflow_key for c in outcome.surfaced} == {f"wf_worked_{i}" for i in range(1, 6)}
    assert outcome.suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP] == []
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 1
    assert outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP][0].workflow_key == "wf_worked_6"

    ledger_rows = (
        (
            await session.execute(
                select(DecisionEmissionNoveltyLedger).where(
                    DecisionEmissionNoveltyLedger.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger_rows) == 5
    assert {row.workflow_key for row in ledger_rows} == {f"wf_worked_{i}" for i in range(1, 6)}


@pytest.mark.asyncio
async def test_weekly_novelty_cap_is_soft_already_novel_keys_keep_surfacing(session, shop):
    """A workflow_key already counted this week does not re-consume novelty
    budget, and is preferred (ranked ahead of any novelty-overflow
    candidate) for the active-cap slots. ``max_active`` is tight (1) so the
    run still demonstrates a real suppression; under fill-to-cap semantics
    that suppression is correctly attributed to ``active_cap``, since a
    looser cap would let both candidates surface (see
    ``test_weekly_novelty_quota_soft_fills_remaining_active_cap_slots``)."""
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    week_start = now.date() - timedelta(days=now.date().weekday())
    session.add_all(
        [
            DecisionEmissionNoveltyLedger(
                id=uuid.uuid4(),
                shop_id=shop.id,
                week_start=week_start,
                workflow_key=f"wf_already_{i}",
                first_surfaced_at=now - timedelta(days=1),
            )
            for i in range(1, 4)  # 3 slots already spent this week
        ]
    )
    # A 4th candidate reusing an already-novel key, plus one brand-new key.
    session.add(_make_card(shop.id, "wf_already_1", priority=1))
    session.add(_make_card(shop.id, "wf_new", priority=2))
    await session.flush()

    config = DecisionEmissionConfig(max_active=1, cooldown_days=7, weekly_novelty_cap=3)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    surfaced_keys = {c.workflow_key for c in outcome.surfaced}
    assert surfaced_keys == {"wf_already_1"}
    assert outcome.suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP] == []
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 1
    assert outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP][0].workflow_key == "wf_new"


@pytest.mark.asyncio
async def test_novelty_overflow_candidates_ranked_after_quota_satisfied_within_active_cap(
    session, shop
):
    """The quota still shapes *which* Decisions win a scarce active-cap slot
    first: an already-novel (free) candidate is preferred over a
    novelty-overflow candidate for the active-cap pass, even when the
    overflow candidate has a numerically better (lower) raw priority.
    Priority ordering is otherwise preserved within each group."""
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    week_start = now.date() - timedelta(days=now.date().weekday())
    # One key already counted novel earlier this week.
    session.add(
        DecisionEmissionNoveltyLedger(
            id=uuid.uuid4(),
            shop_id=shop.id,
            week_start=week_start,
            workflow_key="wf_already",
            first_surfaced_at=now - timedelta(days=1),
        )
    )
    # 3 brand-new candidates consume the novelty quota (cap=3); a 4th
    # brand-new candidate overflows it. "wf_already" reuses the pre-counted
    # key at the *worst* raw priority (5) — numerically after the overflow
    # candidate (priority 4).
    session.add(_make_card(shop.id, "wf_new_1", priority=1))
    session.add(_make_card(shop.id, "wf_new_2", priority=2))
    session.add(_make_card(shop.id, "wf_new_3", priority=3))
    session.add(_make_card(shop.id, "wf_new_4", priority=4))  # overflow
    session.add(_make_card(shop.id, "wf_already", priority=5))
    await session.flush()

    config = DecisionEmissionConfig(max_active=4, cooldown_days=7, weekly_novelty_cap=3)
    outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    surfaced_keys = {c.workflow_key for c in outcome.surfaced}
    # wf_already (already-novel, free) wins the 4th slot over wf_new_4
    # (novelty-overflow) despite its worse raw priority.
    assert surfaced_keys == {"wf_new_1", "wf_new_2", "wf_new_3", "wf_already"}
    assert outcome.suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP] == []
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 1
    assert outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP][0].workflow_key == "wf_new_4"

    # wf_new_4 never surfaced, so it is correctly absent from the ledger —
    # only actual surfacings are recorded, whether from the within-quota or
    # overflow group.
    ledger_rows = (
        (
            await session.execute(
                select(DecisionEmissionNoveltyLedger).where(
                    DecisionEmissionNoveltyLedger.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert {row.workflow_key for row in ledger_rows} == {
        "wf_already",
        "wf_new_1",
        "wf_new_2",
        "wf_new_3",
    }


def test_weekly_novelty_cap_reason_is_structurally_unreachable():
    """Documents (rather than silently leaving dead code) that
    ``SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP`` is retained in
    ``SUPPRESSED_REASONS`` for schema/API stability but is never assigned by
    ``apply_emission_budget`` under the fill-to-cap operator decision
    (#716 B-4, cycle 2): every suppression is now either ``cooldown`` (hard,
    unchanged) or ``active_cap`` (hard, the only real supply ceiling). The
    novelty quota only orders preference among candidates competing for
    active-cap slots — it never itself removes a candidate while a slot
    remains open."""
    from juli_backend.services.action_cards import emission_budget as module

    assert SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP in module.SUPPRESSED_REASONS


# ---------------------------------------------------------------------------
# AC4 / Collision 1 — recomputation continues even when surfacing is suppressed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppressed_candidate_is_still_recomputed_on_next_scoring_run(session, shop):
    for i in range(1, 8):
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)
    await apply_emission_budget(session, shop.id, now=now, config=config)

    suppressed_before = await _fetch(session, shop.id, "wf_7")
    assert suppressed_before is not None
    assert suppressed_before.suppressed_reason == SUPPRESSED_REASON_ACTIVE_CAP
    assert suppressed_before.title == "Card wf_7"

    # A fresh scoring run recomputes wf_7's *content* — the candidate is not
    # dropped just because the emission budget suppressed its surfacing.
    later_computed_at = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
    result = _result(
        shop.id,
        later_computed_at,
        workflow_key="wf_7",
        workflow_name="Rescored wf_7",
        priority=1,
    )
    await persist_scoring_result(session, shop.id, result)
    await session.flush()

    suppressed_after = await _fetch(session, shop.id, "wf_7")
    assert suppressed_after is not None
    assert suppressed_after.title == "Rescored wf_7"
    assert suppressed_after.priority == 1
    assert suppressed_after.computed_at == later_computed_at
    # persist_scoring_result never touches emission-budget-owned columns —
    # the suppression decision survives recomputation untouched, ready for
    # the next apply_emission_budget run to re-evaluate on its own cadence.
    assert suppressed_after.suppressed_reason == SUPPRESSED_REASON_ACTIVE_CAP
    assert suppressed_after.surfaced_at is None


# ---------------------------------------------------------------------------
# AC5 — suppression reason is recorded and queryable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppression_reason_is_recorded_and_queryable(session, shop):
    for i in range(1, 4):
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=1, cooldown_days=7, weekly_novelty_cap=10)
    await apply_emission_budget(session, shop.id, now=now, config=config)

    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.suppressed_reason == SUPPRESSED_REASON_ACTIVE_CAP,
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert {row.workflow_key for row in rows} == {"wf_2", "wf_3"}

    stmt_surfaced = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.surfaced_at.is_not(None),
    )
    surfaced_rows = (await session.execute(stmt_surfaced)).scalars().all()
    assert {row.workflow_key for row in surfaced_rows} == {"wf_1"}


# ---------------------------------------------------------------------------
# AC6 — emission-drop reason codes are logged (on-call diagnosability)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppression_reason_codes_are_logged_per_suppressed_card(session, shop, caplog):
    """Per-suppression visibility, not just an aggregate count — an on-call
    engineer diagnosing Decision lag for one shop needs to see *which*
    workflow_key dropped and *why*, not only "N suppressed"."""
    for i in range(1, 4):  # 3 candidates, cap is 1 -> 2 suppressed by active_cap
        session.add(_make_card(shop.id, f"wf_log_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=1, cooldown_days=7, weekly_novelty_cap=10)

    with caplog.at_level(logging.INFO, logger="juli_backend.services.action_cards.emission_budget"):
        outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 2

    suppressed_records = [
        record
        for record in caplog.records
        if record.name == "juli_backend.services.action_cards.emission_budget"
        and record.getMessage() == "emission_budget_suppressed"
    ]
    # One structured log entry per suppressed card, not merely an aggregate.
    assert len(suppressed_records) == 2
    logged_pairs = {
        (record.workflow_key, record.suppressed_reason) for record in suppressed_records
    }
    assert logged_pairs == {
        ("wf_log_2", SUPPRESSED_REASON_ACTIVE_CAP),
        ("wf_log_3", SUPPRESSED_REASON_ACTIVE_CAP),
    }
    for record in suppressed_records:
        assert record.shop_id == str(shop.id)

    # A per-reason aggregate is also useful (dashboarding/alerting) but must
    # be *in addition to*, never *instead of*, the per-suppression detail
    # above.
    summary_records = [
        record
        for record in caplog.records
        if record.name == "juli_backend.services.action_cards.emission_budget"
        and record.getMessage() == "emission_budget_applied"
    ]
    assert len(summary_records) == 1
    summary = summary_records[0]
    assert summary.shop_id == str(shop.id)
    assert summary.surfaced_count == 1
    assert summary.suppressed_active_cap == 2
    assert summary.suppressed_cooldown == 0
    assert summary.suppressed_weekly_novelty_cap == 0


@pytest.mark.asyncio
async def test_suppression_log_lines_contain_no_pii_tokens_or_financial_values(
    session, shop, caplog
):
    """Hard constraint (PRD security stories 22 & 23): the emission-drop log
    must never carry seller-identifying content, secrets, or raw money
    figures, even though those values live on the suppressed row itself."""
    forbidden_values = [
        "jane.seller@example.com",
        "+84901234567",
        "4111111111111111",
        "sk_live_abcdef0123456789",
        "987654321.99",
    ]
    card = _make_card(shop.id, "wf_sensitive", priority=1)
    card.title = "Contact jane.seller@example.com re: card 4111111111111111"
    card.description = "Seller phone +84901234567, token sk_live_abcdef0123456789"
    card.recommendation_payload = (
        '{"customer_email": "jane.seller@example.com", "revenue": 987654321.99}'
    )
    session.add(card)
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_active=0, cooldown_days=7, weekly_novelty_cap=10)

    with caplog.at_level(logging.INFO, logger="juli_backend.services.action_cards.emission_budget"):
        outcome = await apply_emission_budget(session, shop.id, now=now, config=config)

    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 1

    own_records = [
        record
        for record in caplog.records
        if record.name == "juli_backend.services.action_cards.emission_budget"
    ]
    assert own_records, "expected at least one emission_budget log record"

    for record in own_records:
        haystack_parts = [record.getMessage()]
        for key, value in vars(record).items():
            if key in logging.LogRecord.__dict__ or key in {"message", "args", "msg"}:
                continue
            haystack_parts.append(f"{key}={value}")
        haystack = " ".join(haystack_parts)
        for forbidden in forbidden_values:
            assert forbidden not in haystack, (
                f"forbidden value {forbidden!r} leaked into log record: {haystack}"
            )


# ---------------------------------------------------------------------------
# Collision 2 — the cooldown can start but must eventually finish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismissed_workflow_stays_frozen_within_cooldown_window(session, shop):
    """Same shape as B-3's in-flight test, but at day-scale: still frozen."""
    first_computed_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    first_result = _result(shop.id, first_computed_at, workflow_key="wf_dismiss_cooldown")
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, "wf_dismiss_cooldown")
    assert card is not None
    card.status = "dismissed"
    card.dismissed_at = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    await session.flush()

    # 3 days later — still within the 7-day cooldown.
    second_computed_at = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    second_result = _result(
        shop.id,
        second_computed_at,
        workflow_key="wf_dismiss_cooldown",
        workflow_name="Rescored",
        priority=9,
    )
    await persist_scoring_result(session, shop.id, second_result)
    await session.flush()

    still_frozen = await _fetch(session, shop.id, "wf_dismiss_cooldown")
    assert still_frozen is not None
    assert still_frozen.status == "dismissed"
    assert still_frozen.title == "Workflow"  # unchanged from first candidate
    assert still_frozen.priority == 1


@pytest.mark.asyncio
async def test_dismissed_workflow_superseded_after_cooldown_fully_elapses(session, shop):
    """Collision 2 resolution: once the 7-day cooldown fully elapses, a fresh
    candidate legitimately supersedes the dismissed row so the workflow_key
    can re-enter emission-budget evaluation — the cooldown clock finishes."""
    first_computed_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    first_result = _result(shop.id, first_computed_at, workflow_key="wf_dismiss_expires")
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, "wf_dismiss_expires")
    assert card is not None
    dismissed_marker = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    card.status = "dismissed"
    card.dismissed_at = dismissed_marker
    await session.flush()

    # 8 days after the dismiss — cooldown (7 days) has fully elapsed.
    later_computed_at = dismissed_marker + timedelta(days=8)
    later_result = _result(
        shop.id,
        later_computed_at,
        workflow_key="wf_dismiss_expires",
        workflow_name="Fresh candidate post-cooldown",
        priority=2,
    )
    cards = await persist_scoring_result(session, shop.id, later_result)
    await session.flush()

    superseded = await _fetch(session, shop.id, "wf_dismiss_expires")
    assert superseded is not None
    assert superseded.status == "active"
    assert superseded.title == "Fresh candidate post-cooldown"
    assert superseded.priority == 2
    assert superseded.dismissed_at is None
    assert superseded.computed_at == later_computed_at
    assert any(c.workflow_key == "wf_dismiss_expires" for c in cards)

    # Still exactly one row — a supersede updates in place, no duplicate.
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.workflow_key == "wf_dismiss_expires",
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1

    # Now eligible for a fresh emission-budget evaluation.
    budget_now = later_computed_at + timedelta(minutes=1)
    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)
    outcome = await apply_emission_budget(session, shop.id, now=budget_now, config=config)
    assert any(c.workflow_key == "wf_dismiss_expires" for c in outcome.surfaced)


@pytest.mark.asyncio
@pytest.mark.parametrize("in_flight_status", ["approved", "executing"])
async def test_approved_and_executing_are_never_time_boxed_superseded(
    session, shop, in_flight_status
):
    """Only `dismissed` gets a cooldown-expiry escape hatch (Collision 2). A
    workflow stuck `approved`/`executing` stays frozen indefinitely by time
    alone — resetting those requires an explicit outcome, not just a clock."""
    first_computed_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    workflow_key = f"wf_{in_flight_status}_never_superseded"
    first_result = _result(shop.id, first_computed_at, workflow_key=workflow_key)
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, workflow_key)
    assert card is not None
    card.status = in_flight_status
    marker = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    card.approved_at = marker
    await session.flush()

    # Far beyond any cooldown window.
    much_later = marker + timedelta(days=365)
    later_result = _result(
        shop.id,
        much_later,
        workflow_key=workflow_key,
        workflow_name="Should never land",
        priority=1,
    )
    await persist_scoring_result(session, shop.id, later_result)
    await session.flush()

    unchanged = await _fetch(session, shop.id, workflow_key)
    assert unchanged is not None
    assert unchanged.status == in_flight_status
    assert unchanged.title == "Workflow"  # unchanged from first candidate


def test_in_flight_statuses_still_exactly_approved_dismissed_executing():
    """Collision 2 is resolved without narrowing this frozenset (hard rule)."""
    assert IN_FLIGHT_STATUSES == frozenset({"approved", "dismissed", "executing"})


# ---------------------------------------------------------------------------
# Postgres is SoT — no Redis dependency on emission truth
# ---------------------------------------------------------------------------


def test_no_redis_dependency_in_emission_budget_module():
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "backend/src/juli_backend/services/action_cards/emission_budget.py"
    forbidden = {"redis", "aioredis"}
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert not imports & forbidden, f"emission_budget.py imports Redis: {imports & forbidden}"
