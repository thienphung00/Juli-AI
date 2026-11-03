"""Sản phẩm: one product's page payload (header, KPI by period, Nguồn, Chi phí & giá sàn, từ khoá).

Everything is read from the same :class:`PeriodView` the overview uses, so a product shows the
same numbers here, on Tổng quan and in Xếp hạng. The header comes from the newest
``platform_item_snapshots`` row (``platform_items`` for the name and SKU); a field the platform
has not given is ``None`` and listed in ``missing_fields``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.catalog import ItemInfo
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.engine import SRC_REAL
from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_analytics.fmt import (
    ASSUMED_COST_LABEL,
    delta_pct,
    num,
    pct,
    ratio,
)
from juli_backend.services.shopee_analytics.loaders import (
    ItemHeader,
    KeywordSeed,
    ShopContext,
)
from juli_backend.services.shopee_analytics.matrix import ads_overlay, product_row
from juli_backend.services.shopee_analytics.shared import five_for, five_json
from juli_backend.services.shopee_profit.floor import FloorInputs, compute_floor
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown

KEYWORD_ROLE_LABELS = {
    "chinh": "Chính",
    "phu": "Phụ",
    "thuong_hieu": "Thương hiệu",
    "loai_tru": "Loại trừ",
}
MAX_CORE_KEYWORDS = 5
TITLE_COUNTED_CHARS = 100


def _lines_of(view: PeriodView, product_id: str) -> list[tuple[OrderLine, ProfitBreakdown]]:
    return [(ln, pb) for ln, pb in view.pairs if ln.product_id == product_id]


def sku_waterfall(view: PeriodView, ctx: ShopContext, product_id: str) -> list[dict[str, Any]]:
    """Per SKU (variation): the average unit's waterfall and the floors (contract 6)."""
    by_sku: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in _lines_of(view, product_id):
        by_sku[ln.sku].append((ln, pb))
    margin_target = ctx.rules.target("margin_pct")
    default_cap = ctx.rules.default_max_discount_pct
    out: list[dict[str, Any]] = []
    spend = view.ads.product_spend.get(product_id, ZERO)
    product_paid = sum(
        (pb.revenue for ln, pb in _lines_of(view, product_id) if pb.excluded_reason is None), ZERO
    )
    for sku, items in sorted(by_sku.items()):
        carrying = [(ln, pb) for ln, pb in items if pb.excluded_reason is None]
        units = sum(ln.qty for ln, _ in carrying)
        list_price = view.costs.list_price.get(sku)
        cost = view.costs.by_key.get(sku)
        fee = view.fees.rate(product_id)
        formula = view.fees.schedule(product_id).formula_on(view.window.end)
        paid = sum((pb.revenue for _, pb in carrying), ZERO)
        commission = sum((pb.commission or ZERO for _, pb in carrying), ZERO)
        unit = Decimal(units) if units else None

        def per_unit(total: Decimal | None, unit: Decimal | None = unit) -> int | float | None:
            return None if total is None or not unit else num(total / unit)

        fees_total = sum((pb.fees_total or ZERO for _, pb in carrying), ZERO)
        cogs_total = sum((pb.cogs or ZERO for _, pb in carrying), ZERO)
        pack_total = sum((pb.packaging or ZERO for _, pb in carrying), ZERO)
        list_total = sum((pb.list_value for _, pb in carrying), ZERO)
        promo = sum((pb.promo_discount for _, pb in carrying), ZERO)
        voucher = sum((pb.voucher for _, pb in carrying), ZERO)
        combo = sum((pb.bundle for _, pb in carrying), ZERO)
        contribution = sum((pb.contribution or ZERO for _, pb in carrying), ZERO)
        ad_cost = (spend * paid / product_paid) if product_paid > 0 else ZERO
        ad_rate = safe_div(ad_cost, paid) if paid > 0 else None
        floor = None
        cap = ctx.rules.max_discount_pct.get(sku)
        if cap is None:
            cap = ctx.rules.max_discount_pct.get(product_id, default_cap)
        if formula is not None:
            floor = compute_floor(
                FloorInputs(
                    list_price=list_price,
                    cogs=cost.cogs if cost else None,
                    packaging=cost.packaging if cost else None,
                    fixed_fee_per_order=formula.fixed_per_order,
                    platform_fee_rate=formula.pct_rate_on_buyer_paid,
                    ads_rate=ad_rate if ad_rate is not None else ZERO,
                    affiliate_rate=safe_div(commission, paid) if paid > 0 else ZERO,
                    target_margin_rate=None if margin_target is None else margin_target / 100,
                    seller_max_discount_rate=None if cap is None else cap / 100,
                )
            )
        paid_unit = (paid / unit) if unit else None
        breach = None
        if floor is not None and paid_unit is not None:
            if floor.operating_floor is not None and paid_unit < floor.operating_floor:
                breach = "operating"
            if floor.absolute_floor is not None and paid_unit < floor.absolute_floor:
                breach = "absolute"
        out.append(
            {
                "sku": sku,
                "units": units,
                "list_price": num(list_price),
                "waterfall_per_unit": {
                    "list": per_unit(list_total),
                    "promo_discount": per_unit(promo),
                    "shop_voucher": per_unit(voucher),
                    "combo": per_unit(combo),
                    "net_revenue": per_unit(paid),
                    "platform_fees": per_unit(fees_total),
                    "cogs": per_unit(cogs_total),
                    "packaging": per_unit(pack_total),
                    "commission": per_unit(commission),
                    "contribution_before_ads": per_unit(contribution),
                    "ads": per_unit(ad_cost),
                    "profit": per_unit(contribution - ad_cost),
                    "margin_pct": pct(pct_points(safe_div(contribution - ad_cost, paid))),
                    "organic_vs_ads": "unknown (đơn xuất không ghi nguồn quảng cáo)",
                },
                "cost": {
                    "cogs_per_unit": num(cost.cogs) if cost else None,
                    "cogs_source": view.costs.cogs_source.get(sku),
                    "packaging": num(cost.packaging) if cost else None,
                    "packaging_source": view.costs.packaging_source.get(sku),
                    "label": ASSUMED_COST_LABEL
                    if view.costs.cogs_source.get(sku) != SRC_REAL
                    else None,
                },
                "fee": {
                    "fixed_fee_rate_pct": pct(pct_points(fee.rate)),
                    "rate_source": fee.source,
                    "category": list(fee.category) if fee.category else None,
                    "platform_fee_rate_pct": pct(pct_points(formula.pct_rate_on_buyer_paid))
                    if formula
                    else None,
                    "fixed_per_order": num(formula.fixed_per_order) if formula else None,
                },
                "floor": None
                if floor is None
                else {
                    "absolute": num(floor.absolute_floor),
                    "operating": num(floor.operating_floor),
                    "max_discount_pct": pct(floor.max_discount_pct),
                    "max_discount_amount": num(floor.max_discount_amount),
                    "reasons": floor.reasons,
                    "net_revenue_per_unit": num(paid_unit),
                    "breach": breach,
                    "margin_target_pct": num(margin_target),
                },
            }
        )
    return out


