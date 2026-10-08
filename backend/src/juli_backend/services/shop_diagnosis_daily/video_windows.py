"""Per-video metrics for the last-30 and prior-30 day windows (fast track P8-B, AC-8.2).

ADR-109 d.5 ranks individual videos by the GMV/day their product impressions and
CTR moved. That needs, per video and per 30-day window: product impressions,
product clicks, CTR, SKU orders, GMV (and views). The 60-day video list in the
snapshot (``videos/videos.json``) has one 60-day total per video, not two windows.

**What the Partner API spec says** (``tts-openapi-guide`` bundled OAS,
``references/oas/paths/analytics.json``, version 202509 = ``ANALYTICS_API_VERSION``):

- ``GET /analytics/202509/shop_videos/performance`` (Get Shop Video Performance
  List): ``start_date_ge`` / ``end_date_lt`` are **required**; ``views`` is
  "Number of video views during the selected time range"; rows also carry
  ``sku_orders``, ``gmv``, ``items_sold``, ``video_post_time`` -- but no product
  impressions, and ``click_through_rate`` is product clicks ÷ **video views**.
- ``GET /analytics/202509/shop_videos/{video_id}/performance`` (Get Shop Video
  Performance Details): ``start_date_ge`` / ``end_date_lt`` required and
  ``granularity`` = ``ALL`` | ``1D``; each ``performance.intervals[]`` has its own
  ``start_date`` / ``end_date`` and ``sales.overall.{product_impressions,
  product_clicks, ctr, gmv, items_sold}`` plus ``traffic.views`` -- but no SKU
  orders.
- ``GET .../shop_videos/{video_id}/products/performance``: also date-ranged
  (required); per product GMV and units only in the spec.

So the endpoints ARE date-ranged. The fetch below takes, per window, the list
(SKU orders, GMV, views, title, post time) and, per capped video, ONE details call
over both windows with ``granularity=1D`` that is summed into the two windows
(impressions, clicks, views, GMV). ``basis = "date_range"``.

**Fallback** (``basis = "posted_in_window"``): when a per-window list fails or the
first details call is refused (scope / endpoint not available), no further calls
are made: each window keeps only the videos POSTED inside it, with their 60-day
snapshot totals (impressions / clicks from the snapshot's per-video product file
when present). A prior-window video's totals then include its later days; the
ranking job must treat these rows as approximate.

**Budget.** 2 list walks (``page_size`` 100, usually one page each) plus at most
``max_videos_per_window`` details calls per window, deduplicated across windows
(default 20 → ≤ 40 calls), the same order as the snapshot's 40 per-video product
calls. ADR-109 lists at most 10 rows; videos below the cap fall into the stream's
closing rows, so the top 20 by window GMV (ties: views) per window are enough.
Every call goes through the resources the caller hands in (the job wraps them in
``pacing.RateLimitedResources``) and ``fetch.with_backoff`` (429: 2 s, 4 s, 8 s).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any, Literal

from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows, to_float
from juli_backend.services.shop_diagnosis_daily.fetch import Sleep, error_payload, with_backoff

logger = logging.getLogger(__name__)

Basis = Literal["date_range", "posted_in_window"]
DATE_RANGE: Basis = "date_range"
POSTED_IN_WINDOW: Basis = "posted_in_window"

WINDOW_DAYS = 30
#: Details calls per window (deduplicated across the two windows). See module doc.
MAX_VIDEOS_PER_WINDOW = 20


@dataclass(frozen=True)
class WindowMetrics:
    """One video's totals inside one 30-day window. ``None`` = not available on this basis."""

    views: int | None = None
    product_impressions: int | None = None
    product_clicks: int | None = None
    sku_orders: int | None = None
    gmv: float = 0.0
    items_sold: int | None = None

    @property
    def ctr(self) -> float | None:
        """Product clicks ÷ product impressions (TikTok's video CTR); ``None`` without both."""
        if not self.product_impressions or self.product_clicks is None:
            return None
        return self.product_clicks / self.product_impressions


@dataclass(frozen=True)
class VideoWindowRow:
    video_id: str
    title: str
    #: ``video_post_time`` as TikTok returns it (shop-local, naive), when readable.
    posted_at: datetime | None
    #: ``None`` when the video has no row for that window (fallback: not posted in it).
    last: WindowMetrics | None
    prior: WindowMetrics | None
    basis: Basis


