"""The aggregate of a draft plan (P91 D-6): what the cards do TOGETHER, not summed.

**Certain layer, joint.** The cards that change an order line (price levers, vouchers, combo
tiers, and the ads cards for their spend) are re-priced once on the same history orders with every
chosen version stacked on them -- ``mega.evaluate_mega``, the mega_sale stacking: promo / flash
price first, combo tier on lines that reach it, the shop voucher on the order subtotal after
those, platform fees recomputed once per order, one lever per line, the floor check on the
stacked unit price. So a voucher plus a khuyến mãi that are each above the floor can together
break it, and that breach is reported as ``only_when_stacked``. Cards on different products share
no order line and so add (an order holding both is priced once); a shop-wide lever (shop voucher,
shop ads budget) is applied to the orders the product changes already modified when the plan has
product cards, to all orders when it has none -- counted once on the overlap.

Cards the stacking does not model (listing, affiliate, add-on, gift, multi-product combo) add
their own certain layer. This is an approximation and the payload says which cards are in the
joint layer (``joint_cards``) and which are added (``added_cards``).

**Predicted layer.** Each card's predicted P50 (dGMV, dorders, dprofit) adds to the joint certain
layer. The range is combined by the **root sum of squares of the cards' half-widths**
(``combine_predicted``): for each quantile q the width ``|P50_i - q_i|`` of every card is squared,
summed and square-rooted, and taken off (P10, P25) or on (P75, P90) the summed P50. The cards'
prediction errors are treated as independent; the joint range is then narrower than the sum of
the single ranges and wider than the widest one. Deterministic and reproducible (no draws). A card
with an unknown profit leaves dprofit out of the predicted layer and is listed in
``profit_unknown_cards`` (never a 0 passed off as a number).

**Per card.** ``contribution`` = plan total - the plan without the card (joint re-evaluation),
and ``without`` is "bỏ thẻ này thì": the plan's numbers and the floor check after removing it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import (
    config,
    plan,
    plan_steps,
    service,
    versions,
)
from juli_backend.services.shopee_recommendations.cards import shop_deltas
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.mega import (
    ADS_KINDS,
    BUNDLE_KINDS,
    PRICE_KINDS,
    VOUCHER_KINDS,
    MegaWindow,
    candidate_of_card,
    evaluate_mega,
)
from juli_backend.services.shopee_recommendations.model import Candidate

QUANTILES = ("p10", "p25", "p50", "p75", "p90")
METRICS = ("dgmv", "dorders", "dprofit")
#: change kinds the stacking re-prices on the order lines (the rest add their own certain layer)
LINE_KINDS = frozenset(PRICE_KINDS + BUNDLE_KINDS + VOUCHER_KINDS + ADS_KINDS)
RANGE_METHOD = "root_sum_of_squares_of_half_widths"


@dataclass
class Entry:
    """A card in the plan: its frozen payload, the chosen version and the what-if inputs."""

    card_id: str
    code: str | None
    base: dict[str, Any]
    version: int = 1
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evaluated:
    entry: Entry
    card: dict[str, Any]
    cand: Candidate
    #: P97 D85.13: the single-target cards of a many-target card; the joint layer works on these
    parts: list[Evaluated] = field(default_factory=list)

    @property
    def product(self) -> str | None:
        ids = self.card["scope"]["product_ids"]
        return str(ids[0]) if ids else None

    @property
    def is_line(self) -> bool:
        # a combo over a product list (tiers "Mua N") is not re-priced line by line: its own layer
        if self.cand.kind == "bundle_deal" and self.cand.inputs.get("tiers"):
            return False
        return self.cand.kind in LINE_KINDS

    @property
    def money(self) -> Mapping[str, Any]:
        return self.card["predicted"]["money_per_month"]


def evaluate_entry(env: RecoEnv, entry: Entry, *, now: datetime) -> Evaluated | None:
    """The chosen version of the card (with its what-if inputs) on THIS environment."""
    card = service.recompute_card(
        env, entry.base, dict(entry.overrides), now=now, version=entry.version
    )
    if card is None:
        return None
    parts = [
        Evaluated(
            Entry(f"{entry.card_id}#{i}", entry.code, entry.base, entry.version, entry.overrides),
            part,
            candidate_of_card(part),
        )
        for i, part in enumerate(card.pop("_parts", None) or [], start=1)
    ]
    return Evaluated(entry, card, candidate_of_card(card), parts)


def parent_id(card_id: str) -> str:
    """The plan card a (possibly single-target part) id belongs to."""
    return card_id.split("#", 1)[0]


def _parents(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(parent_id(i) for i in ids))


def flatten(evs: Sequence[Evaluated]) -> list[Evaluated]:
    """The cards the joint layer works on: a many-target card stands for its single-target parts."""
    return [p for e in evs for p in (e.parts or [e])]


# ------------------------------------------------------------------------------------ pure


def combine_predicted(
    parts: Sequence[Mapping[str, Mapping[str, float | None]]],
) -> dict[str, dict[str, float | None]]:
    """Predicted layer of several cards: P50s add, the range is the root sum of squares of the
    cards' half-widths (see the module docstring). ``parts``: ``{quantile: {metric: value}}`` per
    card; a metric a card does not know (None) is left out for that card; a metric nobody knows
    stays None. No parts -> all zeros."""
    out: dict[str, dict[str, float | None]] = {q: {} for q in QUANTILES}
    for m in METRICS:
        known = [
            (float(mid_i), {q: p[q][m] for q in QUANTILES})
            for p in parts
            if (mid_i := p["p50"].get(m)) is not None
        ]
        if not known:
            for q in QUANTILES:
                out[q][m] = None if parts else 0.0
            continue
        mid = sum(k[0] for k in known)
        for q in QUANTILES:
            if q == "p50":
                out[q][m] = mid
                continue
            squares = 0.0
            for mid_i, qs in known:
                v = qs[q]
                if v is not None:
                    squares += (mid_i - float(v)) ** 2
            width = math.sqrt(squares)
            out[q][m] = mid - width if q in ("p10", "p25") else mid + width
    return out


def _add(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def total_of(certain: Mapping[str, float], predicted: Mapping[str, Mapping[str, float | None]]):
    """``certain`` (month) + the predicted layer per quantile = the plan's total range."""
    return {
        q: {
            "dgmv": _add(certain["dgmv"], predicted[q]["dgmv"]),
            "dorders": predicted[q]["dorders"],
            "dprofit": _add(certain["dprofit"], predicted[q]["dprofit"]),
        }
        for q in QUANTILES
    }


