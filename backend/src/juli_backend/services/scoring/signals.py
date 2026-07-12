"""Rules-based visual_layer advisory signals from feature aggregates (#303).

Phase 2: T3 policy rules + deterministic proxies (ml_layer.md). KPIs without ETL
fields emit ``unavailable`` per visual_layer.md CSAT pattern.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from juli_backend.models.models import Product
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

_SHOP_STATUS_ACTION = "investigate fulfillment/cancellation/CS"
_RETURN_ACTION = "review return drivers by SKU"


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
    change = f"SPS {current:.1f}/{threshold:.1f} (thiếu {gap:.1f} điểm)"
    if gap <= 0:
        return _make_signal(
            "sps",
            technique="T3",
            change_text=change,
            signal_type="opportunity",
            action_hint="maintain fulfillment quality",
            severity="healthy",
        )
    return _make_signal(
        "sps",
        technique="T3",
        change_text=change,
        signal_type="risk",
        action_hint="performance deteriorating · " + _SHOP_STATUS_ACTION,
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
            action_hint="account health stable",
            severity="healthy",
        )
    return _make_signal(
        "ahr",
        technique="T3",
        change_text=change,
        signal_type="risk",
        action_hint="account health weakening · " + _SHOP_STATUS_ACTION,
        severity=_severity_from_gap(current, threshold),
    )


def _compute_violation_points(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.vp_score is None:
        return _unavailable_kpi("violation_points", reason="VP chưa xác minh qua Partner API")

    vp = snapshot.vp_score
    change = f"VP {vp:.0f} điểm vi phạm"
    if vp >= 5:
        return _make_signal(
            "violation_points",
            technique="T3",
            change_text=change,
            signal_type="risk",
            action_hint="penalties / reduced visibility · " + _SHOP_STATUS_ACTION,
            severity="critical",
        )
    if vp >= 2:
        return _make_signal(
            "violation_points",
            technique="T3",
            change_text=change,
            signal_type="risk",
            action_hint="monitor violation trend · " + _SHOP_STATUS_ACTION,
            severity="warning",
        )
    return _make_signal(
        "violation_points",
        technique="T3",
        change_text=change,
        signal_type="opportunity",
        action_hint="violations within policy band",
        severity="healthy",
    )


def _compute_net_revenue(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.order_count == 0:
        return _unavailable_kpi("net_revenue")

    revenue = float(snapshot.total_order_value)
    change = f"Net Revenue {revenue:,.0f} VND ({snapshot.order_count} đơn)"
    return _make_signal(
        "net_revenue",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity" if revenue > 0 else "risk",
        action_hint="growth from synced order totals",
        severity="healthy" if revenue > 0 else "warning",
    )


def _compute_aov(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    if snapshot.order_count == 0:
        return _unavailable_kpi("aov")

    aov = float(snapshot.total_order_value / Decimal(snapshot.order_count))
    change = f"AOV {aov:,.0f} VND/đơn"
    return _make_signal(
        "aov",
        technique="rules_proxy",
        change_text=change,
        signal_type="opportunity",
        action_hint="higher spend per order · scale hero products",
        severity="healthy",
    )


def _compute_revenue_by_sku(products: list[Product]) -> AdvisorySignal:
    if not products:
        return _unavailable_kpi("revenue_by_sku")

    top = max(products, key=lambda p: float(p.revenue or 0))
    revenue = float(top.revenue or 0)
    change = f"{top.name} dẫn đầu doanh thu {revenue:,.0f} VND"
    return _make_signal(
        "revenue_by_sku",
        technique="T7",
        change_text=change,
        signal_type="opportunity",
        action_hint="scale winners",
        severity="warning" if revenue >= 500_000 else "healthy",
    )


def _compute_return_request_rate(snapshot: FeatureAggregateSnapshot) -> AdvisorySignal:
    rate = snapshot.return_rate_proxy
    if rate is None or snapshot.order_count == 0:
        return _unavailable_kpi("return_request_rate")

    pct = rate * 100
    change = f"Return rate {pct:.1f}% ({snapshot.return_count}/{snapshot.order_count} đơn)"
    if rate > RETURN_RATE_RISK_THRESHOLD:
        return _make_signal(
            "return_request_rate",
            technique="rules_proxy",
            change_text=change,
            signal_type="risk",
            action_hint=f"returns elevated · {_RETURN_ACTION}",
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
        action_hint="return rate stable",
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
        "conversion_rate_by_category": _unavailable_kpi("conversion_rate_by_category"),
        "repeat_purchase_rate": _unavailable_kpi("repeat_purchase_rate"),
        "roas": _unavailable_kpi("roas", reason="Ads API chưa đồng bộ Phase 2"),
        "cac": _unavailable_kpi("cac", reason="Ads API chưa đồng bộ Phase 2"),
        "ctr": _unavailable_kpi("ctr", reason="Ads API chưa đồng bộ Phase 2"),
        "inventory_turnover": _unavailable_kpi("inventory_turnover"),
        "dsi": _unavailable_kpi("dsi"),
        "stockout_rate": _unavailable_kpi("stockout_rate"),
        "fulfillment_accuracy_rate": _unavailable_kpi("fulfillment_accuracy_rate"),
        "orders_at_sla_risk": _unavailable_kpi("orders_at_sla_risk"),
        "seller_fault_cancellation_rate": _unavailable_kpi(
            "seller_fault_cancellation_rate"
        ),
        "csat": _unavailable_kpi("csat", reason="CSAT deferred Phase 3 — no text source"),
        "after_sales_handling_time": _unavailable_kpi("after_sales_handling_time"),
    }

    return ScoringSignals(
        shop_id=snapshot.shop_id,
        computed_at=computed_at,
        health_data_source=snapshot.health_data_source,
        kpis=kpis,
    )
