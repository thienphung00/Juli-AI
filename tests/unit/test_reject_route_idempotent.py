"""`POST /v1/demo/decisions/{id}/reject` is idempotent and stays per shop (fast track P61-D).

The route (P10-A) stores one reason, closes the card and writes the card log's
`dismissed` row. P61-D makes a repeat of the same reject a 200 no-op instead of a
404 (a retried request, a double tap), and pins that another shop can neither
reject the card nor learn it was rejected. The real-Postgres two-tenant proof is
`tests/integration/test_reject_route_two_tenant.py`.
"""

from __future__ import annotations

from sqlalchemy import func, select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.decision_reasons import DecisionReason
from tests.support.api import authenticated_client
from tests.support.builders import make_product, make_tenant
from tests.unit.test_p10a_card_reasons_edits import _surfaced_card


async def _count(session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for key, value in where.items():
        stmt = stmt.where(getattr(model, key) == value)
    return int((await session.execute(stmt)).scalar_one())


async def test_a_repeat_reject_answers_like_the_first_and_writes_nothing(session):
    user, shop = await make_tenant(session)
    card = await _surfaced_card(session, shop, await make_product(session, shop))
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop) as client:
        first = await client.post(
            f"/v1/demo/decisions/{card.id}/reject", json={"reason_code": "not_convincing"}
        )
        again = await client.post(
            f"/v1/demo/decisions/{card.id}/reject", json={"reason_code": "other"}
        )

    assert first.status_code == 200, first.text
    assert again.status_code == 200, again.text
    assert (
        again.json()
        == first.json()
        == {
            "status": "rejected",
            "cooldown_until": first.json()["cooldown_until"],
        }
    )
    assert await _count(session, DecisionReason, action_card_id=card.id) == 1
    (reason,) = (await session.execute(select(DecisionReason))).scalars().all()
    assert reason.reason_code == "not_convincing", "the repeat must not overwrite the reason"
    assert await _count(session, CardEvent, card_id=card.id, event_type="dismissed") == 1, (
        "a repeat must not write a second `dismissed` event"
    )
    await session.refresh(card)
    assert card.status == "dismissed"


async def test_a_repeat_still_validates_the_body(session):
    user, shop = await make_tenant(session)
    card = await _surfaced_card(session, shop, await make_product(session, shop))
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop) as client:
        await client.post(f"/v1/demo/decisions/{card.id}/reject", json={"reason_code": "other"})
        bad = await client.post(f"/v1/demo/decisions/{card.id}/reject", json={})

    assert bad.status_code == 422


async def test_another_shop_cannot_reject_nor_see_a_rejected_card(session):
    user_a, shop_a = await make_tenant(session)
    user_b, shop_b = await make_tenant(session)
    card_a = await _surfaced_card(session, shop_a, await make_product(session, shop_a))
    await session.commit()

    async with authenticated_client(session, user=user_b, shop=shop_b) as client_b:
        before = await client_b.post(
            f"/v1/demo/decisions/{card_a.id}/reject", json={"reason_code": "other"}
        )
    async with authenticated_client(session, user=user_a, shop=shop_a) as client_a:
        own = await client_a.post(
            f"/v1/demo/decisions/{card_a.id}/reject", json={"reason_code": "discontinued"}
        )
    async with authenticated_client(session, user=user_b, shop=shop_b) as client_b:
        after = await client_b.post(
            f"/v1/demo/decisions/{card_a.id}/reject", json={"reason_code": "other"}
        )

    assert before.status_code == 404
    assert own.status_code == 200
    # Not 200: the idempotent answer is the owner's only -- no existence oracle.
    assert after.status_code == 404
    assert await _count(session, DecisionReason) == 1
    assert await _count(session, DecisionReason, shop_id=shop_b.id) == 0


async def test_a_card_closed_some_other_way_is_still_404(session):
    user, shop = await make_tenant(session)
    card = await _surfaced_card(session, shop, await make_product(session, shop))
    card.status = "approved"
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop) as client:
        resp = await client.post(
            f"/v1/demo/decisions/{card.id}/reject", json={"reason_code": "other"}
        )

    assert resp.status_code == 404
    assert await _count(session, DecisionReason) == 0
