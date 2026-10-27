"""Copy ``tiktok_product_id`` into ``platform_product_id`` on the production-write tables.

ADR-116 §6, DECISIONS D76 (NDA work, PR 5). Migration ``106_write_platform_columns`` added
``platform`` (default ``'tiktok'``, so every existing row is already a TikTok row) and a
nullable ``platform_product_id`` to ``production_write_authorizations`` and
``production_write_audit``. Code writes both product columns from that release on and reads
``COALESCE(platform_product_id, tiktok_product_id)``, so rows written before it keep matching
without this step. This operator command fills the new column on those rows so a later
contract migration can drop the fallback.

It is a DATA change, so it is not a migration (``migration_additive_gate.py`` refuses data
UPDATEs from a release), and ``production_write_audit`` is append-only for ``juli_app`` (no
UPDATE grant, by design): it runs as the migration owner (``migration_database_url``:
``DATABASE_DIRECT_URL`` then ``DATABASE_URL``), like ``services/privacy/payload_cleanup``::

    python -m juli_backend.services.operations.write_platform_backfill            # dry run
    python -m juli_backend.services.operations.write_platform_backfill --apply

Only ``platform_product_id`` changes, only where it is NULL and the row is a TikTok row; no
other column of an audit row is touched. One transaction; a dry run does the same work and
rolls back. It prints row counts per table, never ids. Idempotent: a second ``--apply``
changes zero rows.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

#: The two tables and the literal statement for each (fixed module constants).
TABLES: tuple[str, ...] = ("production_write_authorizations", "production_write_audit")
_SET = "SET platform_product_id = tiktok_product_id"
_WHERE = "WHERE platform_product_id IS NULL AND platform = 'tiktok'"
_UPDATE_SQL: dict[str, str] = {
    table: f"UPDATE public.{table} {_SET} {_WHERE}"  # module constants only
    for table in TABLES
}
_PRIVILEGE_SQL = "SELECT " + " AND ".join(
    f"has_table_privilege('public.{table}', 'UPDATE')" for table in TABLES
)


async def backfill(session: AsyncSession) -> dict[str, int]:
    """Run both UPDATEs in the session's open transaction; the caller commits or not."""
    counts: dict[str, int] = {}
    for table in TABLES:
        result = await session.execute(text(_UPDATE_SQL[table]))
        counts[table] = int(getattr(result, "rowcount", 0) or 0)
    return counts


async def run_backfill(factory: Callable[[], AsyncSession], *, apply: bool) -> dict[str, int]:
    async with factory() as session:
        counts = await backfill(session)
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return counts


def render(counts: dict[str, int], *, applied: bool) -> str:
    verb = "changed" if applied else "would change"
    lines = [f"write_platform_backfill: {'APPLIED' if applied else 'DRY RUN'}"]
    lines += [f"  public.{table}: {verb} {counts.get(table, 0)}" for table in TABLES]
    return "\n".join(lines)


async def _can_update(session: AsyncSession) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool((await session.execute(text(_PRIVILEGE_SQL))).scalar_one())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="write_platform_backfill",
        description="Fill platform_product_id from tiktok_product_id on the production-write "
        "tables (ADR-116 §6, migration 106). Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="commit the changes")
    parser.add_argument(
        "--database-url",
        default=None,
        help="owner connection (default: DATABASE_DIRECT_URL, then DATABASE_URL)",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    from juli_backend.core.config import async_database_url, migration_database_url

    engine = create_async_engine(async_database_url(args.database_url or migration_database_url()))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.apply and not await _can_update(session):
                print(
                    "write_platform_backfill: this role cannot UPDATE the production-write "
                    "tables; run it with the migration owner connection (DATABASE_DIRECT_URL).",
                    file=sys.stderr,
                )
                return 2
        counts = await run_backfill(factory, apply=args.apply)
    finally:
        await engine.dispose()
    print(render(counts, applied=args.apply))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
