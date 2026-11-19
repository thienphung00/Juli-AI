"""`DataPort` over the analytics services and named read-only queries.

The shop is bound here, never by a model. Every call opens its own read-only session from
`read_session_factory` and rolls it back; nothing is written. Chains' numbers come from the
analytics service where it has them (overview, metric_view, channel_split, critical); the daily
series the chains need (shop / source / product rows, stock history, open cards) are named SELECTs.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ServiceData:
    def __init__(self, factory: SessionFactory, shop_id: uuid.UUID) -> None:
        self._f, self.shop = factory, shop_id

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
        if item:
            return await self._item_daily(end, item)
        return await self._q(
            """select day, gmv, orders, units, views, product_clicks as clicks, ads_spend, ads_gmv,
            complete
                 from shop_metrics_daily
                where shop_id = :s and order_type = 'confirmed' and day <= :e order by day""",
            e=end,
        )

    async def _item_daily(self, end: date, item: str) -> list[dict[str, Any]]:
        """One product's rows shaped like shop rows. A complete shop day with no product row = 0
        sales;
        views / clicks stay NULL where the product has no source rows (NULL is not 0)."""
        shop = await self._q(
            """select day, complete from shop_metrics_daily
                                 where shop_id = :s and order_type = 'confirmed' and day <= :e
                                 order by day""",
            e=end,
        )
        pr = {
            r["day"]: r
            for r in await self._q(
                """select day, sum(gmv) gmv, sum(orders) orders, sum(units) units from
                product_metrics_daily
                where shop_id = :s and order_type = 'confirmed' and item_id = :i and day <= :e
                group by day""",
                e=end,
                i=item,
            )
        }
        tr = {
            r["day"]: r
            for r in await self._q(
                """select day, sum(views) views, sum(clicks) clicks, count(views) n from
                source_metrics_daily
                where shop_id = :s and item_id = :i and day <= :e group by day""",
                e=end,
                i=item,
            )
        }
        out = []
        for r in shop:
            p_, t_ = pr.get(r["day"]), tr.get(r["day"])
            out.append(
                {
                    "day": r["day"],
                    "complete": r["complete"],
                    "gmv": (p_ or {}).get("gmv") or 0,
                    "orders": (p_ or {}).get("orders") or 0,
                    "units": (p_ or {}).get("units") or 0,
                    "views": t_["views"] if t_ and t_["n"] else None,
                    "clicks": t_["clicks"] if t_ and t_["n"] else None,
                    "ads_spend": None,
                    "ads_gmv": None,
                }
            )
        return out

    async def source_daily(self, a: date, b: date, item: str | None = None) -> list[dict[str, Any]]:
        if item:
            return await self._q(
                """select day, source, views, clicks, orders, gmv from source_metrics_daily
                                     where shop_id = :s and item_id = :i and day between :a and
                                     :b""",
                a=a,
                b=b,
                i=item,
            )
        return await self._q(
            """select day, source, views, clicks, orders, gmv from source_metrics_daily
                                 where shop_id = :s and item_id is null and day between :a and
                                 :b""",
            a=a,
            b=b,
        )

    async def product_daily(self, a: date, b: date) -> list[dict[str, Any]]:
        return await self._q(
            """select day, item_id, sum(gmv) gmv, sum(orders) orders, sum(units) units
                 from product_metrics_daily
                where shop_id = :s and order_type = 'confirmed' and day between :a and :b
                  and item_id not like 'sku:%' and item_id <> '__residual__'
                group by day, item_id""",
            a=a,
            b=b,
        )

    async def item_names(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        rows = await self._q(
            """select distinct on (item_id) item_id, name from platform_items
                                 where shop_id = :s and item_id = any(:ids) order by item_id,
                                 updated_at desc""",
            ids=ids,
        )
        return {r["item_id"]: r["name"] or r["item_id"] for r in rows}

    async def catalog_search(self, phrase: str) -> list[dict[str, Any]]:
        words = [w for w in re.split(r"\s+", phrase.strip()) if len(w) >= 2][:6]
        if not words:
            return []
        cond = " and ".join(
            f"(lower(name) like lower(:w{i}) or item_id = :raw or seller_sku = :raw)"
            for i in range(len(words))
        )
        return await self._q(
            f"""select distinct on (item_id) item_id, name from platform_items
                 where shop_id = :s and {cond}
                 order by item_id, updated_at desc limit 8""",
            raw=phrase.strip(),
            **{f"w{i}": f"%{w}%" for i, w in enumerate(words)},
        )

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
        """Open cards plus executed ones within 28 days (G4)."""
        return await self._q(
            """select kind, item_id, status, planned_start, subject_label, change_after::text as
            change_after,
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

    async def cost_lines(self, a: date, b: date, item: str | None = None) -> dict[str, Any]:
        """Ads / affiliate / offers from the channel split's KPIs; net revenue from overview
        shop_profit.
        No new formula: every figure is the analytics service's own."""
        cs = await self._svc("channel_split", period="custom", start=a, end=b, product_id=item)
        k = cs.get("kpis") or {}
        nr = None
        if item is None:
            nr = ((await self.overview(a, b)).get("shop_profit") or {}).get("net_revenue")
        return {
            "net_revenue": nr,
            "cost_ads": k.get("cost_ads"),
            "cost_affiliate": k.get("cost_affiliate"),
            "cost_offers": k.get("cost_offers"),
        }
