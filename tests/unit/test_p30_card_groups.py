"""D34 / D39.3 (fast track P30): card groups with a randomised delayed control.

Groups = target metric × lever × channel per shop; from 3 eligible drafts ≈ 1/3 are drawn
(seeded, recorded) as a delayed control, held ``group_control`` and released 14 days
after launch; at day 14 the verdict is the median change treated − control with a
bootstrap interval. Synthetic data only. D41.3 (P31) made the verdict stricter (90 %
interval, a permutation test below 5 controls, CUPED, the false-alarm gate); the cases
here are updated to it, its own tests are in ``test_p31_group_verdict.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.models.card_groups import ARM_CONTROL, ARM_TREATED, CardGroup, CardGroupMember
from juli_backend.models.models import ActionCard, AnalyticsPerformanceInterval
from juli_backend.services.action_cards import card_groups
from juli_backend.services.action_cards.card_groups import (
    LABEL_MEASURING,
    LABEL_NOT_ENOUGH,
    LABEL_PRELIMINARY,
    SUPPRESSED_REASON_GROUP_CONTROL,
    GroupKey,
    apply_groups,
    assign_arms,
    build_verdict,
    compare,
    control_count,
    group_views,
    measure_due_groups,
    seller_sentence,
    seller_sentences,
)
from juli_backend.services.action_cards.emission_budget import (
    SUPPRESSED_REASON_CELL_CAP,
    apply_emission_budget,
)
from juli_backend.services.demo_decisions.card_view import build_card_block, load_card_contexts
from juli_backend.services.optimize_product.tunables import (
    CARD_GROUPS,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.shop_rules.diag_tunables import set_tunable_overrides
from tests.support.builders import make_tenant

#: 02:00 UTC = 09:00 in Vietnam: the shop's day is START's date.
START = datetime(2026, 10, 13, 2, 0, tzinfo=UTC)
LAUNCH = date(2026, 10, 13)
KEY = GroupKey("ctr", "cover_image", "total")
PRODUCTS = [f"p{i}" for i in range(1, 7)]


# =========================================================================== pure


def test_assignment_is_reproducible_from_the_seed():
    arms = assign_arms(PRODUCTS, 12345)
    assert assign_arms(list(reversed(PRODUCTS)), 12345) == arms
    assert sum(1 for a in arms.values() if a == ARM_CONTROL) == 2  # ≈ 1/3 of 6
    # Another seed draws (in general) another control; the draw is the seed's alone.
    draws = {
        tuple(sorted(p for p, a in assign_arms(PRODUCTS, s).items() if a == ARM_CONTROL))
        for s in range(20)
    }
    assert len(draws) > 1
    assert [control_count(n) for n in (2, 3, 4, 5, 6, 9)] == [0, 1, 1, 2, 2, 3]


def test_verdict_is_the_difference_of_medians_with_a_bootstrap_interval():
    treated = [8.0, 9.0, 10.0, 11.0, 12.0]
    control = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = compare(treated, control, seed=7)
    assert out["label"] is None  # ≥ 5 treated + ≥ 3 control: no label
    assert out["difference"] == pytest.approx(10.0 - 3.0)
    assert out["interval_level"] == 0.9 and out["test"] == "bootstrap"
    low, high = out["interval"]
    assert low <= out["difference"] <= high
    assert out["strength"] == "clear" and out["strength_label"] == "Thay đổi rõ"
    assert compare(treated, control, seed=7) == out  # seeded: reproducible

    # D41.3: with 3 controls the permutation test decides; a median difference over
    # 5 + 3 products cannot reach p ≤ 0.10 here (6 of 56 draws are as far), so noise.
    strict = compare(treated, [1.0, 2.0, 3.0], seed=7)
    assert strict["test"] == "permutation"
    assert strict["permutation"]["p_value"] == pytest.approx(6 / 56, abs=1e-4)
    assert strict["strength"] == "noise"

    noisy = compare([5.0, -6.0, 1.0, 9.0, -4.0], [3.0, -2.0, 0.0], seed=7)
    assert noisy["strength"] == "noise" and noisy["strength_label"] == "Trong dao động"

    preliminary = compare([8.0, 9.0, 10.0], [1.0, 2.0], seed=7)
    assert preliminary["label"] == LABEL_PRELIMINARY
    assert preliminary["difference"] == pytest.approx(9.0 - 1.5)


def test_a_small_group_has_no_verdict():
    out = compare([8.0, 9.0], [1.0, 2.0, 3.0], seed=7)
    assert out["label"] == LABEL_NOT_ENOUGH
    assert out["difference"] is None and out["interval"] is None and out["strength"] is None
    verdict = {"primary": out}
    assert seller_sentence(KEY, 5, verdict) is None


def test_seller_sentence_is_one_plain_sentence():
    def verdict(label, diff, strength):
        return {"primary": {"label": label, "difference": diff, "strength": strength}}

    assert (
        seller_sentence(KEY, 8, verdict(None, 7.0, "clear"))
        == "Nhóm 8 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa đổi"
    )
    assert seller_sentence(KEY, 5, verdict(LABEL_PRELIMINARY, 7.0, "likely")).endswith(
        "so với các sản phẩm chưa đổi (sơ bộ)"
    )
    # D41.3: "Đang đo" makes no claim, so the seller is told nothing yet.
    assert seller_sentence(KEY, 5, verdict(LABEL_MEASURING, 7.0, None)) is None
    assert seller_sentence(KEY, 5, None) is None
    built = build_verdict(
        [
            {"product_id": "t1", "arm": ARM_TREATED, "change_pct": 6.0},
            {"product_id": "t2", "arm": ARM_TREATED, "change_pct": 7.0},
            {"product_id": "t3", "arm": ARM_TREATED, "change_pct": 8.0},
            {"product_id": "c1", "arm": ARM_CONTROL, "change_pct": 0.0},
            {"product_id": "c2", "arm": ARM_CONTROL, "change_pct": 0.5},
        ],
        seed=3,
        as_of=LAUNCH,
    )
    assert built["primary"]["label"] in (LABEL_PRELIMINARY, LABEL_MEASURING)
    assert built["false_alarm"]["draws"] == 500


def test_card_groups_tunable_follows_the_quota_mode_unless_set():
    assert DiagTunables().groups_enabled is False
    assert DiagTunables(card_quota_mode=True).groups_enabled is True
    assert DiagTunables(card_quota_mode=True, card_groups=False).groups_enabled is False
    assert DiagTunables(card_groups=True).groups_enabled is True
    assert DiagTunables.from_overrides({CARD_GROUPS: True}).card_groups is True
    assert DiagTunables.from_overrides({}).card_groups is None
    assert DiagTunables().to_json()[CARD_GROUPS] is None
    with pytest.raises(TunableError):
        validate_tunable(CARD_GROUPS, "on")


# =========================================================================== emission


@pytest_asyncio.fixture
async def shop(session):
    _user, shop = await make_tenant(session)
    return shop


def _draft(
    shop_id: uuid.UUID,
    priority: int,
    product: str,
    *,
    metric: str = "ctr",
    lever: str = "cover_image",
    channel: str = "total",
) -> ActionCard:
    payload = {
        "target_metric": metric,
        "kpi": {"metric": metric, "channel": channel},
        "diagnosis": {
            "lever": {"code": lever},
            "tiktok_product_id": product,
            "product_title": f"Sản phẩm {product}",
        },
    }
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key="optimize_product_2",
        subject_type="product_lever",
        subject_id=f"{product}:{lever}",
        priority=priority,
        severity="warning",
        title=f"card {product}",
        description="",
        recommendation_payload=json.dumps(payload),
        status="active",
    )


async def _seed_six(session, shop_id: uuid.UUID) -> list[ActionCard]:
    cards = [_draft(shop_id, i + 1, pid) for i, pid in enumerate(PRODUCTS)]
    session.add_all(cards)
    await session.flush()
    return cards


@pytest.mark.asyncio
async def test_controls_are_held_then_released_after_14_days(session, shop, monkeypatch):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 4242)
    await set_tunable_overrides(session, shop.id, {"card_quota_mode": True})
    cards = await _seed_six(session, shop.id)

    outcome = await apply_emission_budget(session, shop.id, now=START)

    [group] = (await session.execute(select(CardGroup))).scalars().all()
    assert (group.group_key, group.seed) == (KEY.text, 4242)
    assert (group.launched_on, group.release_on) == (LAUNCH, LAUNCH + timedelta(days=14))
    members = (await session.execute(select(CardGroupMember))).scalars().all()
    # The stored arms are the seed's draw.
    assert {m.tiktok_product_id: m.arm for m in members} == assign_arms(PRODUCTS, 4242)
    controls = {m.action_card_id for m in members if m.arm == ARM_CONTROL}
    assert len(controls) == 2
    held = outcome.suppressed[SUPPRESSED_REASON_GROUP_CONTROL]
    assert {c.id for c in held} == controls
    assert all(c.suppressed_reason == SUPPRESSED_REASON_GROUP_CONTROL for c in held)
    # The treated cards surface under the quota (5 per cell: all four today).
    assert {c.id for c in outcome.newly_surfaced} == {c.id for c in cards} - controls

    # Still held on day 13; released on day 14 (same rows, no new group).
    day13 = await apply_emission_budget(session, shop.id, now=START + timedelta(days=13))
    assert {c.id for c in day13.suppressed[SUPPRESSED_REASON_GROUP_CONTROL]} == controls
    day14 = await apply_emission_budget(session, shop.id, now=START + timedelta(days=14))
    assert {c.id for c in day14.newly_surfaced} == controls
    assert day14.suppressed[SUPPRESSED_REASON_GROUP_CONTROL] == []
    released = [m for m in members if m.arm == ARM_CONTROL]
    assert all(m.released_at is not None for m in released)
    assert len((await session.execute(select(CardGroup))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_fewer_than_three_drafts_make_no_group(session, shop):
    await set_tunable_overrides(session, shop.id, {"card_quota_mode": True})
    session.add_all([_draft(shop.id, 1, "p1"), _draft(shop.id, 2, "p2")])
    session.add(_draft(shop.id, 3, "p3", lever="title"))  # another group key
    await session.flush()
    outcome = await apply_emission_budget(session, shop.id, now=START)
    assert (await session.execute(select(CardGroup))).scalars().all() == []
    assert len(outcome.newly_surfaced) == 3
    assert outcome.suppressed[SUPPRESSED_REASON_GROUP_CONTROL] == []


async def _surface_run(session, shop_id: uuid.UUID) -> tuple:
    outcome = await apply_emission_budget(session, shop_id, now=START)
    return (
        sorted(c.priority for c in outcome.newly_surfaced),
        {k: sorted(c.priority for c in v) for k, v in outcome.suppressed.items()},
    )


@pytest.mark.asyncio
async def test_groups_off_leaves_the_budget_unchanged(session, monkeypatch):
    """Off (quota mode off by default, or explicitly off with the quota on): the budget
    never draws or holds a card (``apply_groups`` never runs), writes no group and has
    no group_control reason. D45.1 (P36): only the day-14 measurement still runs, for
    groups made in Ops -- with none, it writes nothing."""

    async def _boom(*_a, **_k):
        raise AssertionError("group code ran while off")

    monkeypatch.setattr(card_groups, "apply_groups", _boom)

    _u1, plain = await make_tenant(session)
    await _seed_six(session, plain.id)
    _u2, quota_off = await make_tenant(session)
    await set_tunable_overrides(session, quota_off.id, {"card_groups": False})
    await _seed_six(session, quota_off.id)
    a = await _surface_run(session, plain.id)
    b = await _surface_run(session, quota_off.id)
    assert a == b
    assert SUPPRESSED_REASON_GROUP_CONTROL not in a[1]

    # Quota on, groups off: exactly the D33 quota behaviour (per-cell cap, no hold).
    _u3, quota = await make_tenant(session)
    await set_tunable_overrides(session, quota.id, {"card_quota_mode": True, "card_groups": False})
    await _seed_six(session, quota.id)
    c = await _surface_run(session, quota.id)
    assert c[0] == [1, 2, 3, 4, 5]
    assert c[1][SUPPRESSED_REASON_CELL_CAP] == [6]
    assert SUPPRESSED_REASON_GROUP_CONTROL not in c[1]
    assert (await session.execute(select(CardGroup))).scalars().all() == []


@pytest.mark.asyncio
async def test_treated_cards_go_first_in_the_launch_window(session, shop, monkeypatch):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 4242)
    # Two other cards rank before the group's drafts.
    others = [_draft(shop.id, 1, "x1", lever="title"), _draft(shop.id, 2, "x2", lever="title")]
    groupees = [_draft(shop.id, 10 + i, pid) for i, pid in enumerate(PRODUCTS[:3])]
    session.add_all([*others, *groupees])
    await session.flush()
    passed = await apply_groups(session, shop.id, [*others, *groupees], now=START)
    arms = assign_arms(PRODUCTS[:3], 4242)
    treated = [
        c
        for c in groupees
        if arms[json.loads(c.recommendation_payload)["diagnosis"]["tiktok_product_id"]]
        == ARM_TREATED
    ]
    assert passed.eligible[: len(treated)] == treated
    assert passed.eligible[len(treated) :] == others
    assert len(passed.held) == 1


# =========================================================================== measurement


def _day_row(shop_id: uuid.UUID, product: str, day: date, impressions: int, clicks: int):
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
        sku_orders=clicks // 20,
        items_sold=clicks // 20,
        gmv=Decimal(clicks // 20 * 100_000),
        update_time=datetime(2026, 10, 1),
    )


async def _group_with_data(
    session, shop_id: uuid.UUID, lifts: dict[str, tuple[str, float]], *, seed: int = 99
) -> CardGroup:
    """A group launched LAUNCH with members ``product -> (arm, CTR lift)`` and 42 days of rows.

    The 14 days before the "before" window wobble a little per product (±2 %), the
    no-effect data D41.3's false-alarm replay draws from.
    """
    group = CardGroup(
        id=uuid.uuid4(),
        shop_id=shop_id,
        group_key=KEY.text,
        metric=KEY.metric,
        lever=KEY.lever,
        channel=KEY.channel,
        launched_on=LAUNCH,
        release_on=LAUNCH + timedelta(days=14),
        seed=seed,
        status="open",
    )
    session.add(group)
    for index, (product, (arm, lift)) in enumerate(lifts.items()):
        card = _draft(shop_id, 1, product)
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
        wobble = ((index * 37) % 9 - 4) / 200
        for offset in range(-28, 14):
            day = LAUNCH + timedelta(days=offset)
            if offset < -14:
                clicks = round(400 * (1 + wobble))
            else:
                clicks = 400 if offset < 0 else round(400 * (1 + lift))
            session.add(_day_row(shop_id, product, day, 10_000, clicks))
    await session.flush()
    return group


@pytest.mark.asyncio
async def test_day_14_verdict_on_synthetic_data(session, shop):
    lifts = {
        **{f"t{i}": (ARM_TREATED, lift) for i, lift in enumerate([0.08, 0.09, 0.10, 0.11, 0.12])},
        **{f"c{i}": (ARM_CONTROL, lift) for i, lift in enumerate([0.01, 0.02, 0.03])},
    }
    group = await _group_with_data(session, shop.id, lifts)
    # The newest analytics day is launch + 12: the 14 days after launch are not in yet.
    assert await measure_due_groups(session, shop.id, now=START + timedelta(days=12)) == []
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=15))
    assert measured.id == group.id and measured.status == "measured"
    primary = measured.verdict["primary"]
    assert primary["label"] is None
    assert (primary["n_treated"], primary["n_control"]) == (5, 3)
    assert primary["median_treated"] == pytest.approx(10.0, abs=0.1)
    assert primary["median_control"] == pytest.approx(2.0, abs=0.1)
    assert primary["difference"] == pytest.approx(8.0, abs=0.2)
    # D41.3: 3 controls -> the permutation test decides; a median difference over 5 + 3
    # products cannot reach p ≤ 0.10 (6 of 56 draws are as far): no claim of change.
    assert primary["test"] == "permutation"
    assert primary["permutation"]["p_value"] == pytest.approx(6 / 56, abs=1e-4)
    assert primary["strength"] == "noise"
    assert all(p["pre_before"] is not None for p in measured.verdict["products"])
    assert measured.verdict["false_alarm"]["source"] == "pre_period+control_after"
    # Approved-only (secondary): no treated card approved -> not enough.
    assert measured.verdict["approved_only"]["label"] == LABEL_NOT_ENOUGH
    # The seller sentence, for cards of the same group key.
    sentences = await seller_sentences(session, shop.id)
    assert sentences == {
        KEY.text: "Nhóm 8 sản phẩm đổi ảnh bìa: lượt nhấp chưa khác rõ so với các sản phẩm chưa đổi"
    }
    # Ops view: arms, seed, interval.
    [view] = await group_views(session, shop.id)
    assert (view["treated"], view["control"], view["seed"]) == (5, 3, 99)
    assert view["false_alarm"] == measured.verdict["false_alarm"]
    assert (
        view["verdict"]["primary"]["interval"][0]
        <= 8.0
        <= view["verdict"]["primary"]["interval"][1]
    )
    assert view["label"] == "CTR · Ảnh bìa · tất cả kênh"


@pytest.mark.asyncio
async def test_a_small_measured_group_reads_not_enough_and_tells_the_seller_nothing(session, shop):
    lifts = {"t1": (ARM_TREATED, 0.1), "t2": (ARM_TREATED, 0.1), "c1": (ARM_CONTROL, 0.0)}
    await _group_with_data(session, shop.id, lifts)
    [measured] = await measure_due_groups(session, shop.id, now=START + timedelta(days=15))
    assert measured.verdict["primary"]["label"] == LABEL_NOT_ENOUGH
    assert measured.verdict["primary"]["difference"] is None
    assert await seller_sentences(session, shop.id) == {}


#: 12 treated products up ≈ 28 %, 2 controls flat: clear even under D41.3 ("Sơ bộ").
CLEAR_LIFTS = {
    **{f"t{i:02d}": (ARM_TREATED, 0.25 + 0.005 * i) for i in range(12)},
    "c0": (ARM_CONTROL, 0.0),
    "c1": (ARM_CONTROL, 0.01),
}


@pytest.mark.asyncio
async def test_the_seller_card_carries_the_group_sentence_once_measured(session, shop):
    lifts = CLEAR_LIFTS
    await _group_with_data(session, shop.id, lifts)
    card = _draft(shop.id, 1, "new-product")
    session.add(card)
    await session.flush()
    payload = json.loads(card.recommendation_payload)

    before = await load_card_contexts(session, shop.id, [card])
    assert build_card_block(card, payload, before[card.id])["group_result"] is None

    await measure_due_groups(session, shop.id, now=START + timedelta(days=15))
    after = await load_card_contexts(session, shop.id, [card])
    block = build_card_block(card, payload, after[card.id])
    assert block["group_result"] == (
        "Nhóm 14 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 27 % so với các sản phẩm chưa đổi"
        " (sơ bộ)"
    )
    # Another group key (title) gets no sentence.
    other = _draft(shop.id, 2, "other", lever="title")
    session.add(other)
    await session.flush()
    ctx = await load_card_contexts(session, shop.id, [other])
    assert (
        build_card_block(other, json.loads(other.recommendation_payload), ctx[other.id])[
            "group_result"
        ]
        is None
    )


# =========================================================================== Ops route


@pytest.mark.asyncio
async def test_ops_group_view_route(session, shop, monkeypatch):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app, client_for
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    lifts = CLEAR_LIFTS
    await _group_with_data(session, shop.id, lifts)
    await measure_due_groups(session, shop.id, now=START + timedelta(days=15))
    email = f"viewer-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role="viewer", active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shop.id}/groups")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False  # quota mode off, grouping not set
    [group] = body["groups"]
    assert (group["treated"], group["control"], group["status"]) == (12, 2, "measured")
    assert group["verdict"]["primary"]["difference"] == pytest.approx(27.25, abs=0.5)
    assert group["verdict"]["primary"]["label"] == LABEL_PRELIMINARY
    # D41.3: the group's simulated false-alarm rate is in the route output.
    assert group["false_alarm"]["acceptable"] is True
    assert 0 <= group["false_alarm"]["rate"] <= group["false_alarm"]["max"] + 0.02
    assert group["seller_sentence"].startswith("Nhóm 14 sản phẩm đổi ảnh bìa: lượt nhấp tăng")


@pytest.mark.asyncio
async def test_a_released_control_is_never_drawn_into_a_second_group(session, shop, monkeypatch):
    monkeypatch.setattr(card_groups, "new_seed", lambda: 4242)
    cards = [_draft(shop.id, i + 1, pid) for i, pid in enumerate(PRODUCTS[:3])]
    session.add_all(cards)
    await session.flush()
    first = await apply_groups(session, shop.id, cards, now=START)
    [held] = first.held
    # Day 20: the released control is still a draft, with two new drafts of its key.
    newcomers = [_draft(shop.id, 10, "n1"), _draft(shop.id, 11, "n2")]
    session.add_all(newcomers)
    await session.flush()
    later = await apply_groups(session, shop.id, [held, *newcomers], now=START + timedelta(days=20))
    assert later.launched == [] and later.held == []
    assert later.eligible == [held, *newcomers]
