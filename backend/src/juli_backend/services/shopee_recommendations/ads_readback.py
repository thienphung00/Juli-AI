"""Read-back of a new ads campaign card (``ads_new_campaign``, P99b; ADR-122 d.8).

Juli never writes to Shopee Ads. The owner creates the campaign by hand in Seller Centre; Juli
finds it in the ingested ads data and reads its real spend / GMV / orders for the card.

Matching (pure, :func:`match_card`): the Connector's ``ads_campaign_daily`` rows give one finished
day per campaign (``segment`` = the campaign, ``platform_source`` = its title); the CSV
``ads_campaign_period`` rows give campaign x product (same title). A campaign matches a card by

1. its exact name (whitespace / case / accents-width normalised, ``ads_sources.campaign_key``), else
2. the same product set and a first day within one day of the card's start date.

Two campaigns fit a step, or two cards fit one campaign -> ``ambiguous``: no match, with a reason.
No campaign fits -> ``not_found`` ("chưa thấy chiến dịch trên Shopee"), never zero results.

Reading (:func:`read_actual`): spend / GMV / orders of THAT campaign's own day rows from the
card's start to its end (or yesterday). Unknown is ``None`` with a reason, never 0 (a campaign
with no day row, a day row without a cost). Money is the ad's own attribution of PLACED orders.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_EXECUTED,
    STATUS_MEASURED,
    STATUS_PLANNED,
    STATUS_SENT,
)
from juli_backend.repositories import PlatformDailyMetricsRepo, PlatformPeriodMetricsRepo
from juli_backend.services.shopee_profit.ads_sources import BASIS_PLACED, campaign_key
from juli_backend.services.shopee_recommendations import store

KIND = "ads_new_campaign"
ADS_DAILY = "ads_campaign_daily"
ADS_PERIOD = "ads_campaign_period"
START_TOLERANCE_DAYS = 1
#: How far before the card's start a campaign's day rows are looked at: a campaign with rows
#: before the start existed before the card (so it is not the one the owner just created).
LOOKBACK_DAYS = 30

STATE_MATCHED = "matched"
STATE_NOT_FOUND = "not_found"
STATE_AMBIGUOUS = "ambiguous"

MATCH_NAME = "name"
MATCH_PRODUCTS_START = "products_start"

LABELS = {
    STATE_MATCHED: "Đã thấy chiến dịch trên Shopee",
    STATE_NOT_FOUND: "chưa thấy chiến dịch trên Shopee",
    STATE_AMBIGUOUS: "Có nhiều chiến dịch khớp, chưa xác định được chiến dịch của thẻ này",
}
REASONS = {
    "no_ads_data": "Chưa có số liệu quảng cáo nào từ Shopee để đối chiếu.",
    "no_campaign_fits": "Không có chiến dịch nào trùng tên, hoặc cùng sản phẩm và ngày bắt đầu.",
    "same_name_many": "Có nhiều chiến dịch cùng tên này trên Shopee.",
    "same_products_many": "Có nhiều chiến dịch cùng sản phẩm và ngày bắt đầu.",
    "campaign_matches_other_card": "Chiến dịch này cũng khớp một thẻ khác trong kế hoạch.",
    "card_without_start": "Thẻ chưa có ngày bắt đầu và tên để đối chiếu.",
}
NO_DAY_ROWS = "Chưa có số liệu theo ngày của chiến dịch này."
NO_COST = "Thiếu chi phí của một số ngày."
NO_GMV = "Thiếu doanh số của một số ngày."
NO_ORDERS = "Thiếu số đơn của một số ngày."
NOT_STARTED = "Chiến dịch chưa chạy xong ngày nào."


@dataclass(frozen=True)
class CampaignSeen:
    """One campaign as the ingested ads data shows it."""

    segment: str
    name: str
    key: str
    first_day: date | None
    items: frozenset[str]


@dataclass
class DayRow:
    day: date
    spend: float | None
    gmv: float | None
    orders: float | None


@dataclass
class AdsMatch:
    state: str
    reason: str | None = None
    matched_by: str | None = None
    campaign: CampaignSeen | None = None
    candidates: list[CampaignSeen] = field(default_factory=list)
    started_before_card: bool = False

    def json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "state": self.state,
            "label": LABELS[self.state],
            "reason": self.reason,
            "reason_text": REASONS.get(self.reason or ""),
            "matched_by": self.matched_by,
            "campaign": None,
            "candidates": [c.name for c in self.candidates],
            "started_before_card": self.started_before_card,
        }
        if self.campaign is not None:
            out["campaign"] = {
                "name": self.campaign.name,
                "segment": self.campaign.segment,
                "first_day": self.campaign.first_day.isoformat()
                if self.campaign.first_day
                else None,
                "item_ids": sorted(self.campaign.items),
            }
        return out


# ------------------------------------------------------------------ pure side


def card_start(card: Mapping[str, Any]) -> date | None:
    raw = (card.get("inputs") or {}).get("start")
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def card_end(card: Mapping[str, Any]) -> date | None:
    """The last planned day: the spec's ``end``, else start + days - 1."""
    inputs = card.get("inputs") or {}
    start = card_start(card)
    raw = inputs.get("end")
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    days = inputs.get("days")
    if start is not None and isinstance(days, int) and days > 0:
        return start + timedelta(days=days - 1)
    return None


