from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)

ImpactConfidence = Literal["high", "medium", "low"]

SignalType = Literal["risk", "opportunity", "unavailable"]

TechniqueId = Literal["T3", "T7", "rules_proxy", "unavailable"]

Severity = Literal["critical", "warning", "healthy", "not_applicable"]


class VisualLayerDomain(StrEnum):
    SHOP_STATUS = "shop_status"
    REVENUE = "revenue"
    ADS = "ads"
    INVENTORY = "inventory"
    OPERATIONS = "operations"
    CUSTOMER_SERVICE = "customer_service"


KpiId = Literal[
    "sps",
    "ahr",
    "violation_points",
    "net_revenue",
    "aov",
    "revenue_by_sku",
    "conversion_rate_by_category",
    "repeat_purchase_rate",
    "roas",
    "cac",
    "ctr",
    "inventory_turnover",
    "dsi",
    "stockout_rate",
    "fulfillment_accuracy_rate",
    "orders_at_sla_risk",
    "seller_fault_cancellation_rate",
    "csat",
    "after_sales_handling_time",
    "return_request_rate",
]

VISUAL_LAYER_KPI_IDS: frozenset[str] = frozenset(
    {
        "sps",
        "ahr",
        "violation_points",
        "net_revenue",
        "aov",
        "revenue_by_sku",
        "conversion_rate_by_category",
        "repeat_purchase_rate",
        "roas",
        "cac",
        "ctr",
        "inventory_turnover",
        "dsi",
        "stockout_rate",
        "fulfillment_accuracy_rate",
        "orders_at_sla_risk",
        "seller_fault_cancellation_rate",
        "csat",
        "after_sales_handling_time",
        "return_request_rate",
    }
)

ExecutionWorkflowKey = str


@dataclass(frozen=True)
class AdvisorySignal:
    """visual_layer.md one-line advisory signal."""

    kpi_id: KpiId
    domain: VisualLayerDomain
    technique: TechniqueId
    change_text: str
    signal_type: SignalType
    action_hint: str
    one_line: str
    workflow_keys: tuple[ExecutionWorkflowKey, ...]
    severity: Severity


@dataclass(frozen=True)
class WorkflowExpectedImpact:
    metric: str
    value: float
    confidence: ImpactConfidence


@dataclass(frozen=True)
class WorkflowRecommendation:
    workflow_key: ExecutionWorkflowKey
    workflow_name: str
    priority: int
    rationale: str
    expected_impact: WorkflowExpectedImpact
    preconditions_met: bool
    user_action_required: bool
    source_kpi_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowRecommendations:
    shop_profile: ShopProfile
    recommended_workflows: list[WorkflowRecommendation]


@dataclass(frozen=True)
class ScoringSignals:
    shop_id: uuid.UUID
    computed_at: datetime
    health_data_source: HealthDataSource
    kpis: dict[KpiId, AdvisorySignal]


CopySource = Literal["rules"]


@dataclass(frozen=True)
class WorkflowReasoningCopy:
    """Rules-only reasoning copy from advisory signals (system-design § copy layer)."""

    copy_source: CopySource
    why: str
    expected_impact: str
    next_steps: tuple[str, ...]
    source_kpi_ids: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowReasoningSummary:
    workflow_key: ExecutionWorkflowKey
    copy: WorkflowReasoningCopy


@dataclass(frozen=True)
class DailyScoringResult:
    aggregates: FeatureAggregateSnapshot
    signals: ScoringSignals
    recommendations: WorkflowRecommendations
    reasoning_summaries: tuple[WorkflowReasoningSummary, ...] = ()
