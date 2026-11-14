"""P100 S1 (Tổng quan): the channel split -- Organic / Quảng cáo / Tiếp thị liên kết -- of the shop
or of one product, from the stored source funnel and the two ad bases.

The split arithmetic is pure (:func:`split_rows`, :func:`weakest_metric`); the loaders below only
read a window and hand the numbers to it.

Rules (the owner's, ORY 11/10-09/11 as the sanity shape):

- Sources (Seller Centre): Thẻ sản phẩm (``the_san_pham_khac``), Trang shop (``trang_shop``), Live,
  Video, Tiếp thị liên kết (``lien_ket``) and the residual ``chenh_lech_nguon``.
- **Quảng cáo, traffic-overview base** = the "trong đó Quảng cáo" overlay of Thẻ sản phẩm
  (``AdShare``: views, clicks, placed orders, GMV). It sits inside the sources, never beside them.
- **Organic = sources - Quảng cáo - Tiếp thị liên kết.** Its four children add up to it: Thẻ sản
  phẩm (organic) = Thẻ sản phẩm + residual - the ads overlay; Trang shop = the ``trang_shop``
  segment; Video; Live.
- Every row carries ``prev`` (the same cells over the previous period of the same length) and
  ``share`` (of the total GMV on the traffic-overview base; ``None`` for ads-report rows).
- **Quảng cáo children, ads-report base** (never added to the traffic-overview figure): DVHT Sản
  phẩm = every ad type of the ads report except ``ads_shop``; DVHT Shop+ = ``ads_shop``. The
  report has no views / clicks, so those stay ``None``. At Sản phẩm level there is no Shop+ row
  and the Quảng cáo row itself is the ads-report base (per-product ad GMV and spend only).
- Tiếp thị liên kết has no views (``None``); clicks and orders only.
- A figure with no data is ``None``, never 0. An ad overlay that is missing at shop level makes
  Organic ``None`` (nothing to subtract).
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import IngestDatasetStatus
from juli_backend.services.shopee_analytics import funnel, loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import frac, num
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import (
    RESIDUAL,
    AdShare,
    FunnelBase,
    SourceFunnel,
)
from juli_backend.services.shopee_profit import shop_profit

SHOP_PLUS_KIND = "ads_shop"
CARD, SHOP_PAGE, LIVE, VIDEO, AFFILIATE = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
)
PLAN_PERIOD = "plan"
MIN_PRODUCTS_FOR_MEDIAN = 3
MAX_PRODUCTS = 200
_METRICS = ("views", "ctr", "ctor", "aov")


# -- pure arithmetic ------------------------------------------------------------------------


def _sum(values: Sequence[Decimal | None]) -> Decimal | None:
    known = [v for v in values if v is not None]
    return sum(known, Decimal(0)) if known else None


def _minus(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None or b <= 0 else a / b


def _row(
    key: str,
    parent: str | None,
    views: Decimal | None,
    clicks: Decimal | None,
    orders: Decimal | None,
    gmv: Decimal | None,
    ad_base: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "parent": parent,
        "views": None if views is None else int(views),
        "clicks": None if clicks is None else int(clicks),
        "ctr": frac(_div(clicks, views)),
        "ctor": frac(_div(orders, clicks)),
        "aov": num(_div(gmv, orders)),
        "gmv": num(gmv),
        "orders": num(orders),
        "ad_base": ad_base,
    }


def _by_source(base: FunnelBase) -> dict[str, SourceFunnel]:
    return {s.source: s for s in base.sources}


def _ad_report(
    ad_types: Mapping[str, Mapping[str, Decimal]] | None,
) -> tuple[dict[str, Decimal] | None, dict[str, Decimal] | None]:
    """(DVHT Sản phẩm, DVHT Shop+) of the ads report: ``{"gmv", "orders", "spend"}`` each."""
    if not ad_types:
        return None, None
    product = {"gmv": Decimal(0), "orders": Decimal(0), "spend": Decimal(0)}
    shop = dict(product)
    has_product = has_shop = False
    for kind, cell in ad_types.items():
        target = shop if kind == SHOP_PLUS_KIND else product
        if kind == SHOP_PLUS_KIND:
            has_shop = True
        else:
            has_product = True
        for k in target:
            target[k] += Decimal(cell.get(k) or 0)
    return (product if has_product else None), (shop if has_shop else None)


def split_rows(
    base: FunnelBase,
    *,
    ad_types: Mapping[str, Mapping[str, Decimal]] | None = None,
    ads_known: bool = True,
    ads_fallback: Mapping[str, Decimal] | None = None,
    affiliate_fallback: Mapping[str, Decimal] | None = None,
) -> list[dict[str, Any]]:
    """The channel table rows for ``base`` (the shop, or one product).

    ``ads_fallback`` / ``affiliate_fallback`` (product level): ``{"gmv", "orders"?}`` taken from
    the ads report / the order lines when the product's funnel rows carry no ad overlay or no
    Tiếp thị liên kết source; Organic then is the total minus both, never below 0.

    ``ad_types``: the ads report by type (shop level only). ``ads_known`` (product level): the
    shop has ad data at all, so a product without an ad figure has 0 ads instead of "no data"."""
    src = _by_source(base)
    product_level = base.scope == "products"
    card, shop_page, aff = src.get(CARD), src.get(SHOP_PAGE), src.get(AFFILIATE)
    ads: AdShare | None = card.ads if card is not None else None
    if (ads is None or not ads.gmv) and product_level and ads_fallback is not None:
        ads = AdShare(None, None, ads_fallback.get("orders"), ads_fallback["gmv"], None)
    if ads is None and product_level and ads_known:
        ads = AdShare(Decimal(0), Decimal(0), None, Decimal(0), Decimal(0))
    if (aff is None or not aff.gmv) and product_level and affiliate_fallback is not None:
        aff = SourceFunnel(
            "lien_ket",
            None,
            None,
            affiliate_fallback.get("orders") or Decimal(0),
            affiliate_fallback["gmv"],
            None,
        )

    def card_part(field: str) -> Decimal | None:
        """Thẻ sản phẩm + residual, before the ads overlay comes off."""
        parts = [x for x in (card, src.get(RESIDUAL)) if x is not None]
        return _sum([getattr(x, field) for x in parts])

    a = ads
    org_card = _row(
        "organic_card",
        "organic",
        _minus(card_part("views"), a.views) if a else None,
        _minus(card_part("clicks"), a.clicks) if a else None,
        _minus(card_part("orders"), a.orders) if a else None,
        _minus(card_part("gmv"), a.gmv) if a else None,
    )

    def child(key: str, s: SourceFunnel | None) -> dict[str, Any]:
        return _row(
            key,
            "organic",
            s.views if s else None,
            s.clicks if s else None,
            s.orders if s else None,
            s.gmv if s else None,
        )

    org_shop = child("organic_shop", shop_page)
    org_video = child("organic_video", src.get(VIDEO))
    org_live = child("organic_live", src.get(LIVE))
    kids = (org_card, org_shop, org_video, org_live)

    def organic(field: str) -> Decimal | None:
        values = [None if k[field] is None else Decimal(str(k[field])) for k in kids]
        # a child without data does not blank the parent unless it is the only one that could count
        return None if org_card[field] is None else _sum(values)

    org_views, org_clicks = organic("views"), organic("clicks")
    org_orders, org_gmv = organic("orders"), organic("gmv")
    if (
        product_level
        and not (card and card.gmv)
        and (ads_fallback is not None or affiliate_fallback)
    ):
        # no source breakdown at all: Organic = the product's total - ads - affiliate (>= 0)
        total_gmv = base.total("gmv")
        if total_gmv is not None:
            taken = (a.gmv if a and a.gmv is not None else Decimal(0)) + (
                aff.gmv if aff and aff.gmv is not None else Decimal(0)
            )
            org_gmv = max(total_gmv - taken, Decimal(0))
            org_card = _row("organic_card", "organic", None, None, None, org_gmv)
    rows = [_row("organic", None, org_views, org_clicks, org_orders, org_gmv), org_card]
    if not product_level or shop_page is not None:
        rows.append(org_shop)
    if not product_level or VIDEO in src:
        rows.append(org_video)
    if not product_level or LIVE in src:
        rows.append(org_live)
    base_name = "ads_report" if product_level else "traffic_overview"
    rows.append(
        _row(
            "ads",
            None,
            a.views if a else None,
            a.clicks if a else None,
            a.orders if a else None,
            a.gmv if a else None,
            base_name,
        )
    )
    if not product_level:
        product_ads, shop_ads = _ad_report(ad_types)
        rows.append(_ad_row("ads_product", product_ads))
        rows.append(_ad_row("ads_shop", shop_ads))
    rows.append(
        _row(
            "affiliate",
            None,
            None,
            aff.clicks if aff else None,
            aff.orders if aff else None,
            aff.gmv if aff else None,
        )
    )
    return with_share(rows, base.total("gmv"))


def with_share(rows: list[dict[str, Any]], total: Decimal | None) -> list[dict[str, Any]]:
    """Each row's ``share`` of the total GMV (traffic-overview base); ``None`` for ads-report rows
    and when the total is unknown or 0."""
    for r in rows:
        r["share"] = (
            frac(Decimal(str(r["gmv"])) / total)
            if total is not None
            and total > 0
            and r["gmv"] is not None
            and r["ad_base"] != "ads_report"
            else None
        )
    return rows


def _ad_row(key: str, cell: Mapping[str, Decimal] | None) -> dict[str, Any]:
    return _row(
        key,
        "ads",
        None,
        None,
        None if cell is None else cell["orders"],
        None if cell is None else cell["gmv"],
        "ads_report",
    )


def weakest_metric(values: Mapping[str, Mapping[str, float | None]], product_id: str) -> str | None:
    """The funnel metric of ``product_id`` furthest below the shop's own median.

    ``values``: product id -> {views, ctr, ctor, aov}. For each metric the median is taken over
    the products that have a value (at least :data:`MIN_PRODUCTS_FOR_MEDIAN` of them, else the
    metric is skipped); the product's gap is ``value / median``. The weakest metric is the one
    with the smallest ratio strictly under 1; ``None`` when no metric is below its median or none
    can be compared. Lượt xem × CTR × CTOR = đơn, so "orders" is never named separately."""
    mine = values.get(product_id, {})
    worst: tuple[float, str] | None = None
    for metric in _METRICS:
        have = [x for v in values.values() if (x := v.get(metric)) is not None]
        value = mine.get(metric)
        if value is None or len(have) < MIN_PRODUCTS_FOR_MEDIAN:
            continue
        median = statistics.median(have)
        if median <= 0:
            continue
        ratio = value / median
        if ratio < 1 and (worst is None or ratio < worst[0]):
            worst = (ratio, metric)
    return None if worst is None else worst[1]


# -- loaders --------------------------------------------------------------------------------


async def _updated_at(session: AsyncSession, shop_id: uuid.UUID) -> str | None:
    stamp = (
        await session.execute(
            select(
                func.max(
                    func.coalesce(
                        IngestDatasetStatus.last_captured_at, IngestDatasetStatus.last_ingest_at
                    )
                )
            ).where(IngestDatasetStatus.shop_id == shop_id)
        )
    ).scalar()
    if stamp is None:
        return None
    return stamp.isoformat() if isinstance(stamp, datetime) else str(stamp)


async def _load(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> tuple[Any, PeriodView, Window] | None:
    from juli_backend.services.shopee_analytics.queries import NoShopeeData

    window = await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, shop_id, ctx, window, funnel=True)
    return ctx, view, window


def _affiliate_cost(view: PeriodView, product_id: str | None) -> Decimal | None:
    lines = [
        ln
        for ln, _ in view.pairs
        if ln.affiliate and (product_id is None or ln.product_id == product_id)
    ]
    known = [ln.commission for ln in lines if ln.commission is not None]
    return sum(known, Decimal(0)) if known else None


def _product_ads(
    view: PeriodView, product_id: str | None, ads_known: bool
) -> dict[str, Decimal] | None:
    """The product's DVHT figures of the ads report (by item id), for a product whose funnel rows
    carry no ad overlay. ``None`` without a product, without ad data, or without a report row."""
    if product_id is None or not ads_known:
        return None
    fig = view.ads.product_figures.get(product_id)
    return None if fig is None or fig.gmv is None else {"gmv": fig.gmv}


def _product_affiliate(view: PeriodView, product_id: str | None) -> dict[str, Decimal] | None:
    """The product's Tiếp thị liên kết GMV and orders from the order lines (the lines
    :func:`_affiliate_cost` reads), for a product whose funnel rows have no such source."""
    if product_id is None:
        return None
    lines = [ln for ln, _ in view.pairs if ln.affiliate and ln.product_id == product_id]
    if not lines:
        return None
    return {
        "gmv": sum((ln.order_value for ln in lines), Decimal(0)),
        "orders": Decimal(len({ln.order_id for ln in lines})),
    }


def _offers_cost(view: PeriodView, product_id: str | None) -> Decimal | None:
    """Ưu đãi: the voucher + Chương Trình Của Shop (khuyến mãi / flash sale) + combo / Deal Sốc
    discounts of the window's order lines -- the same three the profit computation takes off
    (``five_numbers``: promo + voucher + combo). ``None`` without order lines."""
    pairs = [(ln, pb) for ln, pb in view.pairs if product_id is None or ln.product_id == product_id]
    if not pairs:
        return None
    return sum((pb.promo_discount + pb.voucher + pb.bundle for _, pb in pairs), Decimal(0))


def kpis_of(
    gmv: Decimal | None,
    orders: Decimal | None,
    profit: Decimal | None,
    cost_ads: Decimal | None,
    cost_affiliate: Decimal | None,
    cost_offers: Decimal | None,
) -> dict[str, Any]:
    """Tổng quan's KPIs: Tổng chi phí = Quảng cáo (ads report) + Tiếp thị liên kết + Ưu đãi (the
    known ones; ``None`` when none is known); ROI = Lợi nhuận ÷ Tổng chi phí (``None`` when the
    cost is 0 or unknown)."""
    total = _sum([cost_ads, cost_affiliate, cost_offers])
    roi = None if profit is None else _div(profit, total)
    return {
        "gmv": num(gmv),
        "orders": num(orders),
        "profit": num(profit),
        "cost_total": num(total),
        "cost_ads": num(cost_ads),
        "cost_affiliate": num(cost_affiliate),
        "cost_offers": num(cost_offers),
        "roi": frac(roi, 4),
    }


def _kpis(view: PeriodView, base: FunnelBase, product_id: str | None) -> dict[str, Any]:
    if product_id is None:
        profit = shop_profit_of(view).profit
        ads_cost: Decimal | None = view.profit.total_ad_spend
    else:
        pp = view.profit.products.get(product_id)
        profit = None if pp is None else pp.profit
        ads_cost = None if pp is None else pp.ad_spend
    return kpis_of(
        base.total("gmv"),
        base.total("orders"),
        profit,
        ads_cost,
        _affiliate_cost(view, product_id),
        _offers_cost(view, product_id),
    )


def plan_block_of(r: Mapping[str, Any]) -> dict[str, Any]:
    """The Tổng quan ``plan`` block of a ``month_plan.range_plan`` answer."""

    def bar(key: str) -> dict[str, Any]:
        return {
            "now": r[f"actual_{key}"],
            "goal": r[f"goal_{key}"],
            "baseline": r[f"baseline_{key}"],
            "uplift": r[f"uplift_{key}"],
            "ahead": r[f"ahead_{key}"],
        }

    return {
        "product_id": r.get("product_id"),
        "from": r["from"],
        "to": r["to"],
        "days": r["days"],
        "day": r["day"],
        "today_marker": r["today_marker"],
        "gmv": bar("gmv"),
        "profit": bar("profit"),
    }


async def _plan_block(
    session: AsyncSession,
    shop_id: uuid.UUID,
    view: PeriodView | None,
    window: Window,
    product_id: str | None = None,
    plan_last: date | None = None,
) -> dict[str, Any] | None:
    """The Kế hoạch card of the selected period: actual vs the goal built from the RUNNING cards
    of Kế hoạch (``month_plan.range_plan``; no goal when no card is running)."""
    from juli_backend.services.shopee_recommendations import month_plan

    try:
        r = await month_plan.range_plan(
            session,
            shop_id,
            window.start,
            plan_last or window.end,
            scope=month_plan.SCOPE_RUNNING,
            now=datetime.now(UTC),
            actual_to=window.end,
            view=view,
            product_id=product_id,
        )
    except RowsNotMaterialized:
        return None
    return plan_block_of(r)


async def _figures(
    session: AsyncSession,
    shop_id: uuid.UUID,
    view: PeriodView,
    window: Window,
    product_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    ids = (product_id,) if product_id else ()
    base = funnel.base_from_rows(rows, str(shop_id), item_ids=ids)
    shop_card = _by_source(funnel.base_from_rows(rows, str(shop_id))).get(CARD)
    ads_known = shop_card is not None and shop_card.ads is not None
    ad_types = view.data.ads_daily.by_type
    body = split_rows(
        base,
        ad_types=None if product_id else ad_types,
        ads_known=ads_known,
        ads_fallback=_product_ads(view, product_id, ads_known),
        affiliate_fallback=_product_affiliate(view, product_id),
    )
    return body, _kpis(view, base, product_id)


async def split_figures(
    session: AsyncSession,
    shop_id: uuid.UUID,
    view: PeriodView,
    window: Window,
    product_id: str | None = None,
) -> dict[str, Any]:
    """``{"rows", "kpis"}`` of ``channel_split`` for a view the caller already loaded (no second
    read of the window, no previous period, no plan block): what a per-product loop needs."""
    body_rows, kpis = await _figures(session, shop_id, view, window, product_id)
    return {"rows": body_rows, "kpis": kpis}


_CELLS = ("views", "clicks", "ctr", "ctor", "aov", "gmv", "orders")


async def channel_split(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations import month_plan

    now = datetime.now(UTC)
    span = await month_plan.running_range(session, shop_id, product_id, now=now)
    plan_last: date | None = None
    if period == PLAN_PERIOD:
        # "Cả kế hoạch": the running cards' span, cut at the newest data day (no rows beyond it)
        anchor = as_of or await loaders.default_as_of(session, shop_id)
        if span is not None and anchor is not None and span[0] <= anchor:
            period, start, end, plan_last = "custom", span[0], min(span[1], anchor), span[1]
        else:
            period = "30d"
    loaded = await _load(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    assert loaded is not None
    ctx, view, window = loaded
    body_rows, kpis = await _figures(session, shop_id, view, window, product_id)
    prev_rows: dict[str, dict[str, Any]] = {}
    prev_kpis: dict[str, Any] | None = None
    prev_window = window.previous()
    try:
        prev_view = await service.load_view(session, shop_id, ctx, prev_window, funnel=True)
        p_rows, prev_kpis = await _figures(session, shop_id, prev_view, prev_window, product_id)
        prev_rows = {r["key"]: r for r in p_rows}
    except RowsNotMaterialized:
        prev_kpis = None
    for r in body_rows:
        before = prev_rows.get(r["key"])
        r["prev"] = None if before is None else {k: before[k] for k in (*_CELLS, "share")}
    plan = await _plan_block(session, shop_id, view, window, product_id, plan_last)
    return {
        "level": "product" if product_id else "shop",
        "product_id": product_id,
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "days": window.days,
        "plan_range": None
        if span is None
        else {"from": span[0].isoformat(), "to": span[1].isoformat()},
        "updated_at": await _updated_at(session, shop_id),
        "rows": body_rows,
        "kpis": kpis,
        "kpis_prev": prev_kpis,
        "plan": plan,
    }


async def channel_split_products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """The product picker: each product with GMV, margin, its GMV by channel and the weakest
    funnel metric (:func:`weakest_metric`), biggest GMV first."""
    loaded = await _load(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    assert loaded is not None
    _ctx, view, window = loaded
    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    shop_card = _by_source(funnel.base_from_rows(rows, shop_id.hex)).get(CARD)
    ads_known = shop_card is not None and shop_card.ads is not None
    item_ids = sorted(
        {d.item_id for d in rows.product_days if d.item_id and (d.gmv or d.orders or d.views)}
        - set(view.excluded)
    )
    bases = {i: funnel.base_from_rows(rows, str(shop_id), item_ids=(i,)) for i in item_ids}
    values: dict[str, dict[str, float | None]] = {}
    for item, b in bases.items():
        views, clicks = funnel.known_total(b, "views"), funnel.known_total(b, "clicks")
        orders, gmv = b.total("orders"), b.total("gmv")
        values[item] = {
            "views": None if views is None else float(views),
            "ctr": None if _div(clicks, views) is None else float(_div(clicks, views) or 0),
            "ctor": None if _div(orders, clicks) is None else float(_div(orders, clicks) or 0),
            "aov": None if _div(gmv, orders) is None else float(_div(gmv, orders) or 0),
        }
    snaps = await loaders.load_listing_sources(session, shop_id, item_ids)
    products: list[dict[str, Any]] = []
    for item, b in bases.items():
        src = _by_source(b)
        total = b.total("gmv")
        aff = src.get(AFFILIATE)
        card = src.get(CARD)
        ads = card.ads if card is not None else None
        ads_gmv = ads.gmv if ads is not None else (Decimal(0) if ads_known else None)
        aff_gmv = aff.gmv if aff is not None else Decimal(0)
        if ads is None or not ads.gmv:
            fallback = _product_ads(view, item, ads_known)
            if fallback is not None:
                ads_gmv = fallback["gmv"]
        if aff is None or not aff.gmv:
            aff_fb = _product_affiliate(view, item)
            if aff_fb is not None:
                aff_gmv = aff_fb["gmv"]
        margin = shop_profit.scope_margin_pct(view.profit, (item,))
        header = snaps[item].header if item in snaps else None
        images = list(header.image_urls) if header and header.image_urls else []
        products.append(
            {
                "product_id": item,
                "name": view.names.get(item) or (header.title if header else None) or item,
                "image_url": images[0] if images else None,
                "gmv": num(total),
                "margin": None if margin is None else float(margin),
                "organic_gmv": num(
                    None
                    if total is None or ads_gmv is None
                    else max(total - aff_gmv - ads_gmv, Decimal(0))
                ),
                "ads_gmv": num(ads_gmv),
                "affiliate_gmv": num(aff_gmv),
                "weakest_metric": weakest_metric(values, item),
            }
        )
    products.sort(key=lambda p: -(p["gmv"] or 0))
    return {
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "products": products[:MAX_PRODUCTS],
    }
