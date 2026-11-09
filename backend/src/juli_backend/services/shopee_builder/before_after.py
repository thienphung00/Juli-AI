"""So sánh phương án: before -> after with its range for seven metrics (P97 D85.9).

GMV, biên lợi nhuận, số đơn, AOV, CTOR, CTR, lượt xem -- each ``before`` (the base the version
stands on: the shop for a shop-wide lever, the product(s) otherwise; the window ShopMetrics
reads) and ``after`` as ``{low, p50, high}`` = P10 / P50 / P90. A metric the lever has no
modelled effect on is ``unchanged`` with the reason in Vietnamese -- never an invented lift:

- the money layer (``predicted.money_per_month``) moves GMV and đơn; AOV is GMV ÷ đơn on the same
  quantile; the margin follows profit and GMV;
- the lift's own metric (``predicted.lift.metric``) says which funnel metric the model scales:
  ``aov`` -> AOV only; ``ctor`` / ``orders`` -> đơn and CTOR (orders ÷ clicks); ``views`` -> lượt
  xem; ``ctr`` -> CTR; ``none`` / ads -> none of them.

Pure over a built card and the builder context; no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.traffic import scope_traffic
from juli_backend.services.shopee_recommendations import config

ROWS: tuple[tuple[str, str, str], ...] = (
    ("gmv", "GMV", "vnd"),
    ("margin", "Biên lợi nhuận", "pct"),
    ("orders", "Số đơn", "count"),
    ("aov", "AOV", "vnd"),
    ("ctor", "CTOR", "pct"),
    ("ctr", "CTR", "pct"),
    ("views", "Lượt xem", "count"),
)
#: lift metric -> the funnel metrics the model scales
MOVES: dict[str, frozenset[str]] = {
    "aov": frozenset({"aov"}),
    "ctor": frozenset({"orders", "ctor"}),
    "orders": frozenset({"orders", "ctor"}),
    "views": frozenset({"views"}),
    "ctr": frozenset({"ctr"}),
}
LEVER_NAME = {
    "aov": "tăng giá trị mỗi đơn",
    "ctor": "tăng tỉ lệ đặt hàng",
    "orders": "tăng tỉ lệ đặt hàng",
    "views": "tăng lượt xem",
    "ctr": "tăng tỉ lệ nhấp",
}
NO_DATA = "Chưa đủ dữ liệu để ước tính."


def _band(values: Sequence[float | None]) -> dict[str, float | None]:
    if any(v is None for v in values):
        return {"low": None, "p50": None, "high": None}
    lo, mid, hi = sorted(float(v) for v in values if v is not None)
    # the median is the P50 value, not the middle of the sorted three
    return {"low": lo, "p50": float(values[1]) if values[1] is not None else mid, "high": hi}


def _row(key: str, label: str, unit: str, before: float | None, after: Mapping[str, Any] | None,
         reason: str | None = None, *, unchanged: bool = False) -> dict[str, Any]:  # fmt: skip
    return {
        "key": key,
        "label": label,
        "unit": unit,
        "before": before,
        "after": after,
        "unchanged": unchanged,
        "reason": reason,
    }


def _unchanged(
    key: str, label: str, unit: str, before: float | None, reason: str
) -> dict[str, Any]:
    flat = None if before is None else {"low": before, "p50": before, "high": before}
    return _row(key, label, unit, before, flat, reason, unchanged=True)


def _shop_base(ctx: BuilderContext, items: Sequence[str], shop_wide: bool) -> dict[str, Any]:
    """gmv / orders / profit / paid of the base, over the history window."""
    env = ctx.env
    m = env.metrics
    if shop_wide or not items:
        p = env.view.profit
        return {
            "scope": "shop",
            "gmv": float(m.gmv or 0),
            "orders": float(m.orders or 0),
            "profit": None if p.covered_margin_profit is None else float(p.covered_margin_profit),
            "paid": float(p.buyer_paid_covered),
        }
    gmv = orders = profit = paid = 0.0
    known = False
    for item in dict.fromkeys(items):
        s = m.split(item)
        if s is not None:
            gmv += float(s.gmv)
            orders += float(s.orders)
        pp = env.product(item)
        if pp is not None and pp.profit is not None and pp.buyer_paid_covered > 0:
            profit += float(pp.profit)
            paid += float(pp.buyer_paid_covered)
            known = True
    return {
        "scope": "product",
        "gmv": gmv,
        "orders": orders,
        "profit": profit if known else None,
        "paid": paid,
    }


def build(
    numbers: Mapping[str, Any],
    ctx: BuilderContext,
    items: Sequence[str],
    *,
    shop_wide: bool,
    basis_known: bool,
    cost_known: bool,
    orders_note: str | None,
) -> dict[str, Any]:
    """The seven rows of one version; ``numbers`` is the card whose money layer it shows."""
    env = ctx.env
    base = _shop_base(ctx, items, shop_wide)
    f = env.window_days / config.DAYS_PER_MONTH  # the card's month -> the history window
    total = numbers["predicted"]["money_per_month"]["total"]
    lift = numbers["predicted"]["lift"]
    metric = lift["metric"]
    moves = MOVES.get(metric, frozenset())
    scale = float(numbers["predicted"].get("lift_scale") or 1.0)
    traffic = scope_traffic(env, [] if base["scope"] == "shop" else items)
    gmv0, orders0 = base["gmv"], base["orders"]
    qs = ("p10", "p50", "p90")

    def d(key: str, q: str) -> float | None:
        v = total[q][key]
        return None if v is None else float(v) * f

    def dq(key: str, q: str) -> float:
        return d(key, q) or 0.0

    rows: list[dict[str, Any]] = []
    aov0 = gmv0 / orders0 if orders0 else None
    margin0 = (
        base["profit"] / base["paid"] * 100
        if base["profit"] is not None and base["paid"] > 0 and cost_known
        else None
    )
    if not basis_known:
        for key, label, unit in ROWS:
            before = {"gmv": gmv0, "orders": orders0, "aov": aov0, "margin": margin0}.get(key)
            rows.append(_row(key, label, unit, before, None, NO_DATA))
        return _wrap(base, rows)

    def after(fn: Any) -> dict[str, float | None]:
        out: list[float | None] = []
        for q in qs:
            try:
                out.append(fn(q))
            except (ZeroDivisionError, TypeError):
                out.append(None)
        return _band(out)

    rows.append(_row("gmv", "GMV", "vnd", gmv0, after(lambda q: gmv0 + (d("dgmv", q) or 0.0))))
    if margin0 is None:
        rows.append(
            _row("margin", "Biên lợi nhuận", "pct", None, None, "Chưa có giá vốn: biên chưa tính.")
        )
    else:
        ratio = base["paid"] / gmv0 if gmv0 else 0.0

        def margin(q: str) -> float | None:
            dp, dg = d("dprofit", q), d("dgmv", q)
            if dp is None or dg is None:
                return None
            return (base["profit"] + dp) / (base["paid"] + dg * ratio) * 100

        rows.append(_row("margin", "Biên lợi nhuận", "pct", margin0, after(margin)))
    if "orders" in moves:
        rows.append(
            _row(
                "orders",
                "Số đơn",
                "count",
                orders0,
                after(lambda q: orders0 + (d("dorders", q) or 0.0)),
            )
        )
    else:
        why = orders_note or _no_effect("orders", metric)
        rows.append(_unchanged("orders", "Số đơn", "count", orders0, why))
    if "aov" in moves or "orders" in moves:
        more = "orders" in moves

        def aov_after(q: str) -> float:
            return (gmv0 + dq("dgmv", q)) / (orders0 + (dq("dorders", q) if more else 0.0))

        rows.append(_row("aov", "AOV", "vnd", aov0, after(aov_after)))
    else:
        rows.append(_unchanged("aov", "AOV", "vnd", aov0, _no_effect("aov", metric)))
    clicks0 = None if traffic is None else float(traffic.clicks)
    ctor0 = None if traffic is None or traffic.ctor is None else traffic.ctor * 100
    ctr0 = None if traffic is None or traffic.ctr is None else traffic.ctr * 100
    views0 = None if traffic is None or not traffic.views else float(traffic.views)
    if "ctor" in moves and clicks0 and traffic is not None:
        t_orders = float(traffic.orders)

        def ctor_after(q: str) -> float:
            return (t_orders + dq("dorders", q)) / clicks0 * 100

        rows.append(_row("ctor", "CTOR", "pct", ctor0, after(ctor_after)))
    elif "ctor" in moves:
        rows.append(
            _row("ctor", "CTOR", "pct", None, None, "Chưa có lượt nhấp theo nguồn để tính CTOR.")
        )
    else:
        rows.append(_unchanged("ctor", "CTOR", "pct", ctor0, _no_effect("ctor", metric)))
    if "ctr" in moves and ctr0 is not None:
        rows.append(
            _row("ctr", "CTR", "pct", ctr0, after(lambda q: ctr0 * _lifted(lift, q, scale)))
        )
    elif "ctr" in moves:
        rows.append(
            _row("ctr", "CTR", "pct", None, None, "Chưa có lượt xem và lượt nhấp để tính CTR.")
        )
    else:
        rows.append(_unchanged("ctr", "CTR", "pct", ctr0, _no_effect("ctr", metric)))
    if "views" in moves and views0 is not None:
        rows.append(
            _row(
                "views",
                "Lượt xem",
                "count",
                views0,
                after(lambda q: views0 * _lifted(lift, q, scale)),
            )
        )
    elif "views" in moves:
        rows.append(_row("views", "Lượt xem", "count", None, None, "Chưa có lượt xem theo nguồn."))
    else:
        rows.append(_unchanged("views", "Lượt xem", "count", views0, _no_effect("views", metric)))
    return _wrap(base, rows)


def _lifted(lift: Mapping[str, Any], q: str, scale: float) -> float:
    """1 + the lift at quantile ``q``, scaled by the change's size."""
    return 1 + float(lift["lift"][q]) * scale


def _no_effect(key: str, metric: str) -> str:
    """Why a metric stays put: what the lever does move, and that the rest is not modelled."""
    name = LEVER_NAME.get(metric)
    if name is None:
        return "Mô hình không dự kiến thay đổi chỉ số này cho đòn bẩy này (không bịa mức tăng)."
    return (
        f"Đòn bẩy này {name}; mô hình không dự kiến thay đổi "
        f"{dict((k, lbl) for k, lbl, _ in ROWS)[key]} (không bịa mức tăng)."
    )


def _wrap(base: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "scope": base["scope"],
        "rows": rows,
        "range": "P10 – P90, giữa là P50",
        "note": "Trước = số liệu 30 ngày gần nhất của cùng phạm vi; sau = trước cộng thay đổi dự "
        "kiến. Chỉ số mô hình không ước tính được ghi “không đổi” kèm lý do.",
    }


__all__ = ["ROWS", "build"]
