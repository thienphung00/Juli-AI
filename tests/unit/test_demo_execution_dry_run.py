"""Demo dry-run approve -> execute — local records only (#717, B-5, ADR-037/038 §9).

AC1 -> approving/executing a Decision on Demo never enqueues or invokes a real
      Partner write client call (assert zero interaction with the
      Partner-write module: services.execution.dispatch.enqueue_approved_tool
      / services.execution.runner.run_tool_async).
AC2 -> a local execution record is created with a progress state machine
      (queued -> running -> done) on approve.
AC4 -> negative: Demo approve with no live shop credentials configured still
      succeeds — dry-run must not require Partner auth.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, DemoExecutionRecord, Shop, User
from juli_backend.services.demo_execution import (
    DecisionNotFound,
    approve_decision_dry_run,
)


@pytest.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849170000717")
    s = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="B-5 Demo Shop",
        tiktok_shop_id="tiktok_shop_717",
    )
    session.add_all([user, s])
    await session.flush()
    return s


@pytest.fixture
async def action_card(session, shop):
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="replenish_inventory_3",
        priority=1,
        severity="high",
        title="Replenish low-stock SKU",
        description="Stock is running low.",
        recommendation_payload="{}",
        status="active",
    )
    session.add(card)
    await session.flush()
    return card


@pytest.mark.asyncio
async def test_approve_creates_local_execution_record_with_progress_state_machine(
    session, shop, action_card
):
    """AC2: local record created on approve, progressing queued -> running -> done."""
    record = await approve_decision_dry_run(session, shop_id=shop.id, action_card_id=action_card.id)

    assert isinstance(record, DemoExecutionRecord)
    assert record.shop_id == shop.id
    assert record.action_card_id == action_card.id
    assert record.workflow_key == "replenish_inventory_3"
    assert record.status == "done"
    assert record.started_at is not None
    assert record.completed_at is not None

    narrative = json.loads(record.narrative_json)
    states = [step["state"] for step in narrative]
    assert states == ["queued", "running", "done"]
    for step in narrative:
        assert step["message"]
        assert step["at"]


@pytest.mark.asyncio
async def test_approve_persists_record_queryable_by_shop_and_action_card(
    session, shop, action_card
):
    await approve_decision_dry_run(session, shop_id=shop.id, action_card_id=action_card.id)

    stmt = select(DemoExecutionRecord).where(
        DemoExecutionRecord.shop_id == shop.id,
        DemoExecutionRecord.action_card_id == action_card.id,
    )
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_approve_marks_the_decision_approved(session, shop, action_card):
    await approve_decision_dry_run(session, shop_id=shop.id, action_card_id=action_card.id)

    refreshed = await session.get(ActionCard, action_card.id)
    assert refreshed.status == "approved"
    assert refreshed.approved_at is not None


@pytest.mark.asyncio
async def test_approve_raises_for_unknown_decision(session, shop):
    with pytest.raises(DecisionNotFound):
        await approve_decision_dry_run(session, shop_id=shop.id, action_card_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_approve_raises_when_decision_belongs_to_a_different_shop(
    session, shop, action_card, user_id
):
    other_user = User(id=uuid.uuid4(), phone="+849170000718")
    other_shop = Shop(
        id=uuid.uuid4(),
        user_id=other_user.id,
        shop_name="Other Shop",
        tiktok_shop_id="tiktok_shop_other_717",
    )
    session.add_all([other_user, other_shop])
    await session.flush()

    with pytest.raises(DecisionNotFound):
        await approve_decision_dry_run(
            session, shop_id=other_shop.id, action_card_id=action_card.id
        )


@pytest.mark.asyncio
async def test_approve_never_invokes_the_partner_write_module(session, shop, action_card):
    """AC1: zero interaction with the Partner-write module — mocked or otherwise."""
    with (
        patch("juli_backend.services.execution.dispatch.enqueue_approved_tool") as enqueue_mock,
        patch("juli_backend.services.execution.runner.run_tool_async") as run_mock,
    ):
        await approve_decision_dry_run(session, shop_id=shop.id, action_card_id=action_card.id)

        enqueue_mock.assert_not_called()
        run_mock.assert_not_called()


@pytest.mark.asyncio
async def test_approve_succeeds_with_no_tiktok_credentials_configured(session, user_id):
    """AC4: dry-run does not require Partner auth — shop has zero TikTokCredential rows."""
    user = User(id=user_id, phone="+849170000719")
    shop_without_credentials = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="No-Credential Demo Shop",
        tiktok_shop_id=None,
    )
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_without_credentials.id,
        workflow_key="optimize_product_2",
        priority=2,
        severity="medium",
        title="Optimize listing",
        description="",
        recommendation_payload="{}",
        status="active",
    )
    session.add_all([user, shop_without_credentials, card])
    await session.flush()

    record = await approve_decision_dry_run(
        session,
        shop_id=shop_without_credentials.id,
        action_card_id=card.id,
    )

    assert record.status == "done"


@pytest.mark.asyncio
async def test_approve_uses_injectable_clock_for_deterministic_timestamps(
    session, shop, action_card
):
    fixed = datetime(2026, 8, 8, 9, 0, tzinfo=UTC)
    record = await approve_decision_dry_run(
        session,
        shop_id=shop.id,
        action_card_id=action_card.id,
        now=lambda: fixed,
    )

    assert record.started_at == fixed
    assert record.completed_at == fixed
    narrative = json.loads(record.narrative_json)
    assert all(step["at"] == fixed.isoformat() for step in narrative)
