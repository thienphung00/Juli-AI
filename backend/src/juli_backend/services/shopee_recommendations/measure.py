"""Readings at the plan end and the calibration job (ADR-121 d.4), plus the one-off
natural-experiment backfill (d.5).

DB side: daily series per product (and per campaign) from the stored Shopee data, the verified
time of each execution from ``card_events``, the frozen prediction from the `proposed` payload.
Pure side: :mod:`.impact` (ADR-077 DiD), :mod:`.learning` (calibration math).

Nothing here changes a card or a proposal's text; it appends `impact_final` events and rewrites
the shop's own calibration rows. No row of ORY ever reaches another shop's calibration.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_events import (
    ACTOR_SYSTEM,
    EVENT_EXECUTED,
    EVENT_IMPACT_FINAL,
    EVENT_IMPACT_PRELIMINARY,
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.shop_proposals import STATUS_EXECUTED
from juli_backend.models.shopee_plans import PLAN_EXECUTED, ShopRecoChangeSet, ShopRecoPlan
from juli_backend.models.shopee_profit import AdsChangeLog
from juli_backend.repositories import (
    PlatformDailyMetricsRepo,
    PlatformPromotionsRepo,
    ShopeeOrderLinesRepo,
)
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.shopee_recommendations import (
    ads_readback,
    change_sets,
    config,
    impact,
    learning,
    product_queue,
    result_store,
    store,
)
from juli_backend.services.shopee_recommendations.kinds import KINDS, spec
from juli_backend.services.shopee_recommendations.learning import Observation
from juli_backend.services.shopee_recommendations.prediction import factor_from, prior_range

ITEM_DAILY = ("item_traffic_sources", "item_by_source")
ADS_DAILY = "ads_campaign_daily"
STREAMS = ("product_card", "seller_live", "seller_video", "affiliate")
MEASURABLE = ("ctr", "ctor", "views", "orders", "aov", "ads_gmv", "roas", "gmv")


@dataclass
class DayAgg:
    views: float = 0.0
    clicks: float = 0.0
    orders: float = 0.0
    gmv: float = 0.0
    spend: float = 0.0

    def value(self, metric: str) -> float | None:
        if metric == "ctr":
            return self.clicks / self.views if self.views else None
        if metric == "ctor":
            return self.orders / self.clicks if self.clicks else None
        if metric == "views":
            return self.views
        if metric == "orders":
            return self.orders
        if metric == "aov":
            return self.gmv / self.orders if self.orders else None
        if metric in ("ads_gmv", "gmv"):
            return self.gmv
        if metric == "roas":
            return self.gmv / self.spend if self.spend else None
        return None


def series_of(
    days: Mapping[date, DayAgg], metric: str, first: date, last: date
) -> dict[date, float]:
    """Daily values over ``[first, last]``; a day without a value is left out for rates and is
    0 for counts (a covered day with no traffic is a day with 0)."""
    out: dict[date, float] = {}
    d = first
    count = metric in ("views", "orders", "ads_gmv", "gmv")
    while d <= last:
        agg = days.get(d)
        v = None if agg is None else agg.value(metric)
        if v is not None:
            out[d] = v
        elif count:
            out[d] = 0.0
        d += timedelta(days=1)
    return out


async def load_item_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    first: date,
    last: date,
    catalog: Catalog | None = None,
) -> dict[str, dict[date, DayAgg]]:
    """Per product per day: views / clicks from the connector's item x source day rows, orders
    and GMV from the order lines (confirmed = paid)."""
    out: dict[str, dict[date, DayAgg]] = defaultdict(lambda: defaultdict(DayAgg))
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=ITEM_DAILY,
        start=first,
        end=last,
        streams=STREAMS,
        order_types=["confirmed"],
        any_item=True,
    )
    for r in rows:
        if r.item_id and r.segment == "all":
            a = out[r.item_id][r.day]
            a.views += float(r.impressions or 0)
            a.clicks += float(r.clicks or 0)
    if catalog is None:
        catalog = (await loaders.load_context(session, shop_id)).catalog
    lines = await ShopeeOrderLinesRepo(session).in_window(shop_id, first, last)
    seen: dict[tuple[str, date], set[str]] = defaultdict(set)
    for ln in lines:
        if ln.paid_at is None:
            continue
        item = catalog.resolve(ln.item_id, ln.sku, ln.variation_sku)
        if not item or item.startswith("sku:"):
            continue
        d = ln.ordered_at.date()
        a = out[item][d]
        a.gmv += float(ln.deal_price * ln.qty)
        key = (item, d)
        if ln.order_ref not in seen[key]:
            seen[key].add(ln.order_ref)
            a.orders += 1
    return out


async def load_campaign_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> dict[str, dict[date, DayAgg]]:
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id, datasets=[ADS_DAILY], start=first, end=last, any_item=True
    )
    out: dict[str, dict[date, DayAgg]] = defaultdict(lambda: defaultdict(DayAgg))
    for r in rows:
        if r.segment == "all":
            continue
        extra = r.extra or {}
        a = out[r.segment][r.day]
        a.views += float(r.impressions or 0)
        a.clicks += float(r.clicks or 0)
        a.orders += float(r.orders or 0)
        a.gmv += float(extra.get("direct_gmv") or r.gmv or 0)
        a.spend += float(extra.get("cost") or extra.get("ads_expense") or 0)
    return out


async def load_shop_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> dict[date, DayAgg]:
    """The shop's confirmed orders and Doanh số per day (Shopee's own daily overview)."""
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id, datasets=["shop_overview"], start=first, end=last, order_types=["confirmed"]
    )
    out: dict[date, DayAgg] = {}
    for r in rows:
        if r.stream == "total" and r.segment == "all":
            a = out.setdefault(r.day, DayAgg())
            a.orders = float(r.orders or 0)
            a.gmv = float(r.gmv or 0)
    return out


async def load_traffic_controls(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> dict[str, dict[date, float]]:
    """Traffic series a voucher / price change should not move much: shop visitors (overview and
    traffic, all / app / pc) and the product cards' impressions. A reading of orders against
    them is orders per unit of traffic (a conversion), not seasonality."""
    repo = PlatformDailyMetricsRepo(session)
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for r in await repo.window(
        shop_id, datasets=["shop_overview"], start=first, end=last, order_types=["confirmed"]
    ):
        if r.stream == "total" and r.segment == "all" and r.visitors is not None:
            out["visitors_overview"][r.day] = float(r.visitors)
    for r in await repo.window(shop_id, datasets=["shop_traffic"], start=first, end=last):
        if r.stream == "total" and r.visitors is not None:
            out[f"visitors_{r.segment}"][r.day] = float(r.visitors)
    for r in await repo.window(
        shop_id, datasets=["traffic_overview"], start=first, end=last, order_types=["confirmed"]
    ):
        if r.stream == "product_card" and r.segment == "all" and r.impressions is not None:
            out["impressions_card"][r.day] = float(r.impressions)
    return dict(out)


# ------------------------------------------------------------------ cards at plan end


@dataclass
class LearningReport:
    cards_considered: int = 0
    readings: int = 0
    preliminary: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    observations_total: int = 0
    states: int = 0

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def json(self) -> dict[str, Any]:
        return {
            "cards_considered": self.cards_considered,
            "readings": self.readings,
            "preliminary": self.preliminary,
            "skipped": self.skipped,
            "observations_total": self.observations_total,
            "calibration_rows": self.states,
        }


async def verified_time(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID
) -> tuple[datetime | None, str]:
    """When the clock starts: the first `verified` event of the card (all of its executions
    verified -> the latest of them); kinds without a read-back start at `executed`."""
    ver = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.shop_id == shop_id,
                CardEvent.card_id == card_id,
                CardEvent.event_type == EVENT_VERIFIED,
            )
        )
    ).all()
    exe = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.shop_id == shop_id,
                CardEvent.card_id == card_id,
                CardEvent.event_type == EVENT_EXECUTED,
            )
        )
    ).all()
    if not exe:
        return None, "not_executed"
    readable = [
        e
        for e in exe
        if (e.payload or {}).get("change", {}).get("change_kind")
        in ("title", "price", "images", "stock", "daily_budget", "roas_target", "voucher")
    ]
    if readable:
        if len(ver) < len(readable):
            return None, "awaiting_verification"
        return max(v.occurred_at for v in ver).replace(tzinfo=None), "verified"
    return min(e.occurred_at for e in exe).replace(tzinfo=None), "executed_no_readback"


#: The first look at a running change, shown as "sơ bộ" until the plan ends (same shape as final).
PRELIMINARY_DAYS = 7


def _lift_range(card: Mapping[str, Any]) -> tuple[float, float]:
    """The predicted range of the card's metric the reading is judged against: the stored result
    band (one card, one number; the approval-time result when kept). A card whose result does
    not know its metric (ads metrics, not estimable) keeps the prediction's lift."""
    band = result_store.metric_band(
        result_store.measured_block(card), (card.get("metric") or {}).get("key") or ""
    )
    if band is not None:
        return band["p10"], band["p90"]
    lift = card["predicted"]["lift"]["lift"]
    return float(lift["p10"]), float(lift["p90"])


