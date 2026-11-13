"""What the Connector last told Juli about itself, and the one command Juli can give it (P100).

Tables ``shopee_connector_state`` (one row per shop) and ``shopee_connector_commands`` (migration
128).

- Heartbeat: the Connector's fill-job poll (every few minutes) says whether a Seller Centre tab is
  open and acknowledges the command it ran.
- Command ``reconcile`` ("Đối chiếu ngay"): the web app asks, the next poll hands it to the
  Connector (``pending`` -> ``sent``), which runs its readers now; the ack closes it (``acked``).

Reviewer requests never write here (``reviewer_session_active``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_connector import (
    COMMAND_ACKED,
    COMMAND_PENDING,
    COMMAND_RECONCILE,
    COMMAND_SENT,
    ShopeeConnectorCommand,
    ShopeeConnectorState,
)
from juli_backend.services.shop_proposals.cycle import ProposalError

COMMAND_ID_MAX = 64
#: The poll runs every 3 minutes; a heartbeat older than this says nothing about the tab.
HEARTBEAT_FRESH = timedelta(minutes=10)
ERROR_REVIEWER = "connector_command_refused"
_OPEN = (COMMAND_PENDING, COMMAND_SENT)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat() + "Z"


async def _open_command(
    session: AsyncSession, shop_id: uuid.UUID, kind: str = COMMAND_RECONCILE
) -> ShopeeConnectorCommand | None:
    return await session.scalar(
        select(ShopeeConnectorCommand).where(
            ShopeeConnectorCommand.shop_id == shop_id,
            ShopeeConnectorCommand.type == kind,
            ShopeeConnectorCommand.status.in_(_OPEN),
        )
    )


async def record_heartbeat(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    seller_centre_open: bool | None,
    ack: str | None,
    now: datetime,
    version: str | None = None,
) -> None:
    """The Connector's poll: the tab flag (None = it did not say), its version, and the command it
    ran (an id this shop does not have, or one already closed, changes nothing)."""
    row = await session.get(ShopeeConnectorState, shop_id)
    if row is None:
        row = ShopeeConnectorState(shop_id=shop_id)
        session.add(row)
    row.heartbeat_at = now
    row.updated_at = now
    if seller_centre_open is not None:
        row.seller_centre_open = seller_centre_open
    if version:
        row.connector_version = version[:32]
    if ack:
        try:
            command_id = uuid.UUID(ack)
        except ValueError:
            command_id = None
        cmd = None if command_id is None else await session.get(ShopeeConnectorCommand, command_id)
        if cmd is not None and cmd.shop_id == shop_id and cmd.status in _OPEN:
            cmd.status, cmd.acked_at = COMMAND_ACKED, now
    await session.flush()


async def request_reconcile(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    """ "Đối chiếu ngay": queue the command (one open at a time; asking twice keeps the first)."""
    from juli_backend.integrations.tiktok import reviewer_session_active

    if reviewer_session_active():
        raise ProposalError(ERROR_REVIEWER, 403)
    cmd = await _open_command(session, shop_id)
    if cmd is None:
        cmd = ShopeeConnectorCommand(
            id=uuid.uuid4(), shop_id=shop_id, type=COMMAND_RECONCILE, status=COMMAND_PENDING,
            created_at=now,
        )  # fmt: skip
        session.add(cmd)
        await session.flush()
    return {"requested": True, "command_id": str(cmd.id)}


async def commands(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> list[dict[str, str]]:
    """The open command for the Connector's poll (handed over once ``pending``; until it is acked
    the same id is served again, the Connector runs each id once)."""
    cmd = await _open_command(session, shop_id)
    if cmd is None:
        return []
    if cmd.status == COMMAND_PENDING:
        cmd.status, cmd.sent_at = COMMAND_SENT, now
        await session.flush()
    return [{"type": cmd.type, "id": str(cmd.id)}]


async def read(session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> dict[str, Any]:
    row = await session.get(ShopeeConnectorState, shop_id)
    beat = row.heartbeat_at if row else None
    fresh = beat is not None and now - beat <= HEARTBEAT_FRESH
    return {
        "heartbeat_at": _iso(beat),
        "alive": fresh,
        "seller_centre_open": row.seller_centre_open if row and fresh else None,
        "connector_version": row.connector_version if row else None,
        "reconcile_pending": await _open_command(session, shop_id) is not None,
    }
