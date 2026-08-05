"""Product trend classifier for month-over-month analysis — Issue #722.

Classifies products into three tiers based on sales trends:
- strong_positive: Order count growing 1.5x or more month-over-month
- declining: Order count declining to 60% or less of previous period
- no_strong_signal: Stable or unclear trend (between 0.6x and 1.5x)
- insufficient_data: Not enough historical data (< 10 orders in 30 days)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Order

TrendTier = Literal["strong_positive", "declining", "no_strong_signal", "insufficient_data"]

# Thresholds for trend classification
_MIN_ORDERS_FOR_ANALYSIS = 10
_STRONG_GROWTH_THRESHOLD = 1.5
_SIGNIFICANT_DECLINE_THRESHOLD = 0.6
_MAX_CONFIDENCE = 0.9


async def classify_product_trend(
    session: AsyncSession,
    shop_id,
    product_id,
) -> tuple[TrendTier, float, str]:
    """Classify a product's trend over the last 30 days into one of four tiers.

    Compares order count in first 15 days vs second 15 days of a 30-day window.
    Classifies into: strong_positive, declining, no_strong_signal, or insufficient_data.

    Returns:
        Tuple of (tier, confidence, reason) where:
        - tier: One of strong_positive, declining, no_strong_signal, insufficient_data
        - confidence: 0.0-1.0 indicating certainty of classification
        - reason: Vietnamese explanation of the classification
    """
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    mid_period = now - timedelta(days=15)

    # Get order counts for first and second half of 30-day window
    first_half_stmt = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.shop_id == shop_id,
            Order.created_at >= thirty_days_ago,
            Order.created_at < mid_period,
        )
    )
    first_half_count = int((await session.execute(first_half_stmt)).scalar_one() or 0)

    second_half_stmt = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.shop_id == shop_id,
            Order.created_at >= mid_period,
            Order.created_at < now,
        )
    )
    second_half_count = int((await session.execute(second_half_stmt)).scalar_one() or 0)

    total_orders = first_half_count + second_half_count

    # Insufficient data check
    if total_orders < _MIN_ORDERS_FOR_ANALYSIS:
        return (
            "insufficient_data",
            0.3,
            "Chưa đủ dữ liệu lịch sử để phân tích xu hướng.",
        )

    # Calculate trend ratio (second half / first half)
    trend_ratio = (
        2.0
        if first_half_count == 0 and second_half_count > 0
        else 1.0
        if first_half_count == 0
        else second_half_count / first_half_count
    )

    # Strong positive trend: 1.5x or more growth
    if trend_ratio >= _STRONG_GROWTH_THRESHOLD:
        return (
            "strong_positive",
            min(_MAX_CONFIDENCE, trend_ratio / 3.0),
            "Doanh số bán hàng đang tăng trưởng mạnh mẽ.",
        )

    # Declining trend: 60% or less of previous period
    if trend_ratio <= _SIGNIFICANT_DECLINE_THRESHOLD:
        return (
            "declining",
            min(_MAX_CONFIDENCE, 1.0 - trend_ratio),
            "Doanh số đang giảm. Hãy kiểm tra chi tiết listing hoặc giá cả.",
        )

    # No strong signal: trend between thresholds
    return (
        "no_strong_signal",
        0.5 + abs(trend_ratio - 1.0) * 0.2,
        "Chưa thấy xu hướng tăng hoặc giảm rõ ràng.",
    )


def build_recommendation_message(
    product_name: str,
    tier: TrendTier,
    reason: str,
) -> str:
    """Build a Vietnamese recommendation message based on the tier.

    Messages are distinct and action-oriented:
    - strong_positive: Encourage creating new hero listing
    - declining: Explain why and suggest optimization
    - no_strong_signal: General tune-up without alarm
    - insufficient_data: Honest data insufficiency notice
    """
    if tier == "strong_positive":
        return (
            f"Sản phẩm {product_name} đang bán chạy. "
            "Nên tạo listing mới lấy sản phẩm này làm mẫu để mở rộng doanh số."
        )

    if tier == "declining":
        return (
            f"Sản phẩm {product_name} có dấu hiệu bán giảm. "
            "Kiểm tra và tối ưu listing, hình ảnh, mô tả để cải thiện doanh số."
        )

    if tier == "no_strong_signal":
        return (
            f"Sản phẩm {product_name} bán ổn định. "
            "Có thể cải thiện mô tả, hình ảnh hoặc chạy khuyến mãi để tăng doanh số."
        )

    # insufficient_data
    return (
        f"Sản phẩm {product_name} chưa có đủ dữ liệu bán hàng để phân tích. "
        "Tích lũy thêm dữ liệu rồi kiểm tra lại."
    )
