"""Track P (decisions #42-#47): the plan on the card basis. The plan total is the sum of the
separate card results (Lợi nhuận đóng góp) − Δ ads (each campaign once across the plan, its
groups and the month goal) − the affiliate cards' commission; exclusive programmes on one SKU
count once. Synthetic figures only."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace as NS
from typing import Any

import pytest

from juli_backend.services.shopee_recommendations import month_plan
from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from tests.unit.test_p98_plan_results import result

H = pa.Horizon(date(2026, 11, 10))


def _ev(card_id: str, kind: str, product: str = "p1") -> Any:
    return NS(
        entry=NS(card_id=card_id, code=card_id.upper()),
        cand=NS(kind=kind, campaign_key=None),
        product=product,
        parts=[],
    )


def _leaf(card_id: str, d_profit: float, *, start: date | None = None, days: int = 14):
    return pa.CardResult(
        card_id, result(d_gmv=100_000, d_orders=2, d_profit=d_profit, days=days), start=start
    )


# ------------------------------------------------------- #47: exclusive programmes on one SKU


def test_two_exclusive_programmes_on_one_sku_count_the_better_one():
    """A Combo and a Flash Sale on the same product and dates: only the higher P50 Δ profit
    counts; the other is flagged ``exclusive_programme`` and adds nothing."""
    evs = [_ev("combo", "bundle_deal"), _ev("flash", "flash_sale")]
    results = {"combo": _leaf("combo", 50_000), "flash": _leaf("flash", 80_000)}
    pa.resolve_exclusive(results, evs, H)
    assert results["combo"].replaced_by == "FLASH"
    assert results["combo"].reason == pa.EXCLUSIVE_REASON
    assert results["flash"].replaced_by is None
    total = pa.combine_results(list(results.values()), H)
    assert total["p50"]["dprofit"] == pytest.approx(80_000)


def test_exclusive_programmes_on_dates_that_do_not_overlap_both_count():
    evs = [_ev("combo", "bundle_deal"), _ev("flash", "flash_sale")]
    results = {
        "combo": _leaf("combo", 50_000, start=H.start, days=7),
        "flash": _leaf("flash", 80_000, start=H.start + timedelta(days=7), days=7),
    }
    pa.resolve_exclusive(results, evs, H)
    assert results["combo"].replaced_by is None and results["flash"].replaced_by is None
    total = pa.combine_results(list(results.values()), H)
    assert total["p50"]["dprofit"] == pytest.approx(130_000)


def test_a_voucher_is_not_exclusive_with_a_programme():
    evs = [_ev("v", "min_spend_voucher"), _ev("flash", "flash_sale")]
    results = {"v": _leaf("v", 50_000), "flash": _leaf("flash", 80_000)}
    pa.resolve_exclusive(results, evs, H)
    assert results["v"].replaced_by is None


def test_exclusive_programmes_on_two_products_both_count():
    evs = [_ev("combo", "bundle_deal", "p1"), _ev("flash", "flash_sale", "p2")]
    results = {"combo": _leaf("combo", 50_000), "flash": _leaf("flash", 80_000)}
    pa.resolve_exclusive(results, evs, H)
    assert results["combo"].replaced_by is None


# ------------------------------------------------ P4: a campaign counted once across sides


def _side(campaign: str, dates: list[date], per_day: float, cards: list[dict[str, Any]]):
    return {
        "cost": {
            "ads_campaigns": [
                {
                    "campaign": campaign,
                    "cost_horizon": per_day * len(dates),
                    "dates": [d.isoformat() for d in dates],
                    "cost_per_day": per_day,
                }
            ]
        },
        "cards": cards,
    }


def _card(cid: str, campaign: str, cost: float, d_profit: float) -> dict[str, Any]:
    return {
        "card_id": cid,
        "result": {
            "ads": [{"campaign": campaign}],
            "own": {
                "dates": {"from": "2026-11-10", "to": "2026-11-19"},
                "days": 10,
                "delta": {"p50": {"dgmv": 0.0, "dprofit": d_profit}},
                "cost_total": cost,
                "cost_counted_share": 1.0,
            },
        },
    }


def test_a_campaign_shared_by_a_group_and_the_plan_is_counted_once():
    days = [H.start + timedelta(days=i) for i in range(10)]
    plan_side = _side("C", days, 10_000.0, [_card("a", "C", 100_000.0, 20_000.0)])
    group_side = _side("C", days, 10_000.0, [_card("b", "C", 100_000.0, 20_000.0)])
    twice = pa.campaign_overlap([plan_side, group_side])
    assert twice == {"C": pytest.approx(100_000.0)}  # 2 x 100.000 counted, once = 100.000
    pa._once_shares([plan_side, group_side], twice)
    # the month goal of the two cards = the plan's: each now counts half the campaign
    first, last = H.start, H.start + timedelta(days=9)
    gmv, profit, n = month_plan.uplift_in_month(
        [plan_side["cards"][0], group_side["cards"][0]], first, last
    )
    # each own Δ (20.000) held its full 100.000; together they hold the campaign once
    assert n == 2 and profit == pytest.approx(20_000 + 20_000 + 100_000)


def test_different_campaigns_are_never_merged():
    days = [H.start + timedelta(days=i) for i in range(10)]
    assert pa.campaign_overlap([_side("C", days, 1.0, []), _side("D", days, 1.0, [])]) == {}


def test_the_month_goal_skips_a_card_the_plan_does_not_count():
    card = _card("a", "C", 0.0, 50_000.0)
    card["result"]["replaced_by"] = "B"
    gmv, profit, n = month_plan.uplift_in_month([card], date(2026, 11, 10), date(2026, 11, 19))
    assert (profit, n) == (0.0, 0)


# ------------------------------------------------------------- P4: one plan Biên lợi nhuận


def test_the_plan_margin_is_on_doanh_thu_thuc_after_the_new_offers():
    """Biên lợi nhuận after = (profit + Δ) ÷ (doanh thu thực + ΔGMV x net/GMV − new offers)."""
    from decimal import Decimal as D

    env = NS(
        shop_gmv_30d=D(10_000_000),
        shop_orders_30d=100,
        view=NS(profit=NS(margin_rate=D("0.2"), buyer_paid_covered=D(9_000_000))),
    )
    p50 = {"dgmv": 1_000_000.0, "dorders": 10.0, "dprofit": 100_000.0, "drevoffer": 200_000.0}
    d = pa.result_deltas(env, {"p50": p50})
    paid_after = 9_000_000 + 1_000_000 * 0.9 - 200_000
    want = ((0.2 * 9_000_000 + 100_000) / paid_after - 0.2) * 100
    assert d["bien"] == pytest.approx(want)
    # the same Δ profit on a doanh thu thực the voucher lowered: a different margin than ÷ GMV
    no_offer = pa.result_deltas(env, {"p50": {**p50, "drevoffer": 0.0}})
    assert no_offer["bien"] != pytest.approx(d["bien"])


# ----------------------------------------------------------------- P7: the plan's channel Δ


def test_the_plan_channel_delta_adds_up_to_the_plan_total():
    from decimal import Decimal as D

    lever = _leaf("v", 60_000)
    # 20 % of the lever's Δ orders land on the Tiếp thị liên kết source
    res = lever.result
    assert res is not None and res.likely is not None
    before_src = {"lien_ket": {"orders": D(10), "gmv": D(1_000_000), "profit": D(200_000)}}
    likely_src = {"lien_ket": {"orders": D("10.4"), "gmv": D(1_020_000), "profit": D(212_000)}}
    from dataclasses import replace

    lever.result = replace(
        res,
        before=replace(res.before, by_source=before_src),
        likely=replace(res.likely, by_source=likely_src),
    )
    ads = _leaf("a", -30_000)
    ads.campaign = "C"
    results = {"v": lever, "a": ads}
    counted = pa.count_in_horizon(list(results.values()), H)
    split = pa.split_delta(counted, results)
    total = pa.combine_counted(list(counted.values()))["p50"]
    for name in pa.SPLIT_FIELDS:
        assert sum(split[ch][name] for ch in split) == pytest.approx(total[name]), name
    assert split["ads"]["dprofit"] == pytest.approx(-30_000)
    assert split["affiliate"]["dorders"] == pytest.approx(0.4)  # 20 % of the lever's 2 orders
    assert split["affiliate"]["dprofit"] == pytest.approx(12_000)
