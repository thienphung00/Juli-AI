"""S4 on real Postgres: a card that repeats an open card (same kind, target, changed field and
target value) is refused with a Vietnamese reason naming the existing card's code, whatever its
origin; a different value, or a card that is withdrawn / finished, does not block. Synthetic
tenants and figures only."""

from __future__ import annotations

from datetime import datetime

import pytest

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.shopee_recommendations import manual, store
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_reco_db import stub_card
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

NOW = datetime(2026, 11, 4, 3, 0)


def _variants():
    return [{"label": "A", "change_kind": "gift", "items": ["5005"], "extra": {}, "inputs": {}}]


def _card(budget: int = 120_000) -> dict:
    card = stub_card("5005", "gift", "combo")
    card["change"]["after"] = {"daily_budget": budget}
    return card


async def _make(session, shop_id, user_id, budget=120_000, origin=manual.ORIGIN_MANUAL):
    return await manual.create_manual(
        session,
        shop_id,
        _variants(),
        0,
        False,
        manual.Actor("seller", user_id),
        now=NOW,
        cards=[_card(budget)],
        origin=origin,
    )


@pytest.mark.parametrize("origin", [manual.ORIGIN_MANUAL, "agent", "external"])
async def test_a_repeated_open_change_is_refused_naming_the_existing_code(shopee_tenants, origin):
    a, _ = shopee_tenants
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        first = await _make(session, a.shop_id, a.user_id)
        with pytest.raises(manual.ProposalError) as err:
            await _make(session, a.shop_id, a.user_id, origin=origin)
        assert err.value.code == manual.ERROR_DUPLICATE
        assert first["code"] in str(err.value) and "trùng" in str(err.value)


async def test_another_value_is_not_a_duplicate(shopee_tenants):
    a, _ = shopee_tenants
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        await _make(session, a.shop_id, a.user_id)
        other = await _make(session, a.shop_id, a.user_id, budget=150_000)
        assert other["code"]


async def test_a_finished_card_does_not_block_and_an_existing_pair_is_left_alone(shopee_tenants):
    a, _ = shopee_tenants
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        first = await _make(session, a.shop_id, a.user_id)
        p = [r for r, _ in await store.list_cards(session, a.shop_id) if r.code == first["code"]][0]
        p.status = "measured"
        await session.flush()
        again = await _make(session, a.shop_id, a.user_id)
        assert again["code"] != first["code"]
        assert await store.find_open_duplicate(session, a.shop_id, _card()) is not None


async def test_s6_every_card_kind_can_be_withdrawn_one_by_one(shopee_tenants):
    """Q7: the removal in Đề xuất is by card id (``service.withdraw``) and has no kind branch;
    this proves it for every kind the engine knows (mega sale cards are built apart)."""
    from juli_backend.services import shopee_recommendations as reco
    from juli_backend.services.shopee_recommendations.kinds import KINDS, spec

    a, _ = shopee_tenants
    kinds = [k for k in KINDS if spec(k).family != "mega_sale"]
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        made: dict[str, object] = {}
        for n, kind in enumerate(kinds):
            card = stub_card(f"7{n:04d}", kind, spec(kind).family)
            card["change"]["after"] = {"marker": kind}
            made[kind] = await store.save_card(
                session, a.shop_id, card, cycle="2026-11", position=n + 1, now=NOW
            )
        for kind, card_id in made.items():
            await reco.withdraw(session, a.shop_id, card_id, now=NOW, reason_code="not_fit")
        rows = {p.id: p.status for p, _ in await store.list_cards(session, a.shop_id)}
        assert {rows[i] for i in made.values()} == {"withdrawn"}, kinds


async def test_a_replacement_is_never_its_own_twin_but_is_a_twin_of_another_open_card(
    shopee_tenants,
):
    """Replacement / revision path (stale.py): the card being replaced is excluded."""
    a, _ = shopee_tenants
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        first = await _make(session, a.shop_id, a.user_id)
        card = _card()
        mine = [
            r for r, _ in await store.list_cards(session, a.shop_id) if r.code == first["code"]
        ][0]
        assert await store.find_open_duplicate(session, a.shop_id, card, exclude_id=mine.id) is None
        other = await _make(session, a.shop_id, a.user_id, budget=150_000)
        twin_card = _card(150_000)
        found = await store.find_open_duplicate(session, a.shop_id, twin_card, exclude_id=mine.id)
        assert found is not None and found.code == other["code"]


async def test_s6_every_card_kind_can_be_removed_from_the_draft_plan_one_by_one(shopee_tenants):
    """Q7, Kế hoạch: ``plans.remove_card`` of each non-mega kind leaves the plan with the card
    back at its prior status and its row removed."""
    import uuid as _uuid

    from sqlalchemy import select

    from juli_backend.models.shop_proposals import ShopProposal
    from juli_backend.models.shopee_plans import ShopRecoPlan, ShopRecoPlanCard
    from juli_backend.services.shopee_recommendations import plans
    from juli_backend.services.shopee_recommendations.kinds import KINDS, spec

    a, _ = shopee_tenants
    kinds = [k for k in KINDS if spec(k).family != "mega_sale"]
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        plan = ShopRecoPlan(
            id=_uuid.uuid4(), shop_id=a.shop_id, status="draft", product_windows={},
            created_by={}, created_at=NOW, updated_at=NOW,
        )  # fmt: skip
        session.add(plan)
        await session.flush()
        ids: dict[str, _uuid.UUID] = {}
        for n, kind in enumerate(kinds):
            card = stub_card(f"7{n:04d}", kind, spec(kind).family)
            card["change"]["after"] = {"marker": kind}
            cid = await store.save_card(
                session, a.shop_id, card, cycle="2026-11", position=n + 1, now=NOW
            )
            p = await session.get(ShopProposal, cid)
            p.status = "planned"
            p.lever_plan_id = plan.id
            session.add(
                ShopRecoPlanCard(
                    id=_uuid.uuid4(), shop_id=a.shop_id, plan_id=plan.id, proposal_id=cid,
                    chosen_version=1, inputs={}, prior_status="sent", position=n,
                    added_by={}, added_at=NOW,
                )
            )  # fmt: skip
            ids[kind] = cid
        await session.flush()
        for kind, cid in ids.items():
            try:
                await plans.remove_card(
                    session, a.shop_id, cid, actor=manual.Actor("seller", a.user_id), now=NOW
                )
            except manual.ProposalError as exc:  # the plan read-back needs shop numbers
                assert exc.code == manual.ERROR_NO_DATA, (kind, exc.code)
        rows = (await session.scalars(select(ShopRecoPlanCard))).all()
        assert all(r.removed_at is not None for r in rows), kinds
        got = {(await session.get(ShopProposal, c)).status for c in ids.values()}
        assert got == {"sent"}, kinds


async def test_a_card_marked_reverted_by_hand_does_not_count_as_open(shopee_tenants):
    """E145: an executed card undone in Seller Centre ("Đã hoàn tác thủ công") no longer blocks."""
    a, _ = shopee_tenants
    async with juli_app_session() as session, with_shop_scope(session, a.shop_id):
        first = await _make(session, a.shop_id, a.user_id)
        p = [r for r, _ in await store.list_cards(session, a.shop_id) if r.code == first["code"]][0]
        p.status = "executed"
        await session.flush()
        assert await store.find_open_duplicate(session, a.shop_id, _card()) is not None
        await store.set_meta(session, a.shop_id, p.id, {"reverted": {"by": "seller", "at": "x"}})
        assert await store.find_open_duplicate(session, a.shop_id, _card()) is None