@dataclass
class CardReading:
    """One card's reading: the scored observation (None when it feeds no calibration) and what
    was read, for the change set's result."""

    observation: Observation | None = None
    reading: impact.Reading | None = None
    post_days: int | None = None
    skipped: str | None = None
    stacked: bool = False


async def _read_card(
    session: AsyncSession,
    shop_id: uuid.UUID,
    p: Any,
    card: dict[str, Any],
    today: date,
    report: LearningReport,
    *,
    plan_days: int | None,
    extra_bundle: bool = False,
    partial: bool = False,
    change_set: str | None = None,
) -> CardReading:
    """The preliminary (T+7) and final reading of one executed card.

    ``plan_days`` is the window (the change set's, P91 D-8; for a card from before change sets, its
    own measurement plan). ``partial``: the measurement was cut, the window is the days it ran;
    the reading is written but never calibrates. ``extra_bundle``: the card ran with a
    shop-wide change (``kèm thay đổi toàn shop``) -- read, flagged, not calibrated per kind."""
    report.cards_considered += 1
    metric = card["metric"]["key"]
    if card.get("change_kind") == ads_readback.KIND:  # read back from the ads data, not a DiD
        report.skip("ads_readback")
        return CardReading(skipped="ads_readback")
    if plan_days is None:
        report.skip("khong_ket_luan")
        return CardReading(skipped="khong_ket_luan")
    if metric not in MEASURABLE:
        report.skip("metric_not_measurable")
        return CardReading(skipped="metric_not_measurable")
    t_at, how = await verified_time(session, shop_id, p.id)
    if t_at is None:
        report.skip(how)
        return CardReading(skipped=how)
    t = t_at.date()
    final_due = today >= t + timedelta(days=plan_days + 1)
    prelim_due = (
        not partial
        and plan_days > PRELIMINARY_DAYS
        and today >= t + timedelta(days=PRELIMINARY_DAYS + 1)
    )
    if not final_due and not prelim_due:
        report.skip("plan_not_ended")
        return CardReading(skipped="plan_not_ended")
    span = plan_days if final_due else PRELIMINARY_DAYS
    first, last = t - timedelta(days=impact.PRE_DAYS + 1), t + timedelta(days=span)
    items = card["scope"]["product_ids"]
    if metric in ("ads_gmv", "roas"):
        data = await load_campaign_days(session, shop_id, first, last)
        key = card["scope"].get("campaign_key")
        treated_days = data.get(key or "")
        controls = {k: series_of(v, metric, first, last) for k, v in data.items() if k != key}
    else:
        data = await load_item_days(session, shop_id, first, last)
        treated_days = (
            _sum_days([data.get(i, {}) for i in items]) if items else _sum_days(list(data.values()))
        )
        controls = {k: series_of(v, metric, first, last) for k, v in data.items() if k not in items}
    if not treated_days:
        report.skip("no_series")
        return CardReading(skipped="no_series")
    excluded = await executed_days_other(session, shop_id, p.id, first, last)
    stacked = extra_bundle or await stacked_with_other(
        session, shop_id, p.id, items, t, t + timedelta(days=plan_days)
    )

    async def write(event_type: str, reading: impact.Reading, days: int) -> None:
        await store.write_event(
            session,
            shop_id,
            p.id,
            event_type=event_type,
            actor=ACTOR_SYSTEM,
            occurred_at=datetime.combine(t + timedelta(days=days), datetime.min.time()),
            dedup_key=f"{event_type}:{p.id}",
            code=p.code,
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=("item", items[0]) if items else ("shop", str(p.id)),
            payload={
                "method": "adr077_ratio_did",
                "confidence": reading.confidence,
                "reason": reading.reason,
                "impact_pct": reading.impact_pct,
                "se_rel": reading.se_rel,
                "controls": list(reading.controls),
                "clock": how,
                "bundle": bool(card.get("bundle")) or stacked,
                "post_days": days,
                "preliminary": event_type == EVENT_IMPACT_PRELIMINARY,
                "partial": partial,
                "change_set": change_set,
            },
        )

    if prelim_due:
        early = impact.read_effect(
            series_of(treated_days, metric, first, last),
            controls,
            t,
            post_days=PRELIMINARY_DAYS,
            excluded=excluded,
        )
        await write(EVENT_IMPACT_PRELIMINARY, early, PRELIMINARY_DAYS)
        report.preliminary += 1
    if not final_due:
        return CardReading(reading=None, post_days=None, skipped="plan_not_ended", stacked=stacked)
    reading = impact.read_effect(
        series_of(treated_days, metric, first, last),
        controls,
        t,
        post_days=plan_days,
        excluded=excluded,
    )
    await write(EVENT_IMPACT_FINAL, reading, plan_days)
    if partial:  # a cut measurement is shown ("đo được N ngày"), never calibrated
        return CardReading(None, reading, plan_days, stacked=stacked)
    if reading.impact_pct is None or reading.confidence == "suppressed":
        report.skip(f"reading_{reading.reason}")
        return CardReading(None, reading, plan_days, f"reading_{reading.reason}", stacked)
    lo, hi = _lift_range(card)
    obs = Observation(
        card["change_kind"],
        metric,
        lo,
        hi,
        reading.impact_pct,
        reading.se_rel,
        "card",
        bool(card.get("bundle")) or stacked,
        str(p.id),
        not reading.fallback,
        str(card.get("origin") or "engine"),
    )
    report.readings += 1
    return CardReading(obs, reading, plan_days, stacked=stacked)


