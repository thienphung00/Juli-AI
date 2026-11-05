"""P92 B-1 .. B-5: load what the builder needs, evaluate up to four versions of mixed kinds,
compare them, and save the chosen one through the existing manual-card path.

Nothing here computes a formula of its own: ``translate.to_variant`` turns a typed version into a
variant, ``manual.build_variant`` builds its card with the existing evaluators and lift model,
``outcome.shape`` lays the same block out for every kind.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import PlatformItemSnapshotsRepo
from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder import catalogue, copurchase, outcome, response
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
from juli_backend.services.shopee_builder.translate import Translation, lst_fold, to_variant
from juli_backend.services.shopee_builder.variations import economics, variation_rows
from juli_backend.services.shopee_recommendations import loader, manual
from juli_backend.services.shopee_recommendations.env import RecoEnv

HISTORY_DAYS_90 = 90
RESPONSE_PRODUCTS = 15
ERROR_NO_DATA = manual.ERROR_NO_DATA

PRICE_SCALED = ("product_discount", "price", "flash_sale")


class NoShopeeData(LookupError):
    """The shop has no Shopee numbers to anchor a window on."""


async def load_view90(
    session: AsyncSession, shop_id: uuid.UUID, as_of: date | None
) -> tuple[ShopContext, PeriodView, date]:
    anchor = as_of or await loaders.default_as_of(session, shop_id)
    if anchor is None:
        raise NoShopeeData(str(shop_id))
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{anchor:%Y-%m}"))
    window = Window(anchor - timedelta(days=HISTORY_DAYS_90 - 1), anchor)
    view = await service.load_view(session, shop_id, ctx, window)
    return ctx, view, anchor


# ------------------------------------------------------------------------------ B-1: picker


async def products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    as_of: date | None = None,
    query: str | None = None,
    include_excluded: bool = False,
    sort: str = "gmv_90d",
    limit: int = catalogue.DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    ctx, view, anchor = await load_view90(session, shop_id, as_of)
    return catalogue.picker(
        ctx,
        view,
        anchor,
        query=query,
        include_excluded=include_excluded,
        sort=sort,
        limit=limit,
        offset=offset,
    )


# ----------------------------------------------------------------------- B-2: variations


async def _snapshot_variations(
    session: AsyncSession, shop_id: uuid.UUID, items: Sequence[str]
) -> dict[str, tuple[list[dict[str, Any]], Any]]:
    """item id -> (the variations' newest snapshot prices, the item-level snapshot)."""
    out: dict[str, tuple[list[dict[str, Any]], Any]] = {i: ([], None) for i in items}
    if not items:
        return out
    for row in await PlatformItemSnapshotsRepo(session).latest_per_item(shop_id, list(items)):
        variations, head = out[row.item_id]
        if row.variation_id == "":
            out[row.item_id] = (variations, row)
        else:
            variations.append(
                {
                    "variation_id": row.variation_id,
                    "list_price": row.list_price,
                    "current_price": row.current_price,
                    "stock": row.stock,
                }
            )
    return out


async def variation_rows_for(
    session: AsyncSession, shop_id: uuid.UUID, env: RecoEnv, items: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    snaps = await _snapshot_variations(session, shop_id, items)
    rows: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        variations, head = snaps.get(item, ([], None))
        rows[item] = variation_rows(
            item,
            env.ctx.catalog.items.get(item),
            variations,
            rules=env.rules,
            schedule=env.schedule(item),
            on=env.as_of,
            item_list_price=None if head is None else head.list_price,
            item_current_price=None if head is None else head.current_price,
        )
    return rows


async def product_variations(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date | None, now: datetime
) -> dict[str, Any]:
    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise NoShopeeData(str(shop_id))
    rows = (await variation_rows_for(session, shop_id, env, [item_id]))[item_id]
    known = item_id in env.ctx.catalog.items or env.orders_of(item_id) > 0
    if not known:
        raise LookupError(item_id)
    out = economics(item_id, env.name(item_id), rows, vat=env.view.vat)
    out["excluded"] = item_id in env.excluded
    out["exclude_reason"] = env.excluded.get(item_id)
    return out


# --------------------------------------------------------------------- co-purchase (B-4)


async def co_purchase(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, *, as_of: date | None
) -> dict[str, Any]:
    ctx, view, _ = await load_view90(session, shop_id, as_of)
    if item_id in view.excluded:
        raise LookupError(item_id)
    sets = copurchase.order_sets((ln for ln, _ in view.pairs), view.excluded)
    names = {i: view.names.get(i) or ctx.catalog.name(i) for i in view.names}
    out = copurchase.suggestions(sets, item_id, names=names)
    out["window"] = view.window.json()
    return out


# ----------------------------------------------------------------------------- ads levers


async def ads_campaigns(
    session: AsyncSession, shop_id: uuid.UUID, *, as_of: date | None, now: datetime
) -> dict[str, Any]:
    """The campaigns a levers form can pick: live settings, spend, ROAS and break-even ROAS."""
    from juli_backend.services.shopee_analytics.fmt import num, ratio
    from juli_backend.services.shopee_recommendations.evaluate import campaign_profile

    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise NoShopeeData(str(shop_id))
    rows = []
    for alloc in env.view.ads.campaigns:
        prof = campaign_profile(env, alloc.key)
        setting = env.setting_for(alloc.key)
        products = []
        for item, spend in sorted(alloc.products.items(), key=lambda kv: -kv[1]):
            pp = env.product(item)
            fig = env.view.ads.product_figures.get(item)
            products.append(
                {
                    "item_id": item,
                    "name": env.name(item),
                    "spend": num(spend),
                    "roas_direct": ratio(fig.roas_direct if fig else None, 2),
                    "break_even_roas": ratio(pp.break_even_roas if pp else None, 2),
                    "below_break_even": pp.ads_below_break_even if pp else None,
                    "excluded": item in env.excluded,
                }
            )
        rows.append(
            {
                "campaign_key": alloc.key,
                "name": alloc.name,
                "running": alloc.running,
                "daily_budget": num(setting.daily_budget) if setting else None,
                "roas_target": num(setting.roas_target) if setting else None,
                "spend_per_day": num(prof["spend_per_day"]) if prof else None,
                "roas_direct": ratio(prof["roas_direct"], 2) if prof else None,
                "break_even_roas": ratio(prof["break_even_roas"], 2) if prof else None,
                "products": products,
            }
        )
    return {
        "window": env.view.window.json(),
        "daily_cap": num(env.daily_cap),
        "cap_rule": "daily_marketing_cap",
        "campaigns": rows,
    }


# --------------------------------------------------------------- context for the versions


def _keyword_name(campaign_label: str) -> str:
    return campaign_label.split("›", 1)[1].strip() if "›" in campaign_label else ""


def _own_keyword_report(env: RecoEnv, item_id: str | None) -> dict[str, dict[str, Any]]:
    """The shop's ads keyword report (placed orders) per keyword, for one product when given."""
    acc: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"spend": 0.0, "clicks": 0.0, "orders": 0.0, "gmv": 0.0}
    )
    for row in env.view.data.ads_reports.keyword_rows:
        if item_id and row.item_id != item_id:
            continue
        kw = lst_fold(_keyword_name(row.campaign))
        if not kw:
            continue
        a = acc[kw]
        a["spend"] += float(row.spend)
        a["clicks"] += float(row.clicks)
        a["orders"] += float(row.orders)
        a["gmv"] += float(row.gmv)
    for a in acc.values():
        a["roas"] = round(a["gmv"] / a["spend"], 2) if a["spend"] else None
    return dict(acc)