@dataclass(frozen=True)
class VideoWindowMetrics:
    """Per-video 30/30 metrics for the ranking job (ADR-109 d.5, AC-8.2)."""

    end: date
    #: Inclusive local dates ``(first, last)`` of each window.
    last_window: tuple[date, date]
    prior_window: tuple[date, date]
    basis: Basis
    videos: tuple[VideoWindowRow, ...] = ()
    max_videos_per_window: int = MAX_VIDEOS_PER_WINDOW
    calls: int = 0
    #: Why the run fell back to ``posted_in_window`` (class and message, redacted).
    fallback_reason: dict[str, str] | None = None
    #: Videos whose details call failed after the first succeeded (left out).
    failed_video_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for row, data in zip(self.videos, out["videos"], strict=True):
            data["posted_at"] = row.posted_at.isoformat(sep=" ") if row.posted_at else None
            for side in ("last", "prior"):
                metrics = getattr(row, side)
                if metrics is not None:
                    data[side]["ctr"] = metrics.ctr
        out["end"] = self.end.isoformat()
        out["last_window"] = [d.isoformat() for d in self.last_window]
        out["prior_window"] = [d.isoformat() for d in self.prior_window]
        out["failed_video_ids"] = list(self.failed_video_ids)
        return out


def _int(value: Any) -> int:
    return int(to_float(value))


def _posted_at(row: dict) -> datetime | None:
    raw = str(row.get("video_post_time") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("T", " ").removesuffix("Z"))
    except ValueError:
        return None


def _unwrap(payload: Any) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def _top(rows: Iterable[dict], limit: int) -> list[dict]:
    keyed = [r for r in rows if str(r.get("id") or "")]
    keyed.sort(key=lambda r: (to_float(r.get("gmv")), to_float(r.get("views"))), reverse=True)
    return keyed[:limit]


def _sum_intervals(payload: Any, first: date, last: date) -> WindowMetrics:
    """Sum the ``1D`` intervals whose start date is inside ``[first, last]``."""
    performance = _unwrap(payload).get("performance") or {}
    views = impressions = clicks = items = 0
    gmv = 0.0
    for interval in performance.get("intervals") or []:
        try:
            day = date.fromisoformat(str(interval.get("start_date")))
        except ValueError:
            continue
        if not first <= day <= last:
            continue
        overall = (interval.get("sales") or {}).get("overall") or {}
        impressions += _int(overall.get("product_impressions"))
        clicks += _int(overall.get("product_clicks"))
        items += _int(overall.get("items_sold"))
        gmv += to_float(overall.get("gmv"))
        views += _int((interval.get("traffic") or {}).get("views"))
    return WindowMetrics(
        views=views,
        product_impressions=impressions,
        product_clicks=clicks,
        gmv=gmv,
        items_sold=items,
    )


class _Counter:
    def __init__(self, sleep_s: float, backoff_sleep: Sleep) -> None:
        self.calls = 0
        self._sleep_s = sleep_s
        self._backoff_sleep = backoff_sleep

    def __call__(self, call: Any) -> Any:
        if self.calls:
            time.sleep(self._sleep_s)
        self.calls += 1
        return with_backoff(call, self._backoff_sleep)


def _list_window(resources: Any, run: _Counter, first: date, last: date) -> list[dict]:
    return list(
        run(
            partial(
                resources.analytics.list_video_performance_all,
                start_date_ge=first.isoformat(),
                end_date_lt=(last + timedelta(days=1)).isoformat(),
                sort_field="gmv",
            )
        )
    )


def _snapshot_impressions(payload: Any) -> tuple[int | None, int | None]:
    """Sum of the per-product impressions/clicks in a snapshot video file, if it has them."""
    products = _unwrap(payload).get("products") or []
    if not any("product_impressions" in p for p in products if isinstance(p, dict)):
        return None, None
    rows = [p for p in products if isinstance(p, dict)]
    return (
        sum(_int(p.get("product_impressions")) for p in rows),
        sum(_int(p.get("product_clicks")) for p in rows),
    )


def posted_in_window(
    snapshot: Snapshot,
    windows: Windows,
    *,
    max_videos_per_window: int = MAX_VIDEOS_PER_WINDOW,
) -> tuple[VideoWindowRow, ...]:
    """Fallback rows: per window, videos posted inside it with their snapshot totals. No calls."""
    rows: list[VideoWindowRow] = []
    bounds = {
        "last": (windows.last_first, windows.last_last),
        "prior": (windows.prior_first, windows.prior_last),
    }
    for side, (first, last) in bounds.items():
        inside = [
            v
            for v in snapshot.videos
            if (posted := _posted_at(v)) is not None and first <= posted.date() <= last
        ]
        for video in _top(inside, max_videos_per_window):
            video_id = str(video["id"])
            impressions, clicks = _snapshot_impressions(snapshot.video_products.get(video_id))
            metrics = WindowMetrics(
                views=_int(video.get("views")),
                product_impressions=impressions,
                product_clicks=clicks,
                sku_orders=_int(video.get("sku_orders")),
                gmv=to_float(video.get("gmv")),
                items_sold=_int(video.get("items_sold")),
            )
            rows.append(
                VideoWindowRow(
                    video_id=video_id,
                    title=str(video.get("title") or ""),
                    posted_at=_posted_at(video),
                    last=metrics if side == "last" else None,
                    prior=metrics if side == "prior" else None,
                    basis=POSTED_IN_WINDOW,
                )
            )
    return tuple(rows)


