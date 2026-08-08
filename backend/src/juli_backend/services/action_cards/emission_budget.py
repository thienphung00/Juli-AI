"""Decision emission/surfacing budget — ADR-038 §6, #716 (B-4).

Throttles which persisted Action Card *candidates* (``status == "active"``)
surface into the Demo active set. Deliberately independent of recomputation:
``services.action_cards.persist.persist_scoring_result`` always refreshes a
candidate's content on every scoring run regardless of budget; this module
runs on its own cadence and only ever writes the surfacing columns
(``ActionCard.surfaced_at`` / ``ActionCard.suppressed_reason``) — never
title/priority/payload/computed_at. See MODULE.md "Emission/surfacing
persistence model" for why columns were chosen over a new ``status`` enum.

Postgres is sole source of truth here (this table plus the novelty ledger).
Nothing in this module reads or writes Redis.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import DecisionEmissionConfig, decision_emission_config
from juli_backend.models.models import ActionCard, DecisionEmissionNoveltyLedger

logger = logging.getLogger(__name__)

SUPPRESSED_REASON_ACTIVE_CAP = "active_cap"
SUPPRESSED_REASON_COOLDOWN = "cooldown"
SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP = "weekly_novelty_cap"

SUPPRESSED_REASONS: frozenset[str] = frozenset(
    {
        SUPPRESSED_REASON_ACTIVE_CAP,
        SUPPRESSED_REASON_COOLDOWN,
        SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP,
    }
)

# Only "active" (candidate, un-actioned) rows are eligible for surfacing
# consideration. Anything in persist.IN_FLIGHT_STATUSES has already left the
# candidate pool structurally (persist_scoring_result freezes it in place)
# and is not re-litigated here.
_CANDIDATE_STATUS = "active"


@dataclass(frozen=True, slots=True)
class EmissionBudgetOutcome:
    """Result of one ``apply_emission_budget`` run for a shop."""

    surfaced: list[ActionCard]
    suppressed: dict[str, list[ActionCard]]


def _week_start(now: datetime) -> date:
    """Monday (UTC date) of the ISO week containing *now*."""
    today = now.date()
    return today - timedelta(days=today.weekday())


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _terminal_marker(card: ActionCard) -> datetime | None:
    """Most recent terminal-action timestamp on *card*, if any.

    Considers all three terminal markers (approved_at / executed_at /
    dismissed_at). These are read off *already-loaded* ``ActionCard`` rows
    (the caller's single ``WHERE shop_id=:s AND status='active'`` query,
    served by the pre-existing ``ix_action_cards_shop_status``) — this
    function issues no query of its own, so no index backs it today. The
    composite ``ix_action_cards_shop_workflow_terminal`` index (shop_id,
    workflow_key, dismissed_at, approved_at, executed_at) is provisioned
    ahead of need, for a cooldown lookup query a future slice may issue
    directly against Postgres instead of computing this in Python.
    """
    raw_markers = (card.approved_at, card.executed_at, card.dismissed_at)
    markers = [ts for ts in raw_markers if ts is not None]
    if not markers:
        return None
    return max(_as_aware(ts) for ts in markers)


def _in_cooldown(card: ActionCard, *, now: datetime, cooldown_days: int) -> bool:
    marker = _terminal_marker(card)
    if marker is None:
        return False
    return _as_aware(now) - marker < timedelta(days=cooldown_days)


async def _novel_workflow_keys_this_week(
    session: AsyncSession, shop_id: uuid.UUID, week_start: date
) -> set[str]:
    stmt = select(DecisionEmissionNoveltyLedger.workflow_key).where(
        DecisionEmissionNoveltyLedger.shop_id == shop_id,
        DecisionEmissionNoveltyLedger.week_start == week_start,
    )
    result = await session.execute(stmt)
    return set(result.scalars().all())


def _log_suppressed(shop_id_str: str, card: ActionCard, reason: str) -> None:
    """One structured log entry per suppressed candidate (on-call diagnosability
    of Decision lag, #716 AC "emission-drop reason codes are logged").

    Deliberately per-suppression, not only an aggregate: an on-call engineer
    investigating why a *specific* shop's Decision feed looks stale needs to
    see which ``workflow_key`` dropped and why, not just a count. Carries
    only system identifiers (shop id, workflow key, reason code) — never
    ``card.title`` / ``card.description`` / ``card.recommendation_payload``,
    which may carry seller-identifying or financial content (PRD security
    stories 22/23 — no PII, no tokens, no raw financial values in logs).
    """
    logger.info(
        "emission_budget_suppressed",
        extra={
            "shop_id": shop_id_str,
            "workflow_key": card.workflow_key,
            "suppressed_reason": reason,
        },
    )


async def apply_emission_budget(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime | None = None,
    config: DecisionEmissionConfig | None = None,
) -> EmissionBudgetOutcome:
    """Throttle persisted candidate Action Cards into the active surfaced set.

    Evaluates every ``status == "active"`` candidate row for *shop_id*, in
    priority order, against three gates (in this order): the 7-day
    per-workflow cooldown, the soft weekly novelty quota, then the active-cap
    budget. Every evaluated candidate gets a fresh ``surfaced_at`` /
    ``suppressed_reason`` decision — this function never touches candidate
    content. Performs no commit (same isolated-failure-domain pattern as
    ``persist_scoring_result``); the caller controls the transaction.
    """
    now = _as_aware(now) if now is not None else datetime.now(UTC)
    config = config or decision_emission_config()
    week_start = _week_start(now)
    shop_id_str = str(shop_id)

    stmt = (
        select(ActionCard)
        .where(ActionCard.shop_id == shop_id, ActionCard.status == _CANDIDATE_STATUS)
        .order_by(ActionCard.priority.asc(), ActionCard.workflow_key.asc())
    )
    candidates = list((await session.execute(stmt)).scalars().all())

    counted_novel = await _novel_workflow_keys_this_week(session, shop_id, week_start)
    novelty_used = len(counted_novel)

    surfaced: list[ActionCard] = []
    suppressed: dict[str, list[ActionCard]] = {reason: [] for reason in SUPPRESSED_REASONS}

    for card in candidates:
        if _in_cooldown(card, now=now, cooldown_days=config.cooldown_days):
            card.surfaced_at = None
            card.suppressed_reason = SUPPRESSED_REASON_COOLDOWN
            suppressed[SUPPRESSED_REASON_COOLDOWN].append(card)
            _log_suppressed(shop_id_str, card, SUPPRESSED_REASON_COOLDOWN)
            continue

        is_new_this_week = card.workflow_key not in counted_novel
        if is_new_this_week and novelty_used >= config.weekly_novelty_cap:
            card.surfaced_at = None
            card.suppressed_reason = SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP
            suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP].append(card)
            _log_suppressed(shop_id_str, card, SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP)
            continue

        if len(surfaced) >= config.max_active:
            card.surfaced_at = None
            card.suppressed_reason = SUPPRESSED_REASON_ACTIVE_CAP
            suppressed[SUPPRESSED_REASON_ACTIVE_CAP].append(card)
            _log_suppressed(shop_id_str, card, SUPPRESSED_REASON_ACTIVE_CAP)
            continue

        card.surfaced_at = now
        card.suppressed_reason = None
        surfaced.append(card)

        if is_new_this_week:
            novelty_used += 1
            counted_novel.add(card.workflow_key)
            session.add(
                DecisionEmissionNoveltyLedger(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    week_start=week_start,
                    workflow_key=card.workflow_key,
                    first_surfaced_at=now,
                )
            )

    await session.flush()

    # Aggregate, per-reason counts *in addition to* (never instead of) the
    # per-suppression ``emission_budget_suppressed`` entries logged above —
    # cheap to scan/alert on, but not a substitute for drilling into which
    # workflow_key dropped for a given shop.
    logger.info(
        "emission_budget_applied",
        extra={
            "shop_id": shop_id_str,
            "surfaced_count": len(surfaced),
            "suppressed_active_cap": len(suppressed[SUPPRESSED_REASON_ACTIVE_CAP]),
            "suppressed_cooldown": len(suppressed[SUPPRESSED_REASON_COOLDOWN]),
            "suppressed_weekly_novelty_cap": len(suppressed[SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP]),
        },
    )
    return EmissionBudgetOutcome(surfaced=surfaced, suppressed=suppressed)
