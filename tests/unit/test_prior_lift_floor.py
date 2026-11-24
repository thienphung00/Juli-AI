"""Owner rule 2026-11-15: a generic-prior uplift is at least 5 % (card engine and builder)."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

from juli_backend.services.shopee_builder.engine.contract import Band, DriverEffect, OptionInput
from juli_backend.services.shopee_builder.engine_families import adapters, common
from juli_backend.services.shopee_recommendations.kinds import (
    FLOOR_EXEMPT,
    KINDS,
    MIN_PRIOR_LIFT,
    REFERENCE_SIZE,
    floor_prior_band,
)
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.prediction import _floor_generic, predict_lift


def _cand(kind: str) -> Candidate:
    return Candidate(kind=kind, items=("i1",), gap_pct=5.0)  # small gap: prior x 0.4


def _env(calibration=None, response=None):
    return SimpleNamespace(
        calibration=calibration or {}, sim=None, response_by_item={}, response_shop=response
    )


def test_helper_floors_p50_raises_p90_and_keeps_p10():
    p10, p50, p90 = floor_prior_band("gift", D("0.004"), D("0.014"), D("0.024"))
    assert (p10, p50, p90) == (D("0.004"), MIN_PRIOR_LIFT, D("0.05"))


def test_helper_keeps_a_band_already_above_the_floor_and_a_non_positive_prior():
    assert floor_prior_band("gift", D("0.02"), D("0.08"), D("0.2")) == (
        D("0.02"),
        D("0.08"),
        D("0.2"),
    )
    assert floor_prior_band("gift", D("-0.03"), D("-0.01"), D(0)) == (D("-0.03"), D("-0.01"), D(0))


def test_a_prior_kind_under_five_percent_is_floored_on_the_card():
    lift = predict_lift(KINDS["price_display"], _cand("price_display"), _env(), None)
    assert lift.source == "prior" and lift.floored
    assert round(lift.at("p50"), 6) == 0.05
    assert lift.at("p90") >= lift.at("p50") >= lift.at("p10")
    assert lift.at("p10") == 0.01 * 0.4  # P10 unchanged


def test_a_calibrated_lift_is_not_floored():
    state = SimpleNamespace(pooled_ratio=0.5, n_results=20, range_scale=1.0)
    env = _env({("price_display", "ctr"): state})
    lift = predict_lift(KINDS["price_display"], _cand("price_display"), env, None)
    assert lift.source == "shop" and not lift.floored
    assert lift.at("p50") < 0.05


def test_the_shops_own_price_response_is_not_floored():
    own = SimpleNamespace(per_pct_low=0.001, per_pct_high=0.003, source="product_history")
    lift = predict_lift(KINDS["price"], _cand("price"), _env(response=own), 10.0)
    assert lift.source == "product_history" and not lift.floored
    assert round(lift.at("p50"), 6) == 0.02


def test_a_one_percent_cut_floors_to_a_tenth_of_five_percent():
    # F7 2026-11-16: sized kind, floor = 5 % x size / reference (10 %): 1 % -> 0.5 %
    for kind in ("price", "product_discount", "flash_sale", "program_registration"):
        assert REFERENCE_SIZE[kind] == 10.0
    assert REFERENCE_SIZE["ads_budget"] == 20.0
    band = (D("0.001"), D("0.002"), D("0.004"))
    _, p50, p90 = floor_prior_band("price", *band, size=1.0)
    assert p50 == D("0.005") and p90 >= p50


def test_a_cut_at_or_above_the_reference_floors_to_five_percent():
    for size in (10.0, 20.0):
        _, p50, _ = floor_prior_band("price", D("0.001"), D("0.002"), D("0.004"), size=size)
        assert p50 == MIN_PRIOR_LIFT


def test_a_sized_kind_without_a_size_gets_no_floor():
    band = (D("0.001"), D("0.002"), D("0.004"))
    assert floor_prior_band("price", *band) == band
    assert floor_prior_band("price", *band, size=0.0) == band
    assert floor_prior_band("ads_budget", *band, size=-10.0) == band


def test_the_generic_price_response_follows_the_size_on_the_card():
    # the generic 0.5-2 % per 1 % prior already sits on the sized floor, so it is not moved
    one = predict_lift(KINDS["price"], _cand("price"), _env(), 1.0)
    assert round(one.at("p50"), 6) == 0.0125 and not one.floored
    four = predict_lift(KINDS["price"], _cand("price"), _env(), 4.0)
    assert round(four.at("p50"), 6) == 0.05
    none = predict_lift(KINDS["price"], _cand("price"), _env(), None)
    assert none.at("p50") == 0 and not none.floored


def test_an_unsized_kind_keeps_the_flat_floor():
    assert "gift" not in REFERENCE_SIZE
    _, p50, _ = floor_prior_band("gift", D("0.001"), D("0.002"), D("0.004"), size=1.0)
    assert p50 == MIN_PRIOR_LIFT


def test_a_lowered_and_a_raised_roas_target_both_come_back_unchanged():
    # the prior is on ROAS, not volume: ads_roas_target is exempt whatever the direction
    assert "ads_roas_target" in FLOOR_EXEMPT and "ads_roas_target" not in REFERENCE_SIZE
    assert _floor_generic("ads_roas_target", -0.004, -0.001, -5.0) == (-0.004, -0.001, False)
    assert _floor_generic("ads_roas_target", 0.001, 0.004, 5.0) == (0.001, 0.004, False)


def test_the_ads_budget_floor_scales_with_the_step():
    _, half, _ = floor_prior_band("ads_budget", D("0.001"), D("0.002"), D("0.004"), size=10.0)
    _, full, _ = floor_prior_band("ads_budget", D("0.001"), D("0.002"), D("0.004"), size=40.0)
    assert half == D("0.025") and full == MIN_PRIOR_LIFT


def test_exempt_kinds_are_never_floored():
    for kind in ("review_voucher", "voucher_cap", "ads_pause"):
        assert kind in FLOOR_EXEMPT
        lift = predict_lift(KINDS[kind], _cand(kind), _env(), None)
        assert not lift.floored
    assert (
        predict_lift(KINDS["review_voucher"], _cand("review_voucher"), _env(), None).at("p50")
        < 0.05
    )


def test_every_exempt_kind_is_a_real_kind_with_a_reason():
    assert all(k in KINDS and FLOOR_EXEMPT[k] for k in FLOOR_EXEMPT)


def test_not_estimable_stays_not_estimable_in_the_builder():
    option = OptionInput(
        kind="min_spend_voucher",
        label="x",
        drivers=(DriverEffect("aov", ("shop",), cast(Any, "not_estimable"), note="n"),),
        duration_days=None,
    )
    out = common.floor_prior_drivers(option)
    assert out.drivers[0].lift is None and out.drivers[0].basis == "not_estimable"


def test_builder_floors_the_prior_aov_driver_of_a_min_spend_voucher_but_not_a_measured_one():
    tiny = Band(D(0), D("0.0001"), D("0.0003"))
    prior = OptionInput(
        "min_spend_voucher",
        "x",
        (DriverEffect("aov", ("shop",), "prior", lift=tiny),),
        cast(Any, None),
    )
    measured = OptionInput(
        "min_spend_voucher",
        "x",
        (DriverEffect("aov", ("shop",), "measured", lift=tiny),),
        cast(Any, None),
    )
    assert common.floor_prior_drivers(prior).drivers[0].lift == Band(D(0), D("0.05"), D("0.05"))
    assert common.floor_prior_drivers(measured).drivers[0].lift == tiny


def test_builder_and_card_floor_a_kind_the_same_way():
    env = _env()
    card = predict_lift(KINDS["gift"], _cand("gift"), env, None)
    built = adapters.lift_evidence("gift", ["i1"], env)
    assert built.band.p50 == D("0.05") and round(card.at("p50"), 6) == 0.05
    assert built.basis == "prior"
