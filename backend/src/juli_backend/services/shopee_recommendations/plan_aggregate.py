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
its exact cost still counts against the cap (the certain layer); the payload counts them
(``not_estimable_cards``, ``totals_note``). When NO card is estimable the totals are ``None`` and
``totals_estimable`` is False (P100-C, B.10) -- never the empty sum's 0. An unknown profit makes the
plan's profit unknown. The "after" funnel is today's views / clicks / đơn plus the cards' deltas, so
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

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import counts_in_sales
from juli_backend.services.shopee_recommendations import (
    config,
    current,
    forecast,
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

log = logging.getLogger(__name__)

RESULT_BASIS = "option_result"
NOT_ESTIMABLE_TEXT = "chưa ước tính được"
HORIZON_DAYS = 30
RESULT_QUANTILES = ("p10", "p50", "p90")
RESULT_METRICS = ("dgmv", "dorders", "dprofit", "dviews", "dclicks", "drevoffer")

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
    #: A3.1: the last day this card may count (its group's last day); ``None`` = no clip
    end: date | None = None
    #: A2.2: the ads campaign whose budget the card spends (a running campaign's key; a new
    #: campaign is its own); ``None`` = not an ads card
    campaign: str | None = None
    #: a product is in one campaign at a time: the code of the card that won the product
    #: instead of this one (this card then adds nothing to the plan's Δ and cost)
    replaced_by: str | None = None

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
        last = first + timedelta(days=r.days - 1)
        if self.end is not None:  # A3.1: only the card's group days (never into the next group)
            last = min(last, self.end)
        return first, last

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
        if per_day is not None and self.replaced_by:
            return 0.0
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
    # the offers that lower doanh thu thực (voucher, combo, add-on price): the plan margin's
    # denominator (Biên lợi nhuận after = profit ÷ doanh thu thực after)
    "drevoffer": "revenue_offer_cost",
}
COLUMNS = (("p10", "low"), ("p50", "likely"), ("p90", "high"))


# ------------------------------------------------------------------ ads campaigns (A2.2)


@dataclass(frozen=True)
class AdsData:
    """What the platform measured for the shop's ads campaigns (read once from the env's stored
    ads reports; this module does no I/O)."""

    #: campaign key -> product id -> (ads spend, ads orders) of the report's per-product rows
    products: Mapping[str, Mapping[str, tuple[float, float]]] = field(default_factory=dict)
    #: campaign key -> day -> the platform's measured spend that day
    daily: Mapping[str, Mapping[date, float]] = field(default_factory=dict)
    #: campaign key -> product id -> (last day the report row spans, that row's spend), rows with
    #: spend only: where the product spent LAST
    latest: Mapping[str, Mapping[str, tuple[date, float]]] = field(default_factory=dict)
    #: campaign key -> (ads GMV, ads spend) of its per-product rows: the measured ROAS
    roas_parts: Mapping[str, tuple[float, float]] = field(default_factory=dict)

    def roas(self, campaign: str) -> float | None:
        gmv, spend = self.roas_parts.get(campaign, (0.0, 0.0))
        return None if spend <= 0 else gmv / spend

    def campaign_of_product(self, product: str | None) -> str | None:
        """The campaign the product is in NOW: where its spend is latest (a product is in one
        campaign at a time, so spend in two campaigns means it moved); ties go to the larger
        spend of that row, then the smaller key. ``None`` when the platform shows no spend."""
        if product is None:
            return None
        found = []
        for key, rows in self.products.items():
            total = rows.get(product, (0.0, 0.0))[0]
            if total <= 0:
                continue
            last, spend = self.latest.get(key, {}).get(product, (date.min, total))
            found.append((last, spend, key))
        if not found:
            return None
        return min(found, key=lambda t: (-t[0].toordinal(), -t[1], t[2]))[2]

    def spend(self, campaign: str, product: str | None) -> float:
        rows = self.products.get(campaign, {})
        if product is None:
            return sum(s for s, _ in rows.values())
        return rows.get(product, (0.0, 0.0))[0]

    def cost_per_order(self, campaign: str, product: str | None = None) -> float | None:
        """Platform ads spend ÷ platform ads orders (the product's, or the campaign's when
        ``product`` is ``None``); ``None`` when there is no order."""
        rows = self.products.get(campaign, {})
        picked = list(rows.values()) if product is None else [rows.get(product, (0.0, 0.0))]
        orders = sum(o for _, o in picked)
        return None if orders <= 0 else sum(sp for sp, _ in picked) / orders


def ads_data_of(env: Any) -> AdsData:
    """The env's stored per-product ads rows (``view.data.ads_reports``) and the campaigns' daily
    spend (``env.campaigns``: the window's last days up to ``as_of``, oldest first)."""
    rows = getattr(getattr(getattr(env, "view", None), "data", None), "ads_reports", None)
    products: dict[str, dict[str, tuple[float, float]]] = {}
    latest: dict[str, dict[str, tuple[date, float]]] = {}
    parts: dict[str, tuple[float, float]] = {}
    for r in getattr(rows, "campaign_rows", None) or []:
        if not r.item_id:  # a campaign's own total row
            continue
        g, sp0 = parts.get(r.key, (0.0, 0.0))
        parts[r.key] = (g + float(getattr(r, "gmv", 0) or 0), sp0 + float(r.spend))
        end = getattr(r, "period", (None, None))[1]
        if end is not None and float(r.spend) > 0:
            seen = latest.setdefault(r.key, {}).get(r.item_id)
            if seen is None or (end, float(r.spend)) > seen:
                latest[r.key][r.item_id] = (end, float(r.spend))
        sp, od = products.setdefault(r.key, {}).get(r.item_id, (0.0, 0.0))
        products[r.key][r.item_id] = (sp + float(r.spend), od + float(r.orders))
    as_of = getattr(env, "as_of", None)
    daily: dict[str, dict[date, float]] = {}
    for key, setting in (getattr(env, "campaigns", None) or {}).items():
        days = tuple(getattr(setting, "days", ()) or ())
        if as_of is None or not days:
            continue
        daily[key] = {
            as_of - timedelta(days=len(days) - 1 - i): float(spend)
            for i, (spend, _budget) in enumerate(days)
        }
    return AdsData(products, daily, latest, parts)


