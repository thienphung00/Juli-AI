"""Rank execution_layer workflows from visual_layer advisory signals (#303)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from juli_backend.services.aggregates.types import ShopProfile
from juli_backend.services.scoring.kpi_catalog import (
    WORKFLOW_DISPLAY_NAMES,
    get_workflows_for_profile,
)
from juli_backend.services.scoring.types import (
    AdvisorySignal,
    ImpactConfidence,
    ScoringSignals,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

_SEVERITY_SCORE = {
    "critical": 100.0,
    "warning": 50.0,
    "healthy": 10.0,
    "not_applicable": 0.0,
}


@dataclass(frozen=True)
class _ScoredWorkflow:
    workflow_key: str
    score: float
    rationale: str
    expected_impact: WorkflowExpectedImpact
    preconditions_met: bool
    source_kpi_ids: tuple[str, ...]


def _severity_to_confidence(severity: str) -> ImpactConfidence:
    if severity == "critical":
        return "high"
    if severity == "warning":
        return "medium"
    return "low"


def _impact_value(signal: AdvisorySignal) -> float:
    if signal.kpi_id == "return_request_rate" and signal.signal_type == "risk":
        return signal.severity == "critical" and 100.0 or 50.0
    return _SEVERITY_SCORE[signal.severity]


def _score_workflows(
    profile: ShopProfile,
    signals: ScoringSignals,
) -> list[_ScoredWorkflow]:
    eligible = get_workflows_for_profile(profile)
    by_workflow: dict[str, list[AdvisorySignal]] = defaultdict(list)

    for signal in signals.kpis.values():
        if signal.signal_type == "unavailable":
            continue
        for key in signal.workflow_keys:
            if key in eligible:
                by_workflow[key].append(signal)

    scored: list[_ScoredWorkflow] = []
    for workflow_key, linked in by_workflow.items():
        best = max(
            linked,
            key=lambda item: (_SEVERITY_SCORE[item.severity], item.signal_type == "risk"),
        )
        score = _SEVERITY_SCORE[best.severity] + (10.0 if best.signal_type == "risk" else 0.0)
        source_kpis = tuple(sorted({item.kpi_id for item in linked}))
        scored.append(
            _ScoredWorkflow(
                workflow_key=workflow_key,
                score=score,
                rationale=best.one_line,
                expected_impact=WorkflowExpectedImpact(
                    metric=best.kpi_id,
                    value=_impact_value(best),
                    confidence=_severity_to_confidence(best.severity),
                ),
                preconditions_met=best.severity in {"critical", "warning", "healthy"},
                source_kpi_ids=source_kpis,
            )
        )

    return sorted(scored, key=lambda item: item.score, reverse=True)


def rank_workflow_recommendations(
    profile: ShopProfile,
    signals: ScoringSignals,
) -> WorkflowRecommendations:
    ranked = _score_workflows(profile, signals)
    return WorkflowRecommendations(
        shop_profile=profile,
        recommended_workflows=[
            WorkflowRecommendation(
                workflow_key=item.workflow_key,
                workflow_name=WORKFLOW_DISPLAY_NAMES.get(
                    item.workflow_key, item.workflow_key
                ),
                priority=index + 1,
                rationale=item.rationale,
                expected_impact=item.expected_impact,
                preconditions_met=item.preconditions_met,
                user_action_required=item.preconditions_met,
                source_kpi_ids=item.source_kpi_ids,
            )
            for index, item in enumerate(ranked)
        ],
    )
