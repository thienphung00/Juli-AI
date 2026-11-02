"""The numpy CTR / CTOR flow GLM (services/shopee_kpi/flow_glm.py, flow_model.py v2).

- The B-spline basis is patsy's ``bs(t, df=4)``: one interior knot at the median, the
  basis equal to scipy's B-spline design matrix (first column dropped), a partition of
  unity with that column.
- IRLS recovers known logit coefficients from simulated binomial days; extra-binomial
  noise shows up as dispersion > 1 (quasi-binomial), plain binomial days floor it at 1.
- Below the 3,000 / 100 floor there is no model; days with more clicks than
  impressions are dropped and counted.

Simulated data only.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from juli_backend.services.shopee_kpi import flow_glm

FIRST, LAST = date(2026, 4, 1), date(2026, 10, 28)
DAYS = [FIRST + timedelta(i) for i in range((LAST - FIRST).days + 1)]
TRUE = {"Intercept": -3.0, "C(dow)[T.5]": 0.15, "double_day": 0.4, "day15": -0.2, "day25": 0.25}


def simulate(
    n: float, seed: int, noise: float = 0.0
) -> dict[date, tuple[float, float, float, float]]:
    rng = np.random.default_rng(seed)
    out = {}
    for d in DAYS:
        cal = flow_glm.calendar_row(d)
        eta = (
            TRUE["Intercept"]
            + TRUE["C(dow)[T.5]"] * (d.weekday() == 5)
            + TRUE["double_day"] * cal["double_day"]
            + TRUE["day15"] * cal["day15"]
            + TRUE["day25"] * cal["day25"]
            + rng.normal(0, noise)
        )
        imp = float(rng.poisson(n))
        clk = float(rng.binomial(int(imp), 1 / (1 + np.exp(-eta))))
        out[d] = (imp, clk, float(rng.binomial(int(clk), 0.08)), 0.0)
    return out


def test_the_spline_basis_is_patsys_bs_df4():
    scipy_interpolate = pytest.importorskip("scipy.interpolate")
    t = np.arange(0, 211, dtype=float)
    basis = flow_glm.SplineBasis.fit(t)
    assert basis.knots == (0.0,) * 4 + (105.0,) + (210.0,) * 4
    design = basis(t)
    assert design.shape == (211, 4)
    full = scipy_interpolate.BSpline.design_matrix(t, np.array(basis.knots), 3).toarray()
    np.testing.assert_allclose(design, full[:, 1:], atol=1e-12)
    np.testing.assert_allclose(full.sum(axis=1), 1.0, atol=1e-12)
    assert design[-1].tolist() == [0.0, 0.0, 0.0, 1.0]  # the right boundary is inside


def test_irls_recovers_known_coefficients():
    model = flow_glm.fit_rate("the_san_pham", "ctr", simulate(200_000, seed=1))
    assert model is not None
    coef, se = model.coef, model.se
    for name, value in TRUE.items():
        assert coef[name] == pytest.approx(value, abs=4 * se[name] + 0.01), name
    assert abs(coef["day1"]) < 4 * se["day1"] + 0.01  # no true effect
    assert model.fit.dispersion == pytest.approx(1.0, abs=0.3)
    assert model.design.columns[:2] == ("Intercept", "C(dow)[T.1]")
    assert len(model.design.columns) == 1 + 6 + 4 + 4


def test_extra_binomial_noise_is_quasi_binomial_dispersion():
    plain = flow_glm.fit_rate("f", "ctr", simulate(20_000, seed=2))
    noisy = flow_glm.fit_rate("f", "ctr", simulate(20_000, seed=2, noise=0.15))
    assert plain is not None and noisy is not None
    assert plain.fit.dispersion < 1.5
    assert noisy.fit.dispersion > 10  # var(eta)·n·p(1−p) ≈ 0.0225 × 20,000 × 0.045
    assert noisy.se["Intercept"] > 3 * plain.se["Intercept"]


def test_the_band_holds_calendar_terms_at_zero_and_brackets_the_mean():
    model = flow_glm.fit_rate("the_san_pham", "ctr", simulate(200_000, seed=3))
    assert model is not None
    band = flow_glm.band(model, window=30, horizon=14)
    assert band.window_days == 30 and band.last_day == LAST and band.horizon_days == 14
    assert band.band90_low < band.forecast_mean < band.band90_high
    base = 1 / (1 + np.exp(3.0))
    assert band.forecast_mean == pytest.approx(base, rel=0.03)
    # the last 30 days include 15/10 and 25/10: the adjusted rate keeps only the weekday
    last30 = DAYS[-30:]
    expected = np.mean([1 / (1 + np.exp(3.0 - 0.15 * (d.weekday() == 5))) for d in last30])
    assert band.adjusted_rate == pytest.approx(expected, rel=0.03)
    assert 0 < band.noise90_halfwidth_pct < band.band90_halfwidth_pct


def test_no_model_below_the_floor_and_impossible_days_are_dropped():
    thin = {d: (90.0, 3.0, 0.0, 0.0) for d in DAYS[:30]}  # 2,700 impressions < 3,000
    assert flow_glm.fit_rate("f", "ctr", thin) is None
    data = simulate(20_000, seed=4)
    data[DAYS[10]] = (100.0, 150.0, 0.0, 0.0)  # more clicks than impressions
    model = flow_glm.fit_rate("f", "ctr", data)
    assert model is not None and model.dropped_num_gt_den == 1
    assert DAYS[10] not in model.days
