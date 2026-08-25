"""Impact read-side honesty rule — ADR-085 decision 8 (#1338).

#1226 forbids closing the gate by "producing a suppressed reading and calling
it a reading." Make that structural: no surface, report or query that answers
"what was the impact" may count a suppressed or confounded row as a reading.

With ONLY suppressed rows present, the gate-closing query returns ZERO rows.
Asserted directly, because this is the exact dishonesty #1226 names by name.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading


async def list_impact_readings_honest(
    session: AsyncSession,
    tool_execution_id: uuid.UUID,
) -> list[ImpactReading]:
    """List impact readings for an execution, excluding suppressed/confounded.

    Returns only rows with real confidence tiers (cao, trung_binh, thap).
    Suppressed and confounded readings are not counted as readings in any
    gate-closing query or impact report answering "what was the impact".

    Where suppressed/confounded are shown at all (e.g., in detailed audit views),
    they must be labelled as their own outcome, never as zero impact.
    """
    stmt = select(ImpactReading).where(
        ImpactReading.tool_execution_id == tool_execution_id,
        ImpactReading.confidence.in_(["cao", "trung_binh", "thap"]),
    )
    result = await session.execute(stmt)
    return result.scalars().all()
