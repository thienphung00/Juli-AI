"""P90 step 8: the learning loop on stored data -- a finished plan is read (ADR-077) against
the frozen prediction, calibration and coverage are rewritten for the shop, and the one-off
natural-experiment backfill from the ads change log and voucher history seeds them.
SQLite; synthetic series with a known uplift."""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import EVENT_VERIFIED, CardEvent
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.platform_data import PlatformItem, PlatformPromotion
from juli_backend.models.shopee_profit import AdsChangeLog, PlatformItemSnapshot
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.card_events.writer import EventSpec, insert_event
from juli_backend.services.shopee_recommendations import measure, store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import _line, _src
from tests.support.shopee_reco import rule

END = date(2026, 10, 31)
T = date(2026, 10, 1)  # the change is verified on this day
NOW = datetime(2026, 10, 31, 12, 0)
UPLIFT = 0.20


async def _shop_with_items(session, items=("1001", "1002", "1003", "1004", "1005")):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee", shop_name="Learning Shop")
    sid = shop.id
    for it in items:
        session.add(
            PlatformItem(
                shop_id=sid,
                item_id=it,
                variation_id="",
                name=f"SP {it}",
                seller_sku=f"K{it}",
                status="ok",
                extra={},
                **_src(),
            )
        )
        session.add(
            PlatformItemSnapshot(
                shop_id=sid,
                platform="shopee",
                item_id=it,
                variation_id="",
                captured_at=datetime(2026, 10, 30),
                title=f"SP {it}",
                image_urls=[],
                image_hashes=[],
                list_price=D(100_000),
                current_price=D(100_000),
                stock=500,
                rating=D("4.8"),
                rating_count=5,
                category_path=["x"],
                status="ok",
                source="extension",
                source_rank=1,
            )
        )
        session.add(rule(sid, "sku_cost", f"K{it}", 30_000))
        session.add(rule(sid, "packaging_cost", f"K{it}", 1_000))
    session.add(rule(sid, "min_margin_pct", "", 10))
    session.add(rule(sid, "daily_marketing_cap", "", 5_000_000))
    return user, shop, sid


async def _series_shop(session, *, uplift: float):
    """Product 1001: 10 orders/day before T, 10 x (1 + uplift) after; four control products
    flat at 10/day sharing the same weekday pattern."""
    user, shop, sid = await _shop_with_items(session)
    rng = random.Random(4)
    n = 1
    start = T - timedelta(days=21)
    for item in ("1001", "1002", "1003", "1004", "1005"):
        sku = f"K{item}"
        for i in range((END - start).days + 1):
            day = start + timedelta(days=i)
            base = 10 + (3 if day.weekday() >= 5 else 0)  # weekend bump, shared
            k = base + rng.choice([-1, 0, 0, 1])
            if item == "1001" and day > T:
                k = round(k * (1 + uplift))
            for _ in range(k):
                session.add(
                    _line(
                        sid,
                        n,
                        day,
                        sku,
                        original=100_000,
                        deal=100_000,
                        promo_kind="none",
                        fees=None,
                    )
                )
                n += 1
    await session.commit()
    return user, shop, sid


async def _executed_card(session, sid, user, *, planned_days=14, kind="flash_sale"):
    env = await load_env(session, sid, as_of=END)
    cand = Candidate(
        kind, ("1001",), {"discount_pct": 15, "units": 100, "slot_days": 1}, wiring_key="sale"
    )
    card = build_card(env, cand, now=NOW)
    assert card is not None
    card["measurement_plan"]["planned_days"] = planned_days  # the synthetic shop is busy enough
    card["rank"] = {"position": 1, "score": 1, "detail": {}, "mode": "x", "explore": False}
    cid = await store.save_card(
        session, sid, card, cycle="2026-10", position=1, now=datetime(2026, 9, 28)
    )
    await reco.publish(session, sid, [cid], now=datetime(2026, 9, 28))
    await reco.decide(
        session, sid, cid, decision="approve", user_id=user.id, now=datetime(2026, 9, 29)
    )
    await reco.mark_executed(
        session,
        sid,
        cid,
        now=datetime(2026, 10, 1, 9),
        executed_at=datetime(2026, 10, 1, 9),
        user_id=user.id,
    )
    await session.commit()
    return cid, card


