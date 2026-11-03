"""Phân tích: the critical-metric list, ranked by the đồng each item has at stake (contract 8, 11).

Each item is one metric of one scope (shop / flow / product) held against ONE reference, and
carries the đồng per day it moves if it came back to that reference:

- ``band``       -- a flow's CTR / CTOR against the flow-baseline band (the quasi-binomial model of
  ``services/shopee_kpi``, fitted on the days BEFORE the window; its 90 % band);
- ``target``     -- a product's margin, or the shop's monthly GMV / orders / AOV pace, against the
  seller's Cài đặt › Mục tiêu (no target set = no item, never a default);
- ``floor``      -- a SKU's buyer-paid per unit under its operating (else absolute) floor price;
- ``break_even`` -- a product's ROAS trực tiếp under its break-even ROAS;
- ``shop_median`` -- a product's CTR / CTOR / AOV under the median of the shop's products.

Items inside their reference go to ``in_band`` ("Trong dải bình thường"). Every item names the
card kinds contract 8 maps its metric to, and the Xếp hạng link (kpi, src, focus) that shows the
same ₫ per day. Money at stake never mixes bases: a margin item uses buyer_paid, a flow item uses
confirmed GMV, an ads item uses placed-order ads figures and says so.
"""

from __future__ import annotations

import calendar
import statistics
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import ADS_BASIS, ASSUMED_COST_LABEL, num, ratio
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.product import sku_waterfall
from juli_backend.services.shopee_kpi import flow_glm
from juli_backend.services.shopee_profit.flows import FLOW_LABELS
from juli_backend.services.shopee_profit.money import ZERO, safe_div

DAYS_PER_MONTH = Decimal(30)
MIN_PRODUCT_CLICKS = 100
MIN_PRODUCT_ORDERS = 10
MIN_PRODUCTS_FOR_MEDIAN = 3

CHANGE_KINDS: dict[str, list[str]] = {
    "views": ["title", "keyword", "ads_budget", "affiliate_commission"],
    "ctr": ["cover_image", "title", "price_display"],
    "ctor": ["product_discount", "min_spend_voucher", "review_voucher", "price"],
    "aov": ["bundle_deal", "add_on", "min_spend_voucher", "variation_set"],
    "bien": ["price", "voucher_cap", "ads_roas_target", "ads_pause"],
    "roas": ["ads_roas_target", "ads_pause", "ads_purpose"],
    "lien_ket": ["affiliate_commission", "affiliate_target_campaign"],
}
CAUSE_TEXT: dict[str, str] = {
    "ctr": "Khách thấy sản phẩm nhưng ít bấm vào: ảnh bìa / tiêu đề / giá hiển thị.",
    "ctor": "Khách bấm vào nhưng ít đặt đơn: giá, khuyến mãi, voucher, đánh giá.",
    "aov": "Giá trị mỗi đơn thấp: combo, mua kèm, voucher đơn tối thiểu.",
    "bien": "Biên dưới mục tiêu: giá bán, voucher, quảng cáo ăn vào lợi nhuận.",
    "floor": "Giá khách trả thấp hơn giá sàn: giảm giá quá mức.",
    "roas": "ROAS trực tiếp thấp hơn điểm hoà vốn: quảng cáo đang lỗ.",
    "gmv": "Doanh số đang chậm so với mục tiêu tháng.",
    "orders": "Số đơn đang chậm so với mục tiêu tháng.",
}


def _item(
    *,
    id: str,
    kind: str,
    level: str,
    kpi: str,
    stage: str,
    current: Decimal | None,
    reference: dict[str, Any],
    at_stake_per_day: Decimal,
    product_id: str | None = None,
    name: str | None = None,
    flow: str | None = None,
    src: str = "all",
    basis: str = "confirmed",
    assumed_cost: bool = False,
) -> dict[str, Any]:
    ref_value = reference.get("value")
    cur = None if current is None else float(current)
    dev = None
    if cur is not None and ref_value:
        dev = round((cur - float(ref_value)) / float(ref_value) * 100, 1)
    return {
        "id": id,
        "kind": kind,
        "level": level,
        "product_id": product_id,
        "name": name,
        "flow": flow,
        "flow_label": FLOW_LABELS.get(flow or "", None),
        "kpi": kpi,
        "current": None
        if current is None
        else (num(current) if abs(current) >= 10 else ratio(current)),
        "reference": reference,
        "deviation_pct": dev,
        "at_stake_per_day": num(at_stake_per_day.quantize(Decimal(1))),
        "at_stake_per_month": num((at_stake_per_day * DAYS_PER_MONTH).quantize(Decimal(1))),
        "money_basis": basis,
        "cause": {"stage": stage, "text": CAUSE_TEXT.get(stage, "")},
        "change_kinds": CHANGE_KINDS.get(stage if stage in CHANGE_KINDS else kpi, []),
        "ranking_link": {"kpi": kpi, "src": src, "focus": product_id or flow},
        "assumed_cost": assumed_cost,
    }


