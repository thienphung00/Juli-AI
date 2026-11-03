"""Product x source matrix (Tổng quan, Xếp hạng): per product its traffic flows, its price levers
and the ads overlay, all for one window.

Traffic flows come from aggregates (the item x source export / connector), price levers from
order lines, and ads from the ads report (placed orders, "trong đó"). The three are different
bases and are never mixed into one total: each block states its own basis.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ADS_BASIS, ADS_BASIS_NOTE, num, pct, ratio
from juli_backend.services.shopee_analytics.overview import LEVER_LABELS
from juli_backend.services.shopee_analytics.shared import cell_json, flow_table_json
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.shop_profit import ProductProfit
from juli_backend.services.shopee_profit.sources import PriceLever

SORTS = ("gmv", "bien", "orders", "profit")


def ads_overlay(
    view: PeriodView, product_id: str, pp: ProductProfit | None = None
) -> dict[str, Any]:
    spend = view.ads.product_spend.get(product_id)
    fig = view.ads.product_figures.get(product_id)
    pp = pp or view.profit.products.get(product_id)
    return {
        "basis": ADS_BASIS,
        "note": ADS_BASIS_NOTE,
        "spend": num(spend),
        "gmv_placed": num(fig.gmv if fig else None),
        "direct_gmv_placed": num(fig.direct_gmv if fig else None),
        "roas_broad": ratio(fig.roas_broad if fig else None, 2),
        "roas_direct": ratio(fig.roas_direct if fig else None, 2),
        "break_even_roas": ratio(pp.break_even_roas if pp else None, 2),
        "below_break_even": pp.ads_below_break_even if pp else None,
    }


def product_row(view: PeriodView, product_id: str) -> dict[str, Any]:
    pp = view.profit.products.get(product_id)
    levers = []
    for lever in PriceLever:
        cell = view.matrix.lever.get((product_id, lever.value))
        levers.append({"key": lever.value, "label": LEVER_LABELS[lever.value], **cell_json(cell)})
    total = view.matrix.totals.get(product_id)
    flows = view.flows.products.get(product_id) if view.flows else None
    pf = view.data.product_flows
    shopee_total = pf.totals.get(product_id)
    gmv = shopee_total[0] if shopee_total else (total.gmv if total else None)
    return {
        "product_id": product_id,
        "name": view.names.get(product_id) or product_id,
        "gmv": num(gmv),
        "gmv_basis": "shopee_product_period" if shopee_total else "order_lines",
        "orders": shopee_total[1] if shopee_total else (total.orders if total else None),
        "line_gmv": num(total.gmv if total else None),
        "line_orders": total.orders if total else 0,
        "profit": None
        if pp is None
        else {
            "profit": num(pp.profit),
            "margin_pct": pct(pp.margin_pct),
            "contribution": num(pp.contribution),
            "net_revenue": num(pp.buyer_paid),
            "ad_spend": num(pp.ad_spend),
            "break_even_roas": ratio(pp.break_even_roas, 2),
            "cost_coverage_pct": pct(pp.cost_coverage_pct),
            "assumed_cost": any(
                not view.costs.cogs_is_real(ln.sku)
                for ln, _ in view.pairs
                if ln.product_id == product_id
            ),
        },
        "flows": None
        if flows is None
        else {
            **flow_table_json(flows),
            "trang_shop_available": pf.trang_shop_split,
            "basis": pf.flows_basis.json(),
        },
        "levers": levers,
        "ads": ads_overlay(view, product_id, pp),
    }


def _sort_key(sort: str, row: dict[str, Any]) -> float:
    if sort == "bien":
        m = (row["profit"] or {}).get("margin_pct")
        return m if m is not None else 1e9  # lowest margin first, unknown last
    if sort == "orders":
        return -(row["orders"] or 0)
    if sort == "profit":
        p = (row["profit"] or {}).get("profit")
        return -(p if p is not None else -1e18)
    return -(row["gmv"] or 0)


def build_matrix(
    view: PeriodView, *, sort: str = "gmv", limit: int | None = None
) -> dict[str, Any]:
    ids = (
        set(view.matrix.totals) | set(view.data.product_flows.totals) | set(view.ads.product_spend)
    )
    rows = [product_row(view, pid) for pid in ids]
    rows = [r for r in rows if (r["gmv"] or 0) > 0 or r["ads"]["spend"]]
    rows.sort(key=lambda r: _sort_key(sort, r))
    total = len(rows)
    if limit is not None:
        rows = rows[:limit]
    return {
        "platform": "shopee",
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "window": view.window.json(),
        "sort": sort,
        "products": rows,
        "product_count": total,
        "ads_basis": ADS_BASIS,
        "sums": {
            "gmv_shopee_products": num(
                sum((g for g, _ in view.data.product_flows.totals.values()), ZERO)
            ),
            "gmv_shop": num(view.shop_gmv),
            "note": "Σ GMV sản phẩm khớp Doanh số shop khi file sản phẩm đúng kỳ; phần lệch hiện ở dòng Chênh lệch nguồn.",  # noqa: E501
        },
    }


__all__ = ["SORTS", "ads_overlay", "build_matrix", "product_row"]
