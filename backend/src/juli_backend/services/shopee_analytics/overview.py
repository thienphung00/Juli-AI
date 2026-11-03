"""Tổng quan: the shop in one payload (contract 2, 4, 5, 14).

Five flows that add up to the shop's Doanh số (with the "Chênh lệch nguồn" row when they do not),
the GMV chain identity, the four price levers, the five numbers against the previous period, shop
profit with real vs assumed cost coverage, ads as a labelled overlay ("trong đó", placed-orders
basis), vouchers and affiliate. Pure over two :class:`PeriodView`\\ s.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import (
    ADS_BASIS,
    ADS_BASIS_NOTE,
    ASSUMED_COST_LABEL,
    ORDER_BASIS,
    delta_pct,
    num,
    pct,
    pct_of,
    ratio,
)
from juli_backend.services.shopee_analytics.loaders import CARD_CHILDREN, ShopContext
from juli_backend.services.shopee_analytics.shared import (
    cell_json,
    five_for,
    five_json,
    flow_table_json,
)
from juli_backend.services.shopee_profit.flows import (
    FLOW_LABELS,
    Flow,
    FlowMetrics,
)
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.sources import CellStats, PriceLever

LEVER_LABELS: dict[str, str] = {
    PriceLever.KHONG_UU_DAI.value: "Không ưu đãi",
    PriceLever.VOUCHER.value: "Voucher shop",
    PriceLever.KHUYEN_MAI.value: "Khuyến mãi",
    PriceLever.COMBO.value: "Combo",
}
CHILD_LABELS: dict[str, str] = {
    "search": "Tìm kiếm",
    "recommend": "Đề xuất",
    "cart": "Giỏ hàng",
    "my_orders": "Đơn mua của tôi",
    "promo": "Khuyến mãi",
    "other": "Khác",
}


def _int_or_none(value: Decimal | None) -> int | None:
    return None if value is None else int(value)


def data_status(view: PeriodView) -> dict[str, Any]:
    d = view.data
    return {
        "shop_totals": {"basis": d.totals.basis, "days_covered": d.totals.days_covered},
        "traffic": {"basis": d.traffic.basis, "days_covered": d.traffic.days_covered},
        "ads_daily": {"days_covered": d.ads_daily.days_covered},
        "ads_report": d.ads_reports.campaign_choice.json(),
        "product_flows": {
            "source": d.product_flows.source,
            "basis": d.product_flows.flows_basis.json(),
            "trang_shop_split": d.product_flows.trang_shop_split,
        },
        "order_lines": {
            "lines": len(d.lines.lines),
            "days_with_orders": d.lines.days_with_orders,
            "window_days": d.window.days,
            "covers_window": d.lines.covers_window,
        },
    }


def warnings(view: PeriodView) -> list[dict[str, str]]:
    d, out = view.data, []

    def add(code: str, message: str) -> None:
        out.append({"code": code, "message": message})

    if not d.lines.covers_window:
        add(
            "order_lines_partial",
            "File đơn hàng chưa phủ hết kỳ: lợi nhuận, giảm giá và AOV chỉ tính trên các ngày có "
            "đơn.",
        )
    if d.totals.basis == "partial_daily":
        add("shop_totals_partial", "Doanh số shop chỉ có một phần số ngày trong kỳ.")
    if d.traffic.basis in ("partial_daily", "none"):
        add("traffic_partial", "Lưu lượng theo nguồn chưa đủ số ngày trong kỳ.")
    rec = view.profit.reconciliation
    if rec.warn:
        add("gmv_reconciliation", "Tổng GMV theo dòng đơn lệch hơn 2 % so với Doanh số của Shopee.")
    if not view.profit.ad_spend_consistent:
        add(
            "ad_spend_inconsistent",
            "Chi phí quảng cáo theo sản phẩm lớn hơn tổng chi phí chiến dịch.",
        )
    if view.ads.basis in ("report_prorated", "daily_only", "none"):
        add("ads_estimated", view.ads.label)
    if view.coverage.base > 0 and view.coverage.real == 0:
        add(
            "cost_all_assumed",
            f"Toàn bộ giá vốn là {ASSUMED_COST_LABEL}; hãy nhập giá vốn thật ở Cài đặt.",
        )
    return out


def _kpi(now: Decimal | int | None, before: Decimal | int | None) -> dict[str, Any]:
    a = None if now is None else Decimal(str(now))
    b = None if before is None else Decimal(str(before))
    return {"value": num(a), "previous": num(b), "change_pct": delta_pct(a, b)}


def _shop_chain(view: PeriodView) -> dict[str, Any]:
    table = view.flows.shop if view.flows else None
    if table is None:
        return {}
    flows = [r for r in table.rows if not r.is_residual]
    views = sum((r.views for r in flows if r.views is not None), 0)
    clicks = sum((r.clicks for r in flows if r.clicks is not None), 0)
    total = FlowMetrics(
        "shop",
        "Cả shop",
        views or None,
        clicks or None,
        table.total_orders or 0,
        table.total_gmv or ZERO,
    )
    identity = total.gmv_by_identity()
    return {
        "views": total.views,
        "clicks": total.clicks,
        "orders": total.orders,
        "ctr": ratio(total.ctr),
        "ctor": ratio(total.ctor),
        "aov": num(total.aov),
        "gmv": num(total.gmv),
        "identity_gmv": num(identity),
        "identity_ok": identity is None or abs(identity - total.gmv) < Decimal("0.01"),
        "note": "Lượt xem cộng các luồng (Live / Video đếm phiên / video); CTR không so giữa các "
        "luồng.",
    }


def _flows_block(view: PeriodView, prev: PeriodView) -> dict[str, Any]:
    if view.flows is None:
        return {"available": False}
    table = view.flows.shop
    block = flow_table_json(table)
    prev_rows = {r.key: r for r in prev.flows.shop.rows} if prev.flows else {}
    for row in block["rows"]:
        before = prev_rows.get(row["key"])
        row["gmv_previous"] = num(before.gmv) if before else None
        row["gmv_change_pct"] = delta_pct(
            Decimal(str(row["gmv"])) if row["gmv"] is not None else None,
            before.gmv if before else None,
        )
    card_total = next((r for r in table.rows if r.key == Flow.THE_SAN_PHAM_KHAC.value), None)
    kids = view.data.traffic.children
    children = [
        {
            "key": c,
            "label": CHILD_LABELS[c],
            "views": _int_or_none(kids[c].views),
            "clicks": _int_or_none(kids[c].clicks),
            "orders": int(kids[c].orders),
            "gmv": num(kids[c].gmv),
        }
        for c in CARD_CHILDREN
    ]
    child_gmv = sum((kids[c].gmv for c in CARD_CHILDREN), ZERO)
    block.update(
        {
            "available": True,
            "basis": view.data.traffic.basis,
            "labels": {k: v for k, v in FLOW_LABELS.items()},
            "the_san_pham_children": {
                "rows": children,
                "gmv_sum": num(child_gmv),
                "parent_gmv": num(card_total.gmv) if card_total else None,
                "note": "Sáu nguồn con là chi tiết của Thẻ sản phẩm (cộng cả Trang shop); không "
                "cộng vào tổng.",
            },
            "chain": _shop_chain(view),
        }
    )
    return block


def _levers_block(view: PeriodView) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    rows = []
    gmv_sum = ZERO
    for lever in PriceLever:
        cells = [c for (_, lv), c in view.matrix.lever.items() if lv == lever.value]
        agg = CellStats()
        for c in cells:
            agg = agg.plus(c)
        gmv_sum += agg.gmv
        rows.append({"key": lever.value, "label": LEVER_LABELS[lever.value], **cell_json(agg)})
    grand = view.line_gmv
    for r in rows:
        r["share_pct"] = pct_of(safe_div(Decimal(str(r["gmv"] or 0)), grand)) if grand else None
    totals["rows"] = rows
    totals["gmv_sum"] = num(gmv_sum)
    totals["gmv_total"] = num(grand)
    totals["adds_up"] = gmv_sum == grand
    totals["note"] = "Mỗi dòng đơn một ưu đãi: combo > khuyến mãi > voucher > không ưu đãi."
    return totals


def _profit_block(view: PeriodView) -> dict[str, Any]:
    p = view.profit
    cov = view.coverage
    return {
        "profit_vnd": num(p.profit),
        "profit_on_covered_vnd": num(p.profit_on_covered),
        "margin_pct": pct(p.margin_pct),
        "margin_basis": "profit ÷ doanh thu thực (sau voucher và combo)",
        "contribution_before_ads": num(p.contribution),
        "net_revenue": num(p.buyer_paid),
        "orders": p.orders,
        "cost_coverage": cov.json(),
        "assumed_cost_share_pct": pct(cov.pct(cov.assumed)),
        "assumed_cost_label": ASSUMED_COST_LABEL,
        "profit_is_partial": p.margin_is_partial,
        "ad_spend": {
            "total": num(p.total_ad_spend),
            "by_product": num(p.product_ad_spend),
            "unattributed": num(p.unattributed_ad_spend),
            "zero_revenue_campaigns": num(p.zero_revenue_campaign_spend),
            "consistent": p.ad_spend_consistent,
            "unattributed_label": "QC không gắn sản phẩm / không ra đơn",
        },
        "other_marketing_costs": num(p.other_marketing_costs),
        "break_even_roas": ratio(p.break_even_roas, 2),
        "gmv_reconciliation": {
            "line_gmv": num(p.reconciliation.line_gmv),
            "shopee_gmv": num(p.reconciliation.export_gmv),
            "gap": num(p.reconciliation.gap),
            "gap_pct": pct_of(p.reconciliation.gap_rate),
            "warn": p.reconciliation.warn,
        },
        "missing": p.missing,
        "fees": _fee_sources(view),
    }


def _fee_sources(view: PeriodView) -> dict[str, int]:
    out = {"actual": 0, "formula": 0, "not_charged": 0}
    for _, pb in view.pairs:
        out[pb.fee_source or "not_charged"] = out.get(pb.fee_source or "not_charged", 0) + 1
    return out


def _ads_block(view: PeriodView) -> dict[str, Any]:
    ads = view.ads
    daily = view.data.ads_daily
    camp_gmv = sum((c.gmv for c in ads.campaigns), ZERO)
    return {
        "basis": ADS_BASIS,
        "note": ADS_BASIS_NOTE,
        "in_which": "trong đó (overlay, không phải một dòng của tổng)",
        "spend": num(ads.total_spend),
        "gmv_placed": num(daily.gmv if daily.days_covered else camp_gmv),
        "orders_placed": num(daily.orders if daily.days_covered else None),
        "roas": ratio(safe_div(daily.gmv, daily.spend), 2) if daily.spend else None,
        "spend_per_day": num(safe_div(ads.total_spend, Decimal(view.window.days))),
        "allocation": {
            "basis": ads.basis,
            "label": ads.label,
            "scale": ratio(ads.scale),
            "report_windows": [
                {"from": a.isoformat(), "to": b.isoformat()} for a, b in ads.report_windows
            ],
            "exact_window": ads.exact_window,
            "daily_total": num(ads.daily_total),
            "report_total_raw": num(ads.report_total_raw),
        },
        "by_type": {k: {m: num(v) for m, v in cell.items()} for k, cell in daily.by_type.items()},
    }


def _vouchers_block(view: PeriodView, ctx: ShopContext) -> dict[str, Any]:
    rows = []
    for v in sorted(view.data.vouchers.rows, key=lambda r: -r.cost):
        implied = safe_div(v.cost, v.orders)
        rows.append(
            {
                "name": v.name,
                "orders": num(v.orders),
                "gmv": num(v.gmv),
                "cost": num(v.cost),
                "value_from_name": num(v.value_hint),
                "implied_value": num(implied),
                "cost_equals_value_x_orders": (
                    None if v.value_hint is None else v.value_hint * v.orders == v.cost
                ),
                "usage_rate_pct": pct_of(v.usage_rate),
                "created_by_shopee": v.by_shopee,
            }
        )
    total_cost = sum((v.cost for v in view.data.vouchers.rows), ZERO)
    join = view.data.voucher_join
    return {
        "settings_join": None
        if join is None
        else {
            "matched": len(join.matched),
            "unmatched_exports": len(join.unmatched_exports),
            "unmatched_settings": len(join.unmatched_settings),
            "ambiguous": join.ambiguous,
        },
        "basis": view.data.vouchers.choice.json(),
        "rows": rows,
        "total_cost": num(total_cost),
        "from_order_lines": num(sum((ln.shop_voucher_share for ln, _ in view.pairs), ZERO)),
    }


def _affiliate_block(view: PeriodView) -> dict[str, Any]:
    a = view.data.affiliate
    lines = [(ln, pb) for ln, pb in view.pairs if ln.affiliate]
    return {
        "basis": a.choice.json(),
        "kols": len(a.partners),
        "partner_gmv": num(sum((p.gmv for p in a.partners), ZERO)),
        "partner_orders": num(sum((p.orders for p in a.partners), ZERO)),
        "est_commission": num(sum((p.est_commission for p in a.partners), ZERO)),
        "order_lines": {
            "orders": len({ln.order_id for ln, _ in lines}),
            "gmv": num(sum((ln.order_value for ln, _ in lines), ZERO)),
            "commission": num(sum((ln.commission or ZERO for ln, _ in lines), ZERO)),
        },
    }


def build_overview(ctx: ShopContext, now: PeriodView, before: PeriodView) -> dict[str, Any]:
    cap = ctx.rules.target("daily_marketing_cap")
    five = five_for(now, before, cap)
    comparable = before.line_orders > 0 and before.data.lines.covers_window
    chain = _shop_chain(now)
    prev_chain = _shop_chain(before)
    p, pp = now.profit, before.profit
    targets = ctx.rules.targets
    return {
        "platform": "shopee",
        "order_basis": ORDER_BASIS,
        "period": {"window": now.window.json(), "previous": before.window.json()},
        "data": data_status(now),
        "warnings": warnings(now),
        "kpi_strip": {
            "gmv": _kpi(now.shop_gmv, before.shop_gmv),
            "views": _kpi(chain.get("views"), prev_chain.get("views")),
            "ctr": _kpi(chain.get("ctr"), prev_chain.get("ctr")),
            "ctor": _kpi(chain.get("ctor"), prev_chain.get("ctor")),
            "aov": _kpi(chain.get("aov"), prev_chain.get("aov")),
            "orders": _kpi(now.shop_orders, before.shop_orders),
            "margin_pct": {
                "value": pct(p.margin_pct),
                "previous": pct(pp.margin_pct),
                "label": "trên "
                + str(pct_of(safe_div(now.coverage.real + now.coverage.assumed, now.coverage.base)))
                + " % doanh thu có giá vốn (trong đó giả định "
                + str(pct(now.coverage.pct(now.coverage.assumed)))
                + " %)"
                if now.coverage.base > 0
                else None,
            },
        },
        "gmv": {
            "shopee_gmv": num(now.shop_gmv),
            "shopee_orders": now.shop_orders,
            "aov_gmv": num(
                safe_div(now.shop_gmv, Decimal(now.shop_orders))
                if now.shop_gmv and now.shop_orders
                else None
            ),
            "aov_seller_centre": num(_aov_seller_centre(now)),
            "aov_note": "AOV Seller Centre = (GMV − voucher shop) ÷ đơn đã xác nhận (§14); AOV "
            "chuỗi = GMV ÷ đơn.",
            "line_gmv": num(now.line_gmv),
            "line_orders": now.line_orders,
        },
        "flows": _flows_block(now, before),
        "levers": _levers_block(now),
        "five_numbers": five_json(five, comparable=comparable),
        "profit": _profit_block(now),
        "ads": _ads_block(now),
        "vouchers": _vouchers_block(now, ctx),
        "affiliate": _affiliate_block(now),
        "targets": {k: (num(v) if v is not None else None) for k, v in targets.items()},
    }


def _aov_seller_centre(view: PeriodView) -> Decimal | None:
    orders = view.line_orders
    if not orders:
        return None
    gmv = sum((ln.order_value for ln, _ in view.pairs), ZERO)
    voucher = sum((ln.shop_voucher_share for ln, _ in view.pairs), ZERO)
    return (gmv - voucher) / Decimal(orders)
