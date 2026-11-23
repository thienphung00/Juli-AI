"""E80: the ads top-up taken from order revenue is ads spend, never a platform fee, and is never
counted twice. Synthetic days and amounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_profit import income as inc
from juli_backend.services.shopee_profit.ads_days import (
    SOURCE_DAILY_REPORT,
    SOURCE_INCOME_TOPUP,
    DayAds,
    add_income_topup,
)

D1, D2, D3 = date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)


def _day(spend: str) -> DayAds:
    return DayAds(Decimal(spend), Decimal(0), Decimal(0), SOURCE_DAILY_REPORT, {})


def test_a_topup_never_adds_to_a_day_that_has_an_ads_figure():
    days = {D1: _day("500000"), D3: _day("50000")}
    out = add_income_topup(days, {D1: Decimal("300000"), D3: Decimal("100000")})
    assert out[D1].spend == Decimal("500000")
    assert out[D3].spend == Decimal("50000")  # ads 50k + top-up 100k is not 150k


def test_a_day_with_no_ads_figure_takes_the_topup_as_its_spend():
    out = add_income_topup({}, {D2: Decimal("70000")})
    assert out[D2].spend == Decimal("70000") and out[D2].source == SOURCE_INCOME_TOPUP


def test_other_days_and_zero_topups_are_untouched():
    days = {D1: _day("10"), D3: _day("20")}
    out = add_income_topup(days, {D2: Decimal(0)})
    assert out == days


def test_the_topup_is_not_a_platform_fee():
    order = inc.IncomeOrder(
        order_ref="x", fee_fixed=Decimal(1000), fee_nttd=Decimal(3000), fee_service=Decimal(500)
    )
    assert order.fees_total == Decimal(1500)
    assert inc.FEE_NTTD not in inc.FEE_CODES
    line = inc.split_income(order, [Decimal(1)])[0]
    assert line.fees_total == Decimal(1500)
