"""F7.5 / F7.6: the running Thực tế of executed cards and the groups of overlapping change sets.

**Thực tế (F7.5).** For a change set (or a group of them) started on ``start`` with a window of
``N`` days, the daily job reads the stored daily rows (``product_metrics_daily`` for a product set,
``shop_metrics_daily`` for a shop-wide one) for the ``k`` days measured so far (``k <= N``: the
start day up to the newest day with data) and compares them with the ``k`` days just before the
start ("hiện tại"). Five metrics: profit (after ads: a product's stored profit already carries
its ad cost, decision #39, as a shop's does), gmv, orders, aov, margin_pct (÷ doanh thu thực,
P9). Nothing
is estimated: the figures are the stored days' sums. At ``k == N`` the profit Δ is judged against
the forecast band (Trong / Vượt / Dưới khoảng, G16).

**Groups (F7.6).** A change that starts while another set of the same product (or both shop-wide)
is measuring joins it: the sets are ONE group, measured over the first start to the last end,
members listed. Groups are derived from the sets themselves (same scope and product, windows
overlapping, or a ``cut_by_change_set`` link), so a set that an older release cut is read as a
group again by the daily job (:func:`regroup`), with no manual step. A group result is never
``clean`` (it feeds no calibration).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import STATUS_EXECUTED, ShopProposal
from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily, ShopeeShopMetricsDaily
from juli_backend.models.shopee_plans import (
    SET_CUT,
    SET_DONE,
    SET_MEASURING,
    ShopRecoChangeSet,
)
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_recommendations import change_sets, result_store, store

METRICS = ("profit", "gmv", "orders", "aov", "margin_pct")
VERDICT_IN = "trong_khoang"
VERDICT_ABOVE = "vuot_khoang"
VERDICT_BELOW = "duoi_khoang"
VERDICT_VI = {
    VERDICT_IN: "Trong khoảng",
    VERDICT_ABOVE: "Vượt khoảng",
    VERDICT_BELOW: "Dưới khoảng",
}
LABEL_RUNNING = "Đang đo"


@dataclass
class Day:
    gmv: float = 0.0
    orders: float = 0.0
    #: profit after ads; ``None`` = the day's profit is unknown (a cost is missing)
    profit: float | None = None
    #: P9 (#44): doanh thu thực of the day (the margin's denominator); ``None`` = unknown
    net: float | None = None


@dataclass
class Group:
    """Sets of one scope / product measured together (``sets`` is ordered by start)."""

    sets: list[ShopRecoChangeSet]

    @property
    def primary(self) -> ShopRecoChangeSet:
        return self.sets[0]

    @property
    def start(self) -> date:
        return min(s.started_at.date() for s in self.sets)

    @property
    def end_excl(self) -> date:
        """The day after the last measured day (the latest member window's end)."""
        return max(s.started_at.date() + timedelta(days=s.window_days) for s in self.sets)

    @property
    def days(self) -> int:
        return (self.end_excl - self.start).days

    @property
    def id(self) -> str:
        return str(self.primary.id)


# ----------------------------------------------------------------------------- grouping (pure)


def _is_candidate(cs: ShopRecoChangeSet) -> bool:
    """A set that can be part of a group: it still holds cards (a reset / reverted set is
    history), and it is running or was cut by a later change (the old release's cut)."""
    if not cs.card_ids:
        return False
    if cs.status == SET_MEASURING:
        return True
    return cs.status == SET_CUT and bool((cs.result or {}).get("cut_by_change_set"))


def group_sets(sets: Sequence[ShopRecoChangeSet]) -> list[Group]:
    """Group the running / cut-by-overlap sets: same scope and product, the next set starting
    before the group's last day is over, or linked by ``cut_by_change_set``. Pure."""
    by_key: dict[tuple[str, str | None], list[ShopRecoChangeSet]] = {}
    for cs in sets:
        if _is_candidate(cs):
            by_key.setdefault((cs.scope, cs.product_id), []).append(cs)
    out: list[Group] = []
    for rows in by_key.values():
        rows.sort(key=lambda c: (c.started_at, str(c.id)))
        current: list[ShopRecoChangeSet] = []
        end: date | None = None
        for cs in rows:
            s = cs.started_at.date()
            linked = any(
                str((c.result or {}).get("cut_by_change_set")) == str(cs.id)
                or str((cs.result or {}).get("cut_by_change_set")) == str(c.id)
                for c in current
            )
            if current and end is not None and (s < end or linked):
                current.append(cs)
                end = max(end, s + timedelta(days=cs.window_days))
            else:
                if current:
                    out.append(Group(current))
                current = [cs]
                end = s + timedelta(days=cs.window_days)
        if current:
            out.append(Group(current))
    return out


# ------------------------------------------------------------------------------ the figures


def totals(days: Mapping[date, Day], keys: Sequence[date]) -> dict[str, float | None]:
    """The five metrics over ``keys`` (days missing from ``days`` count as 0 sales)."""
    gmv = sum(days[d].gmv for d in keys if d in days)
    orders = sum(days[d].orders for d in keys if d in days)
    known = [days[d].profit for d in keys if d in days and days[d].profit is not None]
    unknown = any(d in days and days[d].profit is None for d in keys)
    profit = None if unknown or not known else float(sum(v for v in known if v is not None))
    nets = [days[d].net for d in keys if d in days]
    net = None if not nets or any(v is None for v in nets) else sum(v or 0.0 for v in nets)
    return {
        "profit": profit,
        "gmv": gmv,
        "orders": orders,
        "aov": gmv / orders if orders else None,
        # P9 (#44): Biên lợi nhuận = lợi nhuận ÷ doanh thu thực, the forecast's basis (never ÷ GMV)
        "margin_pct": None if profit is None or not net else profit / net * 100,
    }


def _delta(now: float | None, before: float | None) -> tuple[float | None, float | None]:
    if now is None or before is None:
        return None, None
    d = now - before
    return d, (d / abs(before) * 100 if before else None)


def profit_band(
    cards: Sequence[Mapping[str, Any]], days: int, hien_tai: float | None
) -> tuple[float, float] | None:
    """The Δ lợi nhuận band (P10, P90) over ``days`` the cards were approved with, summed:
    the stored result's band; else ``forecast.metrics.profit`` (low / high around its own
    ``hien_tai``). ``None`` when any card has neither."""
    lo = hi = 0.0
    for card in cards:
        got = result_store.profit_band(result_store.measured_block(card), days)
        a, b = got.get("p10"), got.get("p90")
        if a is None or b is None:
            m = ((card.get("forecast") or {}).get("metrics") or {}).get("profit") or {}
            base = m.get("hien_tai")
            if m.get("low") is None or m.get("high") is None or base is None:
                return None
            a, b = float(m["low"]) - float(base), float(m["high"]) - float(base)
        lo += float(a)
        hi += float(b)
    return (min(lo, hi), max(lo, hi))


def verdict_of(delta: float | None, band: tuple[float, float] | None) -> dict[str, Any] | None:
    if delta is None or band is None:
        return None
    key = VERDICT_ABOVE if delta > band[1] else VERDICT_BELOW if delta < band[0] else VERDICT_IN
    return {"key": key, "label": VERDICT_VI[key], "band": [band[0], band[1]]}


def build_actual(
    days: Mapping[date, Day],
    data_days: frozenset[date],
    *,
    start: date,
    n: int,
    band: tuple[float, float] | None = None,
) -> dict[str, Any] | None:
    """Running Thực tế vs hiện tại. Pure. ``data_days``: the days with stored order data; ``None``
    when none of the window's days has data yet. ``k`` = measured days so far."""
    measured = [d for d in (start + timedelta(days=i) for i in range(n)) if d in data_days]
    k = len(measured)
    if k == 0:
        return None
    before = [start - timedelta(days=i) for i in range(k, 0, -1)]
    now_t, base_t = totals(days, measured), totals(days, before)
    metrics: dict[str, dict[str, Any]] = {}
    for key in METRICS:
        d, pct = _delta(now_t[key], base_t[key])
        metrics[key] = {
            "thuc_te": now_t[key],
            "hien_tai": base_t[key],
            "delta": d,
            "delta_pct": pct,
            "days_measured": k,
            "days": n,
        }
    final = k >= n
    verdict = verdict_of(metrics["profit"]["delta"], band) if final else None
    return {
        "metrics": metrics,
        "days_measured": k,
        "days": n,
        "label": f"Đã đo {k}/{n} ngày",
        "final": final,
        "from": measured[0].isoformat(),
        "to": measured[-1].isoformat(),
        "base_from": before[0].isoformat(),
        "base_to": before[-1].isoformat(),
        "verdict": verdict,
    }


# --------------------------------------------------------------------------------- DB reads


def _net(r: ShopeeShopMetricsDaily) -> float | None:
    """The shop day's doanh thu thực (covered buyer paid, the margin's denominator)."""
    return None if r.buyer_paid_known is None else float(r.buyer_paid_known)


def _net_ratio(r: ShopeeShopMetricsDaily) -> float | None:
    """The shop day's doanh thu thực per đồng of line GMV: a product row carries no doanh thu
    thực of its own, so its line GMV x this ratio stands for it (one basis with the shop)."""
    if r.buyer_paid_known is None or not r.line_gmv:
        return None
    return float(r.buyer_paid_known) / float(r.line_gmv)


async def load_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_id: str | None,
    first: date,
    last: date,
) -> tuple[dict[date, Day], frozenset[date]]:
    """Per-day figures of the product (or the shop) over ``[first, last]`` and the days with
    stored order data (a day with no data is "chưa có dữ liệu", never 0)."""
    s = ShopeeShopMetricsDaily
    srows = (
        await session.scalars(
            select(s).where(
                s.shop_id == shop_id,
                s.order_type == ORDER_TYPE,
                s.day >= first,
                s.day <= last,
                s.orders.is_not(None),
            )
        )
    ).all()
    data = frozenset(r.day for r in srows)
    out: dict[date, Day] = {}
    if product_id is None:
        for r in srows:
            profit = None if r.profit is None else float(r.profit)
            out[r.day] = Day(float(r.gmv or 0), float(r.orders or 0), profit, _net(r))
        return out, data
    p = ShopeeProductMetricsDaily
    prows = (
        await session.scalars(
            select(p).where(
                p.shop_id == shop_id,
                p.order_type == ORDER_TYPE,
                p.item_id == product_id,
                p.variation_id.is_(None),
                p.day >= first,
                p.day <= last,
            )
        )
    ).all()
    by_day = {r.day: r for r in prows}
    by_shop = {r.day: r for r in srows}
    for d in data:
        row = by_day.get(d)
        if row is None:  # a data day with no row for the product = no sales that day
            out[d] = Day(0.0, 0.0, 0.0, 0.0)
            continue
        # the stored product profit is already after the product's ad cost (decision #39: the one
        # ad cost per product, ``ProductProfit.profit`` = contribution - ad_spend); a day with an
        # ad cost and no sale is a row of -ad cost, a day with no row is no sale and no ad cost
        profit = None if row.profit is None else float(row.profit)
        shop_row = by_shop.get(d)
        ratio = None if shop_row is None else _net_ratio(shop_row)
        net = None if ratio is None else float(row.line_gmv or 0) * ratio
        out[d] = Day(float(row.gmv or 0), float(row.orders or 0), profit, net)
    return out, data


