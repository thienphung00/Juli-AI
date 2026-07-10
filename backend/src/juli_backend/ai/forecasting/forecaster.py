"""Inventory depletion forecasting and sales velocity analysis."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import InventoryItem, Order

_MIN_HISTORY_FOR_REGRESSION = 30
_VELOCITY_CHANGE_THRESHOLD = 0.15
_DEFAULT_LOW_STOCK_WINDOW_DAYS = 7


@dataclass
class ForecastResult:
    sku_id: str
    depletion_date: datetime | None
    daily_velocity: float
    method: Literal["linear_regression", "moving_average"]
    horizon_mape: float | None = None


@dataclass
class LowStockRisk:
    sku_id: str
    tiktok_product_id: str
    quantity: int
    daily_velocity: float
    days_until_stockout: float
    urgency_score: float


@dataclass
class VelocityChange:
    sku_id: str
    direction: Literal["accelerating", "decelerating"]
    recent_velocity: float
    prior_velocity: float
    change_ratio: float


def _linear_regression_forecast(
    daily_series: list[float], horizon: int
) -> list[float]:
    """Fit y = intercept + slope * x and project the next *horizon* days."""
    n = len(daily_series)
    if n == 0:
        return [0.0] * horizon
    if n == 1:
        return [max(0.0, daily_series[0])] * horizon

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(daily_series) / n
    num = sum((xs[i] - mean_x) * (daily_series[i] - mean_y) for i in range(n))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    slope = num / den
    intercept = mean_y - slope * mean_x

    return [max(0.0, intercept + slope * (n + i)) for i in range(horizon)]


def _moving_average_forecast(daily_series: list[float], horizon: int) -> list[float]:
    if not daily_series:
        return [0.0] * horizon
    rate = sum(daily_series) / len(daily_series)
    return [max(0.0, rate)] * horizon


def _mape(actual: list[float], predicted: list[float]) -> float:
    pairs = [
        (a, p)
        for a, p in zip(actual, predicted, strict=True)
        if a > 0
    ]
    if not pairs:
        return 0.0
    return sum(abs(a - p) / a for a, p in pairs) / len(pairs)


def _active_sales_window(daily_series: list[float]) -> list[float]:
    """Drop leading/trailing calendar days with zero attributed sales."""
    start = next((i for i, v in enumerate(daily_series) if v > 0), len(daily_series))
    if start >= len(daily_series):
        return []
    active = daily_series[start:]
    end = len(active)
    while end > 0 and active[end - 1] == 0:
        end -= 1
    return active[:end]


def _history_days_with_sales(daily_series: list[float]) -> int:
    return sum(1 for value in daily_series if value > 0)


def _forecast_daily_rates(
    daily_series: list[float], horizon: int = 7
) -> tuple[list[float], Literal["linear_regression", "moving_average"]]:
    active = _active_sales_window(daily_series)
    if not active:
        return [0.0] * horizon, "moving_average"
    if _history_days_with_sales(active) >= _MIN_HISTORY_FOR_REGRESSION:
        return _linear_regression_forecast(active, horizon), "linear_regression"
    return _moving_average_forecast(active, horizon), "moving_average"


def _backtest_horizon_mape(daily_series: list[float], horizon: int = 7) -> float | None:
    active = _active_sales_window(daily_series)
    if len(active) <= horizon:
        return None
    train = active[:-horizon]
    actual = active[-horizon:]
    predicted, _ = _forecast_daily_rates(train, horizon)
    return _mape(actual, predicted)


async def _daily_units_series(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    lookback_days: int = 90,
) -> dict[str, list[float]]:
    """Build per-SKU daily unit estimates from completed orders (equal attribution)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    stmt = select(Order).where(
        Order.shop_id == shop_id,
        Order.status == "COMPLETED",
        Order.created_at >= cutoff,
    )
    result = await session.execute(stmt)
    orders = list(result.scalars().all())

    counts_by_day: dict[date, float] = {}
    for order in orders:
        created = order.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day = created.date()
        counts_by_day[day] = counts_by_day.get(day, 0.0) + 1.0

    start_day = cutoff.date()
    end_day = now.date()
    shop_daily: list[float] = []
    cursor = start_day
    while cursor <= end_day:
        shop_daily.append(counts_by_day.get(cursor, 0.0))
        cursor += timedelta(days=1)

    inv_stmt = select(InventoryItem).where(InventoryItem.shop_id == shop_id)
    inv_result = await session.execute(inv_stmt)
    skus = list(inv_result.scalars().all())
    if not skus:
        return {}

    per_sku_share = 1.0 / len(skus)
    attributed = [v * per_sku_share for v in shop_daily]
    return {item.tiktok_sku_id: list(attributed) for item in skus}


