"""D41.2 (T2A, fast track P31): shrink CTR / CTOR toward the category before the trigger.

Empirical-Bayes beta-binomial: the category prior (method of moments over the shop's
products of the category, same window) pulls a product with few events toward the
category rate and leaves a product with many events as it is; a category with fewer
than 5 products uses the shop-wide prior. Only D39.1's comparison with the band uses
it; ``kpi_shrinkage = off`` restores P30. Synthetic fixtures only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.metric_trigger import metric_trigger
from juli_backend.services.optimize_product.shrinkage import (
    MIN_CATEGORY_PRODUCTS,
    SCOPE_CATEGORY,
    SCOPE_SHOP,
    BetaPrior,
    ShrinkageContext,
    fit_beta_prior,
)
from juli_backend.services.optimize_product.tunables import (
    KPI_SHRINKAGE,
    TUNABLE_KEYS,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.optimize_product.volatility import assess_product

AS_OF = date(2026, 10, 6)
TUNABLES = DiagTunables()


# =========================================================================== the prior


def test_small_n_is_pulled_to_the_prior_and_large_n_is_unchanged():
    # A category whose products really differ a little (2.5–4.5 %), plenty of data each.
    pairs = [(250, 10_000), (300, 10_000), (350, 10_000), (400, 10_000), (450, 10_000)]
    prior = fit_beta_prior(pairs, scope=SCOPE_CATEGORY)
    assert prior is not None and prior.scope == SCOPE_CATEGORY
    assert prior.mean == pytest.approx(0.035, abs=1e-6)
    # Between-product spread ≈ 0.7 points -> a prior worth a few hundred impressions.
    assert 100 < prior.strength < 2_000

    # 3 clicks out of 20 impressions (15 %) is mostly luck: it lands near the category.
    small = prior.posterior_mean(3, 20)
    assert abs(small - prior.mean) < 0.2 * abs(3 / 20 - prior.mean)
    # 50 000 clicks out of 1 000 000 impressions (5 %) is evidence: it stays put.
    large = prior.posterior_mean(50_000, 1_000_000)
    assert large == pytest.approx(0.05, rel=0.01)


def test_a_spread_no_wider_than_noise_pools_fully_but_never_beyond_the_data():
    # Five products with the same true rate: the spread is binomial noise alone.
    pairs = [(35, 1_000), (36, 1_000), (34, 1_000), (35, 1_000), (35, 1_000)]
    prior = fit_beta_prior(pairs)
    assert prior is not None
    assert prior.strength == pytest.approx(5_000)  # κ = N, the whole category's data
    assert prior.posterior_mean(10, 100) == pytest.approx(prior.mean, abs=0.006)


def test_no_prior_without_two_products_or_without_any_success():
    assert fit_beta_prior([(5, 100)]) is None
    assert fit_beta_prior([(0, 100), (0, 200)]) is None
    assert fit_beta_prior([(5, 0), (6, 0)]) is None


def _flat(impressions: float, clicks_by_window: tuple[float, float], days: int = 28):
    """``days`` rows ending AS_OF: the last 14 at ``clicks_by_window[0]``, the rest at [1]."""
    rows = []
    for offset in range(days):
        clicks = clicks_by_window[0] if offset < 14 else clicks_by_window[1]
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(str(impressions)),
                clicks=Decimal(str(clicks)),
                sku_orders=Decimal("1"),
                items_sold=Decimal("1"),
                gmv=Decimal("100000"),
            )
        )
    return rows


def test_a_small_category_falls_back_to_the_shop_wide_prior():
    daily = {f"p{i}": _flat(1_000, (35 + i, 35 + i)) for i in range(7)}
    # Two products in "Đồ uống" (< 5), five in "Bánh kẹo" (= 5).
    categories = {f"p{i}": ("Đồ uống" if i < 2 else "Bánh kẹo") for i in range(7)}
    ctx = ShrinkageContext(daily=daily, categories=categories, as_of=AS_OF)
    assert MIN_CATEGORY_PRODUCTS == 5
    small = ctx.prior("p0", "ctr", "total", 14)
    own = ctx.prior("p3", "ctr", "total", 14)
    assert isinstance(small, BetaPrior) and small.scope == SCOPE_SHOP and small.products == 7
    assert isinstance(own, BetaPrior) and own.scope == SCOPE_CATEGORY and own.products == 5
    # No category at all: the shop-wide prior too.
    assert (
        ShrinkageContext(daily=daily, categories={}, as_of=AS_OF)
        .prior("p0", "ctr", "total", 14)
        .scope
        == SCOPE_SHOP
    )
    # A shop with fewer than 3 products has no prior: the rate stays raw.
    two = {k: daily[k] for k in ("p0", "p1")}
    assert (
        ShrinkageContext(daily=two, categories={}, as_of=AS_OF).prior("p0", "ctr", "total", 14)
        is None
    )


# =========================================================================== the trigger


def _wobbly(impressions: float, ctr_now: float, ctr_before: float, wobble: float):
    """28 days: the last 14 at ``ctr_now``, the 14 before at ``ctr_before``; clicks
    alternate ± ``wobble`` (relative) day to day, so each window has a band."""
    rows = []
    for offset in range(28):
        ctr = ctr_now if offset < 14 else ctr_before
        sign = 1 if offset % 2 else -1
        clicks = impressions * ctr * (1 + sign * wobble)
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(str(impressions)),
                clicks=Decimal(str(round(clicks, 2))),
                sku_orders=Decimal(str(round(clicks * 0.05, 2))),
                items_sold=Decimal(str(round(clicks * 0.05, 2))),
                gmv=Decimal(str(round(clicks * 0.05 * 100_000))),
            )
        )
    return rows


def _ctr_drop(daily, categories, pid, *, shrink: bool):
    rows = daily[pid]
    tunables = DiagTunables(windows=(14,))
    assessment = assess_product(pid, rows, as_of=AS_OF, tunables=tunables)
    ctx = ShrinkageContext(daily=daily, categories=categories, as_of=AS_OF)
    trigger = metric_trigger(
        rows,
        as_of=AS_OF,
        tunables=tunables,
        assessment=assessment,
        shrinkage=ctx.for_product(pid) if shrink else None,
    )
    return next((d for d in trigger.drops if d.metric == "ctr"), None)


def test_a_noisy_fall_on_few_impressions_no_longer_opens_a_card():
    # Five big products at 3.5 % in both windows; one small product "falls" 4 % -> 3 %
    # on 100 impressions a day: luck the category explains.
    daily = {f"big{i}": _wobbly(10_000, 0.035, 0.035, 0.03) for i in range(5)}
    daily["small"] = _wobbly(100, 0.03, 0.04, 0.3)
    categories = dict.fromkeys(daily, "Bánh kẹo")
    raw = _ctr_drop(daily, categories, "small", shrink=False)
    assert raw is not None and raw.drop_pct == pytest.approx(25.0, abs=0.5)
    assert raw.shrunk is None
    assert _ctr_drop(daily, categories, "small", shrink=True) is None


def test_a_real_fall_on_many_impressions_still_opens_a_card():
    daily = {f"big{i}": _wobbly(10_000, 0.035, 0.035, 0.03) for i in range(4)}
    daily["falling"] = _wobbly(10_000, 0.028, 0.035, 0.03)
    categories = dict.fromkeys(daily, "Bánh kẹo")
    raw = _ctr_drop(daily, categories, "falling", shrink=False)
    shrunk = _ctr_drop(daily, categories, "falling", shrink=True)
    assert raw is not None and shrunk is not None
    assert shrunk.drop_pct == raw.drop_pct  # the copy keeps the raw fall
    assert shrunk.shrunk_drop_pct == pytest.approx(raw.drop_pct, abs=1.0)  # ~unchanged
    assert shrunk.gmv_cost_per_day == raw.gmv_cost_per_day  # cost / ranking unchanged
    payload = shrunk.to_json()["shrinkage"]
    assert payload["prior"]["scope"] == SCOPE_CATEGORY  # 5 products: the category's own


def test_kpi_shrinkage_tunable_defaults_on_and_validates():
    assert KPI_SHRINKAGE in TUNABLE_KEYS
    assert DiagTunables().shrinkage_on is True
    assert DiagTunables().to_json()[KPI_SHRINKAGE] == "on"
    off = DiagTunables.from_overrides({KPI_SHRINKAGE: "off"})
    assert off.shrinkage_on is False
    assert DiagTunables.from_overrides({KPI_SHRINKAGE: "maybe"}).shrinkage_on is True
    with pytest.raises(TunableError):
        validate_tunable(KPI_SHRINKAGE, True)