async def _keyword_facts(
    session: AsyncSession, env: RecoEnv, specs: Sequence[sp.VersionSpec]
) -> dict[str, dict[str, Any]]:
    wanted: dict[str, str | None] = {}
    for spec in specs:
        if isinstance(spec, sp.AdsSpec) and spec.lever == "keywords":
            for k in spec.keywords:
                wanted[k.keyword] = spec.item_id
    if not wanted:
        return {}
    metrics: dict[str, Any] = {}
    try:
        async with session.begin_nested():
            metrics = await loaders.load_keyword_market(session, list(wanted))
    except Exception:  # the public market lane may be closed to this role: facts stay empty
        metrics = {}
    out: dict[str, dict[str, Any]] = {}
    for kw, item in wanted.items():
        folded = lst_fold(kw)
        m = metrics.get(kw)
        facts: dict[str, Any] = {}
        if m is not None:
            facts = {
                "volume": m.volume,
                "difficulty": None if m.difficulty is None else float(m.difficulty),
                "cpc_min": None if m.cpc_min is None else float(m.cpc_min),
                "cpc_max": None if m.cpc_max is None else float(m.cpc_max),
            }
        own = _own_keyword_report(env, item).get(folded)
        if own is not None:
            facts["ads"] = own
        out[folded] = facts
    return out