async def read_cards(
    session: AsyncSession, shop_id: uuid.UUID, today: date, report: LearningReport
) -> list[Observation]:
    """Final readings of executed cards whose plan has ended -- the cards executed before change
    sets existed (they carry no ``change_set``); every other card is read with its change set
    (:func:`read_change_sets`)."""
    out: list[Observation] = []
    for p, card in await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED]):
        meta = await store.card_meta(session, shop_id, p.id)
        if meta.get("change_set"):
            continue
        got = await _read_card(
            session,
            shop_id,
            p,
            card,
            today,
            report,
            plan_days=meta.get("window_days") or card["measurement_plan"]["planned_days"],
        )
        if got.observation is not None:
            out.append(got.observation)
    return out


def _reading_json(reading: impact.Reading | None, post_days: int | None) -> dict[str, Any]:
    if reading is None:
        return {}
    return {
        "impact_pct": reading.impact_pct,
        "confidence": reading.confidence,
        "reason": reading.reason,
        "se_rel": reading.se_rel,
        "post_days": post_days,
    }


def _in_range(measured: float | None, lo: float | None, hi: float | None) -> bool | None:
    if measured is None or lo is None or hi is None:
        return None
    a, b = sorted((lo, hi))
    return a <= measured <= b


async def _set_cards(
    session: AsyncSession, shop_id: uuid.UUID, cs: ShopRecoChangeSet
) -> list[tuple[Any, dict[str, Any]]]:
    wanted = {str(i) for i in cs.card_ids or []}
    return [
        (p, card)
        for p, card in await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED])
        if str(p.id) in wanted
    ]