@dataclass(frozen=True)
class AdsShares:
    """A2.2: each ads card's share of its campaign's cost inside the horizon. ``cost`` is by card
    id; the shares of one campaign add up to the campaign's cost exactly."""

    cost: Mapping[str, float] = field(default_factory=dict)
    campaigns: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def ads_shares(results: Sequence[CardResult], h: Horizon, data: AdsData | None = None) -> AdsShares:
    """A campaign's budget is counted ONCE in the plan however many cards (products) of that
    campaign it holds. The campaign's cost inside the horizon is its lowest per-day cost × the
    days any of its cards counts; each card gets the share of its product's platform ads spend
    (equal split when the platform spent nothing on the plan's products). Forward days stay at the
    full budget: no forward-spend estimate."""
    data = data or AdsData()
    by_campaign: dict[str, list[CardResult]] = {}
    for r in results:
        if r.campaign and not r.replaced_by and r.result is not None and r.cost_in(h) is not None:
            by_campaign.setdefault(r.campaign, []).append(r)
    cost: dict[str, float] = {}
    blocks: dict[str, dict[str, Any]] = {}
    for campaign, cards in sorted(by_campaign.items()):
        cards = sorted(cards, key=lambda r: r.card_id)
        days: set[date] = set()
        for r in cards:
            span = r.counted(h)
            if span is not None:
                days.update(
                    span[0] + timedelta(days=i) for i in range((span[1] - span[0]).days + 1)
                )
        # owner: cards on one campaign with different budgets count the LOWER one
        per_day = min((r.cost_per_day() or 0.0) for r in cards)
        total = per_day * len(days)
        spends = [data.spend(campaign, r.product) for r in cards]
        # one product with several cards splits its spend between them
        same = {p: sum(1 for r in cards if r.product == p) for p in {r.product for r in cards}}
        weights = [sp / same[r.product] for sp, r in zip(spends, cards, strict=True)]
        if sum(weights) <= 0:
            weights = [1.0] * len(cards)
        whole = sum(weights)
        given = 0.0
        shares: list[float] = []
        for i, w in enumerate(weights):
            share = total - given if i == len(cards) - 1 else total * w / whole
            shares.append(share)
            given += share
        for r, share in zip(cards, shares, strict=True):
            cost[r.card_id] = share
        blocks[campaign] = {
            "campaign": campaign,
            "cost_horizon": total,
            "days": len(days),
            #: the counted days and the per-day cost, so a plan's groups count the campaign once
            #: (``merge_groups``: the lowest per-day cost x the union of the days)
            "dates": sorted(d.isoformat() for d in days),
            "cost_per_day": per_day,
            "spend": data.spend(campaign, None),
            "cost_per_order": data.cost_per_order(campaign),
            "cards": [
                {
                    "card_id": r.card_id,
                    "product_id": r.product,
                    "share": 0.0 if total <= 0 else share / total,
                    "cost_horizon": share,
                    "cost_per_order": data.cost_per_order(campaign, r.product),
                }
                for r, share in zip(cards, shares, strict=True)
            ],
        }
    return AdsShares(cost, blocks)


def campaign_span_cost(
    budget_per_day: float,
    first: date,
    last: date,
    today: date,
    measured: Mapping[date, float] | None = None,
) -> dict[str, float]:
    """A2.2: a campaign's cost over its span. A day already run (before ``today``) costs what the
    platform measured that day (the budget when nothing was measured); the days still to come
    cost the full budget."""
    measured = measured or {}
    elapsed = forward = 0.0
    n_elapsed = n_forward = 0
    for i in range((last - first).days + 1):
        d = first + timedelta(days=i)
        if d < today:
            elapsed += measured.get(d, budget_per_day)
            n_elapsed += 1
        else:
            forward += budget_per_day
            n_forward += 1
    return {
        "elapsed_days": n_elapsed,
        "elapsed_spend": elapsed,
        "forward_days": n_forward,
        "forward_cost": forward,
        "total": elapsed + forward,
    }


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


def count_in_horizon(
    results: Sequence[CardResult], h: Horizon, ads: AdsShares | None = None
) -> dict[str, Counted]:
    """Each estimable leaf's Δ inside the horizon (its counted days only).

    A2.2: an ads card's cost is its campaign's share (``ads``); an estimable card's Δ already
    holds its own full cost, so the difference to its share is put back. A card that cannot be
    estimated contributes nothing here (its certain cost stays in the spend line)."""
    out: dict[str, Counted] = {}
    for r in results:
        if not r.ok or r.replaced_by:
            continue
        own_cost = r.cost_in(h)
        cost = own_cost
        if ads is not None and r.card_id in ads.cost:
            cost = ads.cost[r.card_id]
        cols: dict[str, dict[str, float | None]] = {
            q: dict(r.delta(col, h) or {}) for q, col in COLUMNS
        }
        if own_cost is not None and cost is not None and cost != own_cost:
            for q in cols:
                if cols[q].get("dprofit") is not None:
                    cols[q]["dprofit"] = float(cols[q]["dprofit"] or 0.0) + (own_cost - cost)
        out[r.card_id] = Counted(r.card_id, cols, r.counted_days(h), cost)
    return out


def round_orders(x: float | None) -> float | None:
    """Δ Đơn to the precision the cards show (``engine.wire.round_count``): whole orders from 1
    up, kept (2 decimals) under one order so the screen can say "< 1"."""
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
#: item id -> {keyword: volume weight}: what a title / first-line lift is measured against
KeywordWeights = Mapping[str, Mapping[str, float]]


def _weights(w: KeywordWeights | None) -> dict[str, dict[str, float]]:
    return {k: dict(v) for k, v in (w or {}).items()}


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
    keyword_weights: KeywordWeights | None = None,
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
                keyword_weights=_weights(keyword_weights),
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


