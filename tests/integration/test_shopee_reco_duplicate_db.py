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