# --------------------------------------------------------------------------------- joint


@dataclass
class Joint:
    ids: frozenset[str]
    certain: dict[str, float]
    predicted: dict[str, dict[str, float | None]]
    total: dict[str, dict[str, float | None]]
    breaches: list[dict[str, Any]]
    five: dict[str, Any] | None
    joint_cards: list[str]
    added_cards: list[str]
    profit_unknown: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def floor_ok(self) -> bool:
        return not any(b["type"] == "floor" for b in self.breaches)

    def money(self) -> dict[str, Any]:
        """The ``prediction.convert`` shape (``shop_deltas`` and the card brief read it)."""
        return {
            "days": config.DAYS_PER_MONTH,
            "certain": dict(self.certain),
            "predicted": self.predicted,
            "total": self.total,
        }

    def brief(self) -> dict[str, Any]:
        t = self.total
        return {
            "dprofit": {
                "certain": self.certain["dprofit"],
                **{q: t[q]["dprofit"] for q in ("p10", "p50", "p90")},
            },
            "dgmv": {"certain": self.certain["dgmv"], "p50": t["p50"]["dgmv"]},
            "dorders_p50": t["p50"]["dorders"],
            "cost_month": self.certain["dchi"],
            "floor_ok": self.floor_ok,
        }


def _window(env: RecoEnv) -> MegaWindow:
    start = datetime.combine(env.as_of, datetime.min.time())
    return MegaWindow(start, start + timedelta(days=env.window_days))


def joint_lifts(evs: Sequence[Evaluated]) -> tuple[list[Evaluated], list[str]]:
    """One predicted lift per product (D85.4): the options of one product act on the same buyers,
    so their P50s are not added. The option with the largest predicted GMV (ties: smallest card
    id) carries the product's lift; the others keep their certain layer (cost) and add no second
    lift. Cards with no product (shop-wide) each carry their own. Independent of the order the
    cards were added. Returns the cards whose prediction counts and the ids that were folded."""
    by_product: dict[str | None, list[Evaluated]] = {}
    for e in evs:
        by_product.setdefault(e.product, []).append(e)
    keep: list[Evaluated] = []
    folded: list[str] = []
    for product, group in by_product.items():
        if product is None or len(group) == 1:
            keep.extend(group)
            continue
        ranked = sorted(
            group,
            key=lambda e: (-abs(e.money["predicted"]["p50"].get("dgmv") or 0.0), e.entry.card_id),
        )
        keep.append(ranked[0])
        folded.extend(e.entry.card_id for e in ranked[1:])
    return keep, sorted(folded)


