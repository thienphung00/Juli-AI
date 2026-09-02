"""Resumable analytics backfill progress, one row per ``(shop, bucket, date)``.

``ops.analytics_backfill_partitions`` lets a multi-day backfill stop and pick
up where it left off. A partition is ``pending`` until it is either
``complete`` or ``failed``; failed partitions are retried while ``retryable``.

Error text is stored for operators, so it is scrubbed of anything that looks
like a bearer token or an OAuth credential before it is written
(:func:`redact_secrets`). The vendor's error bodies occasionally echo the
request headers back.

One-writer rule: ``mark_complete``/``mark_failed`` may only be called from
``services.analytics_backfill`` and ``services.cdp_batch.partition_checkpoints``.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import select

from juli_backend.models.models import AnalyticsBackfillPartition
from juli_backend.repositories._base import SessionRepo

BACKFILL_BUCKETS = frozenset({"revenue", "product", "live", "catalog"})
COMPLETE = "complete"
FAILED = "failed"
_INCOMPLETE_STATUSES = frozenset({"pending", FAILED})

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s]+"),
    re.compile(r"(?i)(access[_-]?token[=:\s]+)[^\s,;]+"),
    re.compile(r"(?i)(refresh[_-]?token[=:\s]+)[^\s,;]+"),
    re.compile(r"(?i)(authorization[=:\s]+)[^\s,;]+"),
)


def redact_secrets(message: str) -> str:
    """Replace token-shaped substrings with ``[REDACTED]``, keeping the label."""
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(r"\1[REDACTED]", message)
    return message


class AnalyticsBackfillPartitionsRepo(SessionRepo):
    @staticmethod
    def validate_bucket(bucket: str) -> None:
        if bucket not in BACKFILL_BUCKETS:
            raise ValueError(
                f"Invalid backfill bucket {bucket!r}; expected one of {sorted(BACKFILL_BUCKETS)}"
            )

    async def get_partition(
        self, shop_id: uuid.UUID, bucket: str, partition_date: date
    ) -> AnalyticsBackfillPartition | None:
        self.validate_bucket(bucket)
        return await self._one_or_none(
            select(AnalyticsBackfillPartition).where(
                AnalyticsBackfillPartition.shop_id == shop_id,
                AnalyticsBackfillPartition.bucket == bucket,
                AnalyticsBackfillPartition.partition_date == partition_date,
            )
        )

    async def is_complete(self, shop_id: uuid.UUID, bucket: str, partition_date: date) -> bool:
        row = await self.get_partition(shop_id, bucket, partition_date)
        return row is not None and row.status == COMPLETE

    async def mark_complete(
        self, shop_id: uuid.UUID, bucket: str, partition_date: date
    ) -> AnalyticsBackfillPartition:
        row = await self.get_partition(shop_id, bucket, partition_date)
        if row is None:
            row = AnalyticsBackfillPartition(
                shop_id=shop_id,
                bucket=bucket,
                partition_date=partition_date,
                status=COMPLETE,
                retryable=False,
            )
            self._session.add(row)
        else:
            row.status = COMPLETE
            row.retryable = False
            row.last_error = None
        await self._session.flush()
        return row

    async def mark_failed(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
        error: str,
        *,
        retryable: bool = True,
    ) -> AnalyticsBackfillPartition:
        """Record a failed attempt. ``attempt_count`` grows by one per call."""
        row = await self.get_partition(shop_id, bucket, partition_date)
        if row is None:
            row = AnalyticsBackfillPartition(
                shop_id=shop_id,
                bucket=bucket,
                partition_date=partition_date,
                status=FAILED,
                attempt_count=1,
                last_error=redact_secrets(error),
                retryable=retryable,
            )
            self._session.add(row)
        else:
            row.status = FAILED
            row.attempt_count += 1
            row.last_error = redact_secrets(error)
            row.retryable = retryable
        await self._session.flush()
        return row

    async def list_incomplete(
        self, shop_id: uuid.UUID, bucket: str, start: date, end: date
    ) -> list[AnalyticsBackfillPartition]:
        return await self._list_in_range(
            shop_id,
            bucket,
            start,
            end,
            AnalyticsBackfillPartition.status.in_(_INCOMPLETE_STATUSES),
        )

    async def list_completed(
        self, shop_id: uuid.UUID, bucket: str, start: date, end: date
    ) -> list[AnalyticsBackfillPartition]:
        """Bulk-load completed partitions so callers test membership in O(1), not one query each."""
        return await self._list_in_range(
            shop_id, bucket, start, end, AnalyticsBackfillPartition.status == COMPLETE
        )

    async def _list_in_range(
        self, shop_id: uuid.UUID, bucket: str, start: date, end: date, status_criterion
    ) -> list[AnalyticsBackfillPartition]:
        self.validate_bucket(bucket)
        if end < start:
            return []
        stmt = (
            select(AnalyticsBackfillPartition)
            .where(
                AnalyticsBackfillPartition.shop_id == shop_id,
                AnalyticsBackfillPartition.bucket == bucket,
                AnalyticsBackfillPartition.partition_date >= start,
                AnalyticsBackfillPartition.partition_date <= end,
                status_criterion,
            )
            .order_by(AnalyticsBackfillPartition.partition_date)
        )
        return await self._all(stmt)


__all__ = [
    "BACKFILL_BUCKETS",
    "COMPLETE",
    "FAILED",
    "AnalyticsBackfillPartitionsRepo",
    "redact_secrets",
]