def kpi_block(now: PeriodView, before: PeriodView, product_id: str) -> dict[str, Any]:
    row = product_row(now, product_id)
    prev = product_row(before, product_id)
    table = now.flows.products.get(product_id) if now.flows else None
    views = clicks = None
    if table is not None:
        flows = [r for r in table.rows if not r.is_residual]
        views = sum((r.views or 0) for r in flows) or None
        clicks = sum((r.clicks or 0) for r in flows) or None
    gmv, orders = row["gmv"], row["orders"]
    comparable = before.line_orders > 0 and before.data.lines.covers_window
    five = five_json(five_for(now, before, None, product_id), comparable=comparable)
    return {
        "gmv": {
            "value": gmv,
            "previous": prev["gmv"],
            "change_pct": delta_pct(
                None if gmv is None else Decimal(str(gmv)),
                None if prev["gmv"] is None else Decimal(str(prev["gmv"])),
            ),
        },
        "orders": {"value": orders, "previous": prev["orders"]},
        "views": views,
        "clicks": clicks,
        "ctr": ratio(safe_div(Decimal(clicks), Decimal(views))) if views and clicks else None,
        "ctor": ratio(safe_div(Decimal(orders or 0), Decimal(clicks))) if clicks else None,
        "aov": num(safe_div(Decimal(str(gmv)), Decimal(orders))) if gmv and orders else None,
        "profit": row["profit"],
        "five_numbers": five,
        "basis": {
            "gmv": row["gmv_basis"],
            "flows": now.data.product_flows.flows_basis.json(),
        },
    }


