"""AC-10.2 (fast track P10-B), contract §5: the Seller Center promotion flow.

- the proposal respects the seller's rules (margin floor, per-SKU cap) and is
  refused when they leave no room; a run for a product with no cost fails
  loudly (the card should not exist);
- each of the four promotion types gets its own Vietnamese steps;
- a promotion run, driven by the real ``WorkflowRunner`` with the promotion
  playbook and planner: reads, narrates the rules check, waits
  (``awaiting = "seller_action"``); on "Tôi đã áp dụng" it looks for the
  promotion read-only (``tool.*`` events) -- not found: "Chưa tìm thấy trên
  TikTok", still waiting, a re-check scheduled; found: done, and the
  measurement clock starts at the promotion's start date. TikTok's promotion
  write methods and the listing edit are never called (D13);
- approving a promotion card creates the run and its flow row;
- the routes: instructions, applied (202/409/404), revert unavailable with
  ``seller_center``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.lever_flows import RunLeverFlow
from juli_backend.models.models import ActionCard
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services import lever_flows, shop_rules
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.lever_flows import promotion
from juli_backend.services.lever_flows.driver import FlowWiring, LeverFlowRunner
from tests.support.lever_flows import (
    DETAIL,
    NO_SYNC_SESSION,
    PRODUCT_ID,
    FakeProducts,
    FakePromotion,
    api_client,
    card_payload,
    resources,
    seed_run,
    seed_shop,
)

TODAY = date(2026, 10, 9)
RULES = promotion.PromotionRules(
    cost=Decimal(180000),
    min_margin=Decimal("0.30"),
    min_margin_set=True,
    caps_by_sku={"sku-1": Decimal("0.10")},
)

# --- the proposal ----------------------------------------------------------------------


def test_the_product_discount_keeps_the_margin_floor_and_the_cap():
    proposal = promotion.propose("product_discount", RULES, DETAIL, today=TODAY)
    assert proposal.ok
    # 1 − 180k / (279k × 0.7) = 7.8 % headroom < the 10 % cap -> 7 %.
    assert proposal.discount_pct == 7
    assert proposal.new_price == Decimal(259000)
    assert proposal.margin_after_pct == 30 and proposal.min_margin_pct == 30
    assert proposal.cap_pct == 10
    assert (proposal.start, proposal.end) == (TODAY, date(2026, 11, 7))
    assert proposal.seller_sku == "KD-030"
    sentence = promotion.rules_sentence(proposal)
    assert "biên lợi nhuận sau giảm 30 % ≥ 30 %" in sentence
    assert "giảm 7 % ≤ trần 10 %" in sentence


def test_a_tighter_cap_wins():
    rules = promotion.PromotionRules(
        cost=Decimal(100000),
        min_margin=Decimal("0.10"),
        min_margin_set=True,
        caps_by_sku={"sku-1": Decimal("0.05")},
    )
    assert promotion.propose("flash_sale", rules, DETAIL, today=TODAY).discount_pct == 5


def test_no_room_under_the_rules_is_a_refusal_not_a_discount():
    rules = promotion.PromotionRules(
        cost=Decimal(270000), min_margin=Decimal("0.30"), min_margin_set=True
    )
    proposal = promotion.propose("product_discount", rules, DETAIL, today=TODAY)
    assert not proposal.ok
    assert proposal.refusal_vi and "biên lợi nhuận" in proposal.refusal_vi


def test_the_proposal_round_trips_through_json():
    proposal = promotion.propose("shipping_discount", RULES, DETAIL, today=TODAY)
    assert promotion.PromotionProposal.from_json(proposal.to_json()) == proposal


@pytest.mark.parametrize(
    ("lever", "first_step", "detail"),
    [
        ("product_discount", "Giảm giá sản phẩm", "Đặt giá giảm 259.000 ₫"),
        ("flash_sale", "Flash sale", "giá flash 259.000 ₫ (−7 %)"),
        ("shipping_discount", "Giảm phí vận chuyển", "Giảm 19.000 ₫ phí vận chuyển cho đơn từ"),
        ("buy_more_save_more", "Mua nhiều giảm nhiều", "mua từ 2 sản phẩm giảm 7 %"),
    ],
)
def test_each_promotion_type_has_its_own_four_steps(lever, first_step, detail):
    proposal = promotion.propose(lever, RULES, DETAIL, today=TODAY)
    result = promotion.instructions(proposal, product_name="Kem dưỡng ẩm ceramide 50ml")
    assert len(result.steps) == 4
    assert first_step in result.steps[0]
    assert any(detail in step for step in result.steps), result.steps
    assert any("KD-030" in step for step in result.steps)
    assert result.deep_link.startswith("https://seller-vn.tiktok.com/")
    assert result.summary.startswith(promotion.TYPE_LABELS_VI[lever])


@pytest.mark.asyncio
async def test_a_promotion_run_without_a_cost_fails_loudly(session):
    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product, lever="product_discount", flow_kind="promotion")
    with pytest.raises(promotion.PromotionRulesMissing):
        await lever_flows.wiring_for_run(
            session,
            NO_SYNC_SESSION,
            run,
            product,
            product_detail=lambda: None,
        )


# --- the run, end to end through the real runner -----------------------------------------


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


async def _set_rules(session, shop_id):
    for key, scope, value in (
        (shop_rules.PRODUCT_COST, PRODUCT_ID, 180000),
        (shop_rules.MIN_MARGIN_PCT, None, 30),
        (shop_rules.MAX_DISCOUNT_PCT, "sku-1", 10),
    ):
        await shop_rules.set_rule(
            session,
            shop_id,
            rule_key=key,
            scope_ref=scope,
            value=value,
            set_by="seller",
            set_by_user_id=None,
        )


class Leg:
    """What the worker builds for one leg of a promotion run (see ``_construct_runner``)."""

    def __init__(self, session, run, wiring, products, promo, sink, scheduled):
        guard = ConcurrencyGuard(basis_snapshot=run.state.get("basis_snapshots", {}))
        res = resources(products, promo)
        executor = ProductToolExecutor(
            registry=_registry(),
            read_resources=res,
            write_resources=res,
            product_id=PRODUCT_ID,
            concurrency_guard=guard,
            product_detail=run.state.get("product_detail"),
        )

        def _detail():
            return guard.get_product_detail() or run.state.get("product_detail")

        wiring.planner.product_detail = _detail
        wiring.planner.today = lambda: TODAY
        runner = WorkflowRunner(
            llm_service=wiring.planner,
            tool_executor=executor,
            event_sink=sink,
            conversation_store=JsonbConversationStore(session),
            registry=_registry(),
            playbook=wiring.playbook,
            concurrency_guard=guard,
        )
        self.flow_runner = LeverFlowRunner(
            runner,
            session=session,
            wiring=wiring,
            product_detail=_detail,
            schedule_recheck=scheduled.append,
        )

    @classmethod
    async def build(cls, session, run_id, products, promo, sink, scheduled):
        run = await session.get(WorkflowRunRow, run_id)
        await session.refresh(run)
        from juli_backend.models.models import Product

        product = await session.get(Product, run.product_id)
        wiring = await lever_flows.wiring_for_run(
            session,
            NO_SYNC_SESSION,
            run,
            product,
            product_detail=lambda: None,
        )
        assert isinstance(wiring, FlowWiring)
        assert wiring.playbook is lever_flows.PROMOTION_PLAYBOOK
        return cls(session, run, wiring, products, promo, sink, scheduled)


async def _start(session):
    shop, product = await seed_shop(session)
    await _set_rules(session, shop.id)
    run = await seed_run(session, shop, product, lever="product_discount", flow_kind="promotion")
    await session.commit()
    return shop, run


async def _flow(session, run_id) -> RunLeverFlow:
    flow = (
        await session.execute(select(RunLeverFlow).where(RunLeverFlow.workflow_run_id == run_id))
    ).scalar_one()
    await session.refresh(flow)
    return flow


def _narrations(sink) -> list[str]:
    return [e.payload.phase_narration for e in sink.events if e.event_type == "workflow.status"]


@pytest.mark.asyncio
async def test_a_promotion_run_checks_the_rules_waits_verifies_and_never_writes(session):
    shop, run = await _start(session)
    products, promo, sink, scheduled = FakeProducts(), FakePromotion(), InMemoryEventSink(), []
    promo.add("already-running", activity_type="FLASHSALE")  # another type, ignored

    # Leg 1 (approve): read, rules check, wait for the seller.
    leg1 = await Leg.build(session, run.id, products, promo, sink, scheduled)
    paused = await leg1.flow_runner.run(run.id, product_ref=PRODUCT_ID)
    await session.commit()
    assert paused.status == WorkflowRunStatus.WAITING_EXTERNAL
    row = await session.get(WorkflowRunRow, run.id)
    await session.refresh(row)
    assert lever_flows.awaiting_of(row) == "seller_action"
    assert _narrations(sink)[-1] == "Đang chờ bạn áp dụng trên Seller Center"
    texts = [e.payload.text for e in sink.events if e.event_type == "assistant.text"]
    assert texts == [
        promotion.rules_sentence(promotion.propose("product_discount", RULES, DETAIL, today=TODAY))
    ]
    flow = await _flow(session, run.id)
    assert flow.proposal["discount_pct"] == 7 and flow.proposal["new_price"] == 259000
    assert [e.payload.tool_name for e in sink.events if e.event_type == "tool.completed"] == [
        "get_product_information",
        "find_product_promotions",
    ]

    # Leg 2 ("Tôi đã áp dụng", nothing on TikTok yet): still waiting, re-check scheduled.
    leg2 = await Leg.build(session, run.id, products, promo, sink, scheduled)
    again = await leg2.flow_runner.resume_after_external_wait(run.id)
    await session.commit()
    assert again.status == WorkflowRunStatus.WAITING_EXTERNAL
    assert _narrations(sink)[-1] == "Chưa tìm thấy trên TikTok"
    assert lever_flows.awaiting_of(await session.get(WorkflowRunRow, run.id)) == "seller_action"
    assert scheduled == [run.id]
    assert (await _flow(session, run.id)).verify_attempts == 1
    completed = [e for e in sink.events if e.event_type == "tool.completed"]
    assert completed[-1].payload.tool_name == "find_product_promotions"
    assert completed[-1].payload.summary == "Không có khuyến mãi loại này cho sản phẩm"

    # Leg 3: the seller's promotion is there now -> done, the clock starts at its start.
    promo.add("sellers-new-discount", activity_type="DIRECT_DISCOUNT")
    leg3 = await Leg.build(session, run.id, products, promo, sink, scheduled)
    done = await leg3.flow_runner.resume_after_external_wait(run.id)
    await session.commit()
    assert done.status == WorkflowRunStatus.COMPLETED
    assert "Đã xác nhận trên TikTok" in (done.final_response or "")
    flow = await _flow(session, run.id)
    assert flow.measurement_start == date(2026, 10, 9)
    assert flow.found["type_label"] == "Giảm giá sản phẩm"
    assert flow.verify_attempts == 2
    assert sink.events[-1].event_type == "workflow.completed"

    # D13: no promotion write, no listing write, ever.
    assert promo.writes == []
    assert products.edits == [] and products.uploads == []
    assert set(promo.searches) <= {"FIXED_PRICE", "DIRECT_DISCOUNT"}


@pytest.mark.asyncio
async def test_a_promotion_that_already_existed_is_not_taken_as_the_sellers(session):
    shop, run = await _start(session)
    products, promo, sink, scheduled = FakeProducts(), FakePromotion(), InMemoryEventSink(), []
    promo.add("old-discount", activity_type="FIXED_PRICE")
    await (await Leg.build(session, run.id, products, promo, sink, scheduled)).flow_runner.run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    leg2 = await Leg.build(session, run.id, products, promo, sink, scheduled)
    result = await leg2.flow_runner.resume_after_external_wait(run.id)
    assert result.status == WorkflowRunStatus.WAITING_EXTERNAL
    assert _narrations(sink)[-1] == "Chưa tìm thấy trên TikTok"
    assert promo.writes == []


@pytest.mark.asyncio
async def test_no_room_under_the_rules_ends_the_run_without_waiting(session):
    shop, product = await seed_shop(session)
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key=shop_rules.PRODUCT_COST,
        scope_ref=PRODUCT_ID,
        value=270000,
        set_by="seller",
        set_by_user_id=None,
    )
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key=shop_rules.MIN_MARGIN_PCT,
        scope_ref=None,
        value=30,
        set_by="seller",
        set_by_user_id=None,
    )
    run = await seed_run(session, shop, product, lever="product_discount", flow_kind="promotion")
    await session.commit()
    products, promo, sink = FakeProducts(), FakePromotion(), InMemoryEventSink()
    leg = await Leg.build(session, run.id, products, promo, sink, [])
    done = await leg.flow_runner.run(run.id, product_ref=PRODUCT_ID)
    assert done.status == WorkflowRunStatus.COMPLETED
    assert "Không đề xuất" in (done.final_response or "")
    assert promo.writes == []


# --- approve -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lever", "kind"),
    [("product_discount", "promotion"), ("cover_image", "photo"), ("title", None)],
)
@pytest.mark.asyncio
async def test_approving_a_card_registers_its_lever_flow(session, lever, kind):
    from juli_backend.services.agent import approval

    shop, product = await seed_shop(session)
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        subject_type="product",
        subject_id=str(product.id),
        priority=1,
        severity="medium",
        title="card",
        recommendation_payload=card_payload(lever=lever),
        status="active",
    )
    session.add(card)
    await session.flush()
    result = await approval.approve_action_card(
        session, shop_id=shop.id, action_card_id=card.id, approved_by_user_id=shop.user_id
    )
    flow = (
        await session.execute(
            select(RunLeverFlow).where(RunLeverFlow.workflow_run_id == result.run_id)
        )
    ).scalar_one_or_none()
    assert (flow.kind if flow else None) == kind
    if flow is not None:
        assert (flow.lever, flow.shop_id) == (lever, shop.id)


# --- the routes ------------------------------------------------------------------------------


@pytest.fixture
def enqueued(monkeypatch):
    from juli_backend.api.routes import demo_run_flows

    calls: list[uuid.UUID] = []

    def _enqueue(run_id):
        calls.append(run_id)
        return "task-1"

    monkeypatch.setattr(demo_run_flows, "_enqueue_resume_lever_flow", _enqueue)
    return calls


async def _waiting_promotion_run(session, label="a", *, status="waiting_external"):
    shop, product = await seed_shop(session, label)
    run = await seed_run(
        session,
        shop,
        product,
        lever="product_discount",
        flow_kind="promotion",
        status=status,
        external_wait_reason="seller_action",
        waiting_since=datetime(2026, 10, 9, 3, 0, tzinfo=UTC),
    )
    flow = await _flow(session, run.id)
    flow.proposal = promotion.propose("product_discount", RULES, DETAIL, today=TODAY).to_json()
    await session.commit()
    return shop, run


@pytest.mark.asyncio
async def test_instructions_and_applied_routes(engine, session, enqueued):
    shop, run = await _waiting_promotion_run(session)
    async with api_client(engine, shop) as client:
        steps = await client.get(f"/v1/demo/runs/{run.id}/instructions")
        detail = await client.get(f"/v1/demo/runs/{run.id}")
        applied = await client.post(f"/v1/demo/runs/{run.id}/applied")

    assert steps.status_code == 200, steps.text
    body = steps.json()
    assert len(body["steps"]) == 4 and body["deep_link"].startswith("https://seller-vn")
    assert "279k → 259k (−7 %)" in body["summary"]
    assert detail.json()["data"]["awaiting"] == "seller_action"
    assert detail.json()["data"]["promotion"]["proposal"]["discount_pct"] == 7
    assert applied.status_code == 202, applied.text
    assert applied.json()["status"] == "verifying"
    assert enqueued == [run.id]
    assert (await _flow(session, run.id)).applied_at is not None


@pytest.mark.asyncio
async def test_applied_409s_when_not_waiting_and_404s_for_another_shop(engine, session, enqueued):
    shop_a, run_a = await _waiting_promotion_run(session, "a")
    shop_b, run_b = await _waiting_promotion_run(session, "b", status="completed")
    async with api_client(engine, shop_b) as client:
        not_waiting = await client.post(f"/v1/demo/runs/{run_b.id}/applied")
        foreign = await client.post(f"/v1/demo/runs/{run_a.id}/applied")
        foreign_steps = await client.get(f"/v1/demo/runs/{run_a.id}/instructions")
    assert not_waiting.status_code == 409
    assert not_waiting.json()["detail"]["code"] == "not_awaiting_seller_action"
    assert foreign.status_code == 404 and foreign_steps.status_code == 404
    assert enqueued == []


@pytest.mark.asyncio
async def test_instructions_409_for_a_run_that_is_not_a_promotion(engine, session, enqueued):
    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product, lever="cover_image", flow_kind="photo")
    await session.commit()
    async with api_client(engine, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{run.id}/instructions")
        applied = await client.post(f"/v1/demo/runs/{run.id}/applied")
    assert resp.status_code == 409 and applied.status_code == 409


@pytest.mark.asyncio
async def test_a_promotion_run_cannot_be_reverted_reason_seller_center(
    engine, session, monkeypatch
):
    from juli_backend.api.routes import demo_run_changes

    monkeypatch.setattr(demo_run_changes, "_enqueue_run_agent_workflow", lambda _r: "task")
    shop, run = await _waiting_promotion_run(session, status="completed")
    async with api_client(engine, shop) as client:
        changes = await client.get(f"/v1/demo/runs/{run.id}/changes")
        revert = await client.post(f"/v1/demo/runs/{run.id}/revert")
    assert changes.status_code == 200
    availability = changes.json()["revert"]
    assert availability["available"] is False
    assert availability["reason_code"] == "seller_center"
    assert "Seller Center" in availability["message"]
    assert revert.status_code == 409
    assert revert.json()["detail"]["code"] == "seller_center"


# --- the read-only tool --------------------------------------------------------------------


def _find(promo, promotion_type="product_discount"):
    from juli_backend.services.agent.tools.product import (
        FindProductPromotionsInput,
        ProductToolContext,
        handle_find_product_promotions,
    )

    return handle_find_product_promotions(
        resources(FakeProducts(), promo),
        ProductToolContext(product_id=PRODUCT_ID),
        FindProductPromotionsInput(promotion_type=promotion_type),
    )


def test_the_tool_finds_only_live_promotions_of_the_type_that_include_the_product():
    promo = FakePromotion()
    promo.add("mine", activity_type="DIRECT_DISCOUNT")
    promo.add("expired", activity_type="FIXED_PRICE", status="EXPIRED")
    promo.add("someone-else", activity_type="FIXED_PRICE", product_ids=("other",))
    promo.add("flash", activity_type="FLASHSALE")
    result = _find(promo)
    assert [p.begin_date for p in result.promotions] == ["2026-10-09"]
    assert result.promotions[0].end_date == "2026-11-08"
    assert result.promotions[0].type_label == "Giảm giá sản phẩm"
    assert "mine" not in result.promotions[0].ref, "an opaque ref, never TikTok's id"
    assert promo.writes == []


def test_a_shop_wide_shipping_discount_counts_for_the_product():
    promo = FakePromotion()
    promo.add("ship", activity_type="SHIPPING_DISCOUNT", product_ids=())
    promo.details["ship"]["product_level"] = "SHOP"
    assert len(_find(promo, "shipping_discount").promotions) == 1


def test_a_tiktok_error_is_unavailable_not_a_crash():
    from juli_backend.integrations.tiktok import TikTokAPIError
    from juli_backend.services.agent.runner.seller_facing_copy import tool_completed_summary

    promo = FakePromotion()

    def _boom(**_):
        raise TikTokAPIError(36009004, "not authorised")

    promo.search_activities = _boom
    result = _find(promo)
    assert result.unavailable is True and result.promotions == []
    summary = tool_completed_summary("find_product_promotions", result.model_dump())
    assert summary == "Chưa đọc được khuyến mãi từ TikTok"
