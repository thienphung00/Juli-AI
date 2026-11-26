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
            {
                "keys": [],
                "spend": Decimal(0),
                "gmv": Decimal(0),
                "before_ads": Decimal(0),
                "items": {},
            },
        )
        for item, sp in (r.get("items") or {}).items():
            g["items"][item] = g["items"].get(item, Decimal(0)) + Decimal(str(sp))
        g["keys"].append(r["key"])
        g["name"] = r["name"]
        g["spend"] += Decimal(str(r["spend"]))
        g["gmv"] = (
            None if g["gmv"] is None or r["gmv"] is None else g["gmv"] + Decimal(str(r["gmv"]))
        )
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
                "roas": None if g["gmv"] is None else roas_direct(g["gmv"], g["spend"]),
                "break_even": roas_break_even(g["gmv"], before)
                if before is not None and g["gmv"] is not None
                else None,
                "profit_after_ads": None if before is None else before - g["spend"],
                # the products the campaign spends on, biggest spend first (ads report by product)
                "items": sorted(g["items"], key=lambda k: -g["items"][k])[:5],
            }
        )
    return out


SHOP_SCOPE_VI = "cả shop"


def apply_shop_break_even(rows: list[dict[str, Any]], shop_be: Any) -> list[dict[str, Any]]:
    """A campaign whose own ROAS hoà vốn is unknown takes the shop's (the same figure as Tổng quan)
    and says so: `break_even_scope` = "cả shop". The campaign's own value is never replaced."""
    if shop_be is None:
        return rows
    for r in rows:
        if r.get("break_even") is None:
            r["break_even"] = float(shop_be)
            r["break_even_scope"] = SHOP_SCOPE_VI
    return rows