async def test_a_finished_plan_is_read_against_its_frozen_prediction(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, card = await _executed_card(session, sid, user)
    report = await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    assert report.readings == 1 and report.cards_considered == 1 and report.observations_total == 1
    states = await store.load_calibrations(session, sid)
    st = states[("flash_sale", "orders")]
    lo, hi = (
        float(card["predicted"]["lift"]["lift"]["p10"]),
        float(card["predicted"]["lift"]["lift"]["p90"]),
    )
    obs = (await store.load_observations(session, sid))[0]
    assert (
        obs.source == "card"
        and not obs.bundle
        and (obs.predicted_low, obs.predicted_high) == (lo, hi)
    )
    assert obs.measured == pytest.approx(UPLIFT, abs=0.08)  # the injected uplift is recovered
    assert (
        st.n_results == 1
        and st.coverage_n == 1
        and st.coverage_hits == (1 if lo <= obs.measured <= hi else 0)
    )
    assert st.pooled_ratio == pytest.approx(obs.measured / ((lo + hi) / 2))
    (final,) = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "impact_final"
            )
        )
    ).all()
    assert (
        final.payload["method"] == "adr077_ratio_did"
        and final.payload["clock"] == "executed_no_readback"
    )
    assert final.payload["impact_pct"] == pytest.approx(obs.measured)
    # idempotent: a second run writes no second event and keeps one observation
    again = await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    assert again.observations_total == 1
    assert (
        len(
            (
                await session.scalars(
                    select(CardEvent).where(
                        CardEvent.card_id == cid, CardEvent.event_type == "impact_final"
                    )
                )
            ).all()
        )
        == 1
    )