async def _set_clock(
    session: AsyncSession, shop_id: uuid.UUID, cards: list[tuple[Any, dict[str, Any]]]
) -> tuple[date | None, str]:
    """The set's clock starts when ALL its cards are verified (the latest of them)."""
    days: list[date] = []
    how = "verified"
    for p, _ in cards:
        t_at, h = await verified_time(session, shop_id, p.id)
        if t_at is None:
            return None, h
        days.append(t_at.date())
        how = h
    return (max(days) if days else None), how


async def read_change_sets(
    session: AsyncSession, shop_id: uuid.UUID, today: date, report: LearningReport
) -> list[Observation]:
    """Read every change set that is due (P91 D-7). Returns the observations to calibrate with:

    - a one-card set calibrates its change_kind exactly as a card does (clean), unless it ran with
      a shop-wide change (flagged, bundle);
    - a multi-card set calibrates the JOINT prediction (``change_kind`` ``joint``, metric ``gmv``,
      weight 1) and counts for each member's change_kind at ``MULTI_CARD_WEIGHT`` (0.25): the
      joint measured / predicted ratio is applied to each card's own predicted range;
    - a set cut by a later change ("đo được N ngày", at least 3 days) is read at the days it ran,
      shown, and never calibrates; "không kết luận" is not read at all."""
    out: list[Observation] = []
    for cs in await change_sets.sets_for(
        session, shop_id, status=[change_sets.SET_MEASURING, change_sets.SET_CUT]
    ):
        cut = cs.status == change_sets.SET_CUT
        if cut and (
            (cs.result or {}).get("state") != change_sets.STATE_KEPT
            or (cs.result or {}).get("read")
        ):
            continue
        cards = await _set_cards(session, shop_id, cs)
        if not cards:
            continue
        days = int(cs.cut_days or 0) if cut else cs.window_days
        if cut and days < config.CUT_MIN_DAYS:
            continue
        t, how = await _set_clock(session, shop_id, cards)
        if t is None:
            report.skip(how)
            continue
        if len(cards) == 1:
            p, card = cards[0]
            got = await _read_card(
                session, shop_id, p, card, today, report, plan_days=days,
                extra_bundle=cs.with_shop_wide, partial=cut, change_set=str(cs.id),
            )  # fmt: skip
            if got.post_days is None or got.reading is None:
                continue
            lo, hi = _lift_range(card)
            cs.result = {
                **(cs.result or {}),
                "state": change_sets.STATE_KEPT if cut else change_sets.STATE_MEASURED,
                "label": change_sets.kept_label(days) if cut else f"Đo xong sau {days} ngày",
                "joint": False,
                "with_shop_wide": cs.with_shop_wide,
                "predicted_range": [lo, hi],
                "in_range": _in_range(got.reading.impact_pct, lo, hi),
                "read": True,
                **_reading_json(got.reading, got.post_days),
            }
            if not cut:
                cs.status = change_sets.SET_DONE
            if got.observation is not None:
                out.append(got.observation)
            continue
        obs = await _read_joint(
            session, shop_id, cs, cards, today, report, days=days, t=t, how=how, cut=cut
        )
        out.extend(obs)
    return out


