"""Livestream script recommendation — Issue #725 (RA-5).

Provides three-tier classification of livestream performance and deterministic
script templates organized around TikTok's official livestream coaching framework.
Optional AI personalization with daily cap and fallback to unmodified template
when personalization is unavailable or fails.

Public interface:
- classify_livestream_performance() → LivestreamScriptClassification
- get_livestream_script_recommendation() → LivestreamScriptRecommendation
- acknowledge_livestream_script() → acknowledgment record (zero TikTok API calls)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.ai.ranking import score_livestream
from juli_backend.models.models import Livestream, Recommendation

LlmGenerator = Callable[[str], Awaitable[str]]


@dataclass
class LivestreamScriptClassification:
    """Tier classification of livestream performance."""

    tier: Literal["needs_improvement", "maintenance", "low_confidence"]
    score_grade: int
    weakest_metric: str | None
    script_template: str


@dataclass
class LivestreamScriptRecommendation:
    """Complete recommendation with script, source, and metadata."""

    livestream_id: uuid.UUID
    classification_tier: Literal["needs_improvement", "maintenance", "low_confidence"]
    score_grade: int
    script: str
    source: Literal["llm", "rules"]
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ===================================================================
# Script Templates (TikTok's official livestream coaching framework)
# ===================================================================

_TEMPLATES = {
    "needs_improvement": {
        "revenue_per_viewer": (
            "Phiên livestream này có doanh thu trên lượt xem thấp hơn bình thường. "
            "Hãy cải thiện bằng cách: (1) Tăng tốc độ giới thiệu sản phẩm để giữ chú ý khán giả, "
            "(2) Tạo ưu đãi chốt đơn sớm (coupon, gói combo), (3) Ghim sản phẩm bán chạy nhất."
        ),
        "conversion_rate": (
            "Lượt xem cao nhưng tỷ lệ chốt đơn thấp hơn bình thường. "
            "Hãy cải thiện bằng cách: (1) Tăng cảm giác khẩn cấp (hạn số lượng, thời gian), "
            "(2) Chứng minh giá trị sản phẩm qua review/demo rõ ràng, "
            "(3) Tạo combo bán kèm để tăng giá trị đơn."
        ),
        "revenue_vs_avg": (
            "Doanh thu tổng của phiên này thấp hơn bình thường. "
            "Hãy cải thiện bằng cách: (1) Tăng tổng giá trị đơn (bán kèm combo), "
            "(2) Kéo dài thời gian livestream để tăng cơ hội bán, "
            "(3) Tập trung vào sản phẩm margin cao."
        ),
        "duration_efficiency": (
            "Doanh thu trên giờ livestream thấp hơn bình thường. "
            "Hãy cải thiện bằng cách: (1) Giảm thời gian chuyển giữa các sản phẩm, "
            "(2) Tạo flow bán hàng mạnh mẽ hơn với những sản phẩm bán chạy, "
            "(3) Tắt livestream sớm nếu không còn khán giả thay vì kéo dài vô ích."
        ),
    },
    "maintenance": (
        "Phiên livestream này có hiệu suất tốt! Hãy tiếp tục duy trì những thói quen này: "
        "(1) Thời gian bắt đầu và nội dung sẽ tiếp tục hút khán giả, "
        "(2) Cách tương tác và cảm giác khẩn cấp tạo chốt đơn tốt, "
        "(3) Sản phẩm được lựa chọn phù hợp với khán giả. Tiếp tục với kịch bản này cho phiên tới!"
    ),
    "low_confidence": (
        "Chúng tôi chưa có đủ dữ liệu lịch sử để so sánh hiệu suất của bạn. "
        "Đối với phiên tới, hãy áp dụng những best practice: "
        "(1) Bắt đầu livestream trong giờ vàng (18:00-22:00), "
        "(2) Chuẩn bị 3-5 sản phẩm chủ lực để tập trung bán, "
        "(3) Tạo ưu đãi chốt đơn sớm (coupon/gói combo) để kích hoạt bán, "
        "(4) Tương tác tích cực với chat để tăng engagement, "
        "(5) Kéo dài livestream ít nhất 30-45 phút để tối ưu khán giả."
    ),
}

_DEFAULT_TEMPLATE = _TEMPLATES["low_confidence"]


# ===================================================================
# Classification and Recommendation Logic
# ===================================================================


async def _shop_stream_count(session: AsyncSession, shop_id: uuid.UUID) -> int:
    """Count total livestreams for a shop."""
    stmt = select(func.count()).select_from(Livestream).where(Livestream.shop_id == shop_id)
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _shop_stream_averages(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[str, float] | None:
    """Compute historical per-stream averages for the shop, or None if insufficient data."""
    count = await _shop_stream_count(session, shop_id)
    # Need at least 3 streams to establish confidence
    if count < 3:
        return None

    stmt = select(Livestream).where(
        Livestream.shop_id == shop_id,
        Livestream.viewer_count.isnot(None),
        Livestream.viewer_count > 0,
    )
    result = await session.execute(stmt)
    streams = list(result.scalars().all())

    if len(streams) < 3:
        return None

    total_grade = 0.0
    for stream in streams:
        from juli_backend.ai.ranking.scorer import score_livestream as score_func

        score = await score_func(session, stream.id)
        total_grade += score.grade

    avg_grade = total_grade / len(streams)
    return {"avg_grade": avg_grade}


async def classify_livestream_performance(
    session: AsyncSession,
    shop_id: uuid.UUID,
    livestream_id: uuid.UUID,
) -> LivestreamScriptClassification:
    """Classify a livestream into one of three tiers."""
    ls = await session.get(Livestream, livestream_id)
    if ls is None:
        return LivestreamScriptClassification(
            tier="low_confidence",
            score_grade=0,
            weakest_metric=None,
            script_template=_DEFAULT_TEMPLATE,
        )

    # Score the current livestream
    score = await score_livestream(session, livestream_id)

    # Get historical averages
    averages = await _shop_stream_averages(session, shop_id)

    # Determine tier based on historical context
    if averages is None:
        # Insufficient history → low confidence
        return LivestreamScriptClassification(
            tier="low_confidence",
            score_grade=score.grade,
            weakest_metric=None,
            script_template=_DEFAULT_TEMPLATE,
        )

    avg_grade = averages["avg_grade"]
    threshold_good = avg_grade + 10  # 10 points above average = maintenance
    threshold_poor = avg_grade - 10  # 10 points below average = needs improvement

    if score.grade >= threshold_good:
        # Strong performer
        return LivestreamScriptClassification(
            tier="maintenance",
            score_grade=score.grade,
            weakest_metric=None,
            script_template=_TEMPLATES["maintenance"],
        )
    elif score.grade < threshold_poor:
        # Weak performer
        weakest_metric = "conversion_rate"
        if score.breakdown:
            weakest_metric = min(score.breakdown, key=lambda k: score.breakdown[k])
        template = _TEMPLATES["needs_improvement"].get(
            weakest_metric, _TEMPLATES["needs_improvement"]["conversion_rate"]
        )
        return LivestreamScriptClassification(
            tier="needs_improvement",
            score_grade=score.grade,
            weakest_metric=weakest_metric,
            script_template=template,
        )
    else:
        # In the middle → low confidence (not enough data to be certain)
        return LivestreamScriptClassification(
            tier="low_confidence",
            score_grade=score.grade,
            weakest_metric=None,
            script_template=_DEFAULT_TEMPLATE,
        )


async def _count_daily_llm_calls(session: AsyncSession, shop_id: uuid.UUID) -> int:
    """Count LLM personalization calls for the shop today."""
    day_start, day_end = _today_window_utc()
    stmt = (
        select(func.count())
        .select_from(Recommendation)
        .where(
            Recommendation.shop_id == shop_id,
            Recommendation.recommendation_type == "livestream_script_llm",
            Recommendation.created_at >= day_start,
            Recommendation.created_at < day_end,
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


def _today_window_utc() -> tuple[datetime, datetime]:
    """Return (start, end) of today in UTC."""
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    return start, end


async def get_livestream_script_recommendation(
    session: AsyncSession,
    shop_id: uuid.UUID,
    livestream_id: uuid.UUID,
    *,
    max_calls_per_day: int = 20,
    llm_generator: LlmGenerator | None = None,
) -> LivestreamScriptRecommendation:
    """Get a complete script recommendation for a livestream."""
    # Classify the livestream
    classification = await classify_livestream_performance(session, shop_id, livestream_id)

    # Determine if we can use LLM personalization
    used_calls = await _count_daily_llm_calls(session, shop_id)
    allow_llm = llm_generator is not None and used_calls < max_calls_per_day

    script = classification.script_template
    source: Literal["llm", "rules"] = "rules"

    if allow_llm and llm_generator is not None:
        # Try to personalize with LLM
        prompt = (
            "Bạn là trợ lý tối ưu livestream TikTok Shop.\n"
            f"Điểm hiệu suất livestream hiện tại: {classification.score_grade}/100.\n"
            f"Tầng phân loại: {classification.tier}.\n"
            f"Template gốc: {classification.script_template}\n"
            "Hãy viết lại gợi ý tối ưu bằng tiếng Việt, cụ thể, hành động rõ ràng, "
            "và luôn duy trì ý chính của template gốc. Không vượt quá 150 từ."
        )
        try:
            generated = (await llm_generator(prompt)).strip()
            if generated:
                script = generated
                source = "llm"
        except Exception:
            # Fall back to template on any error
            pass

    return LivestreamScriptRecommendation(
        livestream_id=livestream_id,
        classification_tier=classification.tier,
        score_grade=classification.score_grade,
        script=script,
        source=source,
    )


async def acknowledge_livestream_script(
    session: AsyncSession,
    shop_id: uuid.UUID,
    livestream_id: uuid.UUID,
    script_version: str,
) -> dict[str, str]:
    """Record that seller viewed the script recommendation (zero TikTok API calls).

    This function only records locally in the database and makes no external API calls.
    """
    # Record acknowledgment in Recommendation table
    now = datetime.now(UTC)
    payload_data = {
        "livestream_id": str(livestream_id),
        "script_version": script_version,
        "acknowledged_at": now.isoformat(),
    }
    recommendation = Recommendation(
        id=uuid.uuid4(),
        shop_id=shop_id,
        recommendation_type="livestream_script_acknowledged",
        payload=json.dumps(payload_data),
        status="viewed",
    )
    session.add(recommendation)
    await session.flush()

    return {
        "status": "acknowledged",
        "livestream_id": str(livestream_id),
        "recorded_at": now.isoformat(),
    }
