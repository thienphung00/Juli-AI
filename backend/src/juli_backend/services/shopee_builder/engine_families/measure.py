"""Measurements for Ads and Affiliate (ADR-122 d.8, d.9): small pure helpers over the shop's own
history. Ads and Affiliate never take a general prior: when a number cannot be measured the helper
returns ``None`` and the family says "chưa ước tính được"."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from juli_backend.services.shopee_builder.engine.contract import Band
from juli_backend.services.shopee_builder.engine_families import common

ZERO = Decimal(0)


def _div(a: Decimal, b: Decimal) -> Decimal | None:
    return None if b <= 0 else a / b


# -- ads: CPM, ad funnel rates, spend a ROAS target lets Shopee use ------------------------------


@dataclass(frozen=True)
class AdCampaignHist:
    """One past campaign over its run: totals in the window (``ads_campaign_daily`` / settings)."""

    key: str
    item_ids: frozenset[str]
    ad_type: str
    spend: Decimal
    impressions: Decimal
    clicks: Decimal
    direct_orders: Decimal
    direct_gmv: Decimal
    days: int = 0
    daily_budget: Decimal | None = None
    roas_target: Decimal | None = None
    #: P100 B.15: Shopee's ad GMV (placed orders, all attributed), for "ROAS Shopee"
    gmv: Decimal | None = None


@dataclass(frozen=True)
class AdRates:
    """Rates of the ad traffic: CPM band (đ per 1.000 impressions, low = cheapest), CTR, CTOR
    (direct orders ÷ clicks), AOV (direct GMV ÷ direct orders); ``scope`` says which history."""

    cpm_low: Decimal
    cpm_mid: Decimal
    cpm_high: Decimal
    ctr: Decimal | None
    ctor: Decimal | None
    aov: Decimal | None
    scope: str  # "product" | "shop_ad_type"
    campaigns: int


def ad_rates(
    campaigns: Iterable[AdCampaignHist], item_ids: Sequence[str], ad_type: str
) -> AdRates | None:
    """The product's past campaigns first, else the same ad type shop-wide (d.8). ``None`` = no
    campaign with impressions in either."""
    pool = [c for c in campaigns if c.impressions > 0 and c.spend > 0]
    wanted = set(item_ids)
    own = [c for c in pool if c.item_ids & wanted]
    scope = "product"
    chosen = own
    if not chosen:
        chosen = [c for c in pool if c.ad_type == ad_type]
        scope = "shop_ad_type"
    if not chosen:
        return None
    cpms = sorted(c.spend / c.impressions * 1000 for c in chosen)
    imp = sum((c.impressions for c in chosen), ZERO)
    clicks = sum((c.clicks for c in chosen), ZERO)
    orders = sum((c.direct_orders for c in chosen), ZERO)
    gmv = sum((c.direct_gmv for c in chosen), ZERO)
    spend = sum((c.spend for c in chosen), ZERO)
    return AdRates(
        cpms[0],
        spend / imp * 1000,
        cpms[-1],
        _div(clicks, imp),
        _div(orders, clicks),
        _div(gmv, orders),
        scope,
        len(chosen),
    )


def spend_utilisation(
    campaigns: Iterable[AdCampaignHist], roas_target: Decimal, tolerance: Decimal = Decimal("0.5")
) -> Decimal | None:
    """Share of the daily budget Shopee actually spent at a similar ROAS target, from history
    (d.8: "the spend a ROAS target lets Shopee use"). ``None`` = no campaign at a similar target."""
    spent = budget = ZERO
    for c in campaigns:
        if (
            c.roas_target is None
            or c.daily_budget is None
            or c.days <= 0
            or abs(c.roas_target - roas_target) > tolerance
        ):
            continue
        spent += c.spend
        budget += c.daily_budget * c.days
    ratio = _div(spent, budget)
    return None if ratio is None else common.clamp01(ratio)


def spend_utilisation_system(campaigns: Iterable[AdCampaignHist]) -> Decimal | None:
    """Share of the daily budget Shopee spent on campaigns whose ROAS Shopee optimises itself
    (no target); ``None`` = no such campaign with a daily budget."""
    spent = budget = ZERO
    for c in campaigns:
        if c.roas_target is not None or c.daily_budget is None or c.days <= 0:
            continue
        spent += c.spend
        budget += c.daily_budget * c.days
    ratio = _div(spent, budget)
    return None if ratio is None else common.clamp01(ratio)


# -- ads edits (P100 B.15): is the campaign held back by its daily budget? -----------------------

#: A day that spent at least this share of its daily budget was capped by the budget.
CAPPED_SHARE = Decimal("0.95")


@dataclass(frozen=True)
class CampaignDay:
    """One day of a running campaign (``ads_campaign_daily``): its spend and that day's budget
    (``None`` = không giới hạn)."""

    spend: Decimal
    daily_budget: Decimal | None


@dataclass(frozen=True)
class BudgetState:
    """How the campaign spends against its budget: ``rate`` = spend per running day today;
    ``capped`` = it spends (nearly) its whole budget on most days; ``uncapped_rate`` = its mean
    spend on the days the budget did not hold it back (None = too few such days)."""

    rate: Decimal
    capped: bool
    uncapped_rate: Decimal | None
    running_days: int


def budget_state(
    spend: Decimal, window_days: int, budget: Decimal | None, days: Sequence[CampaignDay] = ()
) -> BudgetState | None:
    """From the campaign's own days when the Connector posted them, else from the window's total
    against today's budget. ``None`` = the campaign spent nothing in the window."""
    running = [d for d in days if d.spend > 0]
    if running:
        n = len(running)
        rate = spend / n if spend > 0 else sum((d.spend for d in running), ZERO) / n
        capped_days = [
            d for d in running if d.daily_budget and d.spend >= CAPPED_SHARE * d.daily_budget
        ]
        free = [d for d in running if d not in capped_days]
        free_rate = (
            sum((d.spend for d in free), ZERO) / len(free)
            if len(free) >= common.MIN_MEASURE_DAYS
            else None
        )
        capped = 2 * len(capped_days) >= n
        if free_rate is None and not capped:
            free_rate = rate  # held back on a few days only: today's rate is its own rate
        return BudgetState(rate, capped, free_rate, n)
    if spend <= 0 or window_days <= 0:
        return None
    rate = spend / window_days
    capped = budget is not None and budget > 0 and rate >= CAPPED_SHARE * budget
    return BudgetState(rate, capped, None if capped else rate, window_days)


