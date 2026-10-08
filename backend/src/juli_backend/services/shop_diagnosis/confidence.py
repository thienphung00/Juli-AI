"""Confidence label on every comparison — ADR-108 decision 11.

* **Rõ** — at least ``clear_min_orders`` SKU orders on each side and the 90 %
  interval of the difference excludes 0;
* **Tham khảo** — 10–29 orders on a side, or a difference inside the noise band;
* **Chưa đủ dữ liệu** — under ``reference_min_orders`` orders on a side.

Rates (CTR, Tỷ lệ thêm vào giỏ hàng, CTOR) use a two-proportion z interval on the
window totals. Daily-average quantities (Lượt hiển thị sản phẩm, GMV, AOV) use a
Welch interval on the difference of the two windows' daily series.
"""

from __future__ import annotations

import math
from enum import StrEnum

from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig


class Confidence(StrEnum):
    CLEAR = "Rõ"
    REFERENCE = "Tham khảo"
    INSUFFICIENT = "Chưa đủ dữ liệu"


def volume_label(
    orders_prior: float, orders_last: float, config: ShopDiagnosisConfig
) -> Confidence:
    """The order-floor part of the label, before any test."""
    smallest = min(orders_prior, orders_last)
    if smallest < config.reference_min_orders:
        return Confidence.INSUFFICIENT
    if smallest < config.clear_min_orders:
        return Confidence.REFERENCE
    return Confidence.CLEAR


def _rate_variance(successes: float, trials: float) -> float:
    """Binomial variance of a rate; Poisson when the rate exceeds 1.

    A LIVE CTOR can exceed 1 (buyers order without clicking), where the binomial
    form turns negative.
    """
    rate = successes / trials
    return rate * (1 - rate) / trials if rate <= 1 else rate / trials


def rate_differs(
    successes_prior: float,
    trials_prior: float,
    successes_last: float,
    trials_last: float,
    z_value: float,
) -> bool:
    """Whether the two-proportion interval of ``last − prior`` excludes 0."""
    if trials_prior <= 0 or trials_last <= 0:
        return False
    diff = successes_last / trials_last - successes_prior / trials_prior
    se = math.sqrt(
        _rate_variance(successes_prior, trials_prior) + _rate_variance(successes_last, trials_last)
    )
    if se == 0:
        return diff != 0
    return abs(diff) > z_value * se


def series_differs(prior: list[float], last: list[float], z_value: float) -> bool:
    """Whether the Welch interval of ``mean(last) − mean(prior)`` excludes 0."""
    if len(prior) < 2 or len(last) < 2:
        return False
    mean_prior = sum(prior) / len(prior)
    mean_last = sum(last) / len(last)
    var_prior = sum((x - mean_prior) ** 2 for x in prior) / (len(prior) - 1)
    var_last = sum((x - mean_last) ** 2 for x in last) / (len(last) - 1)
    se = math.sqrt(var_prior / len(prior) + var_last / len(last))
    diff = mean_last - mean_prior
    if se == 0:
        return diff != 0
    return abs(diff) > z_value * se


def label(
    orders_prior: float, orders_last: float, differs: bool, config: ShopDiagnosisConfig
) -> Confidence:
    """Combine the order floors with the test result."""
    volume = volume_label(orders_prior, orders_last, config)
    if volume is Confidence.CLEAR and not differs:
        return Confidence.REFERENCE
    return volume


def rate_label(
    successes_prior: float,
    trials_prior: float,
    successes_last: float,
    trials_last: float,
    orders_prior: float,
    orders_last: float,
    config: ShopDiagnosisConfig,
) -> Confidence:
    differs = rate_differs(
        successes_prior, trials_prior, successes_last, trials_last, config.z_value
    )
    return label(orders_prior, orders_last, differs, config)


def series_label(
    prior: list[float],
    last: list[float],
    orders_prior: float,
    orders_last: float,
    config: ShopDiagnosisConfig,
) -> Confidence:
    return label(orders_prior, orders_last, series_differs(prior, last, config.z_value), config)
