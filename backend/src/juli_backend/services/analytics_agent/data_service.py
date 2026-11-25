"""`DataPort` over the analytics services and named read-only queries.

The shop is bound here, never by a model. Every call opens its own read-only session from
`read_session_factory` and rolls it back; nothing is written. Chains' numbers come from the
analytics service where it has them (overview, metric_view, channel_split, critical); the daily
series the chains need (shop / source / product rows, stock history, open cards) are named SELECTs.
"""

from __future__ import annotations

import importlib
import re
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.analytics_agent.entity_sql import EntitySql

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


SHOP_SCOPE_VI = "cả shop"
#: How far back the daily series reads (the chains' baselines and freshness walk back from `as_of`).
SERIES_DAYS = 400
OPPORTUNITIES_MODULE = "juli_backend.services.shopee_recommendations.opportunities"
QUERY_MODULE = "juli_backend.services.metrics.query"
#: The registry ids a product's profit answer reads (Đóng góp = before ads and AFF; Ròng = after).
PRODUCT_PROFIT_IDS = (
    "profit",
    "margin",
    "contribution",
    "margin_contribution",
    "cost_ads",
    "cost_coverage",
    "roas_break_even",
    "gmv",
)
DAY_IDS = ("gmv", "orders", "units", "views", "clicks", "cost_ads", "ads_gmv_platform")