def joint(env: RecoEnv, evs: Sequence[Evaluated]) -> Joint:
    """The certain layer of these cards stacked on the same orders + the combined prediction."""
    evs = sorted(flatten(evs), key=lambda e: e.entry.card_id)  # never depends on the order added
    line = [e for e in evs if e.is_line and e.card["family"] != "mega_sale"]
    added = [e for e in evs if e not in line]
    certain = {"dgmv": 0.0, "dprofit": 0.0, "dchi": 0.0}
    breaches: list[dict[str, Any]] = []
    five: dict[str, Any] | None = None
    notes: list[str] = []
    if line:
        # a shop-wide lever (a shop voucher) always reaches every shop order, whatever else is in
        # the plan (D85.4): its reach never depends on which other options are present
        shop_wide = any(e.cand.kind in VOUCHER_KINDS for e in line)
        res = evaluate_mega(
            env, [e.cand for e in line], _window(env), env.daily_cap, all_orders=shop_wide
        )
        if res.get("refusal"):  # nothing to stack on: fall back to each card alone
            notes.append(f"joint_unavailable:{res['refusal']}")
            added, line = [*added, *line], []
        else:
            prof = res["profit"]
            days = Decimal(min(prof.effect_days, config.DAYS_PER_MONTH))
            certain["dgmv"] += float(prof.certain_dgmv_per_day * days)
            certain["dprofit"] += float(-prof.extra_cost_per_day * days)
            certain["dchi"] += float(prof.dchi_per_day * days)
            breaches.extend({"type": "floor", **b} for b in res["breaches"])
            five = res["five"]
    for e in added:
        c = e.money["certain"]
        certain["dgmv"] += c["dgmv"]
        certain["dprofit"] += c["dprofit"]
        certain["dchi"] += c["dchi"]
        breaches.extend(
            {"type": "floor", "card_id": e.entry.card_id, **b} for b in e.card["floor"]["breaches"]
        )
    counted, folded = joint_lifts(evs)
    if folded:
        notes.append("lift_shared_per_product:" + ",".join(folded))
    predicted = combine_predicted([e.money["predicted"] for e in counted])
    unknown = [e.entry.card_id for e in evs if e.money["predicted"]["p50"].get("dprofit") is None]
    return Joint(
        ids=frozenset(e.entry.card_id for e in evs),
        certain=certain,
        predicted=predicted,
        total=total_of(certain, predicted),
        breaches=breaches,
        five=five,
        joint_cards=_parents([e.entry.card_id for e in line]),
        added_cards=_parents([e.entry.card_id for e in added]),
        profit_unknown=_parents(unknown),
        notes=notes,
    )


class _Memo:
    def __init__(self, env: RecoEnv, evs: Sequence[Evaluated]) -> None:
        self.env = env
        self.by_id = {e.entry.card_id: e for e in [*evs, *flatten(evs)]}
        self.cache: dict[frozenset[str], Joint] = {}

    def of(self, ids: Sequence[str]) -> Joint:
        key = frozenset(ids)
        if key not in self.cache:
            self.cache[key] = joint(self.env, [self.by_id[i] for i in sorted(key)])
        return self.cache[key]


# ------------------------------------------------------------------------------ the payload


