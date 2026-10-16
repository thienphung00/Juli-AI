"""D45 (fast track P36, Ops only): simulator research priorities in the D34 group code.

- D45.6: the pre-period adjustment follows the group size -- plain change (θ = 1)
  below 15 measured products, ANCOVA on two pre-period windows from 15 (the P31
  single fitted θ when the second window is missing); the false-alarm replay runs
  the same rule (pool entries may be triples).
- D45.2: every verdict also reads all-channel AOV and items per order; a group with a
  CTR guard warns when the product-card CTR falls > 15 % treated vs control.
- D45.1: Ops creates a group for a lever Juli never proposes ("Quy cách mới"), with
  the seeded ≈ 1/3 control; the seller never sees it; its products are never drawn
  into a card group.
- D45.3 / D45.4: the one-line "lý do chọn thử nghiệm"; the weekly-drift floor of the
  90 % interval next to the traffic needed.

Synthetic fixtures only (no shop data).
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.card_groups import ARM_CONTROL, ARM_TREATED, CardGroup, CardGroupMember
from juli_backend.models.models import ActionCard, AnalyticsPerformanceInterval
from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.action_cards import card_groups
from juli_backend.services.action_cards.card_groups import (
    GUARD_DROP_PCT,
    SOURCE_OPS,
    GroupDesign,
    GroupError,
    GroupKey,
    apply_groups,
    build_verdict,
    create_ops_group,
    group_views,
    guard_check,
    measure_due_groups,
    metric_specs,
    seller_sentences,
    set_group_reason,
)
from juli_backend.services.action_cards.group_design import (
    ORDER_VALUE_CV,
    Z90,
    drift_floor,
    traffic_needed,
)
from juli_backend.services.action_cards.group_stats import (
    ADJUST_CHANGE,
    ADJUST_ONE_WINDOW,
    ADJUST_TWO_WINDOWS,
    NULL_PRE_PERIOD,
    TWO_WINDOW_MIN_PRODUCTS,
    Unit,
    adjust_changes,
    cuped_adjust,
    false_alarm_rate,
    null_pool,
)
from juli_backend.services.optimize_product.tunables import (
    GROUP_DRIFT_SIGMA,
    GROUP_GUARD_CTR_DROP,
    GROUP_TWO_WINDOW_MIN,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from tests.support.builders import make_product, make_tenant

AS_OF = date(2026, 10, 16)
START = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)  # 09:00 in Vietnam
LAUNCH = date(2026, 10, 16)
PACK = GroupKey("aov", "pack_option", "total")


# =========================================================================== D45.6 rule


def _units(n: int, *, seed: int, with_pre: bool = True) -> list[Unit]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        level = 0.03 * math.exp(rng.gauss(0, 0.4))
        pre = level * math.exp(rng.gauss(0, 0.15))
        before = level * math.exp(rng.gauss(0, 0.15))
        after = level * math.exp(rng.gauss(0, 0.15))
        out.append(
            Unit(ARM_TREATED if i % 3 else ARM_CONTROL, before, after, pre if with_pre else None)
        )
    return out


def test_a_small_group_reads_the_plain_change():
    units = _units(6, seed=1)
    adj = adjust_changes(units)
    assert adj.method == ADJUST_CHANGE and adj.theta == 1.0 and adj.theta_pre is None
    assert adj.changes == pytest.approx([u.change_pct for u in units])
    # 14 products is still "small" (the threshold is 15).
    assert TWO_WINDOW_MIN_PRODUCTS == 15
    assert adjust_changes(_units(14, seed=2)).method == ADJUST_CHANGE


def test_a_large_group_uses_two_pre_period_windows():
    # ln after = 0.6 ln before + 0.3 ln pre + c exactly -> the slopes are recovered and
    # every adjusted change is the same number.
    rng = random.Random(3)
    units = []
    for i in range(17):
        x, z = math.log(0.03) + rng.gauss(0, 0.3), math.log(0.03) + rng.gauss(0, 0.3)
        y = -1.0 + 0.6 * x + 0.3 * z
        units.append(
            Unit(ARM_TREATED if i < 11 else ARM_CONTROL, math.exp(x), math.exp(y), math.exp(z))
        )
    adj = adjust_changes(units)
    assert adj.method == ADJUST_TWO_WINDOWS
    assert adj.theta == pytest.approx(0.6, abs=1e-9)
    assert adj.theta_pre == pytest.approx(0.3, abs=1e-9)
    assert max(adj.changes) - min(adj.changes) == pytest.approx(0.0, abs=1e-9)
    assert adj.to_json()["method"] == "two_windows"


def test_a_large_group_without_the_second_window_keeps_the_p31_theta():
    units = _units(20, seed=4, with_pre=False)
    adj = adjust_changes(units)
    changes, theta = cuped_adjust(units)
    assert adj.method == ADJUST_ONE_WINDOW
    assert adj.theta == pytest.approx(theta) and adj.changes == pytest.approx(changes)
    # One product missing its pre window is enough to fall back.
    mixed = [*_units(19, seed=5), Unit(ARM_CONTROL, 0.03, 0.031)]
    assert adjust_changes(mixed).method == ADJUST_ONE_WINDOW


def test_the_threshold_is_a_parameter_and_none_is_the_p31_rule():
    units = _units(8, seed=6)
    assert adjust_changes(units, two_window_min=8).method == ADJUST_TWO_WINDOWS
    p31 = adjust_changes(units, two_window_min=None)
    assert p31.method == ADJUST_ONE_WINDOW
    assert p31.changes == pytest.approx(cuped_adjust(units)[0])


def test_the_null_pool_keeps_triples_and_the_replay_runs_the_same_rule():
    pool, source = null_pool(
        [(0.02, 0.03, 0.031), (None, 0.03, 0.029), (0.0, 0.03, 0.033), (0.03, 0.028)], []
    )
    assert source == NULL_PRE_PERIOD
    # A missing / non-positive earlier window keeps the pair.
    assert pool == [(0.02, 0.03, 0.031), (0.03, 0.029), (0.03, 0.033), (0.03, 0.028)]
    rng = random.Random(7)
    triples = [
        (
            0.03 * math.exp(rng.gauss(0, 0.2)),
            0.03 * math.exp(rng.gauss(0, 0.2)),
            0.03 * math.exp(rng.gauss(0, 0.2)),
        )
        for _ in range(30)
    ]
    a = false_alarm_rate(triples, 12, 6, seed=9, source=NULL_PRE_PERIOD, draws=60)
    b = false_alarm_rate(triples, 12, 6, seed=9, source=NULL_PRE_PERIOD, draws=60)
    assert a is not None and a == b and 0.0 <= a.rate <= 1.0
    # The same pool replayed under the P31 rule is a different (valid) number set-up.
    c = false_alarm_rate(
        triples, 12, 6, seed=9, source=NULL_PRE_PERIOD, draws=60, two_window_min=None
    )
    assert c is not None and 0.0 <= c.rate <= 1.0


def _rows(n_t: int, n_c: int, *, seed: int, lift: float) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for i in range(n_t + n_c):
        arm = ARM_TREATED if i < n_t else ARM_CONTROL
        level = 0.03 * math.exp(rng.gauss(0, 0.3))
        pp, p, b = (level * math.exp(rng.gauss(0, 0.1)) for _ in range(3))
        a = level * math.exp(rng.gauss(0, 0.1)) * (1 + (lift if arm == ARM_TREATED else 0))
        rows.append(
            {
                "product_id": f"p{i:02d}",
                "arm": arm,
                "approved": False,
                "pre_pre_before": pp,
                "pre_before": p,
                "before": b,
                "after": a,
                "change_pct": round((a / b - 1) * 100, 2),
            }
        )
    return rows


def test_the_verdict_records_which_rule_ran():
    small = build_verdict(_rows(4, 2, seed=1, lift=0.2), seed=5, as_of=AS_OF)
    assert small["adjustment"]["method"] == ADJUST_CHANGE
    assert small["adjustment"]["two_window_min"] == 15
    assert small["cuped"]["theta"] == 1.0  # the P31 field keeps its shape
    large = build_verdict(_rows(17, 9, seed=2, lift=0.4), seed=5, as_of=AS_OF)
    assert large["adjustment"]["method"] == ADJUST_TWO_WINDOWS
    assert large["adjustment"]["theta_pre"] is not None
    assert large["primary"]["difference"] == pytest.approx(40, abs=12)
    # Its pre-period pairs are triples (days −42..−29 known) -> the replay can use them.
    assert large["false_alarm"]["pool"] == 26
    lowered = build_verdict(_rows(4, 2, seed=1, lift=0.2), seed=5, as_of=AS_OF, two_window_min=4)
    assert lowered["adjustment"]["method"] == ADJUST_TWO_WINDOWS


# =========================================================================== D45.4 design


def test_the_drift_floor_matches_the_research_table():
    floor6 = drift_floor(4, 2, 2)
    assert floor6.to_json()["pooled_pct"] == 10.1  # 6 products × 2 weeks
    assert drift_floor(17, 9, 2).to_json()["pooled_pct"] == 4.8  # 26 × 2 weeks
    assert drift_floor(4, 2, 4).to_json()["pooled_pct"] == 7.1  # 6 × 4 weeks
    # Read as treated − control it is wider: z·√(2σ²/w·(1/4 + 1/2)).
    expected = Z90 * math.sqrt(2 * 0.15**2 / 2 * (1 / 4 + 1 / 2))
    assert floor6.difference == pytest.approx(expected)
    assert floor6.to_json()["difference_pct"] == 21.4
    assert drift_floor(0, 0, 2) is None


def test_traffic_needed_with_and_without_drift():
    totals = {"impressions": 100_000, "clicks": 4_000, "orders": 200}
    big = drift_floor(17, 9, 2)
    ctr = traffic_needed("ctr", totals, floor=big)
    req0 = 2 * Z90**2 / 0.1**2
    assert ctr["unit"] == "impressions" and ctr["reachable"] is True
    assert ctr["no_drift"] == math.ceil(req0 * 0.96 / 0.04)
    assert ctr["with_drift"] > ctr["no_drift"]
    # 6 products × 2 weeks: the floor (10.1 %) alone is wider than ±10 %.
    small = traffic_needed("ctr", totals, floor=drift_floor(4, 2, 2))
    assert small["reachable"] is False and small["with_drift"] is None
    aov = traffic_needed("aov", totals, floor=None)
    assert aov["unit"] == "orders" and aov["no_drift"] == math.ceil(req0 * ORDER_VALUE_CV**2)
    ctor = traffic_needed("ctor", totals, floor=None)
    assert ctor["no_drift"] == math.ceil(req0 * (1 - 0.05) / 0.05 / 0.04)
    assert traffic_needed("items_per_order", totals, floor=None) is None
    assert traffic_needed("ctr", {"impressions": 0}, floor=None) is None


# =========================================================================== D45.2 guard


def test_the_ctr_guard_warns_even_when_aov_rises():
    primary = {"difference": 12.0}
    warn = guard_check(PACK, primary, {"difference": -18.0})
    assert warn["warning"] is True and warn["max_drop_pct"] == GUARD_DROP_PCT == 15.0
    assert "giảm 18 %" in warn["text"] and "dù AOV tăng 12 %" in warn["text"]
    fine = guard_check(PACK, primary, {"difference": -10.0})
    assert fine["warning"] is False
    assert guard_check(PACK, primary, {"difference": None})["warning"] is False
    stricter = guard_check(PACK, primary, {"difference": -10.0}, max_drop_pct=5)
    assert stricter["warning"] is True


def test_which_metrics_a_group_reads():
    cards = GroupDesign()
    assert metric_specs(GroupKey("ctr", "cover_image", "product_card"), cards) == [
        ("aov", "total"),
        ("items_per_order", "total"),
    ]
    ops = GroupDesign(source=SOURCE_OPS, guard=True)
    assert metric_specs(PACK, ops) == [("items_per_order", "total"), ("ctr", "product_card")]


def test_tunables_defaults_and_bounds():
    t = DiagTunables()
    assert (t.group_two_window_min, t.group_guard_ctr_drop, t.group_drift_sigma) == (15, 15.0, 0.15)
    assert validate_tunable(GROUP_TWO_WINDOW_MIN, 20) == 20
    assert validate_tunable(GROUP_GUARD_CTR_DROP, 10) == 10.0
    assert validate_tunable(GROUP_DRIFT_SIGMA, 0.1) == 0.1
    for key, bad in (
        (GROUP_TWO_WINDOW_MIN, 2),
        (GROUP_TWO_WINDOW_MIN, 15.5),
        (GROUP_GUARD_CTR_DROP, 0),
        (GROUP_DRIFT_SIGMA, 2),
    ):
        with pytest.raises(TunableError):
            validate_tunable(key, bad)
    over = DiagTunables.from_overrides({GROUP_TWO_WINDOW_MIN: 30, GROUP_DRIFT_SIGMA: "x"})
    assert over.group_two_window_min == 30 and over.group_drift_sigma == 0.15


# =========================================================================== with the DB


@pytest_asyncio.fixture
async def shop(session):
    _user, shop = await make_tenant(session)
    return shop


async def _products(session, shop, n: int) -> list[str]:
    ids = [f"pk{i:02d}" for i in range(n)]
    for pid in ids:
        await make_product(session, shop, tiktok_product_id=pid, name=f"Sản phẩm {pid}")
    return ids


def _row(shop_id, product, day, *, impressions, clicks, card_impr, card_clicks, orders, items, gmv):
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"t:{product}:{day.isoformat()}",
        grain="product",
        start_date=day,
        end_date=day + timedelta(days=1),
        tiktok_product_id=product,
        impressions=impressions,
        clicks=clicks,
        sku_orders=orders,
        items_sold=items,
        gmv=Decimal(gmv),
        traffic_breakdown={
            "PRODUCT_CARD": {"impressions": card_impr, "clicks": card_clicks},
            "VIDEO": {"impressions": impressions - card_impr, "clicks": clicks - card_clicks},
        },
        update_time=datetime(2026, 10, 1),
    )


async def _pack_data(session, shop_id, arms, *, aov_lift, ctr_drop):
    """42 days before launch to day 13: steady products; after launch the treated AOV
    and items per order rise by ``aov_lift`` and their card CTR falls by ``ctr_drop``."""
    for product, arm in arms.items():
        k = int(product[-2:])
        for offset in range(-42, 14):
            day = LAUNCH + timedelta(days=offset)
            wobble = 1 + 0.01 * ((k * 7 + offset) % 5 - 2)
            treated_after = arm == ARM_TREATED and offset >= 0
            orders = 10
            per_order = 200_000 * wobble * (1 + aov_lift if treated_after else 1)
            items = round(10 * wobble * (1 + aov_lift if treated_after else 1))
            card_ctr = 0.04 * wobble * (1 - ctr_drop if treated_after else 1)
            session.add(
                _row(
                    shop_id,
                    product,
                    day,
                    impressions=5000,
                    clicks=200,
                    card_impr=2000,
                    card_clicks=round(2000 * card_ctr),
                    orders=orders,
                    items=items,
                    gmv=round(orders * per_order),
                )
            )
    await session.flush()


@pytest.mark.asyncio
async def test_ops_creates_a_pack_group_with_a_seeded_control(session, shop, monkeypatch):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 777)
    products = await _products(session, shop, 6)
    group = await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=[*products, products[0], " "],
        reason="  Thêm quy cách ×2 (−5 %/đơn vị):\nphương án đầu ở 25/26 sp  ",
        guard=None,
        created_by="ops@app-juli.com",
        now=START,
    )
    assert (group.group_key, group.seed, group.launched_on) == (
        "aov|pack_option|total",
        777,
        LAUNCH,
    )
    assert group.release_on == LAUNCH + timedelta(days=14)
    design = GroupDesign.of(group)
    assert design.ops and design.guard is True  # AOV primary -> CTR guard on
    assert design.reason == "Thêm quy cách ×2 (−5 %/đơn vị): phương án đầu ở 25/26 sp"
    members = (await session.execute(select(CardGroupMember))).scalars().all()
    assert {m.tiktok_product_id: m.arm for m in members} == card_groups.assign_arms(products, 777)
    assert sum(m.arm == ARM_CONTROL for m in members) == 2  # 4 + 2
    assert all(m.action_card_id is None for m in members)


@pytest.mark.asyncio
async def test_ops_group_requests_that_are_refused(session, shop):
    products = await _products(session, shop, 6)
    kwargs = dict(metric="aov", channel="total", reason=None, guard=None, created_by="x", now=START)
    with pytest.raises(GroupError, match="ít nhất 3"):
        await create_ops_group(
            session, shop.id, lever="pack_option", product_ids=products[:2], **kwargs
        )
    with pytest.raises(GroupError, match="Không có trong shop: zz"):
        await create_ops_group(
            session, shop.id, lever="pack_option", product_ids=[*products[:3], "zz"], **kwargs
        )
    with pytest.raises(GroupError, match="Đòn bẩy"):
        await create_ops_group(
            session, shop.id, lever="write_to_tiktok", product_ids=products, **kwargs
        )
    with pytest.raises(GroupError, match="200 ký tự"):
        await create_ops_group(
            session,
            shop.id,
            lever="pack_option",
            product_ids=products,
            **{**kwargs, "reason": "x" * 201},
        )
    await create_ops_group(
        session, shop.id, lever="pack_option", product_ids=products[:3], **kwargs
    )
    # Two experiments never share a product (D45.1: "different products").
    with pytest.raises(GroupError, match="nhóm thử nghiệm khác: pk02"):
        await create_ops_group(
            session, shop.id, lever="cover_image", product_ids=products[2:], **kwargs
        )


@pytest.mark.asyncio
async def test_a_pack_group_measures_aov_items_and_warns_on_ctr(session, shop, monkeypatch):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 777)
    products = await _products(session, shop, 6)
    group = await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=products,
        reason=None,
        guard=None,
        created_by="x",
        now=START,
    )
    arms = card_groups.assign_arms(products, 777)
    await _pack_data(session, shop.id, arms, aov_lift=0.25, ctr_drop=0.2)
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    assert measured.id == group.id
    verdict = measured.verdict
    assert verdict["primary"]["difference"] == pytest.approx(25, abs=3)
    assert verdict["adjustment"]["method"] == ADJUST_CHANGE  # 6 products: plain change
    assert set(verdict["metrics"]) == {"items_per_order|total", "ctr|product_card"}
    items = verdict["metrics"]["items_per_order|total"]
    assert items["label"] == "Số món mỗi đơn · tất cả kênh"
    assert items["primary"]["difference"] == pytest.approx(25, abs=4)
    assert items["false_alarm"] is not None and items["adjustment"]["method"] == ADJUST_CHANGE
    guard = verdict["guard"]
    assert guard["warning"] is True and guard["difference"] == pytest.approx(-20, abs=3)
    assert "dù AOV tăng" in guard["text"]
    # The seller never sees an Ops group.
    assert await seller_sentences(session, shop.id) == {}
    [view] = await group_views(session, shop.id)
    assert view["seller_sentence"] is None
    assert view["design"]["source"] == "ops"
    assert view["members"][0]["product_title"].startswith("Sản phẩm pk")
    plan = view["plan"]
    assert plan["floor"] == {"pooled_pct": 10.1, "difference_pct": 21.4}
    assert plan["needed_per_arm"]["unit"] == "orders"
    assert plan["have_before"][ARM_TREATED]["orders"] == 4 * 10 * 14
    assert plan["have_before"][ARM_CONTROL]["impressions"] == 2 * 5000 * 14


@pytest.mark.asyncio
async def test_a_large_card_group_uses_two_windows_and_reads_aov(session, shop):
    """A 17 + 9 CTR group drawn from cards: two pre-period windows (days −42..−1 in
    the data), plus all-channel AOV and items per order; no guard (CTR is primary)."""
    group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop.id,
        group_key="ctr|cover_image|product_card",
        metric="ctr",
        lever="cover_image",
        channel="product_card",
        launched_on=LAUNCH,
        release_on=LAUNCH + timedelta(days=14),
        seed=31,
        status="open",
    )
    session.add(group)
    arms = {f"pk{i:02d}": (ARM_TREATED if i < 17 else ARM_CONTROL) for i in range(26)}
    for product, arm in arms.items():
        session.add(
            CardGroupMember(
                id=uuid.uuid4(),
                shop_id=shop.id,
                group_id=group.id,
                tiktok_product_id=product,
                action_card_id=None,
                arm=arm,
                assigned_at=datetime(2026, 10, 16),
            )
        )
    await _pack_data(session, shop.id, arms, aov_lift=0.0, ctr_drop=-0.3)  # CTR +30 %
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    verdict = measured.verdict
    assert verdict["adjustment"]["method"] == ADJUST_TWO_WINDOWS
    assert verdict["primary"]["difference"] == pytest.approx(30, abs=4)
    assert set(verdict["metrics"]) == {"aov|total", "items_per_order|total"}
    assert verdict["metrics"]["aov|total"]["primary"]["difference"] == pytest.approx(0, abs=3)
    assert "guard" not in verdict
    # The null pool's pre-period entries are triples, so the replay ran two windows too.
    assert verdict["null_pool"]["pre_period"] == 26


@pytest.mark.asyncio
async def test_ops_group_products_are_never_drawn_into_a_card_group(session, shop):
    products = await _products(session, shop, 3)
    await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=products,
        reason=None,
        guard=None,
        created_by="x",
        now=START,
    )
    drafts = []
    for i, pid in enumerate(products):
        payload = {
            "target_metric": "ctr",
            "kpi": {"metric": "ctr", "channel": "total"},
            "diagnosis": {"lever": {"code": "cover_image"}, "tiktok_product_id": pid},
        }
        drafts.append(
            ActionCard(
                id=uuid.uuid4(),
                shop_id=shop.id,
                workflow_key="optimize_product_2",
                subject_type="product_lever",
                subject_id=f"{pid}:cover_image",
                priority=i + 1,
                severity="warning",
                title=f"card {pid}",
                description="",
                recommendation_payload=json.dumps(payload),
                status="active",
            )
        )
    session.add_all(drafts)
    await session.flush()
    passed = await apply_groups(session, shop.id, drafts, now=START + timedelta(days=1))
    assert passed.launched == [] and passed.held == []  # surfaced as before, ungrouped
    assert [c.id for c in passed.eligible] == [c.id for c in drafts]


@pytest.mark.asyncio
async def test_the_reason_is_set_and_cleared(session, shop):
    products = await _products(session, shop, 3)
    group = await create_ops_group(
        session,
        shop.id,
        lever="pack_option",
        metric="aov",
        channel="total",
        product_ids=products,
        reason=None,
        guard=False,
        created_by="x",
        now=START,
    )
    assert GroupDesign.of(group).guard is False
    _g, before, after = await set_group_reason(session, shop.id, group.id, " KG: thử tiếp theo ")
    assert (before, after) == (None, "KG: thử tiếp theo")
    _g, before, after = await set_group_reason(session, shop.id, group.id, "")
    assert (before, after) == ("KG: thử tiếp theo", None)
    with pytest.raises(LookupError):
        await set_group_reason(session, shop.id, uuid.uuid4(), "x")
    # A card group (design NULL) can carry a reason too.
    card_group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop.id,
        group_key="ctr|title|total",
        metric="ctr",
        lever="title",
        channel="total",
        launched_on=LAUNCH,
        release_on=LAUNCH,
        seed=1,
        status="open",
    )
    session.add(card_group)
    await session.flush()
    await set_group_reason(session, shop.id, card_group.id, "Lý do")
    assert GroupDesign.of(card_group).reason == "Lý do" and not GroupDesign.of(card_group).ops


# =========================================================================== Ops routes


async def _client(session, monkeypatch, role: str):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


@pytest.mark.asyncio
async def test_ops_routes_create_and_annotate_a_group(session, shop, monkeypatch):
    from tests.support.api import client_for

    products = await _products(session, shop, 6)
    shop_id = shop.id  # a refused request rolls back and expires the ORM objects
    viewer = await _client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        refused = await client.post(
            f"/v1/ops/shops/{shop_id}/groups", json={"product_ids": products}
        )
    assert refused.status_code == 403
    app = await _client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        bad = await client.post(
            f"/v1/ops/shops/{shop_id}/groups", json={"product_ids": products[:2]}
        )
        assert bad.status_code == 422 and "ít nhất 3" in bad.json()["detail"]
        made = await client.post(
            f"/v1/ops/shops/{shop_id}/groups",
            json={"product_ids": products, "reason": "Nhóm quy cách đầu tiên"},
        )
        assert made.status_code == 200
        body = made.json()
        [group] = body["groups"]
        assert group["id"] == body["created"]
        assert group["label"] == "AOV · Quy cách mới · tất cả kênh"
        assert (group["treated"], group["control"]) == (4, 2)
        assert group["design"]["reason"] == "Nhóm quy cách đầu tiên"
        assert group["plan"]["floor"]["pooled_pct"] == 10.1
        patched = await client.patch(
            f"/v1/ops/shops/{shop_id}/groups/{group['id']}", json={"reason": "Chọn theo KG"}
        )
        assert patched.status_code == 200
        assert patched.json()["groups"][0]["design"]["reason"] == "Chọn theo KG"
        missing = await client.patch(
            f"/v1/ops/shops/{shop_id}/groups/{uuid.uuid4()}", json={"reason": "x"}
        )
        assert missing.status_code == 404
    actions = sorted(r.action for r in (await session.execute(select(OpsAuditLog))).scalars().all())
    assert actions == ["card_group_create", "card_group_reason"]