def _campaign_of(e: Evaluated, data: AdsData | None = None) -> str | None:
    """A2.2: the ads campaign a card spends the budget of; ``None`` only for a card that is not
    an ads card. A running campaign's key; a new campaign (no key yet) is its own; an ads card
    with no key resolves to the platform campaign its product spends in (``data``), else it
    stands alone as ``card:<id>`` so it is always tracked and never merged with another."""
    cid = e.entry.card_id
    if e.cand.kind == "ads_new_campaign":
        return f"new:{cid}"
    if e.cand.kind not in ADS_KINDS:
        return None
    if e.cand.campaign_key:
        return str(e.cand.campaign_key)
    return (data or AdsData()).campaign_of_product(e.product) or f"card:{cid}"


def assign_campaigns(
    results: Mapping[str, CardResult], evs: Sequence[Evaluated], data: AdsData
) -> None:
    """Give every ads leaf its campaign (``_campaign_of``); one count line says how many stood
    alone because no campaign could be resolved (a count only)."""
    unresolved = 0
    ads_leaves: list[tuple[Evaluated, CardResult]] = []
    for e in flatten(evs):
        leaf = results.get(e.entry.card_id)
        if leaf is not None and leaf.campaign is None:
            leaf.campaign = _campaign_of(e, data)
            unresolved += bool(leaf.campaign and leaf.campaign.startswith("card:"))
        if leaf is not None and leaf.campaign and leaf.result is not None:
            ads_leaves.append((e, leaf))
    if unresolved:
        log.info("ads_card_without_campaign count=%d", unresolved)
    resolve_product_conflicts(ads_leaves, data)


def _roas_of(e: Evaluated, leaf: CardResult, data: AdsData) -> float:
    """The card's campaign ROAS: measured over the before window for a running campaign, the
    ROAS target (Tùy chỉnh) for a new one; unknown counts as 0."""
    row = _version_row(e)
    spec = (row or {}).get("spec") or {}
    target = spec.get("roas_target") if isinstance(spec, Mapping) else None
    if e.cand.kind != "ads_new_campaign" and leaf.campaign:
        measured = data.roas(leaf.campaign)
        if measured is not None:
            return measured
    return float(target) if target else 0.0


def resolve_product_conflicts(pairs: Sequence[tuple[Evaluated, CardResult]], data: AdsData) -> None:
    """A product is in ONE campaign at a time. When cards of a plan (or group) put the same
    product in different campaigns only the better one counts: higher ROAS, then the lower
    per-day spend, then the smaller card id. The others carry ``replaced_by`` = the winner's
    code and add nothing to the plan's Δ and cost."""
    by_product: dict[str, list[tuple[Evaluated, CardResult]]] = {}
    for e, leaf in pairs:
        if e.product:
            by_product.setdefault(e.product, []).append((e, leaf))
    for group in by_product.values():
        if len({leaf.campaign for _, leaf in group}) < 2:
            continue
        ranked = sorted(
            group,
            key=lambda t: (
                -_roas_of(t[0], t[1], data),
                t[1].cost_per_day() or 0.0,
                t[0].entry.card_id,
            ),
        )
        winner = ranked[0]
        for e, leaf in ranked[1:]:
            if leaf.campaign != winner[1].campaign:
                leaf.replaced_by = str(winner[0].entry.code or winner[0].entry.card_id)


#: decision #47: programmes that cannot run on the same SKU at the same time -- Mua Kèm Deal Sốc,
#: Flash Sale Của Shop, Chương Trình Của Shop, Combo Khuyến Mãi. Two of them on one product with
#: overlapping dates: only the better card (higher P50 Δ lợi nhuận đóng góp) counts.
EXCLUSIVE_KINDS = frozenset(
    {"add_on", "flash_sale", "product_discount", "program_registration", "bundle_deal"}
)
#: the reason code of a card the exclusivity check leaves out of the plan's total
EXCLUSIVE_REASON = "exclusive_programme"


def _p50_profit(r: CardResult) -> float:
    own = r.delta_own("likely") or {}
    v = own.get("dprofit")
    return float("-inf") if v is None else float(v)


def resolve_exclusive(
    results: Mapping[str, CardResult], evs: Sequence[Evaluated], h: Horizon
) -> None:
    """Decision #47: a small check on the SEPARATE card results (no joint evaluation). Of the
    cards whose programmes cannot share a SKU (``EXCLUSIVE_KINDS``), on one product and with
    overlapping own dates, only the one with the higher P50 Δ profit counts (ties: the smaller
    card id); the other carries ``replaced_by`` (the winner's code) and ``reason``
    ``EXCLUSIVE_REASON`` and adds nothing to the plan's Δ or cost. Cards whose dates do not
    overlap both count."""
    cands: list[tuple[Evaluated, CardResult, tuple[date, date]]] = []
    for e in flatten(evs):
        leaf = results.get(e.entry.card_id)
        if leaf is None or not leaf.ok or leaf.replaced_by or e.cand.kind not in EXCLUSIVE_KINDS:
            continue
        span = leaf.own_span(h)
        if span is not None and e.product:
            cands.append((e, leaf, span))
    ranked = sorted(cands, key=lambda t: (-_p50_profit(t[1]), t[0].entry.card_id))
    kept: list[tuple[Evaluated, CardResult, tuple[date, date]]] = []
    for e, leaf, span in ranked:
        winner = next(
            (
                w
                for w in kept
                if w[0].product == e.product and w[2][0] <= span[1] and span[0] <= w[2][1]
            ),
            None,
        )
        if winner is None:
            kept.append((e, leaf, span))
            continue
        leaf.replaced_by = str(winner[0].entry.code or winner[0].entry.card_id)
        leaf.reason = EXCLUSIVE_REASON


def _version_row(e: Evaluated) -> Mapping[str, Any] | None:
    vlist = versions.versions_of(e.card)
    return vlist[e.entry.version - 1] if 0 < e.entry.version <= len(vlist) else None


def _part_target(part: Evaluated) -> str | None:
    cand = part.cand
    if cand.campaign_key:
        return str(cand.campaign_key)
    return str(cand.items[0]) if cand.items else None


