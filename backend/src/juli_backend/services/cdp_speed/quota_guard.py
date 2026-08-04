"""Quota guards for CDP Speed — block unbounded A-31/A-33 detail + A-38/A-39 bestselling (#629)."""

from __future__ import annotations

# Resources that require quota guard checks on the speed material path.
# A-38/A-39 bestselling: no bronze table, never Demo KPI input.
# A-31/A-33 detail fan-out: unbounded detail loops blocked from routine paths.
QUOTA_GUARDED_RESOURCE_NAMES: frozenset[str] = frozenset(
    {
        # A-38/A-39: bestselling rank analytics (ops-only, not Demo KPI)
        "analytics_bestselling_products",
        "analytics_bestselling_videos",
        # A-31/A-33: unbounded detail fan-out (SKU/product/live detail loops)
        "analytics_sku_details",
        "analytics_product_details",
        "analytics_live_overview",
    }
)

_QUOTA_GUARD_REASONS: dict[str, str] = {
    "analytics_bestselling_products": "bestselling_no_bronze_table",
    "analytics_bestselling_videos": "bestselling_no_bronze_table",
    "analytics_sku_details": "unbounded_detail_fanout",
    "analytics_product_details": "unbounded_detail_fanout",
    "analytics_live_overview": "unbounded_detail_fanout",
}


def is_quota_guarded(resource_name: str) -> bool:
    """Check if a resource name should be guarded (skipped with logged reason)."""
    return resource_name in QUOTA_GUARDED_RESOURCE_NAMES


def quota_guard_reason(resource_name: str) -> str:
    """Return the quota guard reason for a resource name.

    Raises KeyError if the resource is not guarded.
    """
    return _QUOTA_GUARD_REASONS[resource_name]
