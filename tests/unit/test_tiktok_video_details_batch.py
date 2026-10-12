"""Get Shop Video Performance Details 202509 -> Get Shop Videos Performance Details 202609.

Analytics changelog 2026-09-28: the single-video details API retires no later than
2026-12-28. ``AnalyticsResource.get_video_performance`` reads the batch API and
returns the old ``data`` shape; on a scope refusal it falls back to the old API
until the retirement date. Fixtures follow the documented response shapes
(``infra/apiwatch/snapshots/tiktok.json``); every value is synthetic.
"""

from __future__ import annotations

import copy
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest

from juli_backend.integrations import schema_drift
from juli_backend.integrations.tiktok.capabilities import is_production_read_allowed
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH,
    analytics_shop_video_performance_path,
)
from juli_backend.integrations.tiktok.exceptions import PermissionDeniedError, TikTokAPIError
from juli_backend.integrations.tiktok.resources import analytics as analytics_mod
from juli_backend.integrations.tiktok.resources.analytics import (
    FALLBACK_EVENT,
    VIDEO_DETAILS_FALLBACK_LOGGED,
    AnalyticsResource,
    VideoPerformanceError,
    legacy_video_details,
)
from juli_backend.integrations.tiktok.schema_expectations import expectation_for
from juli_backend.services.shop_diagnosis_daily.video_windows import _sum_intervals

ROOT = Path(__file__).resolve().parents[2]
LEGACY_PATH = analytics_shop_video_performance_path("7000000000000000001")


def _interval(day: str, nxt: str, impressions: int, clicks: int, gmv: str, views: int) -> dict:
    return {
        "start_date": day,
        "end_date": nxt,
        "sales": {
            "overall": {
                "ctr": "0.05",
                "customers": 3,
                "gmv": {"amount": gmv, "currency": "VND"},
                "gpm": {"amount": "1000", "currency": "VND"},
                "items_sold": 4,
                "product_clicks": clicks,
                "product_impressions": impressions,
            }
        },
        "traffic": {"comments": 1, "likes": 2, "new_followers": 0, "shares": 1, "views": views},
    }


INTERVALS = [
    _interval("2026-09-01", "2026-09-02", 1000, 50, "150000", 4000),
    _interval("2026-09-02", "2026-09-03", 800, 40, "90000", 3000),
]
VIEWER_PROFILE = [
    {
        "type": "VIEWERS",
        "age_distribution": [{"age": "25-34", "percentage": "0.4"}],
        "country_distribution": [{"country_code": "VN", "percentage": "1.0"}],
        "gender_distribution": [{"gender": "FEMALE", "percentage": "0.7"}],
    }
]

#: Get Shop Video Performance Details 202509 ``data`` (the shape downstream reads).
LEGACY_DATA = {
    "latest_available_date": "2026-09-02",
    "performance": {"intervals": copy.deepcopy(INTERVALS), "viewer_profile": VIEWER_PROFILE},
}

#: Get Shop Videos Performance Details 202609 ``data``: one answered video, one refused.
BATCH_DATA = {
    "latest_available_date": "2026-09-02",
    "videos": [
        {
            "video_id": "7000000000000000001",
            "video": {
                "id": "7000000000000000001",
                "title": "synthetic title",
                "username": "synthetic_shop",
                "duration": 15,
                "video_post_time": "1756684800",
                "thumbnail_url": "https://example.invalid/t.jpg",
                "play_url": "https://example.invalid/v.mp4",
            },
            "performance": {
                "intervals": copy.deepcopy(INTERVALS),
                "viewer_profile": VIEWER_PROFILE,
            },
        },
        {
            "video_id": "7000000000000000002",
            "error": {"code": "300001", "message": "Invalid video ID."},
        },
    ],
}


