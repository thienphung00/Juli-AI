"""Rewrite cancellation spellings to ``cancelled`` and report missing create times (P70, E15).

Before P70 the ORDER_STATUS_CHANGE webhook stored TikTok's ``CANCEL`` lower-cased as
``cancel`` (the ETL map knew only ``CANCELLED``), and a webhook that created an order
row left ``tiktok_created_at`` NULL. New writes map every cancellation spelling through
``models/order_status.canonical_order_status``; this operator command brings the rows
stored before that into line:

- ``silver.orders.status``: ONLY a cancellation spelled other than ``cancelled``
  (``cancel``, ``canceled``, ``CANCEL``, ``CANCELLED`` ...) is rewritten to
  ``cancelled``. No other status is touched -- readers depend on the stored values.
- ``silver.orders.tiktok_created_at IS NULL``: counted, never written. The fixed poll
  fills it from Order Search the next time it processes the order. An order whose
  poll event was already claimed (same TikTok ``update_time``) is not processed again
  until it changes on TikTok. For each such shop the command PRINTS -- never runs --
  the operator step that makes the next poll re-read its window: advancing the shop's
  ``tiktok.orders.raw`` dedup epoch (``IngestDedupEpochsRepo.advance``, the #1968
  recovery). That re-claims only the orders the poll's next search returns (its
  ``update_time`` window), not the shop's whole history.

``public.orders`` is the pre-#607 legacy table, write-blocked since migration 025;
the webhook never writes it, so it is not touched.

It is a DATA change, so it is not a migration. Run::

    python -m juli_backend.services.etl.order_status_repair                 # dry run
    python -m juli_backend.services.etl.order_status_repair --apply
    python -m juli_backend.services.etl.order_status_repair --shop <uuid> [--apply]

It connects as the migration owner (``migration_database_url``: ``DATABASE_DIRECT_URL``
then ``DATABASE_URL``) like ``payload_cleanup``. Each shop is processed in its own
transaction under its own scope (``with_shop_scope``) and every statement also filters
on ``shop_id``. A dry run does the same work and rolls each shop back. It prints counts
per shop (shop id, stored spelling, count), never order ids or payloads. Idempotent: a
second ``--apply`` changes zero rows.
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
from juli_backend.models.order_status import CANCELLED, is_cancelled_status

TABLE = "silver.orders"
ORDERS_CHANNEL = "tiktok.orders.raw"


@dataclass
class ShopRepair:
    shop_id: uuid.UUID
    scanned: int = 0
    #: stored cancellation spelling -> rows rewritten to ``cancelled``
    normalised: dict[str, int] = field(default_factory=dict)
    missing_created_at: int = 0

    @property
    def changed(self) -> int:
        return sum(self.normalised.values())

    @property
    def touched(self) -> bool:
        return bool(self.normalised or self.missing_created_at)


#: The #1968 epoch advance as owner SQL (psql variables; no value is formatted in).
EPOCH_ADVANCE_SQL = """\\set shop_id '<shop uuid>'
\\set operator '<your name>'
INSERT INTO ingest_dedup_epochs (shop_id, channel, epoch, advanced_by, reason)
VALUES (:'shop_id', 'tiktok.orders.raw', 1, :'operator', 'E15 refill tiktok_created_at')
ON CONFLICT (shop_id, channel) DO UPDATE SET
    epoch = ingest_dedup_epochs.epoch + 1,
    advanced_by = EXCLUDED.advanced_by,
    reason = EXCLUDED.reason,
    advanced_at = now();"""


def epoch_advance_instructions(shop_id: uuid.UUID) -> str:
    """The documented operator step for one shop -- printed, never executed here."""
    lines = [
        f"    optional (owner decision) -- make the next poll re-read shop {shop_id}'s window:",
        "    python (as the owner, then commit): IngestDedupEpochsRepo.advance with",
        f"            shop_id=uuid.UUID('{shop_id}'),",
        f"            channel={ORDERS_CHANNEL!r}, operator='<your name>',",
        "            reason='E15 refill tiktok_created_at'",
        "    or psql as the owner:",
    ]
    lines += [
        "      " + line
        for line in EPOCH_ADVANCE_SQL.replace("<shop uuid>", str(shop_id)).splitlines()
    ]
    return "\n".join(lines)


@dataclass
class RepairReport:
    shops: list[ShopRepair] = field(default_factory=list)

    def render(self, *, applied: bool) -> str:
        verb = "changed" if applied else "would change"
        changed = sum(s.changed for s in self.shops)
        missing = sum(s.missing_created_at for s in self.shops)
        lines = [
            f"order_status_repair: {'APPLIED' if applied else 'DRY RUN'} over "
            f"{len(self.shops)} shop(s) on {TABLE}: {verb} {changed} cancellation "
            f"spelling(s) to {CANCELLED!r}; {missing} row(s) with NULL tiktok_created_at "
            "(reported only)"
        ]
        for shop in self.shops:
            if not shop.touched:
                continue
            lines.append(
                f"  shop {shop.shop_id}: scanned {shop.scanned}, {verb} {shop.changed}, "
                f"NULL tiktok_created_at {shop.missing_created_at}"
            )
            for stored, rows in sorted(shop.normalised.items()):
                lines.append(f"    status {stored!r} -> {CANCELLED!r}: {rows}")
            if shop.missing_created_at:
                lines.append(epoch_advance_instructions(shop.shop_id))
        return "\n".join(lines)


async def repair_shop(session: AsyncSession, shop_id: uuid.UUID) -> ShopRepair:
    """Rewrite one shop's cancellation spellings in the open transaction; the caller commits."""
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
            if stored == CANCELLED or not is_cancelled_status(stored):
                continue
            await session.execute(
                update(Order)
                .where(Order.shop_id == shop_id, Order.status == stored)
                .values(status=CANCELLED)
                .execution_options(synchronize_session=False)
            )
            result.normalised[str(stored)] = int(rows)
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
        description="Rewrite cancellation spellings in silver.orders.status (cancel, "
        "canceled, CANCEL ...) to 'cancelled' and report orders with NULL "
        "tiktok_created_at (fast track P70, E15). Dry run unless --apply.",
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
