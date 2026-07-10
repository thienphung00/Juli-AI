"""Golden boundary profiles for rules baseline QA — ported from boundary-fixtures.ts."""

from __future__ import annotations

from typing import TypedDict

from juli_backend.ai.seller_stage.rules import SellerStage, SellerStageProfile


class StageBoundaryFixture(TypedDict):
    id: str
    expected_stage: SellerStage
    profile: SellerStageProfile
    note: str


STAGE_BOUNDARY_FIXTURES: tuple[StageBoundaryFixture, ...] = (
    {
        "id": "boundary-new-max-orders",
        "expected_stage": "new",
        "profile": {
            "shop_age_days": 60,
            "order_count_30d": 15,
            "return_rate_30d": 0.05,
            "ad_spend_30d_vnd": 2_000_000,
        },
        "note": "Exactly at ORDER_COUNT_NEW_MAX (15) — still new",
    },
    {
        "id": "boundary-new-young-shop",
        "expected_stage": "new",
        "profile": {
            "shop_age_days": 45,
            "order_count_30d": 30,
            "return_rate_30d": 0.04,
            "ad_spend_30d_vnd": 1_000_000,
        },
        "note": "At SHOP_AGE_NEW_MAX_DAYS with sub-growth volume",
    },
    {
        "id": "boundary-leakage-return-rate",
        "expected_stage": "leakage",
        "profile": {
            "shop_age_days": 120,
            "order_count_30d": 16,
            "return_rate_30d": 0.1,
            "ad_spend_30d_vnd": 3_000_000,
        },
        "note": "Exactly at RETURN_RATE_LEAKAGE_MIN with established volume",
    },
    {
        "id": "boundary-leakage-above-threshold",
        "expected_stage": "leakage",
        "profile": {
            "shop_age_days": 200,
            "order_count_30d": 91,
            "return_rate_30d": 0.189,
            "ad_spend_30d_vnd": 8_000_000,
        },
        "note": "Just below leakage persona return rate",
    },
    {
        "id": "boundary-growth-orders",
        "expected_stage": "growth",
        "profile": {
            "shop_age_days": 365,
            "order_count_30d": 50,
            "return_rate_30d": 0.04,
            "ad_spend_30d_vnd": 5_000_000,
        },
        "note": "Exactly at ORDER_COUNT_GROWTH_MIN and AD_SPEND_GROWTH_MIN_VND",
    },
    {
        "id": "boundary-not-leakage-below-return",
        "expected_stage": "growth",
        "profile": {
            "shop_age_days": 180,
            "order_count_30d": 80,
            "return_rate_30d": 0.099,
            "ad_spend_30d_vnd": 10_000_000,
        },
        "note": "Just below RETURN_RATE_LEAKAGE_MIN — routes to growth",
    },
)