class _Client:
    """Answers per path: a dict is returned, an exception is raised."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, path: str, params: dict[str, str] | None = None, **_: Any) -> dict[str, Any]:
        self.calls.append((path, dict(params or {})))
        answer = self.answers[path]
        if isinstance(answer, BaseException):
            raise answer
        return copy.deepcopy(answer)


def _resource(answers: dict[str, Any]) -> tuple[AnalyticsResource, _Client]:
    client = _Client(answers)
    return AnalyticsResource(cast(TikTokClient, client)), client


def _get(resource: AnalyticsResource, video_id: str, *, today: date = date(2026, 10, 12)):
    return resource.get_video_performance(
        video_id=video_id,
        start_date_ge="2026-09-01",
        end_date_lt="2026-09-03",
        today=lambda: today,
    )


@pytest.fixture(autouse=True)
def _fresh_flags():
    VIDEO_DETAILS_FALLBACK_LOGGED.reset()
    schema_drift.reset_seen()
    yield
    VIDEO_DETAILS_FALLBACK_LOGGED.reset()
    schema_drift.reset_seen()


def test_batch_row_is_reshaped_to_the_legacy_details_data() -> None:
    assert legacy_video_details(BATCH_DATA, "7000000000000000001") == LEGACY_DATA


def test_downstream_window_sums_are_identical_for_old_and_new_shapes() -> None:
    new = legacy_video_details(BATCH_DATA, "7000000000000000001")
    first, last = date(2026, 9, 1), date(2026, 9, 2)
    assert _sum_intervals(new, first, last) == _sum_intervals(LEGACY_DATA, first, last)
    summed = _sum_intervals(new, first, last)
    assert (summed.product_impressions, summed.product_clicks, summed.views) == (1800, 90, 7000)
    assert summed.gmv == 240000.0


def test_get_video_performance_calls_the_batch_api_with_one_id() -> None:
    resource, client = _resource({ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH: BATCH_DATA})
    assert _get(resource, "7000000000000000001") == LEGACY_DATA
    [(path, params)] = client.calls
    assert path == ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH
    assert params["video_ids"] == "[7000000000000000001]"
    assert params["granularity"] == "1D"
    assert (params["start_date_ge"], params["end_date_lt"]) == ("2026-09-01", "2026-09-03")


def test_a_per_video_error_is_raised_for_that_video_only() -> None:
    resource, _client = _resource({ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH: BATCH_DATA})
    with pytest.raises(VideoPerformanceError) as info:
        _get(resource, "7000000000000000002")
    assert info.value.code == 300001
    with pytest.raises(VideoPerformanceError):
        _get(resource, "7000000000000000009")  # not in the batch answer at all


@pytest.mark.parametrize(
    "refusal",
    [
        PermissionDeniedError(code=100003, message="permission denied"),
        TikTokAPIError(code=105005, message="Access denied. ... required access scope"),
    ],
    ids=["permission", "scope"],
)
def test_scope_refusal_falls_back_to_the_legacy_api_logging_once(refusal, caplog) -> None:
    resource, client = _resource(
        {ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH: refusal, LEGACY_PATH: LEGACY_DATA}
    )
    with caplog.at_level(logging.WARNING, logger=analytics_mod.logger.name):
        assert _get(resource, "7000000000000000001") == LEGACY_DATA
        assert _get(resource, "7000000000000000001") == LEGACY_DATA
    assert [c[0] for c in client.calls] == [
        ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH,
        LEGACY_PATH,
        ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH,
        LEGACY_PATH,
    ]
    assert client.calls[1][1]["version"] == "202509"
    fallbacks = [r for r in caplog.records if r.getMessage() == FALLBACK_EVENT]
    assert len(fallbacks) == 1
    record = fallbacks[0]
    assert record.__dict__["fallback_until"] == "2026-12-28"
    assert record.__dict__["error_code"] == refusal.code


def test_no_fallback_after_the_retirement_date() -> None:
    refusal = PermissionDeniedError(code=100003, message="permission denied")
    resource, client = _resource(
        {ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH: refusal, LEGACY_PATH: LEGACY_DATA}
    )
    assert _get(resource, "7000000000000000001", today=date(2026, 12, 28)) == LEGACY_DATA
    with pytest.raises(PermissionDeniedError):
        _get(resource, "7000000000000000001", today=date(2026, 12, 29))
    assert client.calls[-1][0] == ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH


def test_other_errors_do_not_fall_back() -> None:
    bad_params = TikTokAPIError(code=28001022, message="invalid request params")
    resource, client = _resource(
        {ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH: bad_params, LEGACY_PATH: LEGACY_DATA}
    )
    with pytest.raises(TikTokAPIError):
        _get(resource, "7000000000000000001")
    assert [c[0] for c in client.calls] == [ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH]


def test_batch_rejects_an_empty_or_oversized_id_list() -> None:
    resource, client = _resource({})
    for ids in ([], [str(i) for i in range(501)]):
        with pytest.raises(ValueError):
            resource.get_videos_performance(
                video_ids=ids, start_date_ge="2026-09-01", end_date_lt="2026-09-03"
            )
    assert client.calls == []


def test_batch_and_legacy_paths_are_production_reads() -> None:
    assert ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH == (
        "/analytics/202609/shop_videos/batch_performance"
    )
    assert is_production_read_allowed("GET", ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH)
    assert not is_production_read_allowed("POST", ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH)
    assert LEGACY_PATH == "/analytics/202509/shop_videos/7000000000000000001/performance"
    assert is_production_read_allowed("GET", LEGACY_PATH)


def test_documented_batch_response_has_no_drift(caplog) -> None:
    expectation = expectation_for("GET", ANALYTICS_SHOP_VIDEOS_BATCH_PERFORMANCE_PATH)
    assert expectation is not None
    assert expectation.label == "shop videos performance details"
    missing, unexpected = schema_drift.find_drift(
        BATCH_DATA, expectation.expected, expectation.documented
    )
    assert (missing, unexpected) == ((), ())
    broken = copy.deepcopy(BATCH_DATA)
    del broken["videos"][0]["performance"]["intervals"][0]["sales"]["overall"]["product_clicks"]
    del broken["videos"][0]["performance"]["intervals"][1]["sales"]["overall"]["product_clicks"]
    missing, _ = schema_drift.find_drift(broken, expectation.expected, expectation.documented)
    assert missing == ("videos[].performance.intervals[].sales.overall.product_clicks",)


def test_apiwatch_usage_tracks_both_video_details_paths() -> None:
    sys.path.insert(0, str(ROOT / "infra" / "apiwatch"))
    try:
        from apiwatch import juli_usage
    finally:
        sys.path.pop(0)
    usage = juli_usage.load(ROOT)["tiktok"]["endpoints"]
    assert "/analytics/202609/shop_videos/batch_performance" in usage
    assert any(
        p.startswith("/analytics/202509/shop_videos/") and p.endswith("}/performance")
        for p in usage
    )
