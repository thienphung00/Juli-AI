"""F11 final order via ``forecast.triggers.rank`` and F2 stale marker on Đề xuất cards."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from juli_backend.services.forecast import triggers as trg
from juli_backend.services.shopee_recommendations import ranking
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
GAPS = ranking.Gaps({})


def _ri(id, **kw):
    base = {"kind": "price", "family": "promotion", "items": (id,), "kpi_p25": {}, "dgmv_p25": 0.0}
    base.update(kw)
    return ranking.RankInput(id, **base)


def _order(cards, **kw):
    return [x.id for x in ranking.rank(cards, GAPS, **kw).ordered]


def test_order_follows_triggers_rank_on_a_mixed_fixture():
    cards = [
        _ri("opp_big", dprofit_p50=1000.0, trigger_type=trg.OPPORTUNITY),
        _ri("opp_small", dprofit_p50=200.0, trigger_type=trg.OPPORTUNITY),
        _ri("prob_similar", dprofit_p50=950.0, trigger_type=trg.PROBLEM),  # within 10 %
        _ri("prob_low", dprofit_p50=100.0, trigger_type=trg.PROBLEM),
        _ri("rule_lo", dprofit_p50=5.0, trigger_type=trg.RULE, urgency=1.0),
        _ri("rule_hi", dprofit_p50=1.0, trigger_type=trg.RULE, urgency=9.0),
        # profit unknown: valued by dGMV
        _ri("opp_gmv", dprofit_p50=None, dgmv_p50=500.0, trigger_type=trg.OPPORTUNITY),
    ]
    expected = [
        x.product_id or ""
        for x in trg.rank(
            [
                trg.Trigger(
                    c.trigger_type, c.id, None, c.trigger_value(), "profit", urgency=c.urgency
                )
                for c in cards
            ]
        )
    ]
    got = _order(cards)
    assert got == expected
    assert got == [
        "rule_hi",
        "rule_lo",
        "prob_similar",
        "opp_big",
        "opp_gmv",
        "opp_small",
        "prob_low",
    ]


def test_a_larger_opportunity_beats_a_clearly_smaller_problem():
    cards = [
        _ri("prob", dprofit_p50=500.0, trigger_type=trg.PROBLEM),
        _ri("opp", dprofit_p50=1000.0, trigger_type=trg.OPPORTUNITY),
    ]
    assert _order(cards) == ["opp", "prob"]


def test_hard_filters_still_drop_the_same_cards():
    cards = [
        _ri("ok", dprofit_p50=1.0),
        _ri("locked", dprofit_p50=9e6, trigger_type=trg.PROBLEM),
        _ri("nostock", in_stock=False, dprofit_p50=9e6),
        _ri("floor", floor_breach=True, dprofit_p50=9e6),
        _ri("spend", spend_after=11.0, spend_cap=10.0, dprofit_p50=9e6),
        _ri("loss", dprofit_p50=-1.0, trigger_type=trg.RULE, urgency=99.0),
    ]
    r = ranking.rank(cards, GAPS, locked={"locked": "sent:x"})
    assert [x.id for x in r.ordered] == ["ok"]
    assert {d["id"]: d["reasons"] for d in r.dropped} == {
        "locked": ["locked_by_plan"],
        "nostock": ["out_of_stock"],
        "floor": ["below_operating_floor"],
        "spend": ["over_spend_cap"],
        "loss": ["negative_profit_p50"],
    }


@pytest.fixture
async def shop_env(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return await load_env(session, seeded.shop_id, as_of=AS_OF)


def _cand():
    return Candidate(
        "product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor", gap_pct=25.0
    )


async def test_a_fresh_card_has_no_stale_marker(shop_env):
    shop_env.today = AS_OF
    card = build_card(shop_env, _cand(), now=NOW)
    assert card is not None
    assert card["stale"] is None
    assert card["predicted"]["money_per_month"]["stale"] is None


async def test_a_stale_card_carries_the_marker_and_null_shown_numbers(shop_env):
    shop_env.today = AS_OF + timedelta(days=30)
    card = build_card(shop_env, _cand(), now=NOW)
    assert card is not None
    stale = card["stale"]
    assert stale is not None and stale["dataset"] in ("orders", "traffic")
    assert stale["through"] <= AS_OF.isoformat()
    money = card["predicted"]["money_per_month"]
    assert money["stale"] == stale
    assert money["shown"] == {"dgmv": None, "dorders": None, "dprofit": None}
