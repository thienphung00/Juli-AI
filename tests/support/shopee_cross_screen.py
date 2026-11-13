"""P98 / ADR-122 d.11.2 + d.14: the one number, read from every screen of a Shopee shop.

``collect`` reads Tổng quan, Phân tích, Sản phẩm, the Kế hoạch base and the builder "before" for the
same shop, scope and 30-day window and returns each screen's Lượt xem, CTR, CTOR, Đơn, AOV, GMV and
Lợi nhuận. Used by the SQLite unit test and the Postgres integration test. Synthetic shop only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import funnel, queries
from juli_backend.services.shopee_analytics.windows import resolve_window
from juli_backend.services.shopee_recommendations import plan_base
from juli_backend.services.shopee_recommendations.loader import load_env

FIELDS = ("views", "ctr", "ctor", "orders", "aov", "gmv", "profit")


@dataclass(frozen=True)
class Surface:
    name: str
    values: dict[str, float | None]


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


async def collect_shop(
    session: AsyncSession, shop_id: uuid.UUID, as_of: Any, *, days: int = 30
) -> tuple[list[Surface], dict[str, float | None]]:
    """The shop scope, the ``days`` (7 or 30) ending ``as_of``. The Kế hoạch base reads
    ``config.HISTORY_DAYS`` days: the caller sets it to ``days`` (the Tổng quan anchor window).
    Returns the screens and, apart, the two waterfall profits (Tổng quan's block, Phân tích)."""
    kw: dict[str, Any] = {"period": f"{days}d", "as_of": as_of}
    ov = await queries.overview(session, shop_id, **kw)
    sm, strip = ov["shop_metrics"], ov["kpi_strip"]
    tong_quan = {
        "views": strip["views"]["value"],
        "ctr": strip["ctr"]["value"],
        "ctor": strip["ctor"]["value"],
        "orders": strip["orders"]["value"],
        "aov": strip["aov"]["value"],
        "gmv": strip["gmv"]["value"],
        "profit": sm["profit"],  # P100 B.5: the one known-cost shop profit
    }
    profit_block = ov["profit"]["profit_vnd"]  # the profit block's headline (d.14: ShopMetrics)

    async def cell(xep: str) -> Any:
        body = await queries.ranking(session, shop_id, xep_theo=xep, **kw)
        return body["cell"]["now"]

    views_per_day = await cell("views")
    gmv_per_day = await cell("gmv_per_day")
    profit_per_day = await cell("profit_per_day")
    phan_tich = {
        "views": None if views_per_day is None else views_per_day * days,
        "ctr": await cell("ctr"),
        "ctor": await cell("ctor"),
        "orders": None,  # Phân tích ranks no đơn measure
        "aov": await cell("aov"),
        "gmv": None if gmv_per_day is None else gmv_per_day * days,
        "profit": None,  # the ranking's profit is the waterfall's, see ``waterfalls``
    }
    waterfalls = {
        "tong_quan_block": _f(profit_block),
        "phan_tich_ranking": None if profit_per_day is None else float(profit_per_day) * days,
    }

    mx = await queries.matrix(session, shop_id, **kw)
    window = resolve_window(f"{days}d", as_of=as_of)
    headline = await queries.window_metrics(session, shop_id, start=window.start, end=window.end)
    assert headline is not None
    hm = headline[0]
    san_pham = {
        "views": hm["views"],
        "ctr": hm["ctr"],
        "ctor": hm["ctor"],
        "orders": hm["orders"],
        "aov": hm["aov"],
        "gmv": mx["sums"]["gmv_shop"],
        "profit": hm["profit"],
    }

    env = await load_env(session, shop_id, as_of=as_of)
    assert env is not None
    rows = await funnel.load_rows(session, shop_id, env.view.window)
    base = plan_base.base_json(env, rows)
    ke_hoach = {
        "views": base["views"],
        "ctr": base["ctr"],
        "ctor": base["ctor"],
        "orders": base["orders_30d"],
        "aov": base["aov"],
        "gmv": base["gmv_30d"],
        "profit": base["profit_30d"],  # P100 B.5: the one known-cost shop profit
    }

    fb = await funnel.load_funnel_base(session, shop_id, window=window)
    n = funnel.numbers(fb, sm["orders"])
    orders, gmv = fb.total("orders"), fb.total("gmv")
    builder = {
        "views": n.views,
        "ctr": n.ctr,
        "ctor": n.ctor,
        "orders": orders,
        "aov": None if not orders or gmv is None else gmv / orders,
        "gmv": gmv,
        # P99: the base sums only the days with giá vốn ("trên N ngày có dữ liệu chi phí"); it
        # is the window's profit only when every day has one
        "profit": fb.total("profit") if fb.profit_days == fb.days else None,
    }
    surfaces = [
        Surface(name, {k: _f(v) for k, v in vals.items()})
        for name, vals in (
            ("tong_quan", tong_quan),
            ("phan_tich", phan_tich),
            ("san_pham", san_pham),
            ("ke_hoach", ke_hoach),
            ("builder_before", builder),
        )
    ]
    return surfaces, waterfalls


def agreed(
    surfaces: list[Surface], field: str, *, tol: float, abs_tol: float = 0.0
) -> dict[str, float | None]:
    """The field's value per screen that shows it; raises AssertionError listing the gap. The gap
    must be within ``tol`` of the largest value or ``abs_tol`` (for a ratio a screen rounds)."""
    got: dict[str, float | None] = {}
    for s in surfaces:
        value = s.values[field]
        if value is not None:
            got[s.name] = float(value)
    shown = [v for v in got.values() if v is not None]
    if shown:
        lo, hi = min(shown), max(shown)
        scale = max(abs(hi), abs(lo), 1e-9)
        gap = hi - lo
        assert gap <= tol * scale or gap <= abs_tol, f"{field} differs across screens: {got}"
    return got


__all__ = ["FIELDS", "Surface", "agreed", "collect_shop"]
