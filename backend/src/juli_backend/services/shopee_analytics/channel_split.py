"""P100 S1 (Tổng quan): the channel split -- Organic / Quảng cáo / Tiếp thị liên kết -- of the shop
or of one product, from the stored source funnel and the two ad bases.

The split arithmetic is pure (:func:`split_rows`, :func:`weakest_metric`); the loaders below only
read a window and hand the numbers to it.

Rules (the owner's, ORY 11/10-09/11 as the sanity shape):

- Sources (Seller Centre): Thẻ sản phẩm (``the_san_pham_khac``), Trang shop (``trang_shop``), Live,
  Video, Tiếp thị liên kết (``lien_ket``) and the residual ``chenh_lech_nguon``.
- **Quảng cáo, traffic-overview base** = the "trong đó Quảng cáo" overlay of Thẻ sản phẩm
  (``AdShare``: views, clicks, orders, GMV). It sits inside the sources, never beside them.
  P100 B.4b -- **one order basis, confirmed**: the sources' đơn / GMV are ShopMetrics
  (confirmed), so the stored overlay is too (``materialize.ads_overlay``: Shopee's confirmed ads
  row, else the placed row times the card's own confirmed ÷ placed ratio).
- P100 B.4a -- **which report each cell comes from** (shop level; one basis per CTR):

  ===========================  ===============================  ==============================
  cell                         overlay has clicks               overlay has no clicks
  ===========================  ===============================  ==============================
  Quảng cáo views / clicks     overlay (traffic overview)       ads report: impressions /
                                                                clicks of product ads (every
                                                                ``ad_type_class`` product)
  Quảng cáo orders / GMV       overlay (confirmed basis)        overlay (confirmed basis)
  Thẻ sản phẩm (organic) views card - overlay views            card - overlay views; card -
                                                                report impressions when the
                                                                overlay has no views either
  Thẻ sản phẩm (organic) clicks card - overlay clicks           card - report clicks
  ===========================  ===============================  ==============================

  Every derived organic cell is clamped at 0. No report counts: the Quảng cáo clicks stay None.
- **Organic = sources - Quảng cáo - Tiếp thị liên kết.** Its four children add up to it: Thẻ sản
  phẩm (organic) = Thẻ sản phẩm + residual - the ads overlay, each cell clamped at 0 (P100 B.4b:
  a derived organic cell is never negative); Trang shop = the ``trang_shop`` segment; Video;
  Live.
- Every row carries ``prev`` (the same cells over the previous period of the same length) and
  ``share`` (of the total GMV on the traffic-overview base; ``None`` for ads-report rows).
- **Quảng cáo children, ads-report base** (never added to the traffic-overview figure): DVHT Sản
  phẩm and DVHT Shop+ = the ad types ``loaders.ad_type_class`` says so (C3; a livestream or
  unknown type is in neither row). The ads report of a day is the Connector's
  ``ads_campaign_daily`` wherever it has the day, else the daily file report. P100
  B.4c: Lượt xem = the report's impressions, CTR = clicks ÷ impressions, CTOR = orders ÷ clicks
  (broad orders, the report's own basis); a type whose days lack the counts (a day covered only
  by a period file) leaves them ``None``. At Sản phẩm level there is no Shop+ row
  and the Quảng cáo row itself is the ads-report base (per-product ad GMV and spend only).
- Tiếp thị liên kết has no views (``None``); clicks and orders only.
- A figure with no data is ``None``, never 0. An ad overlay that is missing at shop level makes
  Organic ``None`` (nothing to subtract).
"""

from __future__ import annotations

import logging
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
from juli_backend.services.metrics.registry import (
    METRICS,
    REASON_SOURCE_BREAKDOWN_MISSING,
    Platform,
    counts_in_total,
    metric_reason,
)
from juli_backend.services.shopee_analytics import funnel, loaders, service
from juli_backend.services.shopee_analytics.catalog import UNMATCHED_LABEL, Catalog
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.data_through import ads_last_day, data_through
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
from juli_backend.services.shopee_profit.ladder import (
    Ladder,
    affiliate_cost,
    covered,
    ladder_of,
    offers_cost,
    unknown_orders,
)
from juli_backend.services.shopee_profit.order_profit import counts_in_product_sales
from juli_backend.services.shopee_profit.shop_profit import product_profit_reliable

LOG = logging.getLogger(__name__)
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
_CELL_METRICS = ("views", "clicks", "ctr", "ctor", "aov", "gmv", "orders")
#: row key -> the traffic source it stands for (reason codes of a "—", W3 R-2)
_ROW_SOURCE = {
    "organic_card": CARD,
    "organic_shop": SHOP_PAGE,
    "organic_video": VIDEO,
    "organic_live": LIVE,
    "ads": "ads",
    "ads_product": "ads",
    "ads_shop": "ads",
    "affiliate": AFFILIATE,
}


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


AdTypes = Mapping[str, Mapping[str, Decimal | None]]
_COUNTS = ("impressions", "clicks")