def _joint_rel_from_cards(
    cards: list[tuple[Any, dict[str, Any]]],
    treated_days: Mapping[date, DayAgg],
    first: date,
    t: date,
) -> dict[str, float]:
    """The joint prediction of a set that was not planned together (no plan aggregate): the
    cards' stored results (one card, one number), each Δ GMV per 30 days, P50s added and the range
    by the root sum of squares of the half-widths, over the scope's GMV per 30 days before."""
    pre = [treated_days[d].gmv for d in treated_days if first <= d < t]
    base = (sum(pre) / len(pre)) * config.DAYS_PER_MONTH if pre else 0.0
    if base <= 0:
        return {}
    bands: list[dict[str, float]] = []
    for _, c in cards:
        block = result_store.measured_block(c)
        own = (block or {}).get("own") or {}
        d = (own.get("delta") or {}).get("gmv")
        if not d or not own.get("days") or d.get("p50") is None:
            return {}
        k = config.DAYS_PER_MONTH / int(own["days"])
        bands.append({q: float(v) * k for q, v in d.items() if v is not None})
    mid = sum(b["p50"] for b in bands)
    out = {"p50": mid / base}
    for q, sign in (("p10", -1.0), ("p90", 1.0)):
        if any(q not in b for b in bands):
            continue
        width = math.sqrt(sum((b[q] - b["p50"]) ** 2 for b in bands))
        out[q] = (mid + sign * width) / base
    return out


async def _read_joint(
    session: AsyncSession,
    shop_id: uuid.UUID,
    cs: ShopRecoChangeSet,
    cards: list[tuple[Any, dict[str, Any]]],
    today: date,
    report: LearningReport,
    *,
    days: int,
    t: date,
    how: str,
    cut: bool,
) -> list[Observation]:
    report.cards_considered += len(cards)
    if today < t + timedelta(days=days + 1):
        report.skip("plan_not_ended")
        return []
    first, last = t - timedelta(days=impact.PRE_DAYS + 1), t + timedelta(days=days)
    data = await load_item_days(session, shop_id, first, last)
    pid = cs.product_id
    if pid is not None:
        treated_days = data.get(pid)
        controls = {k: series_of(v, "gmv", first, last) for k, v in data.items() if k != pid}
    else:
        treated_days = _sum_days(list(data.values()))
        controls = {}
    if not treated_days:
        report.skip("no_series")
        return []
    excluded = await executed_days_other(
        session, shop_id, cards[0][0].id, first, last, [p.id for p, _ in cards[1:]]
    )
    reading = impact.read_effect(
        series_of(treated_days, "gmv", first, last), controls, t, post_days=days, excluded=excluded
    )
    rel = (cs.predicted or {}).get("rel_gmv") or _joint_rel_from_cards(
        cards, treated_days, first, t
    )
    lo, hi = rel.get("p10"), rel.get("p90")
    for p, card in cards:
        items = card["scope"]["product_ids"]
        await store.write_event(
            session,
            shop_id,
            p.id,
            event_type=EVENT_IMPACT_FINAL,
            actor=ACTOR_SYSTEM,
            occurred_at=datetime.combine(t + timedelta(days=days), datetime.min.time()),
            dedup_key=f"{EVENT_IMPACT_FINAL}:{p.id}",
            code=p.code,
            family=card["family"],
            card=card,
            change_kind=card["change_kind"],
            subject=("item", items[0]) if items else ("shop", str(p.id)),
            payload={
                "method": "adr077_ratio_did",
                "confidence": reading.confidence,
                "reason": reading.reason,
                "impact_pct": reading.impact_pct,
                "se_rel": reading.se_rel,
                "controls": list(reading.controls),
                "clock": how,
                "bundle": True,
                "post_days": days,
                "preliminary": False,
                "partial": cut,
                "change_set": str(cs.id),
                "joint": True,
            },
        )
    cs.result = {
        **(cs.result or {}),
        "state": change_sets.STATE_KEPT if cut else change_sets.STATE_MEASURED,
        "label": change_sets.kept_label(days) if cut else f"Đo xong sau {days} ngày",
        "joint": True,
        "with_shop_wide": cs.with_shop_wide,
        "predicted_range": None if lo is None or hi is None else [lo, hi],
        "in_range": _in_range(reading.impact_pct, lo, hi),
        "read": True,
        **_reading_json(reading, days),
    }
    if not cut:
        cs.status = change_sets.SET_DONE
    report.readings += 1
    if cut or reading.impact_pct is None or reading.confidence == "suppressed":
        if not cut:
            report.skip(f"reading_{reading.reason}")
        return []
    if lo is None or hi is None:
        report.skip("no_joint_prediction")
        return []
    controlled = not reading.fallback
    out = [
        Observation(
            "joint", "gmv", float(lo), float(hi), reading.impact_pct, reading.se_rel,
            "card", cs.with_shop_wide, f"cs:{cs.id}", controlled,
        )
    ]  # fmt: skip
    mid_j = (float(lo) + float(hi)) / 2
    if mid_j == 0:
        return out
    ratio = reading.impact_pct / mid_j
    for p, card in cards:
        klo, khi = _lift_range(card)
        mid_k = (klo + khi) / 2
        if mid_k == 0:
            continue
        out.append(
            Observation(
                card["change_kind"], card["metric"]["key"], klo, khi, ratio * mid_k,
                None if reading.se_rel is None else reading.se_rel * abs(mid_k / mid_j),
                "card", cs.with_shop_wide, f"{cs.id}:{p.id}", controlled,
                str(card.get("origin") or "engine"), config.MULTI_CARD_WEIGHT,
            )
        )  # fmt: skip
    return out


