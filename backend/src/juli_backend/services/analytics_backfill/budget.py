"""Per-run Partner HTTP call-budget governor for analytics historical backfill.

Additive to ``RateLimiter`` (Redis token bucket) — this module counts total
Partner HTTP attempts per backfill run, including retries. It does **not**
replace endpoint-level rate limiting.

Caller contract (orchestrator #470):
- ``stopped_reason=budget`` means the run paused cleanly for a later resume.
  The caller must **not** mark the current partition complete.
- Each outbound Partner HTTP try (initial call or retry) must call
  ``record_attempt()`` once before the request is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

StoppedReason = Literal["budget", "complete", "error"]


class BudgetExhaustedError(Exception):
    """Raised when ``record_attempt`` would exceed the per-run hard limit."""


@dataclass
class CallBudgetGovernor:
    """Tracks Partner HTTP attempts for one analytics backfill run."""

    max_attempts: int = 400
    hard_limit: int = 499
    attempts: int = field(default=0, init=False)
    successes: int = field(default=0, init=False)
    failures: int = field(default=0, init=False)
    rate_limited: int = field(default=0, init=False)
    stopped_reason: StoppedReason | None = field(default=None, init=False)

    def record_attempt(self) -> None:
        """Count one Partner HTTP attempt. Raises when hard limit would be exceeded."""
        if self.attempts >= self.hard_limit:
            raise BudgetExhaustedError(
                f"Partner call budget exhausted ({self.attempts}/{self.hard_limit})"
            )
        self.attempts += 1

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1

    def record_rate_limited(self) -> None:
        self.rate_limited += 1

    def should_stop(self) -> bool:
        """True once the soft target is reached; orchestrator should exit the run loop."""
        return self.attempts >= self.max_attempts

    def remaining(self) -> int:
        """Attempts remaining before the soft target (not the hard limit)."""
        return max(0, self.max_attempts - self.attempts)

    @property
    def implies_partition_complete(self) -> bool:
        """Whether budget state allows marking the active partition complete."""
        return self.stopped_reason == "complete"

    def finish(self, stopped_reason: StoppedReason) -> dict[str, int | str | None]:
        """Set terminal stop reason and return structured log fields."""
        self.stopped_reason = stopped_reason
        return self.structured_log_fields()

    def structured_log_fields(self) -> dict[str, int | str | None]:
        return {
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "rate_limited": self.rate_limited,
            "stopped_reason": self.stopped_reason,
        }


def begin_run(
    max_attempts: int = 400,
    hard_limit: int = 499,
) -> CallBudgetGovernor:
    """Create a fresh per-run Partner call-budget governor (ADR-029 defaults)."""
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if hard_limit <= 0:
        raise ValueError("hard_limit must be positive")
    if max_attempts > hard_limit:
        raise ValueError("max_attempts must not exceed hard_limit")
    return CallBudgetGovernor(max_attempts=max_attempts, hard_limit=hard_limit)
