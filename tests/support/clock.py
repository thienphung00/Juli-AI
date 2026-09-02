"""A controllable ``now()`` so tests never sleep."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SteppingClock:
    """Returns a fixed instant; ``advance`` moves it. Inject as a ``now`` callable."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now_value = start or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self.now_value

    def now_naive(self) -> datetime:
        return self.now_value.replace(tzinfo=None)

    def advance(self, **delta: float) -> datetime:
        self.now_value += timedelta(**delta)
        return self.now_value


__all__ = ["SteppingClock"]