def _sum_days(parts: Iterable[Mapping[date, DayAgg]]) -> dict[date, DayAgg]:
    out: dict[date, DayAgg] = defaultdict(DayAgg)
    for part in parts:
        for d, a in part.items():
            o = out[d]
            o.views += a.views
            o.clicks += a.clicks
            o.orders += a.orders
            o.gmv += a.gmv
            o.spend += a.spend
    return dict(out)


async def executed_days_other(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    first: date,
    last: date,
    siblings: Iterable[uuid.UUID] = (),
) -> frozenset[date]:
    """Days of OTHER executed changes inside the window (dropped from the comparison); the cards
    of the same change set (``siblings``) are the change being measured, not another one."""
    rows = (
        await session.execute(
            select(CardEvent.card_id, CardEvent.occurred_at).where(
                CardEvent.shop_id == shop_id,
                CardEvent.event_type == EVENT_VERIFIED,
                CardEvent.card_id.notin_([card_id, *siblings]),
            )
        )
    ).all()
    return learning.executed_change_days(
        [(r.occurred_at.replace(tzinfo=None), 1) for r in rows], first, last
    )


async def stacked_with_other(
    session: AsyncSession,
    shop_id: uuid.UUID,
    card_id: uuid.UUID,
    items: list[str],
    start: date,
    end: date,
) -> bool:
    """Another executed card changed one of these products inside [start - plan, end]: the two
    are one bundle to measure (ADR-121 d.4), neither belongs to a per-kind calibration."""
    if not items:
        return False
    for p, _ in await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED]):
        if p.id == card_id:
            continue
        meta = await store.card_meta(session, shop_id, p.id)
        if not set(items) & set(meta.get("locked_items", [])):
            continue
        when = meta.get("executed_at")
        if when is None:
            continue
        day = datetime.fromisoformat(when).date()
        if start - timedelta(days=int(meta.get("plan_days") or 14)) <= day <= end:
            return True
    return False


async def read_plan_totals(
    session: AsyncSession, shop_id: uuid.UUID, today: date, report: LearningReport
) -> int:
    """The plan's shop total (P91 D-7): once every change set of an executed plan is read, the
    shop's GMV effect over the plan's window is compared with the plan's predicted dGMV (the
    aggregate frozen on confirm). The result is added to the plan's aggregate as ``shop_result``;
    it calibrates nothing (the shop total is context for the joint reading)."""
    done = 0
    plans_ = (
        await session.scalars(
            select(ShopRecoPlan).where(
                ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.status == PLAN_EXECUTED
            )
        )
    ).all()
    for plan_row in plans_:
        agg = dict(plan_row.aggregate or {})
        if not agg or "shop_result" in agg:
            continue
        sets = await change_sets.sets_for(session, shop_id, plan_id=plan_row.id)
        if not sets or any(cs.status == change_sets.SET_MEASURING for cs in sets):
            continue
        t = min(cs.executed_on for cs in sets)
        window = max(
            cs.window_days if cs.status != change_sets.SET_CUT else (cs.cut_days or 0)
            for cs in sets
        )
        if window < config.CUT_MIN_DAYS or today < t + timedelta(days=window + 1):
            continue
        first, last = t - timedelta(days=impact.PRE_DAYS + 1), t + timedelta(days=window)
        shop_days = await load_shop_days(session, shop_id, first, last)
        traffic = await load_traffic_controls(session, shop_id, first, last)
        reading = impact.read_effect(
            series_of(shop_days, "gmv", first, last), traffic, t, post_days=window
        )
        base = float((agg.get("today") or {}).get("gmv_30d") or 0)
        total = (agg.get("dgmv_month") or {}).get("total") or {}
        rel = {q: (None if not base or total.get(q) is None else total[q] / base) for q in total}
        agg["shop_result"] = {
            "post_days": window,
            "predicted_rel_gmv": rel,
            "in_range": _in_range(reading.impact_pct, rel.get("p10"), rel.get("p90")),
            "label": f"Đo xong sau {window} ngày",
            **_reading_json(reading, window),
        }
        plan_row.aggregate = agg
        done += 1
    return done


