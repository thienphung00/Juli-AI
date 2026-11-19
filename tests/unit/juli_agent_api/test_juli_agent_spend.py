"""The Juli tab's LLM cost counts in the existing spend gates (HELD for the owner's OK).

``shop_rules.openai_cap.openai_spend_this_month`` / ``openai_spend_and_cap`` (the per-shop cap)
and ``ops.system_cap.system_spend_since`` (the system cap; its SQLite path -- on Postgres the
086 ``openai_spend_since`` function needs re-creating first) add ``agent_messages.cost_usd`` of
the month to the runs and content analyses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from juli_backend.models.agent_chat import AgentConversation, AgentMessage
from juli_backend.models.models import Shop, User
from juli_backend.services.ops.system_cap import system_spend_since
from juli_backend.services.shop_rules.openai_cap import (
    month_start_utc,
    openai_spend_and_cap,
    openai_spend_this_month,
)

NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)


async def _shop(session) -> uuid.UUID:
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name="Spend shop", platform="shopee")
    session.add(shop)
    await session.flush()
    return shop.id


async def _answer(session, shop_id, cost: str, at: datetime) -> None:
    conv = AgentConversation(
        id=uuid.uuid4(), shop_id=shop_id, platform="shopee", title="t", created_at=at,
        updated_at=at,
    )  # fmt: skip
    session.add(conv)
    await session.flush()
    session.add(
        AgentMessage(
            id=uuid.uuid4(), shop_id=shop_id, conversation_id=conv.id, role="assistant",
            events=[], status="done", cost_usd=Decimal(cost), created_at=at, updated_at=at,
        )
    )  # fmt: skip
    await session.flush()


async def test_the_shop_spend_counts_the_juli_tab_of_this_month_only(session):
    a, b = await _shop(session), await _shop(session)
    start = month_start_utc(NOW)
    await _answer(session, a, "0.40", start + timedelta(hours=1))
    await _answer(session, a, "0.10", start + timedelta(days=2))
    await _answer(session, a, "9.00", start - timedelta(hours=1))  # last month
    await _answer(session, b, "3.00", start + timedelta(hours=1))  # another shop
    assert await openai_spend_this_month(session, a, now=NOW) == Decimal("0.50")
    spent, cap = await openai_spend_and_cap(session, a, now=NOW)
    assert spent == Decimal("0.50") and cap.is_default


async def test_the_system_spend_counts_every_shops_juli_tab(session):
    a, b = await _shop(session), await _shop(session)
    start = month_start_utc(NOW)
    await _answer(session, a, "0.25", start + timedelta(hours=1))
    await _answer(session, b, "0.75", start + timedelta(hours=1))
    await _answer(session, b, "5.00", start - timedelta(days=1))
    assert await system_spend_since(session, start) == Decimal("1.00")
