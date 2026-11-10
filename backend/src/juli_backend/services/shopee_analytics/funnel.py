"""P98 / ADR-122 d.2-d.3: the stored funnel per source as the one read model of Lượt xem, lượt
nhấp, CTR and CTOR.

``shopee_source_metrics_daily`` (built by :mod:`.materialize`) holds, per day, six source rows
for the shop (``item_id`` NULL) and for each product the item-traffic reader covered. Here they
are summed over a window -- ratios always from the window's sums, never averaged per day -- into
the engine's :class:`FunnelBase`:

- **Shop scope:** the shop rows. A day of the window that has a ShopMetrics row but no source rows
  yet (built before migration 126 / the backfill) adds its đơn / GMV / lợi nhuận to the residual
  ``chenh_lech_nguon``, so đơn always add up to Tổng quan.
- **Product scope:** the products' source rows when they cover every day the products sold or were
  seen; otherwise one all-source funnel from ``shopee_product_metrics_daily`` stands in
  (``source_detail="all_sources"``, carried on ``the_san_pham_khac``) and the card says so.
- **CTR = lượt nhấp ÷ lượt xem; CTOR = đơn (ShopMetrics) ÷ lượt nhấp**, so Lượt xem × CTR × CTOR =
  Đơn exactly. The residual has orders but never traffic (``FunnelBase.total`` counts it as 0).
- A non-residual source with no traffic rows and no đơn over the whole window, while the scope
  has traffic elsewhere, is a source with nothing in it: its views / clicks are 0, not unknown.
- Ads (``AdShare``) sit on ``the_san_pham_khac`` only; a field Shopee never posted for the scope is
  ``None`` (product rows carry spend and GMV only).

``contribution_rate`` -- the profit of one extra đồng of GMV at today's prices -- is the scope's
contribution before ads ÷ its order-line GMV over the window (the ``profit_per_gmv`` the voucher
evaluator uses, ``shopee_recommendations.evaluate``), ``None`` when a line has no real giá vốn.

:func:`load_rows` reads the window once; :func:`base_from_rows` is pure (tests build rows by
hand); :func:`flow_tables` turns the rows into the flow tables every screen reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_metrics import (
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_analytics.windows import Window, resolve_window
from juli_backend.services.shopee_builder.engine.contract import (
    RESIDUAL,
    SOURCES,
    AdShare,
    FunnelBase,
    Source,
    SourceFunnel,
)
from juli_backend.services.shopee_profit.flows import (
    FLOW_LABELS,
    FLOW_ORDER,
    FlowMetrics,
    FlowTable,
    FlowTables,
)

if TYPE_CHECKING:
    from juli_backend.services.shopee_analytics.compute import PeriodView

ZERO = Decimal(0)
#: the one line every payload that shows CTOR carries (ADR-122 d.2)
CTOR_NOTE = "CTOR = đơn (theo Tổng quan) ÷ lượt nhấp"
BASIS_SOURCES = "source_funnel"
BASIS_FLOWS = "flow_tables"
FALLBACK_NOTE = (
    "Chưa dựng phễu theo nguồn cho kỳ này: lượt xem, lượt nhấp lấy từ bảng lưu lượng như trước."
)
ALL_SOURCES_NOTE = "Sản phẩm chưa có số theo từng nguồn: dùng phễu gộp mọi nguồn."
#: where the all-source funnel of a product sits (the card's source: every driver reaches it)
ALL_SOURCES_KEY: Source = "the_san_pham_khac"
ADS_SOURCE: Source = "the_san_pham_khac"
_ADS_FIELDS = ("views", "clicks", "orders", "gmv", "spend")


# -- stored rows -------------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceDay:
    """One ``shopee_source_metrics_daily`` row (``item_id`` None = the shop)."""

    day: date
    item_id: str | None
    source: str
    views: int | None
    clicks: int | None
    orders: int
    gmv: Decimal
    profit: Decimal | None
    ads_views: int | None = None
    ads_clicks: int | None = None
    ads_orders: int | None = None
    ads_gmv: Decimal | None = None
    ads_spend: Decimal | None = None


@dataclass(frozen=True)
class ScopeDay:
    """One ShopMetrics day row: the shop's (``item_id`` None) or a product's."""

    day: date
    item_id: str | None
    orders: int
    gmv: Decimal
    profit: Decimal | None
    views: int | None = None
    clicks: int | None = None
    ads_spend: Decimal | None = None


@dataclass(frozen=True)
class FunnelRows:
    """A window's stored funnel rows plus the ShopMetrics day rows they must add up to."""

    window: Window
    sources: tuple[SourceDay, ...] = ()
    shop_days: tuple[ScopeDay, ...] = ()
    product_days: tuple[ScopeDay, ...] = ()

    @property
    def available(self) -> bool:
        """The shop has source rows in this window (else the screens keep today's tables)."""
        return any(r.item_id is None for r in self.sources)

    def covered_days(self) -> int:
        return len({r.day for r in self.sources if r.item_id is None})


