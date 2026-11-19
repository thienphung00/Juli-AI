"""batch-1119 t2-plan (owner A2.1-A2.5, A3.1): the plan's Δ lợi nhuận subtracts the certain cost
of the cards it cannot estimate, an ads campaign's budget is counted once, and a card in a group
counts only on its group's days. Pure tests on hand-made results (invented figures)."""

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


def test_t2_1_a_not_estimable_ads_card_costs_its_budget_times_days_at_every_quantile():
    base = totals(discount())
    ads = not_estimable("ads", days=14, cost=100_000 * 14)  # daily budget 100.000 x 14 days
    both = totals(discount(), ads)
    for q in ("p10", "p50", "p90"):
        assert both[q]["dprofit"] == pytest.approx(base[q]["dprofit"] - 1_400_000)
    assert both["p50"]["dgmv"] == base["p50"]["dgmv"]  # no sales effect assumed


def test_t2_1_the_cost_counts_only_the_days_inside_the_horizon():
    late = not_estimable("ads", days=14, cost=1_400_000, start=H.end - 6 * DAY)  # 7 days inside
    got = totals(discount(), late)
    assert got["p50"]["dprofit"] == pytest.approx(totals(discount())["p50"]["dprofit"] - 700_000)


def test_t2_2_affiliate_and_combo_certain_costs_come_off_too():
    base = totals(discount())
    aff = not_estimable("aff", days=30, cost=250_960)  # commission % x current affiliate GMV
    combo = not_estimable("combo", days=14, cost=230_543)  # discount x qualifying orders
    for extra, cost in ((aff, 250_960), (combo, 230_543), (None, 250_960 + 230_543)):
        got = totals(discount(), *([extra] if extra else [aff, combo]))
        for q in ("p10", "p50", "p90"):
            assert got[q]["dprofit"] == pytest.approx(base[q]["dprofit"] - cost)


def test_a_card_with_no_result_adds_no_cost_and_the_range_keeps_its_width():
    refused = pa.CardResult("r", None, "no_spec")
    assert totals(discount(), refused) == totals(discount())
    ads = not_estimable("ads", days=14, cost=1_400_000)
    t, b = totals(discount(), ads), totals(discount())
    assert t["p90"]["dprofit"] - t["p10"]["dprofit"] == pytest.approx(
        b["p90"]["dprofit"] - b["p10"]["dprofit"]
    )


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
    got = totals(discount(), a1, a2, ads=DATA)
    assert got["p50"]["dprofit"] == pytest.approx(totals(discount())["p50"]["dprofit"] - 1_400_000)


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
    a = not_estimable("a", days=14, cost=1_400_000, product="p1", campaign="new:a")
    b = not_estimable("b", days=14, cost=1_400_000, product="p2", campaign="new:b")
    assert totals(a, b)["p50"]["dprofit"] == pytest.approx(-2_800_000)


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


def test_a_4_the_total_no_longer_says_tong_chua_gom():
    note = pa._totals_note(
        pa.Joint(
            frozenset(),
            {},
            {},
            {},
            [],
            None,
            [],
            [],
            [],
            not_estimable=["x"],
        ),
        [],
    )
    assert note is None
    merged = pa._merge_note({"not_estimable_cards": ["x"], "unavailable_cards": []}, True)
    assert merged is None
