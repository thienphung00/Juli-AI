"""Performance Prediction, layer 2 (D30.3): a calibrated lift range per card. Pure.

**Prior.** Per (lever, Quality-Score gap bucket) a relative lift range on the
lever's target metric (:data:`PRIOR_LIFT`). TikTok Academy VN names the levers and
the metric each moves -- "Lưu lượng truy cập sản phẩm" (GMV = Lượt hiển thị × CTR ×
CTOR × AOV): the main image and the title drive CTR on the product card, the title's
keywords drive search impressions, the description / detail page and the price
promotions (product discount, flash sale, shipping discount) drive CTOR, and
"mua nhiều giảm nhiều" drives AOV. The Academy publishes no lift figures, so the
numbers below are Juli's conservative placeholders: wider and higher when the
lever's Quality-Score part is weak (more to fix), near zero when it is already
strong. They exist to be replaced by measurements.

**Calibration.** Measured day-14 results move each lever's coefficient
(realised ÷ expected GMV, ``lever_calibrations``, 0.5 until measured,
``lever_flows.measurement``). The factor is D24.6's ``coefficient ÷ 0.5`` clamped to
[0.25, 2] (:class:`~.decision_cards.LeverHistory`). Shrinkage: the fleet factor is
pulled toward neutral (1) by ``n / (n + K)``; the shop's own factor is used, blended
the same way toward the fleet factor, only once the shop has ``≥ MIN_SHOP_RESULTS``
measured results. Output: the lift range × factor, then a GMV range.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: (low, high) relative lift on the lever's metric, by Quality-Score gap bucket.
PRIOR_LIFT: Mapping[str, Mapping[str, tuple[float, float]]] = {
    "cover_image": {
        "large": (0.08, 0.25),
        "medium": (0.04, 0.15),
        "small": (0.00, 0.06),
        "unknown": (0.02, 0.12),
    },
    "title": {
        "large": (0.05, 0.20),
        "medium": (0.03, 0.12),
        "small": (0.00, 0.05),
        "unknown": (0.02, 0.10),
    },
    "description": {
        "large": (0.05, 0.18),
        "medium": (0.03, 0.10),
        "small": (0.00, 0.05),
        "unknown": (0.02, 0.08),
    },
    # Price levers have no Quality-Score part: one range for every bucket.
    "product_discount": {"unknown": (0.05, 0.20)},
    "flash_sale": {"unknown": (0.05, 0.25)},
    "shipping_discount": {"unknown": (0.03, 0.12)},
    "buy_more_save_more": {"unknown": (0.03, 0.10)},
}
DEFAULT_PRIOR: tuple[float, float] = (0.02, 0.10)

#: A shop needs this many measured day-14 results for its own factor to count.
MIN_SHOP_RESULTS = 5
#: Shrinkage strength: ``n / (n + K)`` of the evidence is trusted.
SHRINKAGE_K = 5.0

CALIBRATION_NEUTRAL = 0.5
FACTOR_MIN, FACTOR_MAX = 0.25, 2.0
DAYS_PER_MONTH = 30


def gap_bucket(gap: int | None) -> str:
    if gap is None:
        return "unknown"
    if gap >= 50:
        return "large"
    if gap >= 20:
        return "medium"
    return "small"


def prior_lift(lever: str, gap: int | None) -> tuple[float, float]:
    table = PRIOR_LIFT.get(lever)
    if table is None:
        return DEFAULT_PRIOR
    return table.get(gap_bucket(gap)) or table.get("unknown") or DEFAULT_PRIOR


def calibration_factor(coefficient: float | Decimal | None) -> float:
    """D24.6: ``coefficient ÷ 0.5`` clamped to [0.25, 2]; 1 when unmeasured."""
    if coefficient is None:
        return 1.0
    factor = float(coefficient) / CALIBRATION_NEUTRAL
    return min(max(factor, FACTOR_MIN), FACTOR_MAX)


@dataclass(frozen=True)
class CalibrationStats:
    """One lever's measured coefficient and how many day-14 results it rests on."""

    coefficient: float | None = None
    results: int = 0


#: D14 (owner, 2026-10-27): the fleet level's wider cell -- every lever pooled -- used for
#: a lever whose own fleet cell is too thin (``lever_flows.measurement.
#: pool_fleet_calibration``).
FLEET_ALL_LEVERS = "*"


def fleet_stats_for(fleet: Mapping[str, CalibrationStats], lever: str) -> CalibrationStats | None:
    """The lever's fleet level: its own pooled cell, else the all-levers cell, else None."""
    return fleet.get(lever) or fleet.get(FLEET_ALL_LEVERS)


def blended_factor(
    shop: CalibrationStats | None, fleet: CalibrationStats | None
) -> tuple[float, str]:
    """(factor, source): shop-level when it has enough results, else fleet, else prior."""
    fleet_factor, source = 1.0, "prior"
    if fleet is not None and fleet.results > 0 and fleet.coefficient is not None:
        weight = fleet.results / (fleet.results + SHRINKAGE_K)
        fleet_factor = 1.0 + weight * (calibration_factor(fleet.coefficient) - 1.0)
        source = "fleet"
    if shop is not None and shop.coefficient is not None and shop.results >= MIN_SHOP_RESULTS:
        weight = shop.results / (shop.results + SHRINKAGE_K)
        return fleet_factor + weight * (calibration_factor(shop.coefficient) - fleet_factor), "shop"
    return fleet_factor, source


@dataclass(frozen=True)
class Prediction:
    lever: str
    gap_bucket: str
    lift_low: float
    lift_high: float
    factor: float
    source: str  # "shop" | "fleet" | "prior"

    @property
    def lift_mid(self) -> float:
        return (self.lift_low + self.lift_high) / 2

    def metric_range(self, current: float) -> tuple[float, float]:
        return current * (1 + self.lift_low), current * (1 + self.lift_high)

    def to_json(self) -> dict[str, Any]:
        return {
            "lever": self.lever,
            "gap_bucket": self.gap_bucket,
            "lift_low": self.lift_low,
            "lift_high": self.lift_high,
            "factor": self.factor,
            "source": self.source,
        }


def predict(
    lever: str,
    qs_gap: int | None,
    *,
    shop: CalibrationStats | None = None,
    fleet: CalibrationStats | None = None,
) -> Prediction:
    low, high = prior_lift(lever, qs_gap)
    factor, source = blended_factor(shop, fleet)
    return Prediction(
        lever=lever,
        gap_bucket=gap_bucket(qs_gap),
        lift_low=low * factor,
        lift_high=high * factor,
        factor=factor,
        source=source,
    )


def gmv_range_per_month(
    gmv_per_day: float, current: float, target_min: float, target_max: float
) -> tuple[float, float]:
    """GMV is linear in each factor: GMV/day × (target / current − 1) × 30, per bound."""
    if current <= 0:
        return 0.0, 0.0
    low = gmv_per_day * max(target_min / current - 1, 0.0) * DAYS_PER_MONTH
    high = gmv_per_day * max(target_max / current - 1, 0.0) * DAYS_PER_MONTH
    return low, high


__all__ = [
    "FLEET_ALL_LEVERS",
    "MIN_SHOP_RESULTS",
    "PRIOR_LIFT",
    "SHRINKAGE_K",
    "CalibrationStats",
    "Prediction",
    "blended_factor",
    "calibration_factor",
    "fleet_stats_for",
    "gap_bucket",
    "gmv_range_per_month",
    "predict",
    "prior_lift",
]
