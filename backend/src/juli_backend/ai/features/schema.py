"""Authoritative feature column names — must match feature-store-schema.md."""

from __future__ import annotations

# Group A — anomaly detector (inference signature order)
ANOMALY_FEATURE_COLUMNS: tuple[str, ...] = (
    "buyer_return_count_30d",
    "buyer_item_swap_count_30d",
    "buyer_empty_return_count_30d",
    "buyer_repeat_anomaly_flag",
    "return_rate_30d",
    "seller_fault_cancel_rate_30d",
)

# Shop-level seller stage classifier inputs (Phase 1 profile alignment)
SELLER_STAGE_FEATURE_COLUMNS: tuple[str, ...] = (
    "shop_age_days",
    "order_count_30d",
    "return_rate_30d",
    "ad_spend_30d_vnd",
    "gmv_30d_vnd",
)

# Campaign/day ad performance features + account baselines
AD_FEATURE_COLUMNS: tuple[str, ...] = (
    "spend_vnd",
    "roas",
    "cpc_vnd",
    "conversions",
    "impressions",
    "clicks",
    "account_avg_roas_30d",
    "account_spend_velocity_30d",
)

FORBIDDEN_ANOMALY_INPUT_COLUMNS: frozenset[str] = frozenset(
    {
        "creator_id",
        "affiliate_id",
        "creator_efficiency_score",
        "creator_commission_pending_rate",
        "gmv_generated",
        "follower_count",
        "commission_rate",
        "affiliate_commission",
    }
)

FORBIDDEN_ANOMALY_INPUT_PREFIXES: tuple[str, ...] = ("affiliate_", "creator_")
