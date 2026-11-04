"""Ranking (contract 11, ADR-121 d.2): hard filters, then the share of the gap to the month's
targets that an action closes at the cautious end (P25), weighted to the KPI furthest behind.

    score = sum_k w_k * min(dKPI_k(P25), gap_k) / gap_k    (k in {GMV, don, AOV, bien} behind)
    w_k  proportional to gap_k / target_k, normalised to 1

dKPI uses the P25 of the predicted range plus the certain layer. No target set (nothing behind
or no target) -> the score is the expected dGMV per month at P25 under the same filters.

Hard filters, in this order (a card is counted under the first it fails; all failing reasons
are listed): ``locked_by_plan`` (a product with an open plan / inside a mega_sale window),
``out_of_stock``, ``below_operating_floor``, ``over_spend_cap``, ``negative_profit_p50``.

P91 D-1: ``duplicate_product`` is no longer a filter. One change per product per measurement
window still holds, but as a queue: every card that passes the filters is kept and gets
``product_queue`` 1..n among the cards of its product, best score first (1 = the Quyết định
card; ``product_queue.py`` moves the next one up when it closes). Acceptance statistics break
ties only; the "đáng thử" slot, when reserved, is the eligible card with the largest simulation
knowledge-gradient. Pure.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.shopee_recommendations import config

FILTERS = (
    "locked_by_plan",
    "out_of_stock",
    "below_operating_floor",
    "over_spend_cap",
    "negative_profit_p50",
)


@dataclass
class RankInput:
    id: str
    kind: str
    family: str
    items: tuple[str, ...] = ()
    floor_breach: bool = False
    dprofit_p50: float | None = None
    spend_after: float | None = None
    spend_cap: float | None = None
    in_stock: bool | None = None  # None = unknown (passes, flagged)
    kpi_p25: dict[str, float] = field(default_factory=dict)  # gmv, orders, aov, bien (points)
    dgmv_p25: float = 0.0
    acceptance: float | None = None
    kg_value: float | None = None
    mega_children_items: tuple[str, ...] = ()

    def all_items(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.items, *self.mega_children_items)))


@dataclass
class Gaps:
    """Per KPI: target, projected month value, gap (>0 = behind)."""

    rows: dict[str, dict[str, float]]

    @property
    def behind(self) -> dict[str, dict[str, float]]:
        return {k: r for k, r in self.rows.items() if r["gap"] > 0 and r["target"] > 0}

    def json(self) -> dict[str, Any]:
        return {k: {a: round(b, 4) for a, b in r.items()} for k, r in self.rows.items()}


def month_gaps(
    *,
    targets: dict[str, float | None],
    gmv_30d: float,
    orders_30d: float,
    margin_pct: float | None,
    window_days: int,
    month_days: int,
) -> Gaps:
    """Projected month = the window's pace x month days (as the critical list does)."""
    rows: dict[str, dict[str, float]] = {}
    projected_gmv = gmv_30d / window_days * month_days
    projected_orders = orders_30d / window_days * month_days
    aov = gmv_30d / orders_30d if orders_30d else 0.0
    for key, name, cur in (
        ("gmv", "gmv_month", projected_gmv),
        ("orders", "orders_month", projected_orders),
        ("aov", "aov_month", aov),
    ):
        t = targets.get(name)
        if t:
            rows[key] = {"target": t, "current": cur, "gap": max(t - cur, 0.0)}
    m = targets.get("margin_pct")
    if m and margin_pct is not None:
        rows["bien"] = {"target": m, "current": margin_pct, "gap": max(m - margin_pct, 0.0)}
    return Gaps(rows)


