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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import (
    STATUS_CHANGES_REQUESTED,
    STATUS_SENT,
    ShopProposal,
)
from juli_backend.repositories import PlatformItemSnapshotsRepo
from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder import (
    catalogue,
    copurchase,
    outcome,
    picker_table,
    response,
)
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_builder.reference import with_reference_lines
from juli_backend.services.shopee_builder.translate import Translation, to_variant
from juli_backend.services.shopee_builder.variations import (
    economics,
    measured_rates,
    observed_skus,
    variation_rows,
    with_orders,
)
from juli_backend.services.shopee_recommendations import loader, manual
from juli_backend.services.shopee_recommendations import targets as multi_targets
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.voucher_notes import same_result_notes

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


async def _items_with_proposals(session: AsyncSession, shop_id: uuid.UUID) -> set[str]:
    """Products that have a card the seller can still decide on (the picker's "có đề xuất")."""
    rows = await session.scalars(
        select(ShopProposal.item_id)
        .where(
            ShopProposal.shop_id == shop_id,
            ShopProposal.status.in_((STATUS_SENT, STATUS_CHANGES_REQUESTED)),
            ShopProposal.item_id.is_not(None),
        )
        .distinct()
    )
    return {str(i) for i in rows}


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
    view30 = await service.load_view(
        session, shop_id, ctx, Window(anchor - timedelta(days=catalogue.RECENT_DAYS - 1), anchor)
    )
    prev_end = anchor - timedelta(days=catalogue.RECENT_DAYS)
    prev30 = await service.load_view(
        session,
        shop_id,
        ctx,
        Window(prev_end - timedelta(days=catalogue.RECENT_DAYS - 1), prev_end),
    )
    waiting = await _items_with_proposals(session, shop_id)
    return catalogue.picker(
        ctx,
        view,
        anchor,
        view30=view30,
        extra=picker_table.extras(view30, prev30, proposal_items=waiting),
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
    seen_skus = observed_skus(env.view.lines)
    rows: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        variations, head = snaps.get(item, ([], None))
        # ADR-122 d.12: Biên cuối beside Biên ở giá bán (the product page's one math, margins.py)
        product_rates, sku_rates = measured_rates(
            [(ln, pb) for ln, pb in env.view.pairs if ln.product_id == item],
            env.view.ads.product_spend.get(item),
        )
        rows[item] = variation_rows(
            item,
            env.ctx.catalog.items.get(item),
            variations,
            rules=env.rules,
            schedule=env.schedule(item),
            on=env.as_of,
            item_list_price=None if head is None else head.list_price,
            item_current_price=None if head is None else head.current_price,
            observed=seen_skus.get(item),
            product_rates=product_rates,
            sku_rates=sku_rates,
        )
        rows[item] = with_orders(rows[item], (ln for ln, _ in env.view.pairs), item)
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
    # "So sánh phân loại" shows both margins (ADR-122 d.12)
    out["columns"] = [*out["columns"], "final_margin_pct"]
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
    rows.extend(
        _stored_campaigns(
            env, {str(r["campaign_key"]) for r in rows}, {str(r["name"]) for r in rows}
        )
    )
    return {
        "window": env.view.window.json(),
        "daily_cap": num(env.daily_cap),
        "cap_rule": "daily_marketing_cap",
        "campaigns": rows,
    }


def _stored_campaigns(env: RecoEnv, keys: set[str], names: set[str]) -> list[dict[str, Any]]:
    """Real campaigns the allocation did not list: the Connector's per-campaign daily rows
    (``env.campaigns``: budget, ROAS target) and the ads files' campaign rows. The allocation can
    reduce a shop to one pseudo campaign ("Tổng chi quảng cáo"); the levers form still needs the
    shop's own campaigns to pick from."""
    from juli_backend.services.shopee_analytics.fmt import num

    out: list[dict[str, Any]] = []
    seen = set(keys) | set(names)

    def add(key: str, name: str, budget: Any, roas: Any, running: bool | None) -> None:
        if key in seen or name in seen:
            return
        seen.update({key, name})
        out.append(
            {
                "campaign_key": key,
                "name": name,
                "running": running,
                "daily_budget": num(budget) if budget is not None else None,
                "roas_target": num(roas) if roas is not None else None,
                "spend_per_day": None,
                "roas_direct": None,
                "break_even_roas": None,
                "products": [],
            }
        )

    for setting in dict.fromkeys(env.campaigns.values()):
        add(setting.key, setting.name, setting.daily_budget, setting.roas_target, None)
    for row in env.view.data.ads_reports.campaign_rows:
        add(row.key, row.campaign or row.key, None, None, row.running)
    return out


# --------------------------------------------------------------- context for the versions


async def _responses(
    session: AsyncSession,
    shop_id: uuid.UUID,
    env: RecoEnv,
    view90: PeriodView,
    targets: set[str],
) -> None:
    """Fill ``env.response_by_item`` / ``response_shop`` from the 90-day order counts and the
    snapshot price history. Uses the days the order export covers."""
    span = response.covered_span(
        view90.data.lines.export_bounds, view90.window.start, view90.window.end
    )
    if span is None:
        return
    start, end = span
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
    ctx.env, ctx.reference_items = with_reference_lines(env, ctx.variations, items)
    env = ctx.env
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
    return ctx


# ---------------------------------------------------------------------------- B-3 / B-5


def evaluate_version(
    ctx: BuilderContext, spec: sp.VersionSpec, index: int, now: datetime, shop_id: str = ""
) -> tuple[dict[str, Any], Translation | None]:
    """One version -> its outcome (a refused one carries ``ok = false`` and a reason)."""
    out, tr, _ = _evaluate_version_card(ctx, spec, index, now, shop_id)
    return out, tr


def hidden_refusal() -> dict[str, str]:
    """ADR-122 d.10: Ads edits of running campaigns are hidden from the builder."""
    return {"code": integrate.HIDDEN_CODE, "message": integrate.HIDDEN_TEXT}


def _evaluate_version_card(
    ctx: BuilderContext, spec: sp.VersionSpec, index: int, now: datetime, shop_id: str = ""
) -> tuple[dict[str, Any], Translation | None, dict[str, Any] | None]:
    label = spec.label or f"Phương án {index + 1}"
    if integrate.hidden(spec):
        return outcome.refused(index, spec.kind, label, hidden_refusal()), None, None
    try:
        tr = to_variant(spec, ctx)
    except SpecRefused as exc:
        return outcome.refused(index, spec.kind, label, manual.refusal(exc.code)), None, None
    card, why = manual.build_variant(ctx.env, tr.variant, now=now)
    if card is None:
        refusal = why or manual.refusal("invalid_inputs")
        return outcome.refused(index, spec.kind, label, refusal), tr, None
    est_card = None
    if tr.estimate is not None:
        est_card, _ = manual.build_variant(ctx.env, tr.estimate, now=now)
    ev, per_target = integrate.evaluate(ctx, spec, shop_id)
    shaped = outcome.shape(
        card,
        tr,
        ctx,
        index=index,
        kind=spec.kind,
        label=label,
        estimate_card=est_card,
        result=ev.result_json(),
        result_refusal=ev.refusal_json(),
        scope="shop" if ev.base.scope == "shop" else "product",
    )
    if tr.multi is not None:
        _add_targets(shaped, ctx, tr, card, now)
        results = {t: e for t, e in per_target}
        for row in shaped["targets"]:
            e = results.get(str(row.get("id")))
            row["result"] = None if e is None else e.result_json()
            row["result_refusal"] = None if e is None else e.refusal_json()
            if row.get("ok", True) and "dgmv_p50" in row:
                known, _ = outcome.items_cost_known(ctx, [str(row["id"])])
                row.update(_target_brief(row["result"], cost_known=known))
    return shaped, tr, card


def _add_targets(
    shaped: dict[str, Any],
    ctx: BuilderContext,
    tr: Translation,
    card: dict[str, Any],
    now: datetime,
) -> None:
    """P97 D85.13: the total above is the card; below it a row per target (what untick changes) and
    how the fill works (one bulk pass where Shopee has a bulk edit, else one job per target)."""
    rows: list[dict[str, Any]]
    if tr.multi == "joint":
        rows = []
        for tid, part in tr.parts:
            one, why = manual.build_variant(ctx.env, part.variant, now=now)
            name = ctx.env.name(tid)
            rows.append(
                {
                    "id": tid,
                    "kind": "item",
                    "name": name,
                    "ok": False,
                    "refusal": why,
                    "breaches": [],
                }
                if one is None
                else {
                    "id": tid,
                    "kind": "item",
                    "name": name,
                    "ok": True,
                    "refusal": None,
                    **multi_targets.brief(one),
                    "breaches": [dict(b) for b in one["floor"]["breaches"]],
                    "breach": bool(one["floor"]["breaches"]),
                }
            )
        rows += [{**r, "ok": False, "breaches": []} for r in tr.details.get("refused_targets", [])]
        shaped["targets_note"] = (
            "Một voucher chung cho cả danh sách: tổng là kết quả chung. Mỗi dòng là mức voucher "
            "này mang lại nếu chỉ áp cho riêng sản phẩm đó."
        )
    else:
        rows = []
        for r in card[multi_targets.KEY]:
            own = [dict(b) for b in card["floor"]["breaches"] if b.get("target") == r["id"]]
            rows.append(
                {k: v for k, v in r.items() if k != "variant"}
                | {"breaches": own, "breach": bool(own)}
            )
    shaped["targets"] = rows
    shaped["targets_mode"] = tr.multi
    shaped["fill"] = card.get("fill") or {
        "mode": "bulk" if tr.multi == "joint" else multi_targets.fill_mode(card["change_kind"]),
        "targets": len(rows),
    }
    ba = shaped.get("before_after") or {}
    margin = next((r for r in ba.get("rows", []) if r["key"] == "margin"), None)
    if shaped.get("margin_after_pct") is None and margin and margin.get("after"):
        shaped["margin_before_pct"] = margin["before"]
        shaped["margin_after_pct"] = margin["after"]["p50"]


def _target_brief(result: dict[str, Any] | None, *, cost_known: bool = True) -> dict[str, Any]:
    """A target row's figures from its own result (P98: the card's money layer no longer
    produces them), so the rows add up to the version's summed result. A target without a giá
    vốn has no profit ("chưa tính")."""
    d = outcome.result_delta(result)
    if not cost_known:
        d["profit"] = dict(outcome.NULL_BAND)
    return {
        "dgmv_p50": d["gmv"]["p50"],
        "dorders_p50": d["orders"]["p50"],
        "dprofit_p50": d["profit"]["p50"],
        "dprofit_p10": d["profit"]["low"],
        "dprofit_p90": d["profit"]["high"],
    }


def _row(key: str, label: str, values: list[Any], unit: str) -> dict[str, Any]:
    return {"key": key, "label": label, "unit": unit, "values": values}


def table_of(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """B-5: cost, Δ GMV, Δ orders, Δ profit, margin after, then each version's driver metric."""

    def pick(fn: Any) -> list[Any]:
        return [fn(r) if r["ok"] else None for r in results]

    rows = [
        _row("cost", "Chi phí của thay đổi", pick(lambda r: r["cost"]["amount"]), "vnd"),
        _row("delta_gmv", "Δ GMV", pick(lambda r: r["delta"]["gmv"]), "band"),
        _row("delta_orders", "Δ đơn", pick(lambda r: r["delta"]["orders"]), "band"),
        _row("delta_profit", "Δ lợi nhuận", pick(lambda r: r["delta"]["profit"]), "band"),
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
    evaluated = [
        _evaluate_version_card(ctx, spec, i, now, str(shop_id)) for i, spec in enumerate(specs)
    ]
    results = [e[0] for e in evaluated]
    # Name why a version looks like V1 (an input that differs but does not bind), per version
    head = next((e[2] for e in evaluated if e[2] is not None), None)
    for res, _, card in evaluated:
        if res["ok"] and card is not None and head is not None and card is not head:
            notes = same_result_notes(head, card)
            if notes:
                res["same_as_first_notes"] = notes
    return {
        "today": today_of(ctx.env),
        "versions": results,
        "table": table_of(results),
        "best_profit_p50": best_index(results),
        # P98: the versions in the comparison order (per-30-day Δ lợi nhuận, best first)
        "compare": compare_order(results),
        "saved": False,
    }


def compare_order(results: Sequence[dict[str, Any]]) -> list[int]:
    """Version indexes sorted by the result's per-30-day Δ profit (``engine.compare``); a version
    without one goes last, in its own order."""

    def key(r: dict[str, Any]) -> tuple[int, float]:
        res = r.get("result") if r.get("ok") else None
        v = None if res is None else (res.get("per_30d") or {}).get("profit")
        return (1, 0.0) if v is None else (0, -float(v))

    return [r["index"] for r in sorted(results, key=key)]


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
    if integrate.hidden(specs[chosen]):
        raise manual.ProposalError(integrate.HIDDEN_CODE, 422, integrate.HIDDEN_TEXT)
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
    out["outcome"] = evaluate_version(ctx, specs[chosen], chosen, now, str(shop_id))[0]
    return out


async def run_together(
    session: AsyncSession,
    shop_id: uuid.UUID,
    specs: Sequence[sp.VersionSpec],
    members: Sequence[int],
    *,
    days: int,
    start: date | None,
    acknowledge_breaches: bool,
    actor: manual.Actor,
    as_of: date | None,
    now: datetime,
    audience: str = "ops",
) -> dict[str, Any]:
    """ "Chạy cùng nhau" (P97 D85.14): the ticked versions of So sánh become ONE group of the plan.

    Versions of the same change (same kind, products and campaign: two vouchers of the same scope)
    are saved as versions of one card; every other kind is its own card. All of them go to the draft
    plan and into one new group with one period; a version whose exclusive field is taken in the
    group moves to the next group (never refused). Returns the plan and ``saved``."""
    from juli_backend.services.shopee_recommendations import plans
    from juli_backend.services.shopee_recommendations import service as reco

    picked = list(dict.fromkeys(members))
    if not picked or any(not 0 <= i < len(specs) for i in picked):
        raise manual.ProposalError(manual.ERROR_BAD_VARIANT, 422, "choose versions of the list")
    if any(integrate.hidden(specs[i]) for i in picked):
        raise manual.ProposalError(integrate.HIDDEN_CODE, 422, integrate.HIDDEN_TEXT)
    ctx = await build_context(session, shop_id, specs, as_of=as_of, now=now)
    buckets: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
    for i in picked:
        try:
            variant = to_variant(specs[i], ctx).variant
        except SpecRefused as exc:
            raise manual.ProposalError(
                manual.ERROR_BAD_VARIANT, 422, manual.refusal(exc.code)["message"]
            ) from None
        key = (
            variant.get("change_kind"),
            tuple(variant.get("items") or ()),
            variant.get("campaign_key"),
        )
        buckets.setdefault(key, []).append((i, variant))
    saved: list[dict[str, Any]] = []
    pairs: list[tuple[uuid.UUID, int]] = []
    for rows in buckets.values():
        for chunk in (rows[n : n + manual.MAX_VARIANTS] for n in range(0, len(rows), 4)):
            out = await manual.create_manual(
                session,
                shop_id,
                [v for _, v in chunk],
                0,
                False,
                actor,
                now=now,
                env=ctx.env,
                acknowledge_breaches=acknowledge_breaches,
            )
            card_id = uuid.UUID(out["id"])
            saved.append({"id": out["id"], "code": out["code"], "indexes": [i for i, _ in chunk]})
            pairs += [(card_id, n) for n in range(1, len(chunk) + 1)]
    if actor.kind == "staff":  # Ops' cards are drafts: they must be sent to join the plan
        await reco.publish(session, shop_id, [uuid.UUID(c["id"]) for c in saved], now=now)
    out = await plans.run_together(
        session,
        shop_id,
        pairs,
        days=days,
        start=start,
        actor=actor,
        now=now,
        acknowledge_breaches=acknowledge_breaches,
        audience=audience,
    )
    return {**out, "saved": saved}


__all__ = [
    "NoShopeeData",
    "run_together",
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
