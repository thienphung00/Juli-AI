"""P100 redesign (board B, Phân tích): one metric, by luồng and by sản phẩm, now vs the previous
period of the same length, and the KOL section.

The arithmetic is pure (:func:`value_of`, :func:`change_of`, :func:`impact_of`, :func:`assemble`,
:func:`assemble_kol`); the loaders read the two windows and the open Đề xuất cards.

Metrics: ``views``, ``ctr``, ``ctor``, ``aov``, ``orders``, ``gmv``, ``margin``. Rates (CTR, CTOR,
AOV, margin) stay rates in every row; sums (views, orders, GMV) are totals over ``days`` and the
screen divides by ``days`` for Trung bình / ngày. CTR, CTOR and margin are fractions (0.0636).

**GMV ảnh hưởng** (``impact``, signed ₫, negative = GMV lost against the previous period): the GMV
gap the change of THIS metric explains, one factor at a time, the other factors held where the
funnel already had them (Lượt xem x CTR x CTOR x AOV = GMV):

- GMV: GMV now - GMV before.
- Đơn hàng: (đơn now - đơn before) x AOV before.
- AOV: (AOV now - AOV before) x đơn now.
- Lượt xem: (views now - views before) x GMV per view before.
- CTR: (CTR now - CTR before) x views now x CTOR before x AOV before.
- CTOR: (CTOR now - CTOR before) x clicks now x AOV before.
- Biên lợi nhuận: (margin now - margin before) x GMV now, the one profit figure (₫ of lợi nhuận).

Luồng (kênh) rows: Thẻ sản phẩm (organic = the source minus the "trong đó Quảng cáo" overlay),
Trang shop, Video, Live, DVHT Sản phẩm and DVHT Shop+ (ads report base: ``ad_base`` =
``ads_report``, đơn đã đặt, no views / clicks), Tiếp thị liên kết (no views). Margin is a shop /
product figure: the luồng rows and ``total`` leave it ``None``. ``total`` is the shop (or the
asked luồng / product) as a whole. A figure with no data is ``None``, never 0.

The open Đề xuất count of a row = the open cards (seller: published; Ops: drafts too) whose
critical metric is this metric (:data:`METRIC_OF_KPI`, the reverse of the Xem phân tích link) for
that product (or that luồng).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import channel_split, funnel, kol, loaders, service
from juli_backend.services.shopee_analytics import kol_labels as labels
from juli_backend.services.shopee_analytics.fmt import frac, num
from juli_backend.services.shopee_analytics.queries import NoShopeeData
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import FunnelBase, SourceFunnel
from juli_backend.services.shopee_recommendations import store
from juli_backend.services.shopee_recommendations.kol_cards import KOL_KINDS
from juli_backend.services.shopee_recommendations.refs import (
    OPS_STATUSES,
    SELLER_STATUSES,
    CardRef,
    _ref,
)

METRICS = ("views", "ctr", "ctor", "aov", "orders", "gmv", "margin")
CHANNELS = ("the_san_pham", "trang_shop", "video", "live", "ads_product", "ads_shop", "lien_ket")
#: a card's critical kpi / wiring key -> the metric it moves (anything unlisted moves GMV)
METRIC_OF_KPI: dict[str, str] = {
    "views": "views",
    "ctr": "ctr",
    "ctor": "ctor",
    "aov": "aov",
    "orders": "orders",
    "gmv": "gmv",
    "bien": "margin",
    "margin": "margin",
    "disc": "margin",
    "sale": "orders",
    "roas": "gmv",
    "ads_gmv": "gmv",
    "lien_ket": "gmv",
    "none": "gmv",
}
_SOURCE_OF_CHANNEL = {
    "the_san_pham": channel_split.CARD,
    "trang_shop": channel_split.SHOP_PAGE,
    "video": channel_split.VIDEO,
    "live": channel_split.LIVE,
    "lien_ket": channel_split.AFFILIATE,
}
_CHANNEL_OF_FLOW = {
    channel_split.CARD: "the_san_pham",
    channel_split.SHOP_PAGE: "trang_shop",
    channel_split.VIDEO: "video",
    channel_split.LIVE: "live",
    channel_split.AFFILIATE: "lien_ket",
}
MAX_PRODUCTS = 200
ZERO = Decimal(0)


@dataclass(frozen=True)
class Cell:
    """One scope over one window: sums, plus the margin (a fraction) where one exists."""

    views: Decimal | None = None
    clicks: Decimal | None = None
    orders: Decimal | None = None
    gmv: Decimal | None = None
    margin: Decimal | None = None


def _div(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None or b <= 0 else a / b


def value_of(cell: Cell | None, metric: str) -> Decimal | None:
    """The metric's value of a cell (rates as fractions / đồng, sums as totals)."""
    if cell is None:
        return None
    if metric == "ctr":
        return _div(cell.clicks, cell.views)
    if metric == "ctor":
        return _div(cell.orders, cell.clicks)
    if metric == "aov":
        return _div(cell.gmv, cell.orders)
    return getattr(cell, metric)


