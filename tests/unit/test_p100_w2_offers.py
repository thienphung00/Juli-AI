"""P100 S1 wave 2 "offers": Chương Trình Của Shop and Deal Sốc (Mua Kèm Deal Sốc / Mua Để
Nhận Quà) in Shopee's fields, the discount as a cost inside the ``OptionResult`` (B.14, A.9,
B.4). Synthetic numbers only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import Band, FunnelBase, SourceFunnel
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.facts import LiftEvidence, PriceFacts
from juli_backend.services.shopee_builder.engine_families.families import price_option
from juli_backend.services.shopee_builder.service import version_dates
from juli_backend.services.shopee_profit.order_profit import OrderLine


def b(a, m, c):
    return Band(D(str(a)), D(str(m)), D(str(c)))


def base():
    return FunnelBase(
        "shop-1",
        "products",
        ("i1",),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            SourceFunnel(
                "the_san_pham_khac", D(100000), D(5000), D(200), D(20_000_000), D(4_000_000)
            ),
            SourceFunnel("trang_shop", D(20000), D(1000), D(50), D(5_000_000), D(1_000_000)),
        ),
        D("0.3"),
    )


# -- Chương Trình Của Shop ------


def discount(**kw):
    return sp.ProductDiscountSpec(
        kind="product_discount", item_id="i1", variations=[sp.VariationPrice(discount_pct=10)], **kw
    )


def test_programme_carries_name_hours_promo_qty_and_order_limit():
    spec = discount(
        name="Sale 12.12",
        start=date(2026, 12, 12),
        start_hour=0,
        end=date(2026, 12, 14),
        end_hour=23,
        promo_qty=200,
        per_buyer_limit=2,
    )
    assert spec.days == 3  # 71 hours -> 3 days
    assert spec.promo_qty == 200
    assert discount(start=date(2026, 12, 1), end=date(2026, 12, 10)).days == 10


def test_programme_is_at_least_one_hour_and_has_ordered_ends():
    day = date(2026, 12, 1)
    with pytest.raises(ValidationError):
        discount(start=day, start_hour=8, end=day, end_hour=8)
    with pytest.raises(ValidationError):
        discount(start=date(2026, 12, 2), end=day)
    with pytest.raises(ValidationError):
        discount(start_hour=8)  # an hour needs its date
    with pytest.raises(ValidationError):
        discount(promo_qty=0)


def test_programme_runs_at_most_180_days_but_an_older_card_still_loads():
    with pytest.raises(ValidationError):
        discount(name="Dài", start=date(2026, 1, 1), end=date(2026, 7, 1))  # 182 days
    discount(name="Vừa", start=date(2026, 1, 1), end=date(2026, 6, 29))  # 180 days
    # saved before the Shopee fields (no name, no hours): the 180-day rule does not apply
    assert discount(start=date(2026, 1, 1), end=date(2026, 12, 31)).days == 365


def test_the_card_names_the_hours_of_the_window():
    spec = discount(start=date(2026, 12, 12), start_hour=9, end=date(2026, 12, 14), end_hour=21)
    d = version_dates(spec, None)
    assert d["label"] == "12/12 09:00 – 14/12 21:00 (3 ngày)"
    assert d["days"] == 3


def price_facts(**kw):
    d = dict(
        aov_now=D(100_000),
        profit_per_order=D(20_000),
        profit_per_order_after=D(12_000),
        price_factor=D("0.9"),
        contribution_rate=D("0.3"),
        ctor=LiftEvidence(b(0.02, 0.06, 0.1), "product_history"),
    )
    d.update(kw)
    return PriceFacts(**d)


def test_programme_discount_is_a_cost_inside_the_result_with_roi_and_break_even():
    o = price_option(discount(), price_facts(discount_per_order=D(8_000)))
    assert o.label == "Chương Trình Của Shop"
    assert len(o.offers) == 1
    offer = o.offers[0]
    assert offer.per_use == D(8_000) and offer.use_share.p50 == D(1)
    assert o.profit_per_order_after == D(20_000)  # the cost leaves the per-order profit: once
    r = run(base(), o, seed=3, n=400)
    assert r.cost_total > 0
    assert r.break_even_orders is not None
    j = r.json()
    assert j["cost"]["total"] > 0
    assert j["roi"]["value"] is not None
    assert "giảm giá chương trình" in " ".join(p["text"] for p in j["build_up"])


def test_moving_the_discount_into_the_cost_does_not_change_the_profit():
    without = price_option(discount(), price_facts())
    assert without.offers == ()
    with_cost = price_option(discount(), price_facts(discount_per_order=D(8_000)))
    a = run(base(), without, seed=5, n=400)
    c = run(base(), with_cost, seed=5, n=400)
    assert a.likely is not None and c.likely is not None
    assert float(c.likely.profit) == pytest.approx(float(a.likely.profit), rel=0.01)
    assert float(c.likely.gmv) == pytest.approx(float(a.likely.gmv), rel=0.01)


def test_programme_name_is_the_label_and_a_price_change_has_no_such_cost():
    named = price_option(discount(name="Sale 12.12"), price_facts())
    assert named.label == "Sale 12.12"
    price = sp.PriceSpec(kind="price", item_id="i1", variations=[sp.VariationPrice(change_pct=-10)])
    assert price_option(price, price_facts(discount_per_order=D(8_000))).offers == ()


def evaluation(rows):
    return SimpleNamespace(certain={"skus": rows})


def test_discount_per_order_is_the_profit_lost_net_of_fees_else_the_gross_discount():
    row = {
        "orders": 10,
        "price_before": 100_000,
        "price_after": 90_000,
        "profit_per_order_before": 20_000,
        "profit_per_order_after": 13_000,
    }
    lift = LiftEvidence(b(0, 0, 0), "prior")
    f = adapters.price_facts_from_evaluation(
        evaluation([row]), aov_now=D(100_000), contribution_rate=None, ctor=lift
    )
    assert f.discount_per_order == D(7_000)
    unknown = {**row, "profit_per_order_before": None, "profit_per_order_after": None}
    g = adapters.price_facts_from_evaluation(
        evaluation([unknown]), aov_now=D(100_000), contribution_rate=None, ctor=lift
    )
    assert g.discount_per_order == D(10_000)  # 100.000 × (1 − 0,9)


# -- Deal Sốc ------


def test_an_older_add_on_and_gift_card_still_loads():
    add_on = sp.AddOnSpec.model_validate(
        {"kind": "add_on", "main_item_id": "i1", "addons": [{"item_id": "j", "pct": 15}]}
    )
    assert add_on.name is None and add_on.days is None and add_on.addon_limit is None
    gift = sp.GiftSpec.model_validate(
        {
            "kind": "gift",
            "gift": {"unit_cost": 5000, "qty": 2},
            "trigger": {"type": "buy_item", "item_id": "i1"},
        }
    )
    assert gift.name is None and gift.days is None


def test_mua_kem_deal_soc_fields_and_limits():
    spec = sp.AddOnSpec(
        kind="add_on",
        name="Mua kèm tháng 12",
        main_item_id="i1",
        addons=[sp.AddOn(item_id="j", price=20_000)],
        addon_limit=100,
        start=date(2026, 12, 1),
        start_hour=9,
        end=date(2026, 12, 3),
        end_hour=21,
    )
    assert spec.days == 3
    with pytest.raises(ValidationError):
        sp.AddOnSpec(
            kind="add_on",
            main_item_id="i1",
            addons=[sp.AddOn(item_id="j", pct=10)],
            addon_limit=101,
        )
    day = date(2026, 12, 1)
    with pytest.raises(ValidationError):  # at least one hour
        sp.AddOnSpec(
            kind="add_on",
            main_item_id="i1",
            addons=[sp.AddOn(item_id="j", pct=10)],
            start=day,
            start_hour=9,
            end=day,
            end_hour=9,
        )


def test_mua_de_nhan_qua_takes_up_to_49_gifts():
    def gift(qty, **kw):
        return sp.GiftSpec(
            kind="gift",
            gift=sp.GiftItem(unit_cost=5000, qty=qty),
            trigger=sp.GiftTrigger(type="min_spend", amount=200_000),
            **kw,
        )

    assert gift(49, name="Quà").gift.qty == 49
    with pytest.raises(ValidationError):
        gift(50)
    with pytest.raises(ValidationError):
        gift(1, start=date(2026, 12, 2), end=date(2026, 12, 1))


# -- gift minimum spend: after the combo discount (B.11) ------


def basket(order, price, bundle=0):
    return OrderLine(
        order, "i1-sku", "i1", date(2026, 10, 5), 1, D(price), D(price), bundle_discount=D(bundle)
    )


def test_a_gift_minimum_is_met_after_the_combo_discount():
    lines = [basket("o1", 210_000, 20_000), basket("o2", 210_000), basket("o3", 150_000)]
    env = SimpleNamespace(lines_for=lambda items: lines)
    # 190.000 / 210.000 / 150.000 after the combo: only the second reaches 200.000
    assert adapters.qualifying_share(env, D(200_000)) == D(1) / D(3)
    assert adapters.qualifying_share(env, D(190_000)) == D(2) / D(3)
