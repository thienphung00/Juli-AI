"""A backfill that runs out of budget keeps what it finished (#1665).

Uses the REAL CallBudgetGovernor rather than a double: a hand-rolled budget
omitted `structured_log_fields`, which the orchestrator calls, so the fake
would have proved the orchestrator's shape rather than its behaviour.

WHY THIS EXISTS. `analytics_backfill_topup` had 0 successes in 7 days and wrote
nothing, while `ops.analytics_backfill_partitions` held 571 rows of which ALL
571 were incomplete. `mark_complete` had been called many times and committed
never: the whole run was one transaction, the task's 300s budget expired, and
everything rolled back. Each run then started from zero, so a 157-day backlog
could never shrink.

The resumable-checkpoint design was already correct. It was inert.
"""

from __future__ import annotations

from datetime import date

import pytest

from juli_backend.services.analytics_backfill.budget import CallBudgetGovernor
from juli_backend.services.analytics_backfill.orchestrator import (
    backfill_analytics_history,
)


class _PartitionsRepo:
    def __init__(self) -> None:
        self.completed: list[tuple[str, date]] = []

    async def list_completed(self, _shop_id, _bucket, _start, _end):
        # Underscore-prefixed rather than suppressed. The arity is the contract
        # the orchestrator depends on and is kept; a per-line suppression would
        # be a new debt identity for a double that simply ignores its inputs.
        # (Naming the rule code here would itself be read as a suppression --
        # the detector scans comment text, which is how this comment's first
        # draft tripped the ratchet.)
        return []


@pytest.mark.asyncio
async def test_each_completed_partition_is_committed_before_the_next_runs(monkeypatch):
    """The fix: progress is durable per partition, not per run.

    Asserts the ORDER — a commit lands between partitions — because that is what
    makes a later timeout keep the earlier work. A commit only at the end would
    satisfy "a commit happened" and still lose everything.
    """
    import uuid

    from juli_backend.services.analytics_backfill import orchestrator as orch

    events: list[str] = []

    async def run_partition(bucket: str, partition_date: date) -> None:
        events.append(f"ran:{partition_date.isoformat()}")

    async def on_partition_complete() -> None:
        events.append("commit")

    monkeypatch.setattr(orch, "AnalyticsBackfillPartitionsRepo", lambda session: _PartitionsRepo())

    await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        budget=CallBudgetGovernor(),
        buckets=("revenue",),
        concurrency_limit=1,
        run_partition=run_partition,
        on_partition_complete=on_partition_complete,
    )

    assert events, "no partitions ran; the test proves nothing"
    # A commit must follow every run, not just trail the batch.
    runs = [i for i, e in enumerate(events) if e.startswith("ran:")]
    commits = [i for i, e in enumerate(events) if e == "commit"]
    assert len(commits) == len(runs), (
        f"expected one commit per partition, got {len(commits)} for {len(runs)} runs: {events}"
    )
    for run_i in runs[:-1]:
        assert any(c > run_i for c in commits), (
            f"no commit after the partition at index {run_i}; a run cut short here would "
            f"lose it: {events}"
        )


@pytest.mark.asyncio
async def test_it_still_runs_without_a_commit_hook(monkeypatch):
    """The hook is optional, so existing callers and tests are unaffected."""
    import uuid

    from juli_backend.services.analytics_backfill import orchestrator as orch

    ran: list[date] = []

    async def run_partition(bucket: str, partition_date: date) -> None:
        ran.append(partition_date)

    monkeypatch.setattr(orch, "AnalyticsBackfillPartitionsRepo", lambda session: _PartitionsRepo())

    await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        budget=CallBudgetGovernor(),
        buckets=("revenue",),
        concurrency_limit=1,
        run_partition=run_partition,
    )
    assert len(ran) == 2


@pytest.mark.asyncio
async def test_a_failed_partition_does_not_commit(monkeypatch):
    """A partition that raised has nothing worth making durable.

    Committing a failed partition would mark it done, and the resumable design
    would then skip it forever — losing the day silently, which is worse than
    the timeout this fix removes.
    """
    import uuid

    from juli_backend.services.analytics_backfill import orchestrator as orch

    commits = 0

    async def run_partition(bucket: str, partition_date: date) -> None:
        raise RuntimeError("partition blew up")

    async def on_partition_complete() -> None:
        nonlocal commits
        commits += 1

    monkeypatch.setattr(orch, "AnalyticsBackfillPartitionsRepo", lambda session: _PartitionsRepo())

    await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        budget=CallBudgetGovernor(),
        buckets=("revenue",),
        concurrency_limit=1,
        run_partition=run_partition,
        on_partition_complete=on_partition_complete,
    )
    assert commits == 0, "a failed partition must not be committed as progress"


@pytest.mark.asyncio
async def test_a_failed_partition_rolls_back_so_the_next_one_can_run(monkeypatch):
    """The cascade this prevents was observed in production, twice.

    On 2026-09-06 the first run on the fixed release completed 32 partitions and
    then failed 31 consecutively; the second run completed none. A partition that
    fails on a database error leaves the shared AsyncSession rolled back, and
    every partition after it dies on PendingRollbackError before doing any work
    of its own. Catching per-partition is not enough — the session has to be made
    usable again.
    """
    import uuid

    from juli_backend.services.analytics_backfill import orchestrator as orch

    events: list[str] = []
    calls = {"n": 0}

    async def run_partition(bucket: str, partition_date: date) -> None:
        calls["n"] += 1
        events.append(f"ran:{partition_date.isoformat()}")
        if calls["n"] == 1:
            raise RuntimeError("first partition hits a database error")

    async def on_partition_complete() -> None:
        events.append("commit")

    async def on_partition_failed() -> None:
        events.append("rollback")

    monkeypatch.setattr(orch, "AnalyticsBackfillPartitionsRepo", lambda session: _PartitionsRepo())

    await backfill_analytics_history(
        session=object(),
        shop_id=uuid.uuid4(),
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        budget=CallBudgetGovernor(),
        buckets=("revenue",),
        concurrency_limit=1,
        run_partition=run_partition,
        on_partition_complete=on_partition_complete,
        on_partition_failed=on_partition_failed,
    )

    assert "rollback" in events, (
        f"a failed partition did not roll back; the session stays poisoned and every "
        f"partition after it fails on PendingRollbackError: {events}"
    )
    # The rollback must precede the partitions that follow, or it does not help them.
    rollback_at = events.index("rollback")
    later_runs = [i for i, e in enumerate(events) if e.startswith("ran:") and i > rollback_at]
    assert later_runs, f"no partition ran after the failure, so the cascade is untested: {events}"
    assert events.count("commit") == 2, (
        f"the two partitions after the failure should each have committed: {events}"
    )
