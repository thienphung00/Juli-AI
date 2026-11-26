"""F1 (owner 2026-11-25): "hiện tại" of a scope on a loaded environment.

The one door every surface of the recommendation package takes to the last 30 complete days (GMV,
đơn, lượt xem, lượt nhấp, AOV): :func:`forecast_base.current_30d` on the env's stored rows, the
figures the product picker shows. ``None`` when the shop has no stored rows (the caller keeps the
window's own metrics). Đo lường's "trước" (``running.build_actual``) and a plan's frozen base are
other things and do not come here. Pure apart from reading the already-loaded env.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from juli_backend.services.shopee_analytics import forecast_base, funnel

if TYPE_CHECKING:
    from juli_backend.services.shopee_builder.engine.contract import FunnelBase
    from juli_backend.services.shopee_recommendations.env import RecoEnv

ZERO = Decimal(0)


def rows_of(env: RecoEnv) -> funnel.FunnelRows | None:
    """The stored funnel rows: the 60-day history, else the window's own."""
    for rows in (env.funnel_history, getattr(env.view.data, "funnel", None)):
        if isinstance(rows, funnel.FunnelRows):
            return rows
    return None


def current_30d(env: RecoEnv, item_ids: Iterable[str] | None = None) -> FunnelBase | None:
    """The scope's last 30 days (the shop without ids); ``None`` without stored order days."""
    rows = rows_of(env)
    if rows is None or not (rows.shop_days or rows.sources or rows.product_days):
        return None
    items = tuple(dict.fromkeys(str(i) for i in item_ids or () if i))
    key = (id(rows), items)
    cached = env._current_cache.get(key)
    if cached is None:
        cached = forecast_base.current_30d(rows, "", item_ids=items, days=env.window_days)
        env._current_cache[key] = cached
    return cached


def known_days(base: FunnelBase) -> Decimal:
    """The days a per-day figure of ``base`` divides by: the days with order data."""
    return Decimal(base.days if 0 < base.days < base.window_days else base.window_days)


def gmv_30d(env: RecoEnv, item_ids: Iterable[str] | None = None) -> Decimal | None:
    base = current_30d(env, item_ids)
    return None if base is None else base.total("gmv")


def orders_30d(env: RecoEnv, item_ids: Iterable[str] | None = None) -> Decimal | None:
    base = current_30d(env, item_ids)
    return None if base is None else base.total("orders")


def of_orders(
    env: RecoEnv, item_ids: Sequence[str] | None, part: int, total: int
) -> tuple[int, int]:
    """``part`` of ``total`` orders counted on the order lines, as a part of hiện tại's đơn (the
    share is the lines', the total is the one every surface shows)."""
    now = orders_30d(env, item_ids)
    if not now or total <= 0:
        return part, total
    n = int(now)
    return int((Decimal(part) / Decimal(total) * n).to_integral_value()), n


__all__ = ["current_30d", "gmv_30d", "known_days", "of_orders", "orders_30d", "rows_of"]
