"""The one read function (decision #62, batch-1124-c-data Q1): stored daily facts -> metrics.

Every Shopee screen, the Excel export and Juli Chat read a number through :func:`query`. It
sums ONE indexed range of the stored daily rows (``*_metrics_daily``, written by
``shopee_analytics.materialize``) and evaluates every metric through
:func:`~juli_backend.services.metrics.compute.evaluate` from the summed components. Nothing
here is a formula: ratios, margins, AOV, ROAS, contribution and profit come from the registry.

Rules
- **Grain** is picked from ``scope`` + ``group_by`` (:func:`grain_of`): the shop row, the product
  rows, the channel x discount cells (shop or product), the campaign rows or the traffic-source
  rows.
- **Sums** the registry refuses (``sums_across``, e.g. product đơn into shop đơn) raise
  :class:`InvalidSum` before anything is read.
- **Missing is never 0.** A window day with no shop row is a missing day: the window's values
  are ``None`` with the reason ``day_missing`` (``allow_partial=True`` sums the days that are
  there and marks the result ``partial``); a ``group_by="day"`` row of a missing day is
  ``None``. A NULL component on a row is "not known that day"; a component no row knows is
  ``None``. A product / cell / campaign with no row in the window is ``None`` ("—"); a row of
  zeros is 0 (A8).
- **Coverage** travels with every cost-dependent metric (the registry's ``coverage`` id), and
  ``partial`` is set when it is below 100 % or a day is missing.
- **compare** reads the previous window of the same length in the same range read.

The session: pass the request's session; :func:`query` reads through the read replica when
``DATABASE_READ_URL`` is set (:mod:`juli_backend.database.read_engine`, Q5), unless the
session already is a read session or the request wrote.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.metrics import components as components_mod
from juli_backend.services.metrics.components import COMPONENTS
from juli_backend.services.metrics.compute import evaluate
from juli_backend.services.metrics.registry import METRICS

#: the shop / product rows' order basis read by default (``shopee_analytics.stored.ORDER_TYPE``)
DEFAULT_BASIS = "confirmed"
#: the product row that holds the lines no product owns (``models.shopee_metrics.RESIDUAL_ITEM``)
RESIDUAL_ITEM = "__residual__"

REASON_DAY_MISSING = "day_missing"
REASON_NO_ROWS = "no_rows"

GroupBy = Literal["day", "item", "variation", "channel", "discounted", "campaign", "source"]
GROUP_BYS: tuple[str, ...] = (
    "day",
    "item",
    "variation",
    "channel",
    "discounted",
    "campaign",
    "source",
)


class InvalidSum(ValueError):
    """A sum the registry refuses: the result would not be the number (``sums_across``)."""

    def __init__(self, component_id: str, refused: frozenset[str]) -> None:
        self.component_id = component_id
        self.refused = refused
        super().__init__(f"{component_id} may not be summed over {', '.join(sorted(refused))}")


# -- scope -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """What the numbers are of: the shop, some products, one channel or some campaigns."""

    kind: Literal["shop", "products", "channel", "campaigns"]
    ids: tuple[str, ...] = ()
    #: ``channel`` scope: organic | ads | affiliate
    channel: str | None = None

    @classmethod
    def shop(cls) -> Scope:
        return cls("shop")

    @classmethod
    def products(cls, ids: Iterable[str]) -> Scope:
        return cls("products", tuple(dict.fromkeys(str(i) for i in ids)))

    @classmethod
    def product(cls, item_id: str) -> Scope:
        return cls.products([item_id])

    @classmethod
    def channel_of(cls, name: str, item_ids: Iterable[str] = ()) -> Scope:
        return cls("channel", tuple(dict.fromkeys(str(i) for i in item_ids)), channel=name)

    @classmethod
    def campaigns(cls, ids: Iterable[str]) -> Scope:
        return cls("campaigns", tuple(dict.fromkeys(str(i) for i in ids)))


# -- grains ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Grain:
    """One stored table: its key dimensions and how its columns map to registry components."""

    name: str
    table: str
    #: the key dimensions of a row beside ``shop_id`` (``day`` always first)
    keys: tuple[str, ...]
    #: stored column -> the registry component(s) it is
    columns: Mapping[str, tuple[str, ...]]
    #: columns read as they are (not components): flags / extra figures a caller may show
    extras: tuple[str, ...] = ()
    #: has an ``order_type`` column (the basis)
    has_basis: bool = False
    #: the item key column, when the grain has one
    item_col: str | None = None


def _same(*ids: str) -> dict[str, tuple[str, ...]]:
    return {i: (i,) for i in ids}


#: the cost components FACT stores on every daily grain (CONTRACT-parallel §1 / §6)
_COSTS = (
    "net_revenue",
    "net_revenue_known",
    "cogs",
    "cogs_known_gmv",
    "packaging",
    "fees",
    "shipping_net",
    "offer_promo",
    "offer_voucher",
    "offer_combo",
    "affiliate_commission",
)
_ADS_FUNNEL = ("ads_gmv_direct", "ads_gmv_confirmed", "ads_views", "ads_clicks", "ads_orders")
_KNOWN = ("affiliate_commission_known", "ads_spend_known")

SHOP = Grain(
    "shop",
    "shop_metrics_daily",
    ("day",),
    {
        **_same("gmv", "orders", "units", "views", "ads_spend", "line_gmv", "line_orders"),
        "product_clicks": ("clicks",),
        "ads_gmv": ("ads_gmv_platform",),
        **_same(*_COSTS, "affiliate_gmv", "other_marketing", *_KNOWN, *_ADS_FUNNEL),
    },
    extras=("complete",),
    has_basis=True,
)
PRODUCT = Grain(
    "product",
    "product_metrics_daily",
    ("day", "item"),
    {
        **_same("gmv", "orders", "units", "views", "clicks", "line_gmv", "line_orders"),
        # a product's ad cost = the ads report by product (#39): the product's ``ads_spend``
        # and the registry's ``ads_spend_product`` are the same stored number
        "ads_spend": ("ads_spend", "ads_spend_product"),
        "ads_gmv": ("ads_gmv_platform",),
        **_same(*_COSTS, "affiliate_gmv", *_KNOWN, *_ADS_FUNNEL),
    },
    extras=("variation_id",),
    has_basis=True,
    item_col="item_id",
)
_CELL_COLUMNS = {
    **_same("gmv", "orders", "units", "ads_spend"),
    **_same(*_COSTS),
}
PRODUCT_CHANNEL = Grain(
    "product_channel",
    "product_channel_metrics_daily",
    ("day", "item", "channel", "discounted"),
    _CELL_COLUMNS,
    extras=("capped_gmv",),
    item_col="item_id",
)
SHOP_CHANNEL = Grain(
    "shop_channel",
    "shop_channel_metrics_daily",
    ("day", "channel", "discounted"),
    _CELL_COLUMNS,
)
CAMPAIGN = Grain(
    "campaign",
    "campaign_metrics_daily",
    ("day", "campaign"),
    {
        "spend": ("ads_spend",),
        "gmv": ("ads_gmv_platform",),
        "gmv_direct": ("ads_gmv_direct",),
        "orders": ("ads_orders",),
        "impressions": ("ads_views",),
        "clicks": ("ads_clicks",),
    },
    extras=("ad_type", "orders_direct", "contribution_products"),
)
SOURCE = Grain(
    "source",
    "source_metrics_daily",
    ("day", "source"),
    {
        **_same("views", "clicks", "orders", "gmv", "ads_views", "ads_clicks", "ads_orders"),
        "ads_gmv": ("ads_gmv_platform",),
        "ads_spend": ("ads_spend",),
    },
    item_col="item_id",
)
GRAINS: Mapping[str, Grain] = {
    g.name: g for g in (SHOP, PRODUCT, PRODUCT_CHANNEL, SHOP_CHANNEL, CAMPAIGN, SOURCE)
}
#: the key dimension -> its column
_KEY_COLUMN = {
    "day": "day",
    "item": "item_id",
    "channel": "channel",
    "discounted": "discounted",
    "campaign": "campaign_id",
    "source": "source",
    "variation": "variation_id",
}


def grain_of(scope: Scope, group_by: str | None) -> Grain:
    """The stored table that holds ``scope`` at ``group_by``."""
    if group_by is not None and group_by not in GROUP_BYS:
        raise ValueError(f"unknown group_by {group_by!r}")
    if group_by == "source":
        return SOURCE
    if scope.kind == "campaigns" or group_by == "campaign":
        return CAMPAIGN
    if scope.kind == "channel" or group_by in ("channel", "discounted"):
        return PRODUCT_CHANNEL if scope.ids or group_by == "item" else SHOP_CHANNEL
    if scope.kind == "products" or group_by in ("item", "variation"):
        return PRODUCT
    return SHOP


# -- sums_across -------------------------------------------------------------------------------

#: distinct-order counts: over days, channels and the discount split, never over products
_ORDER_DIMS = frozenset({"day", "channel", "discounted"})
_FALLBACK_SUMS: Mapping[str, frozenset[str]] = {
    "orders": _ORDER_DIMS,
    "line_orders": _ORDER_DIMS,
    "ads_orders": _ORDER_DIMS | {"campaign"},
}


def check_sum(component_id: str, dims: Iterable[str]) -> None:
    """Refuse summing ``component_id`` over ``dims`` when the registry does not allow it.

    The rule is the registry's (``ComponentDef.sums_across``, Track FACT F4); until that field
    exists the written contract rule (CONTRACT-parallel §1: đơn never over products) stands in.
    """
    dims = frozenset(str(d) for d in dims)
    if not dims:
        return
    registry_check = getattr(components_mod, "check_sum", None)
    if registry_check is not None:
        try:
            registry_check(component_id, dims)
        except ValueError as exc:
            raise InvalidSum(component_id, dims) from exc
        return
    allowed = _FALLBACK_SUMS.get(component_id)
    if allowed is None:
        return
    refused = dims - allowed
    if refused:
        raise InvalidSum(component_id, frozenset(refused))


def components_of(metric_id: str) -> frozenset[str]:
    """Every component ``metric_id`` reads (its formula, its coverage, recursively)."""
    out: set[str] = set()
    seen: set[str] = set()

    def walk(mid: str) -> None:
        if mid in seen:
            return
        seen.add(mid)
        if mid in COMPONENTS:
            out.add(mid)
            return
        metric = METRICS[mid]
        for ref in metric.components:
            walk(ref)
        if metric.coverage is not None:
            walk(metric.coverage)

    walk(metric_id)
    return frozenset(out)


def summed_dims(grain: Grain, scope: Scope, group_by: str | None) -> frozenset[str]:
    """The key dimensions a read of ``grain`` sums over (beyond the one it groups by)."""
    dims = set(grain.keys) - {group_by or ""}
    # one named item / campaign / channel is not summed over
    if "item" in dims and len(scope.ids) == 1 and scope.kind in ("products", "channel"):
        dims.discard("item")
    if "campaign" in dims and len(scope.ids) == 1 and scope.kind == "campaigns":
        dims.discard("campaign")
    if "channel" in dims and scope.channel is not None:
        dims.discard("channel")
    if "source" in dims:
        # sources overlap (Tab cửa hàng sits outside the total): a read always groups by them
        raise InvalidSum("source", frozenset({"source"}))
    # a sum over days is always allowed (every stored component is additive over days)
    dims.discard("day")
    return frozenset(dims)


# -- row sources -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Read:
    """One range read: a grain, a shop, days, and the filters the scope implies."""

    grain: Grain
    shop_id: uuid.UUID
    start: date
    end: date
    basis: str = DEFAULT_BASIS
    item_ids: tuple[str, ...] = ()
    channel: str | None = None
    campaign_ids: tuple[str, ...] = ()
    #: ``source`` grain: the shop rows (``item_id`` NULL) unless items are named
    shop_rows: bool = True


class RowSource(Protocol):
    """Where the stored rows come from: the database, or a list in a test."""

    async def rows(self, session: AsyncSession | None, read: Read) -> list[Mapping[str, Any]]: ...

    async def shop_days(
        self, session: AsyncSession | None, shop_id: uuid.UUID, start: date, end: date, basis: str
    ) -> set[date]: ...


def _matches(row: Mapping[str, Any], read: Read) -> bool:
    if row.get("shop_id") not in (None, read.shop_id, str(read.shop_id)):
        return False
    day = row["day"]
    if not read.start <= day <= read.end:
        return False
    if read.grain.has_basis and row.get("order_type", read.basis) != read.basis:
        return False
    if read.grain.item_col is not None:
        item = row.get(read.grain.item_col)
        if read.item_ids and str(item) not in read.item_ids:
            return False
        if read.grain is SOURCE and not read.item_ids and read.shop_rows and item is not None:
            return False
    if read.channel is not None and row.get("channel") != read.channel:
        return False
    return not (read.campaign_ids and str(row.get("campaign_id")) not in read.campaign_ids)


@dataclass
class MemoryRowSource:
    """Rows held in memory, keyed by table name, with the stored column names (tests)."""

    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def rows(self, session: AsyncSession | None, read: Read) -> list[Mapping[str, Any]]:
        return [r for r in self.tables.get(read.grain.table, []) if _matches(r, read)]

    async def shop_days(
        self, session: AsyncSession | None, shop_id: uuid.UUID, start: date, end: date, basis: str
    ) -> set[date]:
        read = Read(SHOP, shop_id, start, end, basis)
        return {r["day"] for r in await self.rows(session, read)}


def _table(grain: Grain) -> sa.TableClause:
    cols = {"shop_id", "day", "built_at", *grain.columns, *grain.extras}
    cols.update(_KEY_COLUMN[k] for k in grain.keys)
    if grain.has_basis:
        cols.add("order_type")
    if grain.item_col is not None:
        cols.add(grain.item_col)
    return sa.table(grain.table, *(sa.column(c) for c in sorted(cols)))


class SqlRowSource:
    """The stored tables: one indexed range read per grain (``shop_id``, ``day`` lead every key).

    Lightweight table clauses with the contract's column names, so the read does not depend on
    the ORM model of another track."""

    async def rows(self, session: AsyncSession | None, read: Read) -> list[Mapping[str, Any]]:
        if session is None:
            raise ValueError("SqlRowSource needs a session")
        t = _table(read.grain)
        c = t.c
        stmt = sa.select(t).where(c.shop_id == read.shop_id, c.day >= read.start, c.day <= read.end)
        if read.grain.has_basis:
            stmt = stmt.where(c.order_type == read.basis)
        if read.grain.item_col is not None:
            item = c[read.grain.item_col]
            if read.item_ids:
                stmt = stmt.where(item.in_(read.item_ids))
            elif read.grain is SOURCE and read.shop_rows:
                stmt = stmt.where(item.is_(None))
        if read.channel is not None:
            stmt = stmt.where(c.channel == read.channel)
        if read.campaign_ids:
            stmt = stmt.where(c.campaign_id.in_(read.campaign_ids))
        return [dict(r) for r in (await session.execute(stmt)).mappings().all()]

    async def shop_days(
        self, session: AsyncSession | None, shop_id: uuid.UUID, start: date, end: date, basis: str
    ) -> set[date]:
        if session is None:
            raise ValueError("SqlRowSource needs a session")
        t = _table(SHOP)
        stmt = sa.select(t.c.day).where(
            t.c.shop_id == shop_id,
            t.c.day >= start,
            t.c.day <= end,
            t.c.order_type == basis,
        )
        return {d if isinstance(d, date) else date.fromisoformat(str(d)) for d in
                (await session.execute(stmt)).scalars().all()}  # fmt: skip


SQL_SOURCE: RowSource = SqlRowSource()


# -- result ------------------------------------------------------------------------------------


@dataclass
class QueryResult:
    """``values`` per metric id (``None`` = no data, never 0); ``rows`` when grouped."""

    window: tuple[date, date]
    grain: str
    values: dict[str, Decimal | None]
    coverage: dict[str, Decimal | None]
    partial: bool
    built_at: datetime | None
    #: metric id -> why its value is ``None`` (``day_missing`` / ``no_rows``)
    reasons: dict[str, str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    missing_days: tuple[date, ...] = ()
    previous: QueryResult | None = None
    #: the summed components (for a caller that must show one, e.g. the export's cost lines)
    components: dict[str, Decimal | None] = field(default_factory=dict)

    def get(self, metric_id: str) -> Decimal | None:
        return self.values.get(metric_id)


def _num(v: Any) -> Decimal | None:
    if v is None:
        return None
    return v if isinstance(v, Decimal) else Decimal(str(v))


def sum_components(grain: Grain, rows: Sequence[Mapping[str, Any]]) -> dict[str, Decimal | None]:
    """Σ of each component over ``rows``; a component no row knows is ``None``."""
    acc: dict[str, Decimal | None] = {}
    for col, comps in grain.columns.items():
        known = [_num(r.get(col)) for r in rows if r.get(col) is not None]
        total = sum((k for k in known if k is not None), Decimal(0)) if known else None
        for comp in comps:
            acc[comp] = total
    return acc


def _evaluate(
    metrics: Sequence[str], comps: Mapping[str, Decimal | None], days: int
) -> tuple[dict[str, Decimal | None], dict[str, Decimal | None], bool]:
    full = {**comps, "window_days": Decimal(days)}
    values: dict[str, Decimal | None] = {}
    coverage: dict[str, Decimal | None] = {}
    partial = False
    for mid in metrics:
        if mid in COMPONENTS and mid not in METRICS:
            values[mid] = full.get(mid)
            coverage[mid] = None
            continue
        mv = evaluate(mid, full)
        values[mid] = mv.value if isinstance(mv.value, Decimal) or mv.value is None else None
        coverage[mid] = mv.coverage
        partial = partial or mv.partial
    return values, coverage, partial


def _built_at(rows: Iterable[Mapping[str, Any]]) -> datetime | None:
    stamps = [r["built_at"] for r in rows if isinstance(r.get("built_at"), datetime)]
    return max(stamps) if stamps else None


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _key_of(row: Mapping[str, Any], group_by: str) -> Any:
    v = row.get(_KEY_COLUMN[group_by])
    return str(v) if group_by in ("item", "campaign", "variation") and v is not None else v


def _window_result(
    grain: Grain,
    metrics: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    window: tuple[date, date],
    shop_days: set[date],
    group_by: str | None,
    allow_partial: bool,
) -> QueryResult:
    start, end = window
    in_window = [r for r in rows if start <= r["day"] <= end]
    days = _days(start, end)
    missing = tuple(d for d in days if d not in shop_days)
    comps = sum_components(grain, in_window)
    values, coverage, partial = _evaluate(metrics, comps, len(days))
    reasons: dict[str, str] = {}
    if missing and not allow_partial:
        values = dict.fromkeys(metrics)
        reasons = dict.fromkeys(metrics, REASON_DAY_MISSING)
    elif not in_window:
        reasons = dict.fromkeys(metrics, REASON_NO_ROWS)
    else:
        reasons = {m: REASON_NO_ROWS for m in metrics if values.get(m) is None}
    out_rows: list[dict[str, Any]] = []
    if group_by is not None:
        groups: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
        for r in in_window:
            groups[_key_of(r, group_by)].append(r)
        keys: list[Any] = days if group_by == "day" else sorted(groups, key=lambda k: str(k))
        for key in keys:
            g = groups.get(key, [])
            row_days = 1 if group_by == "day" else len(days)
            vals, cov, part = _evaluate(metrics, sum_components(grain, g), row_days)
            if group_by == "day" and key in missing:
                vals = dict.fromkeys(metrics)
            out_rows.append(
                {group_by: key, **vals, "_coverage": cov, "_partial": part, "_rows": len(g)}
            )
    return QueryResult(
        window=window,
        grain=grain.name,
        values=values,
        coverage=coverage,
        partial=partial or bool(missing),
        built_at=_built_at(in_window),
        reasons=reasons,
        rows=out_rows,
        missing_days=missing,
        components=comps,
    )


async def query(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    metrics: Sequence[str],
    *,
    scope: Scope,
    window: tuple[date, date],
    group_by: str | None = None,
    compare: bool = False,
    basis: str = DEFAULT_BASIS,
    allow_partial: bool = False,
    source: RowSource | None = None,
) -> QueryResult:
    """The metrics of ``scope`` over ``window`` (both ends included) from the stored rows.

    ``metrics`` are registry metric ids (or component ids, returned summed). ``group_by`` adds
    one row per key. ``compare`` adds ``previous``: the same number of days ending the day
    before ``window`` starts. ``source`` replaces the database (tests)."""
    for mid in metrics:
        if mid not in METRICS and mid not in COMPONENTS:
            raise KeyError(f"unknown metric id {mid!r}")
    start, end = window
    if end < start:
        raise ValueError("window ends before it starts")
    grain = grain_of(scope, group_by)
    dims = summed_dims(grain, scope, group_by)
    for mid in metrics:
        for comp in components_of(mid) if mid in METRICS else {mid}:
            check_sum(comp, dims)
    length = (end - start).days + 1
    prev = (start - timedelta(days=length), start - timedelta(days=1))
    read_from = prev[0] if compare else start
    src = source or SQL_SOURCE
    read = Read(
        grain,
        shop_id,
        read_from,
        end,
        basis,
        item_ids=scope.ids if scope.kind in ("products", "channel") else (),
        channel=scope.channel,
        campaign_ids=scope.ids if scope.kind == "campaigns" else (),
    )
    if source is None and session is not None:
        from juli_backend.database.read_engine import read_session

        async with read_session(session) as rs:
            rows = await src.rows(rs, read)
            shop_days = (
                {r["day"] for r in rows}
                if grain is SHOP
                else await src.shop_days(rs, shop_id, read_from, end, basis)
            )
    else:
        rows = await src.rows(session, read)
        shop_days = (
            {r["day"] for r in rows}
            if grain is SHOP
            else await src.shop_days(session, shop_id, read_from, end, basis)
        )
    rows = [{**r, "day": _as_date(r["day"])} for r in rows]
    result = _window_result(grain, metrics, rows, window, shop_days, group_by, allow_partial)
    if compare:
        result.previous = _window_result(
            grain, metrics, rows, prev, shop_days, group_by, allow_partial
        )
    return result


def _as_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


__all__ = [
    "GRAINS",
    "InvalidSum",
    "MemoryRowSource",
    "QueryResult",
    "Read",
    "RowSource",
    "Scope",
    "SqlRowSource",
    "check_sum",
    "components_of",
    "grain_of",
    "query",
    "sum_components",
]
