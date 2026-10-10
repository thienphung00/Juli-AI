"""P14 integration: P14-E content cards under the P14-A card limits (D24.17).

- the emission budget recognises a P14-E card (``content_video`` /
  ``content_live``, payload ``card_executor: "juli_drafts"``) as the first
  day's content slot;
- a content card the budget expired (status ``expired``) keeps P14-E's 7-day
  return: the content emission does not rewrite it before then.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from juli_backend.core.config.decision_emission import EXECUTOR_CONTENT
from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.emission_budget import (
    EXPIRED_STATUS,
    apply_emission_budget,
    executor_slot,
)
from juli_backend.services.content_cards import emission
from tests.support.lever_flows import seed_shop
from tests.unit.test_p14_content_flow import _products, _row, _video_table

#: Thursday 2026-10-15, 09:00 in Vietnam.
START = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)


def _optimize_card(shop_id: uuid.UUID, priority: int) -> ActionCard:
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key="optimize_product_2",
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        priority=priority,
        severity="warning",
        title=f"card {priority}",
        description="",
        recommendation_payload=json.dumps({"diagnosis": {"lever": {"code": "title"}}}),
        status="active",
    )


async def _content_cards(session, shop_id):
    rows = await session.execute(
        select(ActionCard)
        .where(ActionCard.shop_id == shop_id, ActionCard.workflow_key == "content_video")
        .order_by(ActionCard.revision)
    )
    return list(rows.scalars())


def test_a_p14e_card_is_the_content_slot():
    card = ActionCard(
        workflow_key="content_live",
        recommendation_payload=json.dumps({"card_executor": "juli_drafts", "content": {}}),
    )
    assert executor_slot(card) == EXECUTOR_CONTENT
    other = ActionCard(
        workflow_key="some_future_workflow",
        recommendation_payload=json.dumps({"card_executor": "juli_drafts"}),
    )
    assert executor_slot(other) == EXECUTOR_CONTENT


@pytest.mark.asyncio
async def test_first_day_mix_surfaces_a_p14e_content_card(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    tables = {"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])}
    await emission.emit_content_cards(session, shop.id, now=START, rankings=tables)
    (content,) = await _content_cards(session, shop.id)
    content.priority = 50  # ranked far below the six Juli cards
    for priority in range(1, 7):
        session.add(_optimize_card(shop.id, priority))
    await session.flush()

    outcome = await apply_emission_budget(session, shop.id, now=START)

    assert len(outcome.newly_surfaced) == 5
    assert content in outcome.newly_surfaced


@pytest.mark.asyncio
async def test_a_content_card_the_budget_expired_returns_seven_days_later(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    tables = {"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])}
    await emission.emit_content_cards(session, shop.id, now=START, rankings=tables)
    await apply_emission_budget(session, shop.id, now=START)
    (card,) = await _content_cards(session, shop.id)
    assert card.surfaced_at is not None

    expired_on = START + timedelta(days=7)
    outcome = await apply_emission_budget(session, shop.id, now=expired_on)
    assert card in outcome.expired and card.status == EXPIRED_STATUS

    soon = await emission.emit_content_cards(
        session, shop.id, now=expired_on + timedelta(days=3), rankings=tables
    )
    assert [d.suppressed_reason for d in soon] == [emission.SUPPRESSED_EXPIRY_COOLDOWN]
    assert len(await _content_cards(session, shop.id)) == 1

    back = await emission.emit_content_cards(
        session, shop.id, now=expired_on + timedelta(days=7), rankings=tables
    )
    assert [d.suppressed_reason for d in back] == [None]
    cards = await _content_cards(session, shop.id)
    assert [c.status for c in cards] == [EXPIRED_STATUS, "active"]
    assert cards[1].surfaced_at is None
