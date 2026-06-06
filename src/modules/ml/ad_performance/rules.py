"""Rules for deriving scale/cut/hold labels from campaign features."""

from __future__ import annotations

from typing import Any

from src.modules.ml.ad_performance.thresholds import (
    CUT_ROAS_RATIO,
    SCALE_ROAS_RATIO,
    SPARSE_HISTORY_MIN_CLICKS,
    SPARSE_HISTORY_MIN_CONVERSIONS,
    SPARSE_HISTORY_MIN_IMPRESSIONS,
)
from src.modules.ml.ad_performance.types import AdAction


def is_sparse_ad_history(features: dict[str, Any]) -> bool:
    """Return True when campaign history is too thin for confident recommendations."""
    impressions = int(features.get("impressions") or 0)
    clicks = int(features.get("clicks") or 0)
    conversions = int(features.get("conversions") or 0)
    return (
        impressions < SPARSE_HISTORY_MIN_IMPRESSIONS
        or clicks < SPARSE_HISTORY_MIN_CLICKS
        or conversions < SPARSE_HISTORY_MIN_CONVERSIONS
    )


def derive_ad_action(features: dict[str, Any]) -> AdAction:
    """Derive scale/cut/hold from ROAS vs account baseline — used for training labels."""
    if is_sparse_ad_history(features):
        return "hold"

    roas = float(features.get("roas") or 0.0)
    account_avg = float(features.get("account_avg_roas_30d") or 0.0)
    if account_avg <= 0:
        return "hold"

    if roas >= account_avg * SCALE_ROAS_RATIO:
        return "scale"
    if roas <= account_avg * CUT_ROAS_RATIO:
        return "cut"
    return "hold"
