"""P98 S7: combo options core -- synthetic products only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from juli_backend.services.shopee_builder.combo_options import (
    BundleSpec,
    ComboInputError,
    ComboOption,
    Economics,
    Packs,
    PriceRule,
    PriceRuleError,
    ProductIn,
    Rules,
    VariationIn,
    config,
    count,
    generate,
    limit_warnings,
    price,
    reprice,
    round_price,
)
from juli_backend.services.shopee_builder.specs import MAX_TITLE_CHARS
from juli_backend.services.shopee_profit.fees import FeeSchedule, shopee_vn_non_mall
from juli_backend.services.shopee_profit.vat import VatTreatment
from juli_backend.services.shopee_recommendations.unit_cost import UnitCost

D = Decimal
VAT = VatTreatment(prices_include_vat=False, cost_includes_vat=False)
ECO = Economics(FeeSchedule((shopee_vn_non_mall(D("0.05"), date(2026, 1, 1)),)), date(2026, 10, 1))


def cost(cogs: int | None, pack: int = 1) -> UnitCost:
    return UnitCost(
        cogs=None if cogs is None else D(cogs),
        packaging=D(1000),
        pack_count=pack,
        pack_source="set",
        bom=False,
        vat=VAT,
    )


def var(
    vid: str,
    name: str,
    px: int,
    cogs: int | None = 50_000,
    *,
    sold_30d: bool = True,
    stock: int | None = 100,
) -> VariationIn:
    return VariationIn(vid, name, D(px), cost(cogs), sku=f"S{vid}", stock=stock, sold_30d=sold_30d)


GLOVE = ProductIn(
    "100",
    "Găng",
    (
        var("a", "Size S", 100_000),
        var("b", "Size M", 100_000),
        var("c", "Size L", 110_000, sold_30d=False),
    ),
    code="gang",
)
BAG = ProductIn("200", "Túi Bio", (var("x", "Mặc định", 40_000, 15_000),), code="tui")
ALL = {"100": ["a", "b", "c"], "200": ["x"]}


def test_count_before_building_same_variation_sold_only() -> None:
    c = count([GLOVE], {"100": ["a", "b", "c"]}, Packs((3, 5, 10)), Rules())
    assert c.total == 6 and c.kept == 6 and c.over_cap == 0  # c unsold: 2 variations x 3 sizes
    assert len(generate([GLOVE], {"100": ["a", "b", "c"]}, Packs((3, 5, 10)), Rules())) == 6


def test_sold_only_off_includes_unsold() -> None:
    r = Rules(sold_only=False)
    assert count([GLOVE], ALL, Packs((3,)), r).total == 3


def test_mixed_variations_explode_and_cap() -> None:
    r = Rules(same_variation=False, sold_only=False, max_options=5)
    c = count([GLOVE], ALL, Packs((3,)), r)
    assert c.total == 10  # C(3+3-1, 3)
    assert c.kept == 5 and c.over_cap == 5
    opts = generate([GLOVE], ALL, Packs((3,)), r)
    assert len(opts) == 5
    assert all(o.units == 3 for o in opts)
    assert len({o.key for o in opts}) == 5


def test_generate_matches_count_when_uncapped() -> None:
    r = Rules(same_variation=False, sold_only=True, max_options=1000)
    packs = Packs((2, 3), (BundleSpec((("100", 3), ("200", 1))),))
    c = count([GLOVE, BAG], ALL, packs, r)
    assert c.total == len(generate([GLOVE, BAG], ALL, packs, r)) == 3 + 4 + 1 + 1 + 2


def test_bundle_cross_product() -> None:
    packs = Packs((), (BundleSpec((("100", 3), ("200", 1))),))
    opts = generate([GLOVE, BAG], ALL, packs, Rules(sold_only=False))
    assert len(opts) == 3 * 1
    assert all(o.form == "bundle" for o in opts)
    assert opts[0].name == "Găng Size S ×3 + Túi Bio ×1"
    assert opts[0].units == 4


def test_cap_applies_and_pack_validation() -> None:
    r = Rules(max_options=2)
    assert len(generate([GLOVE], ALL, Packs((3, 5, 10)), r)) == 2
    with pytest.raises(ComboInputError):
        generate([GLOVE], ALL, Packs((1,)), Rules())
    with pytest.raises(ComboInputError):
        count([GLOVE], ALL, Packs((), (BundleSpec((("100", 1),)),)), Rules())


def test_unpicked_product_is_skipped() -> None:
    assert count([GLOVE, BAG], {"100": ["a"]}, Packs((3,)), Rules()).total == 1


def test_names_skus_lengths() -> None:
    opts = generate([GLOVE], ALL, Packs((3,)), Rules(shop_code="Cửa Hàng"))
    assert opts[0].name == "3 hộp – Size S"
    assert opts[0].sku == "CUAHANG-GANG-SA-x3"
    long_p = ProductIn(
        "1", "Tên sản phẩm rất rất dài " * 6, (var("v", "Phân loại rất dài " * 5, 1000),)
    )
    other = ProductIn("2", "Khác " * 30, (var("w", "Màu " * 30, 1000),))
    packs = Packs((), (BundleSpec((("1", 3), ("2", 2))),))
    (o,) = generate([long_p, other], {"1": ["v"], "2": ["w"]}, packs, Rules())
    assert len(o.name) <= MAX_TITLE_CHARS
    assert len(o.option_name) <= config.SHOPEE_MAX_OPTION_NAME_CHARS
    assert len(o.sku) <= config.SHOPEE_MAX_SKU_CHARS
    again = generate([long_p, other], {"1": ["v"], "2": ["w"]}, packs, Rules())[0]
    assert again.sku == o.sku  # deterministic


def test_option_names_stay_unique_after_cut() -> None:
    vs = tuple(var(f"v{i}", "Phân loại giống nhau dài " + str(i), 1000) for i in range(3))
    p = ProductIn("9", "P", vs)
    opts = generate([p], {"9": [v.variation_id for v in vs]}, Packs((3,)), Rules())
    assert len({o.option_name for o in opts}) == 3
    assert len({o.sku for o in opts}) == 3


def test_suggested_stock_min_of_floor() -> None:
    g = ProductIn("1", "G", (var("a", "L", 1000, stock=29),))
    b = ProductIn("2", "B", (var("x", "M", 1000, stock=7),))
    (o,) = generate(
        [g, b], {"1": ["a"], "2": ["x"]}, Packs((), (BundleSpec((("1", 3), ("2", 2))),)), Rules()
    )
    assert o.suggested_stock == min(29 // 3, 7 // 2) == 3
    assert o.stock_note == "không tự đồng bộ"
    unknown = ProductIn("3", "U", (VariationIn("u", "U", D(1000), stock=None, sold_30d=True),))
    (o2,) = generate([unknown], {"3": ["u"]}, Packs((3,)), Rules())
    assert o2.suggested_stock is None


def test_limit_warnings_only_warn() -> None:
    vs = tuple(var(f"v{i}", f"V{i}", 1000) for i in range(config.SHOPEE_MAX_TOTAL_VARIATIONS))
    p = ProductIn("9", "P", vs)
    opts = generate([p], {"9": [v.variation_id for v in vs]}, Packs((3, 5)), Rules(max_options=500))
    assert len(opts) > config.SHOPEE_MAX_TOTAL_VARIATIONS
    assert limit_warnings(opts)
    assert not limit_warnings(opts[:5])


# ---- pricing ---------------------------------------------------------------------------------


def opts_s() -> list[ComboOption]:
    return generate([GLOVE], {"100": ["a"]}, Packs((2, 3, 5, 10)), Rules())


def test_round_price() -> None:
    assert round_price(D("123456")) == 123_000
    assert round_price(D("123500")) == 124_000
    assert round_price(D("200")) == 1000
    assert round_price(D("123456"), ending_9=True) == 119_000
    assert round_price(D("126000"), ending_9=True) == 129_000
    assert round_price(D("123001"), up=True) == 124_000
    assert round_price(D("120100"), ending_9=True, up=True) == 129_000


def test_ladder_default_and_saving() -> None:
    rows = {r.option.units: r for r in price(opts_s(), PriceRule(), ECO)}
    assert rows[2].price == 200_000 and rows[2].saving == 0  # below the first tier
    assert rows[3].price == 285_000 and rows[3].saving == 15_000
    assert rows[3].saving_pct == D("5.0")
    assert rows[5].price == 460_000  # 500k - 8 %
    assert rows[10].price == 880_000
    assert rows[10].price_per_box == 88_000
    assert rows[3].separate_total == 300_000


def test_ladder_ending_9() -> None:
    rows = {r.option.units: r for r in price(opts_s(), PriceRule(ending_9=True), ECO)}
    assert rows[3].price == 289_000  # 285.000 -> nearest k*10.000-1.000
    assert rows[10].price == 879_000


def test_per_box_rule() -> None:
    rows = price(opts_s(), PriceRule(kind="per_box", box_price=D(90_000)), ECO)
    assert [r.price for r in rows] == [180_000, 270_000, 450_000, 900_000]
    with pytest.raises(PriceRuleError):
        price(opts_s(), PriceRule(kind="per_box"), ECO)


def test_target_margin_hits_target_and_rounds_up() -> None:
    rule = PriceRule(kind="target_margin", target_margin_pct=D(25))
    rows = price(opts_s(), rule, ECO)
    for r in rows:
        assert r.price is not None and r.price % 1000 == 0
        assert r.margin_pct is not None and r.margin_pct >= D("25.0")
        assert r.margin_pct < D("26.0")  # not more than one 1.000d step above
    assert rows[0].price is not None and rows[-1].price is not None
    assert rows[0].price < rows[-1].price
    with pytest.raises(PriceRuleError):
        price(opts_s(), PriceRule(kind="target_margin"), ECO)


def test_margin_and_profit_use_cost_and_fees() -> None:
    (row,) = [r for r in price(opts_s(), PriceRule(), ECO) if r.option.units == 3]
    assert row.price == 285_000
    # revenue 285.000; fees 5 % + 6 % + 3.000; cogs 150.000; packaging 1.000
    expected = D(285_000) - D(285_000) * D("0.11") - 3000 - 150_000 - 1000
    assert row.profit_per_order == expected.quantize(D(1))
    assert row.margin_pct == (expected / 285_000 * 100).quantize(D("0.1"))
    assert row.margin_label is None


def test_chua_tinh_without_cost_never_a_fallback() -> None:
    nocost = ProductIn("5", "N", (var("n", "N", 100_000, cogs=None),))
    packs = Packs((3,), (BundleSpec((("5", 1), ("200", 1))),))
    opts = generate([nocost, BAG], {"5": ["n"], "200": ["x"]}, packs, Rules())
    assert len(opts) == 3
    own = [o for o in opts if o.form == "bundle" or o.members[0].item_id == "5"]
    assert len(own) == 2
    bag_only = price([o for o in opts if o not in own], PriceRule(), ECO)
    assert bag_only[0].margin_pct is not None  # a combo of costed members is counted
    opts = own
    rows = price(opts, PriceRule(), ECO, floor=D(10))
    assert all(r.margin_pct is None and r.profit_per_order is None for r in rows)
    assert all(r.margin_label == "chưa tính" and r.below_floor is None for r in rows)
    assert all(r.price is not None for r in rows)  # the ladder price still shows
    tm = price(opts, PriceRule(kind="target_margin", target_margin_pct=D(20)), ECO)
    assert all(r.price is None and r.notes for r in tm)


def test_floor_flag_warns_never_blocks() -> None:
    rows = {r.option.units: r for r in price(opts_s(), PriceRule(), ECO, floor=D(40))}
    assert rows[3].below_floor is True and rows[3].price is not None
    rows = {r.option.units: r for r in price(opts_s(), PriceRule(), ECO, floor=D(1))}
    assert rows[3].below_floor is False


def test_manual_override_recalculates_row() -> None:
    base = {r.option.units: r for r in price(opts_s(), PriceRule(), ECO, floor=D(10))}[3]
    new = reprice(base, 250_000, ECO, floor=D(10))
    assert new.overridden and new.price == 250_000
    assert new.saving == 50_000 and new.saving_pct == D("16.7")
    assert new.price_per_box == 83_333
    assert new.margin_pct is not None and base.margin_pct is not None
    assert new.margin_pct < base.margin_pct
    out = price(opts_s(), PriceRule(), ECO, overrides={base.option.key: 250_000})
    assert [r.overridden for r in out].count(True) == 1
    assert next(r for r in out if r.overridden).price == 250_000
