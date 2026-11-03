"""Decision rules-scoring callable for the continuous-trigger seam (#714 / B-2).

Bridges the ``ScoringStageFn`` seam defined in ``shared_compute_orchestrator.py``
(``Callable[[AsyncSession, SharedComputeJob], Awaitable[Any]]``) onto the
**existing** Phase 2 rules pipeline (aggregates -> signals -> recommendations ->
rules copy) via ``run_daily_scoring_for_shop`` — the same callable manual refresh
(``POST /v1/action-cards/refresh`` -> ``run_action_card_refresh``) uses. There is
exactly one scoring implementation; this module only adapts its call signature to
the continuous-trigger seam. No forked or parallel scoring math (ADR-021).

Scope (see docs/handoffs/phase-3.5-prd-bodies/b-decisions.md "Rules Scoring Wire"):
this module computes the ``DailyScoringResult`` candidate and, as of #715 (B-3
wiring), durably persists it via the **existing**
``services.action_cards.persist.persist_scoring_result`` — the same idempotent,
status-preserving persistence boundary the manual refresh path uses. No second
persistence path is implemented here (ADR-021). As of the #716 (B-4) Meta
routing correction, this module also applies the emission/surfacing budget
(``services.action_cards.emission_budget.apply_emission_budget``) immediately
after persistence, on the same compute run — PRD #599's "candidate upsert ->
emission filter" step. Every ranked recommendation is still persisted as an
``"active"`` candidate regardless of budget outcome; the budget only decides
``surfaced_at`` / ``suppressed_reason`` on top of that (dual cadence, ADR-038
§6). Uses the shop-scoped inputs already fetched into bronze/silver by the
same Shared Compute job — no second Partner fetch cycle.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.action_cards.emission_budget import apply_emission_budget
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.aggregates.types import ShopLifecycleContext
from juli_backend.services.cdp_speed.shared_compute_orchestrator import SharedComputeJob
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.types import DailyScoringResult

logger = logging.getLogger(__name__)

#: P88: the continuous trigger scores a shop at most once per this window. Each pass reads
#: the shop's rolling-window orders, items and 60 product days; webhooks and the staggered
#: reconcile fired it ~57x/day. The daily poll pass and a seller's manual refresh call
#: ``run_daily_scoring_for_shop`` directly and are not gated.
SCORING_MIN_INTERVAL_SECONDS = 3600

ClaimFn = Callable[[str], bool]


def scoring_gate_key(shop_id: str) -> str:
    return f"cdp:scoring-gate:{shop_id}"


_redis_client: Any = None
_redis_url: str = ""


def _default_claim() -> ClaimFn | None:
    """``SET NX EX`` on the shop's gate key; ``None`` without Redis (the stage then runs)."""
    global _redis_client, _redis_url
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    if _redis_client is None or _redis_url != url:
        import redis

        _redis_client = redis.from_url(url)
        _redis_url = url
    client = _redis_client

    def claim(shop_id: str) -> bool:
        key = scoring_gate_key(shop_id)
        return bool(client.set(key, "1", nx=True, ex=SCORING_MIN_INTERVAL_SECONDS))

    return claim


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

    Persists the computed candidates via ``persist_scoring_result`` (#715, B-3)
    before returning, so a webhook or reconcile-triggered scoring run produces
    durable Action Card rows instead of a result that is computed and thrown
    away. Persistence failures propagate to the caller (the Shared Compute
    Orchestrator's isolated scoring failure domain, #713/B-1) rather than being
    swallowed here — the orchestrator rolls back only this stage's own writes,
    never the already-committed KPI envelope.

    Applies the emission/surfacing budget (``apply_emission_budget``, #716/B-4)
    right after persistence, on the same compute run (PRD #599: "candidate
    upsert -> emission filter"). The candidates are committed *before* the
    budget runs, on their own durability boundary — a budget failure never
    discards what ``persist_scoring_result`` just wrote (dual cadence:
    recomputation and surfacing are independently gated, which is the entire
    point of #716). A budget failure is still not silently swallowed: it is
    logged here with stage context, then re-raised so it also lands in the
    orchestrator's own isolated scoring failure domain
    (``SharedComputeResult.scoring_succeeded=False``) exactly like a
    persistence failure would.
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
    persisted_cards = await persist_scoring_result(session, job.shop_id, result)
    logger.info(
        "decision_rules_scoring_stage_persisted",
        extra={
            "shop_id": str(job.shop_id),
            "enqueue_reason": job.enqueue_reason,
            "persisted_card_count": len(persisted_cards),
        },
    )

    # Commit the persisted candidates on their own boundary, independent of
    # the emission budget below. This is the dual-cadence guarantee: a
    # recomputation must be durable even when the surfacing decision that
    # follows it fails. Only the orchestrator's earlier KPI-envelope commit
    # sits ahead of this one; nothing after this point can roll it back.
    await session.commit()

    try:
        outcome = await apply_emission_budget(session, job.shop_id, now=computed_at)
    except Exception:
        logger.exception(
            "decision_rules_scoring_stage_emission_failed",
            extra={
                "shop_id": str(job.shop_id),
                "enqueue_reason": job.enqueue_reason,
            },
        )
        # Roll back only the emission budget's own (uncommitted) writes —
        # the candidates committed above are untouched. Re-raise: this is
        # containment of the *data*, not suppression of the *failure*. The
        # exception still propagates into the orchestrator's isolated
        # scoring failure domain (#713/B-1), which logs it again and
        # records scoring_succeeded=False for observability.
        await session.rollback()
        raise

    logger.info(
        "decision_rules_scoring_stage_emission_applied",
        extra={
            "shop_id": str(job.shop_id),
            "enqueue_reason": job.enqueue_reason,
            "surfaced_count": len(outcome.surfaced),
            "suppressed_count": sum(len(cards) for cards in outcome.suppressed.values()),
        },
    )

    return result


async def hourly_scoring_stage(
    session: AsyncSession,
    job: SharedComputeJob,
    *,
    claim: ClaimFn | None = None,
) -> DailyScoringResult | None:
    """:func:`decision_rules_scoring_stage`, at most once per shop per hour (P88).

    The production continuous-trigger seam. A skipped pass returns ``None``; the next
    trigger after the window scores from the then-current silver rows. A Redis failure
    fails open (scores), so a broken cache never freezes the cards.
    """
    key = str(job.shop_id)
    try:
        claim_fn = claim or _default_claim()
        claimed = True if claim_fn is None else claim_fn(key)
    except Exception:
        logger.warning("decision_rules_scoring_gate_failed", extra={"shop_id": key}, exc_info=True)
        claimed = True
    if not claimed:
        logger.info(
            "decision_rules_scoring_stage_throttled",
            extra={"shop_id": key, "enqueue_reason": job.enqueue_reason},
        )
        return None
    return await decision_rules_scoring_stage(session, job)