def _parts_from_spec(
    env: RecoEnv,
    e: Evaluated,
    variations: Variations | None,
    today: date | None = None,
    keyword_weights: KeywordWeights | None = None,
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
        env=env,
        variations={k: [dict(r) for r in v] for k, v in (variations or {}).items()},
        keyword_weights=_weights(keyword_weights),
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


def _from_block(e: Evaluated, block: Mapping[str, Any]) -> dict[str, CardResult] | None:
    """The card's results from its stored ``result`` (one card, one number: the figure the card
    shows); ``None`` when the block cannot stand for every leaf (it is then computed)."""
    from juli_backend.services.shopee_recommendations.result_store import option_of

    # a spec rebuilt from the candidate has no dates of its own: it starts with the plan
    dated = block.get("start") and block.get("spec_source") != "rebuilt"
    start = date.fromisoformat(block["start"]) if dated else None

    def one(cid: str, core: Mapping[str, Any] | None, product: str | None) -> CardResult:
        if core is None:
            return CardResult(cid, None, block.get("reason") or "refused", start, product)
        res = CardResult(cid, option_of(core), start=start, product=product)
        if not res.ok:
            res.reason = "not_estimable"
        return res

    if e.parts:
        targets = block.get("targets") or {}
        out: dict[str, CardResult] = {}
        for part in e.parts:
            t = _part_target(part) or ""
            if t not in targets:
                return None
            out[part.entry.card_id] = one(part.entry.card_id, targets[t], part.product)
        return out
    return {e.entry.card_id: one(e.entry.card_id, block.get("core"), e.product)}


def card_results(
    env: RecoEnv,
    evs: Sequence[Evaluated],
    variations: Variations | None = None,
    today: date | None = None,
    keyword_weights: KeywordWeights | None = None,
    stored: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, CardResult]:
    """A result per leaf card (a many-target card stands for its single-target parts). A card
    whose chosen version holds a fresh stored result (``stored``: card id -> block) reads it --
    the card, the list and the plan show one number. Every other leaf is evaluated from the
    chosen version's stored builder spec when it has one (P99: the version's own dates / days,
    never the candidate's defaults)."""
    out: dict[str, CardResult] = {}
    for e in evs:
        block = (stored or {}).get(e.entry.card_id)
        if block is not None:
            got = _from_block(e, block)
            if got is not None:
                out.update(got)
                continue
        if e.parts:
            from_spec = _parts_from_spec(env, e, variations, today, keyword_weights)
            if from_spec is not None:
                out.update(from_spec)
                continue
        for leaf in e.parts or [e]:
            row = None if e.parts else _version_row(e)
            out[leaf.entry.card_id] = card_result(
                env,
                leaf,
                version_row=row,
                variations=variations,
                today=today,
                keyword_weights=keyword_weights,
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
    results: Sequence[CardResult],
    horizon: Horizon | None = None,
    ads: AdsData | None = None,
) -> dict[str, dict[str, float | None]]:
    """The estimable cards' Δ added up: inside ``horizon`` (each card on its own days there) when
    given, else each over its own days. Cards without a result
    are left out (the caller lists them)."""
    if horizon is not None:
        shares = ads_shares(results, horizon, ads)
        return combine_counted(list(count_in_horizon(results, horizon, shares).values()))
    return combine_counted([_own_counted(r) for r in results if r.ok])


def after_funnel(
    today: Mapping[str, Any], total: Mapping[str, Mapping[str, float | None]]
) -> dict[str, Any]:
    """Today's views / clicks / đơn / GMV plus the plan's P50 Δ, so Đơn = Lượt xem x CTR x CTOR and
    GMV = Đơn x AOV hold for the "after" (None where today's traffic is unknown)."""
    p50 = total["p50"]
    if p50["dorders"] is None or p50["dgmv"] is None:
        # P100-C: an unknown Δ (no card estimable) leaves the "after" unknown, not today's figure
        return {
            k: None
            for k in (
                "gmv_30d", "orders_30d", "aov", "views_30d", "clicks_30d", "ctr", "ctor",
                "profit_30d",
            )
        }  # fmt: skip
    orders = today["orders_30d"] + p50["dorders"]
    gmv = today["gmv_30d"] + p50["dgmv"]
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
    #: P100-C (B.10): every card is "chưa ước tính được" -> the totals are None, not 0
    none_estimable: bool = False
    #: leaves whose cost is unknown (no result): the spend line leaves them out and says so
    cost_unknown: list[str] = field(default_factory=list)
    outside_horizon: list[str] = field(default_factory=list)
    #: A2.2: campaign key -> its cost once in the horizon, the cards' shares, cost per order
    ads_campaigns: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    #: card id -> its share of its campaign's cost inside the horizon
    ads_cost: dict[str, float] = field(default_factory=dict)
    #: the leaf results this joint counted (P7's channel attribution)
    leaves: list[CardResult] = field(default_factory=list)

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
    none_estimable = False
    counted: dict[str, Counted] = {}
    ads_blocks: dict[str, Mapping[str, Any]] = {}
    cost_unknown: list[str] = []
    outside: list[str] = []
    ads_cost: dict[str, float] = {}
    h = horizon or Horizon(env.as_of + timedelta(days=1))
    if results is not None:
        # P99b one cost: a card's cost is its OptionResult's on its own days inside the horizon
        # (the cap reads it too); a card without a result has an unknown cost -- left out of the
        # spend line and listed, never the money layer's figure
        mine = [results[e.entry.card_id] for e in evs if e.entry.card_id in results]
        # A2.2: an ads campaign's budget is counted once; its cards carry a share of it
        ads = ads_shares(mine, h, ads_data_of(env))
        costs = [ads.cost.get(r.card_id, r.cost_in(h)) for r in mine]
        cost_unknown = [r.card_id for r, c in zip(mine, costs, strict=True) if c is None]
        certain["dchi"] = sum((c for c in costs if c is not None), 0.0)
        counted = count_in_horizon(mine, h, ads)
        ads_blocks = dict(ads.campaigns)
        ads_cost = dict(ads.cost)
        predicted = combine_counted(list(counted.values()))
        total = predicted  # an option result's Δ already holds the cost: nothing is added to it
        not_estimable = [r.card_id for r in mine if not r.ok]
        outside = [r.card_id for r in mine if r.result is not None and r.counted(h) is None]
        none_estimable = bool(mine) and not any(r.ok for r in mine)
        if none_estimable:
            # P100-C (B.10): every card is "chưa ước tính được" -- the plan's Δ is unknown, never
            # the empty sum's 0 (the cards' costs still count, ``certain["dchi"]``)
            predicted = {q: dict.fromkeys(RESULT_METRICS) for q in QUANTILES}
            total = predicted
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
        none_estimable=none_estimable,
        ads_campaigns=ads_blocks,
        ads_cost=ads_cost,
        leaves=[] if results is None else [results[i] for i in sorted(counted)],
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
            ads_campaigns=list(j.ads_campaigns.values()),
            cost_unknown_cards=list(j.cost_unknown),
            cost_complete=not j.cost_unknown,
            cost_note=None
            if not j.cost_unknown
            else f"Chưa tính chi phí của {len(j.cost_unknown)} thẻ chưa có kết quả.",
        )
    return out


