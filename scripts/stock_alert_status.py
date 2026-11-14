"""The Ops switch of a shop's stock e-mail (Part S): off | preview | on, and the alert days.

    python scripts/stock_alert_status.py --database-url postgresql://... --shop UUID \
        --status preview
    python scripts/stock_alert_status.py --shop UUID --status on [--days 7]
    python scripts/stock_alert_status.py --shop UUID --show

``preview`` sends the daily 07:00 GMT+7 e-mail to the Ops address only (``STOCK_ALERT_OPS_EMAIL``);
``on`` to every member, Ops in BCC for the first 14 days; ``off`` (the default) stops it. The
reviewer's sample shop refuses anything but ``off``. Writes the shop's ``shop_rules`` rows
(``stock_alert_status``, ``stock_alert_days``) as ``team``. ``--database-url`` defaults to
``DATABASE_URL``. Prints the shop id and the resulting settings only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.stock_alert import settings


async def run(args: argparse.Namespace) -> int:
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("no --database-url and no DATABASE_URL")
        return 2
    engine = create_async_engine(async_database_url(url))
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            async with with_shop_scope(session, args.shop):
                if args.show:
                    conf = await settings.load_settings(session, args.shop)
                else:
                    try:
                        conf = await settings.set_status(
                            session, args.shop, args.status, now=now, days=args.days
                        )
                    except ValueError as exc:
                        print(f"{args.shop}: refused ({exc})")
                        return 1
                    await session.commit()
        print(f"{args.shop}: status={conf.status} days={conf.days} sample={conf.sample}")
    finally:
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--database-url")
    parser.add_argument("--shop", type=uuid.UUID, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", choices=settings.STATUSES)
    group.add_argument("--show", action="store_true")
    parser.add_argument("--days", type=int)
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
