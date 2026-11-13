"""``/v1/ingest/status``: last ingest per dataset, and the extension's drift reports.

Drift (D31.4): when Seller Centre's JSON gains or loses a field the extension
maps, the extension stops that dataset and reports ``drift`` with the field
names. The gateway then refuses that dataset from the SAME extension version
(409 ``dataset_in_drift``) -- a new version, or an ``ok`` report, resumes it.
Ops reads the same rows to see which shops' connectors need an update.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import DRIFT_DRIFT, DRIFT_OK, IngestDatasetStatus
from juli_backend.services.ingest.mapping import DATASETS
from juli_backend.services.ingest.schemas import ConnectorEvent, DriftReport
from juli_backend.services.ops import audit

logger = logging.getLogger(__name__)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def version_key(version: str | None) -> tuple[tuple[int, ...], str]:
    """Order of Connector versions ("0.3.14" > "0.3.9"): the numeric parts, then the text."""
    text = version or ""
    nums = tuple(int(n) for n in re.findall(r"\d+", text.split("+")[0].split("-")[0]))
    return nums, text


def is_newer(version: str | None, than: str | None) -> bool:
    return version is not None and than is not None and version_key(version) > version_key(than)


def clear_superseded_drift(row: IngestDatasetStatus, posted_version: str, now: datetime) -> bool:
    """A NEWER Connector version posted the dataset successfully: the older version's drift flag
    (``unexpected`` / ``missing``) no longer describes the Connector. Clear it; the old detail is
    kept in the log (no history table). An older or equal version never clears anything."""
    if row.drift_state != DRIFT_DRIFT or not is_newer(posted_version, row.drift_source_version):
        return False
    logger.info(
        "ingest_drift_superseded",
        extra={
            "shop_id": str(row.shop_id),
            "dataset": row.dataset,
            "flagged_version": row.drift_source_version,
            "cleared_by_version": posted_version,
            "detail": row.drift_detail,
        },
    )
    row.drift_state = DRIFT_OK
    row.drift_detail = None
    row.drift_source_version = None
    row.drift_at = now
    row.updated_at = now
    return True


def _drift_of(row: IngestDatasetStatus | None) -> str:
    """ "drift" only while the flagged version is still the last one posting: a newer version's
    accepted post (the gateway refuses only the flagged version) has superseded the flag."""
    if row is None or row.drift_state != DRIFT_DRIFT:
        return DRIFT_OK
    if is_newer(row.last_source_version, row.drift_source_version):
        return DRIFT_OK
    return DRIFT_DRIFT


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
        flagged = _drift_of(row) == DRIFT_DRIFT
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
                "drift": _drift_of(row),
                "drift_detail": row.drift_detail if row and flagged else None,
                "drift_source_version": row.drift_source_version if row and flagged else None,
                "drift_at": _iso(row.drift_at) if row and flagged else None,
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
    # A report of an older Connector never touches a newer version's flag, and an older version's
    # drift is stale once a newer one has posted.
    if is_newer(row.drift_source_version, report.source_version) or is_newer(
        row.last_source_version, report.source_version
    ):
        return
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


#: The audit action of a Connector stop (``system_`` prefix: kind ``system``, 90-day retention).
ACTION_CONNECTOR_STOP = "system_connector_stop"


async def record_connector_event(
    session: AsyncSession, *, shop_id: uuid.UUID, event: ConnectorEvent, now: datetime
) -> None:
    """Keep a Connector stop where Ops looks: the audit log, no table of its own (P97 T1).

    Metadata only; the caller commits."""
    await audit.record(
        session,
        audit.SYSTEM_ACTOR,
        ACTION_CONNECTOR_STOP,
        shop_id=shop_id,
        after={
            "platform": event.platform,
            "reader": event.reader,
            "page": event.page,
            "status": event.status,
            "code": event.code,
            "occurred_at": (event.occurred_at or now).isoformat(),
            "source_version": event.source_version,
        },
        at=now,
    )
    logger.warning(
        "connector_stop",
        extra={
            "shop_id": str(shop_id),
            "reader": event.reader,
            "status": event.status,
            "code": event.code,
            "source_version": event.source_version,
        },
    )
