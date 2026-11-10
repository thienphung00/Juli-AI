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

**Option results (P98 / ADR-122 d.2, d.5).** The numbers the plan shows -- Δ GMV, Δ đơn, Δ lợi
nhuận and their range -- are the sum of the cards' ``OptionResult`` (the builder's one path: funnel
base -> family -> engine, ``integrate.evaluate``), each scaled to 30 days; the money layer below no
longer feeds them. ``result_basis`` is ``"option_result"``. P50s add and the range is the root sum
of squares of the half-widths of the cards' P10 / P90 columns. A card without a result (refused, not
estimable, no way to rebuild its spec) is listed as "chưa ước tính được", left out of the sums and
its exact cost still counts against the cap (the certain layer). An unknown profit makes the plan's
profit unknown. The "after" funnel is today's views / clicks / đơn plus the cards' deltas, so
Đơn = Lượt xem x CTR x CTOR and GMV = Đơn x AOV hold exactly.

**Predicted layer (legacy money layer, used only when no results are passed).** Each card's
predicted P50 (dGMV, dorders, dprofit) adds to the joint certain
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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import (
    config,
    plan,
    plan_steps,
    service,
    versions,
)
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

if TYPE_CHECKING:
    from juli_backend.services.shopee_builder.engine.contract import OptionResult, Scenario

RESULT_BASIS = "option_result"
NOT_ESTIMABLE_TEXT = "chưa ước tính được"
HORIZON_DAYS = 30
RESULT_QUANTILES = ("p10", "p50", "p90")
RESULT_METRICS = ("dgmv", "dorders", "dprofit", "dviews", "dclicks")

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
        env, entry.base, dict(entry.overrides), now=now, version=entry.version, keep_parts=True
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


# ------------------------------------------------------------------- option results (P98)


@dataclass(frozen=True)
class Horizon:
    """P99b (owner, 2026-11-10): Kế hoạch is the expected outcome of its cards over the next 30
    days starting today. A card counts only on its own days inside this horizon."""

    start: date
    days: int = HORIZON_DAYS

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)

    def overlap(self, start: date, end: date) -> tuple[date, date] | None:
        lo, hi = max(start, self.start), min(end, self.end)
        return None if hi < lo else (lo, hi)

    def each_day(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]

    def json(self) -> dict[str, Any]:
        return {
            "from": self.start.isoformat(),
            "to": self.end.isoformat(),
            "days": self.days,
            "label": f"{self.days} ngày tới (từ hôm nay)",
        }


@dataclass
class CardResult:
    """One card (or one target of a many-target card) as an ``OptionResult``, or why it has none.

    ``start`` is the first day of the card's own dates (the version's spec); ``None`` = a change
    without dates, which starts with the plan (today) and runs ``result.days`` days."""

    card_id: str
    result: OptionResult | None
    reason: str | None = None  # a code; ``None`` with a result = fine
    start: date | None = None
    product: str | None = None

    @property
    def ok(self) -> bool:
        r = self.result
        return r is not None and r.estimable and r.likely is not None

    # -- the card's own dates (what Tự tạo shows) ------------------------------------------------

    def own_span(self, h: Horizon) -> tuple[date, date] | None:
        r = self.result
        if r is None:
            return None
        first = self.start or h.start
        return first, first + timedelta(days=r.days - 1)

    def counted(self, h: Horizon) -> tuple[date, date] | None:
        """The card's days inside the horizon; ``None`` = none of them."""
        span = self.own_span(h)
        return None if span is None else h.overlap(*span)

    def counted_days(self, h: Horizon) -> int:
        c = self.counted(h)
        return 0 if c is None else (c[1] - c[0]).days + 1

    def delta_own(self, which: str) -> dict[str, float | None] | None:
        """The Δ of the ``low`` / ``likely`` / ``high`` column over the card's OWN days (the
        builder's figure for the dates it was set on; never scaled to 30 days)."""
        r = self.result
        col: Scenario | None = None if r is None else getattr(r, which)
        if r is None or col is None:
            return None

        def d(name: str) -> float | None:
            a, b = getattr(col, name), getattr(r.before, name)
            return None if a is None or b is None else float(a - b)

        return {m: d(f) for m, f in RESULT_FIELDS.items()}

    def cost_own(self) -> float | None:
        return None if self.result is None else float(self.result.cost_total)

    def cost_per_day(self) -> float | None:
        r = self.result
        return None if r is None else float(r.cost_total) / r.days

    def cost_in(self, h: Horizon) -> float | None:
        """The cost on the card's days inside the horizon (its own cost per day × those days);
        ``None`` when the card has no result (unknown, never a number from elsewhere)."""
        per_day = self.cost_per_day()
        return None if per_day is None else per_day * self.counted_days(h)

    def delta(self, which: str, h: Horizon | None = None) -> dict[str, float | None] | None:
        """The Δ inside the horizon: the own-days Δ × counted days ÷ own days (a card's effect
        is spread evenly over its own days). Without a horizon: the own-days Δ."""
        own = self.delta_own(which)
        r = self.result
        if own is None or r is None or h is None:
            return own
        k = self.counted_days(h) / r.days
        return {m: None if v is None else v * k for m, v in own.items()}

    def before_30d(self) -> dict[str, float | None] | None:
        """P99: the base this card's Δ was computed on (its scope's stored funnel), per 30 days --
        the plan adds the card's Δ onto this, never onto another scope's figures."""
        r = self.result
        if r is None:
            return None
        k = HORIZON_DAYS / r.days
        b = r.before

        def f(x: Any) -> float | None:
            return None if x is None else float(x) * k

        return {
            "gmv_30d": f(b.gmv),
            "orders_30d": f(b.orders),
            "profit_30d": f(b.profit),
            "views_30d": f(b.views),
            "clicks_30d": f(b.clicks),
            "aov": float(b.gmv / b.orders) if b.orders > 0 else None,
        }


