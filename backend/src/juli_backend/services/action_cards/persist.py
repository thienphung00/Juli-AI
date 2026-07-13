"""Persist scoring pipeline output to action_cards — ADR-021."""

from __future__ import annotations

import json
import uuid
from typing import cast

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


async def persist_scoring_result(
    session: AsyncSession,
    shop_id: uuid.UUID,
    result: DailyScoringResult,
) -> list[ActionCard]:
    """Upsert one action card per ranked workflow recommendation."""
    repo = ActionCardsRepo(session)
    cards: list[ActionCard] = []
    computed_at = result.signals.computed_at.isoformat()

    for recommendation in result.recommendations.recommended_workflows:
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
            metadata_json=json.dumps({"computed_at": computed_at}),
        )
        cards.append(card)

    return cards
