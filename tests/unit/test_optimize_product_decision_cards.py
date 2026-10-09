"""Optimize Product cards from the ADR-106 pipeline on P1 data (fasttrack P7-B).

AC-7.3: the whole catalog is scored per shop from the daily per-product
analytics P1 stores; the top 10 are ranked, one card per product, at most 5
surfaced; each card carries the diagnosed stage, the lever and the funnel
evidence (TikTok's KPI names, 30 days vs the 30 before) in ``/v1/demo/decisions``.
Two shops never see each other's cards. D22: the ranking is recoverable GMV per
day, labelled a rule-based estimate.

AC-7.4: approving one of these cards still creates a real run of
``optimize_product_2``, whose write steps are CONFIRM.

The "fake TikTok" here is the analytics rows a P1 fetch would have stored.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.integrations.tiktok.mapping import (
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    merge_product_analytics_rows,
)
from juli_backend.models.models import (
    ActionCard,
    AnalyticsPerformanceInterval,
    DecisionEmissionNoveltyLedger,
    Product,
    Shop,
    User,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.action_cards.emission_budget import apply_emission_budget
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    WITHDRAWN_STATUS,
    plan_optimize_product_cards,
    withdraw_unranked_cards,
)
from juli_backend.services.action_cards.persist import persist_scoring_result
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)
from juli_backend.services.optimize_product.daily_funnel import ProductDay, funnel_evidence
from juli_backend.services.optimize_product.decision_cards import recoverable_gmv_per_day
from juli_backend.services.optimize_product.diagnosis import Branch, Gap
from juli_backend.services.optimize_product.funnel import FunnelWindow
from juli_backend.services.scoring.types import (
    DailyScoringResult,
    ScoringSignals,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

AS_OF = date(2026, 10, 6)
COMPUTED_AT = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)
DAYS = 60
AOV = Decimal("200000")
LONG_TITLE = "Bình giữ nhiệt inox 304 dung tích lớn giữ lạnh 24 giờ cho dân văn phòng"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- fake catalog

#: (suffix, ctr, ctor, short_title). 13 healthy peers keep the shop medians at
#: CTR 5 % / CTOR 5 %; 6 products lose clicks (card branch) and 6 lose orders
#: (page branch); one gift listing is weak but excluded.
CATALOG: list[tuple[str, Decimal, Decimal, bool]] = (
    [(f"healthy{i:02d}", Decimal("0.05"), Decimal("0.05"), False) for i in range(13)]
    + [(f"weakctr{i:02d}", Decimal("0.02"), Decimal("0.05"), i < 3) for i in range(6)]
    + [(f"weakctor{i:02d}", Decimal("0.05"), Decimal("0.02"), False) for i in range(6)]
)


async def _seed_shop(session, label: str, *, catalog=CATALOG, cart_days: int = 5) -> Shop:
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name=f"{label} shop")
    session.add(shop)
    await session.flush()
    now = _now()
    rows: list[dict] = []
    for index, (suffix, ctr, ctor, short) in enumerate(catalog):
        tiktok_id = f"{label}-{suffix}"
        title = f"{label} {suffix}" if short else f"{LONG_TITLE} {label} {suffix}"
        session.add(
            Product(
                shop_id=shop.id,
                tiktok_product_id=tiktok_id,
                title=title,
                name=title,
                status="ACTIVATE",
                # The healthy top seller: the rule pipeline's card would pin it.
                revenue=Decimal("999999999") if suffix == "healthy00" else Decimal("1000"),
                update_time=now,
            )
        )
        impressions = Decimal(2000 + 100 * index)
        clicks = (impressions * ctr).quantize(Decimal("1"))
        orders = (clicks * ctor).quantize(Decimal("1"))
        for offset in range(DAYS):
            day = AS_OF - timedelta(days=offset)
            breakdown = (
                {"A34_TOTAL": {"add_cart_count": int(clicks // 5), "clicks": int(clicks)}}
                if offset < cart_days
                else None
            )
            rows.append(
                dict(
                    id=uuid.uuid4(),
                    shop_id=shop.id,
                    snapshot_key=f"product:{tiktok_id}:{day.isoformat()}",
                    grain="product",
                    start_date=day,
                    end_date=day + timedelta(days=1),
                    tiktok_product_id=tiktok_id,
                    impressions=int(impressions),
                    clicks=int(clicks),
                    gmv=orders * AOV,
                    items_sold=int(orders),
                    orders_count=int(orders),
                    sku_orders=int(orders) if offset < cart_days else None,
                    traffic_breakdown=breakdown,
                    update_time=now,
                )
            )
            if offset >= cart_days:
                # Multi-day backfill days: SKU orders arrive on the SKU grain.
                rows.append(
                    dict(
                        id=uuid.uuid4(),
                        shop_id=shop.id,
                        snapshot_key=f"sku:{tiktok_id}-s1:{day.isoformat()}",
                        grain="sku",
                        start_date=day,
                        end_date=day + timedelta(days=1),
                        tiktok_product_id=tiktok_id,
                        tiktok_sku_id=f"{tiktok_id}-s1",
                        sku_orders=int(orders),
                        gmv=orders * AOV,
                        items_sold=int(orders),
                        update_time=now,
                    )
                )
    gift = f"{label}-gift"
    session.add(
        Product(
            shop_id=shop.id,
            tiktok_product_id=gift,
            title="Quà tặng kèm không bán",
            name="Quà tặng kèm không bán",
            status="ACTIVATE",
            update_time=now,
        )
    )
    for offset in range(DAYS):
        day = AS_OF - timedelta(days=offset)
        rows.append(
            dict(
                id=uuid.uuid4(),
                shop_id=shop.id,
                snapshot_key=f"product:{gift}:{day.isoformat()}",
                grain="product",
                start_date=day,
                end_date=day + timedelta(days=1),
                tiktok_product_id=gift,
                impressions=3000,
                clicks=30,
                gmv=Decimal("0"),
                sku_orders=0,
                update_time=now,
            )
        )
    await session.flush()
    # One bulk statement: ~3 000 ORM adds took > 30 s on a loaded machine.
    await session.execute(insert(AnalyticsPerformanceInterval), rows)
    await session.flush()
    return shop


def _scoring_result(shop_id: uuid.UUID) -> DailyScoringResult:
    workflows = [
        (OPTIMIZE_PRODUCT_WORKFLOW_KEY, "Tối ưu sản phẩm", 1),
        ("prevent_return_8b", "Giảm hoàn hàng", 2),
        ("process_order_5", "Xử lý đơn", 3),
    ]
    return DailyScoringResult(
        aggregates=FeatureAggregateSnapshot(
            shop_id=shop_id,
            shop_profile=ShopProfile.NEW_SHOP,
            health_data_source=HealthDataSource.PROXY,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            order_count=10,
            product_count=5,
            return_count=1,
            total_order_value=Decimal("100000"),
            total_product_revenue=Decimal("100000"),
            total_units_sold=10,
            return_rate_proxy=0.1,
            data_sources=["orders"],
        ),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=COMPUTED_AT,
            health_data_source=HealthDataSource.PROXY,
            kpis={},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.NEW_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key=key,
                    workflow_name=name,
                    priority=priority,
                    rationale="Test rationale",
                    expected_impact=WorkflowExpectedImpact(
                        metric="gmv", value=1.0, confidence="medium"
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=(),
                )
                for key, name, priority in workflows
            ],
        ),
        reasoning_summaries=(),
    )


async def _score(session, shop: Shop) -> list[ActionCard]:
    cards = await persist_scoring_result(session, shop.id, _scoring_result(shop.id))
    await apply_emission_budget(session, shop.id, now=COMPUTED_AT)
    await session.commit()
    return cards


async def _optimize_cards(session, shop_id: uuid.UUID, status: str = "active") -> list[ActionCard]:
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id,
        ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        ActionCard.status == status,
    )
    return list((await session.execute(stmt)).scalars().all())


@pytest_asyncio.fixture
async def shop_a(session):
    return await _seed_shop(session, "A")


# --------------------------------------------------------------------------- AC-7.3


@pytest.mark.asyncio
async def test_whole_catalog_is_scored_and_the_top_ten_ranked(session, shop_a):
    op = await plan_optimize_product_cards(session, shop_a.id, now=COMPUTED_AT)

    assert op is not None
    assert op.as_of == AS_OF
    plan = op.plan
    assert plan.products_scored == len(CATALOG) + 1  # every listing with analytics
    assert any("quà tặng" in reason for reason in plan.excluded.values())
    assert [p.rank for p in plan.proposals] == list(range(1, 11))
    assert plan.overflow == 2  # 12 weak products, 10 kept
    ids = [p.product_id for p in plan.proposals]
    assert len(set(ids)) == len(ids)
    assert not any("healthy" in pid for pid in ids)
    # Short titles under the CTR gap have local title evidence -> rule cards first.
    head = plan.proposals[:3]
    assert {p.status for p in head} == {"rule"}
    assert {p.lever.value for p in head} == {"tiêu đề"}
    assert {p.stage for p in head} == {Branch.CARD}
    rest = {p.status for p in plan.proposals[3:]}
    assert rest == {"tiktok_not_asked"}
    # D22: every proposal carries a recoverable-GMV estimate; ranking follows it.
    assert all(p.recoverable_gmv_per_day is not None for p in plan.proposals)


@pytest.mark.asyncio
async def test_scoring_writes_one_card_per_product_and_surfaces_at_most_five(session, shop_a):
    await _score(session, shop_a)

    cards = await _optimize_cards(session, shop_a.id)
    assert len(cards) == 10
    assert {c.subject_type for c in cards} == {"product"}
    assert len({c.subject_id for c in cards}) == 10
    surfaced = [c for c in cards if c.surfaced_at is not None]
    assert len(surfaced) == 5
    assert sorted(c.priority for c in surfaced) == [1, 2, 3, 4, 5]
    assert {c.suppressed_reason for c in cards if c.surfaced_at is None} == {"active_cap"}

    # The rule pipeline's single top-revenue card is not emitted for this shop.
    top = (
        await session.execute(select(Product).where(Product.tiktok_product_id == "A-healthy00"))
    ).scalar_one()
    assert str(top.id) not in {c.subject_id for c in cards}

    # Other workflows still surface beside them: the 5 product cards take one slot.
    others = (
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_a.id,
                    ActionCard.workflow_key != OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                )
            )
        )
        .scalars()
        .all()
    )
    assert {c.workflow_key for c in others if c.surfaced_at is not None} == {
        "prevent_return_8b",
        "process_order_5",
    }

    payload = json.loads(surfaced[0].recommendation_payload)
    diagnosis, evidence = payload["diagnosis"], payload["evidence"]
    assert diagnosis["stage"]["code"] in {"card", "page", "basket"}
    assert diagnosis["lever"]["label"]
    assert diagnosis["recoverable_gmv_per_day"] > 0
    assert diagnosis["recoverable_gmv_basis"]["label"].startswith("Ước tính theo quy tắc")
    assert payload["expected_impact"]["metric"] == "recoverable_gmv_per_day"
    labels = [m["label"] for m in evidence["metrics"]]
    assert labels[:5] == [
        "Lượt hiển thị sản phẩm",
        "CTR",
        "Tỷ lệ thêm vào giỏ hàng",
        "CTOR",
        "AOV",
    ]


@pytest.mark.asyncio
async def test_rescoring_is_idempotent_and_keeps_one_card_per_product(session, shop_a):
    await _score(session, shop_a)
    first = {c.subject_id: c.id for c in await _optimize_cards(session, shop_a.id)}
    await _score(session, shop_a)
    second = {c.subject_id: c.id for c in await _optimize_cards(session, shop_a.id)}

    assert first == second
    novelty = (
        (
            await session.execute(
                select(DecisionEmissionNoveltyLedger).where(
                    DecisionEmissionNoveltyLedger.shop_id == shop_a.id,
                    DecisionEmissionNoveltyLedger.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(novelty) == 1


@pytest.mark.asyncio
async def test_two_shops_are_scored_in_isolation(session, shop_a):
    small = CATALOG[:6] + CATALOG[13:15] + CATALOG[19:21]
    shop_b = await _seed_shop(session, "B", catalog=small)

    await _score(session, shop_a)
    await _score(session, shop_b)

    b_products = {
        str(p.id)
        for p in (
            await session.execute(select(Product).where(Product.shop_id == shop_b.id))
        ).scalars()
    }
    b_cards = await _optimize_cards(session, shop_b.id)
    a_cards = await _optimize_cards(session, shop_a.id)
    assert b_cards and {c.subject_id for c in b_cards} <= b_products
    assert not {c.subject_id for c in a_cards} & b_products
    # Shop B's medians come from its own 10 listings, not shop A's 26.
    for card in b_cards:
        diagnosis = json.loads(card.recommendation_payload)["diagnosis"]
        assert diagnosis["tiktok_product_id"].startswith("B-")
        assert sum(diagnosis["shop_medians"]["peers"].values()) <= 3 * len(small)


@pytest.mark.asyncio
async def test_a_shop_without_product_analytics_keeps_the_rule_card(session):
    user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(user_id=user.id, shop_name="no analytics")
    session.add(shop)
    await session.flush()
    session.add(
        Product(
            shop_id=shop.id,
            tiktok_product_id="solo",
            title="solo",
            name="solo",
            status="ACTIVATE",
            revenue=Decimal("10"),
            update_time=_now(),
        )
    )
    await session.flush()

    await _score(session, shop)

    cards = await _optimize_cards(session, shop.id)
    assert len(cards) == 1
    assert "diagnosis" not in json.loads(cards[0].recommendation_payload)


@pytest.mark.asyncio
async def test_unranked_drafts_are_withdrawn_and_revived(session, shop_a):
    await _score(session, shop_a)
    drafts = [c for c in await _optimize_cards(session, shop_a.id) if c.surfaced_at is None]
    surfaced = [c for c in await _optimize_cards(session, shop_a.id) if c.surfaced_at]
    keep = {c.subject_id for c in surfaced}

    withdrawn = await withdraw_unranked_cards(session, shop_a.id, keep_subject_ids=keep)
    await session.commit()

    assert {c.id for c in withdrawn} == {c.id for c in drafts}
    assert len(await _optimize_cards(session, shop_a.id, WITHDRAWN_STATUS)) == len(drafts)

    await _score(session, shop_a)  # still ranked -> revived in place, same rows
    assert {c.id for c in await _optimize_cards(session, shop_a.id)} == {
        c.id for c in drafts + surfaced
    }


# --------------------------------------------------------------------------- API


def _client(app, user, shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def app(session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_decisions_endpoint_returns_diagnosis_and_evidence(app, session, shop_a):
    await _score(session, shop_a)
    user = await session.get(User, shop_a.user_id)

    async with _client(app, user, shop_a) as client:
        resp = await client.get("/v1/demo/decisions")

    assert resp.status_code == 200, resp.text
    items = [i for i in resp.json()["data"] if i["recommendation"].get("diagnosis")]
    assert len(items) == 5
    first = items[0]["recommendation"]
    diagnosis, evidence = first["diagnosis"], first["evidence"]
    assert diagnosis["rank"] == 1
    assert diagnosis["status"] == "rule"
    assert diagnosis["stage"] == {"code": "card", "label": "Hiển thị → Nhấp (thẻ sản phẩm)"}
    assert diagnosis["lever"]["code"] == "title"
    assert diagnosis["main_kpi"]["label"] == "CTOR"
    assert diagnosis["trigger"]["code"] == "shop_median"
    assert diagnosis["recoverable_gmv_per_day"] > 0
    assert first["expected_impact"]["confidence"] == "rule_based_estimate"
    assert evidence["window_days"] == 30
    by_key = {m["key"]: m for m in evidence["metrics"]}
    assert by_key["ctr"]["current"] == pytest.approx(0.02, abs=1e-3)
    assert by_key["ctor"]["definition"] == "Đơn hàng SKU ÷ lượt nhấp"
    assert by_key["aov"]["current"] == pytest.approx(200000)
    assert by_key["add_to_cart_rate"]["current"] == pytest.approx(0.2, abs=1e-2)
    assert by_key["add_to_cart_rate"]["note"]  # only 5 of 30 days carry it
    assert by_key["impressions"]["confidence"] in {"Rõ", "Tham khảo", "Chưa đủ dữ liệu"}
    assert items[0]["is_executable"] is True
    # No internal identifiers in the public body.
    body = resp.text
    assert OPTIMIZE_PRODUCT_WORKFLOW_KEY not in body
    for card in await _optimize_cards(session, shop_a.id):
        assert card.subject_id not in body


@pytest.mark.asyncio
async def test_approving_an_adr106_card_creates_an_optimize_product_run(app, session, shop_a):
    from juli_backend.services.agent import playbooks
    from juli_backend.services.agent.tools.registry import ToolPolicy

    await _score(session, shop_a)
    user = await session.get(User, shop_a.user_id)
    card = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)

    task = MagicMock()
    task.delay.return_value = MagicMock(id="celery-p7b")
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", task):
        async with _client(app, user, shop_a) as client:
            resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

    assert resp.status_code == 202, resp.text
    run = (
        await session.execute(
            select(WorkflowRunRow).where(WorkflowRunRow.action_card_id == card.id)
        )
    ).scalar_one()
    assert run.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY
    assert str(run.product_id) == card.subject_id
    assert run.status == "queued"
    # The run's writes stay behind CONFIRM (D13: write policy unchanged).
    playbook = playbooks.get_playbook(run.workflow_key)
    write_steps = [s for s in playbook.steps if "update_product_listing" in s.tools]
    assert write_steps and all(s.policy is ToolPolicy.CONFIRM for s in write_steps)


# --------------------------------------------------------------------------- pure pieces


def test_recoverable_gmv_per_day_follows_d22():
    window = FunnelWindow(
        days=30,
        impressions=Decimal(60000),
        clicks=Decimal(1200),
        sku_orders=Decimal(60),
        items_sold=Decimal(60),
        gmv=Decimal(60) * AOV,
    )

    def gap(factor, value, median):
        return Gap(factor, value, median, None, 1 - value / median, None, True, median_peers=5)

    ctor_gaps = {"ctor": gap("ctor", Decimal("0.05"), Decimal("0.08"))}
    value, basis = recoverable_gmv_per_day(Branch.PAGE, ctor_gaps, window)
    # (0.08 − 0.05) × 40 clicks/day × 200 000 ₫
    assert value == Decimal("0.03") * 40 * AOV
    assert basis["reference"] == "shop_median"

    ctr_gaps = {"ctr": gap("ctr", Decimal("0.02"), Decimal("0.05"))}
    value, _ = recoverable_gmv_per_day(Branch.CARD, ctr_gaps, window)
    # (0.05 − 0.02) × 2000 impressions/day × CTOR 0.05 × 200 000 ₫
    assert value == Decimal("0.03") * 2000 * Decimal("0.05") * AOV
    assert recoverable_gmv_per_day(Branch.CARD, ctr_gaps, None) == (None, None)


def test_funnel_evidence_uses_tiktok_definitions_and_previous_window():
    rows = [
        ProductDay(
            day=AS_OF - timedelta(days=offset),
            impressions=Decimal(1000),
            clicks=Decimal(50 if offset < 30 else 40),
            sku_orders=Decimal(2),
            items_sold=Decimal(2),
            gmv=Decimal(400000),
            add_to_cart=Decimal(10) if offset < 30 else None,
            cart_clicks=Decimal(50) if offset < 30 else None,
        )
        for offset in range(60)
    ]

    evidence = funnel_evidence(rows, as_of=AS_OF)

    by_key = {m["key"]: m for m in evidence["metrics"]}
    assert by_key["impressions"]["current"] == 1000
    assert by_key["ctr"]["current"] == pytest.approx(0.05)
    assert by_key["ctr"]["previous"] == pytest.approx(0.04)
    assert by_key["ctr"]["change"] == pytest.approx(0.25)
    assert by_key["add_to_cart_rate"]["current"] == pytest.approx(0.2)
    assert by_key["add_to_cart_rate"]["previous"] is None
    assert by_key["ctor"]["current"] == pytest.approx(0.04)
    assert by_key["aov"]["current"] == pytest.approx(200000)
    assert by_key["gmv"]["current"] == pytest.approx(400000)
    # 60 SKU orders a side: CTR differs clearly → "Rõ"; AOV is flat → "Tham khảo".
    assert by_key["ctr"]["confidence"] == "Rõ"
    assert by_key["aov"]["confidence"] == "Tham khảo"
    assert evidence["current"]["days_with_data"] == 30
    assert evidence["previous"]["days_with_data"] == 30


@pytest.mark.asyncio
async def test_budget_gives_a_capped_workflow_one_slot_and_its_own_cap(session, shop_a):
    for index in range(7):
        session.add(
            ActionCard(
                shop_id=shop_a.id,
                workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
                subject_type="product",
                subject_id=str(uuid.uuid4()),
                priority=index + 1,
                severity="warning",
                title="t",
                description="d",
                recommendation_payload="{}",
                status="active",
            )
        )
    for index in range(6):
        session.add(
            ActionCard(
                shop_id=shop_a.id,
                workflow_key=f"wf_{index}",
                priority=index + 1,
                severity="warning",
                title="t",
                description="d",
                recommendation_payload="{}",
                status="active",
            )
        )
    await session.flush()
    config = DecisionEmissionConfig(max_active=5, cooldown_days=7, weekly_novelty_cap=10)

    outcome = await apply_emission_budget(session, shop_a.id, now=COMPUTED_AT, config=config)

    keys = [c.workflow_key for c in outcome.surfaced]
    assert keys.count(OPTIMIZE_PRODUCT_WORKFLOW_KEY) == 5
    assert len([k for k in keys if k != OPTIMIZE_PRODUCT_WORKFLOW_KEY]) == 4
    assert len(outcome.suppressed["active_cap"]) == 4


def test_a34_add_to_cart_joins_the_detail_row():
    item = {
        "id": "p1",
        "total_performance": {
            "gmv": {"amount": "100", "currency": "VND"},
            "sku_orders": 1,
            "product_clicks": 50,
            "product_impressions": 1000,
            "add_cart_count": 9,
            "click_order_rate": "0.02",
        },
    }
    list_row = expand_analytics_product_list_item(
        item, start_date="2026-10-06", end_date="2026-10-07", synced_at=1
    )
    detail = expand_analytics_product_detail(
        {
            "performance": {
                "intervals": [
                    {
                        "start_date": "2026-10-06",
                        "end_date": "2026-10-07",
                        "sales": {"gmv": {"amount": "100"}},
                        "traffic": {
                            "breakdowns": [
                                {
                                    "content_type": "VIDEO",
                                    "traffic": {"impressions": 1000, "ctr": "0.05"},
                                }
                            ]
                        },
                    }
                ]
            }
        },
        synced_at=1,
        product_id="p1",
    )

    (merged,) = merge_product_analytics_rows(detail, list_row)

    assert merged["traffic_breakdown"]["VIDEO"]["impressions"] == 1000
    assert merged["traffic_breakdown"]["A34_TOTAL"] == {
        "add_cart_count": 9,
        "clicks": 50,
        "impressions": 1000,
    }


@pytest.mark.asyncio
async def test_the_p1_scoring_hook_produces_the_adr106_cards(session, shop_a):
    """D11: bootstrap fast phase and the daily analytics pass call
    ``score_and_persist_cards``; that path now yields the ranked product cards."""
    from juli_backend.workers.tasks.shop_ingestion import score_and_persist_cards

    await score_and_persist_cards(session, shop_a.id)

    cards = await _optimize_cards(session, shop_a.id)
    assert len(cards) == 10
    assert len([c for c in cards if c.surfaced_at is not None]) == 5
    assert all("diagnosis" in json.loads(c.recommendation_payload) for c in cards)


# --------------------------------------------------------------- AC-8.3 rules wiring


@pytest.mark.asyncio
async def test_the_sellers_max_open_cards_rule_caps_the_surfaced_cards(session, shop_a):
    """ADR-109 d.12 "Số thẻ mở cùng lúc": the seller's number replaces the 5."""
    from juli_backend.services import shop_rules

    await shop_rules.set_rule(
        session,
        shop_a.id,
        rule_key=shop_rules.MAX_OPEN_CARDS,
        scope_ref=None,
        value=2,
        set_by="team",
        set_by_user_id=shop_a.user_id,
    )
    await _score(session, shop_a)

    cards = await _optimize_cards(session, shop_a.id)
    assert len(cards) == 10, "the ranking is unchanged; only surfacing is capped"
    surfaced = [c for c in cards if c.surfaced_at is not None]
    assert sorted(c.priority for c in surfaced) == [1, 2]


