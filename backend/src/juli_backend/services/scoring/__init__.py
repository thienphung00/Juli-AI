"""Rules-based daily batch scoring — aggregates → signals → recommendations → copy (#303, #304)."""

from juli_backend.services.scoring.advisory import format_advisory_one_line
from juli_backend.services.scoring.batch import run_daily_scoring_batch
from juli_backend.services.scoring.copy_layer import (
    COPY_SOURCE_RULES,
    WORKFLOW_COPY_TEMPLATE_KEYS,
    build_reasoning_for_recommendations,
    build_workflow_reasoning_copy,
)
from juli_backend.services.scoring.kpi_catalog import (
    KPI_WORKFLOW_KEYS,
    get_workflows_for_profile,
)
from juli_backend.services.scoring.pipeline import run_daily_scoring_for_shop
from juli_backend.services.scoring.recommendations import rank_workflow_recommendations
from juli_backend.services.scoring.schedule import (
    DAILY_SCORING_CRON_UTC,
    DAILY_SCORING_UTC_HOUR,
    DAILY_SCORING_UTC_MINUTE,
)
from juli_backend.services.scoring.signals import compute_scoring_signals
from juli_backend.services.scoring.types import (
    VISUAL_LAYER_KPI_IDS,
    AdvisorySignal,
    DailyScoringResult,
    ScoringSignals,
    VisualLayerDomain,
    WorkflowReasoningCopy,
    WorkflowReasoningSummary,
    WorkflowRecommendations,
)

__all__ = [
    "AdvisorySignal",
    "COPY_SOURCE_RULES",
    "DAILY_SCORING_CRON_UTC",
    "DAILY_SCORING_UTC_HOUR",
    "DAILY_SCORING_UTC_MINUTE",
    "DailyScoringResult",
    "KPI_WORKFLOW_KEYS",
    "ScoringSignals",
    "VisualLayerDomain",
    "VISUAL_LAYER_KPI_IDS",
    "WORKFLOW_COPY_TEMPLATE_KEYS",
    "WorkflowReasoningCopy",
    "WorkflowReasoningSummary",
    "WorkflowRecommendations",
    "build_reasoning_for_recommendations",
    "build_workflow_reasoning_copy",
    "compute_scoring_signals",
    "format_advisory_one_line",
    "get_workflows_for_profile",
    "rank_workflow_recommendations",
    "run_daily_scoring_batch",
    "run_daily_scoring_for_shop",
]
