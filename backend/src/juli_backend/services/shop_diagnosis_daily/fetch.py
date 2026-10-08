"""Read-only fetch of a shop snapshot for the shop diagnosis report (ADR-108 d.2, d.13).

Moved here from ``scripts/shop_diagnosis_fetch.py`` (fast track P7-A) so the
daily worker job and the operator script share one fetch. Every call goes
through a production-read resources object the caller hands in
(``ProductionReadClientFactory().create_resources(...)`` in production, a fake
in tests); this module never builds a client, never resolves a credential and
never writes to TikTok.

It writes the snapshot layout documented in
``juli_backend.services.shop_diagnosis.snapshot`` into ``folder`` so the pure
report package can load it unchanged. The worker passes a temporary directory
that is removed after the build (orders carry buyer data and are never kept);
the script passes ``~/.juli-shop-snapshots/<shop>/<end>/``.

Daily A-34 files already in ``folder`` are not refetched. Each optional part
that fails writes its own ``_error*.json`` (class and message, tokens redacted)
and the run moves on. A throttled call (HTTP 429 / TikTok "Too many requests")
is retried after 2 s, 4 s, then 8 s.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from juli_backend.integrations.tiktok import pagination_scope

SHOP_UTC_OFFSET_HOURS = 7
DAYS = 60
ACTIVITY_STATUSES = ("ONGOING", "NOT_START", "EXPIRED", "DEACTIVATED")
MAX_ACTIVITY_DETAIL_CALLS = 400
MAX_LIVE_SESSIONS = 60
MAX_VIDEOS = 40
MAX_PRODUCT_DETAILS = 40
ORDER_SLICE_DAYS = 7
MESSAGE_LIMIT = 300

BACKOFF_SECONDS = (2.0, 4.0, 8.0)
#: TikTok's "Too many requests" code (HTTP 429); 100005 is the generic throttle code.
THROTTLE_CODES = (36009002, 100005)

Sleep = Callable[[float], Any]


def yesterday_local(now: datetime | None = None) -> date:
    """Yesterday in the shop's time zone (UTC+7): the default report end date."""
    moment = (now or datetime.now(UTC)).astimezone(timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS)))
    return moment.date() - timedelta(days=1)


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def error_payload(exc: BaseException) -> dict[str, str]:
    """Class and message only; anything token-shaped is redacted and the text truncated."""
    message = re.sub(
        r"(?i)(access[_-]?token|app[_-]?secret|sign|authorization)(\W{0,3})[A-Za-z0-9._~+/=-]{8,}",
        r"\1\2[redacted]",
        str(exc),
    )
    return {"error_class": type(exc).__name__, "message": message[:MESSAGE_LIMIT]}


def window_seconds(first: str, end_lt: str) -> tuple[int, int]:
    """``[first, end_lt)`` local dates as epoch seconds at UTC+7 midnight."""
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))

    def at(day: str) -> int:
        parsed = date.fromisoformat(day)
        return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=zone).timestamp())

    return at(first), at(end_lt)


def overlaps(activity: dict, window: tuple[int, int]) -> bool:
    try:
        begin = int(activity.get("begin_time") or 0)
        end = int(activity.get("end_time") or 0)
    except (TypeError, ValueError):
        return True  # unreadable times: keep, the parser decides
    return begin < window[1] and (end == 0 or end >= window[0])


def gmv_of(item: dict) -> Decimal:
    for key in ("sales_performance", None):
        block = item.get(key) if key else item
        gmv = block.get("gmv") if isinstance(block, dict) else None
        amount = gmv.get("amount") if isinstance(gmv, dict) else None
        if amount is not None:
            return Decimal(str(amount))
    return Decimal(0)


def is_throttled(exc: BaseException) -> bool:
    """True for a 429 / "Too many requests" failure, however the client surfaced it."""
    if getattr(exc, "code", None) in THROTTLE_CODES:
        return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 429 or getattr(exc, "status_code", None) == 429:
        return True
    return "too many requests" in str(exc).lower()


def with_backoff(call: Callable[[], Any], backoff_sleep: Sleep) -> Any:
    """Run ``call``; on a throttle wait 2 s, 4 s, then 8 s and retry (up to 4 calls in all)."""
    for delay in BACKOFF_SECONDS:
        try:
            return call()
        except Exception as exc:
            if not is_throttled(exc):
                raise
            backoff_sleep(delay)
    return call()