def change_of(now: Decimal | None, before: Decimal | None) -> float | None:
    """Relative change vs the previous period (0.12 = +12 %); None without a positive base."""
    if now is None or before is None or before <= 0:
        return None
    return float(round((now - before) / before, 6))


def impact_of(metric: str, now: Cell | None, before: Cell | None) -> Decimal | None:
    """The GMV gap this metric's change explains (see the module docstring); None when a factor
    is unknown."""
    if now is None or before is None:
        return None
    n, b = value_of(now, metric), value_of(before, metric)
    if n is None or b is None:
        return None
    aov_b = value_of(before, "aov")
    if metric == "gmv":
        return n - b
    if metric == "orders":
        return None if aov_b is None else (n - b) * aov_b
    if metric == "aov":
        return None if now.orders is None else (n - b) * now.orders
    if metric == "views":
        per_view = _div(before.gmv, before.views)
        return None if per_view is None else (n - b) * per_view
    if metric == "ctr":
        ctor_b = value_of(before, "ctor")
        if now.views is None or ctor_b is None or aov_b is None:
            return None
        return (n - b) * now.views * ctor_b * aov_b
    if metric == "ctor":
        if now.clicks is None or aov_b is None:
            return None
        return (n - b) * now.clicks * aov_b
    if metric == "margin":
        return None if now.gmv is None else (n - b) * now.gmv
    return None


def _out(v: Decimal | None, metric: str) -> int | float | None:
    if v is None:
        return None
    return frac(v) if metric in ("ctr", "ctor", "margin") else num(v)


def row_of(
    key: str, metric: str, now: Cell | None, before: Cell | None, **extra: Any
) -> dict[str, Any]:
    n, b = value_of(now, metric), value_of(before, metric)
    impact = impact_of(metric, now, before)
    return {
        "key": key,
        "now": _out(n, metric),
        "prev": _out(b, metric),
        "change": change_of(n, b),
        "impact": None if impact is None else num(impact),
        **extra,
    }


# -- cells of the funnel -------------------------------------------------------------------


def _by_source(base: FunnelBase) -> dict[str, SourceFunnel]:
    return {str(s.source): s for s in base.sources}


def _src_cell(s: SourceFunnel | None) -> Cell | None:
    return None if s is None else Cell(s.views, s.clicks, s.orders, s.gmv)


def card_organic(base: FunnelBase, *, ads_known: bool) -> Cell | None:
    """Thẻ sản phẩm without the ads overlay (None when the overlay is unknown at shop level)."""
    src = _by_source(base)
    card = src.get(channel_split.CARD)
    if card is None:
        return None
    ads = card.ads
    if ads is None:
        if base.scope == "products" and ads_known:
            return _src_cell(card)
        return None

    def sub(a: Decimal | None, b: Decimal | None) -> Decimal | None:
        return None if a is None or b is None else a - b

    return Cell(
        sub(card.views, ads.views),
        sub(card.clicks, ads.clicks),
        sub(card.orders, ads.orders),
        sub(card.gmv, ads.gmv),
    )


def channel_cell(base: FunnelBase, channel: str | None, *, ads_known: bool = True) -> Cell | None:
    """A base's cell for one luồng, or all of it (``channel`` None / "all")."""
    if channel in (None, "all"):
        return Cell(
            funnel.known_total(base, "views"),
            funnel.known_total(base, "clicks"),
            base.total("orders"),
            base.total("gmv"),
        )
    if channel == "the_san_pham":
        return card_organic(base, ads_known=ads_known)
    src = _by_source(base)
    if channel in _SOURCE_OF_CHANNEL:
        cell = _src_cell(src.get(_SOURCE_OF_CHANNEL[channel]))
        if channel == "lien_ket" and cell is not None:
            return replace(cell, views=None)
        return cell
    if channel == "ads":
        card = src.get(channel_split.CARD)
        a = card.ads if card else None
        return None if a is None else Cell(a.views, a.clicks, a.orders, a.gmv)
    return Cell(
        funnel.known_total(base, "views"),
        funnel.known_total(base, "clicks"),
        base.total("orders"),
        base.total("gmv"),
    )


