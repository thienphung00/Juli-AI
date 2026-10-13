"""Fast track P28 (D33): the per-shop "many cards" quota mode.

Synthetic fixtures only. One test (or a small group) per rule:

- the quota keys are team tunables (``shop_rules.diag_tunables``), off by default;
- OFF: the emission budget and the planner behave exactly as before (two shops,
  one with no tunables row and one with the mode explicitly off and other quota
  keys set, surface the same cards; the planner's proposals are equal);
- ON: up to N open cards per cell (target metric × KPI channel; content kinds
  their own cells), cooldown and ``ops_disabled`` kept, the seller's
  "Số thẻ mở cùng lúc" still wins, already-open cards count;
- the planner in quota mode: D29.4 (one target metric per product), the S28B
  "below shop level" branch (confidence low, KPI = minimum clamp only, seller
  copy without jargon, ``reason_code``), price levers from stored facts, a
  neutral lever weight, candidates kept per cell;
- the stored price facts (discount cap rule, running promotions);
- the re-score task's log line carries its counts in the message text.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.history import PromotionActivity, PromotionActivityProduct
from juli_backend.models.models import ActionCard
from juli_backend.services.action_cards.emission_budget import (
    CELL_OTHER,
    SUPPRESSED_REASON_CELL_CAP,
    SUPPRESSED_REASON_COOLDOWN,
    SUPPRESSED_REASON_DAILY_CAP,
    apply_emission_budget,
    card_cell,
    open_cell_counts,
    shop_card_quota,
)
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    d29_payload,
    price_lever_facts,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import (
    ChannelTraffic,
    ProductDay,
    product_funnel,
)
from juli_backend.services.optimize_product.decision_cards import (
    REASON_BELOW_SHOP_LEVEL,
    CatalogProduct,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.diagnosis import Angle, PageLevers
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.tunables import (
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.shop_rules.diag_tunables import diag_tunables, set_tunable_overrides
from juli_backend.services.shop_rules.rules import (
    DEFAULT_MAX_DISCOUNT_PCT,
    MAX_OPEN_CARDS,
    set_rule,
)
from tests.support.builders import make_tenant

#: Thursday 2026-10-15, 09:00 in Vietnam.
START = datetime(2026, 10, 15, 2, 0, tzinfo=UTC)
AS_OF = date(2026, 10, 6)
CONFIG = StageDiagnosisConfig()
QUOTA = DiagTunables(card_quota_mode=True)

# =========================================================================== tunables


def test_quota_mode_is_an_off_by_default_team_tunable():
    base = DiagTunables()
    assert (base.card_quota_mode, base.card_quota_per_cell, base.card_quota_max_open) == (
        False,
        5,
        40,
    )
    out = DiagTunables.from_overrides(
        {"card_quota_mode": True, "card_quota_per_cell": 7, "card_quota_max_open": 60}
    )
    assert (out.card_quota_mode, out.card_quota_per_cell, out.card_quota_max_open) == (
        True,
        7,
        60,
    )
    for name, bad in (
        ("card_quota_mode", "yes"),
        ("card_quota_per_cell", 0),
        ("card_quota_per_cell", 2.5),
        ("card_quota_max_open", 500),
    ):
        with pytest.raises(TunableError):
            validate_tunable(name, bad)
    # An invalid stored value is ignored (the default stays).
    assert DiagTunables.from_overrides({"card_quota_per_cell": 99}).card_quota_per_cell == 5


@pytest.mark.asyncio
async def test_the_quota_is_read_from_the_team_row(session, tenant_shop):
    assert await shop_card_quota(session, tenant_shop.id) is None
    await set_tunable_overrides(session, tenant_shop.id, {"card_quota_per_cell": 3})
    assert await shop_card_quota(session, tenant_shop.id) is None  # mode still off
    await set_tunable_overrides(session, tenant_shop.id, {"card_quota_mode": True})
    quota = await shop_card_quota(session, tenant_shop.id)
    assert quota is not None and (quota.per_cell, quota.max_open) == (3, 40)
    assert (await diag_tunables(session, tenant_shop.id)).card_quota_mode is True


# =========================================================================== cells

_CONTENT = "content_video"


def _card(
    shop_id: uuid.UUID,
    priority: int,
    *,
    metric: str | None = "ctr",
    channel: str | None = "product_card",
    lever: str | None = "cover_image",
    workflow_key: str = OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    surfaced_at: datetime | None = None,
) -> ActionCard:
    payload: dict = {}
    if workflow_key == _CONTENT:
        payload = {"executor_type": "video"}
    else:
        if lever:
            payload["diagnosis"] = {"lever": {"code": lever}}
        if metric:
            payload["target_metric"] = metric
            payload["kpi"] = {"metric": metric, **({"channel": channel} if channel else {})}
    return ActionCard(
        id=uuid.uuid4(),
        shop_id=shop_id,
        workflow_key=workflow_key,
        subject_type="product",
        subject_id=str(uuid.uuid4()),
        priority=priority,
        severity="warning",
        title=f"card {priority}",
        description="",
        recommendation_payload=json.dumps(payload),
        status="active",
        surfaced_at=surfaced_at,
    )


def test_card_cells():
    shop_id = uuid.uuid4()
    assert card_cell(_card(shop_id, 1)) == "ctr@product_card"
    assert card_cell(_card(shop_id, 1, metric="ctor", channel="total")) == "ctor@total"
    # Before D32 (no kpi.channel): all channels.
    assert card_cell(_card(shop_id, 1, metric="aov", channel=None)) == "aov@total"
    assert card_cell(_card(shop_id, 1, workflow_key=_CONTENT)) == "content_video"
    assert card_cell(_card(shop_id, 1, metric=None, lever=None)) == CELL_OTHER
    # Before D29: the funnel stage's metric.
    legacy = _card(shop_id, 1, metric=None)
    legacy.recommendation_payload = json.dumps(
        {"diagnosis": {"lever": {"code": "description"}, "stage": {"code": "page"}}}
    )
    assert card_cell(legacy) == "ctor@total"


# =========================================================================== emission


@pytest_asyncio.fixture
async def tenant_shop(session):
    _user, shop = await make_tenant(session)
    return shop


def _seed_mix(session, shop_id: uuid.UUID) -> None:
    """8 CTR × Thẻ sản phẩm (Juli), 3 CTOR × all (Seller Center), 7 video cards, interleaved."""
    priority = 0
    for index in range(8):
        priority += 1
        lever = "cover_image" if index % 2 else "title"
        session.add(_card(shop_id, priority, lever=lever))
        if index < 3:
            priority += 1
            session.add(
                _card(shop_id, priority, metric="ctor", channel="total", lever="product_discount")
            )
        if index < 7:
            priority += 1
            session.add(_card(shop_id, priority, workflow_key=_CONTENT))


def _surfacing(outcome) -> tuple:
    return (
        sorted(c.priority for c in outcome.newly_surfaced),
        {k: sorted(c.priority for c in v) for k, v in outcome.suppressed.items()},
    )


@pytest.mark.asyncio
async def test_off_mode_is_unchanged(session):
    """Mode off (no row, or the row with the mode off and other quota keys set):
    the same cards surface day by day, in the D24.21 slots 3 / 1 / 1."""
    _u1, plain = await make_tenant(session)
    _u2, configured = await make_tenant(session)
    await set_tunable_overrides(
        session,
        configured.id,
        {"card_quota_mode": False, "card_quota_per_cell": 9, "card_quota_max_open": 90},
    )
    _seed_mix(session, plain.id)
    _seed_mix(session, configured.id)
    await session.flush()

    for day in range(3):
        now = START + timedelta(days=day)
        a = await apply_emission_budget(session, plain.id, now=now)
        b = await apply_emission_budget(session, configured.id, now=now)
        assert _surfacing(a) == _surfacing(b)
        assert SUPPRESSED_REASON_CELL_CAP not in a.suppressed
        slots: dict[str, int] = {}
        for card in a.newly_surfaced:
            key = "content" if card.workflow_key == _CONTENT else card_cell(card)
            slots[key] = slots.get(key, 0) + 1
        # 8 CTR cards: 3 + 3 + the last 2.
        assert slots == {"ctr@product_card": (3, 3, 2)[day], "ctor@total": 1, "content": 1}
        assert a.suppressed[SUPPRESSED_REASON_DAILY_CAP]


@pytest.mark.asyncio
async def test_on_mode_fills_up_to_n_per_cell_on_the_first_day(session, tenant_shop):
    shop_id = tenant_shop.id
    await set_tunable_overrides(session, shop_id, {"card_quota_mode": True})
    _seed_mix(session, shop_id)
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)

    cells: dict[str, int] = {}
    for card in outcome.newly_surfaced:
        cells[card_cell(card)] = cells.get(card_cell(card), 0) + 1
    assert cells == {"ctr@product_card": 5, "ctor@total": 3, "content_video": 5}
    # The best of each cell, by priority.
    ctr = sorted(c.priority for c in outcome.newly_surfaced if card_cell(c) == "ctr@product_card")
    all_ctr = sorted(
        c.priority
        for c in outcome.newly_surfaced + outcome.suppressed[SUPPRESSED_REASON_CELL_CAP]
        if card_cell(c) == "ctr@product_card"
    )
    assert ctr == all_ctr[:5]
    assert len(outcome.suppressed[SUPPRESSED_REASON_CELL_CAP]) == 3 + 2
    assert all(
        c.suppressed_reason == SUPPRESSED_REASON_CELL_CAP
        for c in outcome.suppressed[SUPPRESSED_REASON_CELL_CAP]
    )
    assert await open_cell_counts(session, shop_id) == {
        "content_video": 5,
        "ctor@total": 3,
        "ctr@product_card": 5,
    }

    # Next day: the cells are full, nothing new; once a card leaves, its cell refills.
    again = await apply_emission_budget(session, shop_id, now=START + timedelta(days=1))
    assert again.newly_surfaced == []
    gone = next(c for c in outcome.newly_surfaced if card_cell(c) == "ctr@product_card")
    gone.status = "dismissed"
    gone.dismissed_at = START + timedelta(days=1)
    await session.flush()
    refill = await apply_emission_budget(session, shop_id, now=START + timedelta(days=2))
    assert [card_cell(c) for c in refill.newly_surfaced] == ["ctr@product_card"]


@pytest.mark.asyncio
async def test_on_mode_keeps_the_overall_open_cap_and_ops_and_cooldown(session, tenant_shop):
    shop_id = tenant_shop.id
    await set_tunable_overrides(
        session, shop_id, {"card_quota_mode": True, "card_quota_max_open": 6}
    )
    _seed_mix(session, shop_id)
    cooled = _card(shop_id, 0, metric="aov", channel="total", lever="buy_more_save_more")
    cooled.dismissed_at = START - timedelta(days=1)
    session.add(cooled)
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)
    assert len(outcome.newly_surfaced) == 6
    assert cooled in outcome.suppressed[SUPPRESSED_REASON_COOLDOWN]


@pytest.mark.asyncio
async def test_the_sellers_open_card_rule_still_wins(session, tenant_shop):
    shop_id = tenant_shop.id
    await set_tunable_overrides(session, shop_id, {"card_quota_mode": True})
    await set_rule(
        session,
        shop_id,
        rule_key=MAX_OPEN_CARDS,
        scope_ref=None,
        value=5,
        set_by="seller",
        set_by_user_id=None,
    )
    _seed_mix(session, shop_id)
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)
    assert len(outcome.newly_surfaced) == 5


@pytest.mark.asyncio
async def test_open_cards_count_toward_their_cell(session, tenant_shop):
    shop_id = tenant_shop.id
    await set_tunable_overrides(
        session, shop_id, {"card_quota_mode": True, "card_quota_per_cell": 2}
    )
    session.add(_card(shop_id, 1, surfaced_at=START - timedelta(days=1)))
    for priority in range(2, 6):
        session.add(_card(shop_id, priority))
    await session.flush()

    outcome = await apply_emission_budget(session, shop_id, now=START)
    assert [c.priority for c in outcome.newly_surfaced] == [2]


# =========================================================================== the planner


def _flat(
    *,
    card_ctr: float = 0.05,
    conv: float = 0.06,
    days: int = 60,
    card_ctr_recent: float | None = None,
) -> list[ProductDay]:
    """A flat product (no noise): 3000 product-card + 3000 video impressions a day.

    Video CTR 2,5 %; SKU orders = clicks × ``conv``; AOV 200.000 ₫. With
    ``card_ctr_recent`` the last 14 days carry that product-card CTR (a fall).
    """
    rows: list[ProductDay] = []
    for offset in range(days):
        ctr = card_ctr_recent if card_ctr_recent is not None and offset < 14 else card_ctr
        c_imp, v_imp = 3000, 3000
        c_clicks, v_clicks = round(c_imp * ctr), round(v_imp * 0.025)
        orders = (c_clicks + v_clicks) * conv
        gmv = orders * 200_000
        c_gmv = c_clicks * conv * 200_000
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(c_imp + v_imp),
                clicks=Decimal(c_clicks + v_clicks),
                sku_orders=Decimal(str(round(orders, 4))),
                items_sold=Decimal(str(round(orders, 4))),
                gmv=Decimal(str(round(gmv))),
                channels={
                    "PRODUCT_CARD": ChannelTraffic(
                        Decimal(c_imp), Decimal(c_clicks), Decimal(str(round(c_gmv)))
                    ),
                    "VIDEO": ChannelTraffic(
                        Decimal(v_imp), Decimal(v_clicks), Decimal(str(round(gmv - c_gmv)))
                    ),
                },
            )
        )
    return sorted(rows, key=lambda r: r.day)


def _shop_with(target: dict[str, list[ProductDay]]) -> dict[str, list[ProductDay]]:
    daily = dict(target)
    for pid in ("peer1", "peer2", "peer3", "peer4"):
        daily[pid] = _flat()
    return daily


def _plan(daily, evidence=None, tunables: DiagTunables = QUOTA, **kwargs):
    funnels = [
        product_funnel(pid, pid, rows, as_of=AS_OF, config=CONFIG) for pid, rows in daily.items()
    ]
    catalog = {
        pid: CatalogProduct(
            pid, f"Sản phẩm {pid} có tiêu đề đủ dài để không bị đánh dấu", "ACTIVATE"
        )
        for pid in daily
    }
    return plan_shop_cards(
        funnels,
        catalog,
        CONFIG,
        daily=daily,
        as_of=AS_OF,
        tunables=tunables,
        tiktok_evidence=evidence or {},
        **kwargs,
    )


def _tiktok(*codes: str) -> list[Evidence]:
    return [Evidence(code, EvidenceSource.TIKTOK) for code in codes]


#: Jargon the seller must not read on a card (D31.8).
_JARGON = ("band", "median", "trung vị", "dao động", "CV", "D33", "S28B", "_")


def test_below_shop_level_card_is_low_confidence_with_a_modest_kpi():
    daily = _shop_with({"low": _flat(card_ctr=0.025)})
    plan = _plan(daily, {"low": _tiktok("MAIN_IMG_DUPLICATE")})
    [card] = [p for p in plan.proposals if p.product_id == "low"]
    assert card.reason_code == REASON_BELOW_SHOP_LEVEL
    assert card.target_metric == "ctr" and card.kpi is not None
    assert card.kpi.channel == "product_card"
    assert card.confidence == "low"
    # KPI = the minimum clamp alone: current + 1 × band, a single point.
    band_abs = card.kpi.current * card.kpi.band_pct / 100
    assert card.kpi.target == pytest.approx(card.kpi.current + band_abs)
    assert card.kpi.target_min == pytest.approx(card.kpi.target_max)
    # Seller copy, without backend words.
    assert card.reason.startswith("CTR của sản phẩm trên kênh Thẻ sản phẩm thấp hơn mức chung")
    assert "doanh thu không giảm" in card.reason
    for word in _JARGON:
        assert word not in card.reason
    payload = d29_payload(card)
    assert payload["reason_code"] == REASON_BELOW_SHOP_LEVEL
    assert payload["confidence"] == "low"
    # Peers at the shop's level get nothing.
    assert {p.product_id for p in plan.proposals} == {"low"}


def test_no_below_shop_level_card_when_the_mode_is_off():
    daily = _shop_with({"low": _flat(card_ctr=0.025)})
    plan = _plan(daily, {"low": _tiktok("MAIN_IMG_DUPLICATE")}, tunables=DiagTunables())
    assert plan.proposals == []
    # D39.1 metric-first: no metric fell beyond its band either.
    assert any(s.product_id == "low" and s.reason == "d39:no_metric_drop" for s in plan.skips)
    gmv_first = _plan(
        daily,
        {"low": _tiktok("MAIN_IMG_DUPLICATE")},
        tunables=DiagTunables(diag_trigger="gmv_first"),
    )
    assert gmv_first.proposals == []
    assert any(s.product_id == "low" and s.reason == "d29:no_gmv_drop" for s in gmv_first.skips)


def test_off_mode_planner_is_unchanged_by_quota_inputs():
    daily = _shop_with(
        {
            "fall": _flat(card_ctr=0.05, card_ctr_recent=0.03),
            "low": _flat(card_ctr=0.025),
            "conv": _flat(conv=0.03),
        }
    )
    evidence = {"fall": _tiktok("MAIN_IMG_DUPLICATE"), "low": _tiktok("MAIN_IMG_DUPLICATE")}
    base = _plan(daily, evidence, tunables=DiagTunables())
    other = _plan(
        daily,
        evidence,
        tunables=DiagTunables(card_quota_per_cell=9, card_quota_max_open=90),
        page_levers={"conv": PageLevers(product_discount_active=True)},
        active_bmsm=frozenset({"fall"}),
    )
    assert base == other
    assert [p.product_id for p in base.proposals] == ["fall"]
    assert base.proposals[0].reason_code is None


def test_d29_4_one_metric_per_product_and_drop_cards_first():
    """A falling product keeps its D29 card (reason: the GMV fall), ranked first;
    a product's cards (cover image + title) share ONE target metric."""
    daily = _shop_with(
        {
            "fall": _flat(card_ctr=0.05, card_ctr_recent=0.03),
            "low": _flat(card_ctr=0.025, conv=0.03),
        }
    )
    evidence = {
        "fall": _tiktok("MAIN_IMG_DUPLICATE", "TITLE_TOO_SHORT"),
        "low": _tiktok("MAIN_IMG_DUPLICATE", "TITLE_TOO_SHORT"),
    }
    plan = _plan(daily, evidence, discount_cap_set=True)
    fall = [p for p in plan.proposals if p.product_id == "fall"]
    assert {p.lever for p in fall} == {Angle.ANH_BIA, Angle.TIEU_DE}
    assert [p for p in plan.proposals if p.product_id == "low"]
    by_product: dict[str, set[str | None]] = {}
    for p in plan.proposals:
        by_product.setdefault(p.product_id, set()).add(p.target_metric)
    assert all(len(metrics) == 1 for metrics in by_product.values())
    first = plan.proposals[0]
    assert first.product_id == "fall" and first.reason_code is None
    # D39.1 metric-first copy: the metric that fell, then what GMV did.
    assert first.reason.startswith("CTR trên kênh Thẻ sản phẩm giảm")
    gmv_first = _plan(
        daily, evidence, discount_cap_set=True, tunables=replace(QUOTA, diag_trigger="gmv_first")
    )
    assert gmv_first.proposals[0].reason.startswith("GMV mỗi ngày giảm")
    assert all(
        p.reason_code == REASON_BELOW_SHOP_LEVEL for p in plan.proposals if p.product_id == "low"
    )


