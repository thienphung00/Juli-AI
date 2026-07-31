"""Partition-resumable batch reconcile checkpoints (CDP-A2-5 / #620).

Persists mid-partition page cursors in ``ops.analytics_backfill_partitions`` only
(reuses A0 #604 schema — cursor encoded in ``last_error`` while status is pending).
Bronze reconcile pages are append-only; completed pages are not re-fetched on resume.

**Transaction contract:** ``reconcile_partition_with_checkpoints`` performs bronze append
and ops checkpoint writes on the **same** ``AsyncSession``. Callers must ``commit`` once
after the orchestrator returns — never between internal append and checkpoint flushes.
If the session rolls back, both bronze and checkpoint writes are discarded together.
When bronze was committed without a matching checkpoint (crash window), idempotent
page ``source_event_id`` plus bronze ``_batch_reconcile`` metadata recover the cursor.

Reuses Phase 2.9 / ADR-029 partition patterns via ``AnalyticsBackfillPartitionsRepo``.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsBackfillPartition, BronzeOrderRawPayload
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    BronzeOrderRawPayloadsRepo,
)
from juli_backend.services.cdp_batch.partner_budget import (
    DEFER_REASON,
    PartnerApiBudgetGovernor,
    begin_partner_budget_run,
)

logger = logging.getLogger(__name__)

BATCH_RECONCILE_INGEST_SOURCE = "batch_reconcile"
BATCH_RECONCILE_META_KEY = "_batch_reconcile"
_CHECKPOINT_PREFIX = "batch_checkpoint:v1:"
_PAGE_TOKEN_START = "__start__"

BronzeAppendFn = Callable[[list[dict[str, Any]]], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class PartitionPageCheckpoint:
    """Resume cursor for a partially completed batch reconcile partition."""

    page_token: str | None
    pages_completed: int = 0


@dataclass(frozen=True, slots=True)
class BatchPartitionReconcileResult:
    skipped: bool = False
    complete: bool = False
    deferred: bool = False
    pages_fetched: int = 0
    bronze_rows_appended: int = 0
    error: str | None = None


class ReconcilePageFetcher(Protocol):
    def fetch_page(self, *, page_token: str | None) -> dict[str, Any]: ...


def reconcile_page_source_event_id(
    partition_date: date,
    fetched_page_token: str | None,
) -> str:
    """Deterministic bronze idempotency key for one fetched reconcile page."""
    token_key = fetched_page_token if fetched_page_token is not None else _PAGE_TOKEN_START
    return f"batch-reconcile:{partition_date.isoformat()}:page:{token_key}"


def _encode_checkpoint(checkpoint: PartitionPageCheckpoint) -> str:
    payload = json.dumps(
        {
            "page_token": checkpoint.page_token,
            "pages_completed": checkpoint.pages_completed,
        },
        separators=(",", ":"),
    )
    return f"{_CHECKPOINT_PREFIX}{payload}"


def _decode_checkpoint(last_error: str | None) -> PartitionPageCheckpoint | None:
    if not last_error or not last_error.startswith(_CHECKPOINT_PREFIX):
        return None
    raw = last_error[len(_CHECKPOINT_PREFIX) :]
    data = json.loads(raw)
    page_token = data.get("page_token")
    if page_token is not None:
        page_token = str(page_token)
    pages_completed = int(data.get("pages_completed", 0))
    return PartitionPageCheckpoint(page_token=page_token, pages_completed=pages_completed)


class BatchPartitionCheckpointsRepo:
    """Batch-layer partition repo — reads/writes ``ops.analytics_backfill_partitions`` only."""

    _OPS_SCHEMA = "ops"
    _OPS_TABLE = "analytics_backfill_partitions"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._partitions = AnalyticsBackfillPartitionsRepo(session)
        if AnalyticsBackfillPartition.__tablename__ != self._OPS_TABLE:
            msg = (
                "Batch partition repo must target ops.analytics_backfill_partitions only; "
                f"unexpected tablename {AnalyticsBackfillPartition.__tablename__!r}"
            )
            raise ValueError(msg)
        table_args = AnalyticsBackfillPartition.__table_args__
        schema = table_args[-1].get("schema") if isinstance(table_args[-1], dict) else None
        if schema != self._OPS_SCHEMA:
            msg = (
                "Batch partition repo must target ops.analytics_backfill_partitions only; "
                f"unexpected schema {schema!r}"
            )
            raise ValueError(msg)

    async def is_complete(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> bool:
        return await self._partitions.is_complete(shop_id, bucket, partition_date)

    async def mark_complete(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> AnalyticsBackfillPartition:
        return await self._partitions.mark_complete(shop_id, bucket, partition_date)

    async def get_checkpoint(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> PartitionPageCheckpoint | None:
        if await self.is_complete(shop_id, bucket, partition_date):
            return None
        row = await self._partitions.get_partition(shop_id, bucket, partition_date)
        if row is not None:
            decoded = _decode_checkpoint(row.last_error)
            if decoded is not None:
                return decoded
            if row.status == "failed":
                return PartitionPageCheckpoint(page_token=None, pages_completed=0)
        return await recover_checkpoint_from_bronze(
            self._session,
            shop_id=shop_id,
            partition_date=partition_date,
        )

    async def save_checkpoint(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
        checkpoint: PartitionPageCheckpoint,
    ) -> AnalyticsBackfillPartition:
        AnalyticsBackfillPartitionsRepo.validate_bucket(bucket)
        encoded = _encode_checkpoint(checkpoint)
        row = await self._partitions.get_partition(shop_id, bucket, partition_date)
        if row is None:
            row = AnalyticsBackfillPartition(
                shop_id=shop_id,
                bucket=bucket,
                partition_date=partition_date,
                status="pending",
                last_error=encoded,
                retryable=True,
            )
            self._session.add(row)
        else:
            row.status = "pending"
            row.last_error = encoded
            row.retryable = True
        await self._session.flush()
        return row


async def _page_already_landed(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    partition_date: date,
    fetched_page_token: str | None,
) -> bool:
    event_id = reconcile_page_source_event_id(partition_date, fetched_page_token)
    stmt = (
        select(BronzeOrderRawPayload.id)
        .where(
            BronzeOrderRawPayload.shop_id == shop_id,
            BronzeOrderRawPayload.ingest_source == BATCH_RECONCILE_INGEST_SOURCE,
            BronzeOrderRawPayload.source_event_id == event_id,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def recover_checkpoint_from_bronze(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    partition_date: date,
) -> PartitionPageCheckpoint | None:
    """Rebuild resume cursor from append-only bronze when ops checkpoint is missing."""
    prefix = f"batch-reconcile:{partition_date.isoformat()}:page:"
    stmt = (
        select(BronzeOrderRawPayload)
        .where(
            BronzeOrderRawPayload.shop_id == shop_id,
            BronzeOrderRawPayload.ingest_source == BATCH_RECONCILE_INGEST_SOURCE,
            BronzeOrderRawPayload.source_event_id.like(f"{prefix}%"),
        )
        .order_by(BronzeOrderRawPayload.received_at)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return None

    pages_completed = len(rows)
    meta = rows[-1].payload.get(BATCH_RECONCILE_META_KEY, {})
    if not isinstance(meta, dict):
        meta = {}
    next_token = meta.get("next_page_token")
    if next_token is not None:
        next_token = str(next_token)
    return PartitionPageCheckpoint(page_token=next_token, pages_completed=pages_completed)


async def append_reconcile_bronze_page(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    partition_date: date,
    fetched_page_token: str | None,
    next_page_token: str | None,
    payloads: list[dict[str, Any]],
    received_at: datetime | None = None,
) -> int:
    """Append one reconcile page to bronze (idempotent by page ``source_event_id``)."""
    if await _page_already_landed(
        session,
        shop_id=shop_id,
        partition_date=partition_date,
        fetched_page_token=fetched_page_token,
    ):
        return 0

    event_id = reconcile_page_source_event_id(partition_date, fetched_page_token)
    resolved_received_at = received_at or datetime.now(UTC)
    bronze_repo = BronzeOrderRawPayloadsRepo(session)
    page_payload: dict[str, Any] = {
        "records": payloads,
        BATCH_RECONCILE_META_KEY: {
            "partition_date": partition_date.isoformat(),
            "fetched_page_token": fetched_page_token,
            "next_page_token": next_page_token,
        },
    }
    rows = await bronze_repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": BATCH_RECONCILE_INGEST_SOURCE,
                "payload": page_payload,
                "received_at": resolved_received_at,
                "tiktok_order_id": None,
                "source_event_id": event_id,
            }
        ]
    )
    return len(rows)


def _extract_page(page: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    payloads = page.get("payloads", [])
    if not isinstance(payloads, list):
        payloads = []
    next_token = page.get("next_page_token")
    if next_token is not None:
        next_token = str(next_token)
    return payloads, next_token


async def _persist_fetched_page(
    session: AsyncSession,
    checkpoints_repo: BatchPartitionCheckpointsRepo,
    *,
    shop_id: uuid.UUID,
    bucket: str,
    partition_date: date,
    fetched_page_token: str | None,
    payloads: list[dict[str, Any]],
    next_page_token: str | None,
    pages_completed: int,
    received_at: datetime | None = None,
) -> tuple[int, int]:
    """Atomically land bronze page + ops checkpoint on the shared session."""
    appended = await append_reconcile_bronze_page(
        session,
        shop_id=shop_id,
        partition_date=partition_date,
        fetched_page_token=fetched_page_token,
        next_page_token=next_page_token,
        payloads=payloads,
        received_at=received_at,
    )
    updated_pages_completed = pages_completed + 1
    if not next_page_token:
        await checkpoints_repo.mark_complete(shop_id, bucket, partition_date)
    else:
        await checkpoints_repo.save_checkpoint(
            shop_id,
            bucket,
            partition_date,
            PartitionPageCheckpoint(
                page_token=next_page_token,
                pages_completed=updated_pages_completed,
            ),
        )
    return appended, updated_pages_completed


async def reconcile_partition_with_checkpoints(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    bucket: str,
    partition_date: date,
    fetcher: ReconcilePageFetcher,
    budget: PartnerApiBudgetGovernor | None = None,
    received_at: datetime | None = None,
) -> BatchPartitionReconcileResult:
    """Run paginated batch reconcile with ops checkpoint persistence on partial failure."""
    checkpoints_repo = BatchPartitionCheckpointsRepo(session)
    governor = budget or begin_partner_budget_run()

    if await checkpoints_repo.is_complete(shop_id, bucket, partition_date):
        return BatchPartitionReconcileResult(skipped=True, complete=True)

    checkpoint = await checkpoints_repo.get_checkpoint(shop_id, bucket, partition_date)
    page_token = checkpoint.page_token if checkpoint is not None else None
    pages_completed = checkpoint.pages_completed if checkpoint is not None else 0

    pages_fetched = 0
    bronze_rows_appended = 0

    while True:
        if await _page_already_landed(
            session,
            shop_id=shop_id,
            partition_date=partition_date,
            fetched_page_token=page_token,
        ):
            recovered = await recover_checkpoint_from_bronze(
                session,
                shop_id=shop_id,
                partition_date=partition_date,
            )
            if recovered is None or recovered.page_token is None:
                await checkpoints_repo.mark_complete(shop_id, bucket, partition_date)
                governor.finish("complete")
                return BatchPartitionReconcileResult(
                    complete=True,
                    pages_fetched=pages_fetched,
                    bronze_rows_appended=bronze_rows_appended,
                )
            if recovered.page_token == page_token:
                await checkpoints_repo.mark_complete(shop_id, bucket, partition_date)
                governor.finish("complete")
                return BatchPartitionReconcileResult(
                    complete=True,
                    pages_fetched=pages_fetched,
                    bronze_rows_appended=bronze_rows_appended,
                )
            page_token = recovered.page_token
            pages_completed = max(pages_completed, recovered.pages_completed)
            continue

        if governor.should_defer():
            await checkpoints_repo.save_checkpoint(
                shop_id,
                bucket,
                partition_date,
                PartitionPageCheckpoint(page_token=page_token, pages_completed=pages_completed),
            )
            governor.finish("partner_budget_exhausted")
            logger.info(
                "cdp_batch_partition_checkpoint_saved",
                extra={
                    "shop_id": str(shop_id),
                    "bucket": bucket,
                    "partition_date": partition_date.isoformat(),
                    "pages_completed": pages_completed,
                    "page_token": page_token,
                    "defer_reason": DEFER_REASON,
                },
            )
            return BatchPartitionReconcileResult(
                deferred=True,
                pages_fetched=pages_fetched,
                bronze_rows_appended=bronze_rows_appended,
            )

        if not governor.try_consume():
            await checkpoints_repo.save_checkpoint(
                shop_id,
                bucket,
                partition_date,
                PartitionPageCheckpoint(page_token=page_token, pages_completed=pages_completed),
            )
            governor.finish("partner_budget_exhausted")
            return BatchPartitionReconcileResult(
                deferred=True,
                pages_fetched=pages_fetched,
                bronze_rows_appended=bronze_rows_appended,
            )

        fetched_page_token = page_token
        try:
            page = fetcher.fetch_page(page_token=page_token)
            governor.record_success()
        except Exception as exc:
            governor.record_failure()
            await checkpoints_repo.save_checkpoint(
                shop_id,
                bucket,
                partition_date,
                PartitionPageCheckpoint(page_token=page_token, pages_completed=pages_completed),
            )
            logger.info(
                "cdp_batch_partition_fetch_failed",
                extra={
                    "shop_id": str(shop_id),
                    "bucket": bucket,
                    "partition_date": partition_date.isoformat(),
                    "pages_completed": pages_completed,
                    "page_token": page_token,
                },
            )
            return BatchPartitionReconcileResult(
                pages_fetched=pages_fetched,
                bronze_rows_appended=bronze_rows_appended,
                error=str(exc),
            )

        pages_fetched += 1
        payloads, next_page_token = _extract_page(page)

        appended, pages_completed = await _persist_fetched_page(
            session,
            checkpoints_repo,
            shop_id=shop_id,
            bucket=bucket,
            partition_date=partition_date,
            fetched_page_token=fetched_page_token,
            payloads=payloads,
            next_page_token=next_page_token,
            pages_completed=pages_completed,
            received_at=received_at,
        )
        bronze_rows_appended += appended

        if not next_page_token:
            governor.finish("complete")
            return BatchPartitionReconcileResult(
                complete=True,
                pages_fetched=pages_fetched,
                bronze_rows_appended=bronze_rows_appended,
            )

        page_token = next_page_token