def _ad_cell(cell: Mapping[str, Decimal] | None) -> Cell | None:
    return None if cell is None else Cell(None, None, Decimal(cell["orders"]), Decimal(cell["gmv"]))


# -- cards ---------------------------------------------------------------------------------


def metric_of_ref(ref: CardRef) -> str:
    return METRIC_OF_KPI.get(ref.kpi or "", "gmv")


def channel_of_ref(ref: CardRef) -> str | None:
    if ref.family == "affiliate" or ref.flow == channel_split.AFFILIATE:
        return "lien_ket"
    if ref.family == "ads":
        return "ads_product"
    return _CHANNEL_OF_FLOW.get(ref.flow or "")


def card_counts(refs: Iterable[CardRef], metric: str) -> tuple[dict[str, int], dict[str, int]]:
    """(by product id, by luồng key) open cards that move ``metric``."""
    by_product: dict[str, int] = defaultdict(int)
    by_channel: dict[str, int] = defaultdict(int)
    for r in refs:
        if metric_of_ref(r) != metric:
            continue
        for p in set(r.products):
            by_product[p] += 1
        ch = channel_of_ref(r)
        if ch:
            by_channel[ch] += 1
    return dict(by_product), dict(by_channel)


# -- assembly (pure) -----------------------------------------------------------------------


