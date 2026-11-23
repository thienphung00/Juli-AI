"""`DataPort` over the analytics services and named read-only queries.

The shop is bound here, never by a model. Every call opens its own read-only session from
`read_session_factory` and rolls it back; nothing is written. Chains' numbers come from the
analytics service where it has them (overview, metric_view, channel_split, critical); the daily
series the chains need (shop / source / product rows, stock history, open cards) are named SELECTs.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _fold(text_: str) -> str:
    """Lower-case without accents ("Găng" -> "gang")."""
    d = unicodedata.normalize("NFD", text_.casefold().replace("đ", "d"))
    return "".join(c for c in d if unicodedata.category(c) != "Mn")


def merge_campaigns(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per campaign: rows with the same key, then rows with the same name (a campaign
    split over several report segments), are summed; the latest name wins. ROAS and ROAS hoà vốn
    are the registry's, evaluated on the sums. A campaign with no spend has no row."""
    from decimal import Decimal

    from juli_backend.services.analytics_agent.registry_reads import (
        roas_break_even,
        roas_direct,
    )

    groups: dict[str, dict[str, Any]] = {}
    for r in raw:
        gid = " ".join(str(r["name"]).casefold().split()) or str(r["key"])
        g = groups.setdefault(
            gid,
            {"keys": [], "spend": Decimal(0), "gmv": Decimal(0), "before_ads": Decimal(0)},
        )
        g["keys"].append(r["key"])
        g["name"] = r["name"]
        g["spend"] += Decimal(str(r["spend"]))
        g["gmv"] += Decimal(str(r["gmv"]))
        g["before_ads"] = (
            None
            if g["before_ads"] is None or r["before_ads"] is None
            else g["before_ads"] + Decimal(str(r["before_ads"]))
        )
    out = []
    for g in groups.values():
        if g["spend"] <= 0:
            continue
        before = g["before_ads"]
        out.append(
            {
                "key": g["keys"][0],
                "name": g["name"],
                "spend": g["spend"],
                "gmv": g["gmv"],
                "roas": roas_direct(g["gmv"], g["spend"]),
                "break_even": roas_break_even(g["gmv"], before) if before is not None else None,
                "profit_after_ads": None if before is None else before - g["spend"],
            }
        )
    return out


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

    # ------------------------------------------------------------------ entities (Track J)

    #: The shop headline basis (registry / `shopee_analytics.engine`): a confirmed line has a
    #: payment time and a quantity, and counts in đơn / GMV / AOV unless its status is a refund
    #: status (`counts_in_sales`); the day is the line's order day. Entity rows use exactly this,
    #: so they are a subset of the shop totals.
    @staticmethod
    def _sales_basis() -> str:
        from juli_backend.services.shopee_profit.order_profit import REFUND_STATUSES

        refunds = ", ".join(f"'{x.value}'" for x in sorted(REFUND_STATUSES, key=lambda x: x.value))
        return f"paid_at is not null and qty > 0 and status not in ({refunds})"

    async def entity_totals(
        self, kind: str, a: date, b: date, item: str | None = None
    ) -> dict[str, Any]:
        """Orders, GMV (deal price x qty) and the entity's own cost over [a, b], from the
        canonical `order_lines`: voucher = lines with a seller voucher share (cost = that share,
        registry `offer_voucher`); affiliate = lines flagged affiliate (cost = the commission of
        `affiliate_lines`). Optionally one product."""
        cond = {
            "voucher": "shop_voucher_share > 0",
            "no_voucher": "shop_voucher_share = 0",
            "affiliate": "affiliate",
            "all": "1 = 1",  # the shop's own lines on the same basis: the partition's whole
        }[kind]
        row = (
            await self._q(
                f"""select count(distinct order_ref) as orders,
                           coalesce(sum(deal_price * qty), 0) as gmv,
                           coalesce(sum(shop_voucher_share), 0) as voucher_cost
                      from order_lines
                     where shop_id = :s and platform = 'shopee' and day between :a and :b
                       and {self._sales_basis()} and {cond}
                       and (cast(:i as text) is null or item_id = cast(:i as text))""",  # nosec B608 — fragments are fixed literals (closed dict, registry enum)
                a=a,
                b=b,
                i=item,
            )
        )[0]
        cost = row["voucher_cost"]
        if kind == "affiliate":
            comm = await self._q(
                """select sum(commission) as c from affiliate_lines
                    where shop_id = :s and platform = 'shopee' and day between :a and :b
                      and coalesce(valid, true)
                      and (cast(:i as text) is null or item_id = cast(:i as text))""",
                a=a,
                b=b,
                i=item,
            )
            cost = comm[0]["c"]
        return {"orders": row["orders"], "gmv": row["gmv"], "cost": cost}

    async def voucher_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """One row per voucher code: orders, GMV, the voucher's cost."""
        return await self._q(
            f"""select voucher_code as code, count(distinct order_ref) as orders,
                       coalesce(sum(deal_price * qty), 0) as gmv,
                       coalesce(sum(shop_voucher_share), 0) as cost
                  from order_lines
                 where shop_id = :s and platform = 'shopee' and day between :a and :b
                   and {self._sales_basis()} and shop_voucher_share > 0
                   and voucher_code is not null
                 group by voucher_code order by sum(deal_price * qty) desc""",  # nosec B608 — fragments are fixed literals (registry enum)
            a=a,
            b=b,
        )

    async def _reco_env(self, s: AsyncSession, a: date, b: date) -> Any:
        from dataclasses import replace

        from juli_backend.services.shopee_analytics import loaders, service
        from juli_backend.services.shopee_recommendations.env import RecoEnv

        window = await service.resolve(s, self.shop, period="custom", start=a, end=b)
        if window is None:
            return None
        ctx = await loaders.load_context(s, self.shop)
        ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
        view = await service.load_view(s, self.shop, ctx, window, funnel=True, rows="soft")
        return RecoEnv(ctx=ctx, view=view, as_of=b)

    async def product_profit(self, item: str, a: date, b: date) -> dict[str, Any] | None:
        async with self._f() as s:
            try:
                env = await self._reco_env(s, a, b)
                p = None if env is None else env.product(item)
                if p is None:
                    return None
                return {
                    "profit": p.profit,
                    "margin_pct": p.margin_pct,
                    "coverage_pct": p.cost_coverage_pct,
                    "gmv": p.gmv,
                }
            finally:
                await s.rollback()

    async def campaign_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per ad campaign from the ads report (the analytics view): spend, direct GMV, profit
        before ads read by `shopee_recommendations.evaluate.campaign_profile`; ROAS and ROAS hoà
        vốn come from the metric registry. One row per campaign (`merge_campaigns`)."""
        from decimal import Decimal

        from juli_backend.services.shopee_recommendations.evaluate import campaign_profile

        raw: list[dict[str, Any]] = []
        async with self._f() as s:
            try:
                env = await self._reco_env(s, a, b)
                if env is None:
                    return []
                days = Decimal(env.window_days)
                for c in env.view.ads.campaigns:
                    prof = campaign_profile(env, c.key)
                    if prof is None:
                        continue
                    raw.append(
                        {
                            "key": c.key,
                            "name": c.name or c.key,
                            "spend": c.spend,
                            "gmv": prof["direct_per_day"] * days,
                            # NULL is not 0: no contribution rate = profit before ads unknown
                            "before_ads": prof["profit_before_ads_per_day"] * days
                            if prof["rate"] is not None
                            else None,
                        }
                    )
            finally:
                await s.rollback()
        return merge_campaigns(raw)

    async def budget_days(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per day: the shop's ad spend and its summed daily budget (None when a campaign has no
        budget limit that day). The ads report rows `ads_campaign_daily`, read through the
        existing `PlatformDailyMetricsRepo`."""
        from decimal import Decimal

        from juli_backend.repositories import PlatformDailyMetricsRepo
        from juli_backend.services.shopee_recommendations.loader import ADS_DAILY

        async with self._f() as s:
            try:
                rows = await PlatformDailyMetricsRepo(s).window(
                    self.shop, datasets=[ADS_DAILY], start=a, end=b, any_item=True
                )
                plain = [(r.day, r.segment, dict(r.extra or {})) for r in rows]
            finally:
                await s.rollback()
        per: dict[date, dict[str, Any]] = {}
        for day, seg, extra in plain:
            if seg == "all":
                continue
            d = per.setdefault(day, {"day": day, "spend": Decimal(0), "budget": Decimal(0)})
            d["spend"] += Decimal(str(extra.get("cost") or 0))
            bud = extra.get("daily_budget")
            d["budget"] = (
                None if bud is None or d["budget"] is None else d["budget"] + Decimal(str(bud))
            )
        return [per[k] for k in sorted(per)]