def test_price_levers_from_stored_facts_in_quota_mode():
    """CTOR below the shop's level, the seller's maximum discount set, no
    description fault: a product discount (all channels); no product discount
    while one already runs on the product."""
    daily = _shop_with({"conv": _flat(conv=0.03)})
    plan = _plan(daily, discount_cap_set=True)
    [card] = [p for p in plan.proposals if p.product_id == "conv"]
    assert (card.target_metric, card.lever) == ("ctor", Angle.GIAM_GIA)
    assert card.kpi is not None and card.kpi.channel == "total"
    assert card.reason_code == REASON_BELOW_SHOP_LEVEL
    assert card.reason.startswith("CTOR của sản phẩm trên tất cả kênh thấp hơn")

    running = _plan(
        daily,
        discount_cap_set=True,
        page_levers={"conv": PageLevers(product_discount_active=True)},
    )
    # No second discount; what is left is the description, pending TikTok's diagnosis.
    [pending] = [p for p in running.proposals if p.product_id == "conv"]
    assert (pending.lever, pending.status) == (Angle.MO_TA, "tiktok_not_asked")


def test_lever_weight_is_neutral_in_quota_mode():
    daily = _shop_with({"fall": _flat(card_ctr=0.05, card_ctr_recent=0.03)})
    plan = _plan(daily, {"fall": _tiktok("MAIN_IMG_DUPLICATE")})
    [card] = [p for p in plan.proposals if p.product_id == "fall"]
    assert card.prediction is not None and card.d29_ranking_value is not None
    # D39.1 metric-first: ranked on the GMV the CTR fall costs, no lever weight.
    assert card.metric_trigger is not None and card.metric_trigger.target is not None
    cost = Decimal(str(round(card.metric_trigger.target.gmv_cost_per_day, 4)))
    assert card.d29_ranking_value == cost * Decimal(str(card.prediction.factor))
    old = _plan(
        daily,
        {"fall": _tiktok("MAIN_IMG_DUPLICATE")},
        tunables=replace(QUOTA, diag_trigger="gmv_first"),
    )
    [card] = [p for p in old.proposals if p.product_id == "fall"]
    expected = card.recoverable_gmv_per_day * Decimal(str(card.prediction.factor))
    assert card.d29_ranking_value == expected


