"""One ad cost per product (owner decision #39): "chi phí quảng cáo của sản phẩm".

The spend of the campaigns that advertise the product, from the ads report by product. Every
product-level reader (the stored day rows, the window figure ``ProductProfit.ad_spend``, the
exports, Đo lường, the forecast base, Chat) reads this one rule; there is no second formula.

Per campaign and day::

    day value = the campaign's spend that day (Connector daily)
                x the product's share of that campaign's spend in the ads report by product

The share comes from exactly one report window per (campaign, day): the shortest window that
covers the day (a one-day row beats a three-day one), else the nearest window of the campaign.
Overlapping windows are never summed. A day the Connector did not read falls back to the report
window that covers it, spread over its days. A product with no campaign basis on a day has no
value (``None``), never 0. The window figure is the sum of its day values, so the days add up
to the window by construction. Pure: no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal(0)


@dataclass(frozen=True)
class ReportRow:
    """One row of the ads report by product: campaign x product over ``start``..``end``."""

    key: str  # campaign segment hash (the Connector's campaign key)
    item_id: str
    start: date
    end: date
    spend: Decimal


@dataclass(frozen=True)
class CampaignDayRow:
    """One campaign on one finished day, as the Connector read it (``ads_campaign_daily``, placed
    orders); a count the row lacks is ``None``."""

    spend: Decimal
    gmv: Decimal | None = None
    direct_gmv: Decimal | None = None
    orders: Decimal | None = None
    clicks: Decimal | None = None
    impressions: Decimal | None = None
    name: str = ""
    ad_type: str | None = None
    state: str | None = None


@dataclass
class ProductAdsInput:
    """What the rule reads: the Connector's campaign days and the by-product report rows."""

    #: (campaign key, day) -> spend of the Connector's finished day
    campaign_days: dict[tuple[str, date], Decimal] = field(default_factory=dict)
    #: days the Connector read (its shop-level row exists), even when a campaign is absent
    covered_days: frozenset[date] = frozenset()
    report_rows: list[ReportRow] = field(default_factory=list)
    #: C2: the same (campaign key, day) rows with every figure, not only the spend
    day_rows: dict[tuple[str, date], CampaignDayRow] = field(default_factory=dict)
    #: campaign title -> campaign key, for a report that names its campaign only by the title
    title_keys: dict[str, str] = field(default_factory=dict)

    def day_row(self, key: str, day: date) -> CampaignDayRow | None:
        row = self.day_rows.get((key, day))
        if row is None and (key, day) in self.campaign_days:
            return CampaignDayRow(self.campaign_days[(key, day)])
        return row

    def joiner(self) -> Callable[[str, str | None], str]:
        """(segment, title) of a report row -> its campaign: the segment hash (the campaign id); a
        report that names the campaign only by its title joins by the title the days carry."""
        known = {k for k, _ in self.campaign_days}

        def join(segment: str, title: str | None) -> str:
            if segment not in known and title in self.title_keys:
                return self.title_keys[title]
            return segment

        return join


def _window_of(
    windows: Iterable[tuple[date, date]], day: date, *, covering_only: bool
) -> tuple[date, date] | None:
    best: tuple[tuple[int, int, int], tuple[date, date]] | None = None
    for start, end in windows:
        if start <= day <= end:
            rank = (0, (end - start).days, -start.toordinal())
        elif covering_only:
            continue
        else:
            gap = (start - day).days if day < start else (day - end).days
            rank = (gap, (end - start).days, -start.toordinal())
        if best is None or rank < best[0]:
            best = (rank, (start, end))
    return best[1] if best else None


class ProductAdRule:
    """The rule over one input; build once per window, then ask per product and day."""

    def __init__(self, inp: ProductAdsInput) -> None:
        self._inp = inp
        # key -> window -> item -> spend
        self._by_key: dict[str, dict[tuple[date, date], dict[str, Decimal]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        for r in inp.report_rows:
            cell = self._by_key[r.key][(r.start, r.end)]
            cell[r.item_id] = cell.get(r.item_id, ZERO) + r.spend
        self._keys_by_day: dict[date, list[str]] = defaultdict(list)
        for key, day in inp.campaign_days:
            self._keys_by_day[day].append(key)
        self._cache: dict[date, dict[str, Decimal]] = {}

    def day_values(self, day: date) -> dict[str, Decimal]:
        """item -> the product's ad cost on ``day`` (only products with a basis)."""
        cached = self._cache.get(day)
        if cached is not None:
            return cached
        out: dict[str, Decimal] = {}
        if day in self._inp.covered_days:
            for key in self._keys_by_day.get(day, ()):
                spent = self._inp.campaign_days[(key, day)]
                win = _window_of(self._by_key.get(key, {}), day, covering_only=False)
                if win is None:
                    continue
                items = self._by_key[key][win]
                total = sum(items.values(), ZERO)
                if total <= 0:
                    # a report that spent nothing gives no share; the product has no basis
                    continue
                for item, item_spend in items.items():
                    out[item] = out.get(item, ZERO) + spent * item_spend / total
        else:
            for key, windows in self._by_key.items():
                win = _window_of(windows, day, covering_only=True)
                if win is None:
                    continue
                length = (win[1] - win[0]).days + 1
                for item, item_spend in windows[win].items():
                    out[item] = out.get(item, ZERO) + item_spend / length
        self._cache[day] = out
        return out

    def product_day(self, item_id: str, day: date) -> Decimal | None:
        """The one ad cost of a product on a day; ``None`` = no basis (never 0)."""
        return self.day_values(day).get(item_id)

    def window_spend(self, start: date, end: date) -> dict[str, Decimal]:
        """item -> sum of its day values over the window (products with a basis on any day)."""
        out: dict[str, Decimal] = {}
        day = start
        while day <= end:
            for item, value in self.day_values(day).items():
                out[item] = out.get(item, ZERO) + value
            day += timedelta(days=1)
        return out


def product_ad_cost(inp: ProductAdsInput, item_id: str, start: date, end: date) -> Decimal | None:
    """A product's ad cost over ``start``..``end``; ``None`` when no day has a basis."""
    return ProductAdRule(inp).window_spend(start, end).get(item_id)
