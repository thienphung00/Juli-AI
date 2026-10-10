"""Fast track P14-A / P14-B: card limits (D24.17) and learning from history (D24.6).

AC-14.1 one limit for every shop: 5 new cards a day, 25 a week, 30 open; a
        14-day simulation on a fixture shop checks the counts day by day.
AC-14.2 first connect: day 1 is mixed by executor (3 Juli, 1 Seller Center,
        1 content); an empty slot takes the next best card.
AC-14.3 a card is valid 7 days from surfacing, then ``expired``; its action
        returns on the same product 7 days after expiry, every time.
AC-14.4 a surfaced card stays at least 3 days; earlier withdrawal only when it
        is no longer valid (edited outside Juli, out of stock, at target).
AC-14.5 open cards are re-scored in place (numbers move, ``surfaced_at`` not).
AC-14.6 ranking = recoverable GMV × the lever's calibration factor × the
        seller-reason penalty; ``adjusted_by_history`` on the payload.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.models.decision_reasons import ACTION_REJECT, ACTION_REVERT
from juli_backend.models.lever_flows import LeverCalibration
from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.services import decision_reasons
from juli_backend.services.action_cards.emission_budget import (
    CAMPAIGN_PLAN_WORKFLOW_KEYS,
    EXPIRED_STATUS,
    SUPPRESSED_REASON_ACTIVE_CAP,
    SUPPRESSED_REASON_DAILY_CAP,
    SUPPRESSED_REASON_WEEKLY_CAP,
    apply_emission_budget,
    shop_day,
)
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    WITHDRAWN_STATUS,
    emit_optimize_product_cards,
    plan_optimize_product_cards,
    withdraw_unranked_cards,
)
from juli_backend.services.action_cards.persist import (
    SUPPRESSED_REASON_EXPIRED_COOLDOWN,
    emit_scoring_cards,
)
from juli_backend.services.demo_decisions import CardContext, build_card_block
from juli_backend.services.optimize_product.decision_cards import LeverHistory
from tests.support.builders import make_tenant
from tests.unit.test_decision_emission_budget import _result
from tests.unit.test_optimize_product_decision_cards import (
    COMPUTED_AT,
    _optimize_cards,
    _score,
    _seed_shop,
)

#: Thursday 2026-10-15, 09:00 in Vietnam.
START = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)

_LEVER_CYCLE = ("title", "cover_image", "product_discount", "description")


def _card(shop_id: uuid.UUID, priority: int, *, lever: str | None, workflow_key: str | None = None):
    payload: dict = {"diagnosis": {"lever": {"code": lever}}} if lever else {}
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key or OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        priority=priority,
        severity="warning",
        title=f"card {priority}",
        description="",
        recommendation_payload=json.dumps(payload),
        status="active",
    )


def _content_card(shop_id: uuid.UUID, priority: int) -> ActionCard:
    card = _card(shop_id, priority, lever=None, workflow_key="content_video")
    card.recommendation_payload = json.dumps({"executor_type": "video"})
    return card


@pytest_asyncio.fixture
async def tenant_shop(session):
    _user, shop = await make_tenant(session)
    return shop


# =========================================================================== AC-14.1/2


@pytest.mark.asyncio
async def test_fourteen_day_simulation_counts_per_day(session, tenant_shop):
    """80 waiting cards, no seller action, one budget run a day for 14 days."""
    shop_id = tenant_shop.id
    for priority in range(1, 81):
        if priority == 10:
            session.add(_content_card(shop_id, priority))
        else:
            session.add(_card(shop_id, priority, lever=_LEVER_CYCLE[(priority - 1) % 4]))
    await session.flush()

    # (new today, open after the run, expired today, binding limit if any)
    expected = [
        (5, 5, 0, SUPPRESSED_REASON_DAILY_CAP),  # Thu: first connect
        (5, 10, 0, SUPPRESSED_REASON_DAILY_CAP),  # Fri
        (5, 15, 0, SUPPRESSED_REASON_DAILY_CAP),  # Sat
        (5, 20, 0, SUPPRESSED_REASON_DAILY_CAP),  # Sun: week 1 had 20
        (5, 25, 0, SUPPRESSED_REASON_DAILY_CAP),  # Mon: new week
        (5, 30, 0, SUPPRESSED_REASON_DAILY_CAP),  # Tue: 30 open
        (0, 30, 0, SUPPRESSED_REASON_ACTIVE_CAP),  # Wed: open limit binds
        (5, 30, 5, SUPPRESSED_REASON_DAILY_CAP),  # Thu: day-1 cards expire
        (5, 30, 5, SUPPRESSED_REASON_DAILY_CAP),  # Fri
        (5, 30, 5, SUPPRESSED_REASON_DAILY_CAP),  # Sat: week 2 reaches 25
        (0, 25, 5, SUPPRESSED_REASON_WEEKLY_CAP),  # Sun: weekly limit binds
        (5, 25, 5, SUPPRESSED_REASON_DAILY_CAP),  # Mon: new week
        (5, 25, 5, SUPPRESSED_REASON_DAILY_CAP),  # Tue
        (5, 30, 0, SUPPRESSED_REASON_DAILY_CAP),  # Wed: nothing surfaced last Wed
    ]
    first_day: list[ActionCard] = []
    for day, (new, open_, expired, binding) in enumerate(expected):
        now = START + timedelta(days=day)
        outcome = await apply_emission_budget(session, shop_id, now=now)
        await session.flush()
        assert len(outcome.newly_surfaced) == new, f"day {day + 1}"
        assert len(outcome.surfaced) == open_, f"day {day + 1}"
        assert len(outcome.expired) == expired, f"day {day + 1}"
        assert outcome.suppressed[binding], f"day {day + 1}: {binding} should bind"
        if day == 0:
            first_day = list(outcome.newly_surfaced)
            # Mix: priorities 1, 2, 4 (Juli), 3 (Seller Center), 10 (video).
            assert sorted(c.priority for c in first_day) == [1, 2, 3, 4, 10]
        if day == 1:
            # The mix is the first day only; afterwards plain priority order.
            assert sorted(c.priority for c in outcome.newly_surfaced) == [5, 6, 7, 8, 9]
        if day < 7:
            # Sticky: a surfaced card keeps the moment it was first surfaced.
            assert all(c.surfaced_at == START for c in first_day)

    assert {c.status for c in first_day} == {EXPIRED_STATUS}
    open_rows = (
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id,
                    ActionCard.status == "active",
                    ActionCard.surfaced_at.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(open_rows) == 30


@pytest.mark.asyncio
async def test_first_day_without_content_fills_the_slot_with_the_next_best(session, tenant_shop):
    shop_id = tenant_shop.id
    levers = ["title", "title", "title", "title", "flash_sale", "description", "cover_image"]
    for priority, lever in enumerate(levers, start=1):
        session.add(_card(shop_id, priority, lever=lever))
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)

    # Juli 1-3, Seller Center 5 (flash sale), then the next best: 4.
    assert sorted(c.priority for c in outcome.newly_surfaced) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_shop_that_has_had_cards_gets_no_first_day_mix(session, tenant_shop):
    shop_id = tenant_shop.id
    old = _card(shop_id, 99, lever="title")
    old.status = "dismissed"
    old.dismissed_at = START - timedelta(days=30)
    session.add(old)
    for priority in range(1, 7):
        session.add(_card(shop_id, priority, lever="title" if priority < 6 else "flash_sale"))
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)

    assert sorted(c.priority for c in outcome.newly_surfaced) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_the_day_is_the_shops_day(session, tenant_shop):
    """16:59 and 17:01 UTC are two Vietnamese days: each gets its 5."""
    shop_id = tenant_shop.id
    for priority in range(1, 13):
        session.add(_card(shop_id, priority, lever="title"))
    await session.flush()
    before = datetime(2026, 10, 15, 16, 59, tzinfo=UTC)
    after = datetime(2026, 10, 15, 17, 1, tzinfo=UTC)
    assert shop_day(after) == shop_day(before) + timedelta(days=1)

    first = await apply_emission_budget(session, shop_id, now=before)
    second = await apply_emission_budget(session, shop_id, now=after)

    assert len(first.newly_surfaced) == 5
    assert len(second.newly_surfaced) == 5


@pytest.mark.asyncio
async def test_campaign_plan_cards_are_outside_the_limits(session, tenant_shop):
    shop_id = tenant_shop.id
    (campaign_key,) = CAMPAIGN_PLAN_WORKFLOW_KEYS
    for priority in range(1, 7):
        session.add(_card(shop_id, priority, lever="title"))
    session.add(_card(shop_id, 50, lever=None, workflow_key=campaign_key))
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)
    later = await apply_emission_budget(session, shop_id, now=START + timedelta(days=8))

    keys = [c.workflow_key for c in outcome.newly_surfaced]
    assert keys.count(OPTIMIZE_PRODUCT_WORKFLOW_KEY) == 5
    assert keys.count(campaign_key) == 1
    # Not on the 7-day validity clock either.
    assert campaign_key in {c.workflow_key for c in later.surfaced}
    assert campaign_key not in {c.workflow_key for c in later.expired}


@pytest.mark.asyncio
async def test_the_sellers_rule_still_lowers_the_open_limit(session, tenant_shop):
    from juli_backend.services import shop_rules

    shop_id = tenant_shop.id
    await shop_rules.set_rule(
        session,
        shop_id,
        rule_key=shop_rules.MAX_OPEN_CARDS,
        scope_ref=None,
        value=2,
        set_by="team",
        set_by_user_id=tenant_shop.user_id,
    )
    for priority in range(1, 6):
        session.add(_card(shop_id, priority, lever="title"))
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)

    assert len(outcome.newly_surfaced) == 2
    assert len(outcome.suppressed[SUPPRESSED_REASON_ACTIVE_CAP]) == 3


# =========================================================================== AC-14.3


@pytest_asyncio.fixture
async def shop_a(session):
    return await _seed_shop(session, "A")


async def _emit(session, shop, at: datetime):
    op = await plan_optimize_product_cards(session, shop.id, now=at)
    decisions = await emit_optimize_product_cards(
        session, shop.id, op, computed_at=at, emission_config=DecisionEmissionConfig()
    )
    await session.flush()
    return decisions


@pytest.mark.asyncio
async def test_an_expired_card_returns_seven_days_after_expiry(session, shop_a):
    await _score(session, shop_a)  # first day: ranks 1-3 surfaced at COMPUTED_AT
    top = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    assert top.surfaced_at is not None

    expiry = COMPUTED_AT + timedelta(days=7)
    outcome = await apply_emission_budget(session, shop_a.id, now=expiry)
    assert top in outcome.expired
    assert top.status == EXPIRED_STATUS
    block = build_card_block(top, json.loads(top.recommendation_payload), CardContext())
    assert block is not None and block["status"] == "expired"
    assert block["adjusted_by_history"] is False

    def for_top(decisions):
        return [d for d in decisions if d.subject_id == top.subject_id]

    for day in (1, 6):
        (inside,) = for_top(await _emit(session, shop_a, expiry + timedelta(days=day)))
        assert inside.suppressed_reason == SUPPRESSED_REASON_EXPIRED_COOLDOWN

    (back,) = for_top(await _emit(session, shop_a, expiry + timedelta(days=7)))
    assert back.suppressed_reason is None
    assert back.card.id != top.id and back.card.supersedes_card_id == top.id
    assert back.card.status == "active" and back.card.surfaced_at is None


@pytest.mark.asyncio
async def test_rejected_and_reverted_return_after_seven_days_every_time(session, shop_a):
    """No escalation: the second rejection of the same action waits 7 days too."""
    await _score(session, shop_a)
    card = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    subject = card.subject_id
    at = COMPUTED_AT
    rounds = ((1, ACTION_REJECT, "not_convincing"), (2, ACTION_REVERT, "off_brand"))
    for round_, action, code in rounds:
        await decision_reasons.record_reason(
            session,
            shop_id=shop_a.id,
            action=action,
            reason_code=code,
            note=None,
            decided_by_user_id=None,
            card=card,
            product_id=decision_reasons.product_id_of(card),
            now=at,
        )
        decision_reasons.close_card(card, now=at)
        await session.flush()
        (inside,) = [
            d
            for d in await _emit(session, shop_a, at + timedelta(days=6))
            if d.subject_id == subject
        ]
        assert inside.suppressed_reason == "decision_cooldown", f"round {round_}"
        at = at + timedelta(days=7, minutes=1)
        (back,) = [d for d in await _emit(session, shop_a, at) if d.subject_id == subject]
        assert back.suppressed_reason is None, f"round {round_}"
        card = back.card


@pytest.mark.asyncio
async def test_a_legacy_workflow_card_also_waits_seven_days_after_expiry(session, tenant_shop):
    shop_id = tenant_shop.id
    first = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    report = await emit_scoring_cards(session, shop_id, _result(shop_id, first, workflow_key="wf"))
    card = report.emitted[0]
    await apply_emission_budget(session, shop_id, now=first)
    await apply_emission_budget(session, shop_id, now=first + timedelta(days=7))
    assert card.status == EXPIRED_STATUS

    inside = await emit_scoring_cards(
        session, shop_id, _result(shop_id, first + timedelta(days=13), workflow_key="wf")
    )
    assert [d.suppressed_reason for d in inside.decisions] == [SUPPRESSED_REASON_EXPIRED_COOLDOWN]
    back = await emit_scoring_cards(
        session, shop_id, _result(shop_id, first + timedelta(days=14), workflow_key="wf")
    )
    (decision,) = back.decisions
    assert decision.emitted and decision.supersedes_card_id == card.id


# =========================================================================== AC-14.4/5


@pytest.mark.asyncio
async def test_a_surfaced_card_stays_three_days_before_an_unranked_withdrawal(session, shop_a):
    await _score(session, shop_a)
    op = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)
    surfaced = [c for c in await _optimize_cards(session, shop_a.id) if c.surfaced_at]
    assert surfaced

    # Nothing ranked any more (keep = ∅), 2 days in: surfaced cards stay.
    early = await withdraw_unranked_cards(
        session,
        shop_a.id,
        keep_subject_ids=set(),
        now=COMPUTED_AT + timedelta(days=2, hours=23),
        op_plan=op,
    )
    assert not {c.id for c in early} & {c.id for c in surfaced}
    assert all(c.status == "active" for c in surfaced)

    late = await withdraw_unranked_cards(
        session,
        shop_a.id,
        keep_subject_ids=set(),
        now=COMPUTED_AT + timedelta(days=3),
        op_plan=op,
    )
    assert {c.id for c in late} == {c.id for c in surfaced}
    assert all(c.status == WITHDRAWN_STATUS for c in surfaced)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["edited", "out_of_stock", "at_target"])
async def test_an_invalid_card_is_withdrawn_inside_its_three_days(session, shop_a, invalid):
    await _score(session, shop_a)
    card = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    others = [c for c in await _optimize_cards(session, shop_a.id) if c.id != card.id]
    product = await session.get(Product, uuid.UUID(card.subject_id))
    assert product is not None
    if invalid == "edited":
        product.title = "Tiêu đề người bán tự sửa ngoài Juli"
    elif invalid == "out_of_stock":
        session.add(
            InventoryItem(
                shop_id=shop_a.id,
                tiktok_product_id=product.tiktok_product_id,
                tiktok_sku_id=f"{product.tiktok_product_id}-s1",
                quantity=0,
                update_time=datetime(2026, 10, 1),
            )
        )
    else:
        payload = json.loads(card.recommendation_payload)
        payload["diagnosis"]["recoverable_gmv_basis"]["reference_rate"] = 0.01
        card.recommendation_payload = json.dumps(payload)
    await session.flush()
    op = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)
    keep = {c.subject_id for c in [card, *others]}

    withdrawn = await withdraw_unranked_cards(
        session,
        shop_a.id,
        keep_subject_ids=keep,
        now=COMPUTED_AT + timedelta(days=1),
        op_plan=op,
    )

    assert [c.id for c in withdrawn] == [card.id]
    assert card.status == WITHDRAWN_STATUS


@pytest.mark.asyncio
async def test_an_open_card_is_rescored_in_place(session, shop_a):
    await _score(session, shop_a)
    card = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    surfaced_at = card.surfaced_at
    payload = json.loads(card.recommendation_payload)
    payload["diagnosis"]["recoverable_gmv_per_day"] = 1.0
    card.recommendation_payload = json.dumps(payload)
    card.priority = 99
    await session.flush()

    later = COMPUTED_AT + timedelta(days=1)
    await _emit(session, shop_a, later)

    assert card.status == "active"
    assert card.surfaced_at == surfaced_at
    assert card.priority == 1
    assert card.computed_at == later
    assert json.loads(card.recommendation_payload)["diagnosis"]["recoverable_gmv_per_day"] > 1


# =========================================================================== AC-14.6


def test_lever_history_maps_the_coefficient_around_the_neutral_half():
    assert LeverHistory().calibration_factor == 1
    assert LeverHistory().adjusted is False
    assert LeverHistory(calibration=Decimal("0.25")).calibration_factor == Decimal("0.5")
    assert LeverHistory(calibration=Decimal("1")).calibration_factor == 2
    assert LeverHistory(calibration=Decimal("2")).calibration_factor == 2  # clamped
    assert LeverHistory(calibration=Decimal("0.05")).calibration_factor == Decimal("0.25")
    weighted = LeverHistory(calibration=Decimal("0.75"), reason_penalty=Decimal("0.8"))
    assert weighted.weight == Decimal("1.2")
    assert weighted.adjusted is True


def test_reason_penalty_fades_over_sixty_days_with_a_floor():
    assert decision_reasons.reason_penalty([]) == 1
    assert decision_reasons.reason_penalty([0]) == Decimal("0.8")
    assert decision_reasons.reason_penalty([30]) == Decimal("0.9")
    assert decision_reasons.reason_penalty([60]) == 1
    assert decision_reasons.reason_penalty([0, 0, 0, 0]) == Decimal("0.4")


@pytest.mark.asyncio
async def test_calibration_and_reasons_reorder_the_ranking(session, shop_a):
    base = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)
    assert base is not None
    order = [(p.product_id, p.lever.value) for p in base.plan.proposals]
    # Not-asked group: the description cards (1.40M .. 1.25M) lead the cover cards (1.2M).
    assert [lever for _pid, lever in order[3:6]] == ["mô tả"] * 3
    assert not any(p.adjusted_by_history for p in base.plan.proposals)

    # A measured description lever that realised a quarter of what was expected.
    session.add(
        LeverCalibration(
            shop_id=shop_a.id,
            lever="description",
            coefficient=Decimal("0.25"),
            readings=2,
            updated_at=datetime(2026, 10, 1),
        )
    )
    await session.flush()
    calibrated = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)
    assert calibrated is not None
    levers = [p.lever.value for p in calibrated.plan.proposals]
    assert levers[3:6] == ["ảnh bìa"] * 3
    described = [p for p in calibrated.plan.proposals if p.lever.value == "mô tả"]
    assert all(p.adjusted_by_history for p in described)
    first = described[0]
    payload = first.diagnosis_payload(as_of="2026-10-06", medians=calibrated.plan.medians)
    assert payload["adjusted_by_history"] is True
    assert payload["history_adjustment"]["calibration_factor"] == 0.5
    # The shown estimate stays the rule-based one (D22 label honest).
    assert payload["recoverable_gmv_per_day"] == pytest.approx(float(first.recoverable_gmv_per_day))
    assert payload["history_adjustment"]["ranking_gmv_per_day"] == pytest.approx(
        float(first.recoverable_gmv_per_day) * 0.5
    )


@pytest.mark.asyncio
async def test_a_rejection_lowers_that_actions_priority_for_the_shop(session, shop_a):
    await _score(session, shop_a)
    description_card = next(
        c
        for c in await _optimize_cards(session, shop_a.id)
        if json.loads(c.recommendation_payload)["diagnosis"]["lever"]["code"] == "description"
    )
    await decision_reasons.record_reason(
        session,
        shop_id=shop_a.id,
        action=ACTION_REJECT,
        reason_code="not_convincing",
        note=None,
        decided_by_user_id=None,
        card=description_card,
        product_id=decision_reasons.product_id_of(description_card),
        now=COMPUTED_AT,
    )
    # A circumstantial reason on another lever carries no penalty.
    cover = next(
        c
        for c in await _optimize_cards(session, shop_a.id)
        if json.loads(c.recommendation_payload)["diagnosis"]["lever"]["code"] == "cover_image"
    )
    await decision_reasons.record_reason(
        session,
        shop_id=shop_a.id,
        action=ACTION_REJECT,
        reason_code="discontinued",
        note=None,
        decided_by_user_id=None,
        card=cover,
        product_id=decision_reasons.product_id_of(cover),
        now=COMPUTED_AT,
    )
    await session.flush()

    penalties = await decision_reasons.reason_penalties(session, shop_a.id, now=COMPUTED_AT)
    assert penalties == {"description": Decimal("0.8")}

    plan = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)
    assert plan is not None
    levers = [p.lever.value for p in plan.plan.proposals]
    # 1.40M × 0.8 = 1.12M < 1.2M: the cover cards now lead the not-asked group.
    assert levers[3:6] == ["ảnh bìa"] * 3

    await _emit(session, shop_a, COMPUTED_AT + timedelta(days=1))
    rows = await _optimize_cards(session, shop_a.id)
    flags = {
        json.loads(c.recommendation_payload)["diagnosis"]["lever"]["code"]: json.loads(
            c.recommendation_payload
        )["adjusted_by_history"]
        for c in rows
        if c.surfaced_at is None
    }
    assert flags.get("description") is True
    assert flags.get("cover_image") is False
