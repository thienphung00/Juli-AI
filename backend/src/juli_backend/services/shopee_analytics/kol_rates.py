"""The commission rate that applies to a product (P91 D-9).

Order of authority for ONE affiliate order line (``resolve_line_commission``):

1. ``report``  -- the line's ``Chi phí(₫)`` from the SellerConversionReport, when present
   (``ingest/affiliate_commission`` states why that column).
2. ``targeted`` -- the product's rate in a targeted campaign (``affiliate_campaign_terms``:
   a one-day snapshot of ``Tỉ lệ hoa hồng`` per campaign x product). The snapshot nearest
   before the order day is used (else the earliest after it); among several running campaigns
   of the product the highest rate (the conservative cost). The names of the targeted KOLs are
   not stored, so a targeted rate is an upper estimate for a KOL who is not on the list.
3. ``open`` -- the open-campaign rate, derived as ``Hoa hồng ước tính ÷ Doanh thu`` of the
   product in ``affiliate_open_campaign_period`` (else ``affiliate_product_period``).

The line's campaign type picks which of 2 / 3 is tried first: an open campaign
(``Chiến dịch mở rộng`` / ``Open``) tries ``open`` first, anything else ``targeted`` first.

Applied to the line's COMMISSION BASE: ``OrderLine.buyer_paid`` = deal price x qty - shop voucher
share - combo discount, i.e. the order value after the shop's own discounts, shipping excluded
(``shopee_order_lines``; platform-funded discounts are not deducted). ``None`` when no rate is
known: the line then carries no profit figure and is counted in ``commission_missing_lines``.
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import PlatformPeriodMetricsRepo
from juli_backend.services.shopee_profit.money import ZERO, safe_div, to_dong

FAR_PAST = date(2000, 1, 1)
FAR_FUTURE = date(2099, 12, 31)
SRC_REPORT = "report"
SRC_TARGETED = "targeted"
SRC_OPEN = "open"
SRC_NONE = "none"
SOURCE_LABELS = {
    SRC_REPORT: "Hoa hồng thực tế trong báo cáo đơn liên kết",
    SRC_TARGETED: "Mức hoa hồng chiến dịch chỉ định của sản phẩm",
    SRC_OPEN: "Mức hoa hồng chiến dịch mở của sản phẩm",
    SRC_NONE: "Chưa biết mức hoa hồng",
}
_OPEN_WORDS = ("mở rộng", "mo rong", "open")
#: The Connector posts the conversion report's campaign type as a code: "5" = Seller Open
#: Campaign (checked in Seller Centre on ORY, 2026-11-13).
_OPEN_CODES = frozenset({"5"})


def _ymd(value: Any) -> date | None:
    try:
        n = int(value)
        return date(n // 10000, n // 100 % 100, n % 100)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TermsRow:
    day: date
    rate: Decimal
    running: bool
    campaign: str


@dataclass
class RateBook:
    """Per item: targeted-campaign snapshots (sorted by day) and the open-campaign rate."""

    targeted: dict[str, list[TermsRow]] = field(default_factory=dict)
    open_rate: dict[str, Decimal] = field(default_factory=dict)

    def targeted_rate(self, item_id: str, on: date | None = None) -> Decimal | None:
        rows = self.targeted.get(item_id)
        if not rows:
            return None
        days = [r.day for r in rows]
        if on is None:
            day = days[-1]
        else:
            i = bisect_right(days, on)
            day = days[i - 1] if i else days[0]
        snap = [r for r in rows if r.day == day]
        running = [r for r in snap if r.running] or snap
        return max(r.rate for r in running)

    def rate(
        self, item_id: str, on: date | None = None, campaign_type: str | None = None
    ) -> tuple[Decimal | None, str]:
        """``(rate, source)`` with the order of authority above (without the report)."""
        kind = (campaign_type or "").strip()
        open_first = kind in _OPEN_CODES or any(w in kind.casefold() for w in _OPEN_WORDS)
        order = (SRC_OPEN, SRC_TARGETED) if open_first else (SRC_TARGETED, SRC_OPEN)
        for src in order:
            r = (
                self.targeted_rate(item_id, on)
                if src == SRC_TARGETED
                else self.open_rate.get(item_id)
            )
            if r is not None:
                return r, src
        return None, SRC_NONE

    def current(self, item_id: str) -> tuple[Decimal | None, str]:
        """The product's rate today (forecasts use it): targeted snapshot newest, else open."""
        return self.rate(item_id, None, None)


def resolve_line_commission(
    *,
    reported: Decimal | None,
    base: Decimal,
    item_id: str,
    on: date,
    campaign_type: str | None,
    book: RateBook,
) -> tuple[Decimal | None, str]:
    """``(commission, source)`` of one affiliate line; ``(None, 'none')`` when unknown."""
    if reported is not None:
        return reported, SRC_REPORT
    rate, src = book.rate(item_id, on, campaign_type)
    if rate is None:
        return None, SRC_NONE
    return to_dong(base * rate), src


async def load_rate_book(session: AsyncSession, shop_id: uuid.UUID) -> RateBook:
    repo = PlatformPeriodMetricsRepo(session)
    rows = await repo.overlapping(
        shop_id,
        datasets=[
            "affiliate_campaign_terms",
            "affiliate_open_campaign_period",
            "affiliate_product_period",
        ],
        start=FAR_PAST,
        end=FAR_FUTURE,
        any_item=True,
    )
    book = RateBook()
    for r in rows:
        if r.dataset != "affiliate_campaign_terms" or not r.item_id:
            continue
        rate = (r.extra or {}).get("commission_rate")
        if rate is None:
            continue
        book.targeted.setdefault(r.item_id, []).append(
            TermsRow(
                r.period_start,
                Decimal(str(rate)),
                bool((r.extra or {}).get("running", True)),
                r.platform_source or "",
            )
        )
    for rows_ in book.targeted.values():
        rows_.sort(key=lambda t: t.day)
    for dataset in ("affiliate_product_period", "affiliate_open_campaign_period"):
        newest: dict[str, Any] = {}
        for r in rows:
            if r.dataset == dataset and r.item_id:
                if r.item_id not in newest or r.period_end >= newest[r.item_id].period_end:
                    newest[r.item_id] = r
        for item_id, r in newest.items():
            est = (r.extra or {}).get("est_commission")
            gmv = Decimal(str(r.gmv)) if r.gmv is not None else ZERO
            if est is not None and gmv > 0:
                rate = safe_div(Decimal(str(est)), gmv)
                if rate is not None and 0 < rate <= 1:
                    book.open_rate[item_id] = rate  # the open-campaign export wins (loaded last)
    return book
