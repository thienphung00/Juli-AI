"""The "Theo SKU" rows of the Tổng quan export: actuals, stock and the SKU goals.

Actuals (per SKU = product + cost key + variation): units = Σ qty - returned_qty and revenue =
Σ deal_price x net qty of the stored order lines of the period (cancelled lines left out, as the
profit computation does); profit = Σ line contribution (the app's per-line profit) less the
product's report ad spend shared by list value, blank when a giá vốn of the SKU is missing.
Lines that name no SKU (the cost key is the item id) are one "Không có SKU" row per product.

Goals: the SKU's share of the product's Kế hoạch goal (``month_plan.range_plan`` of the
product). The product baseline is split by the SKU's share of the product's revenue (resp. profit)
in the BASELINE WINDOW -- the 30 days ``range_plan`` reports as ``baseline_window`` (the plan's
frozen "today" window); each running card's uplift goes to the SKUs the card is scoped to
(``month_plan.card_sku_scope``; product-level cards: every SKU of the product) by their baseline
shares among them. Units goal = revenue goal / the SKU's average selling price in that window.
Cần bán đến cuối kỳ = max(0, units goal of the whole period - units sold so far), 0 for a finished
period.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.repositories import ShopeeOrderLinesRepo
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.order_profit import OrderStatus

NO_SKU = "Không có SKU"
SkuKey = tuple[str, str, str]  # (product id, cost key, variation id)


@dataclass
class Fig:
    """One SKU's actuals over one window."""

    units: int = 0
    revenue: Decimal = Decimal(0)
    contribution: Decimal = Decimal(0)
    list_value: Decimal = Decimal(0)  # of the lines inside the profit base
    cost_known: bool = True
    profit: float | None = None
    label: str = ""
    variation: str | None = None

    @property
    def avg_price(self) -> float | None:
        return float(self.revenue) / self.units if self.units > 0 else None


async def _returned(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> dict[Any, int]:
    rows = await ShopeeOrderLinesRepo(session).in_window(shop_id, window.start, window.end)
    return {(r.order_ref, r.line_no): int(r.returned_qty or 0) for r in rows}


async def sku_figures(
    session: AsyncSession, shop_id: uuid.UUID, view: PeriodView, window: Window
) -> dict[SkuKey, Fig]:
    """Per-SKU actuals of the view's window (see the module doc)."""
    returned = await _returned(session, shop_id, window)
    raw = [r for r in view.data.lines.lines if r.paid_at is not None and r.qty > 0]
    out: dict[SkuKey, Fig] = {}
    if len(raw) != len(view.pairs):  # the view is not the plain line list: nothing to align
        return out
    included: dict[str, Decimal] = defaultdict(Decimal)  # product -> list value in profit base
    for r, sl, (ln, pb) in zip(raw, view.lines, view.pairs, strict=True):
        key: SkuKey = (ln.product_id, sl.cost_key, sl.variation_id)
        fig = out.setdefault(key, Fig())
        if not fig.label:
            no_sku = sl.base_key == ln.product_id and not sl.variation_id
            fig.label = NO_SKU if no_sku else sl.cost_key
        fig.variation = fig.variation or r.variation_name
        if ln.status is OrderStatus.CANCELLED:
            continue
        net = max(ln.qty - returned.get((r.order_ref, r.line_no), 0), 0)
        fig.units += net
        fig.revenue += ln.deal_price * net
        if pb.excluded_reason is None:
            included[ln.product_id] += pb.list_value
            fig.list_value += pb.list_value
            if pb.contribution is None or not view.costs.cogs_is_real(sl.cost_key):
                fig.cost_known = False
            else:
                fig.contribution += pb.contribution
    for key, fig in out.items():
        pp = view.profit.products.get(key[0])
        spend = pp.ad_spend if pp is not None else Decimal(0)
        base = included.get(key[0], Decimal(0))
        share = fig.list_value / base if base > 0 else Decimal(0)
        fig.profit = float(fig.contribution - spend * share) if fig.cost_known else None
    return out


# ----------------------------------------------------------------------------- stock


@dataclass
class Stock:
    by_variation: dict[tuple[str, str], int | None] = field(default_factory=dict)

    def of(self, item_id: str, variation_id: str, *, only_sku: bool) -> int | None:
        if (item_id, variation_id) in self.by_variation:
            return self.by_variation[(item_id, variation_id)]
        if only_sku and (item_id, "") in self.by_variation:  # a listing without variations
            return self.by_variation[(item_id, "")]
        return None


async def stock_at(
    session: AsyncSession, shop_id: uuid.UUID, item_ids: Iterable[str], end: date
) -> Stock:
    """The newest ``platform_item_snapshots.stock`` of each item + variation captured by the end
    of ``end``."""
    ids = list(item_ids)
    out = Stock()
    if not ids:
        return out
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time())
    rows = await session.execute(
        select(
            PlatformItemSnapshot.item_id,
            PlatformItemSnapshot.variation_id,
            PlatformItemSnapshot.stock,
        )
        .where(
            PlatformItemSnapshot.shop_id == shop_id,
            PlatformItemSnapshot.item_id.in_(ids),
            PlatformItemSnapshot.captured_at < hi,
        )
        .order_by(PlatformItemSnapshot.captured_at)
    )
    for item_id, variation_id, stock in rows:
        out.by_variation[(item_id, variation_id or "")] = None if stock is None else int(stock)
    return out


# ----------------------------------------------------------------------------- goals


