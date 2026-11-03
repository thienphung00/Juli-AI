"""Readings at the plan end and the calibration job (ADR-121 d.4), plus the one-off
natural-experiment backfill (d.5).

DB side: daily series per product (and per campaign) from the stored Shopee data, the verified
time of each execution from ``card_events``, the frozen prediction from the `proposed` payload.
Pure side: :mod:`.impact` (ADR-077 DiD), :mod:`.learning` (calibration math).

Nothing here changes a card or a proposal's text; it appends `impact_final` events and rewrites
the shop's own calibration rows. No row of ORY ever reaches another shop's calibration.
"""

from __future__ import annotations

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
    EVENT_VERIFIED,
    CardEvent,
)
from juli_backend.models.shop_proposals import STATUS_EXECUTED
from juli_backend.models.shopee_profit import AdsChangeLog
from juli_backend.repositories import (
    PlatformDailyMetricsRepo,
    PlatformPromotionsRepo,
    ShopeeOrderLinesRepo,
)
from juli_backend.services.shopee_analytics import loaders
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.shopee_recommendations import config, impact, learning, store
from juli_backend.services.shopee_recommendations.kinds import KINDS, spec
from juli_backend.services.shopee_recommendations.learning import Observation
from juli_backend.services.shopee_recommendations.prediction import factor_from, prior_range

ITEM_DAILY = ("item_traffic_sources", "item_by_source")
ADS_DAILY = "ads_campaign_daily"
STREAMS = ("product_card", "seller_live", "seller_video", "affiliate")
MEASURABLE = ("ctr", "ctor", "views", "orders", "aov", "ads_gmv", "roas")


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
        if metric == "ads_gmv":
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
    count = metric in ("views", "orders", "ads_gmv")
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
    skipped: dict[str, int] = field(default_factory=dict)
    observations_total: int = 0
    states: int = 0

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1

    def json(self) -> dict[str, Any]:
        return {
            "cards_considered": self.cards_considered,
            "readings": self.readings,
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


def _lift_range(card: Mapping[str, Any]) -> tuple[float, float]:
    lift = card["predicted"]["lift"]["lift"]
    return float(lift["p10"]), float(lift["p90"])


async def read_cards(
    session: AsyncSession, shop_id: uuid.UUID, today: date, report: LearningReport
) -> list[Observation]:
    """Final readings of every executed card whose plan has ended."""
    out: list[Observation] = []
    rows = await store.list_cards(session, shop_id, statuses=[STATUS_EXECUTED])
    for p, card in rows:
        report.cards_considered += 1
        plan_days = card["measurement_plan"]["planned_days"]
        metric = card["metric"]["key"]
        if plan_days is None:
            report.skip("khong_ket_luan")
            continue
        if metric not in MEASURABLE:
            report.skip("metric_not_measurable")
            continue
        t_at, how = await verified_time(session, shop_id, p.id)
        if t_at is None:
            report.skip(how)
            continue
        t = t_at.date()
        if today < t + timedelta(days=plan_days + 1):
            report.skip("plan_not_ended")
            continue
        first, last = t - timedelta(days=impact.PRE_DAYS + 1), t + timedelta(days=plan_days)
        items = card["scope"]["product_ids"]
        if metric in ("ads_gmv", "roas"):
            data = await load_campaign_days(session, shop_id, first, last)
            key = card["scope"].get("campaign_key")
            treated_days = data.get(key or "")
            controls = {k: series_of(v, metric, first, last) for k, v in data.items() if k != key}
        else:
            data = await load_item_days(session, shop_id, first, last)
            treated_days = (
                _sum_days([data.get(i, {}) for i in items])
                if items
                else _sum_days(list(data.values()))
            )
            controls = {
                k: series_of(v, metric, first, last) for k, v in data.items() if k not in items
            }
        if not treated_days:
            report.skip("no_series")
            continue
        excluded = await executed_days_other(session, shop_id, p.id, first, last)
        reading = impact.read_effect(
            series_of(treated_days, metric, first, last),
            controls,
            t,
            post_days=plan_days,
            excluded=excluded,
        )
        await store.write_event(
            session,
            shop_id,
            p.id,
            event_type=EVENT_IMPACT_FINAL,
            actor=ACTOR_SYSTEM,
            occurred_at=datetime.combine(t + timedelta(days=plan_days), datetime.min.time()),
            dedup_key=f"impact_final:{p.id}",
            family=card["family"],
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
                "bundle": bool(card.get("bundle")),
            },
        )
        if reading.impact_pct is None or reading.confidence == "suppressed":
            report.skip(f"reading_{reading.reason}")
            continue
        lo, hi = _lift_range(card)
        out.append(
            Observation(
                card["change_kind"],
                metric,
                lo,
                hi,
                reading.impact_pct,
                reading.se_rel,
                "card",
                bool(card.get("bundle")),
                str(p.id),
                not reading.fallback,
            )
        )
        report.readings += 1
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
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, first: date, last: date
) -> frozenset[date]:
    """Days of OTHER executed changes inside the window (dropped from the comparison)."""
    rows = (
        await session.execute(
            select(CardEvent.card_id, CardEvent.occurred_at).where(
                CardEvent.shop_id == shop_id,
                CardEvent.event_type == EVENT_VERIFIED,
                CardEvent.card_id != card_id,
            )
        )
    ).all()
    return learning.executed_change_days(
        [(r.occurred_at.replace(tzinfo=None), 1) for r in rows], first, last
    )


async def run_learning(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, include_natural: bool = True
) -> LearningReport:
    """Score every finished plan, pool with the stored natural experiments, recompute the
    shop's calibration (per change_kind and metric; bundles excluded) and coverage."""
    report = LearningReport()
    card_obs = await read_cards(session, shop_id, now.date(), report)
    old = await store.load_observations(session, shop_id)
    natural = [o for o in old if o.source == "natural"] if include_natural else []
    prior_cards = {o.ref: o for o in old if o.source == "card"}
    merged = {**prior_cards, **{o.ref: o for o in card_obs}}
    all_obs = [*natural, *merged.values()]
    states = learning.calibrate(all_obs)
    report.observations_total = len(all_obs)
    report.states = await store.save_calibrations(session, shop_id, states, all_obs, now=now)
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
    states = learning.calibrate(all_obs)
    await store.save_calibrations(session, shop_id, states, all_obs, now=now)
    return report


__all__ = ["Decimal", "factor_from", "spec", "config"]