def fetch_daily(
    resources: Any,
    folder: Path,
    first: date,
    end: date,
    *,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> int:
    """One A-34 file per day of ``first..end``; days already on disk are skipped."""
    fetched = 0
    day = first
    while day <= end:
        path = folder / "daily" / f"a34_{day.isoformat()}.json"
        if not path.exists():
            start, stop = day.isoformat(), (day + timedelta(days=1)).isoformat()
            products = with_backoff(
                partial(
                    resources.analytics.list_product_performance_all,
                    start_date_ge=start,
                    end_date_lt=stop,
                ),
                backoff_sleep,
            )
            _write(path, {"day": day.isoformat(), "products": products})
            fetched += 1
            time.sleep(sleep_s)
        day += timedelta(days=1)
    return fetched


def fetch_orders(
    resources: Any,
    folder: Path,
    first: str,
    end_lt: str,
    *,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    """Orders created in ``[first, end_lt)``, by 7-day slices; returns the fetch record."""
    slices: list[dict[str, Any]] = []
    orders: dict[str, dict] = {}
    try:
        start = date.fromisoformat(first)
        stop = date.fromisoformat(end_lt)
        while start < stop:
            nxt = min(start + timedelta(days=ORDER_SLICE_DAYS), stop)
            lo, hi = window_seconds(start.isoformat(), nxt.isoformat())
            with pagination_scope() as scope:
                batch = with_backoff(
                    partial(resources.orders.search_all, create_time_from=lo, create_time_to=hi),
                    backoff_sleep,
                )
            for order in batch:
                orders[str(order.get("id") or len(orders))] = order
            slices.append(
                {
                    "from": start.isoformat(),
                    "to_exclusive": nxt.isoformat(),
                    "orders": len(batch),
                    "hit_page_cap": bool(scope.truncated),
                }
            )
            start = nxt
            time.sleep(sleep_s)
        _write(folder / "orders.json", {"orders": list(orders.values())})
        return {
            "status": "ok",
            "window": [first, end_lt],
            "slices": slices,
            "any_slice_hit_cap": any(x["hit_page_cap"] for x in slices),
            "orders": len(orders),
        }
    except Exception as exc:
        return {"status": "error", "slices": slices, **error_payload(exc)}


def _fetch_activities(
    resources: Any, target: Path, sleep_s: float, backoff_sleep: Sleep
) -> list[dict]:
    """Activities of every status; one status the API rejects must not lose the others."""
    seen: dict[str, dict] = {}
    for status in ACTIVITY_STATUSES:
        try:
            found = with_backoff(
                partial(resources.promotion.search_activities_all, status=status),
                backoff_sleep,
            )
            for activity in found:
                seen.setdefault(str(activity.get("id") or len(seen)), activity)
        except Exception as exc:
            _write(target / f"_error_{status.lower()}.json", error_payload(exc))
        time.sleep(sleep_s)
    activities = list(seen.values())
    _write(target / "activities.json", {"activities": activities})
    return activities


def _fetch_details(
    resources: Any,
    target: Path,
    activities: list[dict],
    window: tuple[int, int],
    sleep_s: float,
    backoff_sleep: Sleep,
) -> None:
    """Details of activities overlapping the window; a failed one is recorded, the rest kept."""
    details: dict[str, Any] = {}
    failed: dict[str, dict[str, str]] = {}
    for activity in activities:
        if len(details) >= MAX_ACTIVITY_DETAIL_CALLS:
            break
        activity_id = str(activity.get("id") or "")
        if not activity_id or not overlaps(activity, window):
            continue
        try:
            details[activity_id] = with_backoff(
                partial(resources.promotion.get_activity, activity_id),
                backoff_sleep,
            )
        except Exception as exc:
            failed[activity_id] = error_payload(exc)
        time.sleep(sleep_s)
    _write(target / "activity_details.json", details)
    if failed:
        _write(target / "_error_details.json", failed)


def fetch_promotions(
    resources: Any,
    folder: Path,
    first: str,
    end_lt: str,
    *,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> None:
    """Activities, coupons and activity details as three independent parts.

    Each part that fails writes its own ``_error_*.json`` and the others still run; a
    429 is retried with exponential backoff (``backoff_sleep`` is injectable for tests).
    """
    target = folder / "promotions"
    activities: list[dict] = []
    try:
        activities = _fetch_activities(resources, target, sleep_s, backoff_sleep)
    except Exception as exc:
        _write(target / "_error_activities.json", error_payload(exc))
    try:
        coupons = with_backoff(resources.promotion.search_coupons_all, backoff_sleep)
        _write(target / "coupons.json", {"coupons": coupons})
    except Exception as exc:
        _write(target / "_error_coupons.json", error_payload(exc))
    try:
        window = window_seconds(first, end_lt)
        _fetch_details(resources, target, activities, window, sleep_s, backoff_sleep)
    except Exception as exc:
        _write(target / "_error_details.json", error_payload(exc))


def fetch_live(
    resources: Any,
    folder: Path,
    first: str,
    end_lt: str,
    *,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> None:
    target = folder / "live"
    try:
        sessions = with_backoff(
            lambda: resources.analytics.list_live_performance_all(
                start_date_ge=first, end_date_lt=end_lt
            ),
            backoff_sleep,
        )
        top = sorted(sessions, key=gmv_of, reverse=True)[:MAX_LIVE_SESSIONS]
        _write(target / "sessions.json", {"sessions": top})
        for session in top:
            live_id = str(session.get("id") or "")
            if live_id:
                time.sleep(sleep_s)
                _write(
                    target / "products" / f"{live_id}.json",
                    with_backoff(
                        partial(resources.analytics.get_live_products_performance, live_id=live_id),
                        backoff_sleep,
                    ),
                )
    except Exception as exc:
        _write(target / "_error.json", error_payload(exc))


def fetch_videos(
    resources: Any,
    folder: Path,
    first: str,
    end_lt: str,
    *,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> None:
    target = folder / "videos"
    try:
        videos = with_backoff(
            lambda: resources.analytics.list_video_performance_all(
                start_date_ge=first, end_date_lt=end_lt, sort_field="gmv"
            ),
            backoff_sleep,
        )
        top = sorted(videos, key=gmv_of, reverse=True)[:MAX_VIDEOS]
        _write(target / "videos.json", {"videos": top})
        for video in top:
            video_id = str(video.get("id") or "")
            if video_id:
                time.sleep(sleep_s)
                _write(
                    target / "products" / f"{video_id}.json",
                    with_backoff(
                        partial(
                            resources.analytics.get_video_products_performance,
                            video_id=video_id,
                            start_date_ge=first,
                            end_date_lt=end_lt,
                        ),
                        backoff_sleep,
                    ),
                )
    except Exception as exc:
        _write(target / "_error.json", error_payload(exc))


def _total_gmv(row: dict) -> float:
    block = row.get("total_performance") or {}
    gmv = block.get("gmv") if isinstance(block, dict) else None
    try:
        return float((gmv or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_product_details(
    resources: Any,
    folder: Path,
    *,
    limit: int,
    sleep_s: float,
    backoff_sleep: Sleep = time.sleep,
) -> None:
    """Get Product (title, SKU prices) for the top products by 60-day GMV not on disk yet."""
    totals: dict[str, float] = {}
    for path in sorted((folder / "daily").glob("a34_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")).get("products") or []:
            pid = str(row.get("id") or "")
            if pid:
                totals[pid] = totals.get(pid, 0.0) + _total_gmv(row)
    for pid in sorted(totals, key=lambda p: -totals[p])[:limit]:
        path = folder / "products" / f"{pid}.json"
        if path.exists():
            continue
        try:
            _write(
                path,
                with_backoff(partial(resources.products.get_details, pid), backoff_sleep),
            )
        except Exception as exc:
            _write(folder / "products" / "_error.json", {"product": pid, **error_payload(exc)})
        time.sleep(sleep_s)


def fetch_snapshot(
    resources: Any,
    folder: Path,
    end: date,
    shop_name: str,
    *,
    sleep_s: float = 0.4,
    max_products: int = MAX_PRODUCT_DETAILS,
    backoff_sleep: Sleep = time.sleep,
    source: str = "live (production_read, read-only guard)",
) -> dict[str, Any]:
    """Fill ``folder`` with the 60-day snapshot ending ``end``; returns the meta record."""
    first = end - timedelta(days=DAYS - 1)
    end_lt = (end + timedelta(days=1)).isoformat()
    timing: dict[str, Any] = {"sleep_s": sleep_s, "backoff_sleep": backoff_sleep}
    new_days = fetch_daily(resources, folder, first, end, **timing)
    orders_record = fetch_orders(resources, folder, first.isoformat(), end_lt, **timing)
    fetch_promotions(resources, folder, first.isoformat(), end_lt, **timing)
    fetch_live(resources, folder, first.isoformat(), end_lt, **timing)
    fetch_videos(resources, folder, first.isoformat(), end_lt, **timing)
    fetch_product_details(resources, folder, limit=max_products, **timing)
    meta = {
        "shop_name": shop_name,
        "end": end.isoformat(),
        "days": DAYS,
        "new_daily_files": new_days,
        "orders_fetch": orders_record,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
    }
    _write(folder / "meta.json", meta)
    return meta


__all__ = [
    "BACKOFF_SECONDS",
    "DAYS",
    "MAX_PRODUCT_DETAILS",
    "THROTTLE_CODES",
    "error_payload",
    "fetch_daily",
    "fetch_live",
    "fetch_orders",
    "fetch_product_details",
    "fetch_promotions",
    "fetch_snapshot",
    "fetch_videos",
    "is_throttled",
    "with_backoff",
    "yesterday_local",
]