def _breach_view(
    plan_joint: Joint, evs: Sequence[Evaluated]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan-level floor breaches with the cards that own them, and the products stacked on."""
    own: dict[str, set[str]] = {}
    for e in evs:
        for b in e.card["floor"]["breaches"]:
            own.setdefault(str(b.get("sku")), set()).add(e.entry.card_id)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for b in plan_joint.breaches:
        if b["type"] != "floor":
            continue
        key = (str(b.get("sku")), str(b.get("card_id")))
        if key in seen:
            continue
        seen.add(key)
        owners = sorted(own.get(str(b.get("sku")), ()))
        out.append({**b, "card_ids": owners, "only_when_stacked": not owners})
    by_product: dict[str, list[Evaluated]] = {}
    for e in flatten(evs):
        if e.product:
            by_product.setdefault(e.product, []).append(e)
    stacked = [
        {
            "product_id": pid,
            "cards": _parents([e.entry.card_id for e in group]),
            "codes": list(dict.fromkeys(e.entry.code for e in group)),
            "count": len(_parents([e.entry.card_id for e in group])),
            "stacked_on_same_orders": sum(1 for e in group if e.is_line) > 1,
        }
        for pid, group in sorted(by_product.items())
        if len(_parents([e.entry.card_id for e in group])) > 1
    ]
    return out, stacked


def _cost_block(env: RecoEnv, j: Joint, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    days = Decimal(config.DAYS_PER_MONTH)
    before = Decimal(str(base["chi_per_day"])) if base is not None else env.shop_chi_per_day()
    delta = Decimal(str(j.certain["dchi"])) / days
    after = before + delta
    cap = env.daily_cap
    over = cap is not None and after > cap
    return {
        "per_day_before": float(before),
        "per_day_after": float(after),
        "delta_per_day": float(delta),
        "per_month_after": float(after * days),
        "delta_per_month": j.certain["dchi"],
        "cap_per_day": None if cap is None else float(cap),
        "over_cap": bool(over),
        "over_by_per_day": float(after - cap) if over and cap is not None else 0.0,
        "label": "Chi phí = quảng cáo + voucher + khuyến mãi + combo + hoa hồng",
    }


def _today(env: RecoEnv, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """ "Hôm nay": the plan's frozen base when it has one, else ShopMetrics of the env."""
    if base is not None:
        return {
            "as_of": base["as_of"],
            "gmv_30d": base["gmv_30d"],
            "orders_30d": base["orders_30d"],
            "aov": base["aov"],
            "margin_pct": base["margin_pct"],
        }
    m = env.metrics
    gmv, orders = float(env.shop_gmv_30d), env.shop_orders_30d
    return {
        "as_of": env.as_of.isoformat(),
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": None if m.aov is None else float(m.aov),
        "margin_pct": None if m.margin_pct is None else float(m.margin_pct),
    }


def _after(today: Mapping[str, Any], deltas: Mapping[str, float]) -> dict[str, Any]:
    orders = today["orders_30d"] + deltas["orders"]
    gmv = today["gmv_30d"] + deltas["gmv"]
    return {
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": gmv / orders if orders else None,
        "margin_pct": None if today["margin_pct"] is None else today["margin_pct"] + deltas["bien"],
    }


def _product_block(env: RecoEnv, pid: str, evs: Sequence[Evaluated], memo: _Memo) -> dict[str, Any]:
    j = memo.of([e.entry.card_id for e in evs])
    base = float(sum((ln.order_value for ln in env.lines_for([pid])), ZERO))
    t = j.total
    rel: dict[str, float | None] = {}
    for q in ("p10", "p50", "p90"):
        gmv = t[q]["dgmv"]
        rel[q] = None if base <= 0 or gmv is None else gmv / base
    stats = plan.stats_for(env, [pid], "orders")
    return {
        "product_id": pid,
        "name": env.name(pid),
        "cards": _parents([e.entry.card_id for e in evs]),
        "codes": list(dict.fromkeys(e.entry.code for e in evs)),
        "joint": j.brief(),
        "predicted_rel_gmv": rel,
        "base_gmv_30d": base,
        "orders_per_day": stats.orders_per_day,
        "window": plan.window_options("orders", stats),
        "steps": plan_steps.build_steps(
            [
                {
                    "card_id": parent_id(e.entry.card_id),
                    "code": e.entry.code,
                    "title": e.card["title"],
                    "change_kind": e.cand.kind,
                    "version_label": versions.versions_of(e.card)[e.entry.version - 1].get("label"),
                }
                for e in evs
            ],
            memo.of,
        ),
    }


def aggregate(
    env: RecoEnv,
    entries: Sequence[Entry],
    *,
    now: datetime,
    base: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[Evaluated]]:
    """The plan's aggregate payload and the evaluated cards (chosen version on this env)."""
    evs: list[Evaluated] = []
    unavailable: list[str] = []
    for entry in entries:
        ev = evaluate_entry(env, entry, now=now)
        if ev is None:
            unavailable.append(entry.card_id)
        else:
            evs.append(ev)
    today = _today(env, base)
    if not evs:
        return {
            "as_of": env.as_of.isoformat(),
            "n_cards": 0,
            "today": today,
            "cards": [],
            "unavailable_cards": unavailable,
            "range_method": RANGE_METHOD,
        }, []
    memo = _Memo(env, evs)
    ids = [e.entry.card_id for e in evs]
    full = memo.of(ids)
    floor_breaches, stacked = _breach_view(full, evs)
    cost = _cost_block(env, full, base)
    breaches: list[dict[str, Any]] = [*floor_breaches]
    if cost["over_cap"]:
        breaches.append(
            {
                "type": "spend_cap",
                "spend_per_day_after": cost["per_day_after"],
                "cap": cost["cap_per_day"],
                "over_by_per_day": cost["over_by_per_day"],
            }
        )
    deltas = shop_deltas(env, full.money(), "p50")
    cards: list[dict[str, Any]] = []
    for e in evs:
        rest = memo.of([i for i in ids if i != e.entry.card_id]) if len(ids) > 1 else None
        alone = memo.of([e.entry.card_id])
        wb, ab = (rest.brief() if rest else None), alone.brief()
        pb = full.brief()
        contribution = {
            "dprofit_certain": pb["dprofit"]["certain"] - (wb["dprofit"]["certain"] if wb else 0.0),
            "dprofit_p50": _sub(pb["dprofit"]["p50"], wb["dprofit"]["p50"] if wb else 0.0),
            "dgmv_p50": _sub(pb["dgmv"]["p50"], wb["dgmv"]["p50"] if wb else 0.0),
            "cost_month": pb["cost_month"] - (wb["cost_month"] if wb else 0.0),
        }
        cards.append(
            {
                "card_id": e.entry.card_id,
                "code": e.entry.code,
                "title": e.card["title"],
                "family": e.card["family"],
                "change_kind": e.cand.kind,
                "product_id": e.product,
                "version": e.entry.version,
                "version_label": versions.versions_of(e.card)[e.entry.version - 1].get("label"),
                "inputs": e.card["inputs"],
                "what_if": dict(e.entry.overrides),
                "in_joint_layer": e.entry.card_id in full.joint_cards,
                "alone": ab,
                "contribution": contribution,
                "without": None
                if wb is None
                else {
                    **wb,
                    "delta": {
                        "dprofit_p50": contribution["dprofit_p50"],
                        "dgmv_p50": contribution["dgmv_p50"],
                        "cost_month": contribution["cost_month"],
                    },
                },
                "floor_ok": e.card["floor"]["ok"],
                "breaches": [{"type": "floor", **b} for b in e.card["floor"]["breaches"]],
            }
        )
    by_product: dict[str, list[Evaluated]] = {}
    shop_wide: list[Evaluated] = []
    for e in flatten(evs):
        if e.product:
            by_product.setdefault(e.product, []).append(e)
        else:
            shop_wide.append(e)
    products = [_product_block(env, pid, group, memo) for pid, group in sorted(by_product.items())]
    shop_block = None
    if shop_wide:
        sj = memo.of([e.entry.card_id for e in shop_wide])
        shop_block = {
            "cards": [e.entry.card_id for e in shop_wide],
            "codes": [e.entry.code for e in shop_wide],
            "joint": sj.brief(),
        }
    out = {
        "as_of": env.as_of.isoformat(),
        "n_cards": len(evs),
        "today": today,
        "after": {**_after(today, deltas), "label": "Dự kiến (P50)"},
        "deltas_p50": deltas,
        "five_numbers": full.five,
        "dprofit_month": {
            "certain": full.certain["dprofit"],
            "predicted": {q: full.predicted[q]["dprofit"] for q in ("p10", "p50", "p90")},
            "total": {q: full.total[q]["dprofit"] for q in ("p10", "p50", "p90")},
        },
        "dgmv_month": {
            "certain": full.certain["dgmv"],
            "total": {q: full.total[q]["dgmv"] for q in ("p10", "p50", "p90")},
        },
        "dorders_month": {q: full.total[q]["dorders"] for q in ("p10", "p50", "p90")},
        "cost": cost,
        "floor": {"ok": not floor_breaches, "breaches": floor_breaches},
        "breaches": breaches,
        "stacked_products": stacked,
        "cards": cards,
        "products": products,
        "shop_wide": shop_block,
        "steps_summary": {
            "shop": {
                "products": len(products),
                "dprofit_p50": full.total["p50"]["dprofit"],
                "dprofit_certain": full.certain["dprofit"],
                "dgmv_p50": full.total["p50"]["dgmv"],
                "margin_pct_before": today["margin_pct"],
                "margin_pct_after": _after(today, deltas)["margin_pct"],
            },
            "note": "Từng bước chồng lên các bước trước; tổng shop là kết quả chung của kế hoạch.",
        },
        "joint_cards": full.joint_cards,
        "added_cards": full.added_cards,
        "profit_unknown_cards": full.profit_unknown,
        "unavailable_cards": unavailable,
        "notes": full.notes,
        "range_method": RANGE_METHOD,
        "range_note": "Khoảng dự kiến gộp: P50 cộng lại, độ rộng gộp theo căn bậc hai tổng "
        "bình phương.",
    }
    return out, evs


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


__all__ = [
    "Entry",
    "Evaluated",
    "Joint",
    "aggregate",
    "combine_predicted",
    "evaluate_entry",
    "flatten",
    "joint",
    "joint_lifts",
    "total_of",
]
