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

#: The ONLY confidence values that count as an incremental-impact reading —
#: the real tiers from ``services/impact/confidence.py``'s ``TierOutcome``.
#: Named here, once, so every surface answering "what was the impact" reuses
#: this rule instead of re-declaring the tier list at its own call site: a
#: second copy is a second thing to drift (#1062's defect class), and the
#: whole point of #1338 was to make #1226's dishonesty structurally
#: unreachable rather than a convention each new reader re-observes.
#: :data:`EXCLUDED_CONFIDENCES` is its complement over the
#: ``ck_impact_readings_confidence`` check constraint.
COUNTABLE_CONFIDENCES: tuple[str, ...] = ("cao", "trung_binh", "thap")

#: ``suppressed`` (insufficient signal) and ``confounded`` (a competing
#: change) are NOT readings — but they are not each other either, and
#: neither is "zero impact". A surface that shows them at all must show
#: each under its own name; this tuple exists so such a surface can
#: recognise them without inventing its own literal list.
EXCLUDED_CONFIDENCES: tuple[str, ...] = ("suppressed", "confounded")


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
        ImpactReading.confidence.in_(COUNTABLE_CONFIDENCES),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
