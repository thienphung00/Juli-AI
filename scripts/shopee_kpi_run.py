#!/usr/bin/env python3
"""Run the Shopee KPI job (ADR-117 step 3) for one shop and store its forecasts.

The same service the Ops route ``POST /v1/ops/shops/{id}/shopee-kpi/run`` calls
(``juli_backend.services.shopee_kpi.run_shop_kpi``), for a terminal or a scheduler:

    DATABASE_URL=postgresql://... python scripts/shopee_kpi_run.py --shop-id <uuid> \
        [--as-of YYYY-MM-DD] [--measure-start YYYY-MM-DD] [--dry-run]

``--dry-run`` computes and rolls back. Prints counts only (rows written, acceptance
tally), never metric values: forecasts are internal and client data.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.repositories import utc_now_naive
    from juli_backend.services import shopee_kpi

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            try:
                result = await shopee_kpi.run_shop_kpi(
                    session,
                    uuid.UUID(args.shop_id),
                    now=utc_now_naive(),
                    as_of=args.as_of,
                    measure_start=args.measure_start,
                )
            except (
                shopee_kpi.NoKpiContract,
                shopee_kpi.NoMetrics,
                shopee_kpi.MeasureStartMissing,
                shopee_kpi.ContractTermsError,
            ) as exc:
                await session.rollback()
                print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            if args.dry_run:
                await session.rollback()
            else:
                await session.commit()
    finally:
        await engine.dispose()
    acc = result.report.acceptance
    print(
        f"{'computed (dry run)' if args.dry_run else 'stored'}: as_of={result.as_of} "
        f"forecast_rows={len(result.forecasts) + len(result.bands)} "
        f"targets_written={result.targets_written} "
        f"acceptance={acc.passed}/{acc.eligible} (needed {acc.needed}) "
        f"inputs_sha256={result.inputs_sha256[:12]}"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--shop-id", required=True)
    ap.add_argument("--as-of", type=date.fromisoformat)
    ap.add_argument("--measure-start", type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
