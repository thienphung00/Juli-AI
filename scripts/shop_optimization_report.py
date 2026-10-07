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

    # rebuild from a snapshot already in <out-dir>/snapshot, no network
    python scripts/shop_optimization_report.py --replay --out-dir out/fujiwa-report
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

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

    meta_path = snapshot / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update({"as_of": as_of.isoformat(), "windows_30d": {k: windows[k] for k in fetched}})
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
