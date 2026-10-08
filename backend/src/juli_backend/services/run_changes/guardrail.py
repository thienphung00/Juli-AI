"""The day-7 stability guardrail (fast track P8-C, ADR-109 d.11, D14).

At the day-7 check-in the impact reader has, per metric, a control-adjusted
``impact_pct`` for the changed product. For every metric the seller set a
stability band for and that the change was **not** meant to move (it is not the
primary target of any mutation in the write), a reading outside ``± band %``
is a breach. One or more breaches raise one "Hoàn tác?" question on the run
(``run_revert_questions``), linking to ``POST /v1/demo/runs/{id}/revert``.

Juli asks; it never reverts on its own. No band set -> no question (logged).
A reading with no ``impact_pct`` (suppressed, confounded, not enough data) is
never a breach: there is no honest number to compare.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import QUESTION_OPEN, RunRevertQuestion

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BandBreach:
    metric: str
    impact_pct: Decimal
    band_pct: Decimal

    def to_json(self) -> dict[str, float | str]:
        return {
            "metric": self.metric,
            "impact_pct": float(round(self.impact_pct * 100, 2)),
            "band_pct": float(self.band_pct),
        }


def band_breaches(
    *,
    bands: Mapping[str, Decimal],
    impact_pct_by_metric: Mapping[str, Decimal | None],
    target_metrics: set[str],
) -> list[BandBreach]:
    """Non-target metrics whose ``|impact_pct|`` (a fraction) exceeds their band (a %)."""
    breaches: list[BandBreach] = []
    for metric, band in sorted(bands.items()):
        if metric in target_metrics:
            continue
        impact = impact_pct_by_metric.get(metric)
        if impact is None:
            continue
        if abs(impact) * 100 > band:
            breaches.append(BandBreach(metric=metric, impact_pct=impact, band_pct=band))
    return breaches


async def is_revert_run(session: AsyncSession, run_id: uuid.UUID) -> bool:
    found = await session.execute(
        select(WorkflowRunRow.reverts_run_id).where(WorkflowRunRow.id == run_id)
    )
    return found.scalar_one_or_none() is not None


async def raise_revert_question(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    breaches: list[BandBreach],
) -> RunRevertQuestion | None:
    """Insert the run's "Hoàn tác?" question, once per run. Flush, no commit."""
    if not breaches:
        return None
    existing = (
        await session.execute(
            select(RunRevertQuestion).where(
                RunRevertQuestion.shop_id == shop_id, RunRevertQuestion.workflow_run_id == run_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    question = RunRevertQuestion(
        shop_id=shop_id,
        workflow_run_id=run_id,
        breaches=[breach.to_json() for breach in breaches],
        status=QUESTION_OPEN,
    )
    session.add(question)
    await session.flush()
    logger.info(
        "day7_guardrail_question_raised",
        extra={
            "shop_id": str(shop_id),
            "run_id": str(run_id),
            "metrics": [breach.metric for breach in breaches],
        },
    )
    return question