RESULT_FIELDS = {
    "dgmv": "gmv",
    "dorders": "orders",
    "dprofit": "profit",
    "dviews": "views",
    "dclicks": "clicks",
}
COLUMNS = (("p10", "low"), ("p50", "likely"), ("p90", "high"))


@dataclass
class Counted:
    """What one leaf card contributes to the plan inside the horizon: its own-days Δ spread
    evenly over its own days, times the days that fall inside the horizon. Cards on the same
    product add (ADR-122 d.2: each result is computed on the same base, with its own drivers);
    nothing of the base is added twice -- the base is counted once per scope."""

    card_id: str
    cols: dict[str, dict[str, float | None]]  # p10 / p50 / p90 -> metric -> Δ in the horizon
    counted_days: int
    cost: float | None


def count_in_horizon(results: Sequence[CardResult], h: Horizon) -> dict[str, Counted]:
    """Each estimable leaf's Δ inside the horizon (its counted days only)."""
    out: dict[str, Counted] = {}
    for r in results:
        if not r.ok:
            continue
        cols = {q: dict(r.delta(col, h) or {}) for q, col in COLUMNS}
        out[r.card_id] = Counted(r.card_id, cols, r.counted_days(h), r.cost_in(h))
    return out


def round_orders(x: float | None) -> float | None:
    """Δ Đơn to the precision the cards show (``engine.wire.round_count``): one decimal under 10
    orders, whole orders from 10 up."""
    from juli_backend.services.shopee_builder.engine.wire import round_count

    return round_count(x)


def _voucher_spec(cand: Candidate, today: Any) -> dict[str, Any] | None:
    i = cand.inputs
    scope = str(cand.extra.get("voucher_scope") or ("product" if cand.items else "shop"))
    if scope in ("follower", "livestream"):
        return None
    out: dict[str, Any] = {
        "kind": "voucher",
        "scope": scope,
        "item_ids": list(cand.items) if scope == "product" else [],
        "min_spend": int(i.get("min_spend") or 0),
    }
    if i.get("pct") is not None:
        out.update(discount_type="pct", value=float(i["pct"]))
        if i.get("max_value"):
            out["max_value"] = int(i["max_value"])
    elif i.get("value") is not None:
        out.update(discount_type="amount", value=float(i["value"]))
    else:
        return None
    if i.get("quantity"):
        out["usage_limit"] = int(i["quantity"])
    if i.get("per_user_limit"):
        out["per_buyer_limit"] = int(i["per_user_limit"])
    if i.get("days"):
        out["start"] = today.isoformat()
        out["end"] = (today + timedelta(days=int(i["days"]) - 1)).isoformat()
    return out


def _combo_spec(cand: Candidate) -> dict[str, Any] | None:
    i = cand.inputs
    if not i.get("tiers") or not i.get("discount_type"):
        return None
    out: dict[str, Any] = {
        "kind": "combo",
        "item_ids": list(cand.items),
        "discount_type": i["discount_type"],
        "tiers": [{"qty": t["qty"], "value": t["value"]} for t in i["tiers"]],
    }
    if i.get("name"):
        out["name"] = i["name"]
    if i.get("limit_per_buyer"):
        out["purchase_limit"] = int(i["limit_per_buyer"])
    for key in ("start", "end"):
        if i.get(key):
            out[key] = i[key]
    return out


def _listing_combo_spec(cand: Candidate) -> dict[str, Any] | None:
    i = cand.inputs
    if not (i.get("title") and i.get("price") and i.get("stock") is not None):
        return None
    out: dict[str, Any] = {
        "kind": "listing_combo",
        "title": i["title"],
        "price": int(i["price"]),
        "stock": int(i["stock"]),
        "image_refs": list(i.get("image_refs") or []),
        "member_ids": list(cand.items),
    }
    if i.get("sku"):
        out["sku"] = i["sku"]
    return out


def _item_spec(kind: str, cand: Candidate) -> dict[str, Any] | None:
    if not cand.items:
        return None
    item, i = cand.items[0], cand.inputs
    if kind == "title" and i.get("title"):
        return {"kind": "title", "item_id": item, "title": i["title"]}
    if kind == "description_first_line" and i.get("first_line"):
        return {"kind": "description_first_line", "item_id": item, "first_line": i["first_line"]}
    if kind == "listing_hide":
        return {"kind": "listing_hide", "item_id": item}
    if kind == "listing_relist":
        out: dict[str, Any] = {"kind": "listing_relist", "item_id": item}
        if i.get("stock") is not None:
            out["stock"] = int(i["stock"])
        return out
    return None


Variations = Mapping[str, Sequence[Mapping[str, Any]]]


