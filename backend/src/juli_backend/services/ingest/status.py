"""``/v1/ingest/status``: last ingest per dataset, and the extension's drift reports.

Drift (D31.4): when Seller Centre's JSON gains or loses a field the extension
maps, the extension stops that dataset and reports ``drift`` with the field
names. The gateway then refuses that dataset from the SAME extension version
(409 ``dataset_in_drift``) -- a new version, or an ``ok`` report, resumes it.
Ops reads the same rows to see which shops' connectors need an update.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import DRIFT_DRIFT, DRIFT_OK, IngestDatasetStatus
from juli_backend.services.ingest.mapping import DATASETS
from juli_backend.services.ingest.schemas import DriftReport

logger = logging.getLogger(__name__)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def dataset_status(
    session: AsyncSession, *, shop_id: uuid.UUID, platform: str
) -> list[dict[str, Any]]:
    """One entry per dataset the platform has (never-ingested ones included)."""
    rows = {
        row.dataset: row
        for row in (
            await session.execute(
                select(IngestDatasetStatus).where(
                    IngestDatasetStatus.shop_id == shop_id,
                    IngestDatasetStatus.platform == platform,
                )
            )
        ).scalars()
    }
    out: list[dict[str, Any]] = []
    for (spec_platform, name), _spec in sorted(DATASETS.items()):
        if spec_platform != platform:
            continue
        row = rows.get(name)
        out.append(
            {
                "dataset": name,
                "last_ingest_at": _iso(row.last_ingest_at) if row else None,
                "last_captured_at": _iso(row.last_captured_at) if row else None,
                "last_period_start": _iso(row.last_period_start) if row else None,
                "last_period_end": _iso(row.last_period_end) if row else None,
                "last_row_count": row.last_row_count if row else None,
                "last_source": row.last_source if row else None,
                "last_source_version": row.last_source_version if row else None,
                "drift": (row.drift_state if row else DRIFT_OK),
                "drift_detail": row.drift_detail if row else None,
                "drift_source_version": row.drift_source_version if row else None,
                "drift_at": _iso(row.drift_at) if row else None,
            }
        )
    return out


async def report_drift(
    session: AsyncSession, *, shop_id: uuid.UUID, report: DriftReport, now: datetime
) -> None:
    if (report.platform, report.dataset) not in DATASETS:
        raise LookupError(report.dataset)
    row = (
        await session.execute(
            select(IngestDatasetStatus).where(
                IngestDatasetStatus.shop_id == shop_id,
                IngestDatasetStatus.platform == report.platform,
                IngestDatasetStatus.dataset == report.dataset,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = IngestDatasetStatus(
            id=uuid.uuid4(),
            shop_id=shop_id,
            platform=report.platform,
            dataset=report.dataset,
            updated_at=now,
        )
        session.add(row)
    if report.state == DRIFT_DRIFT:
        row.drift_state = DRIFT_DRIFT
        row.drift_detail = {
            "endpoint": report.endpoint,
            "unexpected": report.unexpected,
            "missing": report.missing,
        }
        row.drift_source_version = report.source_version
        row.drift_at = now
    else:
        row.drift_state = DRIFT_OK
        row.drift_detail = None
        row.drift_source_version = None
        row.drift_at = now
    row.updated_at = now
    await session.flush()
    logger.info(
        "ingest_drift_reported",
        extra={
            "shop_id": str(shop_id),
            "platform": report.platform,
            "dataset": report.dataset,
            "state": report.state,
            "source_version": report.source_version,
            "endpoint": report.endpoint,
            "unexpected": report.unexpected[:20],
            "missing": report.missing[:20],
        },
    )
