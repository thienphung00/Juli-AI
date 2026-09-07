"""One partition's exception must not strand its siblings mid-session (#1683).

WHY THIS EXISTS. `analytics_backfill_topup` died partway through the `live`
bucket with:

    IllegalStateChangeError: Method 'close()' can't be called here;
    method '_connection_for_bind()' is already in progress

followed by `greenlet is being finalized` and a garbage-collected asyncpg
connection. The four partition runners share ONE AsyncSession. `gather` ran
without `return_exceptions`, so the first task to raise propagated out
immediately while its siblings were still inside that session — and the
caller's `async with factory() as session:` then closed it underneath them.

The cost was not the crash. Buckets run `revenue, live, product, catalog`, so a
death inside `live` meant `catalog` was never attempted AT ALL — its rows sat
untouched from 2026-08-18 to 2026-09-07 carrying a stale 401 that a credential
refresh had long since fixed. Three weeks of a bucket silently not running,
because of an exception in a different bucket.

A serialised run (`concurrency_limit=1`) completed all four buckets with
`attempts=74, successes=74, failures=0`, which is what identified concurrency
as the trigger.

WHICH OF THESE IS THE REGRESSION TEST. Only the first. `run_partition_concurrent`
already catches `Exception`, so the failure hook was the only path by which one
could escape a task — and that is the path production took. The other two pass
against the unfixed orchestrator; they are kept as contracts, not as proof. The
third in particular states the three-week outage in terms of behaviour, which is
worth having written down even though it was never the thing that broke.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from juli_backend.services.analytics_backfill.budget import CallBudgetGovernor
from juli_backend.services.analytics_backfill.orchestrator import (
    backfill_analytics_history,
)


class _PartitionsRepo:
    async def list_completed(self, _shop_id, _bucket, _start, _end):
        return []


@pytest.fixture(autouse=True)
def _repo(monkeypatch):
    from juli_backend.services.analytics_backfill import orchestrator as orch

    monkeypatch.setattr(orch, "AnalyticsBackfillPartitionsRepo", lambda s: _PartitionsRepo())


async def _run(run_partition, *, on_failed=None, days=4):
    return await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, days),
        budget=CallBudgetGovernor(),
        buckets=("revenue",),
        concurrency_limit=4,
        run_partition=run_partition,
        on_partition_failed=on_failed,
    )


@pytest.mark.asyncio
async def test_a_hook_that_raises_does_not_abort_the_batch():
    """The exact production path: `on_partition_failed` raising inside the except block.

    It is called while handling another exception, so before the fix it escaped
    the task and took `gather` down with it.
    """
    ran: list[date] = []

    async def run_partition(_bucket: str, partition_date: date) -> None:
        ran.append(partition_date)
        if partition_date == date(2026, 9, 2):
            raise RuntimeError("partition hit a database error")

    async def on_failed(_bucket, _day, _exc) -> None:
        raise RuntimeError("recording the failure ALSO failed")

    result = await _run(run_partition, on_failed=on_failed)

    assert len(ran) == 4, (
        f"not every partition ran; a sibling was stranded when the batch aborted: {ran}"
    )
    assert result.completed_partitions == 3, (
        f"the three healthy partitions must still count as completed, got "
        f"{result.completed_partitions}"
    )


@pytest.mark.asyncio
async def test_every_partition_runs_even_when_one_raises_outright():
    """A partition raising is ordinary; it must not cancel the others."""
    ran: list[date] = []

    async def run_partition(_bucket: str, partition_date: date) -> None:
        ran.append(partition_date)
        if partition_date == date(2026, 9, 1):
            raise RuntimeError("boom")

    result = await _run(run_partition)

    assert len(ran) == 4, f"a partition was skipped after a sibling raised: {ran}"
    assert result.completed_partitions == 3


@pytest.mark.asyncio
async def test_later_buckets_are_still_reached_after_an_earlier_one_fails():
    """The three-week outage, stated as a test.

    `catalog` is last in `revenue, live, product, catalog`. A death inside an
    earlier bucket meant it was never attempted, and nobody could see that
    because the run simply ended.
    """
    seen: list[str] = []

    async def run_partition(bucket: str, _partition_date: date) -> None:
        seen.append(bucket)
        if bucket == "live":
            raise RuntimeError("live blows up, as it did for six weeks")

    await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        budget=CallBudgetGovernor(),
        buckets=("revenue", "live", "product", "catalog"),
        concurrency_limit=4,
        run_partition=run_partition,
    )

    assert "catalog" in seen, (
        f"catalog was never attempted after an earlier bucket raised — this is the "
        f"defect that left it stale from 2026-08-18 to 2026-09-07: {seen}"
    )
    assert seen.count("product") == 1, f"product was also skipped: {seen}"
