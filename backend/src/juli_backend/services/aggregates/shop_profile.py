"""Rules-based shop profile classifier (P2-A3).

Ported from apps/dashboard/src/lib/operations/classification.ts — reference only.
"""

from __future__ import annotations

from juli_backend.services.aggregates.thresholds import (
    GMV_METRICS_MIN_COUNT,
    SHOP_AGE_MID_LARGE_MIN_DAYS,
)
from juli_backend.services.aggregates.types import ShopProfile, ShopProfileSignals


def _has_active_probation(signals: ShopProfileSignals) -> bool:
    return signals.probation_status == "active"


def _has_met_graduation_requirements(signals: ShopProfileSignals) -> bool:
    if _has_active_probation(signals):
        return False

    if signals.probation_status in ("graduated", "not_applicable"):
        if (
            signals.sps_current is None
            or signals.sps_threshold is None
            or signals.ahr_current is None
            or signals.ahr_threshold is None
        ):
            return True

    if (
        signals.sps_current is not None
        and signals.sps_threshold is not None
        and signals.ahr_current is not None
        and signals.ahr_threshold is not None
    ):
        return (
            signals.sps_current >= signals.sps_threshold
            and signals.ahr_current >= signals.ahr_threshold
        )

    return signals.probation_status in ("graduated", "not_applicable")


def _count_gmv_metrics_tracked(signals: ShopProfileSignals) -> int:
    count = 0
    if signals.product_gmv_total > 0:
        count += 1
    if signals.ad_revenue_total > 0:
        count += 1
    if signals.product_units_sold_total > 0:
        count += 1
    if signals.ad_spend_total > 0:
        count += 1
    return count


def _qualifies_as_mid_large_shop(signals: ShopProfileSignals) -> bool:
    if not _has_met_graduation_requirements(signals):
        return False

    if signals.shop_age_days >= SHOP_AGE_MID_LARGE_MIN_DAYS:
        return True

    return _count_gmv_metrics_tracked(signals) >= GMV_METRICS_MIN_COUNT


def classify_shop_profile(signals: ShopProfileSignals) -> ShopProfile:
    if _qualifies_as_mid_large_shop(signals):
        return ShopProfile.MID_LARGE_SHOP
    return ShopProfile.NEW_SHOP
