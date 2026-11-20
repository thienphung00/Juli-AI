"""Derive a TikTok shop's sync status from its credentials and ingestion state.

Connection states (contract p101 §6), derived and never stored:

- ``disconnected`` -- the shop has no credential row.
- ``needs_reauth`` -- a credential failed its refresh (or was revoked); polling,
  history and the refresh beat skip it until the seller re-authorises, and the
  OAuth callback flips it back to ``active``.
- ``backfilling`` -- the history walk has not reached 90 days yet.
- ``degraded`` -- the ingestion failed, or yesterday is still missing after
  09:00 Asia/Ho_Chi_Minh (``late``).
- ``active`` -- otherwise.

Analytics progress comes from the cursors the daily poll and the history walk
already keep in ``shop_ingestion_state``; the partition table is not written by
the live path, so it is deliberately not read here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingestion import (
    BOOTSTRAP_FAILED,
    BOOTSTRAP_HISTORY_DONE,
    ShopIngestionState,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.services.onboarding import history_days_available

BACKFILL_TARGET_DAYS = 90
#: Yesterday's analytics are expected by this local hour (contract p101 §4).
DATA_DUE_HOUR_VN = 9
_VN = ZoneInfo("Asia/Ho_Chi_Minh")
_NEEDS_REAUTH = "needs_reauth"

STATE_DISCONNECTED = "disconnected"
STATE_NEEDS_REAUTH = "needs_reauth"
STATE_BACKFILLING = "backfilling"
STATE_DEGRADED = "degraded"
STATE_ACTIVE = "active"


@dataclass(frozen=True)
class ShopSyncStatus:
    state: str
    backfilling: bool
    history_days_done: int
    history_days_total: int
    #: Last day whose analytics were fetched completely (the "Số liệu đến" date).
    data_through: date | None
    #: Yesterday (VN) is still missing after 09:00 VN.
    late: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "backfilling": self.backfilling,
            "history_days_done": self.history_days_done,
            "history_days_total": self.history_days_total,
            "data_through": self.data_through.isoformat() if self.data_through else None,
            "late": self.late,
        }


def _vn_now(now: datetime | None) -> datetime:
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(_VN)


def is_late(data_through: date | None, *, now: datetime | None = None) -> bool:
    """After 09:00 VN, with data that stops before yesterday (VN)."""
    if data_through is None:
        return False
    local = _vn_now(now)
    if local.hour < DATA_DUE_HOUR_VN:
        return False
    return data_through < local.date() - timedelta(days=1)


def build_sync_status(
    credential_statuses: list[str],
    ingestion: ShopIngestionState | None,
    *,
    now: datetime | None = None,
) -> ShopSyncStatus:
    """The status from already-read rows (pure; see ``shop_sync_status``)."""
    days = min(history_days_available(ingestion), BACKFILL_TARGET_DAYS)
    through = ingestion.analytics_through_date if ingestion is not None else None
    late = is_late(through, now=now)
    failed = ingestion is not None and ingestion.status == BOOTSTRAP_FAILED
    walk_done = ingestion is not None and (
        ingestion.status == BOOTSTRAP_HISTORY_DONE or ingestion.history_done_at is not None
    )
    backfilling = not failed and not walk_done and days < BACKFILL_TARGET_DAYS

    if not credential_statuses:
        state = STATE_DISCONNECTED
    elif _NEEDS_REAUTH in credential_statuses:
        state = STATE_NEEDS_REAUTH
    elif backfilling:
        state = STATE_BACKFILLING
    elif late or failed:
        state = STATE_DEGRADED
    else:
        state = STATE_ACTIVE
    return ShopSyncStatus(
        state=state,
        backfilling=backfilling and state == STATE_BACKFILLING,
        history_days_done=days,
        history_days_total=BACKFILL_TARGET_DAYS,
        data_through=through,
        late=late,
    )


async def shop_sync_status(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> ShopSyncStatus:
    """Read the shop's credentials and ingestion state under its scope, then derive."""
    statuses = list(
        (
            await session.execute(
                select(TikTokCredential.status).where(TikTokCredential.shop_id == shop_id)
            )
        ).scalars()
    )
    ingestion = (
        await session.execute(
            select(ShopIngestionState).where(ShopIngestionState.shop_id == shop_id)
        )
    ).scalar_one_or_none()
    return build_sync_status(statuses, ingestion, now=now)
