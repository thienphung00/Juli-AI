#!/usr/bin/env python3
"""CLI for the read-only Optimize Product catalog scan (ADR-106).

The pipeline lives in ``juli_backend.services.optimize_product.catalog_scan``;
this wrapper only makes the backend package importable from a checkout that
has not installed it, then hands over. Examples::

    # live — needs DATABASE_URL, TIKTOK_APP_KEY, TIKTOK_APP_SECRET; read-only
    python scripts/optimize_product_catalog_scan.py --source live \
        --snapshot-dir out/fujiwa-2026-10-05 --out-dir out/fujiwa-2026-10-05

    # replay a saved snapshot, no network
    python scripts/optimize_product_catalog_scan.py --source snapshot \
        --snapshot-dir out/fujiwa-2026-10-05 --out-dir out/fujiwa-2026-10-05
"""

from __future__ import annotations

import sys
from pathlib import Path


def _run() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "backend" / "src"))
    from juli_backend.services.optimize_product.catalog_scan import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
