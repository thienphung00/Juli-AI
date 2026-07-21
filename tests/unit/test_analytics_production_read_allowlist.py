"""TDD: production-read allowlist for Analytics + Promotion GET paths (#424)."""

from __future__ import annotations

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    is_production_read_allowed,
    path_contains_write_marker,
)
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)

# Verified wire set — A-25, A-31–A-34, A-36–A-39 (not LIVE A-26–A-29 / A-30 / A-35).
_ALLOWED_GET_CASES = [
    (
        "A-32",
        ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    ),
    (
        "A-31",
        analytics_shop_sku_performance_path("1736404513645233795"),
    ),
    (
        "A-34",
        ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ),
    (
        "A-33",
        analytics_shop_product_performance_path("1736363193934775939"),
    ),
    (
        "A-36",
        ANALYTICS_SHOP_PERFORMANCE_PATH,
    ),
    (
        "A-37",
        analytics_shop_performance_per_hour_path("2026-07-13"),
    ),
    (
        "A-38",
        ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ),
    (
        "A-39",
        ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ),
    (
        "A-25",
        promotion_activity_path("7402881377634567979"),
    ),
]

_REJECTED_CASES = [
    ("POST analytics list", "POST", ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH),
    ("PUT analytics list", "PUT", ANALYTICS_SHOP_PERFORMANCE_PATH),
    (
        "LIVE A-26 minute performance",
        "GET",
        "/analytics/202510/shop_lives/abc123/performance_per_minutes",
    ),
    (
        "LIVE A-28 performance list",
        "GET",
        "/analytics/202509/shop_lives/performance",
    ),
    (
        "LIVE A-29 overview",
        "GET",
        "/analytics/202509/shop_lives/overview_performance",
    ),
    (
        "doc-sample A-30",
        "GET",
        "/analytics/202502/live_rooms/room1/core_stats",
    ),
    (
        "doc-sample A-35",
        "GET",
        "/analytics/202502/live_rooms/room1/gmv_trend_performances",
    ),
    (
        "promotion create write",
        "POST",
        "/promotion/202309/activities",
    ),
]


@pytest.mark.parametrize(
    ("label", "path"),
    _ALLOWED_GET_CASES,
    ids=[label for label, _ in _ALLOWED_GET_CASES],
)
def test_production_read_allowlist_accepts_analytics_get_paths(label: str, path: str):
    assert is_production_read_allowed("GET", path), f"{label}: {path}"
    assert not path_contains_write_marker(path), path


@pytest.mark.parametrize(
    ("label", "method", "path"),
    _REJECTED_CASES,
    ids=[label for label, _, _ in _REJECTED_CASES],
)
def test_production_read_allowlist_rejects_non_allowlisted(
    label: str,
    method: str,
    path: str,
):
    assert not is_production_read_allowed(method, path), f"{label}: {method} {path}"
