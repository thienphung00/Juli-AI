"""Ad spend: which source answers for which campaign-day (G-07), and the order basis (D-2).

Two sources describe the same spend. The Connector's ``ads_campaign_daily`` gives one finished
day per campaign; the CSV reports (``ads_campaign_period``) give a window of about three months
per campaign x product, and consecutive exports OVERLAP. The rule (owner, Step 6):

- a day the Connector covers is answered by the Connector, for every campaign. A CSV window never
  adds spend for that day, so one campaign-day is never counted twice;
- every other day is answered by the CSV window rows. A window that also spans covered days (or
  days outside the asked range, or days an overlapping newer window already answers) contributes
  only its share of free days (days in window / free days, pro rata, flagged ``prorated``);
- per-product spend comes from the group-campaign per-product rows only (the Connector has no
  product split), so it covers the CSV share of the range; the rest is ``unattributed``.

Campaigns are matched by their normalised name (the CSV has no campaign id).

D-2: every figure here carries its ORDER BASIS (``placed``: the ads reports count placed orders).
:func:`confirmed_total` is the only way to add figures into a confirmed total and refuses any
other basis, so an ads GMV / orders figure can never be summed into confirmed revenue.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.shopee_profit.money import ZERO

BASIS_PLACED = "placed"
BASIS_CONFIRMED = "confirmed"
#: The column holding the campaign name is cut to 64 characters when stored.
NAME_LENGTH = 64


class OrderBasisError(ValueError):
    """Figures of two order bases were about to be added (D-2)."""


def campaign_key(name: str | None) -> str:
    """The key two sources share for one campaign: NFKC, case-folded, single spaces, 64 chars."""
    text = unicodedata.normalize("NFKC", name or "")
    return " ".join(text.casefold().split())[:NAME_LENGTH]


@dataclass(frozen=True)
class AdDay:
    """One campaign on one finished day (Connector ``ads_campaign_daily``)."""

    campaign: str
    day: date
    spend: Decimal
    gmv: Decimal | None = None
    orders: Decimal | None = None
    order_basis: str = BASIS_PLACED


@dataclass(frozen=True)
class AdWindow:
    """One campaign x product over a report window (CSV ``ads_campaign_period``)."""

    campaign: str
    start: date
    end: date
    spend: Decimal
    item_id: str | None = None  # None = a campaign-level row
    gmv: Decimal | None = None
    orders: Decimal | None = None
    order_basis: str = BASIS_PLACED


@dataclass
class CampaignSpend:
    connector: Decimal = ZERO
    csv: Decimal = ZERO
    prorated: bool = False

    @property
    def total(self) -> Decimal:
        return self.connector + self.csv


@dataclass
class AdSpendResult:
    start: date
    end: date
    order_basis: str
    covered_days: int
    campaigns: dict[str, CampaignSpend] = field(default_factory=dict)
    #: product -> spend from the per-product CSV rows (share of free days only).
    products: dict[str, Decimal] = field(default_factory=dict)
    #: CSV rows set aside because their window shares no free day with the range.
    windows_skipped: int = 0

    @property
    def total(self) -> Decimal:
        return sum((c.total for c in self.campaigns.values()), ZERO)

    @property
    def connector_total(self) -> Decimal:
        return sum((c.connector for c in self.campaigns.values()), ZERO)

    @property
    def csv_total(self) -> Decimal:
        return sum((c.csv for c in self.campaigns.values()), ZERO)

    @property
    def unattributed(self) -> Decimal:
        """Spend no product row accounts for ("QC không gắn sản phẩm")."""
        return self.total - sum(self.products.values(), ZERO)

    @property
    def prorated(self) -> bool:
        return any(c.prorated for c in self.campaigns.values())


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _single_basis(figures: Iterable[AdDay | AdWindow]) -> str:
    bases = {f.order_basis for f in figures}
    if len(bases) > 1:
        raise OrderBasisError(f"ads figures of different order bases: {sorted(bases)}")
    return bases.pop() if bases else BASIS_PLACED


def resolve_ad_spend(
    days: Iterable[AdDay],
    windows: Iterable[AdWindow],
    start: date,
    end: date,
    *,
    covered_days: Iterable[date] | None = None,
) -> AdSpendResult:
    """Spend over ``start..end`` (inclusive): Connector days first, CSV windows for the rest.

    ``covered_days`` are the days the Connector read (default: the days of ``days``). A day it
    read with no row for a campaign means that campaign spent nothing, so the CSV is not asked.
    """
    daily = [d for d in days if start <= d.day <= end]
    wins = list(windows)
    basis = _single_basis([*daily, *wins])
    covered = {d for d in (covered_days if covered_days is not None else (x.day for x in daily))}
    covered = {d for d in covered if start <= d <= end}
    result = AdSpendResult(start, end, basis, len(covered))

    for d in daily:
        slot = result.campaigns.setdefault(campaign_key(d.campaign), CampaignSpend())
        slot.connector += d.spend

    free = {d for d in _days(start, end) if d not in covered}
    by_campaign: dict[str, dict[tuple[date, date], list[AdWindow]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for w in wins:
        by_campaign[campaign_key(w.campaign)][(w.start, w.end)].append(w)

    for key, by_window in by_campaign.items():
        assigned: set[date] = set()
        # Newest window first: it answers the days it covers, an older overlapping one the rest.
        for (w_start, w_end), rows in sorted(by_window.items(), key=lambda kv: kv[0], reverse=True):
            span = _days(w_start, w_end)
            mine = {d for d in span if d in free and d not in assigned}
            if not mine:
                result.windows_skipped += len(rows)
                continue
            assigned |= mine
            share = Decimal(len(mine)) / Decimal(len(span))
            slot = result.campaigns.setdefault(key, CampaignSpend())
            slot.prorated = slot.prorated or share != 1
            for row in rows:
                part = row.spend * share
                slot.csv += part
                if row.item_id:
                    result.products[row.item_id] = result.products.get(row.item_id, ZERO) + part
    return result


@dataclass(frozen=True)
class Figure:
    """A number with the order basis it was counted on."""

    value: Decimal
    order_basis: str


def confirmed_total(figures: Iterable[Figure]) -> Decimal:
    """Add figures into a CONFIRMED total; any other basis (an ads figure) raises (D-2)."""
    total = ZERO
    for f in figures:
        if f.order_basis != BASIS_CONFIRMED:
            raise OrderBasisError(f"a {f.order_basis} figure cannot be added to a confirmed total")
        total += f.value
    return total