def fetch_video_windows(
    resources: Any,
    snapshot: Snapshot,
    *,
    max_videos_per_window: int = MAX_VIDEOS_PER_WINDOW,
    sleep_s: float = 0.4,
    backoff_sleep: Sleep = time.sleep,
) -> VideoWindowMetrics:
    """Per-video last-30 / prior-30 metrics ending at ``snapshot.end``. Read-only; see module doc.

    ``resources`` is the same (rate-limited, production-read) object the snapshot
    fetch used; ``snapshot`` is the in-memory snapshot (only its end date, 60-day
    video list and per-video product files are read, for the fallback).
    """
    windows = Windows.ending(snapshot.end, WINDOW_DAYS)
    run = _Counter(sleep_s, backoff_sleep)

    def result(**kwargs: Any) -> VideoWindowMetrics:
        return VideoWindowMetrics(
            end=snapshot.end,
            last_window=(windows.last_first, windows.last_last),
            prior_window=(windows.prior_first, windows.prior_last),
            max_videos_per_window=max_videos_per_window,
            calls=run.calls,
            **kwargs,
        )

    def fallback(exc: BaseException) -> VideoWindowMetrics:
        reason = error_payload(exc)
        logger.warning(
            "video_windows_fallback",
            extra={
                "end": snapshot.end.isoformat(),
                "error_class": reason["error_class"],
                "error_message": reason["message"],
            },
        )
        rows = posted_in_window(snapshot, windows, max_videos_per_window=max_videos_per_window)
        return result(basis=POSTED_IN_WINDOW, videos=rows, fallback_reason=reason)

    try:
        last_rows = _list_window(resources, run, windows.last_first, windows.last_last)
        prior_rows = _list_window(resources, run, windows.prior_first, windows.prior_last)
    except Exception as exc:
        return fallback(exc)

    by_side = {
        "last": {str(r["id"]): r for r in last_rows if r.get("id")},
        "prior": {str(r["id"]): r for r in prior_rows if r.get("id")},
    }
    chosen: dict[str, dict] = {}
    for rows in (last_rows, prior_rows):
        for row in _top(rows, max_videos_per_window):
            chosen.setdefault(str(row["id"]), row)

    out: list[VideoWindowRow] = []
    failed: list[str] = []
    span_first = windows.prior_first.isoformat()
    span_end_lt = (windows.last_last + timedelta(days=1)).isoformat()
    for video_id, listed in chosen.items():
        try:
            payload = run(
                partial(
                    resources.analytics.get_video_performance,
                    video_id=video_id,
                    start_date_ge=span_first,
                    end_date_lt=span_end_lt,
                    granularity="1D",
                )
            )
        except Exception as exc:
            if not out and not failed:
                return fallback(exc)
            failed.append(video_id)
            continue
        sides: dict[str, WindowMetrics] = {}
        for side, (first, last) in (
            ("last", (windows.last_first, windows.last_last)),
            ("prior", (windows.prior_first, windows.prior_last)),
        ):
            summed = _sum_intervals(payload, first, last)
            listed_row = by_side[side].get(video_id) or {}
            sides[side] = WindowMetrics(
                views=summed.views,
                product_impressions=summed.product_impressions,
                product_clicks=summed.product_clicks,
                # Only the list carries SKU orders; absent from a window's list = none.
                sku_orders=_int(listed_row.get("sku_orders")),
                gmv=summed.gmv,
                items_sold=summed.items_sold,
            )
        out.append(
            VideoWindowRow(
                video_id=video_id,
                title=str(listed.get("title") or ""),
                posted_at=_posted_at(listed),
                last=sides["last"],
                prior=sides["prior"],
                basis=DATE_RANGE,
            )
        )
    return result(basis=DATE_RANGE, videos=tuple(out), failed_video_ids=tuple(failed))


__all__ = [
    "DATE_RANGE",
    "MAX_VIDEOS_PER_WINDOW",
    "POSTED_IN_WINDOW",
    "WINDOW_DAYS",
    "Basis",
    "VideoWindowMetrics",
    "VideoWindowRow",
    "WindowMetrics",
    "fetch_video_windows",
    "posted_in_window",
]
