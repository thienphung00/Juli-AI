"""Rules-based visual_layer advisory signals from feature aggregates (#303).

Phase 2: T3 policy rules + deterministic proxies (ml_layer.md). KPIs without ETL
fields emit ``unavailable`` per visual_layer.md CSAT pattern.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from juli_backend.models.models import Product
from juli_backend.services.aggregates.computed_kpis import ComputedKpiMetrics
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    ShopLifecycleContext,
)
from juli_backend.services.scoring.advisory import format_advisory_one_line
from juli_backend.services.scoring.kpi_catalog import KPI_DOMAIN, KPI_WORKFLOW_KEYS
from juli_backend.services.scoring.types import (
    AdvisorySignal,
    KpiId,
    ScoringSignals,
    Severity,
    SignalType,
    TechniqueId,
)

DEFAULT_SPS_THRESHOLD = 4.0
DEFAULT_AHR_THRESHOLD = 90.0
RETURN_RATE_RISK_THRESHOLD = 0.2
INVENTORY_TURNOVER_RISK_THRESHOLD = 4.0
DSI_RISK_DAYS_THRESHOLD = 60.0
STOCKOUT_RATE_RISK_THRESHOLD = 0.05
FULFILLMENT_ACCURACY_RISK_THRESHOLD = 0.95
SELLER_FAULT_CANCEL_RISK_THRESHOLD = 0.03
AFTER_SALES_HANDLING_RISK_HOURS = 20.0
CSAT_RISK_THRESHOLD = 70.0
# Product CTR rules_proxy: below 1.5% = weak creative; at/above 2.5% = scale winners.
CTR_RISK_THRESHOLD = 0.015
CTR_HEALTHY_THRESHOLD = 0.025

_PROMOTION_UNAVAILABLE_REASON = "Chờ đồng bộ Promotion API"
_ANALYTICS_CTR_UNAVAILABLE_REASON = "Chưa đồng bộ Analytics product CTR"
_PROMOTION_SPEND_UNAVAILABLE_REASON = "Chờ đồng bộ chi phí Promotion (spend)"
_NO_ORDERS_IN_WINDOW_REASON = "Chưa có đơn hàng trong 30 ngày"

_SHOP_STATUS_ACTION = "kiểm tra giao hàng, đơn hủy và chăm sóc khách"
_RETURN_ACTION = "xem lý do trả hàng theo từng SKU"


def _vn_number(value: float, decimals: int = 0) -> str:
    """vi-VN digits: ``.`` groups thousands, ``,`` is the decimal mark."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _vnd(value: float) -> str:
    return f"{_vn_number(value)} ₫"


def _pct(rate_pct: float) -> str:
    return f"{_vn_number(rate_pct, 1)}%"


def _severity_from_gap(current: float, threshold: float) -> Severity:
    if current >= threshold:
        return "healthy"
    gap_ratio = (threshold - current) / threshold if threshold > 0 else 1.0
    return "critical" if gap_ratio > 0.15 else "warning"


def _make_signal(
    kpi_id: KpiId,
    *,
    technique: TechniqueId,
    change_text: str,
    signal_type: SignalType,
    action_hint: str,
    severity: Severity,
) -> AdvisorySignal:
    workflow_keys = KPI_WORKFLOW_KEYS[kpi_id]
    return AdvisorySignal(
        kpi_id=kpi_id,
        domain=KPI_DOMAIN[kpi_id],
        technique=technique,
        change_text=change_text,
        signal_type=signal_type,
        action_hint=action_hint,
        one_line=format_advisory_one_line(change_text, signal_type, action_hint),
        workflow_keys=workflow_keys,
        severity=severity,
    )


def _unavailable_kpi(kpi_id: KpiId, *, reason: str = "Chờ đồng bộ ETL") -> AdvisorySignal:
    return _make_signal(
        kpi_id,
        technique="unavailable",
        change_text="Không có dữ liệu",
        signal_type="unavailable",
        action_hint=reason,
        severity="not_applicable",
    )


