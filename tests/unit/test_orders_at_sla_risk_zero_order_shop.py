"""A shop with no orders mints no `process_order_5` card — #1960.

`orders_at_sla_risk` is keyed on a **count** (`orders_at_sla_risk_count: int`).
A count has no `None` state to carry "nothing was measured", so the null-check
that puts every rate-keyed KPI into `unavailable` on an empty denominator could
not protect this one: zero orders produced `count == 0`, which fell through to
`signal_type="opportunity"`, `severity="healthy"`, *"0 đơn at SLA risk · no
orders past dispatch SLA"*. `_score_workflows` skips only `unavailable`, so
that healthy signal became a real, approvable ActionCard telling a seller to
process orders that do not exist.

Both tests drive the **real** path — `run_daily_scoring_for_shop` (aggregates →
`compute_scoring_signals` → `rank_workflow_recommendations`, i.e. `_score_workflows`)
followed by `persist_scoring_result` — rather than calling the signal function
directly. The bug survived precisely because the signal function looked correct
in isolation; only the end-to-end path shows the card.

AC1 → a zero-order shop reports `orders_at_sla_risk` as `unavailable`, not `healthy`.
AC2 → a zero-order shop persists no `process_order_5` ActionCard at all.
AC3 → a shop whose orders really are past the dispatch SLA still mints its card,
       so the false positive is not traded for a false negative.
AC4 → the issue's audit question, made observable: a shop with nothing synced at all
       reports *every* KPI as `unavailable` and mints no card. `orders_at_sla_risk`
       was the last KPI that did not, which is what made it the unique instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Order, Product, Shop, User
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.aggregates.thresholds import ORDER_DISPATCH_SLA_HOURS
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop

COMPUTED_AT = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)

PROCESS_ORDER = "process_order_5"


def _product(shop_id: uuid.UUID) -> Product:
    """A saleable catalogue, so the shop is not empty of every data source.

    Without this the shop would have nothing at all and the absence of a
    `process_order_5` card would prove nothing — the pipeline has to produce
    *some* recommendations for the assertion to be about orders specifically.
    """
    return Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        tiktok_product_id="prod-1960",
        name="Widget 1960",
        status="ACTIVE",
        category="Electronics",
        revenue=Decimal("900000"),
        units_sold=30,
        update_time=COMPUTED_AT,
    )


async def _make_shop(session, user_id: uuid.UUID, phone: str, name: str) -> Shop:
    user = User(id=user_id, phone=phone)
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name=name,
        tiktok_shop_id=f"tiktok_shop_{phone[-6:]}",
        created_at=COMPUTED_AT - timedelta(days=120),
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def shop_without_orders(session, user_id):
    """Production shape as of #1960: products synced, `orders` empty."""
    shop = await _make_shop(session, user_id, "+84901960001", "Zero Order Shop")
    session.add(_product(shop.id))
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def shop_with_orders_past_sla(session, user_id):
    """Two in-window orders, unshipped, both past the 48h dispatch deadline."""
    shop = await _make_shop(session, user_id, "+84901960002", "Late Dispatch Shop")
    placed = COMPUTED_AT - timedelta(hours=ORDER_DISPATCH_SLA_HOURS + 6)
    session.add(_product(shop.id))
    session.add_all(
        [
            Order(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_order_id=f"ord-late-{index}",
                status="AWAITING_SHIPMENT",
                buyer_id=f"buyer-{index}",
                total_amount=Decimal("150000"),
                currency="VND",
                payment_time=placed,
                ship_time=None,
                update_time=COMPUTED_AT,
                created_at=placed,
            )
            for index in range(2)
        ]
    )
    await session.flush()
    return shop


async def _cards_by_workflow(session, shop_id: uuid.UUID) -> dict[str, ActionCard]:
    rows = await session.execute(select(ActionCard).where(ActionCard.shop_id == shop_id))
    return {card.workflow_key: card for card in rows.scalars().all()}