def _ad_report(
    ad_types: AdTypes | None,
) -> tuple[dict[str, Decimal | None] | None, dict[str, Decimal | None] | None]:
    """(DVHT Sản phẩm, DVHT Shop+) of the ads report (:func:`ad_report_by_class`); a livestream or
    unknown type is in neither."""
    by = ad_report_by_class(ad_types)
    return by.get(loaders.AD_PRODUCT), by.get(loaders.AD_SHOP_PLUS)


def ad_report_by_class(ad_types: AdTypes | None) -> dict[str, dict[str, Decimal | None]]:
    """C3: the ads report per ``loaders.ad_type_class`` (only the classes present): ``{"gmv",
    "orders", "spend", "impressions", "clicks"}`` each; the classes add up to the report. A count
    one of the summed types lacks is ``None``."""
    empty: dict[str, Decimal | None] = {
        "gmv": Decimal(0), "orders": Decimal(0), "spend": Decimal(0),
        "impressions": Decimal(0), "clicks": Decimal(0),
        "rate_impressions": Decimal(0), "rate_clicks": Decimal(0), "rate_orders": Decimal(0),
    }  # fmt: skip
    out: dict[str, dict[str, Decimal | None]] = {}
    for kind, cell in (ad_types or {}).items():
        target = out.setdefault(loaders.ad_type_class(kind), dict(empty))
        for k in target:
            value, have = cell.get(k), target[k]
            if k in _COUNTS:
                target[k] = None if value is None or have is None else have + Decimal(value)
            else:
                target[k] = Decimal(have or 0) + Decimal(value or 0)
    return out


def partition_channels(
    total: Decimal | None, ads: Decimal | None, affiliate: Decimal | None
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """C4: ``(ads, affiliate, organic)`` that add up to ``total``: ads (a placed-order overlay) is
    capped at the total, affiliate at what is left, organic = the rest. An unknown ads figure
    leaves ads and organic unknown; an unknown total, everything."""
    if total is None or ads is None:
        return ads, affiliate, None
    ads_part = min(max(ads, Decimal(0)), total)
    aff_part = min(max(affiliate or Decimal(0), Decimal(0)), total - ads_part)
    return ads_part, aff_part, total - ads_part - aff_part


def _rest(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    """``a - b`` clamped at 0 (a derived organic cell is never negative); ``None`` unknown."""
    return None if a is None or b is None else max(a - b, Decimal(0))


Quad = tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]


def card_total(base: FunnelBase) -> Quad:
    """Thẻ sản phẩm + residual (views, clicks, orders, GMV), before the ads overlay comes off."""
    src = _by_source(base)
    parts = [x for x in (src.get(CARD), src.get(RESIDUAL)) if x is not None]
    return (
        _sum([x.views for x in parts]),
        _sum([x.clicks for x in parts]),
        _sum([x.orders for x in parts]),
        _sum([x.gmv for x in parts]),
    )


def overlay_cells(
    card: Quad, a: AdShare | None, product_ads: Mapping[str, Decimal | None] | None
) -> tuple[Quad | None, Quad | None]:
    """(Thẻ sản phẩm organic, Quảng cáo) cells on ONE basis (P100 B.4a, the module table):
    without overlay clicks the Quảng cáo views AND clicks come from the ads report's product
    ads; organic views = card - overlay views (else - report impressions), organic clicks =
    card - the Quảng cáo clicks; every organic cell clamped at 0. Shared by Tổng quan
    (:func:`split_rows`) and Phân tích (``metric_view``), so both show the same cells."""
    if a is None:
        return None, None
    report_imp = product_ads.get("impressions") if product_ads else None
    report_clk = product_ads.get("clicks") if product_ads else None
    ad_views, ad_clicks = a.views, a.clicks
    if ad_clicks is None and report_clk is not None:
        ad_views, ad_clicks = report_imp, report_clk
    organic = (
        _rest(card[0], a.views if a.views is not None else report_imp),
        _rest(card[1], ad_clicks),
        _rest(card[2], a.orders),
        _rest(card[3], a.gmv),
    )
    return organic, (ad_views, ad_clicks, a.orders, a.gmv)


def total_base(base: FunnelBase, platform: str = "shopee") -> FunnelBase:
    """The base whose sums are the shop (or product) total: on TikTok without the sources the
    registry keeps out of it (Tab cửa hàng overlaps the others, decision #7). Shopee: ``base``.
    A source the registry does not know is left out of the total and logged, never an error."""
    if platform == Platform.shopee:
        return base
    plat = Platform(platform)

    def counts(source: str) -> bool:
        try:
            return counts_in_total(plat, source)
        except KeyError:
            LOG.warning("unknown traffic source %r left out of the %s total", source, platform)
            return False

    return replace(base, sources=tuple(s for s in base.sources if counts(str(s.source))))


def with_reasons(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    """R-2: a cell the platform does not give is ``None`` and the row names why
    (``unavailable``: metric -> registry reason code). Shopee rows are left untouched."""
    if platform == Platform.shopee:
        return rows
    plat = Platform(platform)
    for r in rows:
        source = _ROW_SOURCE.get(r["key"])
        if source is None:
            continue
        gaps = {
            m: reason
            for m in _CELL_METRICS
            if (reason := metric_reason(plat, source, m)) is not None
        }
        if gaps:
            for m in gaps:
                r[m] = None
            r["unavailable"] = gaps
    return rows


def split_rows(
    base: FunnelBase,
    *,
    ad_types: AdTypes | None = None,
    ads_known: bool = True,
    ads_fallback: Mapping[str, Decimal] | None = None,
    affiliate_fallback: Mapping[str, Decimal] | None = None,
    platform: str = "shopee",
) -> list[dict[str, Any]]:
    """The channel table rows for ``base`` (the shop, or one product).

    ``platform`` "tiktok" (W3, decision #7): Organic = Thẻ sản phẩm + Video + LIVE (no ads to
    take off, Tab cửa hàng shown but outside the sum, its orders / CTOR / AOV "—"), Quảng cáo
    "—" with its reason code. The default is the unchanged Shopee arithmetic.

    ``ads_fallback`` / ``affiliate_fallback`` (product level): ``{"gmv", "orders"?}`` taken from
    the ads report / the order lines when the product's funnel rows carry no ad overlay or no
    Tiếp thị liên kết source; Organic then is the total minus both, never below 0.

    ``ad_types``: the ads report by type (shop level only). ``ads_known`` (product level): the
    shop has ad data at all, so a product without an ad figure has 0 ads instead of "no data"."""
    if platform != Platform.shopee:
        return _split_rows_tiktok(base, platform)
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

    a = ads
    product_ads, shop_ads = (None, None) if product_level else _ad_report(ad_types)
    org_cell, ad_cell = overlay_cells(card_total(base), a, product_ads)
    org_card = _row("organic_card", "organic", *(org_cell or (None, None, None, None)))

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
            *(ad_cell or (None, None, None, None)),
            base_name,
        )
    )
    if not product_level:
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
    if product_level:
        _partition_product_rows(rows, base.total("gmv"))
    return with_share(rows, base.total("gmv"))


