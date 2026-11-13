"""P100 S1 (Tổng quan): the channel split -- Organic / Quảng cáo / Tiếp thị liên kết -- of the shop
or of one product, from the stored source funnel and the two ad bases.

The split arithmetic is pure (:func:`split_rows`, :func:`weakest_metric`); the loaders below only
read a window and hand the numbers to it.

Rules (the owner's, ORY 11/10-09/11 as the sanity shape):

- Sources (Seller Centre): Thẻ sản phẩm (``the_san_pham_khac``), Trang shop (``trang_shop``), Live,
  Video, Tiếp thị liên kết (``lien_ket``) and the residual ``chenh_lech_nguon``.
- **Quảng cáo, traffic-overview base** = the "trong đó Quảng cáo" overlay of Thẻ sản phẩm
  (``AdShare``: views, clicks, placed orders, GMV). It sits inside the sources, never beside them.
- **Organic = sources - Quảng cáo - Tiếp thị liên kết.** Thẻ sản phẩm (organic) = Thẻ sản phẩm +
  Live + Video + residual - the ads overlay; Shop (organic) = the ``trang_shop`` segment, pulled
  out of Thẻ sản phẩm. The two children add up to Organic.
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

SHOP_PLUS_KIND = "ads_shop"
CARD, SHOP_PAGE, LIVE, VIDEO, AFFILIATE = (
    "the_san_pham_khac",
    "trang_shop",
    "live",
    "video",
    "lien_ket",
)
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
) -> list[dict[str, Any]]:
    """The channel table rows for ``base`` (the shop, or one product).

    ``ad_types``: the ads report by type (shop level only). ``ads_known`` (product level): the
    shop has ad data at all, so a product without an ad figure has 0 ads instead of "no data"."""
    src = _by_source(base)
    product_level = base.scope == "products"
    card, shop_page, aff = src.get(CARD), src.get(SHOP_PAGE), src.get(AFFILIATE)
    others = [src[k] for k in (LIVE, VIDEO, RESIDUAL) if k in src]
    ads: AdShare | None = card.ads if card is not None else None
    if ads is None and product_level and ads_known:
        ads = AdShare(Decimal(0), Decimal(0), None, Decimal(0), Decimal(0))

    def card_part(field: str) -> Decimal | None:
        """Thẻ sản phẩm + Live + Video + residual, before the ads overlay comes off."""
        parts = [card, *others]
        return _sum([getattr(s, field) for s in parts if s is not None])

    card_views = card_part("views")
    card_clicks = card_part("clicks")
    card_orders = card_part("orders")
    card_gmv = card_part("gmv")
    a = ads
    org_card = _row(
        "organic_card",
        "organic",
        _minus(card_views, a.views) if a else None,
        _minus(card_clicks, a.clicks) if a else None,
        _minus(card_orders, a.orders) if a else None,
        _minus(card_gmv, a.gmv) if a else None,
    )
    org_shop = _row(
        "organic_shop",
        "organic",
        shop_page.views if shop_page else None,
        shop_page.clicks if shop_page else None,
        shop_page.orders if shop_page else None,
        shop_page.gmv if shop_page else None,
    )
    kids = (org_card, org_shop)

    def organic(field: str) -> Decimal | None:
        values = [None if k[field] is None else Decimal(str(k[field])) for k in kids]
        # a child without data does not blank the parent unless it is the only one that could count
        return None if org_card[field] is None else _sum(values)

    org_views, org_clicks = organic("views"), organic("clicks")
    org_orders, org_gmv = organic("orders"), organic("gmv")
    rows = [_row("organic", None, org_views, org_clicks, org_orders, org_gmv), org_card]
    if not product_level or shop_page is not None:
        rows.append(org_shop)
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
    return rows


def _ad_row(key: str, cell: Mapping[str, Decimal] | None) -> dict[str, Any]:
    row = _row(
        key,
        "ads",
        None,
        None,
        None if cell is None else cell["orders"],
        None if cell is None else cell["gmv"],
        "ads_report",
    )
    return row


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


def _kpis(view: PeriodView, base: FunnelBase, product_id: str | None) -> dict[str, Any]:
    if product_id is None:
        profit = shop_profit_of(view).profit
        ads_cost: Decimal | None = view.profit.total_ad_spend
    else:
        pp = view.profit.products.get(product_id)
        profit = None if pp is None else pp.profit
        ads_cost = None if pp is None else pp.ad_spend
    return {
        "gmv": num(base.total("gmv")),
        "orders": num(base.total("orders")),
        "profit": num(profit),
        "ads_cost": num(ads_cost),
        "affiliate_cost": num(_affiliate_cost(view, product_id)),
    }


async def _plan_block(
    session: AsyncSession,
    shop_id: uuid.UUID,
    mtd_view: PeriodView | None,
    anchor: date,
) -> dict[str, Any] | None:
    """The month card: month to date vs the goals built from the RUNNING cards of Kế hoạch --
    the one computation ``month_plan.month_plan(scope="running")`` shared with the Kế hoạch
    screen (no goal when no card is running). ``now`` is the month to date up to ``anchor``."""
    from juli_backend.services.shopee_recommendations import month_plan

    try:
        m = await month_plan.month_plan(
            session,
            shop_id,
            scope=month_plan.SCOPE_RUNNING,
            now=datetime.now(UTC),
            anchor=anchor,
            mtd_view=mtd_view,
        )
    except RowsNotMaterialized:
        return None
    return plan_block_of(m)


def plan_block_of(m: Mapping[str, Any]) -> dict[str, Any]:
    """The Tổng quan ``plan`` block of a ``month_plan`` answer."""
    return {
        "month": m["month"],
        "day": m["day"],
        "days_in_month": m["days_in_month"],
        "gmv": {
            "now": m["mtd_gmv"],
            "goal": m["goal_gmv"],
            "baseline": m["baseline_gmv"],
            "uplift": m["uplift_gmv"],
        },
        "profit": {
            "now": m["mtd_profit"],
            "goal": m["goal_profit"],
            "baseline": m["baseline_profit"],
            "uplift": m["uplift_profit"],
        },
    }


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
    loaded = await _load(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    assert loaded is not None
    ctx, view, window = loaded
    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    ids = (product_id,) if product_id else ()
    base = funnel.base_from_rows(rows, str(shop_id), item_ids=ids)
    ad_types = view.data.ads_daily.by_type
    shop_card = _by_source(funnel.base_from_rows(rows, str(shop_id))).get(CARD)
    ads_known = shop_card is not None and shop_card.ads is not None
    body_rows = split_rows(base, ad_types=None if product_id else ad_types, ads_known=ads_known)
    anchor = window.end
    mtd_start = anchor.replace(day=1)
    month_view: PeriodView | None = None
    if window.start != mtd_start:
        try:
            month_view = await service.load_view(
                session, shop_id, ctx, Window(mtd_start, anchor), funnel=True
            )
        except RowsNotMaterialized:
            month_view = None
    mtd_view = (
        month_view if month_view is not None else (view if window.start == mtd_start else None)
    )
    plan = await _plan_block(session, shop_id, mtd_view, anchor)
    return {
        "level": "product" if product_id else "shop",
        "product_id": product_id,
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "updated_at": await _updated_at(session, shop_id),
        "rows": body_rows,
        "kpis": _kpis(view, base, product_id),
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
        pp = view.profit.products.get(item)
        header = snaps[item].header if item in snaps else None
        images = list(header.image_urls) if header and header.image_urls else []
        products.append(
            {
                "product_id": item,
                "name": view.names.get(item) or (header.title if header else None) or item,
                "image_url": images[0] if images else None,
                "gmv": num(total),
                "margin": None if pp is None or pp.margin_pct is None else float(pp.margin_pct),
                "organic_gmv": num(
                    None if total is None or ads_gmv is None else total - aff_gmv - ads_gmv
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
