"""S5 (Q8): an affiliate / KOC card on a product with no orders in the window is estimated on the
prior (the shop's median orders +5 %) instead of being refused. Synthetic shop."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from juli_backend.services.shopee_recommendations import config, manual
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.evaluate import evaluate
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.no_order_prior import baseline_orders, order_prior
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
NEW_ITEM = "9990001"  # a listing nobody bought in the window


@pytest.fixture
async def env(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return await load_env(session, seeded.shop_id, as_of=AS_OF)


def _cand(kind="affiliate_commission", item=NEW_ITEM, pct=8):
    return Candidate(kind, (item,), {"commission_pct": pct}, wiring_key="lien_ket")


async def test_the_prior_is_the_shop_median_orders_plus_five_percent(env):
    assert env.orders_of(NEW_ITEM) == 0
    base = baseline_orders(env, NEW_ITEM)
    prior = order_prior(env, NEW_ITEM)
    assert base is not None and prior is not None
    assert prior.orders == base * Decimal("1.05")
    assert config.NO_ORDER_UPLIFT == 0.05


async def test_a_commission_card_on_a_product_with_no_orders_is_evaluated(env):
    ev = evaluate(env, _cand())
    assert ev.refusal is None
    assert ev.certain["affiliate_orders"] == 0
    assert ev.certain["commission_cost_after"] > 0
    assert ev.certain["order_prior"]["uplift"] == 0.05
    assert ev.profit.base_orders_per_day > 0


async def test_it_reaches_a_card_with_numbers(env):
    card = build_card(env, _cand(), now=NOW)
    assert card is not None
    assert card["certain"]["commission_pct_after"] == 8


async def test_a_shop_with_no_sale_at_all_is_still_refused_in_vietnamese(env):
    assert manual.refusal("no_order_lines")["message"].startswith("Chưa có đơn")
