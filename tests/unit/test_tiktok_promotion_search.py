"""Promotion and analytics reads added for the traffic-source check (ADR-106 amendment 4)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from juli_backend.integrations.tiktok.capabilities import (
    is_production_read_allowed,
    is_sandbox_write_allowed,
    path_contains_write_marker,
)
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
    PROMOTION_ACTIVITIES_SEARCH_PATH,
    PROMOTION_COUPONS_SEARCH_PATH,
    analytics_shop_live_products_performance_path,
    analytics_shop_video_products_performance_path,
)
from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
from juli_backend.integrations.tiktok.resources.promotion import PromotionResource


class _FakeClient:
    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.pages = list(pages or [])

    def get(self, path: str, params: dict[str, str] | None = None, **_: Any) -> dict[str, Any]:
        self.calls.append(("GET", path, {"params": params}))
        return {}

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("POST", path, {"body": body, "params": params, **kwargs}))
        return self.pages.pop(0) if self.pages else {}

    def get_all_pages(self, path: str, body: dict[str, Any], **kwargs: Any) -> list[dict]:
        self.calls.append(("POST-ALL", path, {"body": body, **kwargs}))
        return []

    def get_all_pages_get(self, path: str, params: dict[str, str], **kwargs: Any) -> list[dict]:
        self.calls.append(("GET-ALL", path, {"params": params, **kwargs}))
        return []


def _promotion(pages: list[dict[str, Any]] | None = None) -> tuple[PromotionResource, _FakeClient]:
    client = _FakeClient(pages)
    return PromotionResource(cast(TikTokClient, client)), client


def _analytics() -> tuple[AnalyticsResource, _FakeClient]:
    client = _FakeClient()
    return AnalyticsResource(cast(TikTokClient, client)), client


def test_exact_search_paths() -> None:
    assert PROMOTION_ACTIVITIES_SEARCH_PATH == "/promotion/202309/activities/search"
    assert PROMOTION_COUPONS_SEARCH_PATH == "/promotion/202406/coupons/search"


@pytest.mark.parametrize("path", [PROMOTION_ACTIVITIES_SEARCH_PATH, PROMOTION_COUPONS_SEARCH_PATH])
def test_searches_are_allowed_reads_on_both_transports(path: str) -> None:
    assert is_production_read_allowed("POST", path)
    assert is_sandbox_write_allowed("POST", path)
    assert not path_contains_write_marker(path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/promotion/202309/activities"),
        ("PUT", PROMOTION_ACTIVITIES_SEARCH_PATH),
        ("DELETE", PROMOTION_COUPONS_SEARCH_PATH),
        ("POST", "/promotion/202309/coupons/search"),
        ("POST", "/promotion/202406/activities/search"),
        ("POST", "/promotion/202309/activities/search/extra"),
        ("POST", "/promotion/202309/activities/123/deactivate"),
        ("POST", "/promotion/202406/coupons/123"),
    ],
)
def test_neighbouring_promotion_paths_stay_rejected(method: str, path: str) -> None:
    assert not is_production_read_allowed(method, path)


def test_sandbox_rejects_neighbouring_promotion_paths() -> None:
    assert not is_sandbox_write_allowed("POST", "/promotion/202309/coupons/search")
    assert not is_sandbox_write_allowed("POST", "/promotion/202406/activities/search")


def test_search_activities_body_carries_filters_and_cursor() -> None:
    resource, client = _promotion()
    resource.search_activities(status="ONGOING", activity_type="FLASHSALE", page_size=100)
    [(method, path, kwargs)] = client.calls
    assert (method, path) == ("POST", PROMOTION_ACTIVITIES_SEARCH_PATH)
    assert kwargs["body"] == {"status": "ONGOING", "activity_type": "FLASHSALE", "page_size": 100}
    assert kwargs["retry_transient"] is True


@pytest.mark.parametrize("size", [0, 101])
def test_search_page_size_is_bounded(size: int) -> None:
    resource, client = _promotion()
    with pytest.raises(ValueError):
        resource.search_activities(page_size=size)
    with pytest.raises(ValueError):
        resource.search_coupons(page_size=size)
    assert client.calls == []


def test_search_activities_all_follows_the_body_cursor() -> None:
    resource, client = _promotion(
        [
            {"activities": [{"id": "1"}], "next_page_token": "t2"},
            {"activities": [{"id": "2"}], "next_page_token": ""},
        ]
    )
    got = resource.search_activities_all(status="EXPIRED")
    assert [a["id"] for a in got] == ["1", "2"]
    assert [c[2]["body"].get("page_token") for c in client.calls] == [None, "t2"]
    assert all(c[2]["body"]["status"] == "EXPIRED" for c in client.calls)


def test_search_activities_all_stops_at_the_page_cap() -> None:
    pages = [{"activities": [{"id": str(i)}], "next_page_token": "again"} for i in range(5)]
    resource, client = _promotion(pages)
    assert len(resource.search_activities_all(max_pages=3)) == 3
    assert len(client.calls) == 3


def test_search_coupons_pages_in_the_query_string() -> None:
    resource, client = _promotion()
    resource.search_coupons(status=["ONGOING"], page_size=20, page_token="abc")
    [(_, path, kwargs)] = client.calls
    assert path == PROMOTION_COUPONS_SEARCH_PATH
    assert kwargs["params"] == {"page_size": "20", "page_token": "abc"}
    assert kwargs["body"] == {"status": ["ONGOING"]}


def test_search_coupons_all_uses_the_budgeted_paginator() -> None:
    resource, client = _promotion()
    resource.search_coupons_all(status=["ONGOING", "EXPIRED"])
    [(kind, path, kwargs)] = client.calls
    assert (kind, path) == ("POST-ALL", PROMOTION_COUPONS_SEARCH_PATH)
    assert kwargs["items_key"] == "coupons"
    assert kwargs["body"] == {"status": ["ONGOING", "EXPIRED"]}


def test_analytics_paths_for_video_and_live_products() -> None:
    video = analytics_shop_video_products_performance_path("v1")
    live = analytics_shop_live_products_performance_path("l1")
    assert video == "/analytics/202509/shop_videos/v1/products/performance"
    assert live == "/analytics/202512/shop/l1/products_performance"
    for path in (ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH, video, live):
        assert is_production_read_allowed("GET", path)
        assert not is_production_read_allowed("POST", path)
        assert not path_contains_write_marker(path)
    assert not is_production_read_allowed("GET", "/analytics/202512/shop/l1/other")
    assert not is_production_read_allowed("GET", "/analytics/202509/shop_videos/v1/products")


def test_analytics_resource_request_shapes() -> None:
    resource, client = _analytics()
    resource.list_video_performance_all(start_date_ge="2026-09-06", end_date_lt="2026-10-06")
    resource.get_video_products_performance(
        video_id="v1", start_date_ge="2026-09-06", end_date_lt="2026-10-06"
    )
    resource.get_live_products_performance(live_id="l1")
    (listing, video, live) = client.calls
    assert listing[1] == ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH
    assert listing[2]["params"]["sort_field"] == "gmv" and listing[2]["items_key"] == "videos"
    assert video[1] == analytics_shop_video_products_performance_path("v1")
    assert video[2]["params"]["start_date_ge"] == "2026-09-06"
    assert live[1] == analytics_shop_live_products_performance_path("l1")


def test_video_performance_details_is_a_production_read_get_only() -> None:
    from juli_backend.integrations.tiktok.constants import analytics_shop_video_performance_path

    path = analytics_shop_video_performance_path("v1")
    assert path == "/analytics/202509/shop_videos/v1/performance"
    assert is_production_read_allowed("GET", path)
    assert not is_production_read_allowed("POST", path)
    assert not path_contains_write_marker(path)
    assert not is_production_read_allowed("GET", "/analytics/202509/shop_videos/v1/x/performance")


def test_video_performance_details_asks_for_daily_intervals() -> None:
    from juli_backend.integrations.tiktok.constants import analytics_shop_video_performance_path

    resource, client = _analytics()
    resource.get_video_performance(
        video_id="v1", start_date_ge="2026-08-08", end_date_lt="2026-10-07"
    )
    [(kind, path, kwargs)] = client.calls
    assert (kind, path) == ("GET", analytics_shop_video_performance_path("v1"))
    assert kwargs["params"]["granularity"] == "1D"
    assert kwargs["params"]["start_date_ge"] == "2026-08-08"
    assert kwargs["params"]["end_date_lt"] == "2026-10-07"