async def test_the_next_prediction_uses_the_shops_calibration_only_after_five_results(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    await _executed_card(session, sid, user)
    await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    env = await load_env(session, sid, as_of=END)
    cand = Candidate("flash_sale", ("1002",), {"discount_pct": 15, "units": 100, "slot_days": 1})
    one = build_card(env, cand, now=NOW)["predicted"]["lift"]
    assert one["source"] == "prior" and one["factor"] == 1.0  # a single result is not enough
    # five results for the same (kind, metric) give the shop its own factor
    from juli_backend.services.shopee_recommendations.learning import Observation, calibrate

    five = [
        Observation(
            "flash_sale", "orders", 0.075, 0.3, 0.6 * 0.1875, None, "natural", False, f"n{i}"
        )
        for i in range(5)
    ]
    await store.save_calibrations(session, sid, calibrate(five), five, now=NOW)
    await session.commit()
    env2 = await load_env(session, sid, as_of=END)
    cal = build_card(env2, cand, now=NOW)["predicted"]["lift"]
    assert cal["source"] == "shop" and cal["factor"] == pytest.approx(1 + 0.5 * (0.6 - 1))
    assert cal["lift"]["p50"] < one["lift"]["p50"]


async def test_a_plan_that_has_not_ended_or_was_khó_kết_luận_is_not_read(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, _ = await _executed_card(session, sid, user, planned_days=28)
    early = await reco.run_learning(session, sid, now=datetime(2026, 10, 20))
    assert early.readings == 0 and early.skipped == {}  # only the T+7 look is written
    assert early.preliminary == 1
    before_plan = await reco.run_learning(session, sid, now=datetime(2026, 10, 5))
    assert before_plan.skipped == {"plan_not_ended": 1} and before_plan.preliminary == 0
    meta = await store.card_meta(session, sid, cid)
    assert meta["plan_days"] == 28


async def test_stacked_cards_are_read_but_excluded_from_per_kind_calibration(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, card = await _executed_card(session, sid, user)
    # the bundle flag is read from the frozen payload: a mega card is simulated by saving a
    # second, bundle-flagged card
    card2 = dict(card, bundle=True, scope={**card["scope"], "product_ids": ["1002"]})
    cid2 = await store.save_card(
        session, sid, card2, cycle="2026-10", position=2, now=datetime(2026, 9, 28)
    )
    await reco.publish(session, sid, [cid2], now=datetime(2026, 9, 28))
    await reco.decide(
        session, sid, cid2, decision="approve", user_id=user.id, now=datetime(2026, 9, 29)
    )
    await reco.mark_executed(
        session,
        sid,
        cid2,
        now=datetime(2026, 10, 1, 9),
        executed_at=datetime(2026, 10, 1, 9),
        user_id=user.id,
    )
    await session.commit()
    rep = await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    st = (await store.load_calibrations(session, sid))[("flash_sale", "orders")]
    assert (
        rep.readings == 2 and st.n_results == 1 and st.n_bundle_excluded == 1 and st.coverage_n == 1
    )


async def test_verified_time_starts_the_clock_for_kinds_with_a_read_back(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, card = await _executed_card(session, sid, user)
    when, how = await measure.verified_time(session, sid, cid)
    assert how == "executed_no_readback" and when == datetime(2026, 10, 1, 9)
    # a card whose change has a read-back waits for it
    ex = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == cid, CardEvent.event_type == "executed")
        )
    ).one()
    assert "price" not in ex.payload["change"]["change_kind"]


async def test_executed_change_days_leave_the_flow_baseline(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, _ = await _executed_card(session, sid, user)
    await insert_event(
        session,
        EventSpec(
            shop_id=sid,
            card_id=cid,
            event_type=EVENT_VERIFIED,
            actor="system",
            occurred_at=datetime(2026, 10, 3, 9),
            workflow_key="shopee_reco:sale",
            subject_type="item",
            subject_id="1001",
            dedup_key=f"verified:assisted:{cid}",
            payload={},
        ),
    )
    from juli_backend.services.shopee_recommendations import service

    days = await service.executed_days(session, sid, date(2026, 10, 1), date(2026, 10, 31))
    assert (
        min(days) == date(2026, 10, 3)
        and date(2026, 10, 4) in days
        and date(2026, 10, 2) not in days
    )


# ---------------------------------------------------------------- natural experiments


def _ad_row(sid, seg, day, *, target, gmv, cost, budget=50_000):
    return PlatformDailyMetric(
        shop_id=sid,
        dataset="ads_campaign_daily",
        day=day,
        item_id="",
        stream="ads",
        segment=seg,
        order_type="placed",
        platform_source=f"Chiến dịch {seg}",
        impressions=D(1000),
        clicks=D(40),
        orders=D(3),
        gmv=D(int(gmv)),
        extra={
            "roi_two_target": target,
            "daily_budget": budget,
            "cost": cost,
            "direct_gmv": int(gmv),
        },
        confidence="high",
        **_src(),
    )


async def test_the_backfill_scores_roas_target_and_budget_changes_and_vouchers_once(session):
    from juli_backend.services.ingest.mapping import campaign_segment

    user, shop, sid = await _shop_with_items(session, items=("1001",))
    rng = random.Random(9)
    start = date(2026, 8, 1)
    change = date(2026, 9, 1)
    segs = ["c1", "c2", "c3", "c4", "c5"]
    common = {start + timedelta(days=i): 1 + rng.gauss(0, 0.2) for i in range(90)}
    for seg in segs:
        for i in range(80):
            d = start + timedelta(days=i)
            gmv = 100_000 * common[d] * (1 + rng.gauss(0, 0.02))
            target = 3.0
            if seg == "c1" and d >= change:
                target = 4.0
                gmv *= 1.10
            session.add(_ad_row(sid, seg, d, target=target, gmv=gmv, cost=20_000))
    # a user's budget change on c2 (+20 %) with a +15 % effect from the change day
    seg2 = campaign_segment("2002")
    for i in range(80):
        d = start + timedelta(days=i)
        gmv = (
            100_000 * common[d] * (1 + rng.gauss(0, 0.02)) * (1.15 if d >= date(2026, 9, 15) else 1)
        )
        session.add(_ad_row(sid, seg2, d, target=3.0, gmv=gmv, cost=20_000))
    session.add(
        AdsChangeLog(
            shop_id=sid,
            platform="shopee",
            campaign_id="2002",
            item_id="",
            occurred_at=datetime(2026, 9, 15, 10),
            actor_kind="user",
            event_type="Chỉnh sửa ngân sách",
            budget_from=D(50_000),
            budget_to=D(60_000),
            ordinal=0,
            source="file",
            source_version="t",
        )
    )
    session.add(
        AdsChangeLog(  # Shopee's own optimiser: not a seller change
            shop_id=sid,
            platform="shopee",
            campaign_id="2002",
            item_id="",
            occurred_at=datetime(2026, 9, 16, 10),
            actor_kind="system",
            event_type="auto",
            budget_from=D(60_000),
            budget_to=D(70_000),
            ordinal=0,
            source="file",
            source_version="t",
        )
    )
    # the shop's daily overview and traffic for the voucher reading: orders per day step up from
    # the voucher's start while visitors do not (so the reading is an effect on conversion)
    for i in range(80):
        d = start + timedelta(days=i)
        k = round((10 if d < date(2026, 9, 20) else 13) * common[d])
        visitors = round(1000 * common[d])
        session.add(
            PlatformDailyMetric(
                shop_id=sid,
                dataset="shop_overview",
                day=d,
                item_id="",
                stream="total",
                segment="all",
                order_type="confirmed",
                orders=D(k),
                gmv=D(k * 100_000),
                visitors=D(visitors),
                extra={},
                confidence="high",
                **_src(),
            )
        )
        for seg, share in (("all", 1.0), ("app", 0.9), ("pc", 0.1)):
            session.add(
                PlatformDailyMetric(
                    shop_id=sid,
                    dataset="shop_traffic",
                    day=d,
                    item_id="",
                    stream="total",
                    segment=seg,
                    order_type="none",
                    visitors=D(round(visitors * share)),
                    extra={},
                    confidence="high",
                    **_src(),
                )
            )
    session.add(
        PlatformPromotion(
            shop_id=sid,
            promo_type="voucher",
            program_name="Ory 5k",
            starts_at=datetime(2026, 9, 20, 8),
            ordinal=0,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            order_type="confirmed",
            extra={"voucher_cost": 5000, "usage_rate": 0.3, "min_spend": 0},
            gmv=D(1),
            orders=D(1),
            **_src(),
        )
    )
    await session.commit()

    report = await reco.apply_backfill(session, sid, now=datetime(2026, 10, 31, 12))
    await session.commit()
    out = report.json()
    assert out["ads_roas_target"]["candidates"] == 1 and out["ads_roas_target"]["usable"] == 1
    assert out["ads_budget"]["usable"] == 1  # the optimiser's own change is not counted
    assert out["review_voucher"]["candidates"] == 1 and out["review_voucher"]["usable"] == 1
    assert out["review_voucher"]["uncontrolled"] == 0
    for kind, row in out.items():
        assert row["usable"] <= row["candidates"]
        assert row["coverage"] is None or 0.0 <= row["coverage"] <= 1.0
    text = json.dumps(out)
    for secret in ("2002", "c1", "Ory", "1001"):
        assert secret not in text  # counts only: no id or name in the report
    states = await store.load_calibrations(session, sid)
    roas = states[("ads_roas_target", "roas")]
    assert roas.sources == {"natural": 1}
    obs = [
        o for o in await store.load_observations(session, sid) if o.change_kind == "ads_roas_target"
    ]
    assert obs[0].measured == pytest.approx(0.10, abs=0.05) and obs[0].source == "natural"
    # once: running it again replaces, never doubles
    await reco.apply_backfill(session, sid, now=datetime(2026, 10, 31, 12))
    await session.commit()
    assert len(await store.load_observations(session, sid)) == len(obs) + 1 + 1
    # natural observations seed the card calibration and survive a card-learning run
    await reco.run_learning(session, sid, now=datetime(2026, 10, 31, 13))
    await session.commit()
    assert ("ads_roas_target", "roas") in await store.load_calibrations(session, sid)


async def test_the_backfill_of_a_shop_with_no_history_reports_zeros(session):
    user, shop, sid = await _shop_with_items(session, items=("1001",))
    await session.commit()
    report = await reco.apply_backfill(session, sid, now=NOW)
    assert report.json() == {}


async def test_two_changes_on_one_product_in_one_window_are_one_bundle(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    first, _ = await _executed_card(session, sid, user)
    second, _ = await _executed_card(session, sid, user)  # the same product, the same days
    report = await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    st = (await store.load_calibrations(session, sid))[("flash_sale", "orders")]
    assert report.readings == 2 and st.n_results == 0 and st.n_bundle_excluded == 2
    events = (
        await session.scalars(select(CardEvent).where(CardEvent.event_type == "impact_final"))
    ).all()
    assert {e.card_id for e in events} == {first, second} and all(
        e.payload["bundle"] for e in events
    )


async def test_a_running_plan_gets_one_preliminary_reading_at_day_7_that_never_calibrates(session):
    user, shop, sid = await _series_shop(session, uplift=UPLIFT)
    cid, _ = await _executed_card(session, sid, user, planned_days=28)
    for _ in range(2):  # idempotent
        report = await reco.run_learning(session, sid, now=datetime(2026, 10, 12))
        await session.commit()
    assert report.readings == 0 and report.observations_total == 0
    assert await store.load_calibrations(session, sid) == {}
    (pre,) = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "impact_preliminary"
            )
        )
    ).all()
    assert pre.payload["post_days"] == 7 and pre.payload["preliminary"] is True
    assert pre.payload["impact_pct"] == pytest.approx(UPLIFT, abs=0.1)
    assert {"confidence", "reason", "impact_pct"} <= set(pre.payload)
    none_final = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "impact_final"
            )
        )
    ).all()
    assert none_final == []
    # the plan ends: the final reading follows with the same shape
    done = await reco.run_learning(session, sid, now=NOW)
    await session.commit()
    assert done.readings == 1
    (fin,) = (
        await session.scalars(
            select(CardEvent).where(
                CardEvent.card_id == cid, CardEvent.event_type == "impact_final"
            )
        )
    ).all()
    assert set(pre.payload) == set(fin.payload) and fin.payload["post_days"] == 28
    detail = await reco.card_detail(session, sid, cid, audience="seller")
    rows = {j["event"]: j["payload"] for j in detail["journey"] if j["payload"]}
    assert rows["impact_preliminary"]["post_days"] == 7
    assert set(rows["impact_final"]) >= {"impact_pct", "confidence", "reason"}
    assert "controls" not in rows["impact_final"] and "method" not in rows["impact_final"]