def campaigns_seen(daily: Iterable[Any], periods: Iterable[Any]) -> list[CampaignSeen]:
    """Campaigns from day rows (one per ``segment``) joined to their products by name key."""
    names: dict[str, str] = {}
    first: dict[str, date] = {}
    for r in daily:
        if r.segment == "all" or not r.platform_source:
            continue
        names[r.segment] = r.platform_source
        if r.day is not None and (r.segment not in first or r.day < first[r.segment]):
            first[r.segment] = r.day
    items: dict[str, set[str]] = defaultdict(set)
    for p in periods:
        if p.item_id and p.platform_source:
            items[campaign_key(p.platform_source)].add(p.item_id)
    seen = [
        CampaignSeen(
            seg, name, campaign_key(name), first.get(seg), frozenset(items[campaign_key(name)])
        )
        for seg, name in names.items()
    ]
    return sorted(seen, key=lambda c: (c.key, c.segment))


def match_card(card: Mapping[str, Any], seen: Sequence[CampaignSeen]) -> AdsMatch:
    """Which campaign is this card's: exact name first, else same products and start +-1 day."""
    if not seen:
        return AdsMatch(STATE_NOT_FOUND, "no_ads_data")
    inputs = card.get("inputs") or {}
    name_key = campaign_key(inputs.get("name"))
    start = card_start(card)
    if not name_key and start is None:
        return AdsMatch(STATE_NOT_FOUND, "card_without_start")
    if name_key:
        named = [c for c in seen if c.key == name_key]
        if len(named) > 1:
            return AdsMatch(STATE_AMBIGUOUS, "same_name_many", candidates=named)
        if named:
            c = named[0]
            before = bool(
                start and c.first_day and c.first_day < start - timedelta(days=START_TOLERANCE_DAYS)
            )
            return AdsMatch(
                STATE_MATCHED, matched_by=MATCH_NAME, campaign=c, started_before_card=before
            )
    items = frozenset(str(i) for i in (card.get("scope") or {}).get("product_ids") or [])
    if items and start is not None:
        fits = [
            c
            for c in seen
            if c.items == items
            and c.first_day is not None
            and abs((c.first_day - start).days) <= START_TOLERANCE_DAYS
        ]
        if len(fits) > 1:
            return AdsMatch(STATE_AMBIGUOUS, "same_products_many", candidates=fits)
        if fits:
            return AdsMatch(STATE_MATCHED, matched_by=MATCH_PRODUCTS_START, campaign=fits[0])
    return AdsMatch(STATE_NOT_FOUND, "no_campaign_fits")


def match_cards(
    cards: Mapping[str, Mapping[str, Any]], seen: Sequence[CampaignSeen]
) -> dict[str, AdsMatch]:
    """:func:`match_card` for every card of a plan; one campaign claimed by two cards makes both
    ambiguous (a match must never be shared)."""
    out = {cid: match_card(card, seen) for cid, card in cards.items()}
    claims: dict[str, list[str]] = defaultdict(list)
    for cid, m in out.items():
        if m.state == STATE_MATCHED and m.campaign is not None:
            claims[m.campaign.segment].append(cid)
    for cids in claims.values():
        if len(cids) > 1:
            for cid in cids:
                shared = out[cid].campaign
                out[cid] = AdsMatch(
                    STATE_AMBIGUOUS,
                    "campaign_matches_other_card",
                    candidates=[shared] if shared else [],
                )
    return out


