"""Outcome prediction helpers for host-product matching (P1-2 / issue #93)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Confidence = Literal["high", "medium", "low"]

ACTION_CONTACT_CREATOR = "contact_creator"
ACTION_ADJUST_COMMISSION = "adjust_commission"
ACTION_SCHEDULE_LIVE = "schedule_live"


@dataclass
class PredictedOutcome:
    gmv_vnd_week: dict[str, int]
    conversion_pct: float
    engagement_index: float
    risk_factors: list[str] = field(default_factory=list)


def estimate_predicted_outcome(
    *,
    match_score: float,
    product_revenue: float,
    product_units: int,
    stream_grade: float,
    viewer_count: int | None,
    order_count: int | None,
    has_graph_signal: bool,
) -> PredictedOutcome:
    """Estimate GMV band, conversion, engagement, and risks from match + signals."""
    per_unit = product_revenue / max(product_units, 1)
    weekly_units = max(1, int(7 * match_score * (1.2 if has_graph_signal else 0.85)))
    expected_weekly = per_unit * weekly_units
    low = int(expected_weekly * 0.75)
    high = int(expected_weekly * 1.25)

    if viewer_count and viewer_count > 0 and order_count is not None:
        conversion_pct = round(min(order_count / viewer_count * 100, 15.0), 2)
    else:
        conversion_pct = round(min(stream_grade / 100 * 4.5, 12.0), 2)

    engagement_index = round(
        min(0.35 + stream_grade / 100 * 0.45 + match_score * 0.2, 1.0),
        2,
    )

    risks: list[str] = []
    if not has_graph_signal:
        risks.append("low_historical_sample")
    if product_units < 20:
        risks.append("limited_sales_history")
    if stream_grade < 40:
        risks.append("weak_recent_livestream")

    return PredictedOutcome(
        gmv_vnd_week={"low": low, "high": high},
        conversion_pct=conversion_pct,
        engagement_index=engagement_index,
        risk_factors=risks,
    )


def confidence_from_score(
    match_score: float,
    has_graph_signal: bool,
) -> Confidence:
    if match_score >= 0.8 or (has_graph_signal and match_score >= 0.65):
        return "high"
    if match_score >= 0.45:
        return "medium"
    return "low"


def select_action_type(match_score: float, commission_rate: Decimal | None) -> str:
    rate = float(commission_rate or 0)
    if match_score >= 0.65:
        return ACTION_CONTACT_CREATOR
    if rate < 0.12 and match_score >= 0.4:
        return ACTION_ADJUST_COMMISSION
    return ACTION_SCHEDULE_LIVE


def build_action_cta(action_type: str, creator_name: str, product_name: str) -> str:
    if action_type == ACTION_CONTACT_CREATOR:
        return f"Nhấn để liên hệ {creator_name} về {product_name}"
    if action_type == ACTION_ADJUST_COMMISSION:
        return f"Nhấn để điều chỉnh hoa hồng cho {creator_name}"
    return f"Nhấn để lên lịch livestream với {creator_name} cho {product_name}"


def build_decision_message(
    creator_name: str,
    product_name: str,
    match_score: float,
    gmv_high: int,
) -> str:
    gmv_m = max(gmv_high // 1_000_000, 1)
    pct = int(match_score * 100)
    return (
        f"{creator_name} phù hợp nhất cho {product_name} — "
        f"dự kiến tới ~{gmv_m} triệu VND/tuần (độ phù hợp {pct}%)."
    )