async def run_learning(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, include_natural: bool = True
) -> LearningReport:
    """Score every finished plan, pool with the stored natural experiments, recompute the
    shop's calibration (per change_kind and metric; bundles excluded) and coverage."""
    report = LearningReport()
    card_obs = await read_cards(session, shop_id, now.date(), report)
    card_obs += await read_change_sets(session, shop_id, now.date(), report)
    await read_plan_totals(session, shop_id, now.date(), report)
    await ads_readback.refresh_shop(session, shop_id, now.date())  # P99b: new-campaign read-back
    old = await store.load_observations(session, shop_id)
    natural = [o for o in old if o.source == "natural"] if include_natural else []
    prior_cards = {o.ref: o for o in old if o.source == "card"}
    merged = {**prior_cards, **{o.ref: o for o in card_obs}}
    all_obs = [*natural, *merged.values()]
    states = learning.calibrate_all(all_obs)
    report.observations_total = len(all_obs)
    report.states = await store.save_calibrations(session, shop_id, states, all_obs, now=now)
    await product_queue.requeue_shop(
        session, shop_id, now
    )  # a read-back or reading may close a card
    return report


# ----------------------------------------------------------- natural-experiment backfill


@dataclass
class BackfillReport:
    candidates: dict[str, int] = field(default_factory=dict)
    usable: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, dict[str, int]] = field(default_factory=dict)
    in_range: dict[str, int] = field(default_factory=dict)
    #: read without a control series: kept, shown, but not used for calibration or coverage
    uncontrolled: dict[str, int] = field(default_factory=dict)

    def bump(self, table: dict[str, int], kind: str) -> None:
        table[kind] = table.get(kind, 0) + 1

    def skip(self, kind: str, why: str) -> None:
        d = self.skipped.setdefault(kind, {})
        d[why] = d.get(why, 0) + 1

    def json(self) -> dict[str, Any]:
        kinds = sorted({*self.candidates, *self.usable})
        return {
            k: {
                "candidates": self.candidates.get(k, 0),
                "usable": self.usable.get(k, 0),
                "uncontrolled": self.uncontrolled.get(k, 0),
                "skipped": self.skipped.get(k, {}),
                "in_range": self.in_range.get(k, 0),
                "coverage": None
                if not self.usable.get(k)
                else round(self.in_range.get(k, 0) / self.usable[k], 3),
            }
            for k in kinds
        }


def natural_prior(kind: str, magnitude_pct: float | None) -> tuple[float, float]:
    """The range the model would have predicted for this change (bucket 'unknown')."""
    s = KINDS[kind]
    return prior_range(s, magnitude_pct, "unknown")


def score_natural(
    kind: str,
    metric: str,
    series: Mapping[date, float],
    controls: Mapping[str, Mapping[date, float]],
    t: date,
    magnitude_pct: float | None,
    ref: str,
    report: BackfillReport,
    *,
    post_days: int = 14,
    excluded: frozenset[date] = frozenset(),
    floor: float = 0.0,
) -> Observation | None:
    report.bump(report.candidates, kind)
    reading = impact.read_effect(
        series, controls, t, post_days=post_days, excluded=excluded, volume_floor_per_day=floor
    )
    if reading.impact_pct is None or reading.confidence == "suppressed":
        report.skip(kind, reading.reason or "suppressed")
        return None
    lo, hi = natural_prior(kind, magnitude_pct)
    if lo == hi == 0.0:
        report.skip(kind, "no_prediction")
        return None
    obs = Observation(
        kind,
        metric,
        lo,
        hi,
        reading.impact_pct,
        reading.se_rel,
        "natural",
        False,
        ref,
        not reading.fallback,
    )
    if obs.controlled:
        report.bump(report.usable, kind)
        if obs.in_range:
            report.bump(report.in_range, kind)
    else:
        report.bump(report.uncontrolled, kind)
    return obs


