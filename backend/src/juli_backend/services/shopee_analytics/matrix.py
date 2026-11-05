"""Product x source matrix (Tổng quan, Xếp hạng): per product its traffic flows, its price levers
and the ads overlay, all for one window.

Traffic flows come from aggregates (the item x source export / connector), price levers from
order lines, and ads from the ads report (placed orders, "trong đó"). The three are different
bases and are never mixed into one total: each block states its own basis.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ADS_BASIS, ADS_BASIS_NOTE, num, pct, ratio
from juli_backend.services.shopee_analytics.loaders import product_totals_for
from juli_backend.services.shopee_analytics.overview import CHILD_LABELS, LEVER_LABELS
from juli_backend.services.shopee_analytics.shared import (
    cell_json,
    excluded_summary,
    five_for,
    five_json,
    flow_table_json,
)
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


def card_children(view: PeriodView, product_id: str) -> list[dict[str, Any]] | None:
    """Thẻ sản phẩm split by where the card was seen (search, recommend, cart ...) for one
    product; None when the daily per-source rows (``item_traffic_sources``) are not stored."""
    kids = view.data.product_flows.children.get(product_id)
    if not kids:
        return None
    rows = []
    for key, agg in kids.items():
        rows.append(
            {
                "key": key,
                "label": CHILD_LABELS.get(key, key),
                "views": None if agg.views is None else int(agg.views),
                "clicks": None if agg.clicks is None else int(agg.clicks),
                "orders": int(agg.orders),
                "gmv": num(agg.gmv),
            }
        )
    return rows


def short_five(now: PeriodView, before: PeriodView, product_id: str) -> dict[str, Any]:
    """The matrix's per-product numbers (1) % giảm giá and (2) thu thêm / chi thêm against the
    previous period; withheld, not zero, when the previous period has no order lines."""
    comparable = before.comparable_as_previous
    full = five_json(five_for(now, before, None, product_id), comparable=comparable)
    return {
        "discount": full["discount"],
        "extra_revenue_per_extra_spend": full["extra_revenue_per_extra_spend"],
        "comparison": full["comparison"],
    }


BASIS_ACTUAL = "theo đơn thực tế"
BASIS_ESTIMATE = "ước tính"
BASIS_UNKNOWN = "chưa tính"


def price_block(view: PeriodView, product_id: str) -> dict[str, Any]:
    """P92 B-9: selling price min-max (paid per unit in the window; the catalogue's current price
    when nothing sold) and the list price (the web strikes it through when it differs)."""
    pairs = getattr(view, "pairs", [])
    lines = [ln for ln, _ in pairs if ln.product_id == product_id]
    current, listed = getattr(view, "item_prices", {}).get(product_id, (None, None))
    basis: str | None
    if lines:
        sell = [ln.deal_price for ln in lines]
        lo, hi = min(sell), max(sell)
        list_price = max(ln.original_price for ln in lines)
        basis = "order_lines"
    else:
        lo = hi = current if current is not None else listed
        list_price = listed
        basis = "catalogue" if lo is not None else None
    return {
        "price_min": num(lo),
        "price_max": num(hi),
        "list_price": num(list_price),
        "price_basis": basis,
    }


def margin_basis(view: PeriodView, product_id: str, pp: ProductProfit | None) -> str:
    """Basis of the biên: "theo đơn thực tế" when every order has an Income row and a giá vốn,
    "ước tính" when the fee formula or an assumed cost stands in, "chưa tính" without a margin."""
    if pp is None or pp.margin_pct is None:
        return BASIS_UNKNOWN
    pairs = [(ln, b) for ln, b in getattr(view, "pairs", []) if ln.product_id == product_id]
    if any(not view.costs.cogs_is_real(ln.sku) for ln, _ in pairs):
        return BASIS_ESTIMATE
    if any(ln.income is None for ln, _ in pairs):
        return BASIS_ESTIMATE
    return BASIS_ACTUAL


def product_row(view: PeriodView, product_id: str) -> dict[str, Any]:
    pp = view.profit.products.get(product_id)
    levers = []
    for lever in PriceLever:
        cell = view.matrix.lever.get((product_id, lever.value))
        levers.append({"key": lever.value, "label": LEVER_LABELS[lever.value], **cell_json(cell)})
    total = view.matrix.totals.get(product_id)
    flows = view.flows.products.get(product_id) if view.flows else None
    pf = view.data.product_flows
    shopee_total = product_totals_for(pf, view.data.lines).get(product_id)
    gmv = shopee_total[0] if shopee_total else (total.gmv if total else None)
    return {
        "product_id": product_id,
        "name": view.names.get(product_id) or product_id,
        "gmv": num(gmv),
        "gmv_basis": "shopee_product_period" if shopee_total else "order_lines",
        "orders": shopee_total[1] if shopee_total else (total.orders if total else None),
        "line_gmv": num(total.gmv if total else None),
        "line_orders": total.orders if total else 0,
        **price_block(view, product_id),
        "margin_basis": margin_basis(view, product_id, pp),
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
        "card_children": card_children(view, product_id),
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
    view: PeriodView,
    *,
    sort: str = "gmv",
    limit: int | None = None,
    before: PeriodView | None = None,
) -> dict[str, Any]:
    ids = (
        set(view.matrix.totals) | set(view.data.product_flows.totals) | set(view.ads.product_spend)
    ) - set(view.excluded)
    rows = [product_row(view, pid) for pid in ids]
    rows = [r for r in rows if (r["gmv"] or 0) > 0 or r["ads"]["spend"]]
    rows.sort(key=lambda r: _sort_key(sort, r))
    total = len(rows)
    sold = {r["product_id"] for r in rows}
    idle = [
        {
            "product_id": i,
            "name": name,
            **price_block(view, i),
            "margin_basis": BASIS_UNKNOWN,
        }
        for i, name in sorted(getattr(view, "active_items", {}).items(), key=lambda kv: kv[1])
        if i not in sold
    ]
    sum_gmv = sum((Decimal(str(r["gmv"] or 0)) for r in rows), ZERO)
    if limit is not None:
        rows = rows[:limit]
    if before is not None:
        for r in rows:
            r["five_numbers"] = short_five(view, before, r["product_id"])
    return {
        "platform": "shopee",
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "window": view.window.json(),
        "sort": sort,
        "products": rows,
        "product_count": total,
        "idle_products": idle,
        "ads_basis": ADS_BASIS,
        "excluded": excluded_summary(view),
        "sums": {
            "gmv_shopee_products": num(sum_gmv),
            "gmv_shop": num(view.shop_gmv),
            "note": "Σ GMV sản phẩm khớp Doanh số shop khi file sản phẩm đúng kỳ (không thì lấy từ "
            "dòng đơn hàng); phần lệch hiện "
            "ở dòng Chênh lệch nguồn.",
        },
    }


__all__ = ["SORTS", "ads_overlay", "build_matrix", "product_row"]
