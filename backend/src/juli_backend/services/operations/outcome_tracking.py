"""Workflow outcome tracking — P2-B5 / Issue #306."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ToolExecution
from juli_backend.repositories.repos import WorkflowOutcomeRecordsRepo
from juli_backend.services.execution.types import ExecutionStatus

logger = logging.getLogger(__name__)

VALIDATED_WORKFLOW_IDS = frozenset(
    {
        "npl",
        "minimize_violations",
        "budget_optimization",
        "product_scaling",
        "refund_spike_detection",
        "stockout_prevention",
    }
)

OUTCOME_CADENCE_IDS = ("realtime", "daily", "weekly", "monthly")

WORKFLOW_DISPLAY_NAMES: dict[str, str] = {
    "npl": "Thêm sản phẩm mới",
    "minimize_violations": "Giảm thiểu vi phạm",
    "budget_optimization": "Tối ưu ngân sách quảng cáo",
    "product_scaling": "Mở rộng sản phẩm",
    "refund_spike_detection": "Phát hiện đỉnh hoàn tiền",
    "stockout_prevention": "Phòng tránh hết hàng",
}

WORKFLOW_OUTCOME_SUCCESS_CRITERIA: dict[str, dict[str, str]] = {
    "npl": {
        "metric": "SPS change",
        "period": "7d post-publish",
        "threshold": "≥ +5 SPS points",
    },
    "minimize_violations": {
        "metric": "AHR improvement / violation count",
        "period": "7d",
        "threshold": "≥ +10 AHR points OR violation count ↓",
    },
    "budget_optimization": {
        "metric": "ROAS / revenue change",
        "period": "7d",
        "threshold": "ROAS +15% OR revenue +10%",
    },
    "product_scaling": {
        "metric": "Revenue per scaled SKU",
        "period": "14d",
        "threshold": "≥ +20% revenue for scaled products",
    },
    "refund_spike_detection": {
        "metric": "Refund rate reduction",
        "period": "7d",
        "threshold": "Refund rate returns to baseline",
    },
    "stockout_prevention": {
        "metric": "Stockouts avoided",
        "period": "30d",
        "threshold": "0 unplanned stockouts",
    },
}

CADENCE_LABELS: dict[str, dict[str, str]] = {
    "realtime": {
        "title": "Thực thi thời gian thực",
        "description": "Trạng thái thực thi ngay sau phê duyệt",
    },
    "daily": {
        "title": "Sơ bộ hàng ngày",
        "description": "Đánh giá sơ bộ sau 24 giờ",
    },
    "weekly": {
        "title": "Đánh giá đầy đủ tuần",
        "description": "Đối chiếu tiêu chí thành công theo chu kỳ",
    },
    "monthly": {
        "title": "Tổng hợp tháng",
        "description": "Tổng hợp xu hướng và kết quả tích lũy",
    },
}


@dataclass(frozen=True)
class WorkflowOutcomeRecordResult:
    record_id: uuid.UUID
    approval_id: str
    workflow_id: str
    is_duplicate: bool


def is_validated_workflow_id(workflow_id: str) -> bool:
    return workflow_id in VALIDATED_WORKFLOW_IDS


def _realtime_execution_status(
    execution_status: ExecutionStatus,
    *,
    error_message: str | None,
) -> str:
    if execution_status == ExecutionStatus.SUCCEEDED:
        return "Tool execution completed successfully"
    if error_message:
        return f"Tool execution failed: {error_message}"
    return "Tool execution failed"


def _realtime_reading_status(execution_status: ExecutionStatus) -> str:
    if execution_status == ExecutionStatus.SUCCEEDED:
        return "preliminary"
    return "needs_attention"


def build_workflow_outcome_metrics(
    *,
    workflow_id: str,
    execution_status: ExecutionStatus,
    executed_at: datetime,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Build the stable workflow_outcome_metrics envelope (ADR-013)."""
    if not is_validated_workflow_id(workflow_id):
        raise ValueError(f"Unknown workflow_id: {workflow_id}")

    success_criteria = WORKFLOW_OUTCOME_SUCCESS_CRITERIA[workflow_id]
    realtime_status = _realtime_execution_status(
        execution_status,
        error_message=error_message,
    )
    realtime_reading_status = _realtime_reading_status(execution_status)

    cadences: list[dict[str, Any]] = [
        {
            "cadence": "realtime",
            **CADENCE_LABELS["realtime"],
            "execution_status": realtime_status,
            "readings": [
                {
                    "label": success_criteria["metric"],
                    "value": "—" if execution_status == ExecutionStatus.SUCCEEDED else "n/a",
                    "status": realtime_reading_status,
                }
            ],
        }
    ]
    for cadence_id in ("daily", "weekly", "monthly"):
        cadences.append(
            {
                "cadence": cadence_id,
                **CADENCE_LABELS[cadence_id],
                "readings": [
                    {
                        "label": success_criteria["metric"],
                        "value": "pending",
                        "status": "preliminary",
                    }
                ],
            }
        )

    return {
        "workflow_id": workflow_id,
        "workflow_name": WORKFLOW_DISPLAY_NAMES[workflow_id],
        "executed_at": executed_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        "success_criteria": success_criteria,
        "cadences": cadences,
    }


def extract_workflow_id(payload: dict[str, Any]) -> str:
    workflow_id = payload.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        raise ValueError("execution payload must include workflow_id")
    if not is_validated_workflow_id(workflow_id):
        raise ValueError(f"Unknown workflow_id: {workflow_id}")
    return workflow_id


async def record_workflow_outcome(
    session: AsyncSession,
    execution: ToolExecution,
    *,
    execution_status: ExecutionStatus,
    error_message: str | None = None,
) -> WorkflowOutcomeRecordResult:
    """Persist workflow outcome metrics after terminal tool execution (idempotent)."""
    payload = json.loads(execution.payload_json or "{}")
    workflow_id = extract_workflow_id(payload)
    executed_at = datetime.now(UTC)
    metrics = build_workflow_outcome_metrics(
        workflow_id=workflow_id,
        execution_status=execution_status,
        executed_at=executed_at,
        error_message=error_message,
    )

    repo = WorkflowOutcomeRecordsRepo(session)
    existing = await repo.get_by_execution_id(execution.shop_id, execution.id)
    if existing is not None:
        return WorkflowOutcomeRecordResult(
            record_id=existing.id,
            approval_id=existing.approval_id,
            workflow_id=existing.workflow_id,
            is_duplicate=True,
        )

    record = await repo.create(
        shop_id=execution.shop_id,
        approval_id=execution.approval_id,
        execution_id=execution.id,
        workflow_id=workflow_id,
        execution_status=execution_status.value,
        metrics_json=json.dumps(metrics),
        executed_at=executed_at,
    )
    logger.info(
        "workflow_outcome_recorded",
        extra={
            "shop_id": str(execution.shop_id),
            "approval_id": execution.approval_id,
            "execution_id": str(execution.id),
            "workflow_id": workflow_id,
            "execution_status": execution_status.value,
        },
    )
    return WorkflowOutcomeRecordResult(
        record_id=record.id,
        approval_id=record.approval_id,
        workflow_id=record.workflow_id,
        is_duplicate=False,
    )


async def load_workflow_outcome_metrics(
    session: AsyncSession,
    shop_id: uuid.UUID,
    approval_id: str,
) -> dict[str, Any]:
    """Load persisted workflow_outcome_metrics envelope for internal validation."""
    record = await WorkflowOutcomeRecordsRepo(session).get_by_approval_id(
        shop_id,
        approval_id,
    )
    return json.loads(record.metrics_json)