@dataclass(frozen=True)
class AdDay:
    """One day of the product: its organic Thẻ sản phẩm orders and whether an ad ran for it."""

    on: bool
    organic_orders: Decimal
    ad_orders: Decimal = ZERO


def _mean_var(xs: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    n = Decimal(len(xs))
    m = sum(xs, ZERO) / n
    var = sum(((x - m) ** 2 for x in xs), ZERO) / (n - 1) if n > 1 else ZERO
    return m, var


def incremental_share(days: Sequence[AdDay]) -> Band | None:
    """P100 B.15: the share of the ad's orders that would not have happened without it -- the
    products' card orders per day (organic + ad) with ads minus without (a Welch difference),
    over the ad orders per on-day. Organic orders that do not move on ad days still give a
    non-zero share (the ad's own orders are the lift). ``None`` = fewer than ``MIN_MEASURE_DAYS``
    on or off days, or no ad orders."""
    on = [d for d in days if d.on]
    off = [d for d in days if not d.on]
    if len(on) < common.MIN_MEASURE_DAYS or len(off) < common.MIN_MEASURE_DAYS:
        return None
    per_on = sum((d.ad_orders for d in on), ZERO) / len(on)
    if per_on <= 0:
        return None
    m_on, v_on = _mean_var([d.organic_orders + d.ad_orders for d in on])
    m_off, v_off = _mean_var([d.organic_orders + d.ad_orders for d in off])
    diff = m_on - m_off
    se = (v_on / len(on) + v_off / len(off)).sqrt()
    return Band(
        common.clamp01((diff - common.Z90 * se) / per_on),
        common.clamp01(diff / per_on),
        common.clamp01((diff + common.Z90 * se) / per_on),
    )


# -- affiliate: a KOL's own rates and its before / after -----------------------------------------


@dataclass(frozen=True)
class KolRates:
    """A KOL's own measured row over ``days``: views of their links (``None`` = unknown), clicks,
    orders, GMV. Rates are always ratios of these sums."""

    kol_key: str
    handle: str
    days: int
    views: Decimal | None
    clicks: Decimal
    orders: Decimal
    gmv: Decimal

    @property
    def ctr(self) -> Decimal | None:
        return None if self.views is None else _div(self.clicks, self.views)

    @property
    def ctor(self) -> Decimal | None:
        return _div(self.orders, self.clicks)

    @property
    def aov(self) -> Decimal | None:
        return _div(self.gmv, self.orders)


@dataclass(frozen=True)
class KolBeforeAfter:
    """The shop's own orders per day of the product before and after the first sample to this KOL,
    and the KOL's own orders after (the number the extra share is a share of)."""

    days_before: int
    days_after: int
    orders_before: Decimal
    orders_after: Decimal
    kol_orders_after: Decimal


def kol_extra_share(m: KolBeforeAfter | None) -> Band | None:
    """Extra share from the before / after on that KOL: the lift in the product's orders per day
    × days after, over the KOL's own orders after; a Poisson spread on the counts. ``None`` =
    not enough days or no KOL orders (then the card says "đo sau lần gửi mẫu đầu")."""
    if (
        m is None
        or m.days_before < common.MIN_MEASURE_DAYS
        or m.days_after < common.MIN_MEASURE_DAYS
        or m.kol_orders_after <= 0
    ):
        return None
    rate_b = m.orders_before / m.days_before
    rate_a = m.orders_after / m.days_after
    extra = (rate_a - rate_b) * m.days_after
    se = (m.orders_after + m.orders_before * m.days_after / m.days_before).sqrt()
    n = m.kol_orders_after
    return Band(
        common.clamp01((extra - common.Z90 * se) / n),
        common.clamp01(extra / n),
        common.clamp01((extra + common.Z90 * se) / n),
    )


def is_cashback(handle: str, extra_names: Sequence[str] = ()) -> bool:
    """Cashback / coupon affiliates by name (config list, case-insensitive; a name ending in `_`
    is a prefix, any other is the whole handle or its prefix before a digit / underscore)."""
    h = handle.strip().lower().lstrip("@")
    for name in (*common.CASHBACK_AFFILIATES, *extra_names):
        n = name.lower()
        if h == n or (n.endswith("_") and h.startswith(n)) or h.rstrip("0123456789_") == n:
            return True
    return False
