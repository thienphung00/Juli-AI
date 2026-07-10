"""Deterministic rules-based seller lifecycle classifier."""

from __future__ import annotations

from typing import Literal, TypedDict

from juli_backend.ai.seller_stage.thresholds import (
    AD_SPEND_GROWTH_MIN_VND,
    ORDER_COUNT_GROWTH_MIN,
    ORDER_COUNT_NEW_MAX,
    RETURN_RATE_LEAKAGE_MIN,
    SHOP_AGE_NEW_MAX_DAYS,
)

SellerStage = Literal["new", "leakage", "growth"]


class SellerStageProfile(TypedDict):
    shop_age_days: int
    order_count_30d: int
    return_rate_30d: float
    ad_spend_30d_vnd: float


def classify_seller_stage(profile: SellerStageProfile) -> SellerStage:
    """Priority: leakage → new → growth (matches Phase 1 TypeScript router)."""
    shop_age_days = profile["shop_age_days"]
    order_count_30d = profile["order_count_30d"]
    return_rate_30d = profile["return_rate_30d"]
    ad_spend_30d_vnd = profile["ad_spend_30d_vnd"]

    if return_rate_30d >= RETURN_RATE_LEAKAGE_MIN and order_count_30d > ORDER_COUNT_NEW_MAX:
        return "leakage"

    if order_count_30d <= ORDER_COUNT_NEW_MAX or (
        shop_age_days <= SHOP_AGE_NEW_MAX_DAYS and order_count_30d < ORDER_COUNT_GROWTH_MIN
    ):
        return "new"

    if order_count_30d >= ORDER_COUNT_GROWTH_MIN and ad_spend_30d_vnd >= AD_SPEND_GROWTH_MIN_VND:
        return "growth"

    return "growth"
