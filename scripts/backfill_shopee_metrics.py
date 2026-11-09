"""P97 D85.2: build the materialized Shopee metrics for shops that already have data.

    python scripts/backfill_shopee_metrics.py --database-url postgresql://... --shop-id UUID
    python scripts/backfill_shopee_metrics.py --database-url postgresql://... --all-shopee
        [--from 2026-08-01] [--to 2026-11-09] [--dry-run]

Run once after migration 123 (``shopee_shop_metrics_daily``, ``shopee_product_metrics_daily``) and
whenever the day rows may have drifted (a failed hook is logged; this repairs it). Every day the
shop has order lines or daily Shopee rows for is recomputed from the raw tables inside the shop's
tenant scope and upserted, so the script is safe to repeat. Prints counts only -- no order id,
product name or amount.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Shop
from juli_backend.services.shopee_analytics import materialize


async def run(args: argparse.Namespace) -> int:
    engine = create_async_engine(async_database_url(args.database_url))
    failures = 0
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            if args.all_shopee:
                shop_ids = list(
                    (await session.execute(select(Shop.id).where(Shop.platform == "shopee")))
                    .scalars()
                    .all()
                )
            else:
                shop_ids = [args.shop_id]
        for shop_id in shop_ids:
            async with maker() as session:
                try:
                    async with with_shop_scope(session, shop_id):
                        days = [
                            d
                            for d in await materialize.data_days(session, shop_id)
                            if (not args.start or d >= args.start)
                            and (not args.end or d <= args.end)
                        ]
                        if args.dry_run:
                            print(f"{shop_id}: {len(days)} day(s) would be rebuilt")
                            continue
                        written = await materialize.rebuild_days(session, shop_id, days)
                        await session.commit()
                    print(f"{shop_id}: {written} day(s) rebuilt")
                except (
                    SQLAlchemyError,
                    ArithmeticError,
                    LookupError,
                    TypeError,
                    ValueError,
                ) as exc:
                    # report and go on to the next shop
                    failures += 1
                    await session.rollback()
                    print(f"{shop_id}: FAILED ({type(exc).__name__})")
    finally:
        await engine.dispose()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--shop-id", type=uuid.UUID)
    group.add_argument("--all-shopee", action="store_true")
    parser.add_argument("--from", dest="start", type=date.fromisoformat)
    parser.add_argument("--to", dest="end", type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