#: W3.1: the rows whose figures come from the A-34 source breakdown (the sum rows included)
_BREAKDOWN_ROWS = (
    "organic",
    "organic_card",
    "organic_shop",
    "organic_video",
    "organic_live",
    "affiliate",
)
#: the sources a day with the A-34 blocks stores (the residual alone is stored without them)
BREAKDOWN_SOURCES = (CARD, SHOP_PAGE, LIVE, VIDEO, AFFILIATE)


def breakdown_missing(base: FunnelBase, platform: str) -> bool:
    """W3.1 (decision #28 Q2/Q3): a TikTok shop whose window has no day with the A-34 source
    breakdown -- no source reports any traffic, yet the residual holds the days' đơn / GMV. Every
    source is then "—" (never 0) and the gap is the whole total. A window with even one breakdown
    day is mixed: each source is the sum over the days that have it. Product scopes and Shopee
    never are."""
    if platform == Platform.shopee or base.scope != "shop":
        return False
    src = _by_source(base)
    gap = src.get(RESIDUAL)
    if gap is None or not (gap.orders or gap.gmv):
        return False
    return all(src[k].views is None for k in BREAKDOWN_SOURCES if k in src)


def gap_row(base: FunnelBase) -> dict[str, Any] | None:
    """The TikTok Chênh lệch nguồn row: the total minus the four sources, only when it is not
    0 (a window with the breakdown on every day has none)."""
    gap = _by_source(base).get(RESIDUAL)
    if gap is None or not (gap.orders or gap.gmv):
        return None
    return _row(RESIDUAL, None, None, None, gap.orders, gap.gmv)


