"""F7.5 / F7.6 / F7.7: the running Thực tế, groups of overlapping change sets, and the clean gate
of calibration (L-3 / L-5). SQLite; made-up numbers."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily, ShopeeShopMetricsDaily
from juli_backend.models.shopee_plans import ShopRecoChangeSet
from juli_backend.services.shopee_recommendations import change_sets, measure, running
from juli_backend.services.shopee_recommendations.running import Day
from tests.support.builders import make_shop, make_user

START = date(2026, 11, 12)
ITEM = "26107129526"


def _cs(start: date, days: int, *, scope="product", product=ITEM, status="measuring", result=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope=scope,
        product_id=product if scope == "product" else None,
        started_at=datetime.combine(start, datetime.min.time()),
        window_days=days,
        status=status,
        card_ids=[str(uuid.uuid4())],
        result=result,
    )


# --------------------------------------------------------------------------- F7.5 (pure)


def _days(first: date, profits: list[float | None], orders: list[int], gmv: float = 100_000):
    return {
        first + timedelta(days=i): Day(gmv, float(orders[i]), profits[i])
        for i in range(len(profits))
    }


def test_running_thuc_te_reproduces_the_gloves_example():
    before = _days(START - timedelta(days=7), [101_055.0] * 7, [2] * 7)  # 707.385 / 14 orders
    after = _days(START, [-38_489.0] * 7, [2, 1, 1, 2, 1, 1, 1])  # -269.423 / 9 orders
    data = frozenset([*before, *after])
    got = running.build_actual({**before, **after}, data, start=START, n=14)
    assert got is not None
    assert got["days_measured"] == 7 and got["days"] == 14 and got["label"] == "Đã đo 7/14 ngày"
    p = got["metrics"]["profit"]
    assert round(p["hien_tai"]) == 707_385 and round(p["thuc_te"]) == -269_423
    assert round(p["delta"]) == -976_808 and p["days_measured"] == 7 and p["days"] == 14
    assert got["metrics"]["orders"]["hien_tai"] == 14 and got["metrics"]["orders"]["thuc_te"] == 9
    assert set(got["metrics"]) == set(running.METRICS)
    assert got["verdict"] is None  # not final: no verdict before the plan ends
    assert got["from"] == "2026-11-12" and got["to"] == "2026-11-18"
    assert got["base_from"] == "2026-11-05" and got["base_to"] == "2026-11-11"


def test_no_data_yet_is_none_and_unknown_profit_stays_none():
    assert running.build_actual({}, frozenset(), start=START, n=7) is None
    days = _days(START - timedelta(days=2), [5.0, 5.0, 5.0, None, 5.0], [1] * 5)
    got = running.build_actual(days, frozenset(days), start=START, n=2)
    assert got is not None and got["metrics"]["profit"]["thuc_te"] is None
    assert got["metrics"]["profit"]["delta"] is None
    assert got["metrics"]["gmv"]["thuc_te"] == 200_000


def test_final_verdict_is_on_profit_against_the_band():
    days = _days(START - timedelta(days=3), [100.0] * 3 + [400.0] * 3, [1] * 6)
    data = frozenset(days)
    for band, key in (
        ((500.0, 1000.0), "trong_khoang"),
        ((0.0, 500.0), "vuot_khoang"),
        ((1000.0, 1500.0), "duoi_khoang"),
    ):
        got = running.build_actual(days, data, start=START, n=3, band=band)
        assert got is not None and got["final"] and got["verdict"]["key"] == key
    assert running.verdict_of(1.0, None) is None


# ---------------------------------------------------------------------------- F7.6 (pure)


def test_overlapping_sets_of_a_product_are_one_group_and_the_rest_stay_apart():
    a = _cs(START, 14)
    b = _cs(START + timedelta(days=3), 7)
    cut = _cs(
        START + timedelta(days=30),
        7,
        status="cut",
        result={"cut_by_change_set": None, "state": "inconclusive"},
    )
    later = _cs(START + timedelta(days=30), 7)
    cut.result["cut_by_change_set"] = str(later.id)  # an old cut links its cutter
    apart = _cs(START + timedelta(days=60), 7)
    other_product = _cs(START, 14, product="999")
    shop_wide = _cs(START, 14, scope="shop")
    groups = running.group_sets([apart, later, b, a, cut, other_product, shop_wide])
    sets = sorted((sorted(s.id for s in g.sets), g) for g in groups)
    multi = [g for g in groups if len(g.sets) > 1]
    assert {frozenset(s.id for s in g.sets) for g in multi} == {
        frozenset({a.id, b.id}),
        frozenset({cut.id, later.id}),
    }
    assert len(groups) == 5 and len(sets) == 5
    g = next(g for g in multi if a in g.sets)
    assert g.primary is a and g.start == START and g.days == 14
    assert g.end_excl == START + timedelta(days=14)


def test_a_reset_or_empty_set_is_not_grouped():
    a = _cs(START, 14)
    gone = _cs(START + timedelta(days=1), 14)
    gone.card_ids = []
    assert [len(g.sets) for g in running.group_sets([a, gone])] == [1]
    cut_plain = _cs(START + timedelta(days=1), 14, status="cut", result={"state": "kept_partial"})
    assert [len(g.sets) for g in running.group_sets([a, cut_plain])] == [1]


# ------------------------------------------------------------------------- DB: regroup, daily


async def _seed_rows(session, sid, first: date, last: date, *, item_profit=10_000.0):
    d = first
    while d <= last:
        session.add(
            ShopeeShopMetricsDaily(
                shop_id=sid, day=d, order_type="confirmed", gmv=D(500_000), orders=10,
                profit=D(50_000), ads_spend=D(0), complete=True,
            )
        )  # fmt: skip
        after = d >= START
        session.add(
            ShopeeProductMetricsDaily(
                shop_id=sid, day=d, order_type="confirmed", item_id=ITEM,
                gmv=D(100_000), orders=2 if not after else 1,
                profit=D(25_000 if not after else 5_000),  # profit is already after ads
                ads_spend=D(5_000),
                source="order_lines",
            )
        )  # fmt: skip
        d += timedelta(days=1)
    await session.flush()


async def _set(session, sid, start, days, **kw):
    cs = ShopRecoChangeSet(
        id=uuid.uuid4(), shop_id=sid, scope="product", product_id=ITEM,
        executed_on=start.date(), started_at=start, card_ids=[str(uuid.uuid4())],
        window_days=days, window_source="auto", status=kw.pop("status", "measuring"),
        with_shop_wide=False, predicted={}, created_at=start, updated_at=start, **kw,
    )  # fmt: skip
    session.add(cs)
    await session.flush()
    return cs


async def test_daily_job_rereads_a_cut_set_as_a_group_and_writes_running_thuc_te(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    sid = shop.id
    await _seed_rows(session, sid, START - timedelta(days=10), START + timedelta(days=6))
    first = await _set(session, sid, datetime(2026, 11, 12, 9), 14)
    second = await _set(session, sid, datetime(2026, 11, 14, 9), 7)
    # an old release cut the first set when the second started
    first.status = "cut"
    first.cut_at = second.started_at
    first.cut_days = 2
    first.result = {"state": "inconclusive", "label": "Không kết luận",
                    "cut_by_change_set": str(second.id)}  # fmt: skip
    now = datetime(2026, 11, 19, 7)
    grouping = await running.regroup(session, sid, now)
    assert len(grouping.multi) == 1 and first.status == "measuring" and first.cut_at is None
    assert first.cut_days is None and first.result["group"]["id"] == str(first.id)
    assert first.result["group"]["change_sets"] == [str(first.id), str(second.id)]
    assert first.result["clean"] is False and second.result["clean"] is False
    n = await running.refresh_actuals(session, sid, now, grouping)
    assert n == 2
    actual = first.result["actual"]
    assert actual == second.result["actual"]  # one result for the group
    assert actual["days"] == 14 and actual["days_measured"] == 7
    assert actual["label"] == "Đã đo 7/14 ngày" and first.result["label"] == actual["label"]
    p = actual["metrics"][
        "profit"
    ]  # the stored product profit is already after ads: 25k x7 -> 5k x7
    assert p["hien_tai"] == 175_000 and p["thuc_te"] == 35_000 and p["delta"] == -140_000
    assert (
        actual["metrics"]["orders"]["hien_tai"] == 14
        and actual["metrics"]["orders"]["thuc_te"] == 7
    )
    assert grouping.grouped_ids == {first.id, second.id}


async def test_a_single_set_gets_its_running_thuc_te_and_the_apis_expose_it(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    sid = shop.id
    await _seed_rows(session, sid, START - timedelta(days=10), START + timedelta(days=3))
    cs = await _set(session, sid, datetime(2026, 11, 12, 9), 7)
    now = datetime(2026, 11, 16, 7)
    grouping = await running.regroup(session, sid, now)
    assert grouping.multi == []
    await running.refresh_actuals(session, sid, now, grouping)
    assert cs.result["actual"]["days_measured"] == 4
    assert cs.result["actual"]["metrics"]["gmv"]["thuc_te"] == 400_000
    assert "group" not in cs.result
    states = await _states(session, sid, cs)
    assert states["actual"]["days_measured"] == 4 and states["group"] is None


async def _states(session, sid, cs):
    from juli_backend.services.shopee_recommendations import service

    out = await service.measurement_states(session, sid, [uuid.UUID(cs.card_ids[0])])
    return out[cs.card_ids[0]]


async def test_group_sets_expose_the_group_to_every_member_card(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    sid = shop.id
    await _seed_rows(session, sid, START - timedelta(days=10), START + timedelta(days=3))
    a = await _set(session, sid, datetime(2026, 11, 12, 9), 7)
    b = await _set(session, sid, datetime(2026, 11, 13, 9), 7)
    await running.regroup(session, sid, datetime(2026, 11, 14))
    out = await _states(session, sid, a)
    assert out["group"]["id"] == str(a.id) and out["clean"] is False
    assert out["measured_with"] == []  # members without a stored proposal carry no code yet
    assert out["group"]["members"][1]["card_id"] == b.card_ids[0]


# -------------------------------------------------------------- F7.7: the clean gate (L-3 / L-5)


def _traffic(first: date, n: int) -> dict[date, measure.DayAgg]:
    return {first + timedelta(days=i): measure.DayAgg(views=100, clicks=5) for i in range(n)}


async def test_clean_needs_no_other_change_no_sale_day_and_five_traffic_days_each_side(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    t = date(2026, 10, 1)
    full = _traffic(t - timedelta(days=7), 15)
    ok = await measure.clean_reasons(session, shop.id, full, t=t, days=7, pre=7, stacked=False)
    assert ok == []
    stacked = await measure.clean_reasons(session, shop.id, full, t=t, days=7, pre=7, stacked=True)
    assert stacked == ["other_change"]
    thin = _traffic(t - timedelta(days=3), 9)  # 3 days before, 5 after
    got = await measure.clean_reasons(session, shop.id, thin, t=t, days=7, pre=7, stacked=False)
    assert got == ["traffic_days_before"]
    cut = await measure.clean_reasons(
        session, shop.id, full, t=t, days=7, pre=7, stacked=False, partial=True
    )
    assert cut == ["partial"]
    sale_t = date(2026, 11, 5)  # the 11.11 window falls inside the 7 days after
    full_sale = _traffic(sale_t - timedelta(days=7), 15)
    sale = await measure.clean_reasons(
        session, shop.id, full_sale, t=sale_t, days=7, pre=7, stacked=False
    )
    assert sale == ["sale_day"]


async def test_a_group_result_is_read_but_feeds_no_calibration(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    sid = shop.id
    a = await _set(session, sid, datetime(2026, 10, 1, 9), 3)
    b = await _set(session, sid, datetime(2026, 10, 2, 9), 3)
    grouping = running.Grouping(running.group_sets([a, b]))
    report = measure.LearningReport()
    # nothing is verified (no cards): the group is skipped, never an observation
    obs = await measure.read_groups(session, sid, date(2026, 11, 1), report, grouping)
    assert obs == []
    assert change_sets.SET_MEASURING == a.status
