"""Issue #629 — CDP Speed Quota Guard contract tests (A-38/A-39 + A-31/A-33).

Quota guards ensure:
1. A-38/A-39 bestselling calls short-circuit with logged reason="quota_guard"
   (no bronze table; never feed Demo KPI)
2. A-31/A-33 detail fan-out is explicitly blocked on routine material paths
"""

from __future__ import annotations

import pytest

from juli_backend.services.cdp_speed.quota_guard import (
    QUOTA_GUARDED_RESOURCE_NAMES,
    is_quota_guarded,
    quota_guard_reason,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FULL_SYNC_ANALYTICS_RESOURCE_NAMES,
)


def test_quota_guarded_resource_names_includes_a38_a39_bestselling():
    """A-38/A-39 bestselling products/videos must be quota guarded."""
    guarded = QUOTA_GUARDED_RESOURCE_NAMES
    assert "analytics_bestselling_products" in guarded
    assert "analytics_bestselling_videos" in guarded


def test_quota_guarded_resource_names_includes_a31_a33_detail_fanout():
    """A-31/A-33 detail analytics must be quota guarded (sku/product/live details)."""
    guarded = QUOTA_GUARDED_RESOURCE_NAMES
    assert "analytics_sku_details" in guarded
    assert "analytics_product_details" in guarded
    assert "analytics_live_overview" in guarded


def test_is_quota_guarded_checks_resource_names():
    """is_quota_guarded returns True for guarded resource names."""
    assert is_quota_guarded("analytics_bestselling_products") is True
    assert is_quota_guarded("analytics_bestselling_videos") is True
    assert is_quota_guarded("analytics_product_details") is True
    assert is_quota_guarded("analytics_sku_details") is True
    assert is_quota_guarded("analytics_live_overview") is True


def test_is_quota_guarded_returns_false_for_unguarded_resources():
    """is_quota_guarded returns False for unguarded resources."""
    assert is_quota_guarded("orders") is False
    assert is_quota_guarded("returns") is False
    assert is_quota_guarded("analytics_shop") is False
    assert is_quota_guarded("analytics_products_list") is False


def test_quota_guard_reason_for_bestselling():
    """quota_guard_reason explains why bestselling is guarded."""
    reason = quota_guard_reason("analytics_bestselling_products")
    assert "bestselling" in reason.lower() or "bronze" in reason.lower()

    reason = quota_guard_reason("analytics_bestselling_videos")
    assert "bestselling" in reason.lower() or "bronze" in reason.lower()


def test_quota_guard_reason_for_detail_resources():
    """quota_guard_reason explains why detail resources are guarded."""
    reason = quota_guard_reason("analytics_product_details")
    assert "detail" in reason.lower() or "unbounded" in reason.lower()

    reason = quota_guard_reason("analytics_sku_details")
    assert "detail" in reason.lower() or "unbounded" in reason.lower()


def test_quota_guard_reason_raises_for_unknown_resource():
    """quota_guard_reason raises KeyError for unknown guarded resource."""
    with pytest.raises(KeyError):
        quota_guard_reason("orders")


def test_guarded_resources_subset_of_forbidden_analytics():
    """All guarded resources should come from forbidden sync_analytics."""
    guarded = QUOTA_GUARDED_RESOURCE_NAMES
    forbidden = FULL_SYNC_ANALYTICS_RESOURCE_NAMES
    assert guarded.issubset(forbidden)


def test_quota_guard_module_has_no_a2_governors():
    """Quota guard must not import A2 batch governors."""
    import juli_backend.services.cdp_speed.quota_guard as module

    source = open(module.__file__, encoding="utf-8").read()
    forbidden = (
        "PostgresIoBudget",
        "FleetDefer",
        "postgres_io_budget",
        "fleet_defer",
        "cdp_batch",
    )
    for token in forbidden:
        assert token not in source