def _variation_prices(
    cand: Candidate, variations: Variations | None, *, price_change: bool
) -> list[dict[str, Any]] | None:
    """The card's price as the builder's per-variation rows (variation id from the product's
    variation list): the per-SKU rows when the card keeps them, else its one slider (giảm %, giá
    mới % so với giá hiện tại) on every variation of the product. ``None`` when it cannot be
    matched."""
    if not cand.items or variations is None:
        return None
    known = variations.get(cand.items[0], ())
    by_sku = {str(v.get("sku_key")): str(v.get("variation_id") or "") for v in known}
    rows = cand.inputs.get("variations")
    if not rows:  # a slider card: the same change on each variation
        if price_change and cand.inputs.get("new_price_pct") is not None:
            one: dict[str, Any] = {"change_pct": float(cand.inputs["new_price_pct"]) - 100.0}
        elif not price_change and cand.inputs.get("discount_pct") is not None:
            one = {"discount_pct": float(cand.inputs["discount_pct"])}
        else:
            return None
        return [{"variation_id": vid, **one} for vid in dict.fromkeys(by_sku.values())] or None
    out: list[dict[str, Any]] = []
    for row in rows:
        vid = by_sku.get(str(row.get("sku")))
        if vid is None:
            return None
        picked: dict[str, Any] = {"variation_id": vid}
        if row.get("final_price") is not None:
            picked["final_price"] = int(row["final_price"])
        elif row.get("discount_pct") is not None and not price_change:
            picked["discount_pct"] = float(row["discount_pct"])
        elif row.get("new_price_pct") is not None and price_change:
            picked["change_pct"] = float(row["new_price_pct"]) - 100.0
        else:
            return None
        out.append(picked)
    return out


def _price_spec(
    kind: str, cand: Candidate, today: Any, variations: Variations | None
) -> dict[str, Any] | None:
    rows = _variation_prices(cand, variations, price_change=kind == "price")
    if rows is None:
        return None
    i = cand.inputs
    out: dict[str, Any] = {"kind": kind, "item_id": cand.items[0], "variations": rows}
    if kind == "product_discount":
        if i.get("days"):
            out["start"] = today.isoformat()
            out["end"] = (today + timedelta(days=int(i["days"]) - 1)).isoformat()
        if i.get("per_buyer_limit"):
            out["per_buyer_limit"] = int(i["per_buyer_limit"])
    elif kind == "flash_sale":
        if not i.get("units"):
            return None
        out["units"] = int(i["units"])
        if i.get("slot_hours"):
            out["slot_hours"] = int(i["slot_hours"])
        if i.get("slot_start"):
            out["slot_start"] = i["slot_start"]
    return out


def spec_of_candidate(
    cand: Candidate,
    today: Any,
    stored: Mapping[str, Any] | None = None,
    variations: Variations | None = None,
) -> Any | None:
    """The builder ``VersionSpec`` of a card's change, or ``None`` when it cannot be rebuilt.

    A version that stored its ``spec`` (the builder's "Chọn") is read back as it is. Otherwise the
    spec is rebuilt from the candidate for the kinds whose spec is fully determined by it (voucher,
    combo, title, description, hide, relist); the price levers (giảm giá, đổi giá, Flash Sale) also
    need the product's variations (``variations``: item id -> the builder's variation rows) to turn
    the card's SKU keys back into variation ids. Anything else has no result."""
    from pydantic import TypeAdapter

    from juli_backend.services.shopee_builder import specs as sp

    raw: dict[str, Any] | None
    if stored:
        raw = dict(stored)
    elif cand.kind == "min_spend_voucher":
        raw = _voucher_spec(cand, today)
    elif cand.kind == "bundle_deal":
        raw = _combo_spec(cand)
    elif cand.kind == "listing_combo":
        raw = _listing_combo_spec(cand)
    elif cand.kind in ("product_discount", "price", "flash_sale"):
        raw = _price_spec(cand.kind, cand, today, variations)
    else:
        raw = _item_spec(cand.kind, cand)
    if raw is None:
        return None
    try:
        return TypeAdapter(sp.VersionSpec).validate_python(raw)
    except ValidationError:
        return None


def spec_start(spec: Any) -> date | None:
    """The first day of a version's own dates (``None`` = no dates: it starts with the plan)."""
    start = getattr(spec, "start", None)
    return start if isinstance(start, date) else None


def card_result(
    env: RecoEnv,
    ev: Evaluated,
    *,
    version_row: Mapping[str, Any] | None,
    variations: Variations | None = None,
    today: date | None = None,
) -> CardResult:
    """``integrate.evaluate`` of this card's saved version on the plan's environment. A spec
    rebuilt from the candidate (no stored spec) starts ``today`` (the plan's first day)."""
    from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
    from juli_backend.services.shopee_builder.engine_families import integrate

    stored = None if version_row is None else version_row.get("spec")
    spec = spec_of_candidate(ev.cand, today or env.as_of, stored, variations)
    if spec is None:
        return CardResult(ev.entry.card_id, None, "no_spec", product=ev.product)
    try:
        done, _ = integrate.evaluate(
            BuilderContext(
                env=env,
                variations={k: [dict(r) for r in v] for k, v in (variations or {}).items()},
            ),
            spec,
        )
    except (SpecRefused, ValueError, KeyError, ArithmeticError) as exc:
        return CardResult(
            ev.entry.card_id, None, f"refused:{type(exc).__name__}", product=ev.product
        )
    start = spec_start(spec)
    if done.result is None:
        code = done.refusal.code if done.refusal is not None else "refused"
        return CardResult(ev.entry.card_id, None, code, start=start, product=ev.product)
    out = CardResult(ev.entry.card_id, done.result, start=start, product=ev.product)
    if not out.ok:
        out.reason = "not_estimable"
    return out