@pytest.mark.asyncio
async def test_zero_order_shop_mints_no_approvable_process_order_card(session, shop_without_orders):
    """AC1 + AC2: no orders ⇒ `unavailable`, and no `process_order_5` row at all."""
    result = await run_daily_scoring_for_shop(
        session, shop_without_orders.id, computed_at=COMPUTED_AT
    )

    signal = result.signals.kpis["orders_at_sla_risk"]
    assert signal.signal_type == "unavailable", (
        "a shop with no orders has no SLA-risk signal to report; "
        f"got {signal.signal_type}/{signal.severity} — {signal.one_line}"
    )
    assert signal.severity == "not_applicable"
    assert signal.technique == "unavailable"

    # `_score_workflows` skips `unavailable` signals, so the only two KPIs that
    # feed process_order_5 (this one and fulfillment_accuracy_rate, itself
    # unavailable on an empty ship-time denominator) leave it unrecommended.
    assert result.signals.kpis["fulfillment_accuracy_rate"].signal_type == "unavailable"
    recommended = {item.workflow_key for item in result.recommendations.recommended_workflows}
    assert PROCESS_ORDER not in recommended, (
        f"process_order_5 was recommended for a shop with zero orders: {sorted(recommended)}"
    )

    await persist_scoring_result(session, shop_without_orders.id, result)
    await session.flush()

    cards = await _cards_by_workflow(session, shop_without_orders.id)
    assert PROCESS_ORDER not in cards, (
        "a zero-order shop was handed an approvable card to process orders "
        f"that do not exist: {cards.get(PROCESS_ORDER)}"
    )
    # The shop is still scored — the assertion above is about orders, not about
    # the pipeline having produced nothing.
    assert cards, "expected the product-backed workflows to still mint their cards"


@pytest_asyncio.fixture
async def shop_with_nothing_synced(session, user_id):
    """A connected shop whose every commerce and analytics table is still empty."""
    return await _make_shop(session, user_id, "+84901960003", "Nothing Synced Shop")


@pytest.mark.asyncio
async def test_a_shop_with_no_synced_data_reports_every_kpi_unavailable_and_mints_no_card(
    session, shop_with_nothing_synced
):
    """AC4: the audit's claim, made observable rather than asserted in prose.

    Every KPI but one already expressed "nothing measured" as `unavailable` on an
    empty population — the rate-keyed ones through a `None` metric, the count-keyed
    `net_revenue`/`aov`/`cac` through an explicit zero check. `orders_at_sla_risk`
    was the only hold-out, which is exactly why it alone minted a card here. With
    it fixed, a shop with nothing synced reports no verdict about anything.
    """
    result = await run_daily_scoring_for_shop(
        session, shop_with_nothing_synced.id, computed_at=COMPUTED_AT
    )

    live = {
        kpi_id: (signal.signal_type, signal.severity)
        for kpi_id, signal in result.signals.kpis.items()
        if signal.signal_type != "unavailable"
    }
    assert live == {}, f"a shop with nothing synced reported a verdict on: {live}"
    assert all(signal.severity == "not_applicable" for signal in result.signals.kpis.values())

    await persist_scoring_result(session, shop_with_nothing_synced.id, result)
    await session.flush()

    assert await _cards_by_workflow(session, shop_with_nothing_synced.id) == {}


@pytest.mark.asyncio
async def test_shop_with_orders_past_sla_still_mints_its_process_order_card(
    session, shop_with_orders_past_sla
):
    """AC3: the false positive is not fixed by creating a false negative."""
    result = await run_daily_scoring_for_shop(
        session, shop_with_orders_past_sla.id, computed_at=COMPUTED_AT
    )

    signal = result.signals.kpis["orders_at_sla_risk"]
    assert signal.signal_type == "risk"
    assert signal.severity == "warning"
    assert "2 đơn at SLA risk" in signal.change_text

    recommendation = next(
        item
        for item in result.recommendations.recommended_workflows
        if item.workflow_key == PROCESS_ORDER
    )
    assert recommendation.preconditions_met is True
    assert "orders_at_sla_risk" in recommendation.source_kpi_ids

    await persist_scoring_result(session, shop_with_orders_past_sla.id, result)
    await session.flush()

    cards = await _cards_by_workflow(session, shop_with_orders_past_sla.id)
    assert PROCESS_ORDER in cards
    assert cards[PROCESS_ORDER].status == "active"
    assert cards[PROCESS_ORDER].severity == "warning"
