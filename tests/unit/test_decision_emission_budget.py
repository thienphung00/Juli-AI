"""Decision emission/surfacing budget — Issue #716 (B-4, ADR-038 §6).

Throttles which persisted Action Card candidates *surface* into the Demo
active set, independently of recomputation/persistence (#715, B-3).

AC1 → the surfaced set is capped (D24.17 replaced #716's "5 active / soft
      weekly novelty 3": 5 new a day, 25 a week, 30 open; the day-by-day
      behaviour is in ``test_p14_card_limits.py``).
AC2 → 7-day per-workflow cooldown blocks re-surfacing after a terminal action.
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
    SUPPRESSED_REASON_DAILY_CAP,
    apply_emission_budget,
)
from juli_backend.services.action_cards.persist import (
    IN_FLIGHT_STATUSES,
    SUPPRESSED_REASON_BASIS_UNCHANGED,
    emit_scoring_cards,
    persist_scoring_result,
)
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)
from juli_backend.services.scoring.types import (
    AdvisorySignal,
    DailyScoringResult,
    KpiId,
    ScoringSignals,
    Severity,
    VisualLayerDomain,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

#: These cards carry no ADR-106 lever (they take ``juli`` slots, D24.21 (4)):
#: one wide slot isolates the limit under test from the daily slots.
_ONE_WIDE_SLOT = (("juli", 50),)


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


def _signal(kpi_id: KpiId, severity: Severity) -> AdvisorySignal:
    """A real ``AdvisorySignal`` — the object the scoring pipeline produces and
    the object ``basis.compute_card_basis`` reads its severity bucket off."""
    return AdvisorySignal(
        kpi_id=kpi_id,
        domain=VisualLayerDomain.INVENTORY,
        technique="rules_proxy",
        change_text="test",
        signal_type="risk",
        action_hint="test",
        one_line="test",
        workflow_keys=(),
        severity=severity,
    )


def _result(
    shop_id: uuid.UUID,
    computed_at: datetime,
    *,
    workflow_key: str,
    workflow_name: str = "Workflow",
    priority: int = 1,
    kpis: dict | None = None,
    source_kpi_ids: tuple[str, ...] = (),
) -> DailyScoringResult:
    return DailyScoringResult(
        aggregates=_snapshot(shop_id),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis=kpis or {},
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
                    source_kpi_ids=source_kpi_ids,
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
# AC1 — the open set is capped (D24.17: 30 open; 5 new a day)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_cards_capped_at_max_open(session, shop):
    for i in range(1, 8):  # 7 candidates, open cap 5
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_open=5, daily_new_cap=50, daily_slots=_ONE_WIDE_SLOT)
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


@pytest.mark.asyncio
async def test_default_limit_is_the_daily_slots(session, shop):
    """5 new a day, split 3 Juli / 1 Seller Center / 1 content (D24.21 (4)):
    legacy cards (no lever) take the Juli slots, so 3 of them a day."""
    for i in range(1, 9):
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    outcome = await apply_emission_budget(session, shop.id, now=now)

    assert [c.workflow_key for c in outcome.newly_surfaced] == [f"wf_{i}" for i in range(1, 4)]
    assert {c.workflow_key for c in outcome.suppressed[SUPPRESSED_REASON_DAILY_CAP]} == {
        "wf_4",
        "wf_5",
        "wf_6",
        "wf_7",
        "wf_8",
    }
    # One ledger row per surfacing (the per-day / per-week count).
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

    # Same day, later run: nothing new; the three stay surfaced.
    again = await apply_emission_budget(session, shop.id, now=now + timedelta(hours=3))
    assert again.newly_surfaced == []
    assert len(again.surfaced) == 3
    assert len(again.suppressed[SUPPRESSED_REASON_DAILY_CAP]) == 5


def test_config_defaults_and_env_overrides(monkeypatch):
    from juli_backend.core.config import decision_emission_config

    default = decision_emission_config()
    assert (default.daily_new_cap, default.weekly_new_cap, default.max_open) == (5, 25, 30)
    assert (default.validity_days, default.min_stay_days, default.cooldown_days) == (7, 3, 7)
    assert dict(default.daily_slots) == {"juli": 3, "seller_center": 1, "content": 1}

    monkeypatch.setenv("CDP_DECISION_EMISSION_DAILY_NEW_CAP", "8")
    monkeypatch.setenv("CDP_DECISION_EMISSION_WEEKLY_NEW_CAP", "40")
    monkeypatch.setenv("CDP_DECISION_EMISSION_MAX_OPEN", "12")
    monkeypatch.setenv("CDP_DECISION_EMISSION_DAILY_SLOTS", "juli=2,seller_center=2")
    tuned = decision_emission_config()
    assert (tuned.daily_new_cap, tuned.weekly_new_cap, tuned.max_open) == (8, 40, 12)
    assert tuned.daily_slots == (("juli", 2), ("seller_center", 2))
    monkeypatch.setenv("CDP_DECISION_EMISSION_DAILY_SLOTS", "garbage")
    assert decision_emission_config().daily_slots == default.daily_slots


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

    outcome = await apply_emission_budget(
        session, shop.id, now=now, config=DecisionEmissionConfig()
    )

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

    outcome = await apply_emission_budget(
        session, shop.id, now=now, config=DecisionEmissionConfig()
    )

    assert len(outcome.surfaced) == 1
    assert outcome.surfaced[0].workflow_key == "wf_old_dismiss"
    assert outcome.surfaced[0].surfaced_at == now
    assert outcome.suppressed[SUPPRESSED_REASON_COOLDOWN] == []


# ---------------------------------------------------------------------------
# AC4 / Collision 1 — recomputation continues even when surfacing is suppressed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppressed_candidate_is_still_recomputed_on_next_scoring_run(session, shop):
    for i in range(1, 8):
        session.add(_make_card(shop.id, f"wf_{i}", priority=i))
    await session.flush()

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    config = DecisionEmissionConfig(max_open=5, daily_new_cap=50, daily_slots=_ONE_WIDE_SLOT)
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
    config = DecisionEmissionConfig(max_open=1, daily_new_cap=50)
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
    config = DecisionEmissionConfig(max_open=1, daily_new_cap=50)

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
    config = DecisionEmissionConfig(max_open=0, daily_new_cap=50)

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
    """Collision 2 resolution, as ADR-087 decision 6 amends it (#1703).

    #716 (B-4) resolved Collision 2 by *resetting the dismissed row in place*
    once the 7-day cooldown elapsed, on the clock alone. Subject-scoped
    emission changes both halves of that:

    * the successor is a **new row** chained by ``supersedes_card_id``, not a
      reset -- ADR-087 decision 3 rejects the counter-on-one-row shape because
      *"the predecessor's information is destroyed by the update, which is the
      half of the requirement that says the successor must carry it"*. The
      dismiss stays on the record;
    * the clock alone no longer produces it. ADR-087 decision 6 admits a
      time-based rule *"only as a secondary cap on churn, never as the primary
      trigger -- it manufactures the appearance of an improvement on a
      schedule"*, which CONTEXT.md's Card revision entry lists under _Avoid_.
      The basis must have moved too; the companion test below pins the
      elapsed-but-unchanged case.

    What #716's acceptance criterion actually asked for is unchanged and still
    proven here: the cooldown clock, once started, can finish, and the
    workflow_key re-enters emission-budget evaluation.
    """
    first_computed_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    first_result = _result(
        shop.id,
        first_computed_at,
        workflow_key="wf_dismiss_expires",
        kpis={"dsi": _signal("dsi", "healthy")},
        source_kpi_ids=("dsi",),
    )
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, "wf_dismiss_expires")
    assert card is not None
    predecessor_id = card.id
    dismissed_marker = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    card.status = "dismissed"
    card.dismissed_at = dismissed_marker
    card.surfaced_at = first_computed_at
    await session.flush()

    # 8 days after the dismiss — cooldown (7 days) has fully elapsed — and the
    # signal behind the recommendation has moved from healthy to critical.
    later_computed_at = dismissed_marker + timedelta(days=8)
    later_result = _result(
        shop.id,
        later_computed_at,
        workflow_key="wf_dismiss_expires",
        workflow_name="Fresh candidate post-cooldown",
        priority=2,
        kpis={"dsi": _signal("dsi", "critical")},
        source_kpi_ids=("dsi",),
    )
    cards = await persist_scoring_result(session, shop.id, later_result)
    await session.flush()

    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.workflow_key == "wf_dismiss_expires",
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 2

    successor = next(row for row in rows if row.id != predecessor_id)
    assert successor.status == "active"
    assert successor.title == "Fresh candidate post-cooldown"
    assert successor.priority == 2
    assert successor.revision == 2
    assert successor.supersedes_card_id == predecessor_id
    assert successor.computed_at == later_computed_at
    assert any(c.id == successor.id for c in cards)

    # The dismiss stays on the record rather than being erased by a reset.
    predecessor = next(row for row in rows if row.id == predecessor_id)
    assert predecessor.status == "dismissed"
    assert predecessor.dismissed_at is not None

    # Now eligible for a fresh emission-budget evaluation.
    budget_now = later_computed_at + timedelta(minutes=1)
    config = DecisionEmissionConfig(max_open=5, daily_new_cap=50, daily_slots=_ONE_WIDE_SLOT)
    outcome = await apply_emission_budget(session, shop.id, now=budget_now, config=config)
    assert any(c.id == successor.id for c in outcome.surfaced)


@pytest.mark.asyncio
async def test_a_dismissed_card_returns_after_seven_days_even_unchanged(session, shop):
    """D24.21 (3) (owner, 2026-10-10) replaces ADR-087 d.6 here: a legacy
    workflow card the seller rejected returns 7 days later as a new revision,
    whether or not its basis moved. Inside the 7 days it stays dismissed.
    """
    first_computed_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    first_result = _result(shop.id, first_computed_at, workflow_key="wf_dismiss_unchanged")
    await persist_scoring_result(session, shop.id, first_result)
    await session.flush()

    card = await _fetch(session, shop.id, "wf_dismiss_unchanged")
    assert card is not None
    dismissed_marker = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    card.status = "dismissed"
    card.dismissed_at = dismissed_marker
    card.surfaced_at = first_computed_at
    await session.flush()

    inside = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, dismissed_marker + timedelta(days=6), workflow_key="wf_dismiss_unchanged"),
    )
    assert [d.suppressed_reason for d in inside.decisions] == [SUPPRESSED_REASON_BASIS_UNCHANGED]

    later_result = _result(
        shop.id,
        dismissed_marker + timedelta(days=7, minutes=1),
        workflow_key="wf_dismiss_unchanged",
        workflow_name="Re-offer after 7 days",
        priority=2,
    )
    report = await emit_scoring_cards(session, shop.id, later_result)
    await session.flush()

    assert [d.suppressed_reason for d in report.decisions] == [None]
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop.id,
        ActionCard.workflow_key == "wf_dismiss_unchanged",
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 2
    successor = next(row for row in rows if row.id != card.id)
    assert successor.title == "Re-offer after 7 days"
    assert successor.supersedes_card_id == card.id and successor.status == "active"


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