def _product_break_even(p: Any) -> dict[str, Any]:
    """The product's contribution before ads and ROAS hoà vốn, as the cards show them
    (`ProductProfit.contribution` / `.break_even_roas`)."""
    from juli_backend.services.shopee_analytics.fmt import ratio
    from juli_backend.services.shopee_profit.shop_profit import (
        product_break_even_roas_shown,
        product_contribution_shown,
    )

    return {  # R1: "—" (None) outside the product's 70-100 % known share
        "contribution_before_ads": product_contribution_shown(p),
        "break_even_roas": ratio(product_break_even_roas_shown(p), 2),
    }


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
                """select day, sum(gmv) gmv, sum(orders) orders, sum(units) units,
                sum(ads_spend) ads_spend, count(ads_spend) n_ads from product_metrics_daily
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
                    # decision #39: the product's own ad cost (NULL = no basis, never 0)
                    "ads_spend": (p_ or {}).get("ads_spend") if (p_ or {}).get("n_ads") else None,
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
                 from stock_history where shop_id = :s
                  and read_at >= cast(:a as date) and read_at < cast(:b as date) + 1
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

    # ------------------------------------------------------------------ entities (Track J)

    #: The shop headline basis (registry / `shopee_analytics.engine`): a confirmed line has a
    #: payment time and a quantity, and counts in đơn / GMV / AOV unless its status is a refund
    #: status (`counts_in_sales`); the day is the line's order day. Entity rows use exactly this,
    #: so they are a subset of the shop totals.
    @staticmethod
    def _sales_basis(product: bool = False) -> str:
        from juli_backend.services.shopee_profit.order_profit import REFUND_STATUSES

        refunds = ", ".join(f"'{x.value}'" for x in sorted(REFUND_STATUSES, key=lambda x: x.value))
        # owner #99: a PRODUCT's sales leave out cancelled lines; the shop-level line basis keeps
        # them, as the headline does
        if product:
            refunds += ", 'cancelled'"
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
                       and {self._sales_basis(item is not None)} and {cond}
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

    async def voucher_income(self, a: date, b: date) -> dict[str, Any]:
        """Voucher orders and the voucher part of Ưu đãi from the stored per-order income
        (`order_settlements`, the table the fee / profit loaders read): orders with
        `seller_voucher_borne > 0`, the sum of `seller_voucher_borne`, and the GMV of those
        orders from `order_lines`. Only orders that HAVE an income row count (a day without
        income is not 0); `income_to` is the last order day the income holds in the window."""
        head = (
            await self._q(
                """select count(*) as rows,
                          count(*) filter (where seller_voucher_borne > 0) as orders,
                          sum(seller_voucher_borne) as cost,
                          max(ordered_on) as income_to
                     from order_settlements
                    where shop_id = :s and platform = 'shopee' and ordered_on between :a and :b""",
                a=a,
                b=b,
            )
        )[0]
        gmv = (
            await self._q(
                f"""select coalesce(sum(deal_price * qty), 0) as gmv
                      from order_lines
                     where shop_id = :s and platform = 'shopee' and day between :a and :b
                       and {self._sales_basis()}
                       and order_ref in (select order_ref from order_settlements
                                          where shop_id = :s and platform = 'shopee'
                                            and ordered_on between :a and :b
                                            and seller_voucher_borne > 0)""",  # nosec B608 — fragments are fixed literals (registry enum)
                a=a,
                b=b,
            )
        )[0]["gmv"]
        return {
            "rows": head["rows"],
            "orders": head["orders"],
            "gmv": gmv,
            "cost": head["cost"],
            "income_to": head["income_to"],
        }

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
        from juli_backend.services.shopee_profit.shop_profit import (
            product_margin_pct_shown,
            product_profit_shown,
        )

        async with self._f() as s:
            try:
                env = await self._reco_env(s, a, b)
                p = None if env is None else env.product(item)
                if p is None:
                    return None
                return {
                    "profit": product_profit_shown(p),
                    "margin_pct": product_margin_pct_shown(p),
                    "coverage_pct": p.cost_coverage_pct,
                    "gmv": p.gmv,
                    **_product_break_even(p),
                }
            finally:
                await s.rollback()

    async def product_profit_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """Every product's profit after ads, contribution before ads and ROAS hoà vốn: the
        shared `ProductProfit` rows the cards and Phân tích read (`RecoEnv.product`)."""
        from juli_backend.services.shopee_profit.shop_profit import (
            product_margin_pct_shown,
            product_profit_shown,
        )

        async with self._f() as s:
            try:
                env = await self._reco_env(s, a, b)
                if env is None:
                    return []
                return [
                    {
                        "item_id": item,
                        "name": env.name(item),
                        "profit": product_profit_shown(p),
                        "ad_spend": p.ad_spend if env.view.ads.known_spend is not None else None,
                        "margin_pct": product_margin_pct_shown(p),
                        "gmv": p.gmv,
                        **_product_break_even(p),
                    }
                    for item, p in env.view.profit.products.items()
                ]
            finally:
                await s.rollback()

    async def campaign_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per ad campaign from the ads report (the analytics view): spend, direct GMV, profit
        before ads read by `shopee_recommendations.evaluate.campaign_profile`; ROAS and ROAS hoà
        vốn come from the metric registry. One row per campaign (`merge_campaigns`)."""
        from decimal import Decimal

        from juli_backend.services.shopee_analytics.fmt import ratio
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
                            "items": dict(c.products or {}),
                            "spend": c.spend,
                            "gmv": prof["direct_per_day"] * days if prof["direct_known"] else None,
                            # NULL is not 0: no rate = unknown, but a segment with no direct GMV
                            # contributes 0 before ads (it only spent)
                            "before_ads": prof["profit_before_ads_per_day"] * days
                            if prof["rate"] is not None and prof["direct_known"]
                            else None
                            if not prof["direct_known"]
                            else (Decimal(0) if prof["direct_per_day"] <= 0 else None),
                        }
                    )
                shop_be = ratio(env.view.profit.break_even_roas, 2)
            finally:
                await s.rollback()
        return apply_shop_break_even(merge_campaigns(raw), shop_be)

    async def budget_days(self, a: date, b: date) -> list[dict[str, Any]]:
        """Per day: the shop's ad spend, its ad orders and its summed daily budget (None when a
        campaign has no budget limit that day). The ads report rows `ads_campaign_daily`, read
        through the existing `PlatformDailyMetricsRepo`."""
        from decimal import Decimal

        from juli_backend.repositories import PlatformDailyMetricsRepo
        from juli_backend.services.shopee_recommendations.loader import ADS_DAILY

        async with self._f() as s:
            try:
                rows = await PlatformDailyMetricsRepo(s).window(
                    self.shop, datasets=[ADS_DAILY], start=a, end=b, any_item=True
                )
                plain = [(r.day, r.segment, dict(r.extra or {}), r.orders) for r in rows]
            finally:
                await s.rollback()
        per: dict[date, dict[str, Any]] = {}
        for day, seg, extra, orders in plain:
            if seg == "all":
                continue
            d = per.setdefault(
                day, {"day": day, "spend": Decimal(0), "budget": Decimal(0), "ad_orders": 0.0}
            )
            d["ad_orders"] += float(orders or 0)
            d["spend"] += Decimal(str(extra.get("cost") or 0))
            bud = extra.get("daily_budget")
            d["budget"] = (
                None if bud is None or d["budget"] is None else d["budget"] + Decimal(str(bud))
            )
        return [per[k] for k in sorted(per)]