async def actual_for(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    product_id: str | None,
    start: date,
    n: int,
    cards: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """The running Thực tế of a set / group over ``start`` and ``n`` days."""
    days, data = await load_days(
        session, shop_id, product_id, start - timedelta(days=n), start + timedelta(days=n)
    )
    first = build_actual(days, data, start=start, n=n)
    if first is None:
        return None
    k = first["days_measured"]
    band = profit_band(cards, n, first["metrics"]["profit"]["hien_tai"]) if cards else None
    return build_actual(days, data, start=start, n=n, band=band) if k >= n else first


async def data_through(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    s = ShopeeShopMetricsDaily
    return await session.scalar(
        select(func.max(s.day)).where(
            s.shop_id == shop_id, s.order_type == ORDER_TYPE, s.orders.is_not(None)
        )
    )


# ----------------------------------------------------------------------------- the job side


@dataclass
class Grouping:
    groups: list[Group] = field(default_factory=list)

    @property
    def grouped_ids(self) -> set[uuid.UUID]:
        return {s.id for g in self.groups if len(g.sets) > 1 for s in g.sets}

    @property
    def multi(self) -> list[Group]:
        return [g for g in self.groups if len(g.sets) > 1]


async def _members(session: AsyncSession, shop_id: uuid.UUID, group: Group) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cs in group.sets:
        for cid in cs.card_ids or []:
            p = await session.get(ShopProposal, uuid.UUID(str(cid)))
            out.append(
                {
                    "card_id": str(cid),
                    "code": None if p is None else p.code,
                    "change_set": str(cs.id),
                    "started_on": cs.started_at.date().isoformat(),
                }
            )
    return out


def group_json(group: Group, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": group.id,
        "change_sets": [str(s.id) for s in group.sets],
        "members": members,
        "codes": [m["code"] for m in members if m["code"]],
        "from": group.start.isoformat(),
        "to": (group.end_excl - timedelta(days=1)).isoformat(),
        "days": group.days,
        "clean": False,
    }


async def regroup(session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> Grouping:
    """Group the shop's running sets; a set an older release cut because of a later change
    comes back to measuring inside its group (its cut result and mark go)."""
    rows = await change_sets.sets_for(session, shop_id, status=[SET_MEASURING, SET_CUT])
    grouping = Grouping(group_sets(rows))
    for g in grouping.multi:
        members = await _members(session, shop_id, g)
        info = group_json(g, members)
        for cs in g.sets:
            if cs.status == SET_CUT:
                kept = {k: v for k, v in (cs.result or {}).items() if k == "reset_card_ids"}
                cs.status = SET_MEASURING
                cs.cut_at = None
                cs.cut_days = None
                cs.result = kept or None
                for cid in cs.card_ids or []:
                    await store.set_meta(
                        session, shop_id, uuid.UUID(str(cid)), {"measure_cut_at": None}
                    )
            cs.result = {**(cs.result or {}), "group": info, "clean": False}
            cs.updated_at = now
    await session.flush()
    return grouping


async def _cards_of(
    session: AsyncSession, shop_id: uuid.UUID, ids: Sequence[Any]
) -> list[dict[str, Any]]:
    wanted = {str(i) for i in ids}
    return [
        card
        for p, card in await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED])
        if str(p.id) in wanted
    ]


async def refresh_actuals(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime, grouping: Grouping
) -> int:
    """Recompute the running Thực tế of every running set / group (daily, as data arrives) and
    of a finished set whose last days had not arrived when it closed. Returns the sets written."""
    n_written = 0
    in_group = grouping.grouped_ids
    targets: list[tuple[list[ShopRecoChangeSet], date, int]] = [
        (g.sets, g.start, g.days) for g in grouping.multi
    ]
    for cs in await change_sets.sets_for(session, shop_id, status=[SET_MEASURING, SET_DONE]):
        if cs.id in in_group or not cs.card_ids:
            continue
        if cs.status == SET_DONE:
            prev = ((cs.result or {}).get("actual") or {}).get("final")
            if prev or (cs.result or {}).get("group"):
                continue
        targets.append(([cs], cs.started_at.date(), cs.window_days))
    for sets, start, n in targets:
        ids = [c for s in sets for c in s.card_ids or []]
        cards = await _cards_of(session, shop_id, ids)
        actual = await actual_for(
            session, shop_id, product_id=sets[0].product_id, start=start, n=n, cards=cards
        )
        if actual is None:
            continue
        for cs in sets:
            cs.result = {**(cs.result or {}), "actual": actual}
            if cs.status == SET_MEASURING:
                result = cs.result
                result.setdefault("state", "running")
                result.setdefault("label", actual["label"])
                if result.get("state") == "running":
                    result["label"] = actual["label"]
            cs.updated_at = now
            n_written += 1
    await session.flush()
    return n_written


__all__ = [
    "METRICS",
    "Group",
    "Grouping",
    "actual_for",
    "build_actual",
    "group_sets",
    "profit_band",
    "refresh_actuals",
    "regroup",
    "totals",
    "verdict_of",
]