def _blank_missing(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        if r["key"] in _BREAKDOWN_ROWS:
            for m in _CELL_METRICS:
                r[m] = None
            r["share"] = None
            r["unavailable"] = {m: REASON_SOURCE_BREAKDOWN_MISSING for m in _CELL_METRICS}


def _split_rows_tiktok(base: FunnelBase, platform: str) -> list[dict[str, Any]]:
    """The TikTok channel table (decision #7): the four A-34 sources add up to the total, Tab cửa
    hàng is a row beside them, Quảng cáo is "—". No ads overlay, residual or fallback exists."""
    src = _by_source(base)
    product_level = base.scope == "products"
    total = total_base(base, platform)

    def child(key: str, s: SourceFunnel | None) -> dict[str, Any]:
        return _row(
            key,
            "organic",
            s.views if s else None,
            s.clicks if s else None,
            s.orders if s else None,
            s.gmv if s else None,
        )

    org_card = child("organic_card", src.get(CARD))
    org_shop = child("organic_shop", src.get(SHOP_PAGE))
    org_video = child("organic_video", src.get(VIDEO))
    org_live = child("organic_live", src.get(LIVE))
    in_sum = (org_card, org_video, org_live)

    def organic(field: str) -> Decimal | None:
        values = [None if k[field] is None else Decimal(str(k[field])) for k in in_sum]
        return None if org_card[field] is None else _sum(values)

    aff = src.get(AFFILIATE)
    rows = [
        _row(
            "organic",
            None,
            organic("views"),
            organic("clicks"),
            organic("orders"),
            organic("gmv"),
        ),
        org_card,
    ]
    if not product_level or SHOP_PAGE in src:
        rows.append(org_shop)
    if not product_level or VIDEO in src:
        rows.append(org_video)
    if not product_level or LIVE in src:
        rows.append(org_live)
    base_name = "ads_report" if product_level else "traffic_overview"
    rows.append(_row("ads", None, None, None, None, None, base_name))
    if not product_level:
        rows.append(_ad_row("ads_product", None))
        rows.append(_ad_row("ads_shop", None))
    rows.append(
        _row(
            "affiliate",
            None,
            aff.views if aff else None,
            aff.clicks if aff else None,
            aff.orders if aff else None,
            aff.gmv if aff else None,
        )
    )
    gap = gap_row(base) if not product_level else None
    if gap is not None:
        rows.append(gap)
    rows = with_reasons(with_share(rows, total.total("gmv")), platform)
    if breakdown_missing(base, platform):
        _blank_missing(rows)
    return rows


def _partition_product_rows(rows: list[dict[str, Any]], total: Decimal | None) -> None:
    """C4: a product's Organic / Quảng cáo / Tiếp thị liên kết GMV add up to its GMV. The
    sources are read from different bases (the ads report is placed orders), so their sum can pass
    the GMV (prod: 105 %); Quảng cáo is capped, Tiếp thị liên kết takes what is left of the
    cap, Organic is the rest. The raw ads figure stays on the row as ``overlay_gmv``."""
    by = {r["key"]: r for r in rows}
    ads, aff, org = by.get("ads"), by.get("affiliate"), by.get("organic")
    if total is None or ads is None or aff is None or org is None or ads["gmv"] is None:
        return
    a_part, f_part, o_part = partition_channels(
        total, Decimal(str(ads["gmv"])), None if aff["gmv"] is None else Decimal(str(aff["gmv"]))
    )
    if a_part is None or o_part is None:
        return
    ads["overlay_gmv"] = ads["gmv"]
    ads["gmv"] = num(a_part)
    if aff["gmv"] is not None:
        aff["gmv"] = num(f_part)
    org["gmv"] = num(o_part)
    kids = [by[k] for k in ("organic_shop", "organic_video", "organic_live") if k in by]
    card = by.get("organic_card")
    if card is not None:
        # the Thẻ sản phẩm child is the drill-down remainder of Organic
        rest = o_part - sum(
            (Decimal(str(k["gmv"])) for k in kids if k["gmv"] is not None), Decimal(0)
        )
        card["gmv"] = num(max(rest, Decimal(0)))


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


def ad_rate_basis(
    cell: Mapping[str, Decimal | None],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(impressions, clicks, orders) the DVHT CTR / CTOR stand on: the days that carry both
    impressions and clicks (every day has them -> the window's own totals). No such day (or a
    cell built without them) -> the window totals, whose ``None`` clicks leave the rates unknown."""
    imp = cell.get("rate_impressions")
    if imp is None or imp <= 0:
        orders = cell.get("orders")
        return cell.get("impressions"), cell.get("clicks"), orders
    return imp, cell.get("rate_clicks"), cell.get("rate_orders")


def _ad_row(key: str, cell: Mapping[str, Decimal | None] | None) -> dict[str, Any]:
    """A DVHT row on the ads report's own basis: Lượt xem = impressions, CTR = clicks ÷
    impressions, CTOR = orders ÷ clicks (broad orders, the report's basis). The rates use
    :func:`ad_rate_basis` (days with both counts), so a day without clicks leaves them known."""
    if cell is None:
        return _row(key, "ads", None, None, None, None, "ads_report")
    row = _row(
        key,
        "ads",
        cell.get("impressions"),
        cell.get("clicks"),
        cell["orders"],
        cell["gmv"],
        "ads_report",
    )
    imp, clk, orders = ad_rate_basis(cell)
    row["ctr"] = frac(_div(clk, imp))
    row["ctor"] = frac(_div(orders, clk))
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
    from juli_backend.services.shopee_analytics.queries import NoShopeeData, resolve_window

    window = await resolve_window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, shop_id, ctx, window, funnel=True)
    return ctx, view, window


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
    the affiliate lines of the cost), for a product whose funnel rows have no such source."""
    if product_id is None:
        return None
    lines = [
        ln
        for ln, _ in view.pairs
        if ln.affiliate and ln.product_id == product_id and counts_in_product_sales(ln)
    ]
    if not lines:
        return None
    return {
        "gmv": sum((ln.order_value for ln in lines), Decimal(0)),
        "orders": Decimal(len({ln.order_id for ln in lines})),
    }


def _offers_cost(view: PeriodView, product_id: str | None) -> Decimal | None:
    """Ưu đãi, one combined cost (#46): Chương Trình Của Shop (khuyến mãi / flash sale) + combo /
    Deal Sốc + the shop voucher the SELLER bore (settlement ``seller_voucher_borne``, never the
    buyer-side voucher share; ``ProfitBreakdown.offer_cost``). ``None`` without order lines."""
    pairs = [(ln, pb) for ln, pb in view.pairs if product_id is None or ln.product_id == product_id]
    if not pairs:
        return None
    return offers_cost(pairs, basis=view.pairs)


ZERO_D = Decimal(0)


# -- P7 (#42 / #46 / #49): the profit split Organic / Quảng cáo / TTLK ---------------------------

#: the split's columns (registry ids where one exists); every one adds up over the channels
SPLIT_COLUMNS = (
    "gmv", "orders", "net_revenue", "cost_offers", "contribution", "cost_ads", "cost_affiliate",
    "profit",
)  # fmt: skip
SPLIT_CHANNELS = ("organic", "ads", "affiliate")
#: the shop's remainder no product owns: ads of no product, other marketing (its own row)
UNATTRIBUTED = "unattributed"


def _zero_row() -> dict[str, Decimal]:
    return dict.fromkeys(SPLIT_COLUMNS, ZERO_D)


def _sums(
    pairs: Sequence[tuple[Any, Any]], basis: Sequence[tuple[Any, Any]] | None = None
) -> dict[str, Decimal]:
    """GMV and đơn of the sale lines; doanh thu thực and Lợi nhuận đóng góp of the covered lines
    (every cost known); Ưu đãi (the combined seller cost, ``ProfitBreakdown.offer_cost``) of the
    known orders; the affiliate commission of the covered lines."""
    sale = [ln for ln, _ in pairs if counts_in_product_sales(ln)]
    unknown = unknown_orders(pairs if basis is None else basis)
    known = [pb for ln, pb in pairs if covered(pb) and ln.order_id not in unknown]
    return {
        "gmv": sum((ln.order_value for ln in sale), ZERO_D),
        "orders": Decimal(len({ln.order_id for ln in sale})),
        "net_revenue": sum((pb.revenue for pb in known), ZERO_D),
        "cost_offers": offers_cost(pairs, basis=basis) or ZERO_D,
        "contribution": sum((pb.organic_contribution or ZERO_D for pb in known), ZERO_D),
        "cost_affiliate": affiliate_cost(pairs, basis=basis) or ZERO_D,
    }


def split_scope(
    pairs: Sequence[tuple[Any, Any]],
    *,
    ads_gmv: Decimal | None,
    ads_spend: Decimal | None,
    basis: Sequence[tuple[Any, Any]] | None = None,
) -> dict[str, dict[str, Decimal]]:
    """One scope (a product, or lines no product owns) split into Organic / Quảng cáo / TTLK
    (owner decision #49):

    - TTLK = the affiliate lines, exactly (their GMV, đơn, doanh thu thực, Ưu đãi, đóng góp,
      commission).
    - The rest (N): s = min(1, GMV_QC ÷ GMV_N), GMV_QC = the ads report's GMV of the scope (the M
      rule); Quảng cáo = s x each of N's columns (GMV, đơn, doanh thu thực, Ưu đãi, đóng góp)
      plus the scope's ads spend; Organic = N − Quảng cáo. No ads report row: s = 0.
    - Lợi nhuận ròng of a channel = its đóng góp − its QC − its AFF.
    Every column adds up to the scope's total exactly."""
    aff = _sums([(ln, pb) for ln, pb in pairs if ln.affiliate], basis or pairs)
    rest = _sums([(ln, pb) for ln, pb in pairs if not ln.affiliate], basis or pairs)
    s = ZERO_D
    if ads_gmv is not None and ads_gmv > 0 and rest["gmv"] > 0:
        s = min(Decimal(1), ads_gmv / rest["gmv"])
    ads = {k: v * s for k, v in rest.items() if k != "cost_affiliate"}
    organic = {k: rest[k] - ads[k] for k in ads}
    out = {
        "organic": {**_zero_row(), **organic},
        "ads": {**_zero_row(), **ads, "cost_ads": ads_spend or ZERO_D},
        "affiliate": {**_zero_row(), **aff},
    }
    # an affiliate line's commission is TTLK's cost; a non-affiliate line carries none
    out["organic"]["cost_affiliate"] = ZERO_D
    out["ads"]["cost_affiliate"] = ZERO_D
    for row in out.values():
        row["profit"] = row["contribution"] - row["cost_ads"] - row["cost_affiliate"]
    return out


def _add_rows(a: dict[str, Decimal], b: Mapping[str, Decimal]) -> dict[str, Decimal]:
    return {k: a[k] + b.get(k, ZERO_D) for k in SPLIT_COLUMNS}


def has_profit(platform: str) -> bool:
    """Does ``platform`` have Lợi nhuận ròng at all (a registry source)? D23: a platform
    without one gets ``profit_split`` ``None``, never a split of zeros."""
    return platform in METRICS["profit"].sources


def _reconcile_to_kpi(
    rows: dict[str, dict[str, Decimal]],
    pairs: Sequence[tuple[Any, Any]],
    kpi_gmv: Decimal | None,
    kpi_orders: Decimal | None,
) -> None:
    """Decision #55 Q1: the GMV and đơn columns add up to the Tổng quan KPI totals. TTLK = the
    affiliate sale lines (đơn deduplicated per order); Quảng cáo = the ads-report share of the
    rest (``rows['ads']``, the M rule, as built per product); both capped by
    :func:`partition_channels`; Organic = the KPI total minus them. Profit columns are untouched
    (line based). A KPI total that is ``None`` leaves that column on the lines."""
    sale = [(ln, pb) for ln, pb in pairs if counts_in_product_sales(ln)]
    aff = [ln for ln, _ in sale if ln.affiliate]
    rest = [ln for ln, _ in sale if not ln.affiliate]
    aff_gmv = sum((ln.order_value for ln in aff), ZERO_D)
    aff_orders = Decimal(len({ln.order_id for ln in aff}))
    rest_gmv = sum((ln.order_value for ln in rest), ZERO_D)
    rest_orders = Decimal(len({ln.order_id for ln in rest}))
    share = ZERO_D if rest_gmv <= 0 else min(Decimal(1), rows["ads"]["gmv"] / rest_gmv)
    ads_gmv = rows["ads"]["gmv"]
    ads_orders = (rest_orders * share).to_integral_value()
    for col, total, ads, a in (
        ("gmv", kpi_gmv, ads_gmv, aff_gmv),
        ("orders", kpi_orders, ads_orders, aff_orders),
    ):
        if total is None:
            continue
        ads_part, aff_part, organic = partition_channels(total, ads, a)
        rows["ads"][col] = ads_part or ZERO_D
        rows["affiliate"][col] = aff_part or ZERO_D
        rows["organic"][col] = organic or ZERO_D


def profit_split(
    view: PeriodView,
    product_id: str | None = None,
    *,
    kpi_gmv: Decimal | None = None,
    kpi_orders: Decimal | None = None,
) -> dict[str, Any]:
    """Tổng quan's Organic / Quảng cáo / TTLK split (P7) of the shop or one product.

    Product level: :func:`split_scope` on its lines, its ads report GMV (direct, else broad) and
    its ad cost (``ProductProfit.ad_spend``, the M rule). Shop level: the SUM of every product's
    split (so Σ products = shop per channel) plus the ``unattributed`` row -- the ads no product
    owns (total campaign spend − the products' ad cost) and the other marketing costs -- stated
    as its own row, never dropped. ``total`` = the rows' sum. With ``kpi_gmv`` / ``kpi_orders``
    (the Tổng quan KPI totals of the same scope) the GMV and đơn columns are reconciled to them
    (:func:`_reconcile_to_kpi`)."""
    by_product: dict[str, list[tuple[Any, Any]]] = {}
    for ln, pb in view.pairs:
        if product_id is None or ln.product_id == product_id:
            by_product.setdefault(ln.product_id, []).append((ln, pb))
    if product_id is not None and product_id not in by_product:
        by_product[product_id] = []
    rows = {ch: _zero_row() for ch in SPLIT_CHANNELS}
    claimed = ZERO_D
    for pid, pairs in sorted(by_product.items()):
        fig = view.ads.product_figures.get(pid)
        gmv = None if fig is None else (fig.direct_gmv if fig.direct_gmv is not None else fig.gmv)
        pp = view.profit.products.get(pid)
        spend = None if pp is None else pp.ad_spend
        claimed += spend or ZERO_D
        for ch, row in split_scope(pairs, ads_gmv=gmv, ads_spend=spend, basis=view.pairs).items():
            rows[ch] = _add_rows(rows[ch], row)
    if kpi_gmv is not None or kpi_orders is not None:
        scope = [p for p in view.pairs if product_id is None or p[0].product_id == product_id]
        _reconcile_to_kpi(rows, scope, kpi_gmv, kpi_orders)
    unattributed = _zero_row()
    if product_id is None:
        ads_rest = view.profit.total_ad_spend - claimed
        other = view.profit.other_marketing_costs
        unattributed["cost_ads"] = ads_rest
        unattributed["profit"] = -ads_rest - other
        unattributed["other_marketing"] = other
    total = _zero_row()
    for row in (*rows.values(), unattributed):
        total = _add_rows(total, row)

    def js(row: Mapping[str, Decimal]) -> dict[str, Any]:
        return {k: num(v) for k, v in row.items()}

    return {
        "level": "shop" if product_id is None else "product",
        "columns": list(SPLIT_COLUMNS),
        "rows": {ch: js(r) for ch, r in rows.items()},
        UNATTRIBUTED: None if product_id is not None else js(unattributed),
        "total": js(total),
    }


def kpis_of(
    gmv: Decimal | None,
    orders: Decimal | None,
    profit: Decimal | None,
    cost_ads: Decimal | None,
    cost_affiliate: Decimal | None,
    cost_offers: Decimal | None,
    ladder: Ladder | None = None,
) -> dict[str, Any]:
    """Tổng quan's KPIs (decision #44). ``cost_marketing`` = Quảng cáo (ads report) + Tiếp thị
    liên kết + Ưu đãi (the known ones; ``None`` when none is known). With the scope's ``ladder``
    (the registry's ladder on its covered lines): Lợi nhuận gộp / đóng góp, the three margins,
    ``cost_total`` = Tổng chi phí (giá vốn + đóng gói + phí + vận chuyển + QC + AFF + Ưu đãi +
    khác) and ROI = Lợi nhuận ròng ÷ Tổng chi phí. No ladder: ``cost_total`` / ROI are ``None``
    (never ÷ the marketing costs)."""
    marketing = _sum([cost_ads, cost_affiliate, cost_offers])

    def lv(mid: str) -> Decimal | None:
        return None if ladder is None else ladder.get(mid)

    total = lv("cost_total")
    roi = None if profit is None or total is None else _div(profit, total)
    out = {
        "gmv": num(gmv),
        "orders": num(orders),
        "profit": num(profit),
        "cost_total": num(total),
        "cost_marketing": num(marketing),
        "cost_ads": num(cost_ads),
        "cost_affiliate": num(cost_affiliate),
        "cost_offers": num(cost_offers),
        "roi": frac(roi, 4),
    }
    for mid in ("cost_cogs", "cost_packaging", "cost_fees", "cost_shipping", "cost_other"):
        out[mid] = num(lv(mid))
    for mid in ("gross_profit", "contribution"):
        out[mid] = num(lv(mid))
    for mid in ("margin_gross", "margin_contribution", "margin"):
        v = lv(mid)
        out[f"{mid}_pct"] = None if v is None else float(v * 100)
    return out


#: R1: every profit level of a KPI block that is "—" outside the 70-100 % known share
WITHHELD_KPIS = (
    "profit", "gross_profit", "contribution", "margin_gross_pct", "margin_contribution_pct",
    "margin_pct", "roi",
)  # fmt: skip


def _kpis(
    view: PeriodView, base: FunnelBase, product_id: str | None, platform: str = "shopee"
) -> dict[str, Any]:
    base = total_base(base, platform)
    withheld = False
    if product_id is None:
        fig = shop_profit_of(view)
        profit, withheld = fig.profit, fig.withheld
        ads_cost: Decimal | None = view.profit.total_ad_spend
        other: Decimal | None = view.profit.other_marketing_costs
    else:
        pp = view.profit.products.get(product_id)
        profit = None if pp is None else pp.profit
        withheld = pp is not None and not product_profit_reliable(pp)  # R1: its own known share
        ads_cost = None if pp is None else pp.ad_spend
        other = ZERO_D
    pairs = [(ln, pb) for ln, pb in view.pairs if product_id is None or ln.product_id == product_id]
    ladder = (
        ladder_of(pairs, ads_spend=ads_cost, other_marketing=other, profit=profit, basis=view.pairs)
        if pairs
        else None
    )
    out = kpis_of(
        base.total("gmv"),
        base.total("orders"),
        profit,
        ads_cost,
        affiliate_cost(pairs, basis=view.pairs),
        _offers_cost(view, product_id),
        ladder,
    )
    if withheld:  # R1: the ladder would recompute its own net profit, margin and ROI
        out.update(dict.fromkeys(WITHHELD_KPIS))
    return out


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
    platform: str = "shopee",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    ids = (product_id,) if product_id else ()
    base = funnel.base_from_rows(
        rows, str(shop_id), item_ids=ids, day_totals=platform == Platform.shopee
    )
    shop_card = _by_source(funnel.base_from_rows(rows, str(shop_id))).get(CARD)
    ads_known = shop_card is not None and shop_card.ads is not None
    ad_types = view.data.ads_daily.by_type
    body = split_rows(
        base,
        ad_types=None if product_id else ad_types,
        ads_known=ads_known,
        ads_fallback=_product_ads(view, product_id, ads_known),
        affiliate_fallback=_product_affiliate(view, product_id),
        platform=platform,
    )
    return body, _kpis(view, base, product_id, platform)


async def split_figures(
    session: AsyncSession,
    shop_id: uuid.UUID,
    view: PeriodView,
    window: Window,
    product_id: str | None = None,
    platform: str = "shopee",
) -> dict[str, Any]:
    """``{"rows", "kpis"}`` of ``channel_split`` for a view the caller already loaded (no second
    read of the window, no previous period, no plan block): what a per-product loop needs."""
    body_rows, kpis = await _figures(session, shop_id, view, window, product_id, platform)
    split = _split_of(view, product_id, kpis, platform)
    return {"rows": body_rows, "kpis": kpis, "profit_split": split}


def _split_of(
    view: PeriodView, product_id: str | None, kpis: Mapping[str, Any], platform: str
) -> dict[str, Any] | None:
    """The profit split of a scope, its GMV / đơn reconciled to the scope's KPIs (#55 Q1)."""
    if not has_profit(platform):
        return None

    def dec(v: Any) -> Decimal | None:
        return None if v is None else Decimal(str(v))

    split = profit_split(
        view, product_id, kpi_gmv=dec(kpis.get("gmv")), kpi_orders=dec(kpis.get("orders"))
    )
    pp = None if product_id is None else view.profit.products.get(product_id)
    if (product_id is None and shop_profit_of(view).withheld) or (
        pp is not None and not product_profit_reliable(pp)
    ):
        # R1: the channels' profits add up to the scope's: withheld with it
        for row in (*split["rows"].values(), split[UNATTRIBUTED], split["total"]):
            if row is not None:
                row["profit"] = None
    return split


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
    platform: str = "shopee",
) -> dict[str, Any]:
    from juli_backend.services.shopee_recommendations import month_plan

    now = datetime.now(UTC)
    span = await month_plan.running_range(session, shop_id, product_id, now=now)
    plan_last: date | None = None
    if period == PLAN_PERIOD:
        # "Cả kế hoạch": the running cards' span, cut at the newest data day (no rows beyond it)
        from juli_backend.services.shopee_analytics.queries import default_anchor

        anchor = as_of or await default_anchor(session, shop_id)
        if span is not None and anchor is not None and span[0] <= anchor:
            period, start, end, plan_last = "custom", span[0], min(span[1], anchor), span[1]
        else:
            period = "30d"
    loaded = await _load(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    assert loaded is not None
    ctx, view, window = loaded
    body_rows, kpis = await _figures(session, shop_id, view, window, product_id, platform)
    prev_rows: dict[str, dict[str, Any]] = {}
    prev_kpis: dict[str, Any] | None = None
    prev_window = window.previous()
    try:
        prev_view = await service.load_view(session, shop_id, ctx, prev_window, funnel=True)
        p_rows, prev_kpis = await _figures(
            session, shop_id, prev_view, prev_window, product_id, platform
        )
        prev_rows = {r["key"]: r for r in p_rows}
    except RowsNotMaterialized:
        prev_kpis = None
    for r in body_rows:
        before = prev_rows.get(r["key"])
        r["prev"] = None if before is None else {k: before[k] for k in (*_CELLS, "share")}
    plan = await _plan_block(session, shop_id, view, window, product_id, plan_last)
    through = data_through(
        await loaders.load_freshness(session, shop_id),
        window.end,
        ads_last=ads_last_day(view.data.ads_daily.source_by_day),
    )
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
        # P100 B.5: "Số liệu đến dd/mm" per section (kpis / channels / plan)
        "data_through": through,
        "rows": body_rows,
        "kpis": kpis,
        "kpis_prev": prev_kpis,
        "plan": plan,
        # P7 (#42 / #49): Organic / Quảng cáo / TTLK of GMV, đơn, doanh thu thực, Ưu đãi, đóng góp,
        # QC, AFF and lợi nhuận ròng; None where the platform has no profit (D23)
        "profit_split": _split_of(view, product_id, kpis, platform),
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
    platform: str = "shopee",
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
    seen = {d.item_id for d in rows.product_days if d.item_id and (d.gmv or d.orders or d.views)}
    seen -= set(view.excluded)
    # C4: order lines matching no listing are not a product: no row, no selection (reported below)
    unmatched_ids = sorted(i for i in seen if Catalog.is_unmatched(i))
    item_ids = sorted(seen - set(unmatched_ids))
    shopee = platform == Platform.shopee
    bases = {
        i: funnel.base_from_rows(rows, str(shop_id), item_ids=(i,), day_totals=shopee)
        for i in item_ids
    }
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
        if platform != Platform.shopee:
            # decision #7: card + video + LIVE + affiliate are the total; no ads (None, reason in
            # the registry); Tab cửa hàng is not a channel here
            total = total_base(b, platform).total("gmv")
            ads_gmv = None
            tiktok_aff = aff.gmv if aff is not None else None
            organic_gmv = _sum(
                [x.gmv for k in (CARD, VIDEO, LIVE) if (x := src.get(k)) is not None]
            )
        margin = shop_profit.scope_margin_pct(view.profit, (item,))
        header = snaps[item].header if item in snaps else None
        images = list(header.image_urls) if header and header.image_urls else []
        # C4: the three channels partition the product's GMV (sum = GMV, 100 %). The ads report
        # is a placed-order overlay, so it is capped at the GMV; the raw figure stays in ads_overlay
        if platform != Platform.shopee:
            ads_part, aff_part, organic_part = None, tiktok_aff, organic_gmv
        else:
            ads_part, aff_part, organic_part = partition_channels(total, ads_gmv, aff_gmv)
        products.append(
            {
                "product_id": item,
                "name": view.names.get(item) or (header.title if header else None) or item,
                "image_url": images[0] if images else None,
                "gmv": num(total),
                "margin": None if margin is None else float(margin),
                "organic_gmv": num(organic_part),
                "ads_gmv": num(ads_part),
                "affiliate_gmv": num(aff_part),
                "ads_overlay_gmv": num(ads_gmv),
                "weakest_metric": weakest_metric(values, item),
            }
        )
    products.sort(key=lambda p: -(p["gmv"] or 0))
    unmatched_gmv = [
        t
        for i in unmatched_ids
        if (t := funnel.base_from_rows(rows, str(shop_id), item_ids=(i,)).total("gmv")) is not None
    ]
    return {
        "from": window.start.isoformat(),
        "to": window.end.isoformat(),
        "products": products[:MAX_PRODUCTS],
        # not a product: not selectable, shown (if at all) as a note so the totals reconcile
        "unmatched": {
            "label": UNMATCHED_LABEL,
            "gmv": num(sum(unmatched_gmv, Decimal(0))) if unmatched_gmv else None,
            "selectable": False,
        },
    }
