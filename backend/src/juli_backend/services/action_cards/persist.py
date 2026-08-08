"""Persist scoring pipeline output to action_cards — ADR-021, #715 (B-3)."""

from __future__ import annotations

import json
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard
from juli_backend.repositories.repos import ActionCardsRepo
from juli_backend.services.scoring.types import (
    DailyScoringResult,
    KpiId,
    Severity,
    WorkflowReasoningSummary,
)

_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "warning": 3,
    "healthy": 2,
    "not_applicable": 1,
}

# In-flight / terminal card statuses that a re-scoring candidate must not
# clobber (#715, B-3). A candidate row only ever proposes "active"; once a
# seller (or dry-run flow) has moved a card past that — approved, dismissed,
# or executing — continuous re-scoring must not silently reset it back.
IN_FLIGHT_STATUSES: frozenset[str] = frozenset({"approved", "dismissed", "executing"})


def _reasoning_for(
    summaries: tuple[WorkflowReasoningSummary, ...],
    workflow_key: str,
) -> WorkflowReasoningSummary | None:
    for item in summaries:
        if item.workflow_key == workflow_key:
            return item
    return None


def _severity_for_recommendation(
    result: DailyScoringResult,
    workflow_key: str,
    source_kpi_ids: tuple[str, ...],
) -> Severity:
    severities: list[Severity] = []
    for kpi_id in source_kpi_ids:
        signal = result.signals.kpis.get(cast(KpiId, kpi_id))
        if signal is not None:
            severities.append(signal.severity)
    if not severities:
        return "healthy"
    return max(severities, key=lambda value: _SEVERITY_RANK.get(value, 0))


def _build_payload(
    result: DailyScoringResult,
    recommendation,
    reasoning: WorkflowReasoningSummary | None,
) -> dict:
    payload = {
        "workflow_key": recommendation.workflow_key,
        "workflow_name": recommendation.workflow_name,
        "priority": recommendation.priority,
        "rationale": recommendation.rationale,
        "expected_impact": {
            "metric": recommendation.expected_impact.metric,
            "value": recommendation.expected_impact.value,
            "confidence": recommendation.expected_impact.confidence,
        },
        "preconditions_met": recommendation.preconditions_met,
        "user_action_required": recommendation.user_action_required,
        "source_kpi_ids": list(recommendation.source_kpi_ids),
        "computed_at": result.signals.computed_at.isoformat(),
    }
    if reasoning is not None:
        payload["reasoning"] = {
            "copy_source": reasoning.copy.copy_source,
            "why": reasoning.copy.why,
            "expected_impact": reasoning.copy.expected_impact,
            "next_steps": list(reasoning.copy.next_steps),
            "source_kpi_ids": list(reasoning.copy.source_kpi_ids),
        }
    return payload


async def _existing_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    workflow_key: str,
) -> ActionCard | None:
    """Look up the persisted card for (shop_id, workflow_key), if any.

    Deliberately bypasses ``ActionCardsRepo.upsert`` (which always overwrites)
    so the in-flight status guard below can decide *before* touching the row.
    """
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == workflow_key,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def persist_scoring_result(
    session: AsyncSession,
    shop_id: uuid.UUID,
    result: DailyScoringResult,
) -> list[ActionCard]:
    """Upsert one action card per ranked workflow recommendation.

    Idempotent on ``(shop_id, workflow_key)`` (#715, B-3): repeated scoring
    runs for the same workflow_key update the existing row in place — never a
    duplicate insert (unique constraint backstops this even under a race).

    Status preservation: a card already in an in-flight/terminal status
    (``IN_FLIGHT_STATUSES`` — approved/dismissed/executing) is left completely
    untouched by a new candidate from re-scoring; only a card still in the
    default ``"active"`` candidate status (or not yet persisted) is upserted.

    Freshness metadata: ``computed_at`` from the scoring run's
    ``ScoringSignals`` is persisted on a real, queryable column — aligned with
    Analytics envelope freshness semantics (ADR-038; see
    ``GoldKpiEnvelope.computed_at`` / ``AnalyticsKpiEnvelope.computed_at``) —
    in addition to the existing ``metadata_json`` / payload copies kept for
    backward-compatible reads.
    """
    repo = ActionCardsRepo(session)
    cards: list[ActionCard] = []
    computed_at = result.signals.computed_at
    computed_at_iso = computed_at.isoformat()

    for recommendation in result.recommendations.recommended_workflows:
        existing = await _existing_card(session, shop_id, recommendation.workflow_key)
        if existing is not None and existing.status in IN_FLIGHT_STATUSES:
            # Candidate recomputed but not surfaced over an in-flight card —
            # do not overwrite status, content, or freshness metadata.
            cards.append(existing)
            continue

        reasoning = _reasoning_for(result.reasoning_summaries, recommendation.workflow_key)
        severity = _severity_for_recommendation(
            result,
            recommendation.workflow_key,
            recommendation.source_kpi_ids,
        )
        description = reasoning.copy.why if reasoning is not None else recommendation.rationale
        payload = _build_payload(result, recommendation, reasoning)

        card = await repo.upsert(
            shop_id=shop_id,
            workflow_key=recommendation.workflow_key,
            priority=recommendation.priority,
            severity=severity,
            title=recommendation.workflow_name,
            description=description,
            recommendation_payload=json.dumps(payload),
            status="active",
            metadata_json=json.dumps({"computed_at": computed_at_iso}),
            computed_at=computed_at,
        )
        cards.append(card)

    return cards