def _compute_sps(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.sps_score is None:
        return _unavailable_kpi("sps", reason="SPS chưa xác minh qua Partner API")

    current = snapshot.sps_score
    threshold = DEFAULT_SPS_THRESHOLD
    gap = max(0.0, threshold - current)
    change = (
        f"SPS {_vn_number(current, 1)}/{_vn_number(threshold, 1)} (thiếu {_vn_number(gap, 1)} điểm)"
    )
    if gap <= 0:
        return _make_signal(
            "sps",
            technique="T3",
            change_text=change,
            signal_type="opportunity",
            action_hint="giữ chất lượng giao hàng",
            severity="healthy",
        )
    return _make_signal(
        "sps",
        technique="T3",
        change_text=change,
        signal_type="risk",
        action_hint="hiệu suất shop đang giảm · " + _SHOP_STATUS_ACTION,
        severity=_severity_from_gap(current, threshold),
    )


def _compute_ahr(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.ahr_score is None:
        return _unavailable_kpi("ahr", reason="AHR chưa xác minh qua Partner API")

    current = snapshot.ahr_score
    threshold = DEFAULT_AHR_THRESHOLD
    gap = max(0.0, threshold - current)
    change = f"AHR {current:.0f}%→{threshold:.0f}% (thiếu {gap:.0f} điểm)"
    if gap <= 0:
        return _make_signal(
            "ahr",
            technique="T3",
            change_text=change,
            signal_type="opportunity",
            action_hint="sức khỏe tài khoản ổn định",
            severity="healthy",
        )
    return _make_signal(
        "ahr",
        technique="T3",
        change_text=change,
        signal_type="risk",
        action_hint="sức khỏe tài khoản đang yếu đi · " + _SHOP_STATUS_ACTION,
        severity=_severity_from_gap(current, threshold),
    )


def _compute_violation_points(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.vp_score is None:
        return _unavailable_kpi("violation_points", reason="VP chưa xác minh qua Partner API")

    vp = snapshot.vp_score
    change = f"{_vn_number(vp)} điểm vi phạm"
    if vp >= 5:
        return _make_signal(
            "violation_points",
            technique="T3",
            change_text=change,
            signal_type="risk",
            action_hint="có thể bị phạt hoặc giảm hiển thị · " + _SHOP_STATUS_ACTION,
            severity="critical",
        )
    if vp >= 2:
        return _make_signal(
            "violation_points",
            technique="T3",
            change_text=change,
            signal_type="risk",
            action_hint="theo dõi điểm vi phạm · " + _SHOP_STATUS_ACTION,
            severity="warning",
        )
    return _make_signal(
        "violation_points",
        technique="T3",
        change_text=change,
        signal_type="opportunity",
        action_hint="điểm vi phạm trong mức cho phép",
        severity="healthy",
    )


def _compute_net_revenue(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.order_count == 0:
        return _unavailable_kpi("net_revenue")

    revenue = float(snapshot.total_order_value)
    change = f"Doanh thu {_vnd(revenue)} ({_vn_number(snapshot.order_count)} đơn)"
    return _make_signal(
        "net_revenue",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity" if revenue > 0 else "risk",
        action_hint="tính từ đơn hàng đã đồng bộ",
        severity="healthy" if revenue > 0 else "warning",
    )


def _compute_aov(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.order_count == 0:
        return _unavailable_kpi("aov")

    aov = float(snapshot.total_order_value / Decimal(snapshot.order_count))
    change = f"Giá trị đơn trung bình {_vnd(aov)}/đơn"
    return _make_signal(
        "aov",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tăng giá trị mỗi đơn · đẩy mạnh sản phẩm chủ lực",
        severity="healthy",
    )


def _compute_revenue_by_sku(products: list[Product]) -> AdvisorySignal:
    if not products:
        return _unavailable_kpi("revenue_by_sku")

    top = max(products, key=lambda p: float(p.revenue or 0))
    revenue = float(top.revenue or 0)
    change = f"{top.name} dẫn đầu doanh thu {_vnd(revenue)}"
    return _make_signal(
        "revenue_by_sku",
        technique="T7",
        change_text=change,
        signal_type="opportunity",
        action_hint="đẩy mạnh sản phẩm bán tốt",
        severity="warning" if revenue >= 500_000 else "healthy",
    )


def _compute_return_request_rate(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    rate = snapshot.return_rate_proxy
    if rate is None or snapshot.order_count == 0:
        return _unavailable_kpi("return_request_rate")

    pct = rate * 100
    change = (
        f"Tỷ lệ trả hàng {_pct(pct)} "
        f"({_vn_number(snapshot.return_count)}/{_vn_number(snapshot.order_count)} đơn)"
    )
    if rate > RETURN_RATE_RISK_THRESHOLD:
        return _make_signal(
            "return_request_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint=f"trả hàng đang cao · {_RETURN_ACTION}",
            severity="critical",
        )
    if rate > 0:
        return _make_signal(
            "return_request_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint=_RETURN_ACTION,
            severity="warning",
        )
    return _make_signal(
        "return_request_rate",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tỷ lệ trả hàng ổn định",
        severity="healthy",
    )


def _computed(snapshot: FeatureAggregateSnapshot) -> ComputedKpiMetrics | None:
    return snapshot.computed_kpis


def _compute_inventory_turnover(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.inventory_turnover is None:
        return _unavailable_kpi("inventory_turnover", reason="Chưa đồng bộ tồn kho")

    turnover = metrics.inventory_turnover
    change = f"Vòng quay tồn kho {_vn_number(turnover, 1)} lần (30 ngày)"
    if turnover < INVENTORY_TURNOVER_RISK_THRESHOLD:
        return _make_signal(
            "inventory_turnover",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="vốn đọng trong tồn kho · xả hàng tồn hoặc nhập lại cho hợp lý",
            severity="warning",
        )
    return _make_signal(
        "inventory_turnover",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tồn kho luân chuyển tốt",
        severity="healthy",
    )


def _compute_dsi(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.dsi_days is None:
        return _unavailable_kpi("dsi", reason="Chưa đồng bộ tồn kho")

    dsi = metrics.dsi_days
    change = f"Số ngày tồn kho {_vn_number(dsi)} ngày"
    if dsi > DSI_RISK_DAYS_THRESHOLD:
        return _make_signal(
            "dsi",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="hàng tồn lâu · xả bớt hàng tồn",
            severity="warning",
        )
    return _make_signal(
        "dsi",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="số ngày tồn kho trong mức ổn",
        severity="healthy",
    )


def _compute_stockout_rate(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.stockout_rate is None:
        return _unavailable_kpi("stockout_rate", reason="Chưa đồng bộ tồn kho")

    rate = metrics.stockout_rate
    pct = rate * 100
    change = (
        f"Tỷ lệ hết hàng {_pct(pct)} "
        f"({_vn_number(metrics.stockout_sku_count)}/"
        f"{_vn_number(metrics.sku_count_with_inventory)} SKU)"
    )
    if rate > STOCKOUT_RATE_RISK_THRESHOLD:
        return _make_signal(
            "stockout_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="có thể mất đơn · nhập thêm hàng",
            severity="critical",
        )
    return _make_signal(
        "stockout_rate",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tỷ lệ hết hàng thấp",
        severity="healthy",
    )


def _compute_fulfillment_accuracy_rate(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.fulfillment_accuracy_rate is None:
        return _unavailable_kpi("fulfillment_accuracy_rate")

    rate = metrics.fulfillment_accuracy_rate
    pct = rate * 100
    change = (
        f"Giao đúng {_pct(pct)} "
        f"({_vn_number(metrics.orders_fulfilled_without_seller_fault_30d)}/"
        f"{_vn_number(metrics.orders_with_ship_time_30d)} đơn)"
    )
    if rate < FULFILLMENT_ACCURACY_RISK_THRESHOLD:
        return _make_signal(
            "fulfillment_accuracy_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="lỗi giao hàng tăng · xử lý đơn sớm",
            severity="warning",
        )
    return _make_signal(
        "fulfillment_accuracy_rate",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="giao hàng ổn định",
        severity="healthy",
    )


def _compute_orders_at_sla_risk(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    """At-SLA-risk order count, or ``unavailable`` when no order was evaluated (#1960).

    Every other computed KPI reaches ``unavailable`` because its own 30-day denominator
    was empty — ``compute_fulfillment_accuracy_rate`` returns None on
    ``orders_with_ship_time_30d <= 0``, ``compute_seller_fault_cancellation_rate`` and
    ``compute_csat_proxy`` on ``order_count_30d <= 0``. This KPI is keyed on a **count**,
    which has no None state to carry that same emptiness, so the denominator is read
    directly: zero orders in the window means nothing was measured, which is not the
    same statement as "no orders are past their dispatch SLA".
    """
    metrics = _computed(snapshot)
    if metrics is None:
        return _unavailable_kpi("orders_at_sla_risk")
    if metrics.order_count_30d == 0:
        return _unavailable_kpi("orders_at_sla_risk", reason=_NO_ORDERS_IN_WINDOW_REASON)

    count = metrics.orders_at_sla_risk_count
    change = f"{_vn_number(count)} đơn sắp trễ hạn giao"
    if count > 0:
        return _make_signal(
            "orders_at_sla_risk",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="có thể bị phạt giao trễ · xử lý đơn ngay",
            severity="critical" if count >= 10 else "warning",
        )
    return _make_signal(
        "orders_at_sla_risk",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="không có đơn nào trễ hạn giao",
        severity="healthy",
    )


def _compute_seller_fault_cancellation_rate(
    snapshot: FeatureAggregateSnapshot,
) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.seller_fault_cancellation_rate is None:
        return _unavailable_kpi("seller_fault_cancellation_rate")

    rate = metrics.seller_fault_cancellation_rate
    pct = rate * 100
    change = f"Đơn hủy do shop {_pct(pct)} ({_vn_number(metrics.seller_fault_order_count_30d)} đơn)"
    if rate > SELLER_FAULT_CANCEL_RISK_THRESHOLD:
        return _make_signal(
            "seller_fault_cancellation_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="có thể làm giảm điểm SPS · hạn chế hủy đơn",
            severity="critical",
        )
    if rate > 0:
        return _make_signal(
            "seller_fault_cancellation_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="theo dõi đơn hủy do shop",
            severity="warning",
        )
    return _make_signal(
        "seller_fault_cancellation_rate",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="đơn hủy do shop ở mức thấp",
        severity="healthy",
    )


def _compute_conversion_rate_by_category(
    snapshot: FeatureAggregateSnapshot,
) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.conversion_rate_by_category is None:
        return _unavailable_kpi("conversion_rate_by_category")

    pct = metrics.conversion_rate_by_category * 100
    category = metrics.top_category_name or "Danh mục bán chạy nhất"
    change = f"{category} chiếm {_pct(pct)} sản phẩm đã bán"
    return _make_signal(
        "conversion_rate_by_category",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tối ưu trang sản phẩm trong danh mục này",
        severity="healthy",
    )


def _compute_repeat_purchase_rate(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.repeat_purchase_rate is None:
        return _unavailable_kpi("repeat_purchase_rate")

    rate = metrics.repeat_purchase_rate
    pct = rate * 100
    change = (
        f"Khách mua lại {_pct(pct)} "
        f"({_vn_number(metrics.repeat_buyers_30d)}/{_vn_number(metrics.unique_buyers_30d)} khách)"
    )
    return _make_signal(
        "repeat_purchase_rate",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="khách quay lại · đẩy mạnh sản phẩm chủ lực",
        severity="healthy" if rate >= 0.15 else "warning",
    )


def _compute_after_sales_handling_time(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.after_sales_handling_time_hours is None:
        return _unavailable_kpi("after_sales_handling_time")

    hours = metrics.after_sales_handling_time_hours
    change = f"Xử lý sau bán trung vị {_vn_number(hours)} giờ"
    if hours > AFTER_SALES_HANDLING_RISK_HOURS:
        return _make_signal(
            "after_sales_handling_time",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="khách có thể không hài lòng · hạn chế trả hàng",
            severity="warning",
        )
    return _make_signal(
        "after_sales_handling_time",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="xử lý sau bán đúng hạn",
        severity="healthy",
    )


def _compute_csat(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.csat_proxy_score is None:
        return _unavailable_kpi("csat", reason="Chưa đủ dữ liệu đơn/return 30d")

    score = metrics.csat_proxy_score
    change = f"Mức hài lòng ước tính {_vn_number(score)}/100 (theo tỷ lệ trả hàng)"
    if score < CSAT_RISK_THRESHOLD:
        return _make_signal(
            "csat",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="mức hài lòng thấp · xem lý do trả hàng",
            severity="warning",
        )
    return _make_signal(
        "csat",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="mức hài lòng ổn định",
        severity="healthy",
    )


def _compute_ctr(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or metrics.analytics_weighted_product_ctr is None:
        return _unavailable_kpi("ctr", reason=_ANALYTICS_CTR_UNAVAILABLE_REASON)

    ctr = metrics.analytics_weighted_product_ctr
    pct = ctr * 100
    change = f"CTR {_pct(pct)} (trung bình các sản phẩm)"
    if ctr < CTR_RISK_THRESHOLD:
        return _make_signal(
            "ctr",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="ít người bấm vào sản phẩm · làm mới ảnh và tiêu đề",
            severity="warning",
        )
    if ctr >= CTR_HEALTHY_THRESHOLD:
        return _make_signal(
            "ctr",
            technique="rules_proxy",
            change_text=change,
            signal_type="opportunity",
            action_hint="đẩy mạnh sản phẩm bán tốt · tăng ngân sách cho SKU dẫn đầu",
            severity="healthy",
        )
    return _make_signal(
        "ctr",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="CTR ở mức trung bình · thử ảnh và tiêu đề mới cho SKU đang tăng",
        severity="warning",
    )


def _compute_roas(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or not metrics.promotion_activity_partition_present:
        return _unavailable_kpi("roas", reason=_PROMOTION_UNAVAILABLE_REASON)
    if metrics.analytics_spend_denominator is None:
        return _unavailable_kpi("roas", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)
    if metrics.analytics_revenue_denominator is None:
        return _unavailable_kpi("roas", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)

    spend = float(metrics.analytics_spend_denominator)
    if spend <= 0:
        return _unavailable_kpi("roas", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)

    revenue = float(metrics.analytics_revenue_denominator)
    roas = revenue / spend
    change = f"ROAS {_vn_number(roas, 1)} lần (GMV/chi phí quảng cáo 30 ngày)"
    if roas < 2.0:
        return _make_signal(
            "roas",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="quảng cáo kém hiệu quả · tạm dừng hoặc phân bổ lại ngân sách",
            severity="warning",
        )
    return _make_signal(
        "roas",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="tăng ngân sách cho chiến dịch có lãi",
        severity="healthy",
    )


def _compute_cac(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    metrics = _computed(snapshot)
    if metrics is None or not metrics.promotion_activity_partition_present:
        return _unavailable_kpi("cac", reason=_PROMOTION_UNAVAILABLE_REASON)
    if metrics.analytics_spend_denominator is None:
        return _unavailable_kpi("cac", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)

    spend = float(metrics.analytics_spend_denominator)
    if spend <= 0:
        return _unavailable_kpi("cac", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)

    buyers = metrics.unique_buyers_30d
    if buyers <= 0:
        return _unavailable_kpi("cac", reason=_PROMOTION_SPEND_UNAVAILABLE_REASON)

    cac = spend / buyers
    change = f"Chi phí mỗi khách {_vnd(cac)} (chi phí quảng cáo/khách 30 ngày)"
    if cac > 500_000:
        return _make_signal(
            "cac",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint="chi phí có khách đang cao · cắt chiến dịch ROAS thấp",
            severity="warning",
        )
    return _make_signal(
        "cac",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="chi phí có khách ổn định",
        severity="healthy",
    )


def compute_scoring_signals(
    snapshot: FeatureAggregateSnapshot,
    *,
    lifecycle: ShopLifecycleContext | None = None,
    computed_at: datetime,
    products: list[Product],
) -> ScoringSignals:
    """Emit visual_layer KPI advisory signals from synced aggregate inputs."""
    del lifecycle  # reserved for probation-aware KPIs when persisted on Shop rows

    kpis: dict[KpiId, AdvisorySignal] = {
        "sps": _compute_sps(snapshot),
        "ahr": _compute_ahr(snapshot),
        "violation_points": _compute_violation_points(snapshot),
        "net_revenue": _compute_net_revenue(snapshot),
        "aov": _compute_aov(snapshot),
        "revenue_by_sku": _compute_revenue_by_sku(products),
        "return_request_rate": _compute_return_request_rate(snapshot),
        "conversion_rate_by_category": _compute_conversion_rate_by_category(snapshot),
        "repeat_purchase_rate": _compute_repeat_purchase_rate(snapshot),
        "roas": _compute_roas(snapshot),
        "cac": _compute_cac(snapshot),
        "ctr": _compute_ctr(snapshot),
        "inventory_turnover": _compute_inventory_turnover(snapshot),
        "dsi": _compute_dsi(snapshot),
        "stockout_rate": _compute_stockout_rate(snapshot),
        "fulfillment_accuracy_rate": _compute_fulfillment_accuracy_rate(snapshot),
        "orders_at_sla_risk": _compute_orders_at_sla_risk(snapshot),
        "seller_fault_cancellation_rate": _compute_seller_fault_cancellation_rate(snapshot),
        "csat": _compute_csat(snapshot),
        "after_sales_handling_time": _compute_after_sales_handling_time(snapshot),
    }

    return ScoringSignals(
        shop_id=snapshot.shop_id,
        computed_at=computed_at,
        health_data_source=snapshot.health_data_source,
        kpis=kpis,
    )