def _shares(
    keys: Sequence[SkuKey], value: Mapping[SkuKey, float | None]
) -> dict[SkuKey, float] | None:
    """Each key's share of ``keys``' total; ``None`` when a value is unknown or the total is not
    positive."""
    vals = [value.get(k) for k in keys]
    if any(v is None for v in vals):
        return None
    total = sum(v for v in vals if v is not None)
    if total <= 0:
        return None
    return {k: (value[k] or 0.0) / total for k in keys}


def split_goal(
    keys: Sequence[SkuKey],
    base_value: Mapping[SkuKey, float | None],
    baseline: float,
    uplifts: Sequence[Mapping[str, Any]],
    uplift_key: str,
) -> dict[SkuKey, float] | None:
    """The product's goal (baseline + Σ card uplifts) split over ``keys``: the baseline by each
    SKU's share of ``base_value``, a card's uplift over the SKUs it is scoped to (all, when the
    card is product-level or names none of them). ``None`` when the baseline share is unknown."""
    shares = _shares(keys, base_value)
    if shares is None:
        return None
    out = {k: baseline * shares[k] for k in keys}
    for card in uplifts:
        wanted = set(card.get("sku_ids") or [])
        scope = [k for k in keys if k[1] in wanted] or list(keys)
        part = _shares(scope, base_value) or {k: 1 / len(scope) for k in scope}
        for k in scope:
            out[k] += float(card[uplift_key]) * part[k]
    return out


@dataclass
class Row:
    key: SkuKey
    sku: str
    variation: str | None
    product_name: str
    units_goal: float | None = None
    units: float | None = None
    revenue_goal: float | None = None
    revenue: float | None = None
    profit_goal: float | None = None
    profit: float | None = None
    stock: float | None = None
    need: float | None = None


def _goals(
    plan: Mapping[str, Any], ordered: Sequence[SkuKey], base_figs: Mapping[SkuKey, Fig]
) -> tuple[dict[SkuKey, float] | None, dict[SkuKey, float] | None]:
    """(revenue goal, profit goal) of each SKU of one product from its Kế hoạch figures."""
    if plan.get("goal_gmv") is None or not base_figs or not ordered:
        return None, None
    rev = split_goal(
        ordered,
        {k: float(f.revenue) for k, f in base_figs.items()}
        | {k: 0.0 for k in ordered if k not in base_figs},
        float(plan["baseline_gmv"] or 0),
        plan.get("card_uplifts") or [],
        "uplift_gmv",
    )
    if plan.get("baseline_profit") is None:
        return rev, None
    prof = split_goal(
        ordered,
        {k: f.profit for k, f in base_figs.items()}
        | {k: 0.0 for k in ordered if k not in base_figs},
        float(plan["baseline_profit"]),
        plan.get("card_uplifts") or [],
        "uplift_profit",
    )
    return rev, prof


def build_rows(
    *,
    product_ids: Sequence[str],
    names: Mapping[str, str],
    now: Mapping[SkuKey, Fig],
    base: Mapping[str, Mapping[SkuKey, Fig]],
    plans: Mapping[str, Mapping[str, Any]],
    stock: Stock,
    catalog_variations: Mapping[str, Sequence[tuple[str, str | None, str | None]]],
    finished: bool,
    plans_full: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Row]:
    """The rows (one per SKU of each product, in ``product_ids`` order). ``base`` = per product the
    SKU figures of its baseline window; ``catalog_variations`` = per product its listed
    (variation id, name, seller SKU) for the SKUs that only have stock. ``plans_full`` = the
    products' Kế hoạch figures of the WHOLE period (``plans`` when the period is not finished):
    Cần bán đến cuối kỳ = max(0, units goal of the whole period - units sold so far), 0 when the
    period is ``finished``."""
    rows: list[Row] = []
    for pid in product_ids:
        keys = {k for k in now if k[0] == pid} | set(base.get(pid, {}))
        base_figs = base.get(pid, {})
        sold = {k[2] for k in keys if k[2]}
        for vid, _vname, seller in catalog_variations.get(pid, ()):
            if vid not in sold and (stock.of(pid, vid, only_sku=False) or 0) > 0:
                keys.add((pid, seller or vid, vid))
        ordered = sorted(keys, key=lambda k: (-float(now[k].revenue) if k in now else 0.0, k[1]))
        rev_goal, prof_goal = _goals(plans.get(pid) or {}, ordered, base_figs)
        rev_full = (
            _goals((plans_full or {}).get(pid) or {}, ordered, base_figs)[0]
            if plans_full is not None
            else rev_goal
        )
        only_sku = len(ordered) == 1
        for k in ordered:
            fig = now.get(k)
            bfig = base_figs.get(k)
            variation = (fig.variation if fig else None) or (bfig.variation if bfig else None)
            label = (fig.label if fig else None) or (bfig.label if bfig else None) or k[1]
            if variation is None:
                variation = next(
                    (n for v, n, _ in catalog_variations.get(pid, ()) if v == k[2]), None
                )
            r = Row(k, label, variation, names.get(pid, pid))
            r.units = float(fig.units) if fig else 0.0
            r.revenue = float(fig.revenue) if fig else 0.0
            r.profit = fig.profit if fig else None
            r.stock = stock.of(pid, k[2], only_sku=only_sku)
            price = bfig.avg_price if bfig else None
            if rev_goal is not None:
                r.revenue_goal = rev_goal[k]
                r.units_goal = None if not price else rev_goal[k] / price
            if prof_goal is not None:
                r.profit_goal = prof_goal[k]
            if finished:
                r.need = 0.0
            elif rev_full is not None and price:
                r.need = max(0.0, rev_full[k] / price - r.units)
            rows.append(r)
    return rows
