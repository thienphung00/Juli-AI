"""Tự tạo UI bugs of 2026-11-15: the missing-cost note, unit price, combo packs."""

from __future__ import annotations

from types import SimpleNamespace

from juli_backend.services.shopee_builder import outcome

CARD = {"predicted": {"lift": {"metric": "ctr"}}, "floor": {"breaches": []}}
TR = SimpleNamespace(notes=[], warnings=[])
NO_PROFIT = {"p50": None}


def _types(result):
    return [w["type"] for w in outcome._warnings(CARD, TR, True, [], NO_PROFIT, result)]  # type: ignore[arg-type]


def test_a_not_estimable_option_does_not_claim_a_missing_cost():
    assert "profit_unknown" not in _types({"estimable": False})


def test_an_estimable_result_without_profit_still_warns():
    assert "profit_unknown" in _types({"estimable": True})


from decimal import Decimal as D  # noqa: E402

import pytest  # noqa: E402

from juli_backend.services.shopee_profit.pack import price_per_measure  # noqa: E402


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
    assert naming.unit_word("Mặc định", "Sản phẩm") == "hộp"


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

    cost = UnitCost(D(90_000), D(0), 3, "name", False, None)  # type: ignore[arg-type]
    var = VariationIn("v1", "Combo 3 chai", D(150_000), cost, "SKU1", 50, True, 5)
    prod = ProductIn("1", "Dầu gội 500ml", (var,))
    [opt] = gen.generate([prod], {"1": ["v1"]}, Packs(sizes=(3,)), Rules())
    assert (opt.units, opt.unit) == (9, "chai")
    assert opt.option_name.startswith("9 chai")