# =========================================================================== stored facts


@pytest.mark.asyncio
async def test_price_lever_facts_from_rules_and_promotions(session, tenant_shop):
    shop_id = tenant_shop.id
    now = START
    facts = await price_lever_facts(session, shop_id, now=now)
    assert (facts.discount_cap_set, facts.page_levers, facts.active_bmsm) == (
        False,
        {},
        frozenset(),
    )
    await set_rule(
        session,
        shop_id,
        rule_key=DEFAULT_MAX_DISCOUNT_PCT,
        scope_ref=None,
        value=20,
        set_by="team",
        set_by_user_id=None,
    )
    naive = now.replace(tzinfo=None)

    def activity(aid: str, kind: str, status: str, begin: datetime, end: datetime) -> None:
        session.add(
            PromotionActivity(
                shop_id=shop_id,
                activity_id=aid,
                activity_type=kind,
                status=status,
                begin_time=begin,
                end_time=end,
                first_seen_at=naive,
                refreshed_at=naive,
            )
        )

    def member(aid: str, product: str, removed: bool = False) -> None:
        session.add(
            PromotionActivityProduct(
                shop_id=shop_id,
                activity_id=aid,
                tiktok_product_id=product,
                tiktok_sku_id="",
                added_at=naive,
                updated_at=naive,
                removed_at=naive if removed else None,
            )
        )

    day = timedelta(days=1)
    activity("a1", "FIXED_PRICE", "ONGOING", naive - day, naive + day)
    member("a1", "p-discount")
    member("a1", "p-removed", removed=True)
    activity("a2", "BUY_MORE_SAVE_MORE", "ONGOING", naive - day, naive + day)
    member("a2", "p-bmsm")
    activity("a3", "FIXED_PRICE", "EXPIRED", naive - 5 * day, naive - 2 * day)
    member("a3", "p-old")
    activity("a4", "FLASHSALE", "DEACTIVATED", naive - day, naive + day)
    member("a4", "p-off")
    await session.flush()

    facts = await price_lever_facts(session, shop_id, now=now)
    assert facts.discount_cap_set is True
    assert facts.page_levers == {"p-discount": PageLevers(product_discount_active=True)}
    assert facts.active_bmsm == frozenset({"p-bmsm"})