def _today(env: RecoEnv, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """ "Hôm nay": the plan's frozen base when it has one, else ShopMetrics of the env. The shop
    profit and margin are the one known-cost figure (P100 B.5, ``shared.shop_profit_of``): the
    same number Tổng quan and Sản phẩm show."""
    if base is not None:
        margin = base["margin_pct"]
        profit = base.get("profit_30d")
        if profit is None and "shop_profit" not in base and margin is not None:
            profit = base["gmv_30d"] * margin / 100  # a base frozen before P100
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
            "profit_30d": profit,
            "shop_profit": base.get("shop_profit"),
        }
    m = env.metrics
    fig = shop_profit_of(env.view).json()
    gmv, orders = float(env.shop_gmv_30d), env.shop_orders_30d
    now = current.current_30d(env)  # F1: the same hiện tại as the builder's and the cards'
    coverage = None if now is None else forecast.coverage(now.days, now.window_days)
    views = m.views if now is None else funnel.known_total(now, "views")
    clicks = m.clicks if now is None else funnel.known_total(now, "clicks")
    return {
        "as_of": env.as_of.isoformat(),
        "coverage": coverage,
        "gmv_30d": gmv,
        "orders_30d": orders,
        "aov": gmv / orders if orders else None,
        "margin_pct": fig["margin_pct"],
        "views_30d": None if views is None else float(views),
        "clicks_30d": None if clicks is None else float(clicks),
        "ctr": float(clicks / views) if views and clicks is not None else None,
        "ctor": orders / float(clicks) if clicks else None,
        "profit_30d": fig["profit"],
        "shop_profit": fig,
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
    d_offer = p50.get("drevoffer") or 0.0
    d_aov: float | None = None
    if d_gmv is not None and d_orders is not None and orders > 0 and orders + d_orders > 0:
        d_aov = (gmv + d_gmv) / (orders + d_orders) - gmv / orders
    d_bien: float | None = None
    sp = env.view.profit
    m0, base_paid = sp.margin_rate, float(sp.buyer_paid_covered)
    if d_profit is not None and d_gmv is not None and m0 is not None and base_paid > 0 and gmv:
        scale = base_paid / gmv
        # doanh thu thực after: today's + ΔGMV x net/GMV − the new offers that lower it
        paid_after = base_paid + d_gmv * scale - d_offer
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
        "replaced_by": next((r.replaced_by for r in leaves if r.replaced_by), None),
        #: decision #47: why the card is not counted (``exclusive_programme``), else None
        "not_counted_reason": next(
            (r.reason for r in leaves if r.replaced_by and r.reason == EXCLUSIVE_REASON), None
        ),
        "cost_total": cost_own,
        "cost_horizon": cost_horizon,
        #: A2.2: the card's share of its campaign's budget and the platform's cost per order
        "ads": _card_ads(full, [r.card_id for r in leaves]),
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
            key=("measured", "product_history", "shop", "pooled", "prior", "not_estimable").index,
        ),
        "own": {
            "dates": common["own_dates"],
            "days": common["own_days"],
            "delta": _rounded(own),
            "cost_total": cost_own,
            # P4: the share of the card's own cost the plan counts (an ads card's campaign is
            # counted once: its share of the campaign; 1.0 otherwise). The month goal reads it
            # (``month_plan.uplift_in_month``), so the goal equals the plan total.
            "cost_counted_share": _cost_share(full, ok, h),
        },
        "delta": _rounded(inside),
        "after": _after_of(common["before"], inside["p50"]),
        **common,
    }


def _cost_share(full: Joint, leaves: Sequence[CardResult], h: Horizon) -> float:
    """The counted share of the leaves' own cost inside the horizon (1.0 without an ads share)."""
    own = shared = 0.0
    for r in leaves:
        c = r.cost_in(h)
        if c is None:
            continue
        own += c
        shared += full.ads_cost.get(r.card_id, c)
    return 1.0 if own <= 0 else shared / own


def _card_ads(full: Joint, leaf_ids: Sequence[str]) -> list[dict[str, Any]] | None:
    out = [
        {"campaign": c["campaign"], **card}
        for c in full.ads_campaigns.values()
        for card in c["cards"]
        if card["card_id"] in leaf_ids
    ]
    return out or None


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


#: P7: the plan's split channels and the Δ fields a channel carries
SPLIT_FIELDS = ("dgmv", "dorders", "dprofit")
AFFILIATE_SOURCE = "lien_ket"


def _channel_of(r: CardResult) -> str | None:
    """The channel a card's own Δ belongs to as a whole: an ads card (it spends a campaign) ->
    Quảng cáo, an affiliate / KOL card -> TTLK; ``None`` = a lever on the shop's own funnel
    (Organic, its Tiếp thị liên kết source's part -> TTLK)."""
    kind = "" if r.result is None else r.result.kind
    if r.campaign:
        return "ads"
    if kind.startswith("affiliate") or kind.startswith("kol"):
        return "affiliate"
    return None


