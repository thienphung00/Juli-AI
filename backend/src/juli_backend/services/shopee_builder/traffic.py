"""Orders and clicks of a scope over the history window, for CTOR (orders / clicks).

CTOR is conversion everywhere in the app (P92 B-3). The break-even of a change is shown as extra
orders AND as the CTOR that many orders would take: ``(orders + extra) / clicks``, on the same
clicks. Clicks come from the per-source flow tables (Thẻ sản phẩm, Trang shop, Video ...) of the
shop or of the product; a scope without flow rows has no CTOR ("chưa có lượt bấm").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from juli_backend.services.shopee_recommendations.env import RecoEnv


@dataclass(frozen=True)
class Traffic:
    orders: int
    clicks: int
    views: int
    window_days: int

    @property
    def ctor(self) -> float | None:
        return self.orders / self.clicks if self.clicks > 0 else None

    @property
    def ctr(self) -> float | None:
        return self.clicks / self.views if self.views > 0 else None

    def pace(self, days: int) -> tuple[float, float]:
        """``(orders, clicks)`` the same pace gives over ``days`` days."""
        f = days / self.window_days
        return self.orders * f, self.clicks * f


def scope_traffic(env: RecoEnv, items: Sequence[str]) -> Traffic | None:
    """Orders / clicks / views of the products (or the shop when ``items`` is empty) over the
    window, or ``None`` when the flow tables are not stored."""
    flows = env.view.flows
    if flows is None:
        return None
    tables = (
        [flows.shop]
        if not items
        else [t for i in dict.fromkeys(items) if (t := flows.products.get(i)) is not None]
    )
    rows = [r for t in tables if t is not None for r in t.rows if not r.is_residual]
    if not rows:
        return None
    return Traffic(
        orders=int(sum(r.orders for r in rows)),
        clicks=int(sum((r.clicks or 0) for r in rows)),
        views=int(sum((r.views or 0) for r in rows)),
        window_days=env.window_days,
    )


def break_even_ctor(
    traffic: Traffic | None, extra_orders: int | None, period_days: int
) -> dict[str, Any]:
    """``ctor_now`` and the CTOR that ``extra_orders`` more orders over ``period_days`` take."""
    if traffic is None:
        return {"ctor_now": None, "ctor_needed": None, "reason": "no_flow_data"}
    orders, clicks = traffic.pace(period_days)
    if clicks <= 0:
        return {"ctor_now": None, "ctor_needed": None, "reason": "no_clicks"}
    now = traffic.ctor
    needed = None if extra_orders is None else (orders + extra_orders) / clicks
    return {
        "ctor_now": None if now is None else round(now * 100, 3),
        "ctor_needed": None if needed is None else round(needed * 100, 3),
        "orders_base": round(orders, 1),
        "clicks_base": round(clicks),
        "reason": None,
    }


__all__ = ["Traffic", "break_even_ctor", "scope_traffic"]
