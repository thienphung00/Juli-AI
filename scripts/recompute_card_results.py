"""One card, one number (owner, 2026-11-14): store the engine result on every live Shopee card.

    python scripts/recompute_card_results.py --database-url postgresql://... --shop UUID
    python scripts/recompute_card_results.py --database-url postgresql://... --all
        [--dry-run] [--force]

Every non-terminal card (draft, sent, changes requested, planned, approved, executed -- the
measuring ones too) gets the simulation result of each of its versions, the figure Tự tạo and Kế
hoạch show (``shopee_recommendations.result_store``). A card whose stored result is still fresh
(same engine, same inputs) is left alone, so a second run writes nothing; ``--force`` recomputes
every card. An approved / executed card keeps the result it was approved with as
``result_at_approval`` the first time, so its measurement stays honest. ``--database-url`` defaults
to ``DATABASE_URL``. Prints counts per shop only -- no product, name or amount.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Shop
from juli_backend.services.shopee_recommendations import result_store
from juli_backend.services.shopee_recommendations.loader import load_env


async def recompute_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, int] | None:
    """The counts for one shop (the caller holds its scope and commits); ``None`` when the shop
    has no Shopee numbers."""
    env = await load_env(session, shop_id, now=now)
    if env is None:
        return None
    counts = await result_store.refresh_shop(
        session, shop_id, env, now=now, force=force, dry_run=dry_run
    )
    return counts.json()


def line(shop_id: uuid.UUID, counts: dict[str, int] | None, *, dry_run: bool) -> str:
    if counts is None:
        return f"{shop_id}: no Shopee numbers, skipped"
    verb = "would update" if dry_run else "updated"
    return (
        f"{shop_id}: {counts['cards']} card(s), {verb} {counts['updated']}, "
        f"fresh {counts['fresh']}, not estimable {counts['not_estimable']}, "
        f"failed {counts['failed']}"
    )


async def run(args: argparse.Namespace) -> int:
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        print("no --database-url and no DATABASE_URL")
        return 2
    engine = create_async_engine(async_database_url(url))
    failures = 0
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        if args.all:
            async with maker() as session:
                shop_ids = list(
                    (await session.execute(select(Shop.id).where(Shop.platform == "shopee")))
                    .scalars()
                    .all()
                )
        else:
            shop_ids = [args.shop]
        for shop_id in shop_ids:
            async with maker() as session:
                try:
                    async with with_shop_scope(session, shop_id):
                        counts = await recompute_shop(
                            session, shop_id, now=now, dry_run=args.dry_run, force=args.force
                        )
                        if args.dry_run:
                            await session.rollback()
                        else:
                            await session.commit()
                    print(line(shop_id, counts, dry_run=args.dry_run))
                    failures += bool(counts and counts["failed"])
                except (
                    SQLAlchemyError,
                    ArithmeticError,
                    LookupError,
                    TypeError,
                    ValueError,
                ) as exc:
                    failures += 1  # report and go on to the next shop
                    await session.rollback()
                    print(f"{shop_id}: FAILED ({type(exc).__name__})")
    finally:
        await engine.dispose()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--database-url")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--shop", type=uuid.UUID)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
