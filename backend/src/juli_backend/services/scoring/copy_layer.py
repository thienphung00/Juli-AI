"""Rules-based copy layer — deterministic templates from advisory signals (#304).

Phase 2: rules-only ``copy_source: rules``. Cloud LLM deferred to Phase 4.

Issue #427 (P2-B2 ext): After #428 enables Ads analytics KPI signals (CTR live;
ROAS/CAC when spend denominators are present), **no additional template branches
are required**. ``why`` is assembled from linked ``AdvisorySignal.one_line``
values (visual_layer risk/opportunity text from ``signals.py``); ``next_steps``
remain static per workflow key — Ads workflows already reference ROAS/CAC.
Contract coverage: ``TestAdsKpiLinkedCopyContract`` in
``tests/unit/test_rules_copy_layer_contract.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from juli_backend.services.scoring.kpi_catalog import (
    MID_LARGE_WORKFLOW_KEYS,
    NEW_SHOP_WORKFLOW_KEYS,
)
from juli_backend.services.scoring.types import (
    AdvisorySignal,
    CopySource,
    KpiId,
    ScoringSignals,
    WorkflowReasoningCopy,
    WorkflowReasoningSummary,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

COPY_SOURCE_RULES: CopySource = "rules"

WORKFLOW_COPY_TEMPLATE_KEYS: frozenset[str] = NEW_SHOP_WORKFLOW_KEYS | MID_LARGE_WORKFLOW_KEYS


@dataclass(frozen=True)
class _CopyTemplate:
    next_steps: tuple[str, ...]


_WORKFLOW_COPY_TEMPLATES: dict[str, _CopyTemplate] = {
    "create_hero_product_1": _CopyTemplate(
        next_steps=(
            "Xác định SKU/category có tiềm năng tăng trưởng cao nhất.",
            "Chuẩn bị listing mới với mô tả và hình ảnh đạt chuẩn Seller Center.",
            "Theo dõi doanh thu sau khi đăng sản phẩm.",
        ),
    ),
    "optimize_product_2": _CopyTemplate(
        next_steps=(
            "Rà soát listing có tỷ lệ chuyển đổi thấp hoặc doanh thu giảm.",
            "Cập nhật mô tả, hình ảnh và giá theo SKU/category ưu tiên.",
            "Theo dõi AOV và doanh thu SKU sau 7 ngày.",
        ),
    ),
    "create_activity_7a": _CopyTemplate(
        next_steps=(
            "Tạo chiến dịch quảng cáo cho SKU hoặc category đang tăng trưởng.",
            "Đặt ngân sách thử nghiệm và theo dõi ROAS ban đầu.",
            "Mở rộng ngân sách khi ROAS ổn định trên mục tiêu.",
        ),
    ),
    "update_activity_7c": _CopyTemplate(
        next_steps=(
            "Rà soát chiến dịch đang chạy và điều chỉnh ngân sách/bid.",
            "Tăng ngân sách cho chiến dịch hiệu quả, giảm cho chiến dịch kém.",
            "Đánh giá lại hiệu quả sau 7 ngày vận hành.",
        ),
    ),
    "delete_activity_7b": _CopyTemplate(
        next_steps=(
            "Tạm dừng hoặc giảm ngân sách chiến dịch hiệu quả thấp.",
            "Chuyển ngân sách sang chiến dịch đạt ROAS ổn định.",
            "Theo dõi CAC và ROAS sau khi điều chỉnh.",
        ),
    ),
    "replenish_inventory_3": _CopyTemplate(
        next_steps=(
            "Ưu tiên đặt hàng bổ sung cho SKU có nguy cơ hết hàng.",
            "Điều chỉnh quảng cáo nếu tồn kho không đủ cho nhu cầu.",
            "Theo dõi mức tồn kho hàng tuần.",
        ),
    ),
    "clear_excess_4": _CopyTemplate(
        next_steps=(
            "Xác định SKU tồn kho dư hoặc DSI cao.",
            "Chạy khuyến mãi hoặc giảm giá để thanh lý tồn kho chậm luân chuyển.",
            "Theo dõi inventory turnover sau 14 ngày.",
        ),
    ),
    "process_order_5": _CopyTemplate(
        next_steps=(
            "Xử lý đơn hàng đang chờ giao trong Seller Center.",
            "Kiểm tra địa chỉ và SLA trước khi tạo gói hàng.",
            "Theo dõi tỷ lệ fulfillment accuracy sau 7 ngày.",
        ),
    ),
    "prevent_cancellation_8a": _CopyTemplate(
        next_steps=(
            "Rà soát đơn có nguy cơ hủy do lỗi seller.",
            "Liên hệ khách hàng hoặc cập nhật trạng thái kịp thời.",
            "Theo dõi seller-fault cancellation rate sau 7 ngày.",
        ),
    ),
    "prevent_return_8b": _CopyTemplate(
        next_steps=(
            "Rà soát đơn hoàn gần đây để tìm nguyên nhân lặp lại.",
            "Kiểm tra mô tả sản phẩm và chính sách đổi trả.",
            "Theo dõi tỷ lệ hoàn trong 7 ngày sau khi xử lý.",
        ),
    ),
    "prevent_refund_8c": _CopyTemplate(
        next_steps=(
            "Xử lý yêu cầu hoàn tiền đang chờ trong Seller Center.",
            "Xác minh lý do hoàn và phản hồi khách hàng kịp thời.",
            "Theo dõi tỷ lệ hoàn tiền sau khi xử lý.",
        ),
    ),
}


def _linked_signals(
    recommendation: WorkflowRecommendation,
    signals: ScoringSignals,
) -> list[AdvisorySignal]:
    linked: list[AdvisorySignal] = []
    for kpi_id in recommendation.source_kpi_ids:
        signal = signals.kpis.get(cast(KpiId, kpi_id))
        if signal is None or signal.signal_type == "unavailable":
            continue
        linked.append(signal)
    return linked


def _format_expected_impact(recommendation: WorkflowRecommendation) -> str:
    impact = recommendation.expected_impact
    return (
        f"Dự kiến cải thiện {impact.metric} với mức ưu tiên {impact.confidence} "
        f"(điểm tác động {impact.value:.0f})."
    )


def _build_why(
    recommendation: WorkflowRecommendation,
    linked: list[AdvisorySignal],
) -> str:
    if linked:
        return " ".join(signal.one_line for signal in linked)
    return recommendation.rationale


def build_workflow_reasoning_copy(
    recommendation: WorkflowRecommendation,
    signals: ScoringSignals,
) -> WorkflowReasoningCopy:
    """Render rules-only Why / Expected Impact / Next Steps for one recommendation."""
    template = _WORKFLOW_COPY_TEMPLATES[recommendation.workflow_key]
    linked = _linked_signals(recommendation, signals)

    return WorkflowReasoningCopy(
        copy_source=COPY_SOURCE_RULES,
        why=_build_why(recommendation, linked),
        expected_impact=_format_expected_impact(recommendation),
        next_steps=template.next_steps,
        source_kpi_ids=recommendation.source_kpi_ids,
    )


def build_reasoning_for_recommendations(
    recommendations: WorkflowRecommendations,
    signals: ScoringSignals,
) -> tuple[WorkflowReasoningSummary, ...]:
    """Build reasoning copy for all ranked recommendations."""
    return tuple(
        WorkflowReasoningSummary(
            workflow_key=item.workflow_key,
            copy=build_workflow_reasoning_copy(item, signals),
        )
        for item in recommendations.recommended_workflows
    )
