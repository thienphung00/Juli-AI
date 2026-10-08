"""Per-video last-30 / prior-30 metrics (fast track P8-B, AC-8.2). Fake TikTok resources only."""

from __future__ import annotations

import inspect
import json
import re
from datetime import date, timedelta
from typing import Any

import pytest

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
    analytics_shop_video_performance_path,
)
from juli_backend.services.shop_diagnosis.snapshot import Snapshot
from juli_backend.services.shop_diagnosis_daily import video_windows
from juli_backend.services.shop_diagnosis_daily.pacing import ENDPOINTS, RateLimitedResources
from juli_backend.services.shop_diagnosis_daily.video_windows import (
    DATE_RANGE,
    POSTED_IN_WINDOW,
    fetch_video_windows,
)

END = date(2026, 10, 6)
LAST_FIRST = END - timedelta(days=29)  # 2026-09-07
PRIOR_FIRST = END - timedelta(days=59)  # 2026-08-08
PRIOR_LAST = LAST_FIRST - timedelta(days=1)


def _money(value: float) -> dict[str, str]:
    return {"amount": f"{value:.2f}", "currency": "VND"}


def _listed(video_id: str, gmv: float, sku_orders: int, posted: str = "2025-01-01 10:00:00"):
    return {
        "id": video_id,
        "title": f"Video {video_id}",
        "video_post_time": posted,
        "gmv": _money(gmv),
        "sku_orders": sku_orders,
        "views": 1000,
        "items_sold": sku_orders,
        "click_through_rate": "0.05",
    }


def _interval(day: date, impressions: int, clicks: int, gmv: float, views: int = 100):
    return {
        "start_date": day.isoformat(),
        "end_date": (day + timedelta(days=1)).isoformat(),
        "sales": {
            "overall": {
                "product_impressions": impressions,
                "product_clicks": clicks,
                "ctr": "0.9999",  # decoy: CTR is recomputed from the sums
                "gmv": _money(gmv),
                "items_sold": 1,
            }
        },
        "traffic": {"views": views},
    }


