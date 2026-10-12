"""Count the database round trips a block of code makes (P22).

On the production VPS one round trip to the Supabase pooler costs ~220 ms, so
an Ops request's latency is, to first order, its number of round trips. This
counts the things that each cost one:

- every statement the DBAPI cursor executes (``before_cursor_execute``) --
  reads, writes, ``set_config(...)`` for tenant scope, ``SET LOCAL ROLE``,
  ``SELECT current_user``;
- every transaction boundary: ``BEGIN`` (asyncpg sends it as its own message
  before the first statement), ``COMMIT`` and ``ROLLBACK``. ``SAVEPOINT`` /
  ``RELEASE`` / ``ROLLBACK TO`` are counted ONCE, as the statements the dialect
  executes through the cursor (P29: they used to be counted twice, once more
  from the savepoint event, so a savepoint pair read as four round trips).

Not counted, and real in production: asyncpg's ``prepare`` of a statement text
the connection has not seen yet (one extra round trip per new statement shape
per connection). ``tests/integration/test_ops_round_trips.py`` therefore counts
the second, warm call.

Usage::

    counter = SqlCounter.attach(engine)      # an AsyncEngine or a sync Engine
    with counter.measure() as seen:
        ...                                  # the code under test
    assert seen.round_trips <= 4, seen.describe()
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass
class Seen:
    """What one measured block sent to the database, in order."""

    events: list[str] = field(default_factory=list)

    @property
    def statements(self) -> int:
        return sum(1 for e in self.events if not e.startswith("<"))

    @property
    def transactions(self) -> int:
        """Transaction-control round trips: BEGIN / COMMIT / ROLLBACK."""
        return sum(1 for e in self.events if e.startswith("<"))

    @property
    def round_trips(self) -> int:
        return len(self.events)

    def describe(self) -> str:
        lines = [
            f"{self.round_trips} round trips "
            f"({self.statements} statements + {self.transactions} transaction control):"
        ]
        lines += [f"  {i + 1:>2}. {e}" for i, e in enumerate(self.events)]
        return "\n".join(lines)


def _one_line(statement: str) -> str:
    text = " ".join(statement.split())
    return text if len(text) <= 160 else text[:157] + "..."


class SqlCounter:
    """Engine listeners feeding whichever :class:`Seen` is currently open."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._current: Seen | None = None

    @classmethod
    def attach(cls, engine: Engine | AsyncEngine) -> SqlCounter:
        sync_engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
        counter = cls(sync_engine)
        event.listen(sync_engine, "before_cursor_execute", counter._on_statement)
        event.listen(sync_engine, "begin", counter._on_begin)
        event.listen(sync_engine, "commit", counter._on_commit)
        event.listen(sync_engine, "rollback", counter._on_rollback)
        return counter

    def detach(self) -> None:
        for name, fn in (
            ("before_cursor_execute", self._on_statement),
            ("begin", self._on_begin),
            ("commit", self._on_commit),
            ("rollback", self._on_rollback),
        ):
            event.remove(self._engine, name, fn)

    @contextmanager
    def measure(self) -> Iterator[Seen]:
        seen = Seen()
        self._current = seen
        try:
            yield seen
        finally:
            self._current = None

    def _record(self, entry: str) -> None:
        if self._current is not None:
            self._current.events.append(entry)

    def _on_statement(self, conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        self._record(_one_line(statement))

    def _on_begin(self, conn: Any) -> None:
        self._record("<BEGIN>")

    def _on_commit(self, conn: Any) -> None:
        self._record("<COMMIT>")

    def _on_rollback(self, conn: Any) -> None:
        self._record("<ROLLBACK>")


__all__ = ["Seen", "SqlCounter"]
