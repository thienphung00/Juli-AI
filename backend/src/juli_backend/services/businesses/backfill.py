"""The automatic business backfill (P101 W1, owner rule T2: no hand-run step).

Every shop made before migration 130 gets its own business (the shop's id, named after the shop),
its owner -- unless removed from the shop -- and its other active ``shop_members`` as members, and
Juli's TikTok sandbox shop ``kind = 'sandbox'`` (a ``sandbox_write`` credential, no
``production_read`` credential, no ``production_write_shops`` row). Once no shop is left without a
business, ``CHECK (business_id IS NOT NULL)`` is added and validated: the additive gate refuses
``SET NOT NULL`` in a migration, and this keeps the step automatic.

The SQL is migration 130's reviewed SECURITY DEFINER functions (``businesses_backfill_batch``,
``businesses_require_shop_business``), called as ``juli_ops``. Each batch is its own transaction
under a transaction-scoped advisory lock, so a second worker skips instead of waiting; a batch
takes its shops ``FOR UPDATE SKIP LOCKED``. Idempotent: once done, a run is two cheap reads.

Runs from the worker (``workers/tasks/businesses_backfill.py``: beat every 10 min and at worker
start). Break-glass, the same function by hand::

    python -m juli_backend.services.businesses.backfill

Logs counts only. Before migration 130 is applied (or on SQLite) it does nothing.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.ops.access import is_sqlite, ops_role

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
#: A run stops after this many batches (500 x 200 = 100 000 shops); the next run continues.
MAX_BATCHES = 200
#: ``pg_try_advisory_xact_lock`` key: fixed, arbitrary, used by nothing else (``"juli-biz"``).
ADVISORY_LOCK_KEY = 0x6A756C6962697A

_FUNCTION_PRESENT = text(
    "SELECT to_regprocedure('public.businesses_backfill_batch(integer)') IS NOT NULL"
)
_LOCK = text("SELECT pg_try_advisory_xact_lock(:key)")
_BATCH = text("SELECT * FROM public.businesses_backfill_batch(:limit)")
_REQUIRE = text("SELECT public.businesses_require_shop_business()")


@dataclass
class BackfillResult:
    shops: int = 0
    owners: int = 0
    members: int = 0
    sandbox: int = 0
    batches: int = 0
    #: ``CHECK (business_id IS NOT NULL)`` is in force.
    required: bool = False
    #: Why nothing ran: ``sqlite`` | ``not_migrated`` | ``locked``; None when it ran.
    skipped: str | None = None

    def as_log(self) -> dict[str, Any]:
        return {
            "shops": self.shops,
            "owners": self.owners,
            "members": self.members,
            "sandbox": self.sandbox,
            "batches": self.batches,
            "required": self.required,
            "skipped": self.skipped,
        }


async def _migrated(session: AsyncSession) -> bool:
    async with ops_role(session, transaction_ends_after=True):
        present = bool((await session.execute(_FUNCTION_PRESENT)).scalar())
    await session.rollback()
    return present


async def _locked_call(session: AsyncSession, statement: Any, params: dict[str, Any]) -> Any:
    """``statement`` in its own transaction as ``juli_ops`` under the advisory lock.

    Returns the first row, or None when another worker holds the lock (nothing ran).
    """
    async with ops_role(session, transaction_ends_after=True):
        got = bool((await session.execute(_LOCK, {"key": ADVISORY_LOCK_KEY})).scalar())
        row = (await session.execute(statement, params)).one() if got else None
    if row is None:
        await session.rollback()
        return None
    await session.commit()
    return row


async def run_backfill(
    session_factory: Callable[[], Any],
    *,
    batch_size: int = BATCH_SIZE,
    max_batches: int = MAX_BATCHES,
) -> BackfillResult:
    """Backfill until no shop is left without a business, then require one. Logs counts only."""
    result = BackfillResult()
    async with session_factory() as session:
        if is_sqlite(session):
            result.skipped = "sqlite"
        elif not await _migrated(session):
            result.skipped = "not_migrated"
        else:
            while result.batches < max_batches:
                row = await _locked_call(session, _BATCH, {"limit": batch_size})
                if row is None:
                    result.skipped = "locked"
                    break
                result.batches += 1
                result.shops += int(row[0])
                result.owners += int(row[1])
                result.members += int(row[2])
                result.sandbox += int(row[3])
                if int(row[0]) < batch_size:
                    break
            if result.skipped is None:
                row = await _locked_call(session, _REQUIRE, {})
                if row is None:
                    result.skipped = "locked"
                else:
                    result.required = bool(row[0])
    logger.info("businesses_backfill", extra=result.as_log())
    return result


def main() -> int:  # pragma: no cover - break-glass CLI, the worker task is the normal path
    import os

    from juli_backend.core.config import async_database_url
    from juli_backend.database.database import ensure_worker_session_factory

    logging.basicConfig(level=logging.INFO)
    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        sys.stderr.write("DATABASE_URL is not set\n")
        return 2
    # services depend on database/core only (import boundaries): no workers helper here.
    factory = ensure_worker_session_factory(async_database_url(raw_url))
    result = asyncio.run(run_backfill(factory))
    sys.stdout.write(f"{result.as_log()}\n")  # counts only, for the operator
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
