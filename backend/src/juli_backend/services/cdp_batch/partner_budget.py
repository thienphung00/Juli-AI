"""Per-run Partner API call-budget governor for CDP batch reconcile (CDP-A2-2).

Wraps analytics_backfill ``CallBudgetGovernor`` (ADR-029 prior art) with batch
defer semantics. On exhaustion the orchestrator must **not** mark the partition
or shop window complete; ``finish("partner_budget_exhausted")`` emits the structured
defer reason for observability.

Independent from ``PostgresIoBudgetGovernor`` (#617) — dual budgets stay separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from juli_backend.services.analytics_backfill.budget import (
    BudgetExhaustedError,
    CallBudgetGovernor,
    StoppedReason,
    begin_run,
)

DEFER_REASON = "partner_budget_exhausted"

PartnerBudgetStopReason = Literal["partner_budget_exhausted", "complete", "error"]


@dataclass
class PartnerApiBudgetGovernor:
    """Tracks Partner HTTP attempts for one CDP batch reconcile run."""

    _governor: CallBudgetGovernor = field(repr=False)
    _finish_reason: PartnerBudgetStopReason | None = field(default=None, init=False)

    @property
    def max_attempts(self) -> int:
        return self._governor.max_attempts

    @property
    def hard_limit(self) -> int:
        return self._governor.hard_limit

    @property
    def attempts(self) -> int:
        return self._governor.attempts

    @property
    def successes(self) -> int:
        return self._governor.successes

    @property
    def failures(self) -> int:
        return self._governor.failures

    @property
    def rate_limited(self) -> int:
        return self._governor.rate_limited

    @property
    def implies_partition_complete(self) -> bool:
        """Whether budget state allows marking the active partition complete."""
        return self._governor.implies_partition_complete

    def should_defer(self) -> bool:
        """True once the soft target is reached; orchestrator should defer the job."""
        return self._governor.should_stop()

    def try_consume(self) -> bool:
        """Reserve one Partner HTTP attempt budget unit.

        Returns ``True`` when an attempt was recorded, ``False`` at hard cap.
        """
        if self._governor.attempts >= self._governor.hard_limit:
            return False
        try:
            self._governor.record_attempt()
        except BudgetExhaustedError:
            return False
        return True

    def record_success(self) -> None:
        self._governor.record_success()

    def record_failure(self) -> None:
        self._governor.record_failure()

    def record_rate_limited(self) -> None:
        self._governor.record_rate_limited()

    def finish(self, reason: PartnerBudgetStopReason) -> dict[str, int | str | None]:
        """Set terminal stop reason and return structured log fields."""
        self._finish_reason = reason
        internal_reason: StoppedReason = (
            "budget" if reason == DEFER_REASON else cast(StoppedReason, reason)
        )
        self._governor.finish(internal_reason)
        return self.structured_log_fields()

    def structured_log_fields(self) -> dict[str, int | str | None]:
        defer_reason = DEFER_REASON if self._finish_reason == DEFER_REASON else None
        return {
            "attempts": self._governor.attempts,
            "successes": self._governor.successes,
            "failures": self._governor.failures,
            "rate_limited": self._governor.rate_limited,
            "defer_reason": defer_reason,
            "stopped_reason": self._finish_reason,
        }


def begin_partner_budget_run(
    max_attempts: int = 400,
    hard_limit: int = 499,
) -> PartnerApiBudgetGovernor:
    """Create a fresh per-run Partner API budget governor (ADR-029 defaults)."""
    return PartnerApiBudgetGovernor(_governor=begin_run(max_attempts, hard_limit))
