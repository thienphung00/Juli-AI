"""Recommendations engine for product push and stream optimization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.utils.data.models import Creator, InventoryItem, Livestream, Product, Recommendation
from src.modules.catalog.domain.intelligence.scoring import score_livestream
from src.modules.catalog.domain.intelligence.forecasting.forecaster import (
    get_low_stock_risks,
    get_velocity_changes,
)

_MAX_SUGGESTIONS = 10
_WEIGHT_TREND = 0.35
_WEIGHT_MARGIN = 0.35
_WEIGHT_STOCK = 0.30
_DEFAULT_MAX_LLM_CALLS_PER_DAY = 20

LlmGenerator = Callable[[str], Awaitable[str]]


@dataclass
class ProductPushSuggestion:
    tiktok_product_id: str
    product_name: str
    sku_id: str | None
    composite_score: float
    message: str
    cta: str


@dataclass
class StreamOptimizationSuggestion:
    session_id: str
    score_grade: int
    message: str
    cta: str
    source: Literal["llm", "rules"]


@dataclass
class HostProductMatch:
    creator_id: str
    creator_name: str
    tiktok_product_id: str
    product_name: str
    match_score: float
    message: str
    cta: str
    source: Literal["llm", "rules"]


def _trend_score(
    sku_ids: set[str],
    velocity_by_sku: dict[str, float],
) -> float:
    if not sku_ids:
        return 0.5
    scores = [velocity_by_sku.get(sku, 0.5) for sku in sku_ids]
    return max(scores)


def _margin_score(revenue: float, units_sold: int, max_margin: float) -> float:
    if max_margin <= 0:
        return 0.0
    per_unit = revenue / max(units_sold, 1)
    return min(per_unit / max_margin, 1.0)


def _stock_score_for_push(
    quantities: list[int],
    days_until_stockout: float | None,
) -> float:
    if not quantities or max(quantities) <= 0:
        return 0.0
    if days_until_stockout is not None and days_until_stockout < 2:
        return 0.15
    if days_until_stockout is not None and days_until_stockout < 4:
        return 0.45
    qty = max(quantities)
    if qty >= 30:
        return 1.0
    if qty >= 10:
        return 0.75
    return 0.55


def _build_message(
    name: str,
    *,
    accelerating: bool,
    strong_margin: bool,
    well_stocked: bool,
) -> str:
    parts: list[str] = [f"Nên ưu tiên đẩy {name}"]
    if accelerating:
        parts.append("vì đang bán chạy hơn tuần trước")
    if strong_margin:
        parts.append("và mang lại doanh thu cao trên mỗi đơn")
    elif well_stocked:
        parts.append("và còn đủ hàng để bán trong livestream")
    return " — ".join(parts) + "."


def _build_cta(name: str) -> str:
    return f"Đẩy sản phẩm {name} lên livestream tối nay"


def _today_window_utc() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    end = start + timedelta(days=1)
    return start, end


async def _count_daily_llm_calls(session: AsyncSession, shop_id: uuid.UUID) -> int:
    day_start, day_end = _today_window_utc()
    stmt = (
        select(func.count())
        .select_from(Recommendation)
        .where(
            Recommendation.shop_id == shop_id,
            Recommendation.recommendation_type.in_(
                ["stream_optimization_llm", "host_product_matching_llm"]
            ),
            Recommendation.created_at >= day_start,
            Recommendation.created_at < day_end,
        )
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def _resolve_livestream(
    session: AsyncSession,
    shop_id: uuid.UUID,
    session_id: uuid.UUID | str,
) -> Livestream | None:
    if isinstance(session_id, uuid.UUID):
        livestream = await session.get(Livestream, session_id)
        if livestream and livestream.shop_id == shop_id:
            return livestream
        return None

    stmt: Select[tuple[Livestream]] = select(Livestream).where(
        Livestream.shop_id == shop_id,
        Livestream.tiktok_livestream_id == str(session_id),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _build_stream_fallback(
    *,
    session_id: str,
    score_grade: int,
    weakest_metric: str,
) -> StreamOptimizationSuggestion:
    metric_copy = {
        "revenue_per_viewer": "giá trị mỗi lượt xem",
        "conversion_rate": "tỷ lệ chốt đơn",
        "revenue_vs_avg": "doanh thu so với trung bình",
        "duration_efficiency": "hiệu suất theo thời lượng livestream",
    }.get(weakest_metric, "khả năng chốt đơn")
    message = (
        f"Phiên {session_id} đang ở mức {score_grade}/100. "
        f"Ưu tiên cải thiện {metric_copy} bằng ưu đãi chốt đơn sớm và ghim sản phẩm chủ lực."
    )
    return StreamOptimizationSuggestion(
        session_id=session_id,
        score_grade=score_grade,
        message=message,
        cta="Nhấn để áp dụng kịch bản tối ưu livestream",
        source="rules",
    )


async def get_stream_optimization(
    session: AsyncSession,
    shop_id: uuid.UUID,
    session_id: uuid.UUID | str,
    *,
    max_calls_per_day: int = _DEFAULT_MAX_LLM_CALLS_PER_DAY,
    llm_generator: LlmGenerator | None = None,
) -> StreamOptimizationSuggestion:
    livestream = await _resolve_livestream(session, shop_id, session_id)
    if livestream is None:
        return StreamOptimizationSuggestion(
            session_id=str(session_id),
            score_grade=0,
            message=(
                "Chưa tìm thấy dữ liệu phiên livestream. "
                "Hãy đồng bộ dữ liệu rồi thử lại để nhận gợi ý tối ưu."
            ),
            cta="Nhấn để đồng bộ lại dữ liệu phiên",
            source="rules",
        )

    score = await score_livestream(session, livestream.id)
    if score.breakdown:
        weakest_metric = min(score.breakdown, key=lambda k: score.breakdown[k])
    else:
        weakest_metric = "conversion_rate"

    fallback = _build_stream_fallback(
        session_id=livestream.tiktok_livestream_id,
        score_grade=score.grade,
        weakest_metric=weakest_metric,
    )
    used_calls = await _count_daily_llm_calls(session, shop_id)
    if llm_generator is None or used_calls >= max_calls_per_day:
        return fallback

    prompt = (
        "Bạn là trợ lý tối ưu livestream TikTok Shop.\n"
        f"Điểm livestream hiện tại: {score.grade}/100.\n"
        f"Điểm chi tiết: {score.breakdown}.\n"
        "Viết đúng 1 gợi ý tối ưu bằng tiếng Việt, ngắn gọn, rõ hành động."
    )
    try:
        generated = (await llm_generator(prompt)).strip()
    except Exception:
        return fallback
    if not generated:
        return fallback

    return StreamOptimizationSuggestion(
        session_id=livestream.tiktok_livestream_id,
        score_grade=score.grade,
        message=generated,
        cta="Nhấn để áp dụng gợi ý cho phiên tiếp theo",
        source="llm",
    )


def _host_performance_summary(streams: list[Livestream]) -> dict[uuid.UUID, Livestream]:
    latest_by_creator: dict[uuid.UUID, Livestream] = {}
    for stream in streams:
        if stream.creator_id is None:
            continue
        existing = latest_by_creator.get(stream.creator_id)
        if existing is None:
            latest_by_creator[stream.creator_id] = stream
            continue
        if (stream.end_time or stream.created_at) > (existing.end_time or existing.created_at):
            latest_by_creator[stream.creator_id] = stream
    return latest_by_creator


async def get_host_product_matching(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    limit: int = 3,
    max_calls_per_day: int = _DEFAULT_MAX_LLM_CALLS_PER_DAY,
    llm_generator: LlmGenerator | None = None,
) -> list[HostProductMatch]:
    creator_stmt = select(Creator).where(Creator.shop_id == shop_id)
    creators_result = await session.execute(creator_stmt)
    creators = list(creators_result.scalars().all())
    if not creators:
        return []

    stream_stmt = select(Livestream).where(
        Livestream.shop_id == shop_id,
        Livestream.creator_id.isnot(None),
    )
    stream_result = await session.execute(stream_stmt)
    streams = list(stream_result.scalars().all())
    latest_by_creator = _host_performance_summary(streams)

    suggestions = await get_product_push_suggestions(session, shop_id, limit=max(limit, 10))
    if not suggestions:
        return []

    used_calls = await _count_daily_llm_calls(session, shop_id)
    allow_llm = llm_generator is not None and used_calls < max_calls_per_day
    matches: list[HostProductMatch] = []
    products_ranked = suggestions[:limit]

    for product in products_ranked:
        best_creator: Creator | None = None
        best_score = 0.0
        for creator in creators:
            candidate = latest_by_creator.get(creator.id)
            if candidate is None:
                continue
            stream_score = await score_livestream(session, candidate.id)
            total = product.composite_score * 100 * 0.5 + stream_score.grade * 0.5
            if total > best_score:
                best_score = total
                best_creator = creator

        if best_creator is None:
            continue

        default_message = (
            f"Gợi ý để {best_creator.name} bán {product.product_name} vì "
            "sản phẩm đang có tín hiệu chuyển đổi tốt và hợp với hiệu suất phiên gần nhất."
        )
        message = default_message
        source: Literal["llm", "rules"] = "rules"
        if allow_llm and llm_generator is not None:
            prompt = (
                f"Tạo 1 câu gợi ý tiếng Việt để ghép host '{best_creator.name}' "
                f"với sản phẩm '{product.product_name}' cho phiên TikTok Shop."
            )
            try:
                generated = (await llm_generator(prompt)).strip()
            except Exception:
                generated = ""
            if generated:
                message = generated
                source = "llm"

        matches.append(
            HostProductMatch(
                creator_id=str(best_creator.id),
                creator_name=best_creator.name,
                tiktok_product_id=product.tiktok_product_id,
                product_name=product.product_name,
                match_score=round(best_score / 100.0, 4),
                message=message,
                cta=(
                    f"Nhấn để gán {best_creator.name} phụ trách "
                    f"{product.product_name} ở phiên tới"
                ),
                source=source,
            )
        )

    matches.sort(key=lambda item: item.match_score, reverse=True)
    return matches[:limit]


async def get_product_push_suggestions(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    limit: int = _MAX_SUGGESTIONS,
) -> list[ProductPushSuggestion]:
    """Rank products to promote using trend, stock, and margin heuristics."""
    prod_stmt = select(Product).where(
        Product.shop_id == shop_id,
        Product.status == "ACTIVE",
    )
    prod_result = await session.execute(prod_stmt)
    products = list(prod_result.scalars().all())
    if not products:
        return []

    inv_stmt = select(InventoryItem).where(InventoryItem.shop_id == shop_id)
    inv_result = await session.execute(inv_stmt)
    inventory = list(inv_result.scalars().all())

    inv_by_product: dict[str, list[InventoryItem]] = {}
    for item in inventory:
        inv_by_product.setdefault(item.tiktok_product_id, []).append(item)

    velocity_changes = await get_velocity_changes(session, shop_id)
    velocity_by_sku: dict[str, float] = {}
    for change in velocity_changes:
        if change.direction == "accelerating":
            velocity_by_sku[change.sku_id] = 1.0
        elif change.direction == "decelerating":
            velocity_by_sku[change.sku_id] = 0.2
        else:
            velocity_by_sku[change.sku_id] = 0.5

    low_stock = await get_low_stock_risks(session, shop_id)
    stockout_by_sku = {r.sku_id: r.days_until_stockout for r in low_stock}

    margins = [
        float(p.revenue or 0) / max(p.units_sold or 0, 1) for p in products
    ]
    max_margin = max(margins) if margins else 0.0

    scored: list[ProductPushSuggestion] = []

    for product in products:
        items = inv_by_product.get(product.tiktok_product_id, [])
        if not items:
            continue

        sku_ids = {item.tiktok_sku_id for item in items}
        quantities = [item.quantity for item in items]
        if max(quantities) <= 0:
            continue

        days_values = [
            stockout_by_sku[item.tiktok_sku_id]
            for item in items
            if item.tiktok_sku_id in stockout_by_sku
        ]
        days_until = min(days_values) if days_values else None

        trend = _trend_score(sku_ids, velocity_by_sku)
        margin = _margin_score(
            float(product.revenue or 0), product.units_sold or 0, max_margin
        )
        stock = _stock_score_for_push(quantities, days_until)
        composite = (
            _WEIGHT_TREND * trend + _WEIGHT_MARGIN * margin + _WEIGHT_STOCK * stock
        )

        if composite <= 0:
            continue

        primary_sku = max(items, key=lambda i: i.quantity).tiktok_sku_id
        accelerating = trend >= 0.9
        strong_margin = margin >= 0.7
        well_stocked = stock >= 0.7

        scored.append(
            ProductPushSuggestion(
                tiktok_product_id=product.tiktok_product_id,
                product_name=product.name,
                sku_id=primary_sku,
                composite_score=round(composite, 4),
                message=_build_message(
                    product.name,
                    accelerating=accelerating,
                    strong_margin=strong_margin,
                    well_stocked=well_stocked,
                ),
                cta=_build_cta(product.name),
            )
        )

    scored.sort(key=lambda s: s.composite_score, reverse=True)
    return scored[:limit]