def read_actual(rows: Sequence[DayRow], first: date, last: date, yesterday: date) -> dict[str, Any]:
    """The campaign's own spend / GMV / orders over ``first..min(last, yesterday)``.

    A figure is ``None`` (with its reason in ``reasons``) when no day row exists or one of the
    days it sums lacks that field -- never a 0 standing for "unknown". ``days_covered`` counts
    the days with a row; a gap is stated, the covered days are still summed."""
    stop = min(last, yesterday)
    reasons: dict[str, str] = {}
    base: dict[str, Any] = {
        "basis": BASIS_PLACED,
        "from": first.isoformat(),
        "to": stop.isoformat() if stop >= first else None,
        "reasons": reasons,
    }
    if stop < first:
        reasons.update(spend=NOT_STARTED, gmv=NOT_STARTED, orders=NOT_STARTED)
        return {**base, "spend": None, "gmv": None, "orders": None, "roas": None,
                "days_covered": 0, "days_expected": 0}  # fmt: skip
    expected = (stop - first).days + 1
    inside = [r for r in rows if first <= r.day <= stop]
    base.update(days_covered=len(inside), days_expected=expected)
    if not inside:
        reasons.update(spend=NO_DAY_ROWS, gmv=NO_DAY_ROWS, orders=NO_DAY_ROWS)
        return {**base, "spend": None, "gmv": None, "orders": None, "roas": None}

    def total(attr: str, why: str) -> float | None:
        vals = [getattr(r, attr) for r in inside]
        if any(v is None for v in vals):
            reasons[attr] = why
            return None
        return float(sum(vals))

    spend = total("spend", NO_COST)
    gmv = total("gmv", NO_GMV)
    orders = total("orders", NO_ORDERS)
    roas = gmv / spend if gmv is not None and spend else None
    if roas is None and "roas" not in reasons and (spend is None or gmv is None or not spend):
        reasons["roas"] = "Chưa đủ chi phí và doanh số để tính ROAS." if spend != 0 else "Chưa chi."
    if len(inside) < expected:
        reasons["coverage"] = f"Có số liệu {len(inside)}/{expected} ngày."
    return {**base, "spend": spend, "gmv": gmv, "orders": orders, "roas": roas}


# ------------------------------------------------------------------ DB side


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


async def _load(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> tuple[list[Any], list[Any]]:
    daily = await PlatformDailyMetricsRepo(session).window(
        shop_id, datasets=[ADS_DAILY], start=first, end=last, streams=["ads"], any_item=True
    )
    periods = await PlatformPeriodMetricsRepo(session).overlapping(
        shop_id, datasets=[ADS_PERIOD], start=first, end=last, order_types=["placed"]
    )
    return list(daily), list(periods)


def _day_rows(daily: Iterable[Any], segment: str) -> list[DayRow]:
    by_day: dict[date, DayRow] = {}
    for r in daily:
        if r.segment != segment or r.day is None:
            continue
        cost = (r.extra or {}).get("cost")
        by_day[r.day] = DayRow(r.day, _f(cost), _f(r.gmv), _f(r.orders))
    return list(by_day.values())


async def readback_cards(
    session: AsyncSession,
    shop_id: uuid.UUID,
    cards: Mapping[str, Mapping[str, Any]],
    today: date,
) -> dict[str, dict[str, Any]]:
    """For each ``ads_new_campaign`` card (id -> card payload): the match and, once matched,
    the campaign's real figures. Other kinds are left out."""
    mine = {cid: c for cid, c in cards.items() if c.get("change_kind") == KIND}
    if not mine:
        return {}
    starts = [s for s in (card_start(c) for c in mine.values()) if s is not None]
    first = (min(starts) if starts else today) - timedelta(days=LOOKBACK_DAYS)
    daily, periods = await _load(session, shop_id, first, today)
    seen = campaigns_seen(daily, periods)
    matches = match_cards(mine, seen)
    yesterday = today - timedelta(days=1)
    out: dict[str, dict[str, Any]] = {}
    for cid, card in mine.items():
        m = matches[cid]
        entry = m.json()
        entry["actual"] = None
        start = card_start(card)
        if m.state == STATE_MATCHED and m.campaign is not None and start is not None:
            last = card_end(card) or yesterday
            entry["actual"] = read_actual(
                _day_rows(daily, m.campaign.segment), start, last, yesterday
            )
        out[cid] = entry
    return out


_LIVE = (
    STATUS_DRAFT,
    STATUS_SENT,
    STATUS_APPROVED,
    STATUS_PLANNED,
    STATUS_EXECUTED,
    STATUS_MEASURED,
)


async def refresh_shop(session: AsyncSession, shop_id: uuid.UUID, today: date) -> int:
    """Read every live ``ads_new_campaign`` card of the shop and keep the result in the card's
    metadata (``ads_readback``) where the plan reads card state. Returns the cards refreshed."""
    cards = {
        str(p.id): card
        for p, card in await store.list_cards(session, shop_id, statuses=list(_LIVE))
        if card.get("change_kind") == KIND
    }
    results = await readback_cards(session, shop_id, cards, today)
    for cid, result in results.items():
        await store.set_meta(session, shop_id, uuid.UUID(cid), {"ads_readback": result})
    return len(results)
