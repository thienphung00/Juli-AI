"""batch-1119 t2-plan (owner A2.2, A3.1): an ads campaign's budget is counted once (platform spend
shares, cost per order) and a card in a group counts only on its group's days. A card that cannot
be estimated still adds nothing to the plan's Δ (its cost model is the next batch). Pure tests on
hand-made results (invented figures)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from juli_backend.services.shopee_recommendations import plan_aggregate as pa
from tests.unit.test_p98_plan_results import H, result

DAY = timedelta(days=1)


def card(cid, *, start=None, end=None, product=None, campaign=None, **kw):
    return pa.CardResult(
        cid, result(**kw), start=start, end=end, product=product, campaign=campaign
    )


def discount():
    return card("disc", d_gmv=300_000, d_orders=6, d_profit=900_000, lo=500_000, hi=1_400_000)


def not_estimable(cid, *, days, cost, **kw):
    return card(cid, d_gmv=0, d_orders=0, d_profit=0, days=days, cost=cost, estimable=False, **kw)


def totals(*cards, ads=None):
    return pa.combine_results(list(cards), H, ads)


def test_a_not_estimable_card_adds_nothing_to_the_plan_delta():
    base = totals(discount())
    for extra in (
        not_estimable("ads", days=14, cost=1_400_000),
        not_estimable("aff", days=30, cost=250_960),
        not_estimable("combo", days=14, cost=230_543),
    ):
        assert totals(discount(), extra) == base


def test_a_card_with_no_result_is_left_out_too():
    refused = pa.CardResult("r", None, "no_spec")
    assert totals(discount(), refused) == totals(discount())


# --------------------------------------------------------------------------- one campaign, once


def two_cards(**kw):
    return [
        not_estimable("a1", days=14, cost=1_400_000, product="p1", campaign="C", **kw),
        not_estimable("a2", days=14, cost=1_400_000, product="p2", campaign="C", **kw),
    ]


DATA = pa.AdsData(products={"C": {"p1": (300_000.0, 6.0), "p2": (100_000.0, 0.0)}})


def test_t2_3_a_campaign_budget_is_counted_once_and_split_by_the_platforms_spend_share():
    a1, a2 = two_cards()
    shares = pa.ads_shares([a1, a2], H, DATA)
    assert shares.cost["a1"] == pytest.approx(1_050_000) and shares.cost["a2"] == pytest.approx(
        350_000
    )
    assert sum(shares.cost.values()) == pytest.approx(1_400_000)


def test_t2_3_equal_split_when_the_platform_spent_nothing_and_shares_add_up_exactly():
    cards = [
        not_estimable(f"c{i}", days=14, cost=100_000 * 14, product=f"p{i}", campaign="C")
        for i in range(3)
    ]
    shares = pa.ads_shares(cards, H, pa.AdsData())
    assert sum(shares.cost.values()) == 1_400_000  # exactly, the last card takes the remainder
    assert all(math.isclose(v, 1_400_000 / 3) for v in shares.cost.values())


def test_t2_3_an_estimable_ads_card_keeps_only_its_share_of_the_cost():
    a1 = card(
        "a1",
        d_gmv=0,
        d_orders=0,
        d_profit=-1_400_000,
        days=14,
        cost=1_400_000,
        product="p1",
        campaign="C",
    )
    a2 = card(
        "a2",
        d_gmv=0,
        d_orders=0,
        d_profit=-1_400_000,
        days=14,
        cost=1_400_000,
        product="p2",
        campaign="C",
    )
    got = totals(a1, a2, ads=DATA)
    assert got["p50"]["dprofit"] == pytest.approx(-1_400_000)  # once, not -2.800.000


def test_a_new_campaign_is_its_own_campaign():
    def new(cid, product):
        return card(
            cid,
            d_gmv=0,
            d_orders=0,
            d_profit=-1_400_000,
            days=14,
            cost=1_400_000,
            product=product,
            campaign=f"new:{cid}",
        )

    assert totals(new("a", "p1"), new("b", "p2"))["p50"]["dprofit"] == pytest.approx(-2_800_000)


def test_t2_3b_cost_per_order_is_platform_spend_over_platform_orders():
    assert DATA.cost_per_order("C", "p1") == pytest.approx(50_000)
    assert DATA.cost_per_order("C", "p2") is None  # no order: unknown, never 0
    assert DATA.cost_per_order("C") == pytest.approx(400_000 / 6)
    assert DATA.cost_per_order("other") is None
    block = pa.ads_shares(two_cards(), H, DATA).campaigns["C"]
    assert block["cost_per_order"] == pytest.approx(400_000 / 6)
    by_card = {c["card_id"]: c for c in block["cards"]}
    assert by_card["a1"]["cost_per_order"] == pytest.approx(50_000)
    assert by_card["a2"]["cost_per_order"] is None


def test_t2_4_a_running_campaign_elapsed_days_use_measured_spend_forward_days_the_budget():
    first, today = date(2026, 11, 1), date(2026, 11, 4)
    measured = {first: 60_000.0, first + DAY: 80_000.0, first + 2 * DAY: 0.0}
    got = pa.campaign_span_cost(100_000, first, first + 6 * DAY, today, measured)
    assert got["elapsed_days"] == 3 and got["elapsed_spend"] == pytest.approx(140_000)
    assert got["forward_days"] == 4 and got["forward_cost"] == pytest.approx(400_000)
    assert got["total"] == pytest.approx(540_000)


def test_t2_4_ads_data_reads_the_env_rows_and_the_campaigns_daily_spend():
    from types import SimpleNamespace as NS

    row = lambda k, i, s, o: NS(key=k, item_id=i, spend=s, orders=o)  # noqa: E731
    env = NS(
        view=NS(
            data=NS(ads_reports=NS(campaign_rows=[row("C", "p1", 10, 2), row("C", "", 99, 9)]))
        ),
        as_of=date(2026, 11, 10),
        campaigns={"C": NS(days=((5, None), (7, None)))},
    )
    data = pa.ads_data_of(env)
    assert data.products == {"C": {"p1": (10.0, 2.0)}}  # the campaign's total row is not a product
    assert data.daily["C"] == {date(2026, 11, 9): 5.0, date(2026, 11, 10): 7.0}


# ------------------------------------------------------------------------------- group days


def test_t2_5_a_14_day_card_in_a_7_day_group_counts_7_days():
    start = H.start
    g = card(
        "g",
        d_gmv=140_000,
        d_orders=14,
        d_profit=140_000,
        days=14,
        cost=14_000,
        start=start,
        end=start + 6 * DAY,
    )
    assert g.own_span(H) == (start, start + 6 * DAY)
    assert g.counted_days(H) == 7
    assert g.delta("likely", H)["dprofit"] == pytest.approx(70_000)
    assert g.cost_in(H) == pytest.approx(7_000)


def test_t2_5_two_discounts_on_one_product_in_groups_a_and_b_do_not_overlap():
    a_start = H.start
    b_start = a_start + 7 * DAY
    a = card(
        "a",
        d_gmv=0,
        d_orders=0,
        d_profit=140_000,
        days=14,
        product="p",
        start=a_start,
        end=a_start + 6 * DAY,
    )
    b = card(
        "b",
        d_gmv=0,
        d_orders=0,
        d_profit=140_000,
        days=14,
        product="p",
        start=b_start,
        end=b_start + 6 * DAY,
    )
    sa, sb = a.counted(H), b.counted(H)
    assert sa[1] < sb[0]  # no shared day
    assert a.counted_days(H) + b.counted_days(H) == 14
    assert totals(a, b)["p50"]["dprofit"] == pytest.approx(140_000)


def test_a_card_starting_after_its_group_ends_counts_nothing():
    g = card(
        "g",
        d_gmv=1,
        d_orders=1,
        d_profit=1,
        days=14,
        start=H.start + 9 * DAY,
        end=H.start + 6 * DAY,
    )
    assert g.counted(H) is None and g.counted_days(H) == 0


# --------------------------------------------------------------------------------- the note


def test_the_total_still_says_which_cards_it_leaves_out():
    j = pa.Joint(frozenset(), {}, {}, {}, [], None, [], [], [], not_estimable=["x"])
    assert pa._totals_note(j, []) == "Tổng chưa gồm 1 thẻ chưa ước tính được."
    merged = pa._merge_note({"not_estimable_cards": ["x"], "unavailable_cards": []}, True)
    assert merged == "Tổng chưa gồm 1 thẻ chưa ước tính được."


# ------------------------------------------------------------- owner notes (verifier round)


def test_cards_on_one_campaign_with_different_budgets_count_the_lower_one():
    low = not_estimable("low", days=14, cost=100_000 * 14, product="p1", campaign="C")
    high = not_estimable("high", days=14, cost=200_000 * 14, product="p2", campaign="C")
    shares = pa.ads_shares([low, high], H, pa.AdsData())
    assert sum(shares.cost.values()) == pytest.approx(1_400_000)  # 100.000 x 14, not 200.000


def _ev(card_id, kind, product="p1", campaign_key=None):
    from types import SimpleNamespace as NS

    return NS(
        entry=NS(card_id=card_id),
        cand=NS(kind=kind, campaign_key=campaign_key),
        product=product,
        parts=[],
    )


def test_an_ads_card_without_a_key_resolves_to_the_campaign_its_product_spends_in():
    data = pa.AdsData(products={"A": {"p1": (10.0, 1.0)}, "B": {"p1": (50.0, 2.0)}})
    assert pa._campaign_of(_ev("c1", "ads_budget"), data) == "B"  # the larger spend
    assert pa._campaign_of(_ev("c1", "ads_budget", campaign_key="K"), data) == "K"
    assert pa._campaign_of(_ev("c1", "ads_new_campaign"), data) == "new:c1"
    assert pa._campaign_of(_ev("c1", "min_spend_voucher"), data) is None  # not an ads card


def test_an_ads_card_that_cannot_be_resolved_is_tracked_alone_and_counted_in_the_log(caplog):
    evs = [_ev("c1", "ads_budget", "p1"), _ev("c2", "ads_budget", "p2")]
    assert pa._campaign_of(evs[0], pa.AdsData()) == "card:c1"
    results = {e.entry.card_id: pa.CardResult(e.entry.card_id, None, "x") for e in evs}
    with caplog.at_level("INFO", logger=pa.log.name):
        pa.assign_campaigns(results, evs, pa.AdsData())
    assert [r.campaign for r in results.values()] == ["card:c1", "card:c2"]  # never None
    assert [m for m in caplog.messages if "ads_card_without_campaign" in m] == [
        "ads_card_without_campaign count=2"
    ]
    # two such cards are not merged: each keeps its own full cost
    a = not_estimable("c1", days=14, cost=1_400_000, product="p1", campaign="card:c1")
    b = not_estimable("c2", days=14, cost=1_400_000, product="p2", campaign="card:c2")
    assert sum(pa.ads_shares([a, b], H, pa.AdsData()).cost.values()) == pytest.approx(2_800_000)
