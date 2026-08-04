"""Per-run Postgres I/O budget governor for CDP batch reconcile (CDP-A2-3).

Caps bronze flush size, silver upsert batch size, and concurrent shop jobs.
On exhaustion the orchestrator must **not** mark the partition or shop window
complete; ``finish("postgres_io_throttled")`` emits the structured defer reason.

Independent from ``PartnerApiBudgetGovernor`` (#616) — dual budgets stay separate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

PostgresIoBudgetStopReason = Literal["postgres_io_throttled", "complete", "error"]

DEFER_REASON: PostgresIoBudgetStopReason = "postgres_io_throttled"

DEFAULT_BRONZE_ROWS_PER_FLUSH = 5000
DEFAULT_SILVER_UPSERT_BATCH_SIZE = 1000
DEFAULT_MAX_CONCURRENT_SHOPS = 10

ENV_BRONZE_ROWS_PER_FLUSH = "BATCH_BRONZE_ROWS_PER_FLUSH"
ENV_SILVER_UPSERT_BATCH_SIZE = "BATCH_SILVER_UPSERT_BATCH_SIZE"
ENV_MAX_CONCURRENT_SHOPS = "BATCH_MAX_CONCURRENT_SHOPS"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


@dataclass
class PostgresIoBudgetGovernor:
    """Tracks Postgres I/O dimensions for one CDP batch reconcile run."""

    bronze_rows_per_flush: int
    silver_upsert_batch_size: int
    max_concurrent_shops: int
    _active_shops: int = field(default=0, init=False)
    _last_bronze_flush_size: int = field(default=0, init=False)
    _last_silver_batch_size: int = field(default=0, init=False)
    _deferred_total: int = field(default=0, init=False)
    _io_throttled: bool = field(default=False, init=False)
    _finish_reason: PostgresIoBudgetStopReason | None = field(default=None, init=False)

    @property
    def last_bronze_flush_size(self) -> int:
        return self._last_bronze_flush_size

    @property
    def last_silver_batch_size(self) -> int:
        return self._last_silver_batch_size

    @property
    def concurrent_shop_count(self) -> int:
        return self._active_shops

    @property
    def batch_postgres_io_deferred_total(self) -> int:
        return self._deferred_total

    @property
    def implies_partition_complete(self) -> bool:
        """Whether I/O budget state allows marking the active partition complete."""
        return self._finish_reason == "complete"

    def should_defer(self) -> bool:
        """True once an I/O dimension rejected an operation; orchestrator should defer."""
        return self._io_throttled or self._finish_reason == DEFER_REASON

    def try_bronze_flush(self, row_count: int) -> bool:
        """Validate bronze flush row count under cap.

        Returns ``True`` when ``row_count`` is within the flush limit, ``False`` otherwise.
        """
        if row_count <= 0:
            raise ValueError("row_count must be positive")
        if row_count > self.bronze_rows_per_flush:
            self._record_defer()
            return False
        self._last_bronze_flush_size = row_count
        return True

    def try_silver_upsert(self, row_count: int) -> bool:
        """Validate silver upsert row count under cap.

        Returns ``True`` when ``row_count`` is within the batch limit, ``False`` otherwise.
        """
        if row_count <= 0:
            raise ValueError("row_count must be positive")
        if row_count > self.silver_upsert_batch_size:
            self._record_defer()
            return False
        self._last_silver_batch_size = row_count
        return True

    def try_acquire_shop(self) -> bool:
        """Reserve one concurrent shop slot.

        Returns ``True`` when under the concurrent shop cap, ``False`` at cap.
        """
        if self._active_shops >= self.max_concurrent_shops:
            self._record_defer()
            return False
        self._active_shops += 1
        return True

    def release_shop(self) -> None:
        """Release one concurrent shop slot acquired via ``try_acquire_shop``."""
        if self._active_shops > 0:
            self._active_shops -= 1

    def finish(self, reason: PostgresIoBudgetStopReason) -> dict[str, int | str | None]:
        """Set terminal stop reason and return structured log fields."""
        self._finish_reason = reason
        if reason == DEFER_REASON:
            self._io_throttled = True
        return self.structured_log_fields()

    def structured_log_fields(self) -> dict[str, int | str | None]:
        defer_reason = DEFER_REASON if self._finish_reason == DEFER_REASON else None
        return {
            "bronze_flush_size": self._last_bronze_flush_size,
            "silver_batch_size": self._last_silver_batch_size,
            "concurrent_shop_count": self._active_shops,
            "batch_postgres_io_deferred_total": self._deferred_total,
            "stopped_reason": self._finish_reason,
            "defer_reason": defer_reason,
        }

    def _record_defer(self) -> None:
        self._io_throttled = True
        self._deferred_total += 1


def begin_postgres_io_budget_run(
    bronze_rows_per_flush: int | None = None,
    silver_upsert_batch_size: int | None = None,
    max_concurrent_shops: int | None = None,
) -> PostgresIoBudgetGovernor:
    """Create a fresh per-run Postgres I/O budget governor."""
    bronze = (
        bronze_rows_per_flush
        if bronze_rows_per_flush is not None
        else _env_int(ENV_BRONZE_ROWS_PER_FLUSH, DEFAULT_BRONZE_ROWS_PER_FLUSH)
    )
    silver = (
        silver_upsert_batch_size
        if silver_upsert_batch_size is not None
        else _env_int(ENV_SILVER_UPSERT_BATCH_SIZE, DEFAULT_SILVER_UPSERT_BATCH_SIZE)
    )
    concurrent = (
        max_concurrent_shops
        if max_concurrent_shops is not None
        else _env_int(ENV_MAX_CONCURRENT_SHOPS, DEFAULT_MAX_CONCURRENT_SHOPS)
    )
    if bronze <= 0:
        raise ValueError("bronze_rows_per_flush must be positive")
    if silver <= 0:
        raise ValueError("silver_upsert_batch_size must be positive")
    if concurrent <= 0:
        raise ValueError("max_concurrent_shops must be positive")
    return PostgresIoBudgetGovernor(
        bronze_rows_per_flush=bronze,
        silver_upsert_batch_size=silver,
        max_concurrent_shops=concurrent,
    )