# =========================================================================== logs


@pytest.mark.asyncio
async def test_rescore_task_log_carries_counts_in_the_message(engine, monkeypatch, caplog):
    from juli_backend.services.action_cards import optimize_product_cards
    from juli_backend.workers.tasks.rescore_shop_cards import rescore_shop_cards_async

    shop_id = uuid.uuid4()

    async def fake(session, shop, *, now):
        return {
            "shop_id": str(shop),
            "status": "ok",
            "as_of": "2026-10-11",
            "gift_cards_retired": 2,
            "cards_rescored": 7,
        }

    monkeypatch.setattr(optimize_product_cards, "rescore_shop_cards", fake)
    caplog.set_level(logging.INFO, logger="juli_backend.workers.tasks.rescore_shop_cards")
    await rescore_shop_cards_async(
        shop_id, session_factory=async_sessionmaker(engine, expire_on_commit=False), now=START
    )
    [record] = [r for r in caplog.records if r.getMessage().startswith("rescore_shop_cards_done")]
    message = record.getMessage()
    assert f"shop_id={shop_id}" in message
    assert "gift_cards_retired=2" in message and "cards_rescored=7" in message
    assert record.cards_rescored == 7  # the extras stay too


# =========================================================================== Ops


@pytest.fixture
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


@pytest.mark.asyncio
async def test_ops_admin_turns_the_mode_on_and_sees_cells(session, bypass_access):
    from tests.unit.test_p23_volatility import _staff_client

    _, shop = await make_tenant(session)
    url = f"/v1/ops/shops/{shop.id}/settings"
    session.add(_card(shop.id, 1, surfaced_at=START))
    await session.flush()
    operator, _ = await _staff_client(session, "operator")
    async with operator as client:
        got = (await client.get(url)).json()
        assert got["settings"]["defaults"]["card_quota_mode"] is False
        assert got["settings"]["defaults"]["card_quota_per_cell"] == 5
        assert got["settings"]["defaults"]["card_quota_max_open"] == 40
        assert "card_cells" not in got  # mode off: no extra read
        denied = await client.put(url, json={"changes": {"card_quota_mode": True}})
        assert denied.status_code == 403  # a team (Admin) setting
    admin, _ = await _staff_client(session, "admin")
    async with admin as client:
        bad = await client.put(url, json={"changes": {"card_quota_per_cell": 0}})
        assert bad.status_code == 422
        put = await client.put(url, json={"changes": {"card_quota_mode": True}})
        assert put.status_code == 200, put.text
        assert put.json()["settings"]["overrides"]["card_quota_mode"] is True
        got = (await client.get(url)).json()
        assert got["card_cells"] == {"ctr@product_card": 1}
    assert await shop_card_quota(session, shop.id) is not None
