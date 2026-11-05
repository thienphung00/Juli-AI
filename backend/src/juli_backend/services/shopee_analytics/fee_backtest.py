"""Ops: the fee-formula backtest of one shop over a window of its order lines (P92 B-9)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit import fee_backtest

DEFAULT_DAYS = 90


class NoShopeeData(LookupError):
    """The shop has no Shopee numbers to anchor a window on."""


async def run(
    session: AsyncSession, shop_id: uuid.UUID, *, as_of: date | None, days: int = DEFAULT_DAYS
) -> dict[str, Any]:
    anchor = as_of or await loaders.default_as_of(session, shop_id)
    if anchor is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{anchor:%Y-%m}"))
    window = Window(anchor - timedelta(days=days - 1), anchor)
    view = await service.load_view(session, shop_id, ctx, window)
    out = fee_backtest.backtest(view.pairs, view.fees.schedule, view.costs.by_key)
    cov = view.income_coverage
    return {
        "window": window.json(),
        "days": days,
        "orders_in_profit_base": cov.orders,
        "orders_with_income": cov.with_income,
        **out,
    }


__all__ = ["DEFAULT_DAYS", "NoShopeeData", "run"]
