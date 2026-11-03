"""Pieces several builders share: flow tables as JSON, five numbers as JSON, snapshots."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import num, pct, pct_of, ratio
from juli_backend.services.shopee_profit.five_numbers import (
    FiveNumbers,
    Snapshot,
    five_numbers,
    snapshot_from,
)
from juli_backend.services.shopee_profit.flows import FlowMetrics, FlowTable
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.sources import CellStats


def snapshot_of(view: PeriodView, product_id: str | None = None) -> Snapshot:
    """The window's period figures (order-line based) for the five numbers; with
    ``product_id`` only that product's lines and its own ads-report spend."""
    if product_id is None:
        return snapshot_from(
            view.pairs,
            view.ads.total_spend,
            days=Decimal(view.window.days),
            ad_spend_covered=view.profit.covered_ad_charge,
        )
    pairs = [(ln, pb) for ln, pb in view.pairs if ln.product_id == product_id]
    return snapshot_from(
        pairs,
        view.ads.product_spend.get(product_id, ZERO),
        days=Decimal(view.window.days),
    )


def flow_json(row: FlowMetrics, total_gmv: Decimal | None) -> dict[str, Any]:
    gmv_id = row.gmv_by_identity()
    return {
        "key": row.key,
        "label": row.label,
        "is_residual": row.is_residual,
        "views": row.views,
        "clicks": row.clicks,
        "orders": row.orders,
        "gmv": num(row.gmv),
        "ctr": ratio(row.ctr),
        "ctor": ratio(row.ctor),
        "aov": num(row.aov),
        "share_pct": pct_of(safe_div(row.gmv, total_gmv)) if total_gmv else None,
        "identity_gmv": num(gmv_id),
        "identity_ok": gmv_id is None or abs(gmv_id - row.gmv) < Decimal("0.01"),
    }


def flow_table_json(table: FlowTable) -> dict[str, Any]:
    rows = [flow_json(r, table.total_gmv) for r in table.rows]
    return {
        "rows": rows,
        "total_gmv": num(table.total_gmv),
        "total_orders": table.total_orders,
        "gmv_sum": num(table.gmv_sum),
        "orders_sum": table.orders_sum,
        "adds_up": table.total_gmv is None or table.gmv_sum == table.total_gmv,
        "has_residual": table.residual is not None,
    }


def cell_json(cell: CellStats | None) -> dict[str, Any]:
    cell = cell or CellStats()
    return {
        "orders": cell.orders,
        "gmv": num(cell.gmv),
        "net_revenue": num(cell.buyer_paid),
        "contribution": num(cell.contribution),
        "profit": num(cell.profit),
        "margin_pct": pct(cell.margin_pct),
        "aov": num(cell.aov),
        "orders_missing_profit": cell.orders_missing_profit,
        "orders_excluded": cell.orders_excluded,
    }


def five_json(f: FiveNumbers, *, comparable: bool = True) -> dict[str, Any]:
    """``comparable`` False = the previous period has no order lines: the "after" side is shown
    and every difference to the previous period is withheld (never a delta against nothing)."""
    cap = f.spend_cap
    out = _five_json(f)
    out["comparison"] = {
        "available": comparable,
        "reason": None if comparable else "no_order_lines_in_previous_period",
    }
    if not comparable:
        out["extra_revenue_per_extra_spend"].update(
            {
                "extra_revenue": None,
                "extra_spend": None,
                "per_vnd": None,
                "pct": None,
                "status": "undefined",
                "below_one": False,
            }
        )
        out["discount"].update({"vnd_before": None, "pct_before": None})
        out["margin"].update({"profit_before": None, "pct_before": None})
        out["orders"].update({"before": None, "change_pct": None})
        out["aov"].update({"before": None, "change_pct": None})
    del cap
    return out


def _five_json(f: FiveNumbers) -> dict[str, Any]:
    cap = f.spend_cap
    return {
        "discount": {
            "vnd_before": num(f.discount.vnd_before),
            "vnd_after": num(f.discount.vnd_after),
            "pct_before": pct(f.discount.pct_before),
            "pct_after": pct(f.discount.pct_after),
        },
        "extra_revenue_per_extra_spend": {
            "extra_revenue": num(f.extra_revenue),
            "extra_spend": num(f.extra_spend),
            "per_vnd": ratio(f.extra_revenue_per_extra_spend, 2),
            "pct": pct(f.extra_revenue_pct),
            "status": f.chi_status,
            "below_one": f.below_one,
        },
        "margin": {
            "profit_before": num(f.margin.vnd_before),
            "profit_after": num(f.margin.vnd_after),
            "pct_before": pct(f.margin.pct_before),
            "pct_after": pct(f.margin.pct_after),
            "is_partial": f.margin_is_partial,
            "cost_coverage_pct": pct(f.cost_coverage_pct),
        },
        "orders": {
            "before": num(f.orders[0]),
            "after": num(f.orders[1]),
            "change_pct": pct(f.orders[2]),
        },
        "aov": {
            "before": num(f.aov.vnd_before),
            "after": num(f.aov.vnd_after),
            "change_pct": pct(f.aov_change_pct),
        },
        "spend_cap": None
        if cap is None
        else {
            "spend_per_day": num(cap.spend),
            "cap": num(cap.cap),
            "remaining": num(cap.remaining),
            "used_pct": pct(cap.used_pct),
            "over_cap": cap.over_cap,
        },
        "chi_definition": "chi = quảng cáo + voucher + khuyến mãi + combo + hoa hồng",
    }


def five_for(
    now: PeriodView,
    before: PeriodView,
    cap: Decimal | None = None,
    product_id: str | None = None,
) -> FiveNumbers:
    return five_numbers(
        snapshot_of(before, product_id), snapshot_of(now, product_id), spend_cap=cap
    )
