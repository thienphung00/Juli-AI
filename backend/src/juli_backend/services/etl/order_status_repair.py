"""Normalise stored order statuses and report orders missing their create time (P70, E15).

Before P70 the ORDER_STATUS_CHANGE webhook stored TikTok's status lower-cased when the
ETL map did not know it -- ``CANCEL`` became ``cancel`` -- and a webhook that created
an order row left ``tiktok_created_at`` NULL. New writes go through
``models/order_status.canonical_order_status``; this operator command brings the
rows stored before that into line:

- ``silver.orders.status``: every value the shared map recognises but is not already
  canonical (``cancel``, ``CANCELLED``, ``awaiting_shipment``, ``on_hold`` stays) is
  rewritten to its canonical value. A value the map does NOT recognise is left as it
  is and counted as ``unrecognised`` -- rewriting it to ``unknown`` would lose what
  TikTok sent; extend the map instead. (The poll also heals such a row: a
  non-canonical stored status counts as a gap it fills.)
- ``silver.orders.tiktok_created_at IS NULL``: counted, never written. The fixed poll
  fills it from Order Search the next time it processes the order. An order whose
  poll event was already claimed (same TikTok ``update_time``) is not processed again
  until it changes on TikTok; to re-read the current poll window now, an operator
  advances the shop's ``tiktok.orders.raw`` dedup epoch (``IngestDedupEpochsRepo
  .advance``, the #1968 recovery). This command never moves a cursor or an epoch.

``public.orders`` is the pre-#607 legacy table, write-blocked since migration 025;
the webhook never writes it, so it is not touched.

It is a DATA change, so it is not a migration. Run::

    python -m juli_backend.models.order_status_repair                 # dry run
    python -m juli_backend.models.order_status_repair --apply
    python -m juli_backend.models.order_status_repair --shop <uuid> [--apply]

It connects as the migration owner (``migration_database_url``: ``DATABASE_DIRECT_URL``
then ``DATABASE_URL``) like ``payload_cleanup``. Each shop is processed in its own
transaction under its own scope (``with_shop_scope``) and every statement also filters
on ``shop_id``. A dry run does the same work and rolls each shop back. It prints counts
per shop (shop id, status value -> canonical value, count), never order ids or
payloads. Idempotent: a second ``--apply`` changes zero rows.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import Order, Shop
from juli_backend.models.order_status import (
    CANONICAL_ORDER_STATUSES,
    known_order_status,
)

TABLE = "silver.orders"


@dataclass
class ShopRepair:
    shop_id: uuid.UUID
    scanned: int = 0
    #: ``(stored value, canonical value) -> rows``
    normalised: dict[tuple[str, str], int] = field(default_factory=dict)
    #: ``stored value -> rows`` the map does not recognise (left unchanged)
    unrecognised: dict[str, int] = field(default_factory=dict)
    missing_created_at: int = 0

    @property
    def changed(self) -> int:
        return sum(self.normalised.values())

    @property
    def touched(self) -> bool:
        return bool(self.normalised or self.unrecognised or self.missing_created_at)


@dataclass
class RepairReport:
    shops: list[ShopRepair] = field(default_factory=list)

    def render(self, *, applied: bool) -> str:
        verb = "changed" if applied else "would change"
        changed = sum(s.changed for s in self.shops)
        missing = sum(s.missing_created_at for s in self.shops)
        unrecognised = sum(sum(s.unrecognised.values()) for s in self.shops)
        lines = [
            f"order_status_repair: {'APPLIED' if applied else 'DRY RUN'} over "
            f"{len(self.shops)} shop(s) on {TABLE}: {verb} {changed} status(es); "
            f"{unrecognised} unrecognised (left as is); "
            f"{missing} with NULL tiktok_created_at (reported only; the poll fills them)"
        ]
        for shop in self.shops:
            if not shop.touched:
                continue
            lines.append(
                f"  shop {shop.shop_id}: scanned {shop.scanned}, {verb} {shop.changed}, "
                f"NULL tiktok_created_at {shop.missing_created_at}"
            )
            for (stored, canonical), rows in sorted(shop.normalised.items()):
                lines.append(f"    status {stored!r} -> {canonical!r}: {rows}")
            for stored, rows in sorted(shop.unrecognised.items()):
                lines.append(f"    status {stored!r} unrecognised: {rows}")
        return "\n".join(lines)


async def repair_shop(session: AsyncSession, shop_id: uuid.UUID) -> ShopRepair:
    """Normalise one shop's statuses in the session's open transaction; the caller commits."""
    result = ShopRepair(shop_id=shop_id)
    async with with_shop_scope(session, shop_id):
        counts = (
            await session.execute(
                select(Order.status, func.count())
                .where(Order.shop_id == shop_id)
                .group_by(Order.status)
            )
        ).all()
        for stored, rows in counts:
            result.scanned += int(rows)
            if stored in CANONICAL_ORDER_STATUSES:
                continue
            canonical = known_order_status(stored)
            if canonical is None:
                result.unrecognised[str(stored)] = int(rows)
                continue
            await session.execute(
                update(Order)
                .where(Order.shop_id == shop_id, Order.status == stored)
                .values(status=canonical)
                .execution_options(synchronize_session=False)
            )
            result.normalised[(str(stored), canonical)] = int(rows)
        result.missing_created_at = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Order)
                    .where(Order.shop_id == shop_id, Order.tiktok_created_at.is_(None))
                )
            ).scalar_one()
        )
    return result


async def shop_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Every shop id (identifiers only; the owner connection sees every shop)."""
    return list((await session.execute(select(Shop.id).order_by(Shop.id))).scalars())


async def run_repair(
    factory: Callable[[], AsyncSession],
    *,
    apply: bool,
    only: Sequence[uuid.UUID] | None = None,
    list_shops: Callable[[AsyncSession], Awaitable[list[uuid.UUID]]] = shop_ids,
) -> RepairReport:
    """Repair every shop (or ``only``), one transaction per shop; roll back unless ``apply``."""
    report = RepairReport()
    async with factory() as session:
        targets = list(only) if only else await list_shops(session)
        await session.rollback()
    for shop_id in targets:
        async with factory() as session:
            shop_result = await repair_shop(session, shop_id)
            if apply:
                await session.commit()
            else:
                await session.rollback()
        report.shops.append(shop_result)
    return report


async def _can_update(session: AsyncSession) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    sql = "SELECT has_table_privilege('silver.orders', 'UPDATE')"
    return bool((await session.execute(text(sql))).scalar_one())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="order_status_repair",
        description="Rewrite non-canonical silver.orders.status values to the shared "
        "canonical vocabulary and report orders with NULL tiktok_created_at "
        "(fast track P70, E15). Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="commit the changes")
    parser.add_argument(
        "--shop", action="append", type=uuid.UUID, default=None, help="limit to this shop id"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="owner connection (default: DATABASE_DIRECT_URL, then DATABASE_URL)",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    from juli_backend.core.config import async_database_url, migration_database_url

    url = async_database_url(args.database_url or migration_database_url())
    engine = create_async_engine(url, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.apply and not await _can_update(session):
                print(
                    "order_status_repair: this role cannot UPDATE silver.orders; "
                    "run it with the migration owner connection (DATABASE_DIRECT_URL).",
                    file=sys.stderr,
                )
                return 2
        report = await run_repair(factory, apply=args.apply, only=args.shop)
    finally:
        await engine.dispose()
    print(report.render(applied=args.apply))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