def _ttlk_share(r: CardResult, name: str) -> float:
    """The part of a lever card's P50 Δ ``name`` that lands on the Tiếp thị liên kết source."""
    res = r.result
    if res is None or res.likely is None:
        return 0.0
    field = RESULT_FIELDS[name]
    total_a, total_b = getattr(res.likely, field), getattr(res.before, field)
    a = (res.likely.by_source.get(AFFILIATE_SOURCE) or {}).get(field)
    b = (res.before.by_source.get(AFFILIATE_SOURCE) or {}).get(field)
    if total_a is None or total_b is None or a is None or b is None or total_a == total_b:
        return 0.0
    return float((a - b) / (total_a - total_b))


def split_delta(
    counted: Mapping[str, Counted], results: Mapping[str, CardResult]
) -> dict[str, dict[str, float | None]]:
    """P7: the plan's P50 Δ per channel (Organic / Quảng cáo / TTLK) from the SEPARATE card
    results as the plan counts them (an ads card's campaign share, #47's exclusions): an ads card
    -> Quảng cáo, an affiliate card -> TTLK, a lever card -> Organic but the part of its Δ on the
    Tiếp thị liên kết source -> TTLK. The channels add up to the plan's P50 exactly; an unknown
    Δ stays unknown."""
    out: dict[str, dict[str, float | None]] = {
        ch: dict.fromkeys(SPLIT_FIELDS, 0.0) for ch in ("organic", "ads", "affiliate")
    }
    for cid, c in counted.items():
        r = results.get(cid)
        if r is None:
            continue
        whole = _channel_of(r)
        for name in SPLIT_FIELDS:
            v = c.cols["p50"].get(name)
            if v is None:
                for ch in out:
                    out[ch][name] = None
                continue
            if whole is not None:
                if out[whole][name] is not None:
                    out[whole][name] = float(out[whole][name] or 0.0) + v
                continue
            share = _ttlk_share(r, name)
            for ch, part in (("affiliate", v * share), ("organic", v * (1 - share))):
                if out[ch][name] is not None:
                    out[ch][name] = float(out[ch][name] or 0.0) + part
    return out


def _split_block(env: RecoEnv, j: Joint, product_id: str | None) -> dict[str, Any] | None:
    """P7: today's Organic / Quảng cáo / TTLK of the scope (Tổng quan's split, 30 days) and the
    plan's Δ per channel; ``None`` without results (the legacy path)."""
    from juli_backend.services.shopee_analytics.channel_split import profit_split

    if j.result_basis is None or j.horizon is None or not hasattr(env.view, "pairs"):
        return None
    results = {r.card_id: r for r in j.leaves}
    metrics = getattr(env.view, "metrics", None)
    kpi_gmv = kpi_orders = None
    if metrics is not None:
        # the Tổng quan totals of the scope (decision #55 Q1): the shop's, or the product's
        # share of them; the split's GMV / đơn add up to these
        part = metrics if product_id is None else metrics.split(product_id)
        if part is not None:
            kpi_gmv = None if part.gmv is None else Decimal(part.gmv)
            kpi_orders = None if part.orders is None else Decimal(part.orders)
    return {
        "today": profit_split(env.view, product_id, kpi_gmv=kpi_gmv, kpi_orders=kpi_orders),
        "delta_p50": split_delta(j.counted, results),
    }


def _product_block(env: RecoEnv, pid: str, evs: Sequence[Evaluated], memo: _Memo) -> dict[str, Any]:
    j = memo.of([e.entry.card_id for e in evs])
    base = float(sum((ln.order_value for ln in env.lines_for([pid]) if counts_in_sales(ln)), ZERO))
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
        "split": _split_block(env, j, pid),
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
    comb = combine_results(mine, horizon, ads_data_of(env))
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
    default_end: date | None = None,
    keyword_weights: KeywordWeights | None = None,
    stored: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[Evaluated]]:
    """The plan's aggregate payload and the evaluated cards (chosen version on this env).

    P99b: the numbers are the expected outcome over the next 30 days starting ``today``
    (default ``now``'s date): baseline 30 days + each card's Δ on its own days inside them.
    ``default_start``: where a change without dates of its own starts (a group's first day; else
    today). ``default_end``: a group's last day -- a card counts only on its group's days (A3.1)."""
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
            # P100 A.8: "no card" only when there is none (cards that cannot be evaluated on
            # this data are listed in ``unavailable_cards`` instead)
            "empty_note": None if entries else "Kế hoạch chưa có thẻ nào.",
            "today": today_block,
            "after": None,
            "deltas_p50": None,
            "cost": None,
            "cards": [],
            "unavailable_cards": unavailable,
            "range_method": RANGE_METHOD,
            "result_basis": RESULT_BASIS,
        }, []
    results = card_results(
        env, evs, variations, default_start or horizon.start, keyword_weights, stored
    )
    if default_start is not None:
        for r in results.values():
            if r.start is None:
                r.start = default_start
    if default_end is not None:
        for r in results.values():
            r.end = default_end
    assign_campaigns(results, evs, ads_data_of(env))
    resolve_exclusive(results, evs, horizon)  # decision #47
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
        "drevoffer_month": {q: full.total[q]["drevoffer"] for q in ("p10", "p50", "p90")},
        # P7: Organic / Quảng cáo / TTLK today (Tổng quan's split) and the plan's Δ per channel
        "split": _split_block(env, full, None),
        # P4: the plan's ONE "Biên lợi nhuận" (registry ``margin``: lợi nhuận ròng ÷ doanh thu
        # thực) before and after; ``after.margin_pct`` and the steps summary read the same figure
        "margin": {
            "metric_id": "margin",
            "before_pct": today_block["margin_pct"],
            "after_pct": _after(today_block, deltas)["margin_pct"],
        },
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
        #: P100-C (B.10): False when no card is estimable -- the totals are None ("chưa ước tính
        #: được"), the cards' costs and break-even still show
        "totals_estimable": not full.none_estimable,
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
    if j.none_estimable:
        return (
            f"Chưa ước tính được: {len(j.not_estimable)} thẻ chưa có kết quả ước tính "
            "(chỉ có chi phí và điểm hoà vốn)."
        )
    if j.not_estimable:
        parts.append(f"{len(j.not_estimable)} thẻ chưa ước tính được")
    if unavailable:
        parts.append(f"{len(unavailable)} thẻ không tính lại được")
    if not parts:
        return None
    return "Tổng chưa gồm " + " và ".join(parts) + "."


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _sum_range(parts: Sequence[Mapping[str, float | None]]) -> dict[str, float | None]:
    """``{p10, p50, p90}`` of several independent sides: the P50s add, the range is the P50 -/+ the
    root sum of squares of the sides' half-widths (the plan's range rule, ``combine_counted``). A
    side that does not know the metric (P50 ``None``) is left out; nobody knows it: all ``None``."""
    known = [p for p in parts if p.get("p50") is not None]
    if not known:
        return {"p10": None, "p50": None, "p90": None}
    mid = sum(float(p["p50"] or 0.0) for p in known)
    out: dict[str, float | None] = {"p10": None, "p50": mid, "p90": None}
    for q, sign in (("p10", -1.0), ("p90", 1.0)):
        edges = [p.get(q) for p in known]
        if any(e is None for e in edges):
            continue
        width = math.sqrt(
            sum(
                (float(p["p50"] or 0.0) - float(e or 0.0)) ** 2
                for p, e in zip(known, edges, strict=True)
            )
        )
        out[q] = mid + sign * width
    return out