def assemble(
    metric: str,
    *,
    now: funnel.FunnelRows,
    before: funnel.FunnelRows,
    shop_key: str,
    ad_types_now: Mapping[str, Mapping[str, Decimal]] | None,
    ad_types_before: Mapping[str, Mapping[str, Decimal]] | None,
    item_ids: Sequence[str],
    names: Mapping[str, str],
    margin_now: Mapping[str, Decimal | None],
    margin_before: Mapping[str, Decimal | None],
    refs: Sequence[CardRef] = (),
    channel: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    """The metric view of two windows. ``margin_*``: product id -> margin fraction."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {list(METRICS)}")
    by_product, by_channel = card_counts(refs, metric)
    shop_now = funnel.base_from_rows(now, shop_key)
    shop_before = funnel.base_from_rows(before, shop_key)
    ads_known_now = _ads_known(shop_now)
    ads_known_before = _ads_known(shop_before)

    # luồng rows (the shop, or one product)
    scope_ids = (product_id,) if product_id else ()
    c_now = funnel.base_from_rows(now, shop_key, item_ids=scope_ids)
    c_before = funnel.base_from_rows(before, shop_key, item_ids=scope_ids)
    channels: list[dict[str, Any]] = []
    for key in ("the_san_pham", "trang_shop", "video", "live"):
        channels.append(
            row_of(
                key,
                metric,
                _no_margin(channel_cell(c_now, key, ads_known=ads_known_now), metric),
                _no_margin(channel_cell(c_before, key, ads_known=ads_known_before), metric),
                cards=by_channel.get(key, 0),
            )
        )
    if product_id:
        ads_p = (channel_cell(c_now, "ads"), channel_cell(c_before, "ads"))
        ads_rows: list[tuple[str, Cell | None, Cell | None]] = [("ads_product", *ads_p)]
    else:
        pn, sn = channel_split._ad_report(ad_types_now)
        pb, sb = channel_split._ad_report(ad_types_before)
        ads_rows = [
            ("ads_product", _ad_cell(pn), _ad_cell(pb)),
            ("ads_shop", _ad_cell(sn), _ad_cell(sb)),
        ]
    for key, n, b in ads_rows:
        channels.append(
            row_of(
                key,
                metric,
                _no_margin(n, metric),
                _no_margin(b, metric),
                cards=by_channel.get(key, 0),
                ad_base="ads_report",
            )
        )
    channels.append(
        row_of(
            "lien_ket",
            metric,
            _no_margin(channel_cell(c_now, "lien_ket"), metric),
            _no_margin(channel_cell(c_before, "lien_ket"), metric),
            cards=by_channel.get("lien_ket", 0),
        )
    )

    # sản phẩm rows (restricted to a luồng when one is asked)
    products: list[dict[str, Any]] = []
    for item in item_ids:
        pn_base = funnel.base_from_rows(now, shop_key, item_ids=(item,))
        pb_base = funnel.base_from_rows(before, shop_key, item_ids=(item,))
        cn = channel_cell(pn_base, channel, ads_known=ads_known_now)
        cb = channel_cell(pb_base, channel, ads_known=ads_known_before)
        if cn is not None:
            cn = replace(cn, margin=margin_now.get(item))
        if cb is not None:
            cb = replace(cb, margin=margin_before.get(item))
        products.append(
            row_of(
                item,
                metric,
                cn,
                cb,
                product_id=item,
                name=names.get(item) or item,
                cards=by_product.get(item, 0),
            )
        )
    products.sort(key=lambda r: (r["impact"] is None, r["impact"] or 0, r["name"]))
    days = now.window.days
    total = row_of(
        "total",
        metric,
        _no_margin(channel_cell(c_now, channel, ads_known=ads_known_now), metric),
        _no_margin(channel_cell(c_before, channel, ads_known=ads_known_before), metric),
        cards=sum(by_product.values()),
    )
    return {
        "metric": metric,
        "channel": channel,
        "product_id": product_id,
        "from": now.window.start.isoformat(),
        "to": now.window.end.isoformat(),
        "days": days,
        "prev_from": before.window.start.isoformat(),
        "prev_to": before.window.end.isoformat(),
        "total": total,
        "channels": channels,
        "products": products[:MAX_PRODUCTS],
    }


def _no_margin(cell: Cell | None, metric: str) -> Cell | None:
    """Margin is not a luồng figure: a luồng row of that metric has no cell."""
    return None if metric == "margin" else cell


def _ads_known(base: FunnelBase) -> bool:
    card = _by_source(base).get(channel_split.CARD)
    return card is not None and card.ads is not None


# -- KOL section (pure) --------------------------------------------------------------------


def kol_split(channel: str) -> str:
    """Which of the section's three GMV buckets a KOL channel belongs to."""
    label = (labels.channel_label(channel) or "").casefold()
    if label == "shopee video":
        return "video"
    if label in ("shopee live", "trong shopee (live)"):
        return "live"
    return "other"


def assemble_kol(
    model: kol.KolModel,
    before: kol.KolModel | None,
    *,
    flow_totals: Mapping[str, Decimal | None] | None,
    kol_card_counts: Mapping[tuple[str, str], int] | None = None,
    days: int,
) -> dict[str, Any]:
    """The KOL section: totals, and one row per KOL x sản phẩm x kênh with the previous period."""
    counts = kol_card_counts or {}
    prev = {(r.kol_key, r.item_id, r.channel): r for r in (before.rows if before else [])}
    rows: list[dict[str, Any]] = []
    split = {"video": ZERO, "live": ZERO, "other": ZERO}
    for r in model.rows:
        p = prev.get((r.kol_key, r.item_id, r.channel))
        split[kol_split(r.channel)] += r.gmv
        rows.append(
            {
                "kol_key": r.kol_key,
                "handle": r.handle,
                "channel": r.channel,
                "channel_label": labels.channel_label(r.channel),
                "item_id": r.item_id,
                "product_name": r.product_name,
                "clicks": num(r.kol_clicks),
                "orders": r.orders,
                "gmv": num(r.gmv),
                "commission": num(r.commission),
                "profit": num(r.net_profit),
                "prev_gmv": None if p is None else num(p.gmv),
                "prev_profit": None if p is None else num(p.net_profit),
                "change": change_of(r.gmv, None if p is None else p.gmv),
                "cards": counts.get((r.kol_key, r.item_id), 0),
            }
        )
    rows.sort(key=lambda x: (-(x["gmv"] or 0), x["handle"], x["item_id"]))
    flow = flow_totals or {}
    totals = kol._totals(list(model.rows))
    clicks = flow.get("clicks")
    orders = flow.get("orders")
    gmv = flow.get("gmv")
    return {
        "days": days,
        "totals": {
            "clicks": num(clicks),
            "orders": totals["orders"] if orders is None else num(orders),
            "gmv": totals["gmv"] if gmv is None else num(gmv),
            "video_gmv": num(split["video"]),
            "live_gmv": num(split["live"]),
            "other_gmv": num(split["other"]),
        },
        "rows": rows,
    }


# -- loaders -------------------------------------------------------------------------------


async def open_cards(
    session: AsyncSession, shop_id: uuid.UUID, *, audience: str
) -> list[tuple[CardRef, dict[str, Any]]]:
    statuses = OPS_STATUSES if audience == "ops" else SELLER_STATUSES
    rows = await store.list_cards(session, shop_id, statuses=statuses)
    return [(_ref(p.id, card, p.product_queue, p.code), card) for p, card in rows]


def kol_counts_of(cards: Iterable[tuple[CardRef, dict[str, Any]]]) -> dict[tuple[str, str], int]:
    """(kol key, item id) -> open KOL cards."""
    out: dict[tuple[str, str], int] = defaultdict(int)
    for ref, card in cards:
        if card.get("change_kind") not in KOL_KINDS:
            continue
        key = ((card.get("candidate_extra") or {}).get("kol") or {}).get("key")
        if not key:
            continue
        for item in ref.products or ("",):
            out[(key, item)] += 1
    return dict(out)


async def _window(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    period: str,
    month: str | None,
    start: date | None,
    end: date | None,
    as_of: date | None,
) -> Window:
    window = await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise NoShopeeData(str(shop_id))
    return window


async def metric_view(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    metric: str = "gmv",
    audience: str = "seller",
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
    channel: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {list(METRICS)}")
    window = await _window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    now_view = await service.load_view(session, shop_id, ctx, window, funnel=True)
    prev_window = window.previous()
    try:
        prev_view = await service.load_view(
            session, shop_id, ctx, prev_window, funnel=True, rows="soft"
        )
    except RowsNotMaterialized:
        prev_view = None
    now_rows = now_view.data.funnel or await funnel.load_rows(session, shop_id, window)
    prev_rows = (prev_view.data.funnel if prev_view else None) or await funnel.load_rows(
        session, shop_id, prev_window
    )
    ids = {
        d.item_id for d in now_rows.product_days if d.item_id and (d.gmv or d.orders or d.views)
    } - set(now_view.excluded)
    margins_now = _margins(now_view)
    margins_before = _margins(prev_view) if prev_view else {}
    names = dict(now_view.names)
    refs = [r for r, _ in await open_cards(session, shop_id, audience=audience)]
    return assemble(
        metric,
        now=now_rows,
        before=prev_rows,
        shop_key=str(shop_id),
        ad_types_now=now_view.data.ads_daily.by_type,
        ad_types_before=prev_view.data.ads_daily.by_type if prev_view else None,
        item_ids=sorted(ids),
        names=names,
        margin_now=margins_now,
        margin_before=margins_before,
        refs=refs,
        channel=channel,
        product_id=product_id,
    )


def _margins(view: Any) -> dict[str, Decimal | None]:
    out: dict[str, Decimal | None] = {}
    for item, pp in view.profit.products.items():
        m = pp.margin_pct
        out[item] = None if m is None else Decimal(str(m)) / 100
    return out


async def kol_section(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    audience: str = "seller",
    period: str = "30d",
    month: str | None = None,
    start: date | None = None,
    end: date | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    window = await _window(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, shop_id, ctx, window)
    model = await kol.load_model(session, shop_id, ctx, view)
    before: kol.KolModel | None
    try:
        prev_view = await service.load_view(session, shop_id, ctx, window.previous())
        before = await kol.load_model(session, shop_id, ctx, prev_view)
    except RowsNotMaterialized:
        before = None
    table = view.flows.shop if view.flows else None
    aff = table.row("lien_ket") if table else None
    clicks = _affiliate_clicks(view)
    flow_totals = (
        {"clicks": clicks, "orders": Decimal(aff.orders), "gmv": aff.gmv}
        if aff is not None
        else {"clicks": clicks}
    )
    cards = await open_cards(session, shop_id, audience=audience)
    return assemble_kol(
        model,
        before,
        flow_totals=flow_totals,
        kol_card_counts=kol_counts_of(cards),
        days=window.days,
    )


def _affiliate_clicks(view: Any) -> Decimal | None:
    rows = view.data.funnel
    if rows is None:
        return None
    base = funnel.base_from_rows(rows, "x")
    cell = channel_cell(base, "lien_ket")
    return None if cell is None else cell.clicks


__all__ = [
    "CHANNELS",
    "METRICS",
    "Cell",
    "assemble",
    "assemble_kol",
    "impact_of",
    "kol_section",
    "metric_view",
    "value_of",
]
