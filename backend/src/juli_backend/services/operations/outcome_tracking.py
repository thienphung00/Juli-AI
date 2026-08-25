"""Workflow outcome tracking — P2-B5 / Issue #306."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, ToolExecution
from juli_backend.repositories.repos import WorkflowOutcomeRecordsRepo
from juli_backend.services.operations.impact_honesty import list_impact_readings_honest

logger = logging.getLogger(__name__)

TERMINAL_SUCCEEDED = "succeeded"
TERMINAL_FAILED = "failed"

VALIDATED_WORKFLOW_IDS = frozenset(
    {
        "npl",
        "minimize_violations",
        "budget_optimization",
        "product_scaling",
        "refund_spike_detection",
        "stockout_prevention",
        # ADR-077 decision 5 / d.1 (#1044): closes the vocabulary gap for the
        # Optimize Product agent workflow. Named "_2" deliberately: an earlier
        # attempt used "optimize_product", which is the *prompt directory*
        # name (services/execution/tool_routing.py,
        # services/scoring/kpi_catalog.py), not this workflow key.
        "optimize_product_2",
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
    "optimize_product_2": "Tối ưu sản phẩm",
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
    # ADR-077 decision 5 / d.1 (#1044): the real success measure for this
    # workflow is the control-adjusted incremental impact computed by the
    # daily impact-reader beat task and stored in `impact_readings` — see
    # `_fill_cadences_from_impact_readings` below, which fills the `weekly`
    # cadence slot from a `preliminary` reading and `monthly` from a `final`
    # one once each lands.
    "optimize_product_2": {
        "metric": "Incremental impact (ADR-077 funnel metric(s) touched)",
        "period": "7d preliminary / 14d final",
        "threshold": "positive control-adjusted incremental vs. expected (see impact_readings)",
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
    execution_status: str,
    *,
    error_message: str | None,
) -> str:
    if execution_status == TERMINAL_SUCCEEDED:
        return "Tool execution completed successfully"
    if error_message:
        return f"Tool execution failed: {error_message}"
    return "Tool execution failed"


def _realtime_reading_status(execution_status: str) -> str:
    if execution_status == TERMINAL_SUCCEEDED:
        return "preliminary"
    return "needs_attention"


def build_workflow_outcome_metrics(
    *,
    workflow_id: str,
    execution_status: str,
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
                    "value": "—" if execution_status == TERMINAL_SUCCEEDED else "n/a",
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
    execution_status: str,
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
        execution_status=execution_status,
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
            "execution_status": execution_status,
        },
    )
    return WorkflowOutcomeRecordResult(
        record_id=record.id,
        approval_id=record.approval_id,
        workflow_id=record.workflow_id,
        is_duplicate=False,
    )


#: ADR-077 decision 5: preliminary readings fill the legacy `weekly` cadence
#: slot, final readings fill `monthly`. `realtime` keeps its existing
#: execution-status meaning (never repurposed here) and `daily` is likewise
#: untouched — neither participates in this fill.
_IMPACT_KIND_TO_CADENCE: dict[str, str] = {"preliminary": "weekly", "final": "monthly"}


def _format_impact_reading_value(reading: ImpactReading) -> str:
    """Never fabricate a number: a suppressed/confounded reading (or one
    with no computed incremental) renders as ``"n/a"``, not a placeholder
    zero or the raw ``None``."""
    if reading.confidence in ("suppressed", "confounded") or reading.incremental is None:
        return "n/a"
    return str(reading.incremental)


async def _fill_cadences_from_impact_readings(
    session: AsyncSession,
    cadences: list[dict[str, Any]],
    tool_execution_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """ADR-077 decision 5: the legacy envelope stays display-compatible by
    reading straight from ``impact_readings`` at serve time rather than
    re-persisting derived values onto ``metrics_json`` — the table is the
    single source of truth the daily impact-reader beat task (#1044) writes
    to, so a cadence with no matching reading yet is left exactly as
    ``build_workflow_outcome_metrics`` built it (the "pending" placeholder).

    ADR-085 decision 8 (#1338): this surface uses the honesty rule —
    only real confidence tiers (cao/trung_binh/thap) are counted as readings.
    Suppressed and confounded rows are never shown here (gate-closing query
    returns zero when only suppressed present). For audit views showing
    suppressed/confounded, those must be labelled as their own outcome.

    A run can classify multiple mutation kinds (price + image + title +
    description, say), each with its own metric — so one ``kind`` can have
    several ``impact_readings`` rows. This lists every one of them rather
    than picking a single "the" rollup row: ``impact_readings`` has no
    column marking one row as the run-level rollup (that distinction is
    computed transiently by ``workers/impact_reader/classify.
    rollup_metric_for`` at write time, not persisted), so showing the full
    per-metric breakdown here is the honest option that never guesses.
    """
    # Use the honest read model — exclude suppressed/confounded
    honest_rows = await list_impact_readings_honest(session, tool_execution_id)
    if not honest_rows:
        return cadences

    by_kind: dict[str, list[ImpactReading]] = {}
    for row in honest_rows:
        by_kind.setdefault(row.kind, []).append(row)

    filled: list[dict[str, Any]] = []
    for cadence in cadences:
        cadence_id = cadence.get("cadence")
        target_kind = next(
            (kind for kind, cid in _IMPACT_KIND_TO_CADENCE.items() if cid == cadence_id),
            None,
        )
        readings_for_kind = by_kind.get(target_kind) if target_kind is not None else None
        if not readings_for_kind:
            filled.append(cadence)
            continue
        filled.append(
            {
                **cadence,
                "readings": [
                    {
                        "label": row.metric,
                        "value": _format_impact_reading_value(row),
                        "status": row.confidence,
                    }
                    for row in sorted(readings_for_kind, key=lambda r: r.metric)
                ],
            }
        )
    return filled


async def load_workflow_outcome_metrics(
    session: AsyncSession,
    shop_id: uuid.UUID,
    approval_id: str,
) -> dict[str, Any]:
    """Load persisted workflow_outcome_metrics envelope for internal validation.

    ADR-077 decision 5: the ``weekly``/``monthly`` cadences are filled from
    ``impact_readings`` at read time (see
    :func:`_fill_cadences_from_impact_readings`); ``realtime`` and ``daily``
    are untouched.
    """
    record = await WorkflowOutcomeRecordsRepo(session).get_by_approval_id(
        shop_id,
        approval_id,
    )
    metrics = json.loads(record.metrics_json)
    metrics["cadences"] = await _fill_cadences_from_impact_readings(
        session, metrics["cadences"], record.execution_id
    )
    return metrics
