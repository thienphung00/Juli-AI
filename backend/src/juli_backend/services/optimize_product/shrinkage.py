"""Empirical-Bayes shrinkage of per-product CTR / CTOR before the trigger (D41.2, T2A; P31). Pure.

A product with few events has a noisy rate: 3 orders from 40 clicks is a CTOR of
7.5 %, 1 order the next fortnight is 2.5 % -- a "fall" of two thirds that says
nothing. D39.1 compares each product's window mean with its earlier level, so
such noise opens cards. D41.2 shrinks the rate first, toward the rate of the
product's category in the shop, in proportion to the product's own events:

1. **Successes / trials.** CTR = clicks / impressions, CTOR = orders / clicks,
   summed over the window (on the metric's channel, D32).
2. **Prior (beta-binomial, method of moments).** Over the shop's products of the
   same category, same channel, same calendar window (``k`` products with
   ``n_i > 0`` trials, ``s_i`` successes, rate ``p_i = s_i / n_i``)::

       N  = Σ n_i                    m  = Σ s_i / N           (pooled rate)
       S  = Σ n_i (p_i − m)²                                   (weighted spread)
       τ² = (S − (k − 1) · m (1 − m)) / (N − Σ n_i² / N)       (spread beyond binomial noise)
       κ  = m (1 − m) / τ² − 1        clipped to [1, N];  κ = N when τ² ≤ 0
       α  = m κ,  β = (1 − m) κ

   ``τ²`` is the between-product variance of the true rates once the binomial
   noise each product's own trials add is taken out (the weighted
   method-of-moments estimator); ``κ = α + β`` is the prior's weight in
   "pseudo-trials". When the spread is no larger than noise, the products are
   indistinguishable and the prior weighs as much as the whole category's data
   (κ = N, never more). A category with fewer than
   :data:`MIN_CATEGORY_PRODUCTS` (5) products with trials uses the shop-wide
   prior (every product, any category); a shop with fewer than
   :data:`MIN_SHOP_PRODUCTS` (3) has no prior and the rate is left raw.
3. **Posterior mean.** ``(s + α) / (n + α + β)``: a product with ``n ≫ κ`` is
   essentially unchanged, one with ``n ≪ κ`` sits near the category rate.

Both windows the trigger compares (now, and the same-length window before it)
are shrunk, each with the prior of its own calendar window. Only detection uses
this (D41.2); the KPI target, the band and the GMV cost read the raw values
(D41.1). Switch: the per-shop tunable ``kpi_shrinkage`` (``on`` / ``off``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.kpi_channel import CHANNEL_TOTAL, channel_days
from juli_backend.services.optimize_product.volatility import WindowCounts, window_counts

#: The rates shrunk (Lượt hiển thị is a count, AOV a mean of money: not binomial).
SHRINK_METRICS: tuple[str, ...] = ("ctr", "ctor")
#: A category needs this many products with trials to have its own prior.
MIN_CATEGORY_PRODUCTS = 5
#: The shop-wide fallback needs this many.
MIN_SHOP_PRODUCTS = 3

SCOPE_CATEGORY = "category"
SCOPE_SHOP = "shop"


@dataclass(frozen=True)
class BetaPrior:
    """A beta prior on a rate: mean ``α / (α + β)``, weight ``κ = α + β`` pseudo-trials."""

    alpha: float
    beta: float
    products: int
    scope: str = SCOPE_SHOP

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def strength(self) -> float:
        return self.alpha + self.beta

    def posterior_mean(self, successes: float, trials: float) -> float:
        return (successes + self.alpha) / (trials + self.alpha + self.beta)

    def to_json(self) -> dict[str, Any]:
        return {
            "alpha": round(self.alpha, 4),
            "beta": round(self.beta, 4),
            "mean": round(self.mean, 6),
            "strength": round(self.strength, 2),
            "products": self.products,
            "scope": self.scope,
        }


def successes_trials(counts: WindowCounts, metric: str) -> tuple[float, float] | None:
    """``(successes, trials)`` over a window: CTR clicks / impressions, CTOR orders / clicks."""
    if metric == "ctr":
        s, n = counts.clicks, counts.impressions
    elif metric == "ctor":
        s, n = counts.orders, counts.clicks
    else:
        return None
    if n <= 0:
        return None
    return min(s, n), n


def fit_beta_prior(
    pairs: Sequence[tuple[float, float]], *, scope: str = SCOPE_SHOP
) -> BetaPrior | None:
    """The method-of-moments beta prior of ``(successes, trials)`` pairs (docstring, step 2)."""
    usable = [(float(s), float(n)) for s, n in pairs if n > 0]
    k = len(usable)
    if k < 2:
        return None
    total = sum(n for _, n in usable)
    m = sum(s for s, _ in usable) / total
    if not 0 < m < 1:
        return None
    spread = sum(n * (s / n - m) ** 2 for s, n in usable)
    denominator = total - sum(n * n for _, n in usable) / total
    noise = m * (1 - m)
    tau2 = (spread - (k - 1) * noise) / denominator if denominator > 0 else 0.0
    kappa = total if tau2 <= 0 else noise / tau2 - 1
    kappa = min(max(kappa, 1.0), max(total, 1.0))
    return BetaPrior(alpha=m * kappa, beta=(1 - m) * kappa, products=k, scope=scope)


@dataclass(frozen=True)
class Shrunk:
    """Both windows' rates after shrinkage, with the priors used."""

    current: float
    earlier: float
    prior_now: BetaPrior
    prior_earlier: BetaPrior

    def to_json(self) -> dict[str, Any]:
        return {
            "current": round(self.current, 6),
            "earlier": round(self.earlier, 6),
            "prior": self.prior_now.to_json(),
            "prior_earlier": self.prior_earlier.to_json(),
        }


