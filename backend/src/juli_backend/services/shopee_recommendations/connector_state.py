"""What the Connector last told Juli about itself, and the one command Juli can give it (P100).

No table of its own: one ``ingest_dataset_status`` row per shop with the pseudo-dataset
``connector_state`` (never listed by ``dataset_status``, which walks the real datasets only) keeps
its JSON in ``drift_detail`` (read only while ``drift_state`` is ``drift``; this row stays ``ok``).

- Heartbeat: the Connector's fill-job poll (every few minutes) says whether a Seller Centre tab is
  open and acknowledges the command it ran.
- Command ``reconcile`` ("Đối chiếu ngay"): the web app asks, the next poll hands it to the
  Connector, which runs its readers now; the ack clears it.

Reviewer requests never write here (``reviewer_session_active``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import DRIFT_OK, IngestDatasetStatus
from juli_backend.services.shop_proposals.cycle import ProposalError

DATASET = "connector_state"
COMMAND_RECONCILE = "reconcile"
#: The poll runs every 3 minutes; a heartbeat older than this says nothing about the tab.
HEARTBEAT_FRESH = timedelta(minutes=10)
ERROR_REVIEWER = "connector_command_refused"


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat() + "Z"


async def _row(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, create: bool, now: datetime
) -> IngestDatasetStatus | None:
    row = await session.scalar(
        select(IngestDatasetStatus).where(
            IngestDatasetStatus.shop_id == shop_id,
            IngestDatasetStatus.platform == platform,
            IngestDatasetStatus.dataset == DATASET,
        )
    )
    if row is None and create:
        row = IngestDatasetStatus(
            shop_id=shop_id,
            platform=platform,
            dataset=DATASET,
            drift_state=DRIFT_OK,
            drift_detail={},
            updated_at=now,
        )
        session.add(row)
        await session.flush()
    return row


def _put(row: IngestDatasetStatus, patch: dict[str, Any], now: datetime) -> None:
    row.drift_detail = {**(row.drift_detail or {}), **patch}
    row.updated_at = now


async def record_heartbeat(
    session: AsyncSession,
    shop_id: uuid.UUID,
    platform: str,
    *,
    seller_centre_open: bool | None,
    ack: str | None,
    now: datetime,
) -> None:
    """The Connector's poll: the tab flag (None = it did not say) and the command it ran."""
    row = await _row(session, shop_id, platform, create=True, now=now)
    assert row is not None
    patch: dict[str, Any] = {"heartbeat_at": _iso(now)}
    if seller_centre_open is not None:
        patch["seller_centre_open"] = seller_centre_open
    if ack and (row.drift_detail or {}).get("command_id") == ack:
        patch.update(command_id=None, command_done_at=_iso(now))
    _put(row, patch, now)
    await session.flush()


async def request_reconcile(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, now: datetime
) -> dict[str, Any]:
    """ "Đối chiếu ngay": queue the command (one at a time; asking twice keeps the first)."""
    from juli_backend.integrations.tiktok import reviewer_session_active

    if reviewer_session_active():
        raise ProposalError(ERROR_REVIEWER, 403)
    row = await _row(session, shop_id, platform, create=True, now=now)
    assert row is not None
    detail = row.drift_detail or {}
    if not detail.get("command_id"):
        _put(row, {"command_id": f"{COMMAND_RECONCILE}:{_iso(now)}", "command_at": _iso(now)}, now)
        await session.flush()
    return {"requested": True, "command_id": (row.drift_detail or {}).get("command_id")}


async def commands(
    session: AsyncSession, shop_id: uuid.UUID, platform: str
) -> list[dict[str, str]]:
    row = await _row(session, shop_id, platform, create=False, now=datetime.min)
    cid = (row.drift_detail or {}).get("command_id") if row else None
    return [{"type": COMMAND_RECONCILE, "id": cid}] if cid else []


async def read(
    session: AsyncSession, shop_id: uuid.UUID, platform: str, *, now: datetime
) -> dict[str, Any]:
    row = await _row(session, shop_id, platform, create=False, now=now)
    detail = (row.drift_detail or {}) if row else {}
    beat = detail.get("heartbeat_at")
    fresh = False
    if beat:
        fresh = now - datetime.fromisoformat(beat.removesuffix("Z")) <= HEARTBEAT_FRESH
    return {
        "heartbeat_at": beat,
        "alive": fresh,
        "seller_centre_open": detail.get("seller_centre_open") if fresh else None,
        "reconcile_pending": bool(detail.get("command_id")),
        "reconcile_done_at": detail.get("command_done_at"),
    }
