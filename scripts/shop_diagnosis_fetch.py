#!/usr/bin/env python3
"""Read-only fetch of a shop snapshot for the shop diagnosis report (ADR-108 d.2, d.13).

The fetch itself is ``juli_backend.services.shop_diagnosis_daily.fetch`` (the
daily worker job uses the same code, fast track P7-A). Every call is a
production-read GET through the TikTok client's read-only transport guard
(client bootstrap shared with ``scripts/optimize_product_catalog_scan.py``);
nothing is written to TikTok.
The owner runs it himself, with ``!`` in the agent session, so credentials never
pass through the agent (runbook step 1)::

    # needs DATABASE_URL, TIKTOK_APP_KEY, TIKTOK_APP_SECRET
    python scripts/shop_diagnosis_fetch.py --shop fujiwa            # ends yesterday (UTC+7)
    python scripts/shop_diagnosis_fetch.py --shop fujiwa --end 2026-10-06
    # per-video last-30 / prior-30 metrics on that snapshot (P8-B), nothing else
    python scripts/shop_diagnosis_fetch.py --shop fujiwa --end 2026-10-06 --video-windows

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
import importlib
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

_SCRIPTS = Path(__file__).resolve().parent
_BACKEND_SRC = str(_SCRIPTS.parent / "backend" / "src")
if _BACKEND_SRC not in sys.path:
    sys.path.insert(0, _BACKEND_SRC)

# Loaded after the path insert above (the script also runs without PYTHONPATH).
_fetch = importlib.import_module("juli_backend.services.shop_diagnosis_daily.fetch")
_video_windows = importlib.import_module("juli_backend.services.shop_diagnosis_daily.video_windows")
_snapshot = importlib.import_module("juli_backend.services.shop_diagnosis.snapshot")
BACKOFF_SECONDS = _fetch.BACKOFF_SECONDS
DAYS = _fetch.DAYS
MAX_PRODUCT_DETAILS = _fetch.MAX_PRODUCT_DETAILS
THROTTLE_CODES = _fetch.THROTTLE_CODES
fetch_promotions = _fetch.fetch_promotions
fetch_snapshot = _fetch.fetch_snapshot
is_throttled = _fetch.is_throttled
with_backoff = _fetch.with_backoff
yesterday_local = _fetch.yesterday_local

SNAPSHOT_ROOT = Path.home() / ".juli-shop-snapshots"

__all__ = [
    "BACKOFF_SECONDS",
    "DAYS",
    "MAX_PRODUCT_DETAILS",
    "SNAPSHOT_ROOT",
    "THROTTLE_CODES",
    "fetch_promotions",
    "fetch_snapshot",
    "is_throttled",
    "main",
    "slug",
    "with_backoff",
    "yesterday_local",
]


def _load(name: str) -> ModuleType:
    """Load a sibling script as a module (they are not a package)."""
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "shop"


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
    parser.add_argument(
        "--video-windows",
        action="store_true",
        help="only fetch per-video last-30/prior-30 metrics for the snapshot already on "
        "disk; writes videos/windows.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    end = args.end or yesterday_local()
    folder = args.out or SNAPSHOT_ROOT / slug(args.shop) / end.isoformat()
    scan = _load("optimize_product_catalog_scan")
    resources = asyncio.run(scan._build_resources())
    if args.video_windows:
        return video_windows(resources, folder, end, sleep_s=args.sleep)
    meta = fetch_snapshot(
        resources, folder, end, args.shop, sleep_s=args.sleep, max_products=args.max_products
    )
    print(f"snapshot {folder}: {meta['new_daily_files']} new daily files")
    return 0


def video_windows(resources, folder: Path, end: date, *, sleep_s: float) -> int:
    """Per-video 30/30 metrics on the snapshot in ``folder``; prints what the owner checks."""
    snapshot = _snapshot.load_snapshot(folder, end)
    result = _video_windows.fetch_video_windows(resources, snapshot, sleep_s=sleep_s)
    out = folder / "videos" / "windows.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"basis={result.basis} calls={result.calls} videos={len(result.videos)} "
        f"failed={len(result.failed_video_ids)} fallback={result.fallback_reason}"
    )
    for row in result.videos[:5]:
        for side in ("last", "prior"):
            m = getattr(row, side)
            if m is not None:
                print(
                    f"  {row.video_id} {side}: impressions={m.product_impressions} "
                    f"clicks={m.product_clicks} sku_orders={m.sku_orders} gmv={m.gmv:.0f}"
                )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
