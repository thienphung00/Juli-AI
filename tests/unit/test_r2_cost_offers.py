"""#78 / #87: ``result.cost.offers`` -- per offer {label, expected_uses, per_use, total} from the
same computation as ``cost.total`` (the middle column's offer uses), in the wire and in the stored
core. Invented figures only."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_builder.engine.contract import (
    DriverEffect,
    OfferCost,
    OptionInput,
)
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_recommendations import result_store
from tests.unit.test_funnel_engine import band, simple_base, voucher_option


def two_offers(fixed: int = 0) -> OptionInput:
    return OptionInput(
        "combo",
        "Combo + voucher",
        (DriverEffect("ctor", ("the_san_pham_khac",), "prior", lift=band(0, 0.05, 0.1)),),
        14,
        offers=(
            OfferCost(D(5000), band(0.1, 0.2, 0.3), None, "voucher"),
            OfferCost(D(12000), band(0.1, 0.1, 0.1), D(3), "giảm giá combo"),
        ),
        fixed_cost=D(fixed),
    )


def test_offers_add_up_to_the_cost_exactly():
    for opt in (voucher_option(), two_offers(), two_offers(fixed=300_000)):
        r = run(simple_base(), opt, seed=2, n=400)
        assert len(r.offers) == len(opt.offers)
        assert sum((o.total for o in r.offers), D(0)) + opt.fixed_cost == r.cost_total
        for o, src in zip(r.offers, opt.offers, strict=True):
            assert o.label == src.label and o.per_use == src.per_use
            assert o.total == o.expected_uses * o.per_use
        j = r.json()["cost"]
        assert [o["label"] for o in j["offers"]] == [o.label for o in opt.offers]
        assert sum(o["total"] for o in j["offers"]) + j["fixed"] == pytest.approx(
            j["total"], abs=1e-6
        )


def test_a_use_cap_caps_the_expected_uses():
    r = run(simple_base(), two_offers(), seed=2, n=400)
    assert r.offers[1].expected_uses == 3  # the combo's 3-use cap binds
    assert r.offers[1].total == 3 * 12000


def test_not_estimable_still_lists_its_offers():
    opt = OptionInput(
        "voucher",
        "v",
        (DriverEffect("ctor", ("trang_shop",), "not_estimable"),),
        30,
        offers=(OfferCost(D(1000), band(0.2, 0.2, 0.2), None, "voucher"),),
    )
    r = run(simple_base(), opt, n=10)
    assert not r.estimable
    assert r.offers[0].expected_uses == pytest.approx(D(250) * D("0.2"))
    assert r.offers[0].total == r.cost_total


def test_the_stored_core_carries_the_offers():
    r = run(simple_base(), two_offers(fixed=1000), seed=5, n=200)
    back = result_store.option_of(result_store.core_of(r))
    assert back.offers == r.offers
    assert back.json()["cost"]["offers"] == r.json()["cost"]["offers"]


def test_the_builder_voucher_numbers_come_from_the_result_offers():
    from juli_backend.services.shopee_builder.outcome import (
        voucher_cost_from_result,
        voucher_detail_from_result,
    )

    r = run(simple_base(), voucher_option(), seed=4, n=300).json()
    offer = r["cost"]["offers"][0]
    money_layer = {"amount": 123, "period_days": 14, "label": "Voucher ở mức dùng dự kiến"}
    cost = voucher_cost_from_result("min_spend_voucher", money_layer, r)
    assert cost["amount"] == offer["total"] == r["cost"]["total"]
    assert cost["expected_units"] == offer["expected_uses"] and cost["source"] == "result"
    detail = {"usage": {"used": 1, "limit": 10, "capped": False}, "cost_per_used_order": 1}
    d = voucher_detail_from_result(detail, r)
    assert d["usage"]["used"] == offer["expected_uses"]
    assert d["usage"]["capped"] is (offer["expected_uses"] >= 10)
    assert d["cost_per_used_order"] == offer["per_use"] and d["cost"] == offer["total"]
    # another kind, or a stored result without offers, keeps its own line
    assert voucher_cost_from_result("combo_multi", money_layer, r) == money_layer
    old = {**r, "cost": {k: v for k, v in r["cost"].items() if k != "offers"}}
    assert voucher_cost_from_result("min_spend_voucher", money_layer, old) == money_layer
