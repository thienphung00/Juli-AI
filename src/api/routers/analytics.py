from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_active_shop
from src.data import Order, Shop, get_session

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
