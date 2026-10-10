#!/usr/bin/env python3
"""Read-only fetch of a shop snapshot for the shop diagnosis report (ADR-108 d.2, d.13).

Every call is a production-read GET through the TikTok client's read-only
transport guard (client bootstrap shared with
``scripts/optimize_product_catalog_scan.py``); nothing is written to TikTok.
The owner runs it himself, with ``!`` in the agent session, so credentials never
pass through the agent (runbook step 1)::

    # needs DATABASE_URL, TIKTOK_APP_KEY, TIKTOK_APP_SECRET
    python scripts/shop_diagnosis_fetch.py --shop fujiwa            # ends yesterday (UTC+7)
    python scripts/shop_diagnosis_fetch.py --shop fujiwa --end 2026-10-06

Writes the snapshot layout documented in
``juli_backend.services.shop_diagnosis.snapshot`` to
``~/.juli-shop-snapshots/<shop>/<end>/`` (outside the repo — orders carry buyer
data), or ``--out``. Daily A-34 files already on disk are not refetched, so a
morning run adds only yesterday; orders, promotions, LIVE and video lists are
refreshed each run. Each optional part that fails writes its own ``_error*.json`` (class
and message, tokens redacted) and the run moves on. Then build offline with
``scripts/shop_diagnosis_report.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

SNAPSHOT_ROOT = Path.home() / ".juli-shop-snapshots"
SHOP_UTC_OFFSET_HOURS = 7
DAYS = 60
ACTIVITY_STATUSES = ("ONGOING", "NOT_START", "EXPIRED", "DEACTIVATED")
MAX_ACTIVITY_DETAIL_CALLS = 400
MAX_LIVE_SESSIONS = 60
MAX_VIDEOS = 40
# The shop's own accounts: every video with activity in the window, no GMV cut.
SHOP_ACCOUNT_TYPES = ("OFFICIAL_ACCOUNTS", "MARKETING_ACCOUNTS")
MAX_PRODUCT_DETAILS = 40

_SCRIPTS = Path(__file__).resolve().parent


def _load(name: str) -> ModuleType:
    """Load a sibling script as a module (they are not a package)."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def yesterday_local(now: datetime | None = None) -> date:
    moment = (now or datetime.now(UTC)).astimezone(timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS)))
    return moment.date() - timedelta(days=1)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "shop"


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def fetch_daily(resources: Any, folder: Path, first: date, end: date, *, sleep_s: float) -> int:
    """One A-34 file per day of ``first..end``; days already on disk are skipped."""
    fetched = 0
    day = first
    while day <= end:
        path = folder / "daily" / f"a34_{day.isoformat()}.json"
        if not path.exists():
            products = resources.analytics.list_product_performance_all(
                start_date_ge=day.isoformat(), end_date_lt=(day + timedelta(days=1)).isoformat()
            )
            _write(path, {"day": day.isoformat(), "products": products})
            fetched += 1
            time.sleep(sleep_s)
        day += timedelta(days=1)
    return fetched


BACKOFF_SECONDS = (2.0, 4.0, 8.0)
#: TikTok's "Too many requests" code (HTTP 429); 100005 is the generic throttle code.
THROTTLE_CODES = (36009002, 100005)


def is_throttled(exc: BaseException) -> bool:
    """True for a 429 / "Too many requests" failure, however the client surfaced it."""
    if getattr(exc, "code", None) in THROTTLE_CODES:
        return True
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) == 429 or getattr(exc, "status_code", None) == 429:
        return True
    return "too many requests" in str(exc).lower()


def with_backoff(call: Callable[[], Any], backoff_sleep: Callable[[float], Any]) -> Any:
    """Run ``call``; on a throttle wait 2 s, 4 s, then 8 s and retry (up to 4 calls in all)."""
    for delay in BACKOFF_SECONDS:
        try:
            return call()
        except Exception as exc:
            if not is_throttled(exc):
                raise
            backoff_sleep(delay)
    return call()


def _fetch_activities(
    resources: Any, target: Path, report: ModuleType, sleep_s: float, backoff_sleep: Any
) -> list[dict]:
    """Activities of every status; one status the API rejects must not lose the others."""
    seen: dict[str, dict] = {}
    for status in ACTIVITY_STATUSES:
        try:
            found = with_backoff(
                lambda status=status: resources.promotion.search_activities_all(status=status),
                backoff_sleep,
            )
            for activity in found:
                seen.setdefault(str(activity.get("id") or len(seen)), activity)
        except Exception as exc:
            _write(target / f"_error_{status.lower()}.json", report._error_payload(exc))
        time.sleep(sleep_s)
    activities = list(seen.values())
    _write(target / "activities.json", {"activities": activities})
    return activities