async def _responses(
    session: AsyncSession,
    shop_id: uuid.UUID,
    env: RecoEnv,
    view90: PeriodView,
    targets: set[str],
) -> None:
    """Fill ``env.response_by_item`` / ``response_shop`` from the 90-day order counts and the
    snapshot price history. Needs the order export to cover the whole 90 days."""
    if not view90.data.lines.covers_window:
        return
    start, end = view90.window.start, view90.window.end
    per_day: dict[str, dict[date, set[str]]] = defaultdict(lambda: defaultdict(set))
    for ln, _ in view90.pairs:
        per_day[ln.product_id][ln.order_date].add(ln.order_id)
    ranked = sorted(per_day, key=lambda i: -sum(len(s) for s in per_day[i].values()))
    chosen = [i for i in ranked if i not in env.excluded][:RESPONSE_PRODUCTS]
    pool = list(dict.fromkeys([*targets, *chosen]))
    found: dict[str, Any] = {}
    repo = PlatformItemSnapshotsRepo(session)
    for item in pool:
        snaps = await repo.history(shop_id, item, limit=200)
        series = [(s.captured_at.date(), s.list_price, s.current_price) for s in snaps]
        depth = response.depth_by_day(series, start, end)
        counts = {d: len(orders) for d, orders in per_day.get(item, {}).items()}
        resp = response.product_response(counts, depth, start, end)
        if resp is not None:
            found[item] = resp
    env.response_by_item = {i: r for i, r in found.items() if i in targets}
    env.response_shop = response.shop_response(found)


async def build_context(
    session: AsyncSession,
    shop_id: uuid.UUID,
    specs: Sequence[sp.VersionSpec],
    *,
    as_of: date | None,
    now: datetime,
) -> BuilderContext:
    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise NoShopeeData(str(shop_id))
    items = list(dict.fromkeys(i for spec in specs for i in sp.items_of(spec)))
    ctx = BuilderContext(env=env)
    ctx.variations = await variation_rows_for(session, shop_id, env, items)
    if any(spec.kind in PRICE_SCALED for spec in specs):
        _, view90, _ = await load_view90(session, shop_id, env.as_of)
        ctx.view90 = view90
        await _responses(
            session,
            shop_id,
            env,
            view90,
            {i for spec in specs if spec.kind in PRICE_SCALED for i in sp.items_of(spec)},
        )
    ctx.keyword_facts = await _keyword_facts(session, env, specs)
    return ctx


# ---------------------------------------------------------------------------- B-3 / B-5