def month_days_of(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def score(card: RankInput, gaps: Gaps) -> tuple[float, dict[str, Any]]:
    behind = gaps.behind
    if not behind:
        return card.dgmv_p25, {"mode": "dgmv_month_p25", "dgmv_p25": card.dgmv_p25}
    weights = {k: r["gap"] / r["target"] for k, r in behind.items()}
    total_w = sum(weights.values())
    parts: dict[str, Any] = {}
    s = 0.0
    for k in config.KPI_ORDER:  # GMV first: on equal weights the north star leads
        if k not in behind:
            continue
        r = behind[k]
        d = card.kpi_p25.get(k, 0.0)
        share = min(d, r["gap"]) / r["gap"]
        w = weights[k] / total_w
        parts[k] = {
            "weight": round(w, 4),
            "delta_p25": round(d, 4),
            "gap": round(r["gap"], 4),
            "closed": round(share, 4),
        }
        s += w * share
    return s, {"mode": "gap_share_p25", "kpis": parts}


@dataclass
class Ranked:
    id: str
    position: int
    score: float
    detail: dict[str, Any]
    explore: bool = False
    #: place among the kept cards of the same product (1 = first); None = no product
    product_queue: int | None = None


@dataclass
class RankResult:
    ordered: list[Ranked]
    dropped: list[dict[str, Any]]
    counts: dict[str, int]  # first failing filter -> n
    counts_any: dict[str, int]  # every failing filter -> n
    mode: str
    unknown: dict[str, int] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "filters_first": self.counts,
            "filters_any": self.counts_any,
            "eligible": len(self.ordered),
            "queued_behind": sum(1 for r in self.ordered if (r.product_queue or 1) > 1),
            "dropped": len(self.dropped),
            "unknown_inputs": self.unknown,
        }


def hard_filters(card: RankInput, locked: dict[str, str]) -> list[str]:
    failed: list[str] = []
    if any(i in locked for i in card.all_items()):
        failed.append("locked_by_plan")
    if card.in_stock is False:
        failed.append("out_of_stock")
    if card.floor_breach:
        failed.append("below_operating_floor")
    if (
        card.spend_cap is not None
        and card.spend_after is not None
        and card.spend_after > card.spend_cap
    ):
        failed.append("over_spend_cap")
    if card.dprofit_p50 is not None and card.dprofit_p50 < 0:
        failed.append("negative_profit_p50")
    return failed


def rank(
    cards: list[RankInput],
    gaps: Gaps,
    *,
    locked: dict[str, str] | None = None,
    top_n: int = config.DEFAULT_TOP_N,
    explore_slot: bool = False,
) -> RankResult:
    locked = locked or {}
    first: dict[str, int] = dict.fromkeys(FILTERS, 0)
    anyc: dict[str, int] = dict.fromkeys(FILTERS, 0)
    dropped: list[dict[str, Any]] = []
    scored: list[tuple[RankInput, float, dict[str, Any]]] = []
    unknown = {"stock": 0, "profit": 0}
    for c in cards:
        failed = hard_filters(c, locked)
        if c.in_stock is None:
            unknown["stock"] += 1
        if c.dprofit_p50 is None:
            unknown["profit"] += 1
        if failed:
            first[failed[0]] += 1
            for f in failed:
                anyc[f] += 1
            dropped.append({"id": c.id, "kind": c.kind, "reasons": failed})
            continue
        s, d = score(c, gaps)
        scored.append((c, s, d))
    scored.sort(key=lambda t: (-t[1], -(t[0].acceptance or 0.0), -t[0].dgmv_p25, t[0].id))
    kept = scored
    seen: dict[str, int] = {}
    ordered: list[Ranked] = []
    for i, (c, s, d) in enumerate(kept):
        product = c.items[0] if c.items else None
        place = None
        if product is not None:
            seen[product] = seen.get(product, 0) + 1
            place = seen[product]
        ordered.append(Ranked(c.id, i + 1, s, d, product_queue=place))
    if explore_slot and len(kept) > top_n:
        pool = [(c, s, d) for c, s, d in kept[top_n - 1 :] if c.kg_value is not None]
        if pool:
            pick = max(pool, key=lambda t: t[0].kg_value or 0.0)
            rest = [r for r in ordered if r.id != pick[0].id]
            slot = Ranked(
                pick[0].id,
                top_n,
                pick[1],
                {**pick[2], "slot": "dang_thu", "kg_value": pick[0].kg_value},
                True,
                next(r.product_queue for r in ordered if r.id == pick[0].id),
            )
            ordered = [*rest[: top_n - 1], slot, *rest[top_n - 1 :]]
            for i, r in enumerate(ordered):
                r.position = i + 1
    mode = "gap_share_p25" if gaps.behind else "dgmv_month_p25"
    return RankResult(ordered, dropped, first, anyc, mode, unknown)
