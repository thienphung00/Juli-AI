"""F6: the pooled calibration rung (Shopee only), between the shop's calibration and the prior."""

from __future__ import annotations

from types import SimpleNamespace

from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.learning import (
    CalibrationState,
    Observation,
    calibrate,
)
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.prediction import predict_lift


def _env(shop=None, pooled=None):
    return SimpleNamespace(
        calibration=shop or {},
        pooled_calibration=pooled or {},
        sim=None,
        response_by_item={},
        response_shop=None,
    )


def _state(n, ratio=2.0):
    return CalibrationState("price_display", "ctr", n_results=n, pooled_ratio=ratio)


def _lift(env):
    spec = KINDS["price_display"]
    return predict_lift(spec, Candidate(kind="price_display", items=("1",)), env, None)


def test_the_shop_rung_wins_when_it_has_five_results():
    key = ("price_display", "ctr")
    lift = _lift(_env({key: _state(6, 1.5)}, {key: _state(40, 0.5)}))
    assert lift.source == "shop"


def test_pooled_is_used_when_the_shop_has_fewer_than_five_results():
    key = ("price_display", "ctr")
    lift = _lift(_env({key: _state(2, 1.5)}, {key: _state(8, 1.5)}))
    assert lift.source == "pooled"
    assert lift.factor > 1.0 and not lift.floored


def test_pooled_needs_five_results_else_the_prior():
    key = ("price_display", "ctr")
    lift = _lift(_env({}, {key: _state(4)}))
    assert lift.source == "prior"


def test_calibrate_over_several_shops_observations_pools_their_results():
    def obs(measured):
        return Observation("price_display", "ctr", 0.01, 0.03, measured)

    pooled = calibrate([obs(0.02)] * 3 + [obs(0.04)] * 3)
    assert pooled[("price_display", "ctr")].n_results == 6