@pytest.mark.asyncio
async def test_a_lever_the_seller_did_not_allow_is_not_executable_nor_approvable(
    app, session, shop_a
):
    """ADR-109 d.12 "Đòn bẩy được phép tự thực thi": list and approve agree."""
    from juli_backend.services import shop_rules

    await _score(session, shop_a)
    user = await session.get(User, shop_a.user_id)
    async with _client(app, user, shop_a) as client:
        allowed = (await client.get("/v1/demo/decisions")).json()["data"]
    title_cards = [
        i
        for i in allowed
        if (i["recommendation"].get("diagnosis") or {}).get("lever", {}).get("code") == "title"
    ]
    assert title_cards and all(i["is_executable"] for i in title_cards)

    await shop_rules.set_rule(
        session,
        shop_a.id,
        rule_key=shop_rules.AUTO_LEVERS,
        scope_ref=None,
        value=["description", "image"],
        set_by="seller",
        set_by_user_id=shop_a.user_id,
    )
    await session.commit()
    async with _client(app, user, shop_a) as client:
        after = {i["id"]: i for i in (await client.get("/v1/demo/decisions")).json()["data"]}
        approve = await client.post(f"/v1/demo/decisions/{title_cards[0]['id']}/approve")
    assert all(after[i["id"]]["is_executable"] is False for i in title_cards)
    assert approve.status_code == 409


def test_promotion_levers_never_execute_and_legacy_cards_are_not_judged():
    from juli_backend.services import shop_rules

    every = shop_rules.DEFAULT_AUTO_LEVERS
    assert shop_rules.card_lever_allowed("title", every)
    assert shop_rules.card_lever_allowed("cover_image", every)
    for promo in ("product_discount", "flash_sale", "shipping_discount", "buy_more_save_more"):
        assert not shop_rules.card_lever_allowed(promo, every)
    assert shop_rules.card_lever_allowed(None, frozenset())
