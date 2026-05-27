from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_active_shop
from src.data import InventoryItem, Order, Product, Shop, get_session
from src.intelligence.forecasting import get_low_stock_risks

_ESTIMATED_FEE_RATE = Decimal("0.15")

router = APIRouter(prefix="/analytics", tags=["analytics"])


class Period(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class DataPoint(BaseModel):
    date: str
    gmv: str


class RevenueResponse(BaseModel):
    total_gmv: str
    trend: str
    period: str
    data_points: list[DataPoint]


@router.get("/revenue", response_model=RevenueResponse)
async def get_revenue(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    period: Period = Query(default=Period.daily),
) -> RevenueResponse:
    """Return GMV aggregated by period with trend direction."""
    now = datetime.now(timezone.utc)

    if period == Period.daily:
        lookback = timedelta(days=30)
        bucket_days = 1
    elif period == Period.weekly:
        lookback = timedelta(weeks=12)
        bucket_days = 7
    else:
        lookback = timedelta(days=365)
        bucket_days = 30

    start = now - lookback

    stmt = (
        select(Order.update_time, Order.total_amount)
        .where(Order.shop_id == shop.id, Order.update_time >= start)
        .order_by(Order.update_time.asc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    buckets: dict[str, Decimal] = {}
    for update_time, amount in rows:
        bucket_key = _bucket_key(update_time, bucket_days)
        buckets[bucket_key] = buckets.get(bucket_key, Decimal("0")) + amount

    total_gmv = sum(buckets.values(), Decimal("0"))
    data_points = [
        DataPoint(date=k, gmv=str(v)) for k, v in sorted(buckets.items())
    ]

    trend = _compute_trend(data_points)

    return RevenueResponse(
        total_gmv=str(total_gmv),
        trend=trend,
        period=period.value,
        data_points=data_points,
    )


def _bucket_key(dt: datetime, bucket_days: int) -> str:
    if bucket_days == 1:
        return dt.strftime("%Y-%m-%d")
    elif bucket_days == 7:
        iso_year, iso_week, _ = dt.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    else:
        return dt.strftime("%Y-%m")


def _compute_trend(data_points: list[DataPoint]) -> str:
    """Compare the last two buckets to determine trend direction."""
    if len(data_points) < 2:
        return "flat"
    last = Decimal(data_points[-1].gmv)
    prev = Decimal(data_points[-2].gmv)
    if last > prev:
        return "up"
    elif last < prev:
        return "down"
    return "flat"


class SkuProfitItem(BaseModel):
    sku_id: str
    product_name: str
    revenue: str
    profit: str


class PrepChecklistItem(BaseModel):
    sku_id: str
    tiktok_product_id: str
    action: str
    days_until_stockout: float
    quantity: int


class DailyAnalyticsResponse(BaseModel):
    date: str
    total_revenue: str
    total_profit: str
    sku_breakdown: list[SkuProfitItem]
    prep_checklist: list[PrepChecklistItem]


@router.get("/daily", response_model=DailyAnalyticsResponse)
async def get_daily_analytics(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> DailyAnalyticsResponse:
    """Return yesterday's profit breakdown by SKU and livestream prep checklist."""
    now = datetime.now(timezone.utc)
    yesterday = (now - timedelta(days=1)).date()
    day_start = datetime.combine(yesterday, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    order_stmt = select(Order).where(
        Order.shop_id == shop.id,
        Order.update_time >= day_start,
        Order.update_time < day_end,
    )
    order_result = await session.execute(order_stmt)
    yesterday_orders = list(order_result.scalars().all())
    total_revenue = sum((o.total_amount for o in yesterday_orders), Decimal("0"))
    total_profit = total_revenue * (Decimal("1") - _ESTIMATED_FEE_RATE)

    product_stmt = select(Product).where(Product.shop_id == shop.id)
    product_result = await session.execute(product_stmt)
    products = list(product_result.scalars().all())
    products_by_tiktok = {p.tiktok_product_id: p for p in products}
    revenue_base = sum((p.revenue for p in products), Decimal("0"))

    inv_stmt = select(InventoryItem).where(InventoryItem.shop_id == shop.id)
    inv_result = await session.execute(inv_stmt)
    inventory = list(inv_result.scalars().all())

    sku_breakdown: list[SkuProfitItem] = []
    for item in inventory:
        product = products_by_tiktok.get(item.tiktok_product_id)
        if product is None:
            continue
        share = (
            product.revenue / revenue_base
            if revenue_base > 0
            else Decimal("1") / max(len(inventory), 1)
        )
        sku_revenue = total_revenue * share
        sku_profit = sku_revenue * (Decimal("1") - _ESTIMATED_FEE_RATE)
        sku_breakdown.append(
            SkuProfitItem(
                sku_id=item.tiktok_sku_id,
                product_name=product.name,
                revenue=str(sku_revenue.quantize(Decimal("0.01"))),
                profit=str(sku_profit.quantize(Decimal("0.01"))),
            )
        )

    risks = await get_low_stock_risks(session, shop.id)
    prep_checklist = [
        PrepChecklistItem(
            sku_id=risk.sku_id,
            tiktok_product_id=risk.tiktok_product_id,
            action="restock",
            days_until_stockout=round(risk.days_until_stockout, 1),
            quantity=risk.quantity,
        )
        for risk in risks
    ]

    return DailyAnalyticsResponse(
        date=yesterday.isoformat(),
        total_revenue=str(total_revenue.quantize(Decimal("0.01"))),
        total_profit=str(total_profit.quantize(Decimal("0.01"))),
        sku_breakdown=sku_breakdown,
        prep_checklist=prep_checklist,
    )