def _flow_items(
    view: PeriodView,
    series: dict[str, dict[date, tuple[float, float, float, float]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    crit: list[dict[str, Any]] = []
    ok: list[dict[str, Any]] = []
    notes: list[dict[str, str]] = []
    window = view.window
    table = view.flows.shop if view.flows else None
    if table is None:
        return (
            crit,
            ok,
            [{"code": "no_flow_data", "message": "Chưa có lưu lượng theo nguồn cho kỳ này."}],
        )
    days = Decimal(window.days)
    for row in table.rows:
        if row.is_residual or row.key not in series:
            continue
        before = {d: v for d, v in series[row.key].items() if d < window.start}
        if len(before) < 60:
            notes.append(
                {
                    "code": f"band_missing:{row.key}",
                    "message": f"Chưa đủ lịch sử để lập dải bình thường cho {row.label}.",
                }
            )
            continue
        for metric in ("ctr", "ctor"):
            model = flow_glm.fit_rate(row.key, metric, before)
            if model is None:
                continue
            band = flow_glm.band(model, window=30, horizon=min(window.days, 28))
            now = row.ctr if metric == "ctr" else row.ctor
            if now is None:
                continue
            low, high, mean = (
                Decimal(str(band.band90_low)),
                Decimal(str(band.band90_high)),
                Decimal(str(band.forecast_mean)),
            )
            reference = {
                "type": "band",
                "label": "dải bình thường (khoảng 90 % từ lịch sử trước kỳ)",
                "value": float(mean),
                "low": float(low),
                "high": float(high),
            }
            aov = row.aov or ZERO
            if metric == "ctr":
                lost = Decimal(row.views or 0) / days * (mean - now) * (row.ctor or ZERO) * aov
            else:
                lost = Decimal(row.clicks or 0) / days * (mean - now) * aov
            item = _item(
                id=f"flow:{row.key}:{metric}",
                kind="below_band",
                level="flow",
                kpi=metric,
                stage=metric,
                current=now,
                reference=reference,
                at_stake_per_day=max(lost, ZERO),
                flow=row.key,
                src=row.key,
            )
            (crit if now < low and lost > 0 else ok).append(item)
    return crit, ok, notes


def _margin_items(view: PeriodView, ctx: ShopContext) -> list[dict[str, Any]]:
    target = ctx.rules.target("margin_pct")
    if target is None:
        return []
    out: list[dict[str, Any]] = []
    days = Decimal(view.window.days)
    for pid, pp in view.profit.products.items():
        if pp.margin_rate is None or pp.buyer_paid_covered <= 0:
            continue
        shortfall = target / 100 - pp.margin_rate
        if shortfall <= 0:
            continue
        assumed = any(
            not view.costs.cogs_is_real(ln.sku) for ln, _ in view.pairs if ln.product_id == pid
        )
        out.append(
            _item(
                id=f"product:{pid}:bien",
                kind="margin_below_target",
                level="product",
                kpi="bien",
                stage="bien",
                current=pp.margin_rate * 100,
                reference={"type": "target", "label": "mục tiêu biên", "value": float(target)},
                at_stake_per_day=shortfall * pp.buyer_paid_covered / days,
                product_id=pid,
                name=view.names.get(pid),
                assumed_cost=assumed,
            )
        )
    return out


def _floor_items(view: PeriodView, ctx: ShopContext) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    days = Decimal(view.window.days)
    for pid in view.profit.products:
        for sku in sku_waterfall(view, ctx, pid):
            floor = sku["floor"]
            if not floor or not floor["breach"]:
                continue
            ref = floor["operating"] if floor["breach"] == "operating" else floor["absolute"]
            paid = floor["net_revenue_per_unit"]
            if ref is None or paid is None:
                continue
            gap = Decimal(str(ref)) - Decimal(str(paid))
            out.append(
                _item(
                    id=f"product:{pid}:floor:{sku['sku']}",
                    kind="floor_breach",
                    level="product",
                    kpi="bien",
                    stage="floor",
                    current=Decimal(str(paid)),
                    reference={
                        "type": "floor",
                        "label": "giá sàn vận hành"
                        if floor["breach"] == "operating"
                        else "giá sàn tuyệt đối",
                        "value": ref,
                        "sku": sku["sku"],
                    },
                    at_stake_per_day=gap * Decimal(sku["units"]) / days,
                    product_id=pid,
                    name=view.names.get(pid),
                    assumed_cost=sku["cost"]["cogs_source"] != "real",
                )
            )
    return out


def _roas_items(view: PeriodView) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    days = Decimal(view.window.days)
    for pid, pp in view.profit.products.items():
        be, direct, fig = pp.break_even_roas, pp.roas_direct, pp.ads
        if be is None or direct is None or fig is None or fig.spend <= 0 or direct >= be:
            continue
        loss = fig.spend - (fig.direct_gmv or ZERO) / be
        out.append(
            _item(
                id=f"product:{pid}:roas",
                kind="roas_below_break_even",
                level="product",
                kpi="roas",
                stage="roas",
                current=direct,
                reference={
                    "type": "break_even",
                    "label": "ROAS hoà vốn (trực tiếp)",
                    "value": float(be),
                },
                at_stake_per_day=max(loss, ZERO) / days,
                product_id=pid,
                name=view.names.get(pid),
                src="ads",
                basis=ADS_BASIS["key"],
                assumed_cost=True,
            )
        )
    return out


@dataclass(frozen=True)
class _ProdStats:
    views: Decimal
    clicks: Decimal
    orders: Decimal
    rates: dict[str, Decimal | None]


def _median_items(view: PeriodView) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    crit: list[dict[str, Any]] = []
    ok: list[dict[str, Any]] = []
    if not view.flows:
        return crit, ok
    days = Decimal(view.window.days)
    stats: dict[str, _ProdStats] = {}
    for pid, table in view.flows.products.items():
        flows = [r for r in table.rows if not r.is_residual]
        views = sum((r.views or 0) for r in flows)
        clicks = sum((r.clicks or 0) for r in flows)
        orders = sum(r.orders for r in flows)
        gmv = sum((r.gmv for r in flows), ZERO)
        stats[pid] = _ProdStats(
            views=Decimal(views),
            clicks=Decimal(clicks),
            orders=Decimal(orders),
            rates={
                "ctr": safe_div(Decimal(clicks), Decimal(views))
                if clicks >= MIN_PRODUCT_CLICKS
                else None,
                "ctor": safe_div(Decimal(orders), Decimal(clicks))
                if orders >= MIN_PRODUCT_ORDERS and clicks
                else None,
                "aov": safe_div(gmv, Decimal(orders)) if orders >= MIN_PRODUCT_ORDERS else None,
            },
        )
    for metric in ("ctr", "ctor", "aov"):
        values = [s.rates[metric] for s in stats.values() if s.rates[metric] is not None]
        if len(values) < MIN_PRODUCTS_FOR_MEDIAN:
            continue
        median = Decimal(str(statistics.median(float(v) for v in values if v is not None)))
        for pid, s in stats.items():
            now = s.rates[metric]
            if now is None:
                continue
            aov = s.rates["aov"] or ZERO
            if metric == "ctr":
                lost = (
                    s.views / days * (median - now) * (safe_div(s.orders, s.clicks) or ZERO) * aov
                )
            elif metric == "ctor":
                lost = s.clicks / days * (median - now) * aov
            else:
                lost = s.orders / days * (median - now)
            item = _item(
                id=f"product:{pid}:{metric}:median",
                kind="below_shop_median",
                level="product",
                kpi=metric,
                stage=metric,
                current=now,
                reference={
                    "type": "shop_median",
                    "label": "trung vị các sản phẩm của shop",
                    "value": float(median),
                },
                at_stake_per_day=max(lost, ZERO),
                product_id=pid,
                name=view.names.get(pid),
            )
            (crit if now < median and lost > 0 else ok).append(item)
    return crit, ok


#: A product is "low on search views" below this share of the shop's median per-product search
#: views per day (views are skewed: half the catalogue is always below the median).
LOW_VIEWS_SHARE = Decimal("0.5")


def _search_views_items(view: PeriodView) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lượt xem (search): a product's Thẻ sản phẩm "search" impressions per day against the
    median of the shop's products. Needs the per-source daily rows (``item_traffic_sources``);
    without them there is no item, never a guess. The đồng at stake is the missing views at the
    shop's own search CTR x CTOR x AOV."""
    crit: list[dict[str, Any]] = []
    ok: list[dict[str, Any]] = []
    kids = view.data.product_flows.children
    stats = {pid: k["search"] for pid, k in kids.items() if k.get("search") and k["search"].views}
    if len(stats) < MIN_PRODUCTS_FOR_MEDIAN:
        return crit, ok
    days = Decimal(view.window.days)
    views = sum((a.views or ZERO for a in stats.values()), ZERO)
    clicks = sum((a.clicks or ZERO for a in stats.values()), ZERO)
    orders = sum((a.orders for a in stats.values()), ZERO)
    gmv = sum((a.gmv for a in stats.values()), ZERO)
    ctr, ctor, aov = safe_div(clicks, views), safe_div(orders, clicks), safe_div(gmv, orders)
    if not (ctr and ctor and aov):
        return crit, ok
    per_day = {pid: (a.views or ZERO) / days for pid, a in stats.items()}
    median = Decimal(str(statistics.median(float(v) for v in per_day.values())))
    for pid, now in per_day.items():
        lost = (median - now) * ctr * ctor * aov
        item = _item(
            id=f"product:{pid}:views:median",
            kind="below_shop_median",
            level="product",
            kpi="views",
            stage="views",
            current=now,
            reference={
                "type": "shop_median",
                "label": "trung vị lượt xem từ tìm kiếm của các sản phẩm",
                "value": float(median),
            },
            at_stake_per_day=max(lost, ZERO),
            product_id=pid,
            name=view.names.get(pid),
            flow="the_san_pham_khac",
            src="the_san_pham_khac",
        )
        item["ranking_link"]["sub"] = "search"
        (crit if now < median * LOW_VIEWS_SHARE and lost > 0 else ok).append(item)
    return crit, ok


def _target_items(view: PeriodView, ctx: ShopContext) -> list[dict[str, Any]]:
    """The shop's monthly GMV / orders pace against the seller's targets."""
    out: list[dict[str, Any]] = []
    window = view.window
    month_days = Decimal(calendar.monthrange(window.end.year, window.end.month)[1])
    days = Decimal(window.days)
    for key, current, label in (
        ("gmv_month", view.shop_gmv, "gmv"),
        (
            "orders_month",
            Decimal(view.shop_orders) if view.shop_orders is not None else None,
            "orders",
        ),
    ):
        target = ctx.rules.target(key)
        if target is None or current is None:
            continue
        projected = current / days * month_days
        if projected >= target:
            continue
        per_day = (target - projected) / month_days
        out.append(
            _item(
                id=f"shop:{label}:target",
                kind="below_monthly_target",
                level="shop",
                kpi=label,
                stage=label,
                current=projected,
                reference={"type": "target", "label": "mục tiêu tháng", "value": float(target)},
                at_stake_per_day=per_day
                * (
                    Decimal(1)
                    if label == "gmv"
                    else (safe_div(view.shop_gmv or ZERO, current) or ZERO)
                ),
            )
        )
    return out


def build_critical(
    ctx: ShopContext,
    now: PeriodView,
    series: dict[str, dict[date, tuple[float, float, float, float]]],
) -> dict[str, Any]:
    flow_crit, flow_ok, notes = _flow_items(now, series)
    med_crit, med_ok = _median_items(now)
    views_crit, views_ok = _search_views_items(now)
    med_crit, med_ok = [*med_crit, *views_crit], [*med_ok, *views_ok]
    items = [
        *flow_crit,
        *_margin_items(now, ctx),
        *_floor_items(now, ctx),
        *_roas_items(now),
        *med_crit,
        *_target_items(now, ctx),
    ]
    items.sort(key=lambda it: -(it["at_stake_per_day"] or 0))
    for rank, it in enumerate(items, 1):
        it["rank"] = rank
    if ctx.rules.target("margin_pct") is None:
        notes.append(
            {
                "code": "margin_target_missing",
                "message": "Chưa đặt mục tiêu biên (Cài đặt › Mục tiêu): chưa có mục biên dưới "
                "mục tiêu.",
            }
        )
    if any(it["assumed_cost"] for it in items):
        notes.append({"code": "assumed_cost", "message": f"Một số mục dùng {ASSUMED_COST_LABEL}."})
    return {
        "platform": "shopee",
        "window": now.window.json(),
        "items": items,
        "in_band": sorted([*flow_ok, *med_ok], key=lambda it: -(it["at_stake_per_day"] or 0)),
        "total_at_stake_per_day": num(
            sum((Decimal(str(it["at_stake_per_day"] or 0)) for it in items), ZERO)
        ),
        "notes": notes,
        "ranking_rule": "Xếp theo ₫ mỗi ngày đang bị ảnh hưởng nếu chỉ số về mức tham chiếu của "
        "nó.",
    }


__all__ = ["CHANGE_KINDS", "build_critical"]
