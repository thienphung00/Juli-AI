"""L-3 (owner 2026-11-19): the calibration is per shop, never pooled across shops.

F6's pooled rung (the same evidence pooled across the real Shopee shops, between the shop's
calibration and the prior) is gone: this file asserts nothing reads or builds it any more.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

from juli_backend.services.shopee_recommendations import loader, store
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.kinds import KINDS
from juli_backend.services.shopee_recommendations.learning import CalibrationState
from juli_backend.services.shopee_recommendations.model import Candidate
from juli_backend.services.shopee_recommendations.prediction import predict_lift


def _env(shop=None, pooled=None):
    # a stray ``pooled_calibration`` attribute (an old caller) must change nothing
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


def test_the_shops_own_results_win_at_three():
    key = ("price_display", "ctr")
    lift = _lift(_env({key: _state(3, 1.5)}, {key: _state(40, 0.5)}))
    assert lift.source == "shop" and lift.factor > 1.0


def test_other_shops_results_never_lift_a_shop_with_too_few_of_its_own():
    key = ("price_display", "ctr")
    lift = _lift(_env({key: _state(2, 1.5)}, {key: _state(80, 1.5)}))
    assert lift.source == "prior" and lift.factor == 1.0


def test_no_pooled_calibration_is_stored_loaded_or_read():
    assert "pooled_calibration" not in {f.name for f in dataclasses.fields(RecoEnv)}
    assert not hasattr(store, "load_pooled_calibrations")
    assert "pooled_calibration" not in vars(loader) and not hasattr(loader.store, "load_pooled")
