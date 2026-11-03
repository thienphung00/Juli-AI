"""P90 Step 6: ad spend primary source (G-07), the order basis guard (D-2), the voucher join
(G-14). Pure. One test per conflict pair, each asserting which value wins. Synthetic numbers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_profit.ads_sources import (
    BASIS_CONFIRMED,
    BASIS_PLACED,
    AdDay,
    AdWindow,
    Figure,
    OrderBasisError,
    campaign_key,
    confirmed_total,
    resolve_ad_spend,
)
from juli_backend.services.shopee_profit.vouchers import (
    VoucherExport,
    VoucherSetting,
    join_vouchers,
)

OCT1, OCT2, OCT3, OCT4 = (date(2026, 10, d) for d in (1, 2, 3, 4))


def _day(campaign: str, day: date, spend: int) -> AdDay:
    return AdDay(campaign, day, D(spend))


def _win(campaign: str, start: date, end: date, spend: int, item: str | None = None) -> AdWindow:
    return AdWindow(campaign, start, end, D(spend), item)


def test_connector_and_csv_for_the_same_campaign_day_the_connector_wins_and_nothing_adds_twice():
    daily = [_day("Chiến dịch A", OCT1, 100), _day("Chiến dịch A", OCT2, 100)]
    csv = [_win("chiến  dịch a", OCT1, OCT2, 999)]  # same campaign, normalised name
    result = resolve_ad_spend(daily, csv, OCT1, OCT2)
    assert result.total == D(200)
    assert (result.connector_total, result.csv_total) == (D(200), D(0))
    assert result.windows_skipped == 1


def test_csv_answers_the_days_the_connector_did_not_read():
    daily = [_day("A", OCT3, 100)]
    csv = [_win("A", OCT1, OCT3, 300)]  # three days, only Oct 1-2 are free
    result = resolve_ad_spend(daily, csv, OCT1, OCT3)
    assert result.connector_total == D(100)
    assert result.csv_total == D(200)  # 2 of 3 days of the window
    assert result.total == D(300) and result.prorated


def test_a_covered_day_with_no_row_for_a_campaign_means_it_spent_nothing():
    daily = [_day("B", OCT1, 50)]  # the day was read; campaign A has no row that day
    csv = [_win("A", OCT1, OCT1, 70)]
    result = resolve_ad_spend(daily, csv, OCT1, OCT1)
    assert (
        result.campaigns[campaign_key("A")].total == D(0)
        if campaign_key("A") in result.campaigns
        else True
    )
    assert result.total == D(50)


def test_overlapping_csv_windows_do_not_double_count_the_newer_window_wins_the_overlap():
    older = _win("A", OCT1, OCT3, 300)
    newer = _win("A", OCT2, OCT4, 600)
    result = resolve_ad_spend([], [older, newer], OCT1, OCT4)
    # newer answers Oct 2-4 (all 600); older only Oct 1 (1/3 of 300)
    assert result.total == D(700)
    assert result.prorated


def test_per_product_spend_comes_from_the_group_campaign_rows_and_the_rest_is_unattributed():
    csv = [
        _win("Nhóm", OCT1, OCT2, 600, item="1001"),
        _win("Nhóm", OCT1, OCT2, 400, item="1002"),
        _win("Nhóm", OCT1, OCT2, 100),  # campaign-level row, no product
    ]
    result = resolve_ad_spend([], csv, OCT1, OCT2)
    assert result.products == {"1001": D(600), "1002": D(400)}
    assert result.total == D(1100)
    assert result.unattributed == D(100)


def test_a_window_outside_the_range_is_set_aside():
    result = resolve_ad_spend([], [_win("A", OCT3, OCT4, 100)], OCT1, OCT2)
    assert result.total == D(0) and result.windows_skipped == 1


def test_ads_of_two_order_bases_are_never_mixed():
    daily = [AdDay("A", OCT1, D(1), order_basis="paid")]
    with pytest.raises(OrderBasisError):
        resolve_ad_spend(daily, [_win("A", OCT1, OCT1, 1)], OCT1, OCT1)


# -- D-2 -----------------------------------------------------------------------------------


def test_an_ads_figure_is_never_summed_into_a_confirmed_total():
    ads = Figure(D(500), BASIS_PLACED)
    shop = Figure(D(1000), BASIS_CONFIRMED)
    assert confirmed_total([shop, shop]) == D(2000)
    with pytest.raises(OrderBasisError):
        confirmed_total([shop, ads])


def test_resolved_ad_spend_carries_its_basis():
    assert resolve_ad_spend([], [_win("A", OCT1, OCT1, 1)], OCT1, OCT1).order_basis == BASIS_PLACED


# -- G-14 ----------------------------------------------------------------------------------


def _exp(ref: str, name: str, day: date = OCT1, value: int | None = None) -> VoucherExport:
    return VoucherExport(ref, name, day, None if value is None else D(value))


def _set(ref: str, name: str, day: date = OCT1, value: int | None = None) -> VoucherSetting:
    return VoucherSetting(ref, name, day, None if value is None else D(value))


def test_vouchers_join_by_normalised_name_and_start_date():
    join = join_vouchers([_exp("e1", "Voucher  Thu Đông")], [_set("s1", "voucher thu đông")])
    assert join.matched == (("e1", "s1"),)
    assert join.unmatched == 0 and join.ambiguous == 0


def test_a_different_start_date_does_not_join():
    join = join_vouchers([_exp("e1", "V")], [_set("s1", "V", OCT2)])
    assert join.matched == () and join.unmatched == 2


def test_the_discount_value_must_agree_when_both_sides_have_one():
    join = join_vouchers([_exp("e1", "V", value=10)], [_set("s1", "V", value=20)])
    assert join.matched == ()


def test_twin_vouchers_are_ambiguous_and_stay_unmatched_but_the_value_can_tell_them_apart():
    twins = join_vouchers([_exp("e1", "V")], [_set("s1", "V"), _set("s2", "V")])
    assert twins.matched == () and twins.ambiguous == 1
    assert set(twins.unmatched_settings) == {"s1", "s2"} and twins.unmatched_exports == ("e1",)
    by_value = join_vouchers(
        [_exp("e1", "V", value=10)], [_set("s1", "V", value=10), _set("s2", "V", value=20)]
    )
    assert by_value.matched == (("e1", "s1"),) and by_value.ambiguous == 0


def test_two_export_rows_for_one_setting_are_ambiguous():
    join = join_vouchers([_exp("e1", "V"), _exp("e2", "V")], [_set("s1", "V")])
    assert join.matched == () and join.ambiguous == 2