def _fetch_details(
    resources: Any,
    target: Path,
    activities: list[dict],
    window: tuple[int, int],
    report: ModuleType,
    sleep_s: float,
    backoff_sleep: Any,
) -> None:
    """Details of activities overlapping the window; a failed one is recorded, the rest kept."""
    details: dict[str, Any] = {}
    failed: dict[str, dict[str, str]] = {}
    for activity in activities:
        if len(details) >= MAX_ACTIVITY_DETAIL_CALLS:
            break
        activity_id = str(activity.get("id") or "")
        if not activity_id or not report._overlaps(activity, window):
            continue
        try:
            details[activity_id] = with_backoff(
                lambda activity_id=activity_id: resources.promotion.get_activity(activity_id),
                backoff_sleep,
            )
        except Exception as exc:
            failed[activity_id] = report._error_payload(exc)
        time.sleep(sleep_s)
    _write(target / "activity_details.json", details)
    if failed:
        _write(target / "_error_details.json", failed)


def fetch_promotions(
    resources: Any,
    folder: Path,
    first: str,
    end_lt: str,
    report: ModuleType,
    *,
    sleep_s: float,
    backoff_sleep: Callable[[float], Any] = time.sleep,
) -> None:
    """Activities, coupons and activity details as three independent parts.

    Each part that fails writes its own ``_error_*.json`` and the others still run; a
    429 is retried with exponential backoff (``backoff_sleep`` is injectable for tests).
    """
    target = folder / "promotions"
    activities: list[dict] = []
    try:
        activities = _fetch_activities(resources, target, report, sleep_s, backoff_sleep)
    except Exception as exc:
        _write(target / "_error_activities.json", report._error_payload(exc))
    try:
        coupons = with_backoff(resources.promotion.search_coupons_all, backoff_sleep)
        _write(target / "coupons.json", {"coupons": coupons})
    except Exception as exc:
        _write(target / "_error_coupons.json", report._error_payload(exc))
    try:
        window = report._window_seconds(first, end_lt)
        _fetch_details(resources, target, activities, window, report, sleep_s, backoff_sleep)
    except Exception as exc:
        _write(target / "_error_details.json", report._error_payload(exc))


def fetch_live(
    resources: Any, folder: Path, first: str, end_lt: str, report: ModuleType, *, sleep_s: float
) -> None:
    target = folder / "live"
    try:
        sessions = resources.analytics.list_live_performance_all(
            start_date_ge=first, end_date_lt=end_lt
        )
        top = sorted(sessions, key=report._gmv_of, reverse=True)[:MAX_LIVE_SESSIONS]
        _write(target / "sessions.json", {"sessions": top})
        for session in top:
            live_id = str(session.get("id") or "")
            if live_id:
                time.sleep(sleep_s)
                _write(
                    target / "products" / f"{live_id}.json",
                    resources.analytics.get_live_products_performance(live_id=live_id),
                )
    except Exception as exc:
        _write(target / "_error.json", report._error_payload(exc))


def fetch_videos(
    resources: Any, folder: Path, first: str, end_lt: str, report: ModuleType, *, sleep_s: float
) -> None:
    target = folder / "videos"
    try:
        videos = resources.analytics.list_video_performance_all(
            start_date_ge=first, end_date_lt=end_lt, sort_field="gmv"
        )
        top = sorted(videos, key=report._gmv_of, reverse=True)[:MAX_VIDEOS]
        _write(target / "videos.json", {"videos": top})
        for video in top:
            video_id = str(video.get("id") or "")
            if video_id:
                time.sleep(sleep_s)
                _write(
                    target / "products" / f"{video_id}.json",
                    resources.analytics.get_video_products_performance(
                        video_id=video_id, start_date_ge=first, end_date_lt=end_lt
                    ),
                )
    except Exception as exc:
        _write(target / "_error.json", report._error_payload(exc))


