"""ADR-122 d.12: the product page and the builder compute Biên cuối with ONE math."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D

from juli_backend.services.shopee_analytics import margins, product
from juli_backend.services.shopee_builder import variations


@dataclass
class _Line:
    sku: str


@dataclass
class _Breakdown:
    revenue: D
    voucher: D
    commission: D | None
    excluded_reason: str | None = None


def test_both_screens_use_the_shared_margin_functions():
    assert product.measured_rates is margins.measured_rates
    assert product.final_margin is margins.final_margin
    assert variations.measured_rates is margins.measured_rates
    assert variations.final_margin is margins.final_margin
    assert variations.Rates is margins.Rates


def test_measured_rates_allocate_ads_by_revenue_and_skip_excluded_lines():
    pairs = [
        (_Line("A×3"), _Breakdown(D(100_000), D(5_000), D(2_000))),
        (_Line("A×5"), _Breakdown(D(300_000), D(0), None)),
        (_Line("A×5"), _Breakdown(D(999_999), D(9), D(9), excluded_reason="qua_tang")),
    ]
    whole, by_sku = margins.measured_rates(pairs, D(40_000))
    assert whole is not None
    assert whole.ads == D("0.1")  # 40.000 ÷ 400.000, the same on every SKU
    assert by_sku["A×3"].ads == by_sku["A×5"].ads == D("0.1")
    assert by_sku["A×3"].voucher == D("0.05") and by_sku["A×3"].commission == D("0.02")
    assert by_sku["A×5"].voucher == D(0) and by_sku["A×5"].commission == D(0)
    # Biên cuối = Biên ở giá bán − (voucher + commission + ads), in percent points
    assert margins.final_margin(36.4, by_sku["A×3"]) == 19.4


def test_no_history_or_no_price_margin_is_none():
    assert margins.measured_rates([], D(1)) == (None, {})
    assert margins.final_margin(None, margins.Rates()) is None
    assert margins.final_margin(30.0, None) is None