def _num(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def _plain(res: Any) -> dict[str, Any]:
    """A `QueryResult` as plain dicts (Decimal -> float at the edge; None stays None)."""
    if res is None:
        return {}
    return {
        "values": {k: _num(v) for k, v in dict(res.values).items()},
        "rows": [{k: _num(v) for k, v in dict(r).items()} for r in (res.rows or [])],
        "coverage": {k: _num(v) for k, v in dict(res.coverage or {}).items()},
        "partial": bool(res.partial),
        "previous": _plain(res.previous) if res.previous is not None else None,
        "built_at": res.built_at,
    }


def _fold(text_: str) -> str:
    """Lower-case without accents ("Găng" -> "gang")."""
    d = unicodedata.normalize("NFD", text_.casefold().replace("đ", "d"))
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


class ServiceData(EntitySql):
    def __init__(self, factory: SessionFactory, shop_id: uuid.UUID) -> None:
        self._f, self.shop = factory, shop_id

    async def metrics(
        self,
        ids: list[str],
        a: date,
        b: date,
        *,
        scope: str = "shop",
        items: list[str] | None = None,
        channel: str | None = None,
        campaigns: list[str] | None = None,
        group_by: str | None = None,
        compare: bool = False,
    ) -> dict[str, Any]:
        """The one metrics read: `metrics.query.query` (the shop is bound here, the session is
        read-only and rolled back). Returns plain dicts: values, rows, coverage, partial, previous,
        built_at. Missing is None, never 0."""
        q = importlib.import_module(QUERY_MODULE)
        sc = {
            "shop": lambda: q.Scope.shop(),
            "products": lambda: q.Scope.products(list(items or [])),
            "channel": lambda: q.Scope.channel_of(str(channel), list(items or [])),
            "campaigns": lambda: q.Scope.campaigns(list(campaigns or [])),
        }[scope]()
        async with self._f() as s:
            try:
                res = await q.query(
                    s, self.shop, list(ids), scope=sc, window=(a, b), group_by=group_by,
                    compare=compare,
                )  # fmt: skip
            finally:
                await s.rollback()
        return _plain(res)

    async def _opps(self, fn_name: str, *args: Any, **kw: Any) -> Any:
        mod = importlib.import_module(OPPORTUNITIES_MODULE)
        async with self._f() as s:
            try:
                return await getattr(mod, fn_name)(s, self.shop, *args, **kw)
            finally:
                await s.rollback()

    async def opportunities(
        self, *, kind: str | None = None, item: str | None = None
    ) -> list[dict[str, Any]]:
        """The stored opportunities (OPP `list_opportunities`), outcome and reason included."""
        rows = await self._opps("list_opportunities", kind=kind, item_id=item)
        return [_opp_dict(r) for r in rows]

    async def compare_options(
        self, kind: str, *, item: str | None = None, points: list[Any] | None = None
    ) -> dict[str, Any]:
        """OPP `compare`: exactly 4 options (or a reason each), priced by the engine."""
        res = await self._opps("compare", kind, item_id=item, points=points)
        return _opp_dict(res)

    async def draft_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        """OPP `draft_card(opportunity_id)`: a Juli draft card from a stored opportunity."""
        mod = importlib.import_module(OPPORTUNITIES_MODULE)
        async with self._f() as s:
            try:
                oid = uuid.UUID(str(opportunity_id))  # OPP's row key is a uuid
                return _opp_dict(await mod.draft_card(s, self.shop, oid))
            finally:
                await s.rollback()

    async def _q(self, sql: str, **p: Any) -> list[dict[str, Any]]:
        async with self._f() as s:
            try:
                res = await s.execute(text(sql), {"s": self.shop, **p})
                return [dict(r._mapping) for r in res]
            finally:
                await s.rollback()

    async def _svc(self, fn_name: str, **kw: Any) -> Any:
        from juli_backend.services.shopee_analytics import channel_split, metric_view, queries

        fn = {
            "overview": queries.overview,
            "critical": queries.critical,
            "channel_split": channel_split.channel_split,
            "metric_view": metric_view.metric_view,
        }[fn_name]
        async with self._f() as s:
            try:
                return await fn(s, self.shop, **kw)
            finally:
                await s.rollback()

    async def shop_daily(self, end: date, item: str | None = None) -> list[dict[str, Any]]:
        """Daily rows (the chains' series) from `query(group_by="day")`; a day with no GMV figure
        is not `complete` (missing is None, never 0). One product = `Scope.products([item])`."""
        res = await self.metrics(
            list(DAY_IDS),
            end - timedelta(days=SERIES_DAYS),
            end,
            scope="products" if item else "shop",
            items=[item] if item else None,
            group_by="day",
        )
        return [
            {
                "day": r["day"],
                "complete": r.get("gmv") is not None,
                "gmv": r.get("gmv"),
                "orders": r.get("orders"),
                "units": r.get("units"),
                "views": r.get("views"),
                "clicks": r.get("clicks"),
                "ads_spend": r.get("cost_ads"),
                "ads_gmv": r.get("ads_gmv_platform"),
            }
            for r in res.get("rows", [])
        ]

    async def source_totals(
        self, a: date, b: date, item: str | None = None
    ) -> list[dict[str, Any]]:
        """Per traffic source over [a, b] from `query(group_by="source")`: views, clicks, orders,
        GMV (None = the source reported nothing; never 0)."""
        res = await self.metrics(
            ["views", "clicks", "orders", "gmv"],
            a,
            b,
            scope="products" if item else "shop",
            items=[item] if item else None,
            group_by="source",
        )
        return [
            {k: r.get(k) for k in ("views", "clicks", "orders", "gmv")} | {"source": r["source"]}
            for r in res.get("rows", [])
        ]

    async def product_daily(self, a: date, b: date) -> list[dict[str, Any]]:
        """One row per product over [a, b] from `query(group_by="item")` (the window's own totals,
        dated at its first day)."""
        res = await self.metrics(
            ["gmv", "orders", "units"], a, b, scope="shop", group_by="item"
        )  # fmt: skip
        return [
            {
                "day": a,
                "item_id": r["item"],
                "gmv": r.get("gmv"),
                "orders": r.get("orders"),
                "units": r.get("units"),
            }
            for r in res.get("rows", [])
        ]

    async def _items(self) -> dict[str, tuple[str, str | None]]:
        """item_id -> (name, seller_sku), through the existing `PlatformItemsRepo` read. The
        item-level row (no variation) wins; the repository scopes every read to the shop."""
        from juli_backend.models.platform_data import ITEM_LEVEL_VARIATION
        from juli_backend.repositories.shopee_analytics import PlatformItemsRepo

        out: dict[str, tuple[str, str | None]] = {}
        async with self._f() as s:
            try:
                rows = await PlatformItemsRepo(s).all_items(self.shop)
                # copy the fields inside the session: the rollback below expires the ORM objects
                plain = [(r.item_id, r.variation_id, r.name, r.seller_sku) for r in rows]
            finally:
                await s.rollback()
        for item_id, variation_id, name, sku in sorted(
            plain, key=lambda r: r[1] != ITEM_LEVEL_VARIATION
        ):
            out.setdefault(item_id, (name or item_id, sku))
        return out

    async def item_names(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        items = await self._items()
        return {i: items[i][0] if i in items else i for i in ids}

    async def catalog_search(self, phrase: str) -> list[dict[str, Any]]:
        """Every word (>= 2 letters, accent- and case-insensitive) must be in the name; the exact
        item id or seller SKU also matches. At most 8, like the product Choice expects."""
        raw = phrase.strip()
        words = [_fold(w) for w in re.split(r"\s+", raw) if len(w) >= 2][:6]
        if not words:
            return []
        out = []
        for item_id, (name, sku) in (await self._items()).items():
            if (
                item_id == raw
                or (sku is not None and sku == raw)
                or all(w in _fold(name) for w in words)
            ):
                out.append({"item_id": item_id, "name": name})
        return out[:8]

    async def stock_events(self, a: date, b: date) -> list[dict[str, Any]]:
        return await self._q(
            """select item_id, read_at::date as day, min(available) as min_available,
                      string_agg(distinct listing_status, ',') as statuses
                 from stock_history where shop_id = :s and read_at::date between :a and :b
                group by item_id, read_at::date""",
            a=a,
            b=b,
        )

    async def open_cards(self) -> list[dict[str, Any]]:
        """Open cards plus executed ones within 28 days (G4). `kind` is the stored (coarse) proposal
        kind ("ads", "other", ...); `change_kind` is the card's own kind id (ads_budget, ...)."""
        return await self._q(
            """select kind, change_after->>'change_kind' as change_kind, item_id, status,
                      planned_start, subject_label, change_after::text as change_after,
                      code
                 from shop_proposals
                where shop_id = :s and platform = 'shopee'
                  and (status in ('draft','sent','approved','planned')
                       or (status = 'executed' and updated_at > now() - interval '28 days'))"""
        )

    async def overview(self, a: date, b: date) -> dict[str, Any]:
        return dict(await self._svc("overview", period="custom", start=a, end=b))

    async def metric_view(self, metric: str, a: date, b: date, item: str | None) -> dict[str, Any]:
        return dict(
            await self._svc(
                "metric_view", metric=metric, period="custom", start=a, end=b, product_id=item
            )
        )

    async def critical(self, a: date, b: date) -> dict[str, Any]:
        return dict(await self._svc("critical", period="custom", start=a, end=b))

    @staticmethod
    def _lines(kpis: dict[str, Any] | None, net_revenue: Any) -> dict[str, Any]:
        k = kpis or {}
        return {
            "net_revenue": net_revenue,
            "cost_ads": k.get("cost_ads"),
            "cost_affiliate": k.get("cost_affiliate"),
            "cost_offers": k.get("cost_offers"),
        }

    async def _net_revenue(self, a: date, b: date, item: str | None) -> Any:
        if item is not None:
            return None
        return ((await self.overview(a, b)).get("shop_profit") or {}).get("net_revenue")

    async def cost_lines(self, a: date, b: date, item: str | None = None) -> dict[str, Any]:
        """Ads / affiliate / offers from the channel split's KPIs; net revenue from overview
        shop_profit. No new formula: every figure is the analytics service's own."""
        cs = await self._svc("channel_split", period="custom", start=a, end=b, product_id=item)
        return self._lines(cs.get("kpis"), await self._net_revenue(a, b, item))

    async def cost_lines_pair(
        self, a1: date, b1: date, a0: date, b0: date, item: str | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Two windows of one scope in one read. The channel split also answers the window before
        it (`kpis_prev`, same length, the days before), so adjacent equal windows need ONE call
        instead of two (the cost chain read every top product twice)."""
        n = (b1 - a1).days + 1
        adjacent = b0 == a1 - timedelta(days=1) and (b0 - a0).days + 1 == n
        cs = await self._svc("channel_split", period="custom", start=a1, end=b1, product_id=item)
        now = self._lines(cs.get("kpis"), await self._net_revenue(a1, b1, item))
        if adjacent and cs.get("kpis_prev") is not None:
            before = self._lines(cs.get("kpis_prev"), await self._net_revenue(a0, b0, item))
        else:
            before = await self.cost_lines(a0, b0, item)
        return now, before

    @staticmethod
    def _profit_row(v: dict[str, Any]) -> dict[str, Any]:
        """A product's values keyed as the chains read them (registry ids -> the legacy keys)."""
        return {
            "profit": v.get("profit"),
            "margin_pct": v.get("margin"),  # registry margin is in points (42.8)
            "coverage_pct": None if v.get("cost_coverage") is None else 100 * v["cost_coverage"],
            "gmv": v.get("gmv"),
            "contribution": v.get("contribution"),
            "margin_contribution_pct": v.get("margin_contribution"),
            "ad_spend": v.get("cost_ads"),
            "break_even_roas": v.get("roas_break_even"),
        }

    async def product_profit(self, item: str, a: date, b: date) -> dict[str, Any] | None:
        res = await self.metrics(
            list(PRODUCT_PROFIT_IDS), a, b, scope="products", items=[item]
        )  # fmt: skip
        values = res.get("values") or {}
        if not values or all(v is None for v in values.values()):
            return None
        return self._profit_row(values)

    async def product_profit_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """Every product's profit after ads, contribution before ads and ROAS hoà vốn: one
        `query(group_by="item")`, the same figures the cards and Phân tích read."""
        res = await self.metrics(
            list(PRODUCT_PROFIT_IDS), a, b, scope="shop", group_by="item"
        )  # fmt: skip
        rows = [{"item_id": r["item"], **self._profit_row(r)} for r in res.get("rows", [])]
        names = await self.item_names([str(r["item_id"]) for r in rows])
        return [{**r, "name": names.get(str(r["item_id"]))} for r in rows]

    async def campaign_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per ad campaign from `query(group_by="campaign")` (stored `campaign_metrics_daily`):
        spend, GMV, ROAS and ROAS hoà vốn are the registry's. A campaign with no spend has no
        row."""
        res = await self.metrics(
            ["cost_ads", "ads_gmv_direct", "roas_direct", "roas_break_even", "contribution"],
            a,
            b,
            scope="shop",
            group_by="campaign",
        )
        shop_be = (res.get("values") or {}).get("roas_break_even")
        products = await self.campaign_products(a, b)
        out = []
        for r in res.get("rows", []):
            spend = r.get("cost_ads")
            if spend is None or spend <= 0:
                continue
            contrib = r.get("contribution")
            out.append(
                {
                    "key": r["campaign"],
                    "name": r.get("campaign_name") or r["campaign"],
                    "spend": spend,
                    "gmv": r.get("ads_gmv_direct"),
                    "roas": r.get("roas_direct"),
                    "break_even": r.get("roas_break_even") or shop_be,
                    "break_even_scope": None if r.get("roas_break_even") else SHOP_SCOPE_VI,
                    "profit_after_ads": None if contrib is None else contrib - spend,
                    "items": products.get(str(r["campaign"]), []),
                }
            )
        return out

    async def campaign_products(self, a: date, b: date) -> dict[str, list[str]]:
        """{campaign id: [item id]} (QUERY's `campaign_products`, a dimension read from the ads
        by product rows, not a fact)."""
        q = importlib.import_module(QUERY_MODULE)
        async with self._f() as s:
            try:
                got = await q.campaign_products(s, self.shop, (a, b))
            finally:
                await s.rollback()
        return {str(k): [str(i) for i in v] for k, v in dict(got).items()}

    async def budget_days(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per day: the shop's ad spend, its ad orders and its daily budget (None when no
        campaign has a limit that day): `query(scope=campaigns, group_by="day")` over the shop's
        campaigns, using the stored `daily_budget` column."""
        camps = list(await self.campaign_products(a, b))
        if not camps:
            return []
        res = await self.metrics(
            ["cost_ads", "daily_budget", "ads_orders"],
            a,
            b,
            scope="campaigns",
            campaigns=camps,
            group_by="day",
        )
        return [
            {
                "day": r["day"],
                "spend": r.get("cost_ads"),
                "budget": r.get("daily_budget"),
                "ad_orders": r.get("ads_orders"),
            }
            for r in res.get("rows", [])
        ]


def _opp_dict(obj: Any) -> Any:
    """An OPP result (dataclass, list or dict) as plain data."""
    import dataclasses

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _opp_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list | tuple):
        return [_opp_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _opp_dict(v) for k, v in obj.items()}
    return _num(obj)
