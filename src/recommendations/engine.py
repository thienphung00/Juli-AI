"""Rule-based product push and restock recommendations (no LLM)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import InventoryItem, Product
from src.intelligence.forecasting.forecaster import (
    get_low_stock_risks,
    get_velocity_changes,
)

_MAX_SUGGESTIONS = 10
_WEIGHT_TREND = 0.35
_WEIGHT_MARGIN = 0.35
_WEIGHT_STOCK = 0.30


@dataclass
class ProductPushSuggestion:
    tiktok_product_id: str
    product_name: str
    sku_id: str | None
    composite_score: float
    message: str
    cta: str


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