def fetch_shop_videos(
    resources: Any, folder: Path, first: str, end_lt: str, report: ModuleType, *, sleep_s: float
) -> None:
    """Every video from the shop's own accounts, newest post first, with its products.

    ``videos/videos.json`` keeps the top videos of all accounts by GMV for the report;
    this list keeps the shop's own videos that a GMV cut would drop (zero-GMV ones too).
    Each row carries the ``account_type`` it was listed under.
    """
    target = folder / "videos"
    videos: dict[str, dict] = {}
    for account_type in SHOP_ACCOUNT_TYPES:
        try:
            rows = resources.analytics.list_video_performance_all(
                start_date_ge=first,
                end_date_lt=end_lt,
                sort_field="views",
                account_type=account_type,
            )
        except Exception as exc:
            _write(target / f"_error_shop_{account_type.lower()}.json", report._error_payload(exc))
            continue
        for row in rows:
            video_id = str(row.get("id") or "")
            if video_id and video_id not in videos:
                videos[video_id] = {**row, "account_type": account_type}
    listed = sorted(
        videos.values(), key=lambda v: str(v.get("video_post_time") or ""), reverse=True
    )
    _write(target / "shop_videos.json", {"videos": listed})
    for video_id in videos:
        time.sleep(sleep_s)
        try:
            payload = resources.analytics.get_video_products_performance(
                video_id=video_id, start_date_ge=first, end_date_lt=end_lt
            )
        except Exception as exc:
            payload = {"_error": report._error_payload(exc)}
        _write(target / "shop_products" / f"{video_id}.json", payload)


def _gmv(row: dict) -> float:
    block = row.get("total_performance") or {}
    gmv = block.get("gmv") if isinstance(block, dict) else None
    try:
        return float((gmv or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_product_details(
    resources: Any, folder: Path, report: ModuleType, *, limit: int, sleep_s: float
) -> None:
    """Get Product (title, SKU prices) for the top products by 60-day GMV not on disk yet."""
    totals: dict[str, float] = {}
    for path in sorted((folder / "daily").glob("a34_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")).get("products") or []:
            pid = str(row.get("id") or "")
            if pid:
                totals[pid] = totals.get(pid, 0.0) + _gmv(row)
    for pid in sorted(totals, key=lambda p: -totals[p])[:limit]:
        path = folder / "products" / f"{pid}.json"
        if path.exists():
            continue
        try:
            _write(path, resources.products.get_details(pid))
        except Exception as exc:
            _write(
                folder / "products" / "_error.json", {"product": pid, **report._error_payload(exc)}
            )
        time.sleep(sleep_s)


def fetch_snapshot(
    resources: Any,
    folder: Path,
    end: date,
    shop_name: str,
    *,
    sleep_s: float = 0.4,
    max_products: int = MAX_PRODUCT_DETAILS,
    backoff_sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Fill ``folder`` with the 60-day snapshot ending ``end``; returns the meta record."""
    report = _load("shop_optimization_report")
    first = end - timedelta(days=DAYS - 1)
    end_lt = (end + timedelta(days=1)).isoformat()
    new_days = fetch_daily(resources, folder, first, end, sleep_s=sleep_s)
    orders_record = report._fetch_orders(
        resources, folder, first.isoformat(), end_lt, sleep_s=sleep_s
    )
    fetch_promotions(
        resources,
        folder,
        first.isoformat(),
        end_lt,
        report,
        sleep_s=sleep_s,
        backoff_sleep=backoff_sleep,
    )
    fetch_live(resources, folder, first.isoformat(), end_lt, report, sleep_s=sleep_s)
    fetch_videos(resources, folder, first.isoformat(), end_lt, report, sleep_s=sleep_s)
    fetch_shop_videos(resources, folder, first.isoformat(), end_lt, report, sleep_s=sleep_s)
    fetch_product_details(resources, folder, report, limit=max_products, sleep_s=sleep_s)
    meta = {
        "shop_name": shop_name,
        "end": end.isoformat(),
        "days": DAYS,
        "new_daily_files": new_days,
        "orders_fetch": orders_record,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "live (production_read, read-only guard)",
    }
    _write(folder / "meta.json", meta)
    return meta


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--shop", required=True, help="shop name or id; names the folder")
    parser.add_argument(
        "--end", type=date.fromisoformat, default=None, help="default: yesterday UTC+7"
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sleep", type=float, default=0.4, help="seconds between calls")
    parser.add_argument("--max-products", type=int, default=MAX_PRODUCT_DETAILS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    end = args.end or yesterday_local()
    folder = args.out or SNAPSHOT_ROOT / slug(args.shop) / end.isoformat()
    scan = _load("optimize_product_catalog_scan")
    resources = asyncio.run(scan._build_resources())
    meta = fetch_snapshot(
        resources, folder, end, args.shop, sleep_s=args.sleep, max_products=args.max_products
    )
    print(f"snapshot {folder}: {meta['new_daily_files']} new daily files")
    return 0


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