def _version_row(e: Evaluated) -> Mapping[str, Any] | None:
    vlist = versions.versions_of(e.card)
    return vlist[e.entry.version - 1] if 0 < e.entry.version <= len(vlist) else None


def _part_target(part: Evaluated) -> str | None:
    cand = part.cand
    if cand.campaign_key:
        return str(cand.campaign_key)
    return str(cand.items[0]) if cand.items else None


def _parts_from_spec(
    env: RecoEnv, e: Evaluated, variations: Variations | None, today: date | None = None
) -> dict[str, CardResult] | None:
    """P99: the parts of a many-target card from the version's OWN builder spec (expanded per
    target as the builder does), so a saved version keeps its dates and days; ``None`` when the
    version stored no spec (the candidates are rebuilt instead)."""
    from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
    from juli_backend.services.shopee_builder.engine_families import integrate

    row = _version_row(e)
    spec = (
        None
        if row is None or not row.get("spec")
        else spec_of_candidate(e.cand, today or env.as_of, row["spec"])
    )
    if spec is None:
        return None
    ctx = BuilderContext(
        env=env, variations={k: [dict(r) for r in v] for k, v in (variations or {}).items()}
    )
    try:
        _, targets = integrate.evaluate(ctx, spec)
    except (SpecRefused, ValueError, KeyError, ArithmeticError):
        return None
    by_target = dict(targets)
    start = spec_start(spec)
    out: dict[str, CardResult] = {}
    for part in e.parts:
        done = by_target.get(_part_target(part) or "")
        if done is None:
            return None
        cid = part.entry.card_id
        if done.result is None:
            code = done.refusal.code if done.refusal is not None else "refused"
            out[cid] = CardResult(cid, None, code, start=start, product=part.product)
            continue
        res = CardResult(cid, done.result, start=start, product=part.product)
        if not res.ok:
            res.reason = "not_estimable"
        out[cid] = res
    return out


def card_results(
    env: RecoEnv,
    evs: Sequence[Evaluated],
    variations: Variations | None = None,
    today: date | None = None,
) -> dict[str, CardResult]:
    """A result per leaf card (a many-target card stands for its single-target parts). Every
    leaf is evaluated from the chosen version's stored builder spec when it has one (P99: the
    version's own dates / days, never the candidate's defaults)."""
    out: dict[str, CardResult] = {}
    for e in evs:
        if e.parts:
            from_spec = _parts_from_spec(env, e, variations, today)
            if from_spec is not None:
                out.update(from_spec)
                continue
        for leaf in e.parts or [e]:
            row = None if e.parts else _version_row(e)
            out[leaf.entry.card_id] = card_result(
                env, leaf, version_row=row, variations=variations, today=today
            )
    return out


def _own_counted(r: CardResult) -> Counted:
    cols = {q: dict(r.delta_own(col) or {}) for q, col in COLUMNS}
    days = 0 if r.result is None else r.result.days
    return Counted(r.card_id, cols, days, r.cost_own())


def combine_counted(counted: Sequence[Counted]) -> dict[str, dict[str, float | None]]:
    """``{quantile: {metric: value}}`` of the counted leaves: the P50s add; P10 / P90 are the sum
    -/+ the root sum of squares of the leaves' half-widths (independent errors, as in
    ``combine_predicted``). A metric one counted leaf does not know (a profit without giá vốn) is
    unknown for the whole -- never a partial sum passed off as the whole. Nothing counted: zeros.
    P25 / P75 are not part of an ``OptionResult`` and stay ``None``."""
    out: dict[str, dict[str, float | None]] = {q: {} for q in QUANTILES}
    for m in RESULT_METRICS:
        mids = [c.cols["p50"].get(m) for c in counted]
        if any(v is None for v in mids):
            for q in QUANTILES:
                out[q][m] = None
            continue
        mid = sum(float(v or 0.0) for v in mids)
        for q in QUANTILES:
            out[q][m] = mid if q == "p50" else None
        for q in ("p10", "p90"):
            edge = [c.cols[q].get(m) for c in counted]
            if any(v is None for v in edge):
                continue
            width = math.sqrt(
                sum(
                    (float(v or 0.0) - float(mm or 0.0)) ** 2
                    for v, mm in zip(edge, mids, strict=True)
                )
            )
            out[q][m] = mid - width if q == "p10" else mid + width
    return out


def combine_results(
    results: Sequence[CardResult], horizon: Horizon | None = None
) -> dict[str, dict[str, float | None]]:
    """The estimable cards' Δ added up: inside ``horizon`` (each card on its own days there) when
    given, else each over its own days. Cards without a result
    are left out (the caller lists them)."""
    if horizon is not None:
        return combine_counted(list(count_in_horizon(results, horizon).values()))
    return combine_counted([_own_counted(r) for r in results if r.ok])