async def _daily_series_for_sku(
    session: AsyncSession, shop_id: uuid.UUID, sku_id: str
) -> list[float]:
    all_series = await _daily_units_series(session, shop_id)
    return all_series.get(sku_id, [])


async def get_forecast(
    session: AsyncSession, shop_id: uuid.UUID, sku_id: str
) -> ForecastResult:
    item_stmt = select(InventoryItem).where(
        InventoryItem.shop_id == shop_id,
        InventoryItem.tiktok_sku_id == sku_id,
    )
    item_result = await session.execute(item_stmt)
    item = item_result.scalar_one_or_none()
    if item is None:
        return ForecastResult(
            sku_id=sku_id,
            depletion_date=None,
            daily_velocity=0.0,
            method="moving_average",
        )

    daily_series = await _daily_series_for_sku(session, shop_id, sku_id)
    predicted, method = _forecast_daily_rates(daily_series, horizon=7)
    daily_velocity = predicted[0] if predicted else 0.0
    horizon_mape = _backtest_horizon_mape(daily_series)

    depletion_date: datetime | None = None
    if daily_velocity > 0 and item.quantity > 0:
        days_left = item.quantity / daily_velocity
        depletion_date = datetime.now(timezone.utc) + timedelta(days=days_left)

    return ForecastResult(
        sku_id=sku_id,
        depletion_date=depletion_date,
        daily_velocity=daily_velocity,
        method=method,
        horizon_mape=horizon_mape,
    )


async def get_low_stock_risks(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    window_days: int = _DEFAULT_LOW_STOCK_WINDOW_DAYS,
) -> list[LowStockRisk]:
    inv_stmt = select(InventoryItem).where(InventoryItem.shop_id == shop_id)
    inv_result = await session.execute(inv_stmt)
    items = list(inv_result.scalars().all())
    if not items:
        return []

    daily_by_sku = await _daily_units_series(session, shop_id)
    risks: list[LowStockRisk] = []

    for item in items:
        series = _active_sales_window(daily_by_sku.get(item.tiktok_sku_id, []))
        predicted, _ = _forecast_daily_rates(series, horizon=1)
        velocity = predicted[0] if predicted else 0.0

        if velocity <= 0:
            if item.quantity <= 0:
                days_until = 0.0
            else:
                continue
        else:
            days_until = item.quantity / velocity

        if days_until > window_days:
            continue

        urgency = 1.0 / max(days_until, 0.01)
        risks.append(
            LowStockRisk(
                sku_id=item.tiktok_sku_id,
                tiktok_product_id=item.tiktok_product_id,
                quantity=item.quantity,
                daily_velocity=velocity,
                days_until_stockout=days_until,
                urgency_score=urgency,
            )
        )

    risks.sort(key=lambda r: r.urgency_score, reverse=True)
    return risks


async def get_velocity_changes(
    session: AsyncSession, shop_id: uuid.UUID
) -> list[VelocityChange]:
    daily_by_sku = await _daily_units_series(session, shop_id)
    changes: list[VelocityChange] = []

    for sku_id, series in daily_by_sku.items():
        if len(series) < 14:
            continue

        recent = series[-7:]
        prior = series[-14:-7]
        recent_velocity = sum(recent) / len(recent)
        prior_velocity = sum(prior) / len(prior)

        if prior_velocity <= 0:
            if recent_velocity <= 0:
                continue
            change_ratio = float("inf")
            direction: Literal["accelerating", "decelerating"] = "accelerating"
        else:
            change_ratio = (recent_velocity - prior_velocity) / prior_velocity
            if change_ratio >= _VELOCITY_CHANGE_THRESHOLD:
                direction = "accelerating"
            elif change_ratio <= -_VELOCITY_CHANGE_THRESHOLD:
                direction = "decelerating"
            else:
                continue

        changes.append(
            VelocityChange(
                sku_id=sku_id,
                direction=direction,
                recent_velocity=recent_velocity,
                prior_velocity=prior_velocity,
                change_ratio=change_ratio,
            )
        )

    changes.sort(key=lambda c: abs(c.change_ratio), reverse=True)
    return changes