class FakeVideoResources:
    """Shop video list per window + per-day details; records every call."""

    def __init__(
        self,
        *,
        last: list[dict],
        prior: list[dict],
        list_error: Exception | None = None,
        details_error: dict[str, Exception] | None = None,
        throttle_once: set[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        outer = self

        class Analytics:
            def list_video_performance_all(self, **kwargs: str):
                outer.calls.append(("list", kwargs))
                if list_error is not None:
                    raise list_error
                return last if kwargs["start_date_ge"] == LAST_FIRST.isoformat() else prior

            def get_video_performance(self, **kwargs: str):
                outer.calls.append(("details", kwargs))
                video_id = kwargs["video_id"]
                if throttle_once and video_id in throttle_once:
                    throttle_once.discard(video_id)
                    raise RuntimeError("Too many requests")
                if details_error and video_id in details_error:
                    raise details_error[video_id]
                first = date.fromisoformat(kwargs["start_date_ge"])
                stop = date.fromisoformat(kwargs["end_date_lt"])
                days = [first + timedelta(days=i) for i in range((stop - first).days)]
                # 10 impressions / 1 click / 1,000 ₫ per day in the prior window,
                # 20 / 3 / 2,000 in the last one; one stray day after the end.
                rows = [
                    _interval(d, 20, 3, 2000) if d >= LAST_FIRST else _interval(d, 10, 1, 1000)
                    for d in days
                ]
                rows.append(_interval(END + timedelta(days=1), 99_999, 9_999, 9e9))
                return {
                    "latest_available_date": END.isoformat(),
                    "performance": {"intervals": rows},
                }

        self.analytics = Analytics()

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [kwargs for k, kwargs in self.calls if k == kind]


def _snapshot(videos: list[dict] | None = None, video_products: dict | None = None) -> Snapshot:
    return Snapshot(
        shop_name="Shop Thử Nghiệm",
        end=END,
        daily={},
        videos=videos or [],
        video_products=video_products or {},
    )


def _fetch(resources: Any, snapshot: Snapshot | None = None, **kwargs: Any):
    kwargs.setdefault("sleep_s", 0)
    kwargs.setdefault("backoff_sleep", lambda _s: None)
    return fetch_video_windows(resources, snapshot or _snapshot(), **kwargs)


def test_date_range_path_splits_one_daily_details_call_into_the_two_windows():
    resources = FakeVideoResources(
        last=[_listed("v1", 60_000, 12)],
        prior=[_listed("v1", 30_000, 4), _listed("v2", 10_000, 2)],
    )

    result = _fetch(resources)

    assert result.basis == DATE_RANGE
    assert result.last_window == (LAST_FIRST, END)
    assert result.prior_window == (PRIOR_FIRST, PRIOR_LAST)
    # Each window's list is asked for its own dates (end exclusive).
    assert [(c["start_date_ge"], c["end_date_lt"]) for c in resources.of("list")] == [
        ("2026-09-07", "2026-10-07"),
        ("2026-08-08", "2026-09-07"),
    ]
    details = resources.of("details")
    assert [c["video_id"] for c in details] == ["v1", "v2"]
    assert details[0]["granularity"] == "1D"
    assert (details[0]["start_date_ge"], details[0]["end_date_lt"]) == ("2026-08-08", "2026-10-07")
    assert result.calls == 4

    v1 = {row.video_id: row for row in result.videos}["v1"]
    assert v1.title == "Video v1" and v1.posted_at is not None and v1.basis == DATE_RANGE
    assert v1.last is not None and v1.prior is not None
    # 30 days each; the stray interval after the end is ignored.
    assert (v1.last.product_impressions, v1.last.product_clicks) == (600, 90)
    assert (v1.prior.product_impressions, v1.prior.product_clicks) == (300, 30)
    assert v1.last.gmv == 60_000 and v1.prior.gmv == 30_000
    assert v1.last.views == 3000
    assert v1.last.ctr == pytest.approx(0.15) and v1.prior.ctr == pytest.approx(0.1)
    # SKU orders come from each window's list.
    assert (v1.last.sku_orders, v1.prior.sku_orders) == (12, 4)
    v2 = {row.video_id: row for row in result.videos}["v2"]
    assert v2.last is not None and v2.last.sku_orders == 0  # not in the last window's list

    json.dumps(result.to_dict())  # storable as JSON


def test_fallback_when_the_list_is_refused_uses_videos_posted_in_each_window():
    snapshot = _snapshot(
        videos=[
            _listed("new", 50_000, 5, posted="2026-09-20 09:00:00"),
            _listed("mid", 20_000, 2, posted="2026-08-15 18:30:00"),
            _listed("old", 90_000, 9, posted="2025-10-28 13:28:37"),
            _listed("noposttime", 1_000, 1, posted=""),
        ],
        video_products={
            "new": {"products": [{"product_impressions": 800, "product_clicks": 40}]},
            "mid": {"products": [{"id": "p", "gmv": _money(1)}]},  # no impressions
        },
    )
    resources = FakeVideoResources(
        last=[], prior=[], list_error=RuntimeError("access_token=abcdefghijkl scope denied")
    )

    result = _fetch(resources, snapshot)

    assert result.basis == POSTED_IN_WINDOW
    assert resources.of("details") == []
    assert result.calls == 1
    assert result.fallback_reason is not None
    assert "abcdefghijkl" not in result.fallback_reason["message"]
    rows = {row.video_id: row for row in result.videos}
    assert set(rows) == {"new", "mid"}  # "old" was posted before both windows
    assert rows["new"].prior is None and rows["new"].last is not None
    assert rows["new"].last.product_impressions == 800 and rows["new"].last.ctr == 0.05
    assert rows["new"].last.gmv == 50_000 and rows["new"].last.sku_orders == 5
    assert rows["mid"].last is None and rows["mid"].prior is not None
    assert rows["mid"].prior.product_impressions is None and rows["mid"].prior.ctr is None
    assert all(row.basis == POSTED_IN_WINDOW for row in result.videos)
    json.dumps(result.to_dict())


def test_a_refused_first_details_call_falls_back_without_further_calls():
    snapshot = _snapshot(videos=[_listed("v1", 1, 1, posted="2026-10-01 08:00:00")])
    resources = FakeVideoResources(
        last=[_listed("v1", 9, 1), _listed("v2", 8, 1)],
        prior=[],
        details_error={"v1": RuntimeError("no permission for this API")},
    )

    result = _fetch(resources, snapshot)

    assert result.basis == POSTED_IN_WINDOW
    assert len(resources.of("details")) == 1
    assert [row.video_id for row in result.videos] == ["v1"]


def test_a_later_failed_video_is_left_out_and_recorded():
    resources = FakeVideoResources(
        last=[_listed("v1", 9, 1), _listed("v2", 8, 1), _listed("v3", 7, 1)],
        prior=[],
        details_error={"v2": RuntimeError("video not found")},
    )

    result = _fetch(resources)

    assert result.basis == DATE_RANGE
    assert [row.video_id for row in result.videos] == ["v1", "v3"]
    assert result.failed_video_ids == ("v2",)


def test_details_calls_are_capped_per_window_by_gmv_and_deduplicated():
    last = [_listed(f"L{i}", 1000 - i, 1) for i in range(30)]
    prior = [_listed(f"P{i}", 500 - i, 1) for i in range(30)] + [_listed("L0", 999_999, 1)]
    resources = FakeVideoResources(last=last, prior=prior)

    result = _fetch(resources, max_videos_per_window=5)

    called = [c["video_id"] for c in resources.of("details")]
    # Top 5 by GMV of each window; L0 is top of both and fetched once.
    assert called == ["L0", "L1", "L2", "L3", "L4", "P0", "P1", "P2", "P3"]
    assert len(called) <= 2 * 5
    assert result.max_videos_per_window == 5
    assert result.calls == 2 + len(called)


def test_default_budget_is_at_most_two_lists_and_forty_details_calls():
    last = [_listed(f"L{i}", 1000 - i, 1) for i in range(100)]
    prior = [_listed(f"P{i}", 1000 - i, 1) for i in range(100)]
    resources = FakeVideoResources(last=last, prior=prior)

    result = _fetch(resources)

    assert len(resources.of("list")) == 2
    assert len(resources.of("details")) == 2 * video_windows.MAX_VIDEOS_PER_WINDOW == 40
    assert result.calls == 42


def test_every_read_takes_a_token_on_the_polls_endpoint_key_and_429s_back_off():
    gated: list[str] = []
    backoffs: list[float] = []
    inner = FakeVideoResources(
        last=[_listed("v1", 9, 1), _listed("v2", 8, 1)], prior=[], throttle_once={"v2"}
    )

    result = _fetch(RateLimitedResources(inner, gated.append), backoff_sleep=backoffs.append)

    assert result.basis == DATE_RANGE and len(result.videos) == 2
    assert gated == [
        ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
        ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH,
        analytics_shop_video_performance_path("v1"),
        analytics_shop_video_performance_path("v2"),
        analytics_shop_video_performance_path("v2"),  # the retry takes its own token
    ]
    assert backoffs == [2.0]


def test_every_tiktok_method_the_module_calls_is_gated():
    called = set(re.findall(r"resources\.(analytics)\.(\w+)", inspect.getsource(video_windows)))
    assert called == {
        ("analytics", "list_video_performance_all"),
        ("analytics", "get_video_performance"),
    }
    assert called <= set(ENDPOINTS)
