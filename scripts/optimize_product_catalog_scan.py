#!/usr/bin/env python3
"""CLI for the read-only Optimize Product catalog scan (ADR-106).

The pipeline lives in ``juli_backend.services.optimize_product.catalog_scan``.
This wrapper makes the backend package importable from a checkout that has not
installed it and owns the **live fetcher** (TikTok read-only client + DB
credential lookup), which the services package may not import under the
import-boundary gate; it is handed to ``catalog_scan.main`` as ``live_fetcher``.
The snapshot layout is documented in the ``catalog_scan`` module docstring.
Examples::

    # live — needs DATABASE_URL, TIKTOK_APP_KEY, TIKTOK_APP_SECRET; read-only
    python scripts/optimize_product_catalog_scan.py --source live \
        --snapshot-dir out/fujiwa-2026-10-05 --out-dir out/fujiwa-2026-10-05

    # replay a saved snapshot, no network
    python scripts/optimize_product_catalog_scan.py --source snapshot \
        --snapshot-dir out/fujiwa-2026-10-05 --out-dir out/fujiwa-2026-10-05
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from juli_backend.services.optimize_product.config import StageDiagnosisConfig


async def _fetch_live(
    snapshot: Path,
    as_of: date,
    config: StageDiagnosisConfig,
    *,
    max_products: int,
    with_a33: bool,
    sleep_s: float,
) -> None:
    """Pull A-34 (three windows), GetProduct and optionally A-33 per product. Read-only."""
    from juli_backend.core.async_db import async_database_url
    from juli_backend.core.config import require_env
    from juli_backend.core.security import resolve_production_read_credential
    from juli_backend.database.database import ensure_worker_session_factory
    from juli_backend.integrations.tiktok.factories import (
        ClientFactoryConfig,
        ProductionReadClientFactory,
    )
    from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID
    from juli_backend.services.optimize_product.catalog_scan import dump_json, windows

    app_key, app_secret = require_env("TIKTOK_APP_KEY"), require_env("TIKTOK_APP_SECRET")
    # Resolve the URL here rather than via ``workers.tasks.database``: importing
    # ``workers.tasks`` boots the Celery app and asserts the full runtime
    # config (SUPABASE_URL, broker), which a read-only scan has no business
    # requiring.
    factory = ensure_worker_session_factory(async_database_url(require_env("DATABASE_URL")))
    async with factory() as session:
        credential = await resolve_production_read_credential(session)
    resources = ProductionReadClientFactory().create_resources(
        ClientFactoryConfig(
            app_key=app_key,
            app_secret=app_secret,
            access_token=credential.access_token,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            shop_cipher=credential.shop_cipher,
        )
    )
    scan_windows = windows(as_of, config)
    a34: dict[str, list[dict]] = {}
    for name, (start, end) in scan_windows.items():
        a34[name] = resources.analytics.list_product_performance_all(
            start_date_ge=start, end_date_lt=end
        )
        dump_json(snapshot / f"a34_{name}.json", {"products": a34[name], "window": [start, end]})
        time.sleep(sleep_s)

    def _gmv(item: dict) -> Decimal:
        total = item.get("total_performance") or {}
        return Decimal(str((total.get("gmv") or {}).get("amount") or "0"))

    ranked = sorted(a34["current"], key=_gmv, reverse=True)
    product_ids = [str(p["id"]) for p in ranked if p.get("id")][:max_products]
    for product_id in product_ids:
        detail = resources.products.get_details(product_id)
        dump_json(snapshot / "products" / f"{product_id}.json", detail)
        time.sleep(sleep_s)
        if with_a33:
            for name in ("current", "prior"):
                start, end = scan_windows[name]
                payload = resources.analytics.get_product_performance(
                    product_id=product_id, start_date_ge=start, end_date_lt=end
                )
                dump_json(snapshot / "a33" / f"{product_id}_{name}.json", payload)
                time.sleep(sleep_s)
    dump_json(
        snapshot / "meta.json",
        {
            "as_of": as_of.isoformat(),
            "windows": scan_windows,
            "products_fetched": len(product_ids),
            "with_a33": with_a33,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "source": "live (production_read, read-only guard)",
        },
    )


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    from juli_backend.services.optimize_product.catalog_scan import main

    return main(live_fetcher=_fetch_live)


if __name__ == "__main__":
    raise SystemExit(_run())