async def backfill_natural(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> tuple[BackfillReport, list[Observation]]:
    """Score the shop's own past ad changes (ROAS target / budget) and vouchers once, as
    natural experiments, to seed its calibration. Reports counts and coverage only."""
    report = BackfillReport()
    obs: list[Observation] = []
    today = now.date()
    first_all = today - timedelta(days=400)
    camp = await load_campaign_days(session, shop_id, first_all, today)
    settings = await PlatformDailyMetricsRepo(session).window(
        shop_id, datasets=[ADS_DAILY], start=first_all, end=today, any_item=True
    )
    by_seg: dict[str, list[Any]] = defaultdict(list)
    for r in sorted(settings, key=lambda r: (r.segment, r.day)):
        if r.segment != "all":
            by_seg[r.segment].append(r)
    # ROAS target changes: the target series of the campaign day by day
    for seg, rows in by_seg.items():
        prev = None
        for r in rows:
            cur = (r.extra or {}).get("roi_two_target")
            if cur is None:
                continue
            if prev is not None and float(cur) != float(prev):
                mag = (float(cur) - float(prev)) / float(prev) * 100 if float(prev) else None
                first, last = r.day - timedelta(days=16), r.day + timedelta(days=15)
                series = series_of(camp[seg], "roas", first, last)
                ctrl = {k: series_of(v, "roas", first, last) for k, v in camp.items() if k != seg}
                o = score_natural(
                    "ads_roas_target",
                    "roas",
                    series,
                    ctrl,
                    r.day,
                    mag,
                    f"roas:{seg}:{r.day}",
                    report,
                )
                if o:
                    obs.append(o)
            prev = cur
    # budget changes: the ads change log (budget_from -> budget_to by a user)
    logs = (
        await session.scalars(
            select(AdsChangeLog).where(
                AdsChangeLog.shop_id == shop_id,
                AdsChangeLog.budget_from.is_not(None),
                AdsChangeLog.budget_to.is_not(None),
            )
        )
    ).all()
    from juli_backend.services.ingest.mapping import campaign_segment

    for lg in logs:
        if not lg.budget_from or lg.budget_from == lg.budget_to or lg.item_id:
            continue
        report.bump(report.candidates, "ads_budget")
        if lg.actor_kind != "user":
            report.skip("ads_budget", "shopee_optimiser_not_a_seller_change")
            continue
        seg = campaign_segment(lg.campaign_id)
        if seg not in camp:
            report.skip("ads_budget", "no_campaign_series")
            continue
        d = lg.occurred_at.date()
        assert lg.budget_to is not None and lg.budget_from is not None
        mag = float((lg.budget_to - lg.budget_from) / lg.budget_from * 100)
        first, last = d - timedelta(days=16), d + timedelta(days=15)
        series = series_of(camp[seg], "ads_gmv", first, last)
        ctrl = {k: series_of(v, "ads_gmv", first, last) for k, v in camp.items() if k != seg}
        o = score_natural(
            "ads_budget", "ads_gmv", series, ctrl, d, mag, f"budget:{lg.campaign_id}:{d}", report
        )
        report.candidates["ads_budget"] -= 1  # score_natural counted it again
        if o:
            obs.append(o)
    # vouchers: the shop's own daily orders before and after each voucher's start (no controls;
    # traffic is not held fixed, so the reading is a proxy and the card says so)
    shop_days = await load_shop_days(session, shop_id, first_all, today)
    traffic = await load_traffic_controls(session, shop_id, first_all, today)
    prom = await PlatformPromotionsRepo(session).overlapping(
        shop_id, promo_types=["voucher"], start=first_all, end=today, order_types=["confirmed"]
    )
    seen: set[tuple[str, date]] = set()
    for p in prom:
        if p.starts_at is None:
            continue
        key = (p.program_name, p.starts_at.date())
        if key in seen:
            continue
        seen.add(key)
        extra = p.extra or {}
        d = p.starts_at.date()
        min_spend = float(extra.get("min_spend") or 0)
        kind, metric = ("min_spend_voucher", "aov") if min_spend > 0 else ("review_voucher", "ctor")
        if extra.get("created_by_shopee"):
            report.bump(report.candidates, kind)
            report.skip(kind, "created_by_shopee_not_a_seller_change")
            continue
        if not any(first_all <= x <= today for x in (d,)) or d - timedelta(days=15) < first_all:
            report.bump(report.candidates, kind)
            report.skip(kind, "before_the_data_starts")
            continue
        post = 14
        if p.ends_at is not None:
            post = min(post, (p.ends_at.date() - d).days)
            if post < 7:
                report.bump(report.candidates, kind)
                report.skip(kind, "ran_less_than_a_week")
                continue
        lo_day, hi_day = d - timedelta(days=16), d + timedelta(days=post + 1)
        series = series_of(shop_days, "aov" if metric == "aov" else "orders", lo_day, hi_day)
        controls = {
            k: {day: v for day, v in c.items() if lo_day <= day <= hi_day}
            for k, c in traffic.items()
        }
        o = score_natural(
            kind,
            metric,
            series,
            controls,
            d,
            None,
            f"voucher:{d}",
            report,
            post_days=post,
            floor=1.0,
        )
        if o:
            obs.append(o)
    return report, obs


async def apply_backfill(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> BackfillReport:
    """Run the backfill and merge its observations into the calibration (idempotent)."""
    report, new = await backfill_natural(session, shop_id, now=now)
    old = await store.load_observations(session, shop_id)
    kept = [o for o in old if o.source != "natural"]
    all_obs = [*kept, *new]
    states = learning.calibrate_all(all_obs)
    await store.save_calibrations(session, shop_id, states, all_obs, now=now)
    return report


__all__ = ["Decimal", "factor_from", "spec", "config"]
