#!/usr/bin/env python3
"""Per-shop optimization report (read-only): JSON + a shareable HTML page.

The report logic is ``juli_backend.services.optimize_product.shop_report``;
this wrapper owns the live fetch, which the services package may not import
(import-boundary gate). Live mode reuses the catalog scan's fetch
(``scripts/optimize_product_catalog_scan.py``: A-34 for the 14/28-day card
windows, GetProduct, diagnoses) into ``<out-dir>/snapshot``, then adds the two
30-day A-34 windows the tables use. Every call is a production-read GET;
nothing is written to TikTok. Examples::

    # live — needs DATABASE_URL, TIKTOK_APP_KEY, TIKTOK_APP_SECRET
    python scripts/shop_optimization_report.py --as-of 2026-10-05 \
        --out-dir out/fujiwa-report --shop-name "Fujiwa Vietnam Store"

    # rebuild from a snapshot already in <out-dir>/snapshot, no network;
    # --owner-tests copies the owner's own tests into the snapshot
    python scripts/shop_optimization_report.py --replay --out-dir out/fujiwa-report \
        --owner-tests owner_tests.json

Live mode also fetches ``orders.json``: orders *created* in the previous + current
30 days (``create_time_ge`` / ``create_time_lt``, never ``update_time``), in 7-day
slices so the page cap is never hit. ``meta.json`` records per slice how many orders
came back and whether the cap was hit. Optional snapshot files never fetched:
``ratings.json`` (per-product star rating and review count), ``owner_tests.json``.

Live mode also tries three optional enrichments for the traffic-source check
(ADR-106 amendment 4); each tolerates failure by writing ``_error.json`` (class and
message, no tokens) next to what it did save and moving on:

* ``promotions/``: Search Activities (ONGOING, NOT_START, EXPIRED), Search Coupons
  and, for activities overlapping the current window, Get Activity for the product
  list (at most ``MAX_ACTIVITY_DETAIL_CALLS``);
* ``live/``: the top ``TOP_LIVE_SESSIONS`` LIVE sessions by GMV and their products;
* ``videos/``: the top ``TOP_VIDEOS`` shop videos by GMV and their products.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

ORDER_SLICE_DAYS = 7
ACTIVITY_STATUSES = ("ONGOING", "NOT_START", "EXPIRED")
MAX_ACTIVITY_DETAIL_CALLS = 50
TOP_LIVE_SESSIONS = 10
TOP_VIDEOS = 20
SHOP_UTC_OFFSET_HOURS = 7
MESSAGE_LIMIT = 300

_SCAN_SCRIPT = Path(__file__).resolve().parent / "optimize_product_catalog_scan.py"


def _load_scan_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("optimize_product_catalog_scan", _SCAN_SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {_SCAN_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _error_payload(exc: Exception) -> dict[str, str]:
    """Class and message only; anything token-shaped is redacted and the text truncated."""
    message = re.sub(
        r"(?i)(access[_-]?token|app[_-]?secret|sign|authorization)(\W{0,3})[A-Za-z0-9._~+/=-]{8,}",
        r"\1\2[redacted]",
        str(exc),
    )
    return {"error_class": type(exc).__name__, "message": message[:MESSAGE_LIMIT]}


def _window_seconds(first: str, end_lt: str) -> tuple[int, int]:
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))

    def at(day: str) -> int:
        parsed = date.fromisoformat(day)
        return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=zone).timestamp())

    return at(first), at(end_lt)


def _overlaps(activity: dict, window: tuple[int, int]) -> bool:
    try:
        begin = int(activity.get("begin_time") or 0)
        end = int(activity.get("end_time") or 0)
    except (TypeError, ValueError):
        return True  # unreadable times: keep, the parser decides
    return begin < window[1] and (end == 0 or end >= window[0])


def _fetch_promotions(
    resources: Any, snapshot: Path, first: str, end_lt: str, *, sleep_s: float
) -> None:
    """Search activities and coupons; fetch product lists for the activities in the window."""
    folder = snapshot / "promotions"
    try:
        seen: dict[str, dict] = {}
        for status in ACTIVITY_STATUSES:
            for activity in resources.promotion.search_activities_all(status=status):
                seen.setdefault(str(activity.get("id") or len(seen)), activity)
            time.sleep(sleep_s)
        activities = list(seen.values())
        _write(folder / "activities.json", {"activities": activities})
        _write(folder / "coupons.json", {"coupons": resources.promotion.search_coupons_all()})
        time.sleep(sleep_s)
        window = _window_seconds(first, end_lt)
        details: dict[str, Any] = {}
        for activity in activities:
            if len(details) >= MAX_ACTIVITY_DETAIL_CALLS:
                break
            activity_id = str(activity.get("id") or "")
            if activity_id and "products" not in activity and _overlaps(activity, window):
                details[activity_id] = resources.promotion.get_activity(activity_id)
                time.sleep(sleep_s)
        _write(folder / "activity_details.json", details)
    except Exception as exc:
        _write(folder / "_error.json", _error_payload(exc))


def _fetch_orders(
    resources: Any, snapshot: Path, first: str, end_lt: str, *, sleep_s: float
) -> dict[str, Any]:
    """Orders created in ``[first, end_lt)``, by 7-day slices; returns the fetch record."""
    from juli_backend.integrations.tiktok import pagination_scope

    slices: list[dict[str, Any]] = []
    orders: dict[str, dict] = {}
    try:
        start = date.fromisoformat(first)
        stop = date.fromisoformat(end_lt)
        while start < stop:
            nxt = min(start + timedelta(days=ORDER_SLICE_DAYS), stop)
            lo, hi = _window_seconds(start.isoformat(), nxt.isoformat())
            with pagination_scope() as scope:
                batch = resources.orders.search_all(create_time_from=lo, create_time_to=hi)
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
        _write(snapshot / "orders.json", {"orders": list(orders.values())})
        return {
            "status": "ok",
            "window": [first, end_lt],
            "slices": slices,
            "any_slice_hit_cap": any(x["hit_page_cap"] for x in slices),
            "orders": len(orders),
        }
    except Exception as exc:
        return {"status": "error", "slices": slices, **_error_payload(exc)}


def _gmv_of(item: dict) -> Decimal:
    for key in ("sales_performance", None):
        block = item.get(key) if key else item
        gmv = block.get("gmv") if isinstance(block, dict) else None
        amount = gmv.get("amount") if isinstance(gmv, dict) else None
        if amount is not None:
            return Decimal(str(amount))
    return Decimal(0)


def _fetch_live_sessions(
    resources: Any, snapshot: Path, first: str, end_lt: str, *, sleep_s: float
) -> None:
    folder = snapshot / "live"
    try:
        sessions = resources.analytics.list_live_performance_all(
            start_date_ge=first, end_date_lt=end_lt
        )
        top = sorted(sessions, key=_gmv_of, reverse=True)[:TOP_LIVE_SESSIONS]
        _write(folder / "sessions.json", {"sessions": top})
        for session in top:
            live_id = str(session.get("id") or "")
            if live_id:
                time.sleep(sleep_s)
                _write(
                    folder / "products" / f"{live_id}.json",
                    resources.analytics.get_live_products_performance(live_id=live_id),
                )
    except Exception as exc:
        _write(folder / "_error.json", _error_payload(exc))


def _fetch_videos(
    resources: Any, snapshot: Path, first: str, end_lt: str, *, sleep_s: float
) -> None:
    folder = snapshot / "videos"
    try:
        videos = resources.analytics.list_video_performance_all(
            start_date_ge=first, end_date_lt=end_lt, sort_field="gmv"
        )
        top = sorted(videos, key=_gmv_of, reverse=True)[:TOP_VIDEOS]
        _write(folder / "videos.json", {"videos": top})
        for video in top:
            video_id = str(video.get("id") or "")
            if video_id:
                time.sleep(sleep_s)
                _write(
                    folder / "products" / f"{video_id}.json",
                    resources.analytics.get_video_products_performance(
                        video_id=video_id, start_date_ge=first, end_date_lt=end_lt
                    ),
                )
    except Exception as exc:
        _write(folder / "_error.json", _error_payload(exc))


async def _fetch_live(
    snapshot: Path,
    as_of: date,
    shop_name: str | None,
    *,
    max_products: int,
    sleep_s: float,
) -> None:
    from juli_backend.services.optimize_product.config import StageDiagnosisConfig
    from juli_backend.services.optimize_product.shop_report import money, report_windows

    config = StageDiagnosisConfig()
    scan = _load_scan_script()
    await scan._fetch_live(snapshot, as_of, config, max_products=max_products, sleep_s=sleep_s)

    resources = await scan._build_resources()
    windows = report_windows(as_of, config)
    fetched: dict[str, list[dict]] = {}
    for key, name in (("current_30d", "a34_30d_current"), ("previous_30d", "a34_30d_previous")):
        first, last = windows[key]
        end_lt = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        fetched[key] = resources.analytics.list_product_performance_all(
            start_date_ge=first, end_date_lt=end_lt
        )
        _write(snapshot / f"{name}.json", {"products": fetched[key], "window": [first, end_lt]})
        time.sleep(sleep_s)

    # The 30-day tables need status and title for products the 14-day scan never saw.
    ranked = sorted(
        (*fetched["current_30d"], *fetched["previous_30d"]),
        key=lambda p: money((p.get("total_performance") or {}).get("gmv")),
        reverse=True,
    )
    missing: list[str] = []
    for item in ranked:
        product_id = str(item.get("id") or "")
        path = snapshot / "products" / f"{product_id}.json"
        if product_id and not path.exists() and product_id not in missing:
            missing.append(product_id)
    for product_id in missing[:max_products]:
        _write(
            snapshot / "products" / f"{product_id}.json", resources.products.get_details(product_id)
        )
        time.sleep(sleep_s)

    first, last = windows["current_30d"]
    end_lt = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    orders_record = _fetch_orders(
        resources, snapshot, windows["previous_30d"][0], end_lt, sleep_s=sleep_s
    )
    _fetch_promotions(resources, snapshot, first, end_lt, sleep_s=sleep_s)
    _fetch_live_sessions(resources, snapshot, first, end_lt, sleep_s=sleep_s)
    _fetch_videos(resources, snapshot, first, end_lt, sleep_s=sleep_s)

    meta_path = snapshot / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update(
        {
            "as_of": as_of.isoformat(),
            "windows_30d": {k: windows[k] for k in fetched},
            "orders_fetch": orders_record,
        }
    )
    if shop_name:
        meta["shop_name"] = shop_name
    _write(meta_path, meta)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=date.today() - timedelta(days=1)
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--shop-name", default=None)
    parser.add_argument("--max-products", type=int, default=200)
    parser.add_argument("--sleep", type=float, default=0.4, help="seconds between live calls")
    parser.add_argument("--replay", action="store_true", help="skip network; use out-dir/snapshot")
    parser.add_argument(
        "--owner-tests",
        type=Path,
        default=None,
        help='JSON list of {"product_id", "angle", "gift_product_id"?, "note"?}; '
        "copied to <out-dir>/snapshot/owner_tests.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from juli_backend.services.optimize_product.shop_report import build_shop_report, render_html

    args = _parse_args(argv)
    snapshot = args.out_dir / "snapshot"
    if not args.replay:
        asyncio.run(
            _fetch_live(
                snapshot,
                args.as_of,
                args.shop_name,
                max_products=args.max_products,
                sleep_s=args.sleep,
            )
        )
    elif not (snapshot / "meta.json").exists():
        raise SystemExit(f"--replay needs a snapshot at {snapshot}")
    if args.owner_tests is not None:
        _write(snapshot / "owner_tests.json", json.loads(args.owner_tests.read_text()))
    report = build_shop_report(snapshot, shop_name=args.shop_name)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(report.to_json())
    (args.out_dir / "report.html").write_text(render_html(report))
    print(f"wrote {args.out_dir / 'report.json'}")
    print(f"wrote {args.out_dir / 'report.html'}")
    return 0


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