def _side_totals(side: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    """One side's (the plan's own cards or one group) {metric: {p10, p50, p90}} from its payload."""
    dprofit = (side.get("dprofit_month") or {}).get("total") or {}
    dgmv = (side.get("dgmv_month") or {}).get("total") or {}
    dorders = side.get("dorders_month") or {}
    after, today = side.get("after") or {}, side.get("today") or {}

    def own(key: str) -> dict[str, float | None]:
        a, t = after.get(key), today.get(key)
        return {
            "p10": None,
            "p50": None if a is None or t is None else float(a) - float(t),
            "p90": None,
        }

    return {
        "dgmv": {q: dgmv.get(q) for q in ("p10", "p50", "p90")},
        "dorders": {q: dorders.get(q) for q in ("p10", "p50", "p90")},
        "dprofit": {q: dprofit.get(q) for q in ("p10", "p50", "p90")},
        "dviews": own("views_30d"),
        "dclicks": own("clicks_30d"),
        "drevoffer": {
            q: (side.get("drevoffer_month") or {}).get(q, 0.0) for q in ("p10", "p50", "p90")
        },
    }


def merge_groups(
    env: RecoEnv, agg: dict[str, Any], group_aggs: Sequence[Mapping[str, Any] | None]
) -> dict[str, Any]:
    """K2 / K3 (batch-1117b): the plan's total over ALL its cards. A card run together in a group
    is evaluated in the group's aggregate (its own period, one joint lift), so the plan's own
    aggregate alone leaves it out and reads "chưa ước tính được" while the group holds an estimable
    card. The plan total adds the groups' totals to the plan's own by the one range rule (P50s add,
    half-widths by root sum of squares). The plan's own ``cards`` stay as they are (each group
    keeps its cards), so no card is listed twice.

    ``n_cards`` counts the plan's cards (a card in a group once, whatever its versions)."""
    groups = [g for g in group_aggs if g and not g.get("empty")]
    if not groups:
        return agg
    sides = ([] if agg.get("empty") else [agg]) + groups
    parent_ids = {
        parent_id(str(c["card_id"]).split("@v", 1)[0]) for g in groups for c in g.get("cards") or []
    }
    own_ids = {parent_id(c["card_id"]) for c in agg.get("cards") or []}
    out = dict(agg)
    if agg.get("empty"):  # only grouped cards: the shape of a full aggregate, from the first group
        for k, v in groups[0].items():
            if k not in ("cards", "products", "n_cards", "unavailable_cards"):
                out.setdefault(k, v)
    out["n_cards"] = len(own_ids | parent_ids)
    out["empty"] = False
    out["empty_note"] = None
    live = [s for s in sides if s.get("totals_estimable", True)]
    totals = {m: _sum_range([_side_totals(s)[m] for s in live]) for m in RESULT_METRICS}
    # P4: a campaign on two sides is counted once across the plan (its cost was in each side's Δ)
    twice = campaign_overlap(sides)
    back = sum(twice.values())
    if back:
        totals["dprofit"] = {
            q: None if v is None else v + back for q, v in totals["dprofit"].items()
        }
        _once_shares(sides, twice)
    estimable = bool(live)
    out["totals_estimable"] = estimable

    def union(key: str) -> list[str]:
        return list(dict.fromkeys(i for s in sides for i in s.get(key) or []))

    for key in ("not_estimable_cards", "outside_horizon_cards", "unavailable_cards"):
        out[key] = union(key)
    out["cost_unknown_cards"] = union("cost_unknown_cards")
    out["totals_partial"] = bool(out["not_estimable_cards"] or out["unavailable_cards"])
    certain: dict[str, float | None] = {}
    for key, name in (("dprofit_month", "dprofit"), ("dgmv_month", "dgmv")):
        vals: list[float | None] = [(s.get(key) or {}).get("certain") for s in sides]
        known = [v for v in vals if v is not None]
        certain[name] = sum(known) if len(known) == len(vals) else None
    predicted = _sum_range([(s.get("dprofit_month") or {}).get("predicted") or {} for s in live])
    out["dprofit_month"] = {
        "certain": certain["dprofit"],
        "predicted": predicted,
        "total": totals["dprofit"],
    }
    out["dgmv_month"] = {"certain": certain["dgmv"], "total": totals["dgmv"]}
    out["dorders_month"] = totals["dorders"]
    p50 = {m: totals[m]["p50"] for m in RESULT_METRICS}
    deltas = result_deltas(env, {"p50": p50})
    out["deltas_p50"] = deltas
    today_block = agg.get("today") or groups[0].get("today")
    if today_block is not None:
        out["today"] = today_block
        out["after"] = {
            **_after(today_block, deltas),
            **after_funnel(today_block, {"p50": p50}),
            "label": "Dự kiến (P50)",
        }
        out["margin"] = {
            "metric_id": "margin",
            "before_pct": today_block["margin_pct"],
            "after_pct": out["after"]["margin_pct"],
        }
    out["drevoffer_month"] = totals["drevoffer"]
    out["split"] = _merge_split(sides, twice)
    out["cost"] = _merge_cost(agg, groups)
    if back and out["cost"] is not None:
        cost = dict(out["cost"])
        cost["ads_counted_once"] = {k: -v for k, v in twice.items()}
        for key in ("delta_per_month", "horizon_spend_delta"):
            if cost.get(key) is not None:
                cost[key] = float(cost[key]) - back
        out["cost"] = cost
    out["totals_note"] = _merge_note(out, estimable)
    return out


def _merge_split(
    sides: Sequence[Mapping[str, Any]], twice: Mapping[str, float]
) -> dict[str, Any] | None:
    """P7: the plan's channel Δ over its own cards and every group's (the campaign counted twice
    across sides goes back to Quảng cáo, as in the total)."""
    blocks = [s["split"] for s in sides if s.get("split")]
    if not blocks:
        return None
    delta: dict[str, dict[str, float | None]] = {
        ch: dict.fromkeys(SPLIT_FIELDS, 0.0) for ch in ("organic", "ads", "affiliate")
    }
    for b in blocks:
        for ch, row in b["delta_p50"].items():
            for name, v in row.items():
                cur = delta[ch][name]
                delta[ch][name] = None if v is None or cur is None else cur + v
    if delta["ads"]["dprofit"] is not None:
        delta["ads"]["dprofit"] = float(delta["ads"]["dprofit"] or 0.0) + sum(twice.values())
    return {"today": blocks[0]["today"], "delta_p50": delta}


def _once_shares(sides: Sequence[Mapping[str, Any]], twice: Mapping[str, float]) -> None:
    """Scale the counted cost share of the cards of a campaign counted twice, so the month goal
    (``month_plan.uplift_in_month``) counts it once too."""
    total: dict[str, float] = {}
    for s in sides:
        for block in ((s.get("cost") or {}).get("ads_campaigns")) or []:
            k = str(block["campaign"])
            total[k] = total.get(k, 0.0) + float(block.get("cost_horizon") or 0.0)
    for s in sides:
        for card in s.get("cards") or []:
            res = card.get("result") or {}
            own = res.get("own")
            ads = res.get("ads") or []
            keys = [str(a["campaign"]) for a in ads if str(a["campaign"]) in twice]
            if not own or not keys or total.get(keys[0], 0.0) <= 0:
                continue
            k = keys[0]
            factor = (total[k] - twice[k]) / total[k]
            own["cost_counted_share"] = float(own.get("cost_counted_share", 1.0)) * factor


def campaign_overlap(sides: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """P4 (audit P6): a campaign the plan's own cards AND a group's (or two groups') cards spend
    is counted once across the plan: its lowest per-day cost x the union of the days, the
    owner's rule inside one aggregate (``ads_shares``). Returns campaign -> the cost the sides
    counted twice (Σ sides − once); only campaigns on two sides or more."""
    seen: dict[str, list[Mapping[str, Any]]] = {}
    for s in sides:
        for block in ((s.get("cost") or {}).get("ads_campaigns")) or []:
            seen.setdefault(str(block["campaign"]), []).append(block)
    out: dict[str, float] = {}
    for key, blocks in seen.items():
        if len(blocks) < 2:
            continue
        days = {d for b in blocks for d in b.get("dates") or []}
        per_day = min(float(b.get("cost_per_day") or 0.0) for b in blocks)
        twice = sum(float(b.get("cost_horizon") or 0.0) for b in blocks) - per_day * len(days)
        if twice > 0:
            out[key] = twice
    return out


def _merge_cost(
    agg: Mapping[str, Any], groups: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    sides = [s for s in (agg, *groups) if s.get("cost")]
    if not sides:
        return None
    base = dict(sides[0]["cost"])
    days = float((base.get("horizon") or {}).get("days") or config.DAYS_PER_MONTH)
    delta_total = sum(float(s["cost"].get("horizon_spend_delta") or 0.0) for s in sides)
    before = float(base["per_day_before"])
    after = before + delta_total / days
    cap = base.get("cap_per_day")
    over = cap is not None and after > float(cap)
    base.update(
        per_day_after=after,
        delta_per_day=delta_total / days,
        per_month_after=after * days,
        delta_per_month=sum(float(s["cost"].get("delta_per_month") or 0.0) for s in sides),
        over_cap=bool(over),
        over_by_per_day=float(after - float(cap)) if over and cap is not None else 0.0,
        horizon_spend_delta=delta_total,
        horizon_spend_after=after * days,
        cost_unknown_cards=list(
            dict.fromkeys(i for s in sides for i in s["cost"].get("cost_unknown_cards") or [])
        ),
    )
    base["cost_complete"] = not base["cost_unknown_cards"]
    base["ads_campaigns"] = [c for s in sides for c in s["cost"].get("ads_campaigns") or []]
    return base


def _merge_note(out: Mapping[str, Any], estimable: bool) -> str | None:
    n_bad = len(out.get("not_estimable_cards") or [])
    if not estimable:
        return (
            f"Chưa ước tính được: {n_bad} thẻ chưa có kết quả ước tính "
            "(chỉ có chi phí và điểm hoà vốn)."
        )
    parts = []
    if n_bad:
        parts.append(f"{n_bad} thẻ chưa ước tính được")
    if out.get("unavailable_cards"):
        parts.append(f"{len(out['unavailable_cards'])} thẻ không tính lại được")
    return "Tổng chưa gồm " + " và ".join(parts) + "." if parts else None


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
    "merge_groups",
    "total_of",
]
