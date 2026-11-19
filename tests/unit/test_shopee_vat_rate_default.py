"""Owner 2026-11-19: prices include VAT for every line, so a line whose SKU has no ``vat_rate``
takes the item's rate (when the item's rated variations agree) or the shop's ``vat_rate_default``,
instead of being left outside the margin.

Pure: hand-built raw lines and rule rows, no database.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from juli_backend.services.shop_rules.rules import RuleValidationError, validate_rule
from juli_backend.services.shopee_analytics.engine import item_vat_rates
from juli_backend.services.shopee_analytics.rules_view import RuleRow, read_rules
from tests.unit.test_shopee_income_engine import _profit, _raw

D = Decimal
FLAGS = [RuleRow("prices_include_vat", "", True), RuleRow("cost_includes_vat", "", True)]


def test_the_shop_default_is_read_shop_wide_only():
    rules = read_rules([RuleRow("vat_rate_default", "", 8)])
    assert rules.vat_rate_default == D("0.08")
    scoped = read_rules([RuleRow("vat_rate_default", "G1", 8)])
    assert scoped.vat_rate_default is None


def test_the_default_is_validated_like_a_sku_rate_and_takes_no_scope():
    assert validate_rule("vat_rate_default", "", 8) == ("", 8)
    with pytest.raises(RuleValidationError, match="shop-wide"):
        validate_rule("vat_rate_default", "G1", 8)
    with pytest.raises(RuleValidationError, match="must be one of"):
        validate_rule("vat_rate_default", "", 7)


def test_an_item_rate_needs_its_rated_variations_to_agree():
    rates = {
        "100:1": D("0.1"),
        "100:2": D("0.1"),
        "200:1": D("0.08"),
        "200:2": D("0.1"),
        "G1": D("0.05"),  # a seller SKU, not an item:variation scope
    }
    assert item_vat_rates(rates) == {"100": D("0.1")}


def test_a_line_without_a_sku_rate_takes_the_shop_default():
    lines, _, pairs = _profit([_raw(1)], [*FLAGS, RuleRow("vat_rate_default", "", 8)])
    assert lines[0].vat is not None and lines[0].vat.rate == D("0.08")
    (_, pb) = pairs[0]
    assert pb.vat_output == D(6_667)  # 90000 / 1.08 -> 6667 of output VAT taken out


def test_without_a_default_the_line_still_has_no_rate():
    lines, _, _ = _profit([_raw(1)], FLAGS)
    assert lines[0].vat is not None and lines[0].vat.rate is None


def test_a_sku_rate_wins_over_the_default():
    lines, _, _ = _profit(
        [_raw(1)], [*FLAGS, RuleRow("vat_rate", "G1", 10), RuleRow("vat_rate_default", "", 8)]
    )
    assert lines[0].vat is not None and lines[0].vat.rate == D("0.1")


def test_a_line_with_no_variation_takes_its_items_rate_before_the_default():
    raw = _raw(1, item_id="11", sku=None)
    lines, _, _ = _profit(
        [raw], [*FLAGS, RuleRow("vat_rate", "11:5010", 10), RuleRow("vat_rate_default", "", 8)]
    )
    assert lines[0].product_id == "11"
    assert lines[0].vat is not None and lines[0].vat.rate == D("0.1")
