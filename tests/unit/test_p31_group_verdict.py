"""D41.3 (T3A, fast track P31): the stricter group verdict.

90 % bootstrap interval; below 5 controls an exact permutation test over the random
assignment must also reject; each change CUPED-adjusted by the product's previous 14
days; "Sơ bộ" (or a full verdict) only when the group's own simulated false-alarm rate
is not above 15 % (T3.1), else "Đang đo" with no strength claim -- re-gated at every
measurement as the control's untouched post-launch data join the null pool. Synthetic
fixtures only.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import combinations
from statistics import median

import pytest
import pytest_asyncio

from juli_backend.models.card_groups import CardGroup, CardGroupMember
from juli_backend.models.models import ActionCard, AnalyticsPerformanceInterval
from juli_backend.services.action_cards.card_groups import (
    LABEL_MEASURING,
    LABEL_PRELIMINARY,
    GroupKey,
    build_verdict,
    compare,
    measure_due_groups,
    seller_sentence,
)
from juli_backend.services.action_cards.group_stats import (
    FALSE_ALARM_DRAWS,
    FALSE_ALARM_MAX,
    INTERVAL_HIGH,
    INTERVAL_LOW,
    NULL_CENTRED,
    NULL_PRE_AND_CONTROL,
    NULL_PRE_PERIOD,
    FalseAlarm,
    Unit,
    cuped_adjust,
    cuped_theta,
    false_alarm_rate,
    null_pool,
    permutation_test,
)

AS_OF = date(2026, 10, 13)
KEY = GroupKey("ctr", "cover_image", "product_card")


# =========================================================================== permutation


def test_the_permutation_test_enumerates_every_assignment():
    treated, control = [5.0, 7.0, 9.0], [1.0, 2.0]
    perm = permutation_test(treated, control, rng=random.Random(0))
    assert perm.exact and perm.draws == math.comb(5, 2) == 10
    # By hand: every choice of 2 controls among the 5 values.
    values = [*treated, *control]
    observed = abs(median(treated) - median(control))
    hits = 0
    for chosen in combinations(range(5), 2):
        c = [values[i] for i in chosen]
        t = [values[i] for i in range(5) if i not in chosen]
        hits += abs(median(t) - median(c)) >= observed - 1e-9
    assert perm.p_value == pytest.approx(hits / 10)
    # The most extreme split among 10 cannot go below 1/10.
    assert perm.p_value >= 0.1


def test_a_large_assignment_space_is_sampled_not_enumerated():
    treated = [float(i) for i in range(30)]
    control = [100.0, 101.0, 102.0, 103.0]
    perm = permutation_test(treated, control, rng=random.Random(1), exact_max=1_000)
    assert not perm.exact and perm.draws == 10_000
    assert perm.p_value < 0.01  # the 4 highest as control: rare under re-assignment


def test_below_five_controls_the_permutation_test_must_also_reject():
    out = compare([20.0, 21.0, 22.0, 23.0], [0.0, 1.0, 2.0, 3.0], seed=5)
    assert out["test"] == "permutation" and out["permutation"]["exact"]
    assert out["permutation"]["draws"] == 70
    assert out["permutation"]["p_value"] <= 0.1
    assert out["detected"] and out["strength"] in ("clear", "likely")
    # Five controls: the bootstrap grade alone, as in P30.
    five = compare([20.0, 21.0, 22.0, 23.0, 24.0], [0.0, 1.0, 2.0, 3.0, 4.0], seed=5)
    assert five["test"] == "bootstrap" and five["permutation"] is None


def test_the_interval_is_90_percent():
    assert (INTERVAL_LOW, INTERVAL_HIGH) == (0.05, 0.95)
    out = compare([5.0, -6.0, 1.0, 9.0, -4.0], [3.0, -2.0, 0.0, 4.0, -1.0], seed=7)
    assert out["interval_level"] == 0.9
    again = compare([5.0, -6.0, 1.0, 9.0, -4.0], [3.0, -2.0, 0.0, 4.0, -1.0], seed=7)
    assert again == out  # seeded: reproducible


# =========================================================================== CUPED


def test_cuped_with_theta_one_is_the_plain_change():
    units = [
        Unit("treated", 0.04, 0.044),
        Unit("control", 0.04, 0.041),
        Unit("treated", 0.04, 0.05),
    ]
    adjusted, theta = cuped_adjust(units)
    assert theta == 1.0  # no spread in the before values
    assert adjusted == pytest.approx([u.change_pct for u in units])


def test_cuped_removes_the_part_of_a_low_before_value_that_was_noise():
    # True level 4 % for every product; "before" is noisy, "after" is not. A product
    # chosen because it looked low (before 3 %) rebounds to 4 % with no lever at all.
    befores = [0.03, 0.035, 0.04, 0.045, 0.05, 0.04]
    units = [Unit("control" if i % 2 else "treated", b, 0.04) for i, b in enumerate(befores)]
    theta = cuped_theta(units)
    assert theta == pytest.approx(0.0, abs=1e-9)  # before predicts nothing of after
    adjusted, _ = cuped_adjust(units)
    raw = [u.change_pct for u in units]
    assert raw[0] == pytest.approx(33.33, abs=0.01)  # the plain change credits the rebound
    # Adjusted: everyone's after against the group's mean before -- the same small number.
    assert max(adjusted) - min(adjusted) == pytest.approx(0.0, abs=1e-9)
    assert abs(adjusted[0]) < 2.0


def test_cuped_theta_is_the_pooled_regression_slope():
    xs = [0.02, 0.03, 0.04, 0.05, 0.06]
    units = [Unit("treated", x, x**0.5) for x in xs]  # ln after = 0.5 ln before
    assert cuped_theta(units) == pytest.approx(0.5, abs=1e-9)
    clipped = [Unit("control", x, x**3) for x in xs]  # slope 3 -> clipped to 2
    assert cuped_theta(clipped) == 2.0


# =========================================================================== false alarm


def _group(n_treated, n_control, *, lift, noise, seed_data):
    """Products at varied CTR levels; pre / before / after each wobble by ``noise``."""
    rng = random.Random(seed_data)
    rows = []
    for i in range(n_treated + n_control):
        arm = "treated" if i < n_treated else "control"
        level = 0.03 * math.exp(rng.gauss(0, 0.3))
        pre = level * math.exp(rng.gauss(0, noise))
        before = level * math.exp(rng.gauss(0, noise))
        after = level * math.exp(rng.gauss(0, noise)) * (1 + (lift if arm == "treated" else 0))
        rows.append(
            {
                "product_id": f"p{i:02d}",
                "arm": arm,
                "approved": False,
                "pre_before": pre,
                "before": before,
                "after": after,
                "change_pct": round((after / before - 1) * 100, 2),
            }
        )
    return rows


def test_a_noisy_small_group_reads_dang_do():
    rows = _group(3, 5, lift=0.0, noise=0.3, seed_data=2)
    verdict = build_verdict(rows, seed=11, as_of=AS_OF)
    primary = verdict["primary"]
    fa = verdict["false_alarm"]
    assert fa["source"] == NULL_PRE_PERIOD and fa["draws"] == FALSE_ALARM_DRAWS
    assert fa["acceptable"] is False and fa["rate"] > FALSE_ALARM_MAX
    assert primary["label"] == LABEL_MEASURING
    assert primary["strength"] is None and primary["strength_label"] is None
    assert primary["false_alarm"] == fa
    # Numbers stay for Ops; the seller is told nothing.
    assert primary["difference"] is not None and primary["interval"] is not None
    assert seller_sentence(KEY, 8, verdict) is None


def test_a_large_clean_group_with_a_big_effect_reads_so_bo():
    rows = _group(12, 2, lift=0.3, noise=0.02, seed_data=0)
    verdict = build_verdict(rows, seed=11, as_of=AS_OF)
    primary = verdict["primary"]
    assert verdict["false_alarm"]["acceptable"] is True
    assert verdict["false_alarm"]["rate"] <= FALSE_ALARM_MAX
    assert primary["label"] == LABEL_PRELIMINARY  # 2 controls: still preliminary
    assert primary["test"] == "permutation" and primary["permutation"]["p_value"] <= 0.1
    assert primary["strength"] == "clear" and primary["detected"] is True
    assert primary["difference"] == pytest.approx(28, abs=4)
    assert 0.8 < verdict["cuped"]["theta"] < 1.2 and verdict["cuped"]["from_before_after"]
    assert all(p["adjusted_change_pct"] is not None for p in verdict["products"])
    assert seller_sentence(KEY, 14, verdict).endswith("(sơ bộ)")


def test_the_false_alarm_rate_is_seeded_and_falls_back_to_centred_changes():
    pool = [(1.0, math.exp(g)) for g in (0.05, -0.02, 0.03, -0.04, 0.01, 0.0, -0.01, 0.02)]
    a = false_alarm_rate(pool, 5, 3, seed=7, source=NULL_PRE_PERIOD, draws=100)
    b = false_alarm_rate(pool, 5, 3, seed=7, source=NULL_PRE_PERIOD, draws=100)
    assert isinstance(a, FalseAlarm) and a == b
    # Fewer than 3 usable pre-period pairs: each arm's adjusted changes, centred.
    centred, source = null_pool(
        [(0.03, 0.031)], [("treated", 10.0), ("treated", 12.0), ("control", 1.0), ("control", 3.0)]
    )
    assert source == NULL_CENTRED and len(centred) == 4
    logs = sorted(math.log(after) for _before, after in centred)
    assert logs[0] < 0 < logs[-1] and sum(1 for v in logs if v > 0) == 2


def test_rows_without_before_and_after_are_left_unadjusted():
    rows = [
        *(
            {"product_id": f"t{i}", "arm": "treated", "change_pct": v}
            for i, v in enumerate([6.0, 7.0, 8.0, 9.0, 10.0])
        ),
        *(
            {"product_id": f"c{i}", "arm": "control", "change_pct": v}
            for i, v in enumerate([-1.0, 0.0, 1.0, 2.0, 3.0])
        ),
    ]
    verdict = build_verdict(rows, seed=3, as_of=AS_OF)
    assert verdict["cuped"] == {"theta": 1.0, "from_before_after": False}
    assert [p["adjusted_change_pct"] for p in verdict["products"]] == pytest.approx(
        [p["change_pct"] for p in rows]
    )
    assert verdict["false_alarm"]["source"] == NULL_CENTRED


def test_the_gate_is_a_flat_15_percent():
    assert FALSE_ALARM_MAX == 0.15
    assert FalseAlarm(0.15, 500, NULL_PRE_PERIOD, 10).acceptable is True
    assert FalseAlarm(0.152, 500, NULL_PRE_PERIOD, 10).acceptable is False
    assert "margin" not in FalseAlarm(0.1, 500, NULL_PRE_PERIOD, 10).to_json()


# =========================================================================== T3.1 re-gating

#: A 5 + 5 group (found by a seeded search): the treated rose ≈ 32 %, the control held.
#: Its pre-period pairs are mostly flat with three large swings, so at day 14 the
#: replayed rule over-calls (> 15 %) -> "Đang đo"; the control's days 14–27 add five
#: moderate no-effect pairs, the pool looks like ordinary noise and the gate passes.
PRE = [0.01, 0.001, 0.561, 0.006, -0.003, 0.0, -0.593, -0.007, 0.007, -0.316]
LIFTS = [0.3, 0.31, 0.32, 0.33, 0.34, 0.008, 0.003, 0.005, 0.004, 0.005]
LATER = [-0.2737, 0.2889, 0.274, -0.148, -0.1991]  # control, days 14–27 vs 0–13


def _rows_5_5():
    rows = []
    for i, (pre, lift) in enumerate(zip(PRE, LIFTS, strict=True)):
        rows.append(
            {
                "product_id": f"p{i:02d}",
                "arm": "treated" if i < 5 else "control",
                "approved": False,
                "pre_before": 0.04 * (1 + pre),
                "before": 0.04,
                "after": 0.04 * (1 + lift),
                "change_pct": round(lift * 100, 2),
            }
        )
    return rows


def test_a_group_gated_at_day_14_can_pass_once_its_control_pool_grows():
    rows = _rows_5_5()
    controls = rows[5:]
    day14 = [(c["before"], c["after"]) for c in controls]
    day28 = [*day14, *((c["after"], c["after"] * (1 + d)) for c, d in zip(controls, LATER))]
    first = build_verdict(rows, seed=99, as_of=AS_OF, control_pairs=day14)
    assert first["false_alarm"]["source"] == NULL_PRE_AND_CONTROL
    assert first["null_pool"] == {"pre_period": 10, "control_after": 5}
    assert first["false_alarm"]["rate"] > FALSE_ALARM_MAX
    assert first["primary"]["label"] == LABEL_MEASURING
    later = build_verdict(
        rows,
        seed=99,
        as_of=AS_OF + timedelta(days=14),
        control_pairs=day28,
        history=first["checks"],
    )
    assert later["null_pool"] == {"pre_period": 10, "control_after": 10}
    assert later["false_alarm"]["rate"] <= FALSE_ALARM_MAX
    assert later["primary"]["label"] is None  # 5 + 5: a full verdict
    assert later["primary"]["strength"] == "clear"
    assert [c["label"] for c in later["checks"]] == [LABEL_MEASURING, None]


# --------------------------------------------------------------------------- with the DB

START = datetime(2026, 10, 13, 2, 0, tzinfo=UTC)
LAUNCH = date(2026, 10, 13)
IMPRESSIONS = 100_000


@pytest_asyncio.fixture
async def shop(session):
    from tests.support.builders import make_tenant

    _user, shop = await make_tenant(session)
    return shop


def _ctr_row(shop_id, product, day, ctr):
    clicks = round(IMPRESSIONS * ctr)
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"t:{product}:{day.isoformat()}",
        grain="product",
        start_date=day,
        end_date=day + timedelta(days=1),
        tiktok_product_id=product,
        impressions=IMPRESSIONS,
        clicks=clicks,
        sku_orders=clicks // 20,
        items_sold=clicks // 20,
        gmv=Decimal(clicks // 20 * 100_000),
        update_time=datetime(2026, 10, 1),
    )


async def _gated_group(session, shop_id):
    group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        group_key="ctr|cover_image|total",
        metric="ctr",
        lever="cover_image",
        channel="total",
        launched_on=LAUNCH,
        release_on=LAUNCH + timedelta(days=14),
        seed=99,
        status="open",
    )
    session.add(group)
    for i, (pre, lift) in enumerate(zip(PRE, LIFTS, strict=True)):
        product = f"p{i:02d}"
        arm = "treated" if i < 5 else "control"
        payload = {
            "target_metric": "ctr",
            "kpi": {"metric": "ctr", "channel": "total"},
            "diagnosis": {"lever": {"code": "cover_image"}, "tiktok_product_id": product},
        }
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key="optimize_product_2",
            subject_type="product_lever",
            subject_id=f"{product}:cover_image",
            priority=1,
            severity="warning",
            title=f"card {product}",
            description="",
            recommendation_payload=json.dumps(payload),
            status="active",
        )
        session.add(card)
        await session.flush()
        session.add(
            CardGroupMember(
                id=uuid.uuid4(),
                shop_id=shop_id,
                group_id=group.id,
                tiktok_product_id=product,
                action_card_id=card.id,
                arm=arm,
                assigned_at=datetime(2026, 10, 13),
            )
        )
        later = LATER[i - 5] if arm == "control" else 0.0
        for offset in range(-28, 28):
            if offset < -14:
                ctr = 0.04 * (1 + pre)
            elif offset < 0:
                ctr = 0.04
            elif offset < 14:
                ctr = 0.04 * (1 + lift)
            else:
                ctr = 0.04 * (1 + lift) * (1 + later)
            session.add(_ctr_row(shop_id, product, LAUNCH + timedelta(days=offset), ctr))
    await session.flush()
    return group


@pytest.mark.asyncio
async def test_dang_do_is_re_gated_with_the_controls_later_data(session, shop):
    group = await _gated_group(session, shop.id)
    [first] = await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    assert first.id == group.id
    assert first.verdict["primary"]["label"] == LABEL_MEASURING
    assert first.verdict["null_pool"] == {"pre_period": 10, "control_after": 5}
    # Day 20: not a week since the last check -> nothing; day 21: re-gated, but no new
    # complete 14-day window yet, so the pool and the label are the same.
    assert await measure_due_groups(session, shop.id, now=START + timedelta(days=19)) == []
    [again] = await measure_due_groups(session, shop.id, now=START + timedelta(days=20))
    assert again.verdict["null_pool"]["control_after"] == 5
    assert again.verdict["primary"]["label"] == LABEL_MEASURING
    # Day 28: the control's days 14–27 join the pool and the gate lets it out.
    [last] = await measure_due_groups(session, shop.id, now=START + timedelta(days=27))
    assert last.verdict["null_pool"] == {"pre_period": 10, "control_after": 10}
    assert last.verdict["false_alarm"]["rate"] <= FALSE_ALARM_MAX
    assert last.verdict["primary"]["label"] is None
    assert [c["label"] for c in last.verdict["checks"]] == [LABEL_MEASURING] * 2 + [None]
    # Out of "Đang đo": no more re-checks.
    assert await measure_due_groups(session, shop.id, now=START + timedelta(days=34)) == []


@pytest.mark.asyncio
async def test_an_approved_control_stops_feeding_the_null_pool(session, shop):
    group = await _gated_group(session, shop.id)
    from sqlalchemy import select

    members = (
        (await session.execute(select(CardGroupMember).where(CardGroupMember.group_id == group.id)))
        .scalars()
        .all()
    )
    for member in members:
        if member.arm == "control":
            card = await session.get(ActionCard, member.action_card_id)
            card.approved_at = datetime(2026, 10, 28, 3, 0)  # day 15: touched from then on
    await session.flush()
    await measure_due_groups(session, shop.id, now=START + timedelta(days=13))
    [last] = await measure_due_groups(session, shop.id, now=START + timedelta(days=27))
    assert last.verdict["null_pool"]["control_after"] == 5  # days 14–27 are not no-effect
    assert last.verdict["primary"]["label"] == LABEL_MEASURING