async def load_rows(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> FunnelRows:
    """The window's source rows, shop day rows and product day rows (three reads)."""
    t = ShopeeSourceMetricsDaily
    src = (
        (
            await session.execute(
                select(t).where(t.shop_id == shop_id, t.day >= window.start, t.day <= window.end)
            )
        )
        .scalars()
        .all()
    )
    s = ShopeeShopMetricsDaily
    shop = (
        (
            await session.execute(
                select(s).where(
                    s.shop_id == shop_id,
                    s.order_type == ORDER_TYPE,
                    s.day >= window.start,
                    s.day <= window.end,
                )
            )
        )
        .scalars()
        .all()
    )
    p = ShopeeProductMetricsDaily
    prod = (
        (
            await session.execute(
                select(p).where(
                    p.shop_id == shop_id,
                    p.order_type == ORDER_TYPE,
                    p.item_id != RESIDUAL_ITEM,
                    p.day >= window.start,
                    p.day <= window.end,
                )
            )
        )
        .scalars()
        .all()
    )
    return FunnelRows(
        window,
        tuple(
            SourceDay(
                r.day,
                r.item_id,
                r.source,
                r.views,
                r.clicks,
                r.orders or 0,
                r.gmv or ZERO,
                r.profit,
                r.ads_views,
                r.ads_clicks,
                r.ads_orders,
                r.ads_gmv,
                r.ads_spend,
            )
            for r in src
        ),  # fmt: skip
        tuple(
            ScopeDay(
                r.day,
                None,
                r.orders or 0,
                r.gmv or ZERO,
                None if (r.detail or {}).get("profit_partial") else r.profit,
            )
            for r in shop
        ),
        tuple(
            ScopeDay(
                r.day,
                r.item_id,
                r.orders or 0,
                r.gmv or ZERO,
                r.profit,
                r.views,
                r.clicks,
                r.ads_spend,
            )
            for r in prod
        ),  # fmt: skip
    )


# -- sums --------------------------------------------------------------------------------------


def _plus(a: Any, b: Any) -> Any:
    if b is None:
        return a
    return b if a is None else a + b


@dataclass
class _Acc:
    """One source of one scope over the window: sums; None = no day had a value.

    P99: ``profit`` sums the days whose profit is known (None only when no day is), and
    ``profit_orders`` their đơn, so one day without giá vốn no longer blanks the window's profit;
    ``profit_days`` / ``days`` count the days with a known profit / with any row."""

    views: int | None = None
    clicks: int | None = None
    orders: int = 0
    gmv: Decimal = ZERO
    profit: Decimal | None = None
    profit_orders: int = 0
    ads: dict[str, Any] = field(default_factory=lambda: dict.fromkeys(_ADS_FIELDS))
    day_set: set[date] = field(default_factory=set)
    profit_day_set: set[date] = field(default_factory=set)

    @property
    def days(self) -> int:
        return len(self.day_set)

    @property
    def profit_days(self) -> int:
        return len(self.profit_day_set)

    def add(self, orders: int, gmv: Decimal, profit: Decimal | None, day: date) -> None:
        self.orders += orders
        self.gmv += gmv
        self.day_set.add(day)
        if profit is not None:
            self.profit = (self.profit or ZERO) + profit
            self.profit_orders += orders
            self.profit_day_set.add(day)

    def add_row(self, r: SourceDay) -> None:
        self.views = _plus(self.views, r.views)
        self.clicks = _plus(self.clicks, r.clicks)
        self.add(r.orders, r.gmv, r.profit, r.day)
        for f, v in zip(
            _ADS_FIELDS,
            (r.ads_views, r.ads_clicks, r.ads_orders, r.ads_gmv, r.ads_spend),
            strict=True,
        ):
            self.ads[f] = _plus(self.ads[f], v)


@dataclass
class _Scope:
    accs: dict[str, _Acc]
    detail: Literal["per_source", "all_sources"]


def _active(d: ScopeDay) -> bool:
    return bool(d.orders or d.gmv or d.views or d.clicks)


def _item_per_source(rows: FunnelRows, item_id: str) -> bool:
    """The product's source rows cover every day it sold or was seen."""
    covered = {r.day for r in rows.sources if r.item_id == item_id}
    active = {d.day for d in rows.product_days if d.item_id == item_id and _active(d)}
    return active <= covered


def _scope(rows: FunnelRows, item_ids: Sequence[str]) -> _Scope:
    accs: dict[str, _Acc] = {s: _Acc() for s in SOURCES}
    if not item_ids:
        covered = {r.day for r in rows.sources if r.item_id is None}
        for r in rows.sources:
            if r.item_id is None and r.source in accs:
                accs[r.source].add_row(r)
        for d in rows.shop_days:
            if d.day not in covered:
                accs[RESIDUAL].add(d.orders, d.gmv, d.profit, d.day)
        return _Scope(accs, "per_source")
    wanted = set(item_ids)
    if all(_item_per_source(rows, i) for i in wanted):
        pairs = {(r.item_id, r.day) for r in rows.sources if r.item_id in wanted}
        for r in rows.sources:
            if r.item_id in wanted and r.source in accs:
                accs[r.source].add_row(r)
        for d in rows.product_days:
            if d.item_id in wanted and (d.item_id, d.day) not in pairs:
                accs[RESIDUAL].add(d.orders, d.gmv, d.profit, d.day)
        return _Scope(accs, "per_source")
    one = _Acc()
    for d in rows.product_days:
        if d.item_id in wanted:
            one.views = _plus(one.views, d.views)
            one.clicks = _plus(one.clicks, d.clicks)
            one.add(d.orders, d.gmv, d.profit, d.day)
            one.ads["spend"] = _plus(one.ads["spend"], d.ads_spend)
    return _Scope({ALL_SOURCES_KEY: one}, "all_sources")


def _ads(acc: _Acc) -> AdShare | None:
    if all(acc.ads[f] is None for f in _ADS_FIELDS):
        return None
    a = acc.ads
    return AdShare(
        *(None if a[f] is None else Decimal(a[f]) for f in _ADS_FIELDS)  # views .. spend
    )


def _days(scope: _Scope) -> tuple[int, int]:
    """(days with a known profit, days with any row) over the scope's sources."""
    known: set[date] = set()
    seen: set[date] = set()
    for a in scope.accs.values():
        known |= a.profit_day_set
        seen |= a.day_set
    return len(known), len(seen)


def _sources(scope: _Scope) -> tuple[SourceFunnel, ...]:
    has_traffic = any(a.views is not None for k, a in scope.accs.items() if k != RESIDUAL)
    # a source without a known day adds 0 to a scope that has one; with no known day at all the
    # scope's profit stays unknown. A source with no rows is 0, as before.
    any_known = any(a.profit is not None for a in scope.accs.values())
    out: list[SourceFunnel] = []
    for key, a in scope.accs.items():
        profit = a.profit
        if profit is None and (any_known or not a.days):
            profit = ZERO
        views, clicks = a.views, a.clicks
        if key == RESIDUAL:
            views = clicks = None
        elif has_traffic and views is None and clicks is None and a.orders == 0 and a.gmv == 0:
            views = clicks = 0  # a source with nothing in it, not an unknown one
        out.append(
            SourceFunnel(
                source=cast(Source, key),
                views=None if views is None else Decimal(views),
                clicks=None if clicks is None else Decimal(clicks),
                orders=Decimal(a.orders),
                gmv=a.gmv,
                profit=profit,
                ads=_ads(a) if key == ADS_SOURCE else None,
                profit_orders=Decimal(a.profit_orders),
            )
        )
    return tuple(out)


def base_from_rows(
    rows: FunnelRows,
    shop_id: str,
    *,
    item_ids: Sequence[str] = (),
    contribution_rate: Decimal | None = None,
) -> FunnelBase:
    """The window's :class:`FunnelBase` for the shop (``item_ids`` empty) or those products.
    Pure. A scope without traffic rows keeps views / clicks ``None`` ("chưa có dữ liệu")."""
    scope = _scope(rows, item_ids)
    profit_days, days = _days(scope)
    return FunnelBase(
        shop_id=shop_id,
        scope="products" if item_ids else "shop",
        item_ids=tuple(item_ids),
        window_start=rows.window.start,
        window_end=rows.window.end,
        sources=_sources(scope),
        contribution_rate=contribution_rate,
        source_detail=scope.detail,
        profit_days=profit_days,
        days=days,
    )


def known_total(base: FunnelBase, name: Literal["views", "clicks"]) -> Decimal | None:
    """Views / clicks of the scope: the sources that report them (the residual never does);
    None when none does. Equals ``base.total(name)`` whenever every source reports."""
    values = [
        getattr(s, name)
        for s in base.sources
        if s.source != RESIDUAL and getattr(s, name) is not None
    ]
    return sum(values, ZERO) if values else None


@dataclass(frozen=True)
class FunnelNumbers:
    """Lượt xem, lượt nhấp, CTR and CTOR of one scope, CTOR on the given đơn (ShopMetrics)."""

    views: Decimal | None
    clicks: Decimal | None
    orders: Decimal | None
    basis: str
    note: str | None = None

    @property
    def ctr(self) -> Decimal | None:
        if self.views is None or self.clicks is None or self.views <= 0:
            return None
        return self.clicks / self.views

    @property
    def ctor(self) -> Decimal | None:
        if self.clicks is None or self.orders is None or self.clicks <= 0:
            return None
        return self.orders / self.clicks


def numbers(base: FunnelBase, orders: int | Decimal | None) -> FunnelNumbers:
    """The base's traffic with CTOR on ``orders`` (ShopMetrics đơn of the same scope)."""
    return FunnelNumbers(
        known_total(base, "views"),
        known_total(base, "clicks"),
        None if orders is None else Decimal(orders),
        BASIS_SOURCES,
        ALL_SOURCES_NOTE if base.source_detail == "all_sources" else None,
    )


# -- contribution rate -------------------------------------------------------------------------


def contribution_rate(view: PeriodView, item_ids: Iterable[str] = ()) -> Decimal | None:
    """Contribution before ads per đồng of order-line GMV of the scope's carrying lines (the
    window's prices), ``None`` without lines or when a line has no real giá vốn."""
    wanted = set(item_ids)
    lines = [
        (ln, pb)
        for ln, pb in view.pairs
        if pb.excluded_reason is None and (not wanted or ln.product_id in wanted)
    ]
    if not lines:
        return None
    if any(not view.costs.cogs_is_real(ln.sku) or pb.contribution is None for ln, pb in lines):
        return None
    gmv = sum((ln.order_value for ln, _ in lines), ZERO)
    if gmv <= 0:
        return None
    return sum((pb.contribution or ZERO for _, pb in lines), ZERO) / gmv


# -- the screens' flow tables ------------------------------------------------------------------


def _table(scope: _Scope, raw: FlowTable | None) -> FlowTable:
    """The scope's five flows plus the residual (only when non-zero), as the screens show them;
    the ads overlay stays the raw table's."""
    rows: list[FlowMetrics] = []
    for f in FLOW_ORDER:
        a = scope.accs.get(f.value, _Acc())
        old = raw.row(f.value) if raw is not None else None
        rows.append(
            FlowMetrics(
                f.value,
                FLOW_LABELS[f],
                a.views,
                a.clicks,
                a.orders,
                a.gmv,
                old.ads if old is not None else None,
            )
        )
    res = scope.accs[RESIDUAL]
    if res.orders or res.gmv:
        rows.append(FlowMetrics(RESIDUAL, FLOW_LABELS[RESIDUAL], None, None, res.orders, res.gmv))
    return FlowTable(tuple(rows), sum((r.gmv for r in rows), ZERO), sum(r.orders for r in rows))


def flow_tables(rows: FunnelRows, raw: FlowTables | None) -> FlowTables | None:
    """The screens' flow tables from the stored funnel: the shop table, and each product whose
    source rows cover its window (other products keep their traffic-table rows). ``raw`` (today's
    tables) is returned unchanged when the shop has no source rows in the window."""
    if raw is None or not rows.available:
        return raw
    shop = _table(_scope(rows, ()), raw.shop)
    products = dict(raw.products)
    for item in sorted({r.item_id for r in rows.sources if r.item_id is not None}):
        scope = _scope(rows, (item,))
        if scope.detail == "per_source":
            products[item] = _table(scope, raw.products.get(item))
    return FlowTables(shop, products)


def apply_to_view(view: PeriodView, rows: FunnelRows) -> PeriodView:
    """Make ``view`` read the stored funnel: its flow tables and ShopMetrics traffic (the screens'
    path only; the rebuild reads the raw tables)."""
    view.data.funnel = rows
    view.flows = flow_tables(rows, view.flows)
    view._metrics = None
    return view


def basis_json(rows: FunnelRows | None) -> dict[str, Any]:
    """The ``funnel`` block of a payload: where Lượt xem / CTR / CTOR come from."""
    ok = rows is not None and rows.available
    out: dict[str, Any] = {
        "basis": BASIS_SOURCES if ok else BASIS_FLOWS,
        "ctor_note": CTOR_NOTE,
        "note": None if ok else FALLBACK_NOTE,
    }
    if rows is not None:
        out["days_with_sources"] = rows.covered_days()
        out["window_days"] = rows.window.days
    return out


# -- entry points ------------------------------------------------------------------------------


async def anchor_window(session: AsyncSession, shop_id: uuid.UUID) -> Window | None:
    """The last 30 complete days ending at the Tổng quan anchor (None without Shopee data)."""
    from juli_backend.services.shopee_analytics import service

    anchor = await service.anchor_for(session, shop_id)
    return None if anchor is None else resolve_window("30d", as_of=anchor.day)


async def load_funnel_base(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    item_ids: Sequence[str] = (),
    window: Window,
    view: PeriodView | None = None,
) -> FunnelBase:
    """The "before" of an option (ADR-122 d.2) for the shop or ``item_ids`` over ``window``
    (normally :func:`anchor_window`). ``view`` = the same window's view when the caller has one
    (for ``contribution_rate``); otherwise it is loaded."""
    rows = await load_rows(session, shop_id, window)
    if view is None or view.window != window:
        from juli_backend.services.shopee_analytics import loaders, service

        ctx = await loaders.load_context(session, shop_id)
        ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
        view = await service.load_view(session, shop_id, ctx, window)
    return base_from_rows(
        rows,
        str(shop_id),
        item_ids=tuple(item_ids),
        contribution_rate=contribution_rate(view, item_ids),
    )


__all__ = [
    "ALL_SOURCES_NOTE",
    "CTOR_NOTE",
    "FALLBACK_NOTE",
    "FunnelNumbers",
    "FunnelRows",
    "ScopeDay",
    "SourceDay",
    "anchor_window",
    "apply_to_view",
    "base_from_rows",
    "basis_json",
    "contribution_rate",
    "flow_tables",
    "known_total",
    "load_funnel_base",
    "load_rows",
    "numbers",
]
