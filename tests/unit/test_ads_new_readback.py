"""P99b: an ``ads_new_campaign`` card is matched to the campaign the owner created by hand and
read back from that campaign's own ingested rows (synthetic data)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace as NS

from juli_backend.services.shopee_recommendations import ads_readback as ar

START = date(2026, 11, 3)


def _card(name="Mùa Tết SP A", items=("1", "2"), start=START, **inputs):
    return {
        "change_kind": "ads_new_campaign",
        "inputs": {"name": name, "start": start.isoformat(), "days": 7, **inputs},
        "scope": {"product_ids": list(items)},
    }


def _daily(segment, name, day, cost=100.0, gmv=500.0, orders=5.0):
    return NS(
        segment=segment, platform_source=name, day=day, extra={"cost": cost}, gmv=gmv, orders=orders
    )


def _period(name, item):
    return NS(platform_source=name, item_id=item)


def _seen(*camps):
    daily, periods = [], []
    for seg, name, first, items in camps:
        daily.append(_daily(seg, name, first))
        periods += [_period(name, i) for i in items]
    return ar.campaigns_seen(daily, periods)


def test_exact_name_match_ignores_case_and_spacing():
    seen = _seen(("c1", "  mùa  TẾT sp a ", START, ["9"]))
    m = ar.match_card(_card(), seen)
    assert (m.state, m.matched_by, m.campaign.segment) == ("matched", "name", "c1")


def test_products_and_start_within_one_day_when_name_differs():
    seen = _seen(("c1", "Khác tên", date(2026, 11, 4), ["2", "1"]))
    m = ar.match_card(_card(), seen)
    assert (m.state, m.matched_by) == ("matched", "products_start")


def test_start_two_days_off_or_other_products_is_not_found():
    far = _seen(("c1", "X", date(2026, 11, 5), ["1", "2"]))
    other = _seen(("c1", "X", START, ["1"]))
    for seen in (far, other):
        m = ar.match_card(_card(), seen)
        assert (m.state, m.reason) == ("not_found", "no_campaign_fits")
        assert m.json()["label"] == "chưa thấy chiến dịch trên Shopee"


def test_no_ads_data_is_not_found_not_zero():
    m = ar.match_card(_card(), [])
    assert (m.state, m.reason) == ("not_found", "no_ads_data")


def test_two_fitting_campaigns_are_ambiguous_with_a_reason():
    seen = _seen(("c1", "A", START, ["1", "2"]), ("c2", "B", START, ["1", "2"]))
    m = ar.match_card(_card(name="Z"), seen)
    assert (m.state, m.reason, m.campaign) == ("ambiguous", "same_products_many", None)
    assert m.json()["reason_text"]
    same = _seen(("c1", "Mùa Tết SP A", START, []), ("c2", "mùa tết sp a", START, []))
    assert ar.match_card(_card(), same).reason == "same_name_many"


def test_one_campaign_cannot_belong_to_two_cards():
    seen = _seen(("c1", "Mùa Tết SP A", START, ["1", "2"]))
    out = ar.match_cards({"a": _card(), "b": _card(name="khác")}, seen)
    assert {m.state for m in out.values()} == {"ambiguous"}
    assert out["a"].reason == "campaign_matches_other_card"


def test_actuals_sum_only_that_campaign_and_unknown_is_none():
    rows = [
        ar.DayRow(date(2026, 11, 3), 100.0, 500.0, 5.0),
        ar.DayRow(date(2026, 11, 4), 200.0, 900.0, 7.0),
    ]
    got = ar.read_actual(rows, START, date(2026, 11, 9), yesterday=date(2026, 11, 4))
    assert (got["spend"], got["gmv"], got["orders"]) == (300.0, 1400.0, 12.0)
    assert got["roas"] == 1400 / 300
    assert got["days_covered"] == got["days_expected"] == 2

    gap = ar.read_actual(rows, START, date(2026, 11, 9), yesterday=date(2026, 11, 6))
    assert gap["spend"] == 300.0 and "coverage" in gap["reasons"]

    nocost = ar.read_actual([ar.DayRow(START, None, 5.0, 1.0)], START, START, START)
    assert nocost["spend"] is None and nocost["roas"] is None and "spend" in nocost["reasons"]
    assert nocost["gmv"] == 5.0

    none = ar.read_actual([], START, date(2026, 11, 9), yesterday=date(2026, 11, 5))
    assert none["spend"] is None and none["gmv"] is None and none["orders"] is None
    early = ar.read_actual(rows, START, date(2026, 11, 9), yesterday=date(2026, 11, 2))
    assert early["spend"] is None and early["reasons"]["spend"]


def test_card_end_prefers_end_then_days():
    assert ar.card_end(_card()) == date(2026, 11, 9)
    assert ar.card_end(_card(end="2026-11-05")) == date(2026, 11, 5)