def keyword_block(
    seeds: list[KeywordSeed],
    market: dict[str, Any],
    title: str | None,
    view: PeriodView,
    product_id: str,
) -> dict[str, Any]:
    folded_title = fold(title or "")
    ads_kw: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"spend": ZERO, "gmv": ZERO, "orders": ZERO}
    )
    for r in view.data.ads_reports.keyword_rows:
        if r.item_id == product_id and " › " in r.campaign:
            kw = fold(r.campaign.rsplit(" › ", 1)[1])
            ads_kw[kw]["spend"] += r.spend
            ads_kw[kw]["gmv"] += r.gmv
            ads_kw[kw]["orders"] += r.orders
    groups: dict[str, list[dict[str, Any]]] = {k: [] for k in KEYWORD_ROLE_LABELS}
    for s in sorted(seeds, key=lambda x: x.keyword):
        f = fold(s.keyword)
        pos = folded_title.find(f) if f else -1
        m = market.get(s.keyword)
        ad = ads_kw.get(f)
        groups.setdefault(s.role, []).append(
            {
                "keyword": s.keyword,
                "pattern": s.pattern,
                "in_title": pos >= 0 if title else None,
                "title_position": pos if pos >= 0 else None,
                "within_counted_chars": (pos >= 0 and pos + len(f) <= TITLE_COUNTED_CHARS)
                if title and pos >= 0
                else None,
                "market": None
                if m is None
                else {
                    "volume": m.volume,
                    "cpc_min": num(m.cpc_min),
                    "cpc_max": num(m.cpc_max),
                    "difficulty": num(m.difficulty),
                    "collected_on": m.collected_on.isoformat(),
                },
                "ads_placed": None
                if ad is None
                else {
                    "spend": num(ad["spend"]),
                    "gmv": num(ad["gmv"]),
                    "orders": num(ad["orders"]),
                },
            }
        )
    core = groups.get("chinh", [])
    covered = [k for k in core if k["in_title"]]
    return {
        "roles": {
            role: {"label": label, "keywords": groups.get(role, [])}
            for role, label in KEYWORD_ROLE_LABELS.items()
        },
        "core": {
            "used": len(core),
            "max": MAX_CORE_KEYWORDS,
            "full": len(core) >= MAX_CORE_KEYWORDS,
            "in_title": len(covered),
            "coverage_pct": pct(pct_points(safe_div(Decimal(len(covered)), Decimal(len(core)))))
            if core
            else None,
        },
        "title_counted_chars": TITLE_COUNTED_CHARS,
    }


def header_block(
    info: ItemInfo | None,
    snap: ItemHeader | None,
    view: PeriodView,
    product_id: str,
    as_of: date,
) -> dict[str, Any]:
    lines = [ln for ln, _ in _lines_of(view, product_id)]
    last_line = max(lines, key=lambda ln: ln.order_date) if lines else None
    title = (snap.title if snap and snap.title else None) or (info.name if info else None)
    missing: list[str] = []

    def pick(value: Any, field: str) -> Any:
        if value is None:
            missing.append(field)
        return value

    age = None
    if snap and snap.captured_at is not None:
        age = (as_of - snap.captured_at.date()).days
    return {
        "product_id": product_id,
        "title": pick(title, "title"),
        "title_chars": len(title) if title else None,
        "seller_sku": info.seller_sku if info else None,
        "status": pick(
            (snap.status if snap and snap.status else None) or (info.status if info else None),
            "status",
        ),
        "category_path": list(snap.category_path)
        if snap and snap.category_path
        else (list(info.category_path) if info and info.category_path else None),
        "images": snap.image_urls if snap else [],
        "price": {
            "list": num(
                (snap.list_price if snap else None)
                or (last_line.original_price if last_line else None)
            ),
            "current": num(
                (snap.current_price if snap else None)
                or (last_line.deal_price if last_line else None)
            ),
            "promo_label": snap.promo_label if snap else None,
            "source": "snapshot"
            if snap and snap.list_price is not None
            else ("last_order_line" if last_line else None),
            "captured_at": snap.captured_at.isoformat() + "Z"
            if snap and snap.captured_at
            else None,
        },
        "stock": {
            "value": pick(snap.stock if snap else None, "stock"),
            "age_days": age,
            "stale": age is not None and age >= 3,
        },
        "reputation": {
            "rating": num(snap.rating) if snap else None,
            "rating_count": snap.rating_count if snap else None,
            "likes": snap.likes if snap else None,
            "sold_total": snap.sold_total if snap else None,
        },
        "variations": [
            {
                "variation_id": v.variation_id,
                "name": v.name,
                "seller_sku": v.seller_sku,
                "status": v.status,
            }
            for v in (info.variations if info else ())
        ],
        "missing_fields": missing,
    }


def build_product_page(
    ctx: ShopContext,
    product_id: str,
    views: dict[str, tuple[PeriodView, PeriodView]],
    selected: str,
    snap: ItemHeader | None,
    seeds: list[KeywordSeed],
    market: dict[str, Any],
    as_of: date,
) -> dict[str, Any]:
    now, before = views[selected]
    info = ctx.catalog.items.get(product_id)
    header = header_block(info, snap, now, product_id, as_of)
    return {
        "platform": "shopee",
        "order_basis": {"key": "confirmed", "label": "Đơn đã xác nhận"},
        "period": {
            "selected": selected,
            "window": now.window.json(),
            "previous": before.window.json(),
        },
        "header": header,
        "kpi_by_period": {key: kpi_block(n, b, product_id) for key, (n, b) in views.items()},
        "nguon": product_row(now, product_id),
        "ads": ads_overlay(now, product_id),
        "cost_and_floor": {
            "skus": sku_waterfall(now, ctx, product_id),
            "coverage_label": ASSUMED_COST_LABEL,
            "floor_note": "Giá sàn tuyệt đối = (giá vốn + đóng gói + phí cố định/đơn) ÷ (1 − phí sàn %); "  # noqa: E501
            "giá sàn vận hành trừ thêm QC %, hoa hồng % và biên mục tiêu %.",
        },
        "keywords": keyword_block(seeds, market, header["title"], now, product_id),
    }
