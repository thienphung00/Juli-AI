"""F4.13 (C6): the Connector readers that did not finish well, from the stored tick reports.

Ops reads the shop's ``system_connector_tick`` audit rows (a run's per-reader outcomes) and
lists, per reader, its newest outcome when it is not ``done`` / ``fresh`` / ``skipped``
(``error:*``, ``timeout``, ``needs_template:*``, ``blocked:*``, ``open_failed``,
``waiting_budget``, ``partial:*``) and since when it has been the same. Metadata only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.ops import audit
from juli_backend.services.shopee_recommendations.connector_state import ACTION_CONNECTOR_TICK

#: How far back the tick reports are read, and how many (a day has a few runs).
LOOKBACK = timedelta(days=3)
MAX_TICKS = 200
_GOOD = ("done", "fresh", "skipped")


def is_problem(outcome: str) -> bool:
    return not outcome.startswith(_GOOD)


def _at(row: OpsAuditLog) -> datetime:
    stamp = (row.after or {}).get("occurred_at")
    if isinstance(stamp, str):
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            return moment.replace(tzinfo=None) - (moment.utcoffset() or timedelta(0))
        except ValueError:
            pass
    return row.at


def problems_of(rows: list[OpsAuditLog]) -> list[dict[str, Any]]:
    """``rows``: the shop's tick audit rows. Per reader: the newest outcome when it is a problem,
    and the time of the oldest report in the unbroken run of that same outcome."""
    runs = sorted((r for r in rows if (r.after or {}).get("kind") == "run"), key=_at, reverse=True)
    newest: dict[str, str] = {}
    since: dict[str, datetime] = {}
    ended: set[str] = set()
    for row in runs:
        at = _at(row)
        for reader, outcome in ((row.after or {}).get("outcomes") or {}).items():
            outcome = str(outcome)
            if reader not in newest:
                newest[reader] = outcome
                since[reader] = at
            elif reader not in ended:
                if outcome == newest[reader]:
                    since[reader] = at
                else:
                    ended.add(reader)
    return [
        {"reader": reader, "outcome": outcome, "since": since[reader].isoformat() + "Z"}
        for reader, outcome in sorted(newest.items())
        if is_problem(outcome)
    ]


async def reader_problems(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> list[dict[str, Any]]:
    rows = await audit.list_entries(session, shop_id=shop_id, kind="system", limit=MAX_TICKS)
    fresh = [r for r in rows if r.action == ACTION_CONNECTOR_TICK and r.at >= now - LOOKBACK]
    return problems_of(fresh)