@dataclass
class ShrinkageContext:
    """The shop's products, to fit priors per (category, metric, channel, window). Cached."""

    daily: Mapping[str, Sequence[ProductDay]]
    categories: Mapping[str, str | None]
    as_of: date
    _projected: dict[tuple[str, str], Sequence[ProductDay]] = field(default_factory=dict)
    _pairs: dict[tuple[str, str, int, int], dict[str, tuple[float, float]]] = field(
        default_factory=dict
    )
    _priors: dict[tuple[str | None, str, str, int, int], BetaPrior | None] = field(
        default_factory=dict
    )

    def _rows(self, product_id: str, channel: str) -> Sequence[ProductDay]:
        key = (product_id, channel)
        if key not in self._projected:
            rows = self.daily.get(product_id, ())
            self._projected[key] = rows if channel == CHANNEL_TOTAL else channel_days(rows, channel)
        return self._projected[key]

    def _window_pairs(
        self, metric: str, channel: str, length: int, offset: int
    ) -> dict[str, tuple[float, float]]:
        key = (metric, channel, length, offset)
        if key not in self._pairs:
            out: dict[str, tuple[float, float]] = {}
            for pid in self.daily:
                rows = self._rows(pid, channel)
                if not rows:
                    continue
                pair = successes_trials(
                    window_counts(rows, self.as_of, length, offset=offset), metric
                )
                if pair is not None:
                    out[pid] = pair
            self._pairs[key] = out
        return self._pairs[key]

    def prior(
        self, product_id: str, metric: str, channel: str, length: int, offset: int = 0
    ) -> BetaPrior | None:
        """The category prior of ``product_id``'s window, else the shop-wide one, else ``None``."""
        category = self.categories.get(product_id) or None
        cache_key = (category, metric, channel, length, offset)
        if cache_key in self._priors:
            return self._priors[cache_key]
        pairs = self._window_pairs(metric, channel, length, offset)
        prior: BetaPrior | None = None
        if category is not None:
            peers = [p for pid, p in pairs.items() if self.categories.get(pid) == category]
            if len(peers) >= MIN_CATEGORY_PRODUCTS:
                prior = fit_beta_prior(peers, scope=SCOPE_CATEGORY)
        if prior is None and len(pairs) >= MIN_SHOP_PRODUCTS:
            prior = fit_beta_prior(list(pairs.values()), scope=SCOPE_SHOP)
        self._priors[cache_key] = prior
        return prior

    def for_product(self, product_id: str) -> ProductShrinkage:
        return ProductShrinkage(self, product_id)


@dataclass(frozen=True)
class ProductShrinkage:
    """One product's view of the shop's priors (what the trigger is handed)."""

    context: ShrinkageContext
    product_id: str

    def shrink(
        self,
        metric: str,
        channel: str,
        length: int,
        now: WindowCounts,
        before: WindowCounts,
    ) -> Shrunk | None:
        """Both windows' posterior means, or ``None`` (not a rate, no trials, no prior)."""
        if metric not in SHRINK_METRICS:
            return None
        pair_now, pair_before = successes_trials(now, metric), successes_trials(before, metric)
        if pair_now is None or pair_before is None:
            return None
        prior_now = self.context.prior(self.product_id, metric, channel, length, 0)
        prior_before = self.context.prior(self.product_id, metric, channel, length, length)
        if prior_now is None or prior_before is None:
            return None
        return Shrunk(
            current=prior_now.posterior_mean(*pair_now),
            earlier=prior_before.posterior_mean(*pair_before),
            prior_now=prior_now,
            prior_earlier=prior_before,
        )


__all__ = [
    "MIN_CATEGORY_PRODUCTS",
    "MIN_SHOP_PRODUCTS",
    "SCOPE_CATEGORY",
    "SCOPE_SHOP",
    "SHRINK_METRICS",
    "BetaPrior",
    "ProductShrinkage",
    "ShrinkageContext",
    "Shrunk",
    "fit_beta_prior",
    "successes_trials",
]