def after_funnel(
    today: Mapping[str, Any], total: Mapping[str, Mapping[str, float | None]]
) -> dict[str, Any]:
    """Today's views / clicks / đơn / GMV plus the plan's P50 Δ, so Đơn = Lượt xem x CTR x CTOR and
    GMV = Đơn x AOV hold for the "after" (None where today's traffic is unknown)."""
    p50 = total["p50"]
    orders = today["orders_30d"] + (p50["dorders"] or 0.0)
    gmv = today["gmv_30d"] + (p50["dgmv"] or 0.0)
    views = clicks = ctr = ctor = None
    tv, tc = today.get("views_30d"), today.get("clicks_30d")
    if (
        tv is not None
        and tc is not None
        and p50["dviews"] is not None
        and p50["dclicks"] is not None
    ):
        views, clicks = tv + p50["dviews"], tc + p50["dclicks"]
        ctr = clicks / views if views > 0 else None
        ctor = orders / clicks if clicks > 0 else None
    profit = today.get("profit_30d")
    d_profit = p50["dprofit"]
    return {
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": gmv / orders if orders else None,
        "views_30d": views,
        "clicks_30d": clicks,
        "ctr": ctr,
        "ctor": ctor,
        "profit_30d": None if profit is None or d_profit is None else profit + d_profit,
    }


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
    #: cards with no ``OptionResult`` (left out of the sums; their exact cost is still counted)
    not_estimable: list[str] = field(default_factory=list)
    result_basis: str | None = None
    #: P99b: the horizon the results are counted in and what each leaf contributes there
    horizon: Horizon | None = None
    counted: dict[str, Counted] = field(default_factory=dict)
    #: leaves whose cost is unknown (no result): the spend line leaves them out and says so
    cost_unknown: list[str] = field(default_factory=list)
    outside_horizon: list[str] = field(default_factory=list)

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

    def certain_or_none(self, key: str) -> float | None:
        """The money layer's certain figure on the legacy path; ``None`` on the option-result
        path (P99b: never a number from another basis beside the results)."""
        return None if self.result_basis else self.certain[key]

    def brief(self) -> dict[str, Any]:
        t = self.total
        return {
            "dprofit": {
                "certain": self.certain_or_none("dprofit"),
                **{q: t[q]["dprofit"] for q in ("p10", "p50", "p90")},
            },
            "dgmv": {"certain": self.certain_or_none("dgmv"), "p50": t["p50"]["dgmv"]},
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


def joint(
    env: RecoEnv,
    evs: Sequence[Evaluated],
    results: Mapping[str, CardResult] | None = None,
    horizon: Horizon | None = None,
) -> Joint:
    """The certain layer of these cards stacked on the same orders (floor, cost against the cap) +
    the numbers: the cards' option results counted in ``horizon`` (default: 30 days from the
    env's anchor) when ``results`` is given, else the legacy money layer's prediction."""
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
    not_estimable: list[str] = []
    counted: dict[str, Counted] = {}
    cost_unknown: list[str] = []
    outside: list[str] = []
    h = horizon or Horizon(env.as_of + timedelta(days=1))
    if results is not None:
        # P99b one cost: a card's cost is its OptionResult's on its own days inside the horizon
        # (the cap reads it too); a card without a result has an unknown cost -- left out of the
        # spend line and listed, never the money layer's figure
        mine = [results[e.entry.card_id] for e in evs if e.entry.card_id in results]
        costs = [r.cost_in(h) for r in mine]
        cost_unknown = [r.card_id for r, c in zip(mine, costs, strict=True) if c is None]
        certain["dchi"] = sum((c for c in costs if c is not None), 0.0)
        counted = count_in_horizon(mine, h)
        predicted = combine_counted(list(counted.values()))
        total = predicted  # an option result's Δ already holds the cost: nothing is added to it
        not_estimable = [r.card_id for r in mine if not r.ok]
        outside = [r.card_id for r in mine if r.result is not None and r.counted(h) is None]
        unknown = [c.card_id for c in counted.values() if c.cols["p50"].get("dprofit") is None]
    else:
        kept, folded = joint_lifts(evs)
        if folded:
            notes.append("lift_shared_per_product:" + ",".join(folded))
        predicted = combine_predicted([e.money["predicted"] for e in kept])
        total = total_of(certain, predicted)
        unknown = [
            e.entry.card_id for e in evs if e.money["predicted"]["p50"].get("dprofit") is None
        ]
    return Joint(
        ids=frozenset(e.entry.card_id for e in evs),
        certain=certain,
        predicted=predicted,
        total=total,
        breaches=breaches,
        five=five,
        joint_cards=_parents([e.entry.card_id for e in line]),
        added_cards=_parents([e.entry.card_id for e in added]),
        profit_unknown=_parents(unknown),
        notes=notes,
        not_estimable=_parents(not_estimable),
        result_basis=None if results is None else RESULT_BASIS,
        horizon=None if results is None else h,
        counted=counted,
        cost_unknown=_parents(cost_unknown),
        outside_horizon=_parents(outside),
    )


class _Memo:
    def __init__(
        self,
        env: RecoEnv,
        evs: Sequence[Evaluated],
        results: Mapping[str, CardResult] | None = None,
        horizon: Horizon | None = None,
    ) -> None:
        self.env = env
        self.results = results
        self.horizon = horizon
        self.by_id = {e.entry.card_id: e for e in [*evs, *flatten(evs)]}
        self.cache: dict[frozenset[str], Joint] = {}

    def of(self, ids: Sequence[str]) -> Joint:
        key = frozenset(ids)
        if key not in self.cache:
            self.cache[key] = joint(
                self.env, [self.by_id[i] for i in sorted(key)], self.results, self.horizon
            )
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
    """The spend line. On the option-result path (P99b) the cards' cost is their cost on their
    own days inside the horizon and the cap compares the horizon's spend (today's spend per day
    × the horizon's days + the cards' cost there) with the cap × those days."""
    days = Decimal(j.horizon.days if j.horizon is not None else config.DAYS_PER_MONTH)
    before = Decimal(str(base["chi_per_day"])) if base is not None else env.shop_chi_per_day()
    delta_total = Decimal(str(j.certain["dchi"]))
    delta = delta_total / days
    after = before + delta
    cap = env.daily_cap
    over = cap is not None and after * days > cap * days
    out: dict[str, Any] = {
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
    if j.horizon is not None:
        out.update(
            horizon=j.horizon.json(),
            horizon_spend_before=float(before * days),
            horizon_spend_delta=float(delta_total),
            horizon_spend_after=float(after * days),
            horizon_cap=None if cap is None else float(cap * days),
            over_by_horizon=float(after * days - cap * days) if over and cap is not None else 0.0,
            cost_unknown_cards=list(j.cost_unknown),
            cost_complete=not j.cost_unknown,
            cost_note=None
            if not j.cost_unknown
            else f"Chưa tính chi phí của {len(j.cost_unknown)} thẻ chưa có kết quả.",
        )
    return out


def _today(env: RecoEnv, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """ "Hôm nay": the plan's frozen base when it has one, else ShopMetrics of the env."""
    if base is not None:
        margin = base["margin_pct"]
        return {
            "as_of": base["as_of"],
            "gmv_30d": base["gmv_30d"],
            "orders_30d": base["orders_30d"],
            "aov": base["aov"],
            "margin_pct": margin,
            "views_30d": base.get("views"),
            "clicks_30d": base.get("clicks"),
            "ctr": base.get("ctr"),
            "ctor": base.get("ctor"),
            "profit_30d": None if margin is None else base["gmv_30d"] * margin / 100,
        }
    m = env.metrics
    gmv, orders = float(env.shop_gmv_30d), env.shop_orders_30d
    return {
        "as_of": env.as_of.isoformat(),
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": None if m.aov is None else float(m.aov),
        "margin_pct": None if m.margin_pct is None else float(m.margin_pct),
        "views_30d": m.views,
        "clicks_30d": m.clicks,
        "ctr": None if m.ctr is None else float(m.ctr),
        "ctor": None if m.ctor is None else float(m.ctor),
        "profit_30d": None if m.profit is None else float(m.profit),
    }


def _after(today: Mapping[str, Any], deltas: Mapping[str, float | None]) -> dict[str, Any]:
    def add(a: Any, d: float | None) -> float | None:
        return None if a is None or d is None else float(a) + d

    orders = add(today["orders_30d"], deltas["orders"])
    gmv = add(today["gmv_30d"], deltas["gmv"])
    return {
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": gmv / orders if orders and gmv is not None else None,
        "margin_pct": add(today["margin_pct"], deltas["bien"]),
    }


def result_deltas(env: RecoEnv, total: Mapping[str, Mapping[str, float | None]]) -> dict[str, Any]:
    """The shop's Δ GMV / đơn / AOV / biên (points) from the plan's P50 (``cards.shop_deltas``
    math) -- an unknown stays unknown: no money-layer profit stands in for a missing one, no
    unknown đơn is read as 0 (P99b)."""
    p50 = total["p50"]
    gmv, orders = float(env.shop_gmv_30d), float(env.shop_orders_30d)
    d_gmv, d_orders, d_profit = p50["dgmv"], p50["dorders"], p50["dprofit"]
    d_aov: float | None = None
    if d_gmv is not None and d_orders is not None and orders > 0 and orders + d_orders > 0:
        d_aov = (gmv + d_gmv) / (orders + d_orders) - gmv / orders
    d_bien: float | None = None
    sp = env.view.profit
    m0, base_paid = sp.margin_rate, float(sp.buyer_paid_covered)
    if d_profit is not None and d_gmv is not None and m0 is not None and base_paid > 0 and gmv:
        scale = base_paid / gmv
        paid_after = base_paid + d_gmv * scale
        if paid_after > 0:
            d_bien = ((float(m0) * base_paid + d_profit) / paid_after - float(m0)) * 100
    return {"gmv": d_gmv, "orders": d_orders, "aov": d_aov, "bien": d_bien}


OUTSIDE_TEXT = "Ngoài 30 ngày tới: không tính vào kế hoạch."
NO_COST_TEXT = "Chưa có kết quả: chưa tính được chi phí."


def _span_json(span: tuple[date, date] | None) -> dict[str, Any] | None:
    if span is None:
        return None
    return {
        "from": span[0].isoformat(),
        "to": span[1].isoformat(),
        "days": (span[1] - span[0]).days + 1,
    }


def _rounded(cols: Mapping[str, Mapping[str, float | None]]) -> dict[str, dict[str, Any]]:
    return {
        q: {
            m: round_orders(cols[q][m]) if m == "dorders" else cols[q][m]
            for m in ("dgmv", "dorders", "dprofit")
        }
        for q in RESULT_QUANTILES
    }


def _card_result_json(
    ev: Evaluated, results: Mapping[str, CardResult], full: Joint
) -> dict[str, Any]:
    """What a card contributes to the plan (P99b): its Δ / cost over its OWN dates (``own``: the
    same figures Tự tạo shows for the version) and inside the plan's horizon (``delta`` /
    ``cost_horizon``: its counted days only). "chưa ước tính được" with the reason and its cost
    when it has no estimate; ``counted`` False with ``outside_horizon`` when none of its days fall
    in the next 30 days."""
    h = full.horizon or Horizon(date.today())
    leaves = [results[p.entry.card_id] for p in (ev.parts or [ev])]
    ok = [r for r in leaves if r.ok]
    have = [r for r in leaves if r.result is not None]
    first = have[0].result if have else None
    lead = have[0] if have else None
    counted_days = max((r.counted_days(h) for r in have), default=0)
    cost_own = (
        float(sum((r.result.cost_total for r in have if r.result), Decimal(0))) if have else None
    )
    cost_horizon = sum((c for r in have if (c := r.cost_in(h)) is not None), 0.0) if have else None
    outside = bool(have) and all(r.counted(h) is None for r in have)
    # P99 / P99b: the card's own base (the funnel "before" its Δ was computed on), its own dates,
    # its days inside the horizon and its cost on each
    common: dict[str, Any] = {
        "horizon": h.json(),
        "own_dates": None if lead is None else _span_json(lead.own_span(h)),
        "own_days": None if first is None else first.days,
        "dated": None if lead is None else lead.start is not None,
        "counted_dates": None if lead is None else _span_json(lead.counted(h)),
        "counted_days": counted_days if have else None,
        "outside_horizon": outside,
        "cost_total": cost_own,
        "cost_horizon": cost_horizon,
        # deprecated alias (the horizon is 30 days): the cost inside it
        "cost_month": cost_horizon,
        "cost_known": bool(have) and len(have) == len(leaves),
        "cost_note": None if have and len(have) == len(leaves) else NO_COST_TEXT,
        "break_even_orders": None
        if len(have) != 1 or first is None or first.break_even_orders is None
        else float(math.ceil(float(first.break_even_orders) - 1e-6)),
        "days": None if first is None else first.days,
        "result_horizon": None if first is None else first.horizon,
        "before": _sum_before([r.before_30d() for r in have]) if have else None,
        "notes": [] if first is None else list(first.notes),
    }
    if not ok:
        return {
            "estimable": False,
            "counted": False,
            "message": NOT_ESTIMABLE_TEXT,
            "reason": next((r.reason for r in leaves if r.reason), "not_estimable"),
            "own": None,
            "delta": None,
            "after": None,
            **common,
        }
    own = combine_counted([_own_counted(r) for r in ok])
    mine = [full.counted[r.card_id] for r in ok if r.card_id in full.counted]
    inside = combine_counted(mine)
    partial = len(ok) < len(leaves)
    return {
        "estimable": True,
        "counted": not outside,
        "partial": partial,
        "partial_note": None
        if not partial
        else f"{len(leaves) - len(ok)}/{len(leaves)} mục chưa ước tính được, chưa cộng vào.",
        "message": OUTSIDE_TEXT if outside else None,
        "reason": "outside_horizon" if outside else None,
        "basis": max(
            (r.result.basis for r in ok if r.result is not None),
            key=("measured", "product_history", "shop", "prior", "not_estimable").index,
        ),
        "own": {
            "dates": common["own_dates"],
            "days": common["own_days"],
            "delta": _rounded(own),
            "cost_total": cost_own,
        },
        "delta": _rounded(inside),
        "after": _after_of(common["before"], inside["p50"]),
        **common,
    }


def _sum_before(rows: Sequence[dict[str, float | None] | None]) -> dict[str, float | None] | None:
    """The 30-day bases of a card's leaves added up (a many-target card's products)."""
    known = [r for r in rows if r is not None]
    if not known:
        return None
    out: dict[str, float | None] = {}
    for k in ("gmv_30d", "orders_30d", "profit_30d", "views_30d", "clicks_30d"):
        vals = [r[k] for r in known]
        out[k] = None if any(v is None for v in vals) else sum(float(v or 0.0) for v in vals)
    o, g = out["orders_30d"], out["gmv_30d"]
    out["aov"] = None if not o or g is None else g / o
    return out


def _after_of(
    before: Mapping[str, float | None] | None, p50: Mapping[str, float | None]
) -> dict[str, float | None] | None:
    """``before`` + the P50 Δ (both per 30 days, same scope): Đơn × AOV = GMV holds."""
    if before is None:
        return None

    def add(a: float | None, d: float | None) -> float | None:
        return None if a is None or d is None else a + d

    orders = add(before["orders_30d"], p50.get("dorders"))
    gmv = add(before["gmv_30d"], p50.get("dgmv"))
    return {
        "gmv_30d": gmv,
        "orders_30d": orders,
        "profit_30d": add(before["profit_30d"], p50.get("dprofit")),
        "views_30d": add(before["views_30d"], p50.get("dviews")),
        "clicks_30d": add(before["clicks_30d"], p50.get("dclicks")),
        "aov": None if not orders or gmv is None else gmv / orders,
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
    today, after = _product_today_after(env, pid, evs, memo.results, memo.horizon)
    return {
        "product_id": pid,
        "name": env.name(pid),
        "cards": _parents([e.entry.card_id for e in evs]),
        "codes": list(dict.fromkeys(e.entry.code for e in evs)),
        "today": today,
        "after": after,
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
            base_margin_pct=None if today is None else today["margin_pct"],
        ),
    }


def _product_today_after(
    env: RecoEnv,
    pid: str,
    evs: Sequence[Evaluated],
    results: Mapping[str, CardResult] | None,
    horizon: Horizon | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """P99 one base: the product's "hôm nay" is the same stored funnel its cards' results stand on
    (``integrate.base_for`` of the product, the plan's window) with Luồng sản phẩm's margin, and
    its "sau" is that base plus its cards' P50 Δ -- a product's Δ is never put on the shop's
    figures. ``(None, None)`` on the legacy path (no results)."""
    if results is None:
        return None, None
    from juli_backend.services.shopee_builder.engine_families import integrate

    today = integrate.scope_today(env, integrate.base_for(env, [pid]))
    mine = [results[e.entry.card_id] for e in evs if e.entry.card_id in results]
    comb = combine_results(mine, horizon)
    after = _after_of(today, comb["p50"])
    return today, None if after is None else {**after, "label": "Dự kiến (P50)"}


def aggregate(
    env: RecoEnv,
    entries: Sequence[Entry],
    *,
    now: datetime,
    base: Mapping[str, Any] | None = None,
    variations: Variations | None = None,
    today: date | None = None,
    default_start: date | None = None,
) -> tuple[dict[str, Any], list[Evaluated]]:
    """The plan's aggregate payload and the evaluated cards (chosen version on this env).

    P99b: the numbers are the expected outcome over the next 30 days starting ``today``
    (default ``now``'s date): baseline 30 days + each card's Δ on its own days inside them.
    ``default_start``: where a change without dates of its own starts (a group's first day; else
    today)."""
    horizon = Horizon(today or now.date())
    evs: list[Evaluated] = []
    unavailable: list[str] = []
    for entry in entries:
        ev = evaluate_entry(env, entry, now=now)
        if ev is None:
            unavailable.append(entry.card_id)
        else:
            evs.append(ev)
    today_block = _today(env, base)
    if not evs:
        return {
            "as_of": env.as_of.isoformat(),
            "horizon": horizon.json(),
            "n_cards": 0,
            "empty": True,
            "empty_note": "Kế hoạch chưa có thẻ nào.",
            "today": today_block,
            "after": None,
            "deltas_p50": None,
            "cost": None,
            "cards": [],
            "unavailable_cards": unavailable,
            "range_method": RANGE_METHOD,
            "result_basis": RESULT_BASIS,
        }, []
    results = card_results(env, evs, variations, default_start or horizon.start)
    if default_start is not None:
        for r in results.values():
            if r.start is None:
                r.start = default_start
    memo = _Memo(env, evs, results, horizon)
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
    deltas = result_deltas(env, full.total)
    cards: list[dict[str, Any]] = []
    for e in evs:
        rest = memo.of([i for i in ids if i != e.entry.card_id]) if len(ids) > 1 else None
        alone = memo.of([e.entry.card_id])
        wb, ab = (rest.brief() if rest else None), alone.brief()
        pb = full.brief()
        contribution = {
            "dprofit_certain": _sub(
                pb["dprofit"]["certain"], wb["dprofit"]["certain"] if wb else 0.0
            ),
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
                "result": _card_result_json(e, results, full),
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
        "horizon": horizon.json(),
        "live": True,
        "today": today_block,
        "after": {
            **_after(today_block, deltas),
            **after_funnel(today_block, full.total),
            "label": "Dự kiến (P50)",
        },
        "deltas_p50": deltas,
        "five_numbers": full.five,
        "dprofit_month": {
            "certain": full.certain_or_none("dprofit"),
            "predicted": {q: full.predicted[q]["dprofit"] for q in ("p10", "p50", "p90")},
            "total": {q: full.total[q]["dprofit"] for q in ("p10", "p50", "p90")},
        },
        "dgmv_month": {
            "certain": full.certain_or_none("dgmv"),
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
                "dprofit_certain": full.certain_or_none("dprofit"),
                "dgmv_p50": full.total["p50"]["dgmv"],
                "margin_pct_before": today_block["margin_pct"],
                "margin_pct_after": _after(today_block, deltas)["margin_pct"],
            },
            "note": "Từng bước chồng lên các bước trước; tổng shop là kết quả chung của kế hoạch.",
        },
        "joint_cards": full.joint_cards,
        "added_cards": full.added_cards,
        "profit_unknown_cards": full.profit_unknown,
        "not_estimable_cards": full.not_estimable,
        "outside_horizon_cards": full.outside_horizon,
        "cost_unknown_cards": full.cost_unknown,
        "totals_partial": bool(full.not_estimable or unavailable),
        "totals_note": _totals_note(full, unavailable),
        "result_basis": RESULT_BASIS,
        "unavailable_cards": unavailable,
        "notes": full.notes,
        "range_method": RANGE_METHOD,
        "range_note": "Khoảng dự kiến gộp: P50 cộng lại, độ rộng gộp theo căn bậc hai tổng "
        "bình phương.",
    }
    return out, evs


def _totals_note(j: Joint, unavailable: Sequence[str]) -> str | None:
    """Says which cards the totals leave out (never a silent partial sum)."""
    parts = []
    if j.not_estimable:
        parts.append(f"{len(j.not_estimable)} thẻ chưa ước tính được")
    if unavailable:
        parts.append(f"{len(unavailable)} thẻ không tính lại được")
    if not parts:
        return None
    return "Tổng chưa gồm " + " và ".join(parts) + "."


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


__all__ = [
    "RESULT_BASIS",
    "CardResult",
    "Entry",
    "Evaluated",
    "Joint",
    "after_funnel",
    "aggregate",
    "card_result",
    "card_results",
    "combine_predicted",
    "combine_results",
    "evaluate_entry",
    "flatten",
    "joint",
    "joint_lifts",
    "total_of",
]