def evaluate_version(
    ctx: BuilderContext, spec: sp.VersionSpec, index: int, now: datetime
) -> tuple[dict[str, Any], Translation | None]:
    """One version -> its outcome (a refused one carries ``ok = false`` and a reason)."""
    label = spec.label or f"Phương án {index + 1}"
    try:
        tr = to_variant(spec, ctx)
    except SpecRefused as exc:
        return outcome.refused(index, spec.kind, label, manual.refusal(exc.code)), None
    card, why = manual.build_variant(ctx.env, tr.variant, now=now)
    if card is None:
        return outcome.refused(index, spec.kind, label, why or manual.refusal("invalid_inputs")), tr
    est_card = None
    if tr.estimate is not None:
        est_card, _ = manual.build_variant(ctx.env, tr.estimate, now=now)
    return outcome.shape(
        card, tr, ctx, index=index, kind=spec.kind, label=label, estimate_card=est_card
    ), tr


def _row(key: str, label: str, values: list[Any], unit: str) -> dict[str, Any]:
    return {"key": key, "label": label, "unit": unit, "values": values}


def table_of(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """B-5: cost, Δ GMV, Δ orders, Δ profit, margin after, then each version's driver metric."""

    def pick(fn: Any) -> list[Any]:
        return [fn(r) if r["ok"] else None for r in results]

    rows = [
        _row("cost", "Chi phí của thay đổi", pick(lambda r: r["cost"]["amount"]), "vnd"),
        _row("delta_gmv", "Δ GMV / tháng", pick(lambda r: r["delta"]["gmv"]), "band"),
        _row("delta_orders", "Δ đơn / tháng", pick(lambda r: r["delta"]["orders"]), "band"),
        _row("delta_profit", "Δ lợi nhuận / tháng", pick(lambda r: r["delta"]["profit"]), "band"),
        _row("margin_after", "Biên sau thay đổi", pick(lambda r: r["margin_after_pct"]), "pct"),
    ]
    driver_keys = list(
        dict.fromkeys(m["key"] for r in results if r["ok"] for m in r["driver"]["metrics"])
    )
    for key in driver_keys:
        values = []
        for r in results:
            metric = (
                next((m for m in r["driver"]["metrics"] if m["key"] == key), None)
                if r["ok"]
                else None
            )
            values.append(
                None
                if metric is None
                else {"before": metric["before"], "after_p50": metric["after_p50"]}
            )
        rows.append(_row(f"driver:{key}", outcome.METRIC_LABELS[key], values, "driver"))
    return {"rows": rows}


def best_index(results: Sequence[dict[str, Any]]) -> int | None:
    """The version with the best P50 profit among those that break no floor and know their cost."""
    safe = [
        r
        for r in results
        if r["ok"] and not r["breach"] and r["delta"]["profit"]["p50"] is not None
    ]
    return max(safe, key=lambda r: r["delta"]["profit"]["p50"])["index"] if safe else None


def today_of(env: RecoEnv) -> dict[str, Any]:
    return manual.today_of(env)


async def evaluate_versions(
    session: AsyncSession,
    shop_id: uuid.UUID,
    specs: Sequence[sp.VersionSpec],
    *,
    as_of: date | None,
    now: datetime,
) -> dict[str, Any]:
    """Up to four versions of mixed kinds side by side. Saves nothing."""
    ctx = await build_context(session, shop_id, specs, as_of=as_of, now=now)
    results = [evaluate_version(ctx, spec, i, now)[0] for i, spec in enumerate(specs)]
    return {
        "today": today_of(ctx.env),
        "versions": results,
        "table": table_of(results),
        "best_profit_p50": best_index(results),
        "saved": False,
    }


async def choose(
    session: AsyncSession,
    shop_id: uuid.UUID,
    specs: Sequence[sp.VersionSpec],
    chosen: int,
    *,
    primary: bool,
    acknowledge_breaches: bool,
    actor: manual.Actor,
    as_of: date | None,
    now: datetime,
) -> dict[str, Any]:
    """ "Chọn": save ``specs[chosen]`` as a manual card (the others are its versions)."""
    ctx = await build_context(session, shop_id, specs, as_of=as_of, now=now)
    variants: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        try:
            variants.append(to_variant(spec, ctx).variant)
        except SpecRefused as exc:
            if i == chosen:
                raise manual.ProposalError(
                    manual.ERROR_BAD_VARIANT, 422, manual.refusal(exc.code)["message"]
                ) from None
            variants.append(
                {"label": spec.label or f"Phương án {i + 1}", "change_kind": "unknown", "items": []}
            )
    out = await manual.create_manual(
        session,
        shop_id,
        variants,
        chosen,
        primary,
        actor,
        now=now,
        env=ctx.env,
        acknowledge_breaches=acknowledge_breaches,
    )
    out["outcome"] = evaluate_version(ctx, specs[chosen], chosen, now)[0]
    return out


__all__ = [
    "NoShopeeData",
    "ads_campaigns",
    "best_index",
    "build_context",
    "choose",
    "co_purchase",
    "evaluate_version",
    "evaluate_versions",
    "load_view90",
    "product_variations",
    "products",
    "table_of",
    "variation_rows_for",
]


# ------------------------------------------------------------------------ LLM draft facts


def _k(value: Any) -> str:
    n = float(value)
    return f"{n / 1000:g}K" if n >= 1000 else f"{n:g}đ"


def voucher_line(env: RecoEnv) -> tuple[str | None, int | None]:
    """The best running shop voucher as the cover would say it, from the settings Juli reads from
    Seller Centre (``voucher_settings``): ``(text, amount in đ or None for a percent)``."""
    best: tuple[float, str, int | None] | None = None
    today = env.as_of.isoformat()
    for v in env.vouchers:
        if v.ends_at and v.ends_at[:10] < today:
            continue
        if v.value is not None:
            gain, amount = float(v.value), int(v.value)
            text = f"Voucher giảm {_k(v.value)}"
        elif v.pct is not None:
            cap = float(v.max_value) if v.max_value is not None else 0.0
            gain, amount = cap or float(v.pct), None
            text = f"Voucher giảm {float(v.pct):g}%" + (f" tối đa {_k(cap)}" if cap else "")
        else:
            continue
        if v.min_spend:
            text += f" đơn từ {_k(v.min_spend)}"
        if best is None or gain > best[0]:
            best = (gain, text, amount)
    return (None, None) if best is None else (best[1], best[2])


async def draft_facts(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    as_of: date | None,
    now: datetime,
) -> tuple[RecoEnv, Any]:
    """The facts a draft may state about one product (nothing else reaches the model)."""
    from juli_backend.services import shop_rules
    from juli_backend.services.shopee_builder.drafts import ProductFacts
    from juli_backend.services.shopee_recommendations import listing as lst

    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise NoShopeeData(str(shop_id))
    known = item_id in env.ctx.catalog.items or env.orders_of(item_id) > 0
    if not known:
        raise LookupError(item_id)
    rows = (await variation_rows_for(session, shop_id, env, [item_id]))[item_id]
    li = env.listings.get(item_id)
    title = (li.title if li and li.title else None) or env.name(item_id)
    price = li.price if li else None
    size = lst.unit_price(title, price)
    voucher_text, voucher_amount = voucher_line(env)
    tone = await shop_rules.content_tone(session, shop_id)
    facts = ProductFacts(
        item_id=item_id,
        title=title,
        variations=tuple(
            {
                k: r[k]
                for k in (
                    "variation_id",
                    "name",
                    "list_price",
                    "selling_price",
                    "price_per_unit",
                    "pack_count",
                )
            }
            for r in rows
        ),
        unit_price_line=None if size is None or price is None else size.line(price),
        voucher_text=voucher_text,
        voucher_amount_vnd=voucher_amount,
        tone=tone,
        banned_terms=tuple(env.banned_terms),
    )
    return env, facts
