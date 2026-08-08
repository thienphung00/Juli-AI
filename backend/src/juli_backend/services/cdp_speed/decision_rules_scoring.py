"""Decision rules-scoring callable for the continuous-trigger seam (#714 / B-2).

Bridges the ``ScoringStageFn`` seam defined in ``shared_compute_orchestrator.py``
(``Callable[[AsyncSession, SharedComputeJob], Awaitable[Any]]``) onto the
**existing** Phase 2 rules pipeline (aggregates -> signals -> recommendations ->
rules copy) via ``run_daily_scoring_for_shop`` — the same callable manual refresh
(``POST /v1/action-cards/refresh`` -> ``run_action_card_refresh``) uses. There is
exactly one scoring implementation; this module only adapts its call signature to
the continuous-trigger seam. No forked or parallel scoring math (ADR-021).

Scope (see docs/handoffs/phase-3.5-prd-bodies/b-decisions.md "Rules Scoring Wire"):
this module returns the computed ``DailyScoringResult`` candidate — it does not
persist Action Cards (persistence-on-compute is #715 / B-3) and does not apply an
emission/surfacing budget (#716 / B-4). Uses the shop-scoped inputs already
fetched into bronze/silver by the same Shared Compute job — no second Partner
fetch cycle.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.aggregates.types import ShopLifecycleContext
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.types import DailyScoringResult

logger = logging.getLogger(__name__)


async def decision_rules_scoring_stage(
    session: AsyncSession,
    job: SharedComputeJob,
    *,
    lifecycle: ShopLifecycleContext | None = None,
    computed_at: datetime | None = None,
) -> DailyScoringResult:
    """Continuous-trigger scoring callable — same pipeline as manual refresh.

    Matches the ``ScoringStageFn`` seam signature: called with exactly
    ``(session, job)`` in production. ``lifecycle`` / ``computed_at`` are
    keyword-only test seams (default ``None``, mirroring
    ``run_daily_scoring_for_shop``'s own defaults) so golden/regression tests can
    pin a deterministic clock without touching the seam's call contract.
    """
    result = await run_daily_scoring_for_shop(
        session,
        job.shop_id,
        lifecycle=lifecycle,
        computed_at=computed_at,
    )
    logger.info(
        "decision_rules_scoring_stage_computed",
        extra={
            "shop_id": str(job.shop_id),
            "enqueue_reason": job.enqueue_reason,
            "recommended_workflow_count": len(result.recommendations.recommended_workflows),
        },
    )
    return result
