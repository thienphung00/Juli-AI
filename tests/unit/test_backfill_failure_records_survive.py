"""A partition's failure record has to outlive the rollback that follows it (#1673).

WHY THIS EXISTS. #1668 made a failed partition roll back, so one database error
stopped poisoning every partition behind it. That was right, and it was also a
regression: `mark_failed` flushes and never commits, so the rollback threw the
runner's own failure record away.

The result was failure bookkeeping that was write-only. In production, across
three consecutive runs on the fixed release:

  - the same 30 in-window `live` partitions failed on every single run
  - `attempt_count` stayed frozen at its pre-#1668 value (1..5)
  - `updated_at` stayed frozen at 04:27, before the deploy
  - #1672's `retryable=False` — the mechanism meant to stop a 401 being retried
    forever — never reached a single row, so #1672 was inert in production

Completions committed and persisted (554 -> 562 -> 570, +8 per run) while
failures persisted nothing. That asymmetry is exactly what the bug predicts,
and it is why the backfill could not converge: it re-learned the same 30
failures every run and spent its 300s budget doing it.

These tests model flush/rollback/commit faithfully rather than counting calls,
because "mark_failed was called" was true throughout the outage. What was false
was that anything survived.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest

from juli_backend.services.analytics_backfill.orchestrator import (
    persist_partition_failure,
)


class _Session:
    """Models the transaction semantics the bug turned on.

    `flush` stages; `rollback` discards what is staged; `commit` makes it
    durable. A double that merely records calls cannot express this bug — under
    it, the broken and fixed orderings look identical.
    """

    def __init__(self) -> None:
        self.staged: list[tuple[str, date]] = []
        self.durable: list[tuple[str, date]] = []
        self.events: list[str] = []

    async def flush(self) -> None:
        self.events.append("flush")

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.staged.clear()

    async def commit(self) -> None:
        self.events.append("commit")
        self.durable.extend(self.staged)
        self.staged.clear()


class _PartitionsRepo:
    def __init__(self, session: _Session) -> None:
        self._session = session
        self.marked: list[tuple[str, date, str, bool]] = []

    async def mark_failed(
        self,
        _shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
        error: str,
        *,
        retryable: bool = True,
    ) -> None:
        # Mirrors the real repository: stage the row and flush. No commit.
        # That single fact is what the rollback used to erase.
        self.marked.append((bucket, partition_date, error, retryable))
        self._session.staged.append((bucket, partition_date))
        await self._session.flush()


@pytest.fixture(autouse=True)
def _no_op_shop_scope(monkeypatch):
    """`reapply_shop_scope` needs a real connection; the order under test does not."""
    from juli_backend.services.analytics_backfill import orchestrator as orch

    async def _noop(_session, _shop_id) -> None:
        return None

    monkeypatch.setattr(orch, "reapply_shop_scope", _noop)


async def _run(session: _Session, repo: _PartitionsRepo, exc: BaseException) -> None:
    await persist_partition_failure(
        session,
        session_lock=asyncio.Lock(),
        partitions_repo=repo,
        shop_id=uuid.uuid4(),
        bucket="live",
        partition_date=date(2026, 9, 1),
        exc=exc,
    )


@pytest.mark.asyncio
async def test_the_failure_record_is_durable_after_the_rollback():
    """The regression itself: the row must exist once the dust settles.

    Under the #1668 ordering this list is empty — the record was written into a
    transaction that was then discarded.
    """
    session = _Session()
    repo = _PartitionsRepo(session)

    await _run(session, repo, RuntimeError("partition blew up"))

    assert session.durable == [("live", date(2026, 9, 1))], (
        f"the failure record did not survive; nothing was learned from this failure "
        f"and the partition will fail identically on every future run: {session.events}"
    )
    assert not session.staged, "a staged-but-uncommitted record is the bug, not the fix"


@pytest.mark.asyncio
async def test_the_rollback_comes_first():
    """Order, not presence. Writing then rolling back is exactly what broke."""
    session = _Session()
    repo = _PartitionsRepo(session)

    await _run(session, repo, RuntimeError("boom"))

    assert session.events.index("rollback") < session.events.index("flush"), (
        f"the record was written before the rollback, so the rollback discards it: {session.events}"
    )
    assert session.events.index("flush") < session.events.index("commit"), (
        f"the record must be written into the transaction that is committed: {session.events}"
    )


@pytest.mark.asyncio
async def test_the_session_is_left_usable_for_the_next_partition():
    """#1668's own guarantee must not regress while fixing its side effect."""
    session = _Session()
    repo = _PartitionsRepo(session)

    await _run(session, repo, RuntimeError("boom"))

    assert "rollback" in session.events, (
        "without the rollback the session stays poisoned and every partition behind "
        "this one dies on PendingRollbackError"
    )


@pytest.mark.asyncio
async def test_a_permanent_failure_is_recorded_as_not_retryable():
    """#1672 only works if its verdict reaches a row.

    In production it never did: `retryable=False` was written and rolled back on
    every run, which is why 28 catalog partitions kept re-attempting a 401.
    """
    session = _Session()
    repo = _PartitionsRepo(session)

    await _run(session, repo, RuntimeError("401 Client Error: Unauthorized"))

    assert repo.marked, "nothing was recorded"
    _bucket, _day, error, retryable = repo.marked[0]
    assert retryable is False, f"a 401 must stop being retried; recorded retryable={retryable}"
    assert "401" in error, f"the real exception text must be recorded, not a literal: {error!r}"
    assert session.durable, "the not-retryable verdict must be committed to matter"


@pytest.mark.asyncio
async def test_a_transient_failure_stays_retryable():
    """The conservative half of #1672: unrecognised failures keep their retry."""
    session = _Session()
    repo = _PartitionsRepo(session)

    await _run(session, repo, TimeoutError("vendor was slow"))

    _bucket, _day, error, retryable = repo.marked[0]
    assert retryable is True, "a timeout must stay retryable; a slow vendor is not a permanent fact"
    assert error.startswith("TimeoutError"), f"the exception type belongs in the record: {error!r}"
