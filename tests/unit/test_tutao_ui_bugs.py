"""Tự tạo UI bugs of 2026-11-15: the missing-cost note, unit price, combo packs."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.shopee_builder import outcome
from juli_backend.services.shopee_profit.pack import price_per_measure

CARD = {"predicted": {"lift": {"metric": "ctr"}}, "floor": {"breaches": []}}
TR = SimpleNamespace(notes=[], warnings=[])
NO_PROFIT = {"p50": None}


def _types(result):
    tr = cast(Any, TR)  # a stand-in Translation: only .notes / .warnings are read
    return [w["type"] for w in outcome._warnings(CARD, tr, True, [], NO_PROFIT, result)]


def test_a_not_estimable_option_does_not_claim_a_missing_cost():
    assert "profit_unknown" not in _types({"estimable": False})


def test_an_estimable_result_without_profit_still_warns():
    assert "profit_unknown" in _types({"estimable": True})


@pytest.mark.parametrize(
    ("price", "pack", "text", "want"),
    [
        (59_000, 1, "Dầu gội 500 ml", (11_800, "100 ml")),
        (59_000, 1, "500ml", (11_800, "100 ml")),
        (59_000, 1, "Nước 1 l", (5_900, "100 ml")),
        (59_000, 1, "Nước 1,5L", (59_000 * 100 / 1500, "100 ml")),
        (30_000, 1, "Bột 250g", (12_000, "100 g")),
        (30_000, 1, "Gạo 2kg", (1_500, "100 g")),
        (59_000, 2, "Combo 2 chai 500ml", (5_900, "100 ml")),
    ],
)
def test_price_per_measure_is_per_100_of_the_stated_content(price, pack, text, want):
    got = price_per_measure(D(price), pack, None, text)
    assert got is not None
    assert float(got[0]) == pytest.approx(want[0])
    assert got[1] == want[1]


@pytest.mark.parametrize("text", ["Hộp 12 cái", "Combo 3 hộp", "Size 30cm", None, "Màu L"])
def test_a_counted_unit_has_no_measure(text):
    assert price_per_measure(D(59_000), 1, text) is None


def test_unit_word_comes_from_the_products_own_names():
    from juli_backend.services.shopee_builder.combo_options import naming

    assert naming.unit_word("Combo 3 chai", "Dầu gội") == "chai"
    assert naming.unit_word("Mặc định", "Nước hoa 500ml chai thuỷ tinh") == "chai"
    assert naming.unit_word("Combo 5 túi") == "túi"
    # G6 (owner 2026-11-16): no unit word in the names -> "sản phẩm" (was "hộp")
    assert naming.unit_word("Mặc định", "Sản phẩm") == "sản phẩm"


def test_a_pack_variation_counts_its_real_items_in_combo_options():
    import importlib
    from decimal import Decimal as D

    gen = importlib.import_module("juli_backend.services.shopee_builder.combo_options.generate")
    from juli_backend.services.shopee_builder.combo_options.models import (
        Packs,
        ProductIn,
        Rules,
        VariationIn,
    )
    from juli_backend.services.shopee_recommendations.unit_cost import UnitCost

    cost = UnitCost(D(90_000), D(0), 3, cast(Any, "name"), False, None)
    var = VariationIn("v1", "Combo 3 chai", D(150_000), cost, "SKU1", 50, True, 5)
    prod = ProductIn("1", "Dầu gội 500ml", (var,))
    # G6 (owner 2026-11-16): never build packs of a variation already named "Combo N"
    assert gen.generate([prod], {"1": ["v1"]}, Packs(sizes=(3,)), Rules()) == []
    one = VariationIn("v2", "Chai 500ml", D(50_000), cost, "SKU2", 50, True, 5)
    [opt] = gen.generate(
        [ProductIn("1", "Dầu gội 500ml", (one,))], {"1": ["v2"]}, Packs(sizes=(3,)), Rules()
    )
    assert opt.unit == "chai" and opt.option_name.startswith(f"{opt.units} chai")
