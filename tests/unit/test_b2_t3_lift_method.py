"""Batch 2 / t3: the lift method (owner 2026-11-19 round 5, acceptance L-1 ... L-9 and row IF).

The one ladder in ``prediction.predict_lift``: "ước tính" (the kind's P50 prior) -> "dữ liệu shop"
(>= 3 clean results of the kind in this shop) -> "Juli" (>= 3 of them from Juli cards); the
calibration is per shop and never pooled. Made-up figures only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import Band
from juli_backend.services.shopee_builder.engine.engine import run
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.engine_families.facts import LiftEvidence, SimpleFacts
from juli_backend.services.shopee_builder.engine_families.families import simple_option
from juli_backend.services.shopee_recommendations import config, forecast, learning, measure
from juli_backend.services.shopee_recommendations.kinds import KINDS, MIN_PRIOR_LIFT
from juli_backend.services.shopee_recommendations.learning import (
    CalibrationState,
    Observation,
    calibrate_all,
    is_juli_card,
)
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.prediction import (
    juli_results,
    predict_lift,
    prediction_type_of,
)
from tests.unit.test_engine_families import base

KEY = ("price_display", "ctr")
METRIC_KEYS = {"hien_tai", "du_kien", "delta", "delta_pct", "low", "high", "days"}


def _env(state: CalibrationState | None = None):
    return SimpleNamespace(
        calibration={} if state is None else {KEY: state},
        sim=None,
        response_by_item={},
        response_shop=None,
    )


def _lift(env, kind="price_display"):
    return predict_lift(KINDS[kind], Candidate(kind=kind, items=("1",)), env, None)


def _obs(measured=0.04, origin="engine", source="card"):
    return Observation("price_display", "ctr", 0.01, 0.03, measured, origin=origin, source=source)


def _state(obs):
    return calibrate_all(obs)[KEY]


# -- L-1 / L-2: the shop rung and the prior -----------------------------------------------------


def test_l1_two_clean_results_are_not_enough_three_are():
    two = _lift(_env(_state([_obs(origin="import")] * 2)))
    three = _lift(_env(_state([_obs(origin="import")] * 3)))
    assert (two.source, two.factor, two.prediction_type) == ("prior", 1.0, "ước tính")
    assert three.source == "shop" and three.prediction_type == "dữ liệu shop"
    assert three.factor > 1.0  # measured 0.04 against a 0.02 prediction centre


def test_l2_no_evidence_is_the_kinds_p50_prior_at_least_five_percent():
    lift = _lift(_env())
    assert lift.source == "prior" and lift.prediction_type == "ước tính"
    assert lift.at("p50") >= float(MIN_PRIOR_LIFT) - 1e-9
    # a kind with no formula (a relist) is estimated too, never zero (L-9)
    relist = _lift(_env(), "listing_relist")
    assert relist.source == "prior" and relist.at("p50") >= float(MIN_PRIOR_LIFT) - 1e-9


# -- L-3: per shop, never pooled; shrinkage n / (n + 5) -------------------------------------------


def test_l3_the_factor_is_shrunk_by_n_over_n_plus_five():
    state = _state([_obs(measured=0.04)] * 3)  # ratio 2.0
    lift = _lift(_env(state))
    assert lift.factor == pytest.approx(1 + (3 / (3 + config.SHRINKAGE_K)) * (2.0 - 1))


def test_l3_there_is_no_pooled_rung_to_fall_back_on():
    env = _env(_state([_obs()] * 2))
    env.pooled_calibration = {KEY: CalibrationState(*KEY, n_results=99, pooled_ratio=2.0)}
    assert _lift(env).source == "prior"


# -- L-4: Juli cards only -------------------------------------------------------------------------


def test_l4_two_juli_results_read_shop_three_read_juli():
    assert _lift(_env(_state([_obs()] * 3))).prediction_type == "Juli"
    mixed = _state([_obs()] * 2 + [_obs(origin="import")] * 2)  # 4 clean, 2 from Juli
    lift = _lift(_env(mixed))
    assert lift.source == "shop" and lift.prediction_type == "dữ liệu shop"
    assert juli_results(_env(mixed), "price_display") == 2


@pytest.mark.parametrize(
    ("origin", "source", "counts"),
    [
        ("engine", "card", True),
        ("manual", "card", True),  # built in Tự tạo and run through Juli
        ("import", "card", False),  # planned outside Juli ("Làm ngoài Juli")
        ("engine", "natural", False),  # backfill_natural: a past promotion
    ],
)
def test_l4_which_results_are_juli_cards(origin, source, counts):
    o = _obs(origin=origin, source=source)
    assert is_juli_card(o) is counts
    state = _state([o] * 3)
    assert state.n_results == 3  # every clean result counts toward "dữ liệu shop"
    assert (state.n_juli == 3) is counts
    assert _lift(_env(state)).prediction_type == ("Juli" if counts else "dữ liệu shop")


# -- L-5: what makes a result clean ------------------------------------------------------------


async def _why(monkeypatch, *, stacked=False, partial=False, sale=(), traffic_before=5, after=5):
    async def sale_days(session, shop_id, first, last):
        return set(sale)

    monkeypatch.setattr(measure, "contract_excluded_days", sale_days)
    t = date(2026, 10, 20)
    days = {}
    for i in range(1, 8):  # the 7 days before ``t``: the first ``traffic_before`` have traffic
        days[date.fromordinal(t.toordinal() - i)] = SimpleNamespace(
            views=100 if i <= traffic_before else 0, clicks=0
        )
    for i in range(1, 8):
        days[date.fromordinal(t.toordinal() + i)] = SimpleNamespace(
            views=100 if i <= after else 0, clicks=0
        )
    return await measure.clean_reasons(
        cast(Any, None),
        cast(Any, None),
        cast(Any, days),
        t=t,
        days=7,
        pre=7,
        stacked=stacked,
        partial=partial,
    )


async def test_l5_a_result_with_nothing_in_the_way_is_clean(monkeypatch):
    assert await _why(monkeypatch) == []


async def test_l5_another_card_or_promotion_on_the_same_days(monkeypatch):
    assert await _why(monkeypatch, stacked=True) == ["other_change"]


async def test_l5_a_mega_sale_day_in_either_window(monkeypatch):
    assert await _why(monkeypatch, sale=[date(2026, 10, 22)]) == ["sale_day"]


async def test_l5_fewer_than_five_traffic_days_in_either_window(monkeypatch):
    assert await _why(monkeypatch, traffic_before=4) == ["traffic_days_before"]
    assert await _why(monkeypatch, after=4) == ["traffic_days_after"]


# -- L-6: the range keeps the prior's proportions ------------------------------------------------


def test_l6_calibration_moves_the_whole_prior_band_by_one_factor():
    prior = _lift(_env())
    shop = _lift(_env(_state([_obs(measured=0.01)] * 3)))  # ratio 0.5 -> factor < 1
    assert shop.factor < 1.0 and not shop.floored
    # P10 / P90 are the (floored) prior's scaled by the same factor, the proportion is kept
    spec_lo, spec_hi = KINDS["price_display"].prior
    assert shop.low / shop.high == pytest.approx(spec_lo / spec_hi)
    assert prior.high >= prior.low


# -- L-7 / L-8 / L-9: nothing estimable by prior is "chưa ước tính được" --------------------------


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("title", sp.TitleSpec(kind="title", item_id="i", title="x")),
        (
            "cover_image",
            sp.CoverSpec(
                kind="cover_image", item_id="i", overlay=sp.CoverOverlay(layout="banner_top")
            ),
        ),
        ("price_display", sp.PriceDisplaySpec(kind="price_display", item_id="i")),
        (
            "description_first_line",
            sp.DescriptionSpec(kind="description_first_line", item_id="i", first_line="x"),
        ),
        ("listing_relist", sp.RelistSpec(kind="listing_relist", item_id="i")),
    ],
)
def test_l8_every_listing_kind_is_five_percent_through_the_chain(kind, spec):
    evidence = adapters.lift_evidence(kind, ["i"], _env())
    assert evidence.basis == "prior" and evidence.band.p50 >= MIN_PRIOR_LIFT
    result = run(base(), simple_option(spec, SimpleFacts(evidence)), n=300)
    assert result.estimable and result.basis == "prior"
    assert result.likely is not None and result.likely.gmv > result.before.gmv
    assert result.likely.profit is not None  # down the chain to lợi nhuận and biên
    assert forecast.forecast_of(result, reason=None, data_through=None)["prediction_type"] == (
        "ước tính"
    )


def test_l7_the_not_estimable_listing_helpers_are_gone():
    from juli_backend.services.shopee_builder import engine_families as ef
    from juli_backend.services.shopee_builder.engine_families import common, families

    for name in ("keyword_not_estimable_option", "unmeasured_listing_option"):
        assert not hasattr(families, name)
    assert not hasattr(ef, "_not_estimable_set")
    assert not hasattr(common, "NOTE_SET_NOT_CHEAPER")


# -- IF: prediction_type for t1 / t2 --------------------------------------------------------------


def _result(basis):
    spec = sp.PriceDisplaySpec(kind="price_display", item_id="i")
    band = Band(D("0.01"), D("0.05"), D("0.09"))
    return run(base(), simple_option(spec, SimpleFacts(LiftEvidence(band, basis))), n=300)


def test_if_prediction_type_sits_beside_metrics_never_inside_them():
    fc = forecast.forecast_of(_result("prior"), reason=None, data_through=None)
    assert fc["prediction_type"] == "ước tính"
    assert set(fc["metrics"]) == set(forecast.METRIC_KEYS)
    assert all(set(block) == METRIC_KEYS for block in fc["metrics"].values())


def test_if_the_three_values_and_one_function():
    shop = forecast.forecast_of(_result("shop"), reason=None, data_through=None)
    assert shop["prediction_type"] == "dữ liệu shop"
    juli = forecast.forecast_of(_result("shop"), reason=None, data_through=None, juli_results=3)
    assert juli["prediction_type"] == "Juli"
    assert prediction_type_of("prior") == "ước tính"
    assert prediction_type_of("product_history") == "dữ liệu shop"
    assert prediction_type_of("shop", config.JULI_MIN_RESULTS) == "Juli"
    assert prediction_type_of("not_estimable") is None


def test_if_no_estimate_has_no_type():
    fc = forecast.forecast_of(None, reason="no_spec", data_through=None)
    assert fc["prediction_type"] is None and set(fc["metrics"]) == set(forecast.METRIC_KEYS)


def test_if_the_stored_lift_carries_the_type():
    assert _lift(_env()).json()["prediction_type"] == "ước tính"
    assert learning.JULI_ORIGINS == {"engine", "manual"}
