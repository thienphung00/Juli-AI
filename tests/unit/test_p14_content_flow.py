"""P14-E content cards and runs, against the database and the real runner.

- the nightly cards: one per candidate, re-scored in place, ≤ 5 new per week,
  expiry after 7 days and its 7-day cooldown, the seller's reason cooldown,
  withdrawal of a surfaced card only when no longer valid (at target);
- the decisions item: ``recommendation.card`` with ``executor: "juli_drafts"``
  and ``content``, executable, no ``diagnosis``;
- a video run end to end through ``WorkflowRunner`` + ``ContentRunner``: reads
  (``tool.*``), rules, ONE model call (its tokens on the run), wait for the
  choice, Soạn lại (bản 2, sees bản 1), a rejected edit, Dùng with an edit,
  wait for the video, "Tôi đã đăng video" → found on TikTok → measuring; never a
  TikTok write;
- the poll: auto-detect, the day-7 / day-14 readings, the final verdict and the
  per-lever calibration, stored once;
- a LIVE run: the plan within the discount cap, Không thực hiện at the wait
  (existing decline route) → its 7-day cooldown keyed on ``live_script``;
- the routes: run detail ``content``, 202 / 409 / 422, measurement 409 before
  it starts.
"""

from __future__ import annotations

import copy as _copy
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.lever_flows import LeverCalibration, RunMeasurementFinal
from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.shop_diagnosis import ShopMetricRanking
from juli_backend.services import decision_reasons, lever_flows
from juli_backend.services.agent import composition, playbooks
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm.blocks import Usage
from juli_backend.services.agent.playbooks.base import validate_playbook_tools
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.content_cards import actions, emission, run_state
from juli_backend.services.content_cards import driver as content_driver
from juli_backend.services.content_cards import measurement as content_measurement
from juli_backend.services.content_cards import poll as content_poll
from juli_backend.services.content_cards.card_view import build_content_card_block
from juli_backend.services.content_cards.drafter import outcome_from_text
from juli_backend.services.content_cards.tools import shop_today
from juli_backend.services.demo_decisions.card_view import load_card_contexts
from juli_backend.services.demo_decisions.read import mask_decision_payload
from tests.support.lever_flows import (
    DETAIL,
    PRODUCT_ID,
    FakeProducts,
    FakePromotion,
    api_client,
    seed_shop,
)

NOW = datetime.now(UTC)
TODAY = shop_today(NOW)


# --- fixtures ------------------------------------------------------------------------------


def _video_table(rows):
    return {
        "stream": "seller_video",
        "metric": "ctr",
        "stream_prior": 0.032,
        "down": rows,
        "up": [],
    }


def _live_table(rows):
    return {
        "stream": "seller_live",
        "metric": "ctor",
        "stream_prior": 0.075,
        "down": rows,
        "up": [],
    }


def _row(rid, rate, quantity, gmv, products, name="Video trước và sau"):
    return {
        "id": rid,
        "name": name,
        "gmv_per_day": gmv,
        "last": rate,
        "prior": 0.032,
        "quantity_last": quantity,
        "date": "2026-09-27",
        "product_ids": products,
    }


async def _products(session, shop, ids_and_skus):
    out = {}
    for tiktok_id, sku in ids_and_skus:
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id=tiktok_id,
            name=f"Sản phẩm {sku}",
            status="ACTIVATE",
            update_time=datetime(2026, 10, 1),
        )
        session.add(product)
        session.add(
            InventoryItem(
                shop_id=shop.id,
                tiktok_product_id=tiktok_id,
                tiktok_sku_id=f"sku-{tiktok_id}",
                quantity=10,
                seller_sku=sku,
                update_time=datetime(2026, 10, 1),
            )
        )
        out[tiktok_id] = product
    await session.flush()
    return out


async def _cards(session, shop_id):
    rows = await session.execute(
        select(ActionCard).where(ActionCard.shop_id == shop_id).order_by(ActionCard.created_at)
    )
    return list(rows.scalars())


# --- the nightly cards ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidates_become_content_cards_with_the_contract_card_block(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015"), ("p-live", "SM-012")])
    tables = {
        "video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])]),
        "live": _live_table([_row("s1", 0.059, 30, -30_000, ["p-live"], "LIVE xả kho")]),
    }
    decisions = await emission.emit_content_cards(session, shop.id, now=NOW, rankings=tables)
    assert [d.suppressed_reason for d in decisions] == [None, None]
    cards = {c.workflow_key: c for c in await _cards(session, shop.id)}
    assert set(cards) == {"content_video", "content_live"}
    video = cards["content_video"]
    assert video.status == "active" and video.surfaced_at is None
    payload = json.loads(video.recommendation_payload)
    assert "diagnosis" not in payload and payload["card_executor"] == "juli_drafts"
    assert payload["content"]["lever_code"] == "video_script"

    contexts = await load_card_contexts(session, shop.id, [video])
    item = mask_decision_payload(
        video, allowed_levers=frozenset({"title"}), card_context=contexts[video.id]
    )
    assert item["is_executable"] is True
    card = item["recommendation"]["card"]
    assert card["workflow_label"] == "Tối ưu nội dung · Video"
    assert card["seller_sku"] == "MN-015" and card["status"] == "pending"
    assert card["main_kpi"] == {
        "key": "video_ctr",
        "label": "CTR - Video của người bán",
        "current": pytest.approx(0.019),
        "target": 0.032,
        "unit": "ratio",
    }
    assert card["expected_gmv_per_month"] == 56_000 * 30
    assert card["reason_short"] == "Video có lượt xem nhưng ít bấm vào sản phẩm"
    assert card["lever"] == {
        "code": "video_script",
        "label": "Kịch bản video mới",
        "executor": "juli_drafts",
    }
    assert card["content"]["chip"] == "Juli soạn · bạn làm"
    assert (
        card["content"]["measure"]
        == "CTR trên các video mới gắn MN-015 trong 7 và 14 ngày, so với video cũ."
    )
    assert len(card["content"]["will_draft"]) == 3
    live = build_content_card_block(
        cards["content_live"], json.loads(cards["content_live"].recommendation_payload), None
    )
    assert live["lever"]["label"] == "Kịch bản host + thứ tự giỏ"
    assert live["main_kpi"]["label"] == "CTOR - LIVE của người bán"
    # No discount cap set: no flash-sale line in "Juli sẽ soạn".
    assert "chưa đặt trần giảm giá" in live["content"]["will_draft"][-1]


@pytest.mark.asyncio
async def test_the_stored_rankings_are_read_when_none_are_given(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    session.add(
        ShopMetricRanking(
            shop_id=shop.id,
            end_date=date(2026, 10, 9),
            stream="seller_video",
            metric="ctr",
            ranking=_video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])]),
            built_at=datetime(2026, 10, 10),
        )
    )
    await session.flush()
    decisions = await emission.emit_content_cards(session, shop.id, now=NOW)
    assert [d.workflow_key for d in decisions] == ["content_video"]


@pytest.mark.asyncio
async def test_open_cards_are_rescored_in_place_and_at_most_five_new_ones_a_week(session):
    shop, _ = await seed_shop(session)
    ids = [(f"p{i}", f"SKU-{i}") for i in range(7)]
    await _products(session, shop, ids)
    rows = [_row(f"v{i}", 0.01, 300, -1_000 * (10 - i), [f"p{i}"]) for i in range(7)]
    first = await emission.emit_content_cards(
        session, shop.id, now=NOW, rankings={"video": _video_table(rows)}
    )
    assert [d.suppressed_reason for d in first].count(None) == 5
    assert [d.suppressed_reason for d in first][5:] == ["content_weekly_cap"] * 2
    cards = await _cards(session, shop.id)
    assert len(cards) == 5
    rows[0] = _row("v0", 0.012, 300, -20_000, ["p0"])
    later = NOW + timedelta(hours=1)
    await emission.emit_content_cards(
        session, shop.id, now=later, rankings={"video": _video_table(rows)}
    )
    cards = await _cards(session, shop.id)
    assert len(cards) == 5 and {c.revision for c in cards} == {1}
    top = next(
        c
        for c in cards
        if c.subject_id
        and json.loads(c.recommendation_payload)["content"]["tiktok_product_id"] == "p0"
    )
    assert json.loads(top.recommendation_payload)["content"]["recoverable_gmv_per_day"] == 20_000


@pytest.mark.asyncio
async def test_a_surfaced_card_expires_after_seven_days_and_returns_seven_days_later(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    tables = {"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])}
    await emission.emit_content_cards(session, shop.id, now=NOW, rankings=tables)
    (card,) = await _cards(session, shop.id)
    card.surfaced_at = NOW - timedelta(days=8)
    assert (
        build_content_card_block(card, json.loads(card.recommendation_payload), None)["status"]
        == "expired"
    )
    await emission.emit_content_cards(session, shop.id, now=NOW, rankings=tables)
    assert card.status == "withdrawn"
    again = await emission.emit_content_cards(
        session, shop.id, now=NOW + timedelta(days=3), rankings=tables
    )
    assert again[0].suppressed_reason == "content_expiry_cooldown"
    back = await emission.emit_content_cards(
        session, shop.id, now=NOW + timedelta(days=8), rankings=tables
    )
    assert back[0].suppressed_reason is None
    assert card.status == "active" and card.surfaced_at is None


@pytest.mark.asyncio
async def test_a_surfaced_card_stays_unless_its_metric_reached_the_target(session):
    shop, _ = await seed_shop(session)
    await _products(session, shop, [("p-video", "MN-015")])
    await emission.emit_content_cards(
        session,
        shop.id,
        now=NOW,
        rankings={"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])},
    )
    (card,) = await _cards(session, shop.id)
    card.surfaced_at = NOW - timedelta(days=1)
    # The product dropped out of the table (no data today): the card stays.
    await emission.emit_content_cards(
        session, shop.id, now=NOW, rankings={"video": _video_table([])}
    )
    assert card.status == "active"
    # Its videos' CTR is at the target now: no longer valid, withdrawn even inside 3 days.
    recovered = {"video": {**_video_table([]), "up": [_row("v1", 0.04, 200, 9_000, ["p-video"])]}}
    await emission.emit_content_cards(session, shop.id, now=NOW, rankings=recovered)
    assert card.status == "withdrawn"


@pytest.mark.asyncio
async def test_a_rejected_content_card_cools_down_its_own_lever_for_seven_days(session):
    shop, _ = await seed_shop(session)
    products = await _products(session, shop, [("p-video", "MN-015")])
    tables = {"video": _video_table([_row("v1", 0.019, 2249, -56_000, ["p-video"])])}
    await emission.emit_content_cards(session, shop.id, now=NOW, rankings=tables)
    (card,) = await _cards(session, shop.id)
    reason = await decision_reasons.record_reason(
        session,
        shop_id=shop.id,
        action="reject",
        reason_code="not_convincing",
        note=None,
        decided_by_user_id=None,
        card=card,
        product_id=products["p-video"].id,
        now=NOW,
    )
    decision_reasons.close_card(card, now=NOW)
    assert reason.lever_code == "video_script" and reason.basis_stage_rate == "ctr"
    later = await emission.emit_content_cards(
        session, shop.id, now=NOW + timedelta(days=2), rankings=tables
    )
    assert later[0].suppressed_reason == decision_reasons.SUPPRESSED_REASON_DECISION_COOLDOWN


# --- the run, end to end ----------------------------------------------------------------------

VIDEO_POSTED = (TODAY - timedelta(days=12)).isoformat()


class FakeAnalytics:
    def __init__(self) -> None:
        self.videos: list[dict[str, Any]] = [
            {
                "id": "old-video",
                "title": "Mặt nạ đất sét: trước và sau",
                "video_post_time": f"{VIDEO_POSTED} 10:00:00",
                "product_impressions": 118_000,
                "product_clicks": 2_242,
                "views": 90_000,
                "sku_orders": 80,
                "products": [{"id": PRODUCT_ID}],
                "hash_tags": ["matnadatset"],
                "creator": {"author_type": "OFFICIAL_ACCOUNTS"},
            }
        ]
        self.sessions: list[dict[str, Any]] = []
        self.live_products: dict[str, dict[str, Any]] = {}

    def list_video_performance_all(self, *, start_date_ge, end_date_lt, sort_field="gmv"):
        return [v for v in _copy.deepcopy(self.videos) if v["video_post_time"][:10] < end_date_lt]

    def list_live_performance_all(self, *, start_date_ge, end_date_lt):
        return _copy.deepcopy(self.sessions)

    def get_live_products_performance(self, *, live_id):
        return _copy.deepcopy(self.live_products.get(live_id, {"products": []}))

    def add_session(self, live_id, day: date, clicks: int, orders: int) -> None:
        start = int(datetime(day.year, day.month, day.day, 5, tzinfo=UTC).timestamp())
        self.sessions.append(
            {
                "id": live_id,
                "title": f"LIVE {day:%d/%m}",
                "start_time": str(start),
                "interaction_performance": {"product_clicks": clicks * 3},
                "sales_performance": {"sku_orders": orders * 3},
            }
        )
        self.live_products[live_id] = {
            "products": [
                {"id": "other", "traffic": {"produt_clicks": 5}, "sales": {"sku_orders": 1}},
                {
                    "id": PRODUCT_ID,
                    "traffic": {"product_impressions": clicks * 10, "produt_clicks": clicks},
                    "sales": {"sku_orders": orders},
                },
            ]
        }


class SeoProducts(FakeProducts):
    def get_seo_words(self, product_ids):
        return {"products": [{"id": PRODUCT_ID, "seo_words": ["kem dưỡng ẩm", "ceramide"]}]}

    def get_suggestions(self, product_ids):
        return {"products": []}


def _resources(analytics, products=None, promo=None):
    return SimpleNamespace(
        products=products or SeoProducts(), analytics=analytics, promotion=promo or FakePromotion()
    )


def _video_script(cta="Bấm giỏ vàng, giá 279k hôm nay", hook="Da khô sau 1 tuần dùng cái này"):
    return json.dumps(
        {
            "hook_options": [hook, "Thử kem 279k này 7 ngày"],
            "scenes": [
                {
                    "t_from": 0,
                    "t_to": 3,
                    "visual": "Cận da",
                    "voiceover": "Da khô?",
                    "on_screen": "7 ngày",
                },
                {
                    "t_from": 3,
                    "t_to": 15,
                    "visual": "Thoa kem",
                    "voiceover": "Thoa mỏng.",
                    "on_screen": "Sáng và tối",
                },
                {
                    "t_from": 15,
                    "t_to": 28,
                    "visual": "Chạm da",
                    "voiceover": "Mềm hơn.",
                    "on_screen": "Trước / sau",
                },
            ],
            "cta": cta,
            "hashtags": ["#kemduongam", "#ceramide"],
            "music_hint": "nhạc nhẹ",
            "product_on_screen_by_s": 2,
        }
    )


def _live_plan(discount=8):
    return json.dumps(
        {
            "opening": "Da khô mùa lạnh thì ở lại 5 phút",
            "show": "Thoa trên mu bàn tay, so sánh trước sau",
            "close": "Chốt trong 10 phút, ghim ngay lúc nói giá",
            "offer": {
                "type": "flash_sale",
                "discount_pct": discount,
                "text": f"Giảm {discount} % trong LIVE",
            },
            "basket_order": [{"position": 1, "sku": "KD-030", "pin_at": "khi nói giá"}],
        }
    )


class FakeDrafter:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls: list[tuple[str, int, Any]] = []

    async def draft(self, *, kind, inputs, version, previous, config):
        self.calls.append((kind, version, previous))
        return outcome_from_text(
            kind,
            self.texts.pop(0),
            inputs,
            version=version,
            model=config.model,
            usage=Usage(1000, 300),
        )


async def _content_run(session, shop, product, *, kind="video", cap=None, first=True):
    if first:
        await session.execute(
            InventoryItem.__table__.insert().values(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id=PRODUCT_ID,
                tiktok_sku_id="sku-1",
                quantity=50,
                seller_sku="KD-030",
                velocity="low",
                update_time=datetime(2026, 10, 1),
            )
        )
    key = "content_video" if kind == "video" else "content_live"
    content = {
        "kind": kind,
        "lever_code": "video_script" if kind == "video" else "live_script",
        "stage_rate": "ctr" if kind == "video" else "ctor",
        "current": 0.019 if kind == "video" else 0.059,
        "target": 0.032 if kind == "video" else 0.075,
        "recoverable_gmv_per_day": 56_000,
        "tiktok_product_id": PRODUCT_ID,
        "product_label": "KD-030",
        "product_title": "Kem dưỡng ẩm ceramide 50ml",
        "discount_cap_pct": cap,
    }
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=key,
        subject_type="product",
        subject_id=str(product.id),
        priority=1,
        severity="warning",
        title="card",
        recommendation_payload=json.dumps({"content": content}),
        status="approved",
        revision=1 if first else 2,
        approved_at=NOW.replace(tzinfo=None),
    )
    session.add(card)
    await session.flush()
    run = WorkflowRunRow(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        action_card_id=card.id,
        workflow_key=key,
        # SQLite's active-run index has no Postgres predicate: a second run needs its own ref.
        subject_ref=str(product.id) if first else str(uuid.uuid4()),
        state=RunState().to_dict(),
        status="queued",
        prompt_version=f"{key}.v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.commit()
    return card, run


async def _leg(session, run_id, res, drafter, sink):
    run = await session.get(WorkflowRunRow, run_id)
    await session.refresh(run)
    product = await session.get(Product, run.product_id)
    wiring = await content_driver.wiring_for_run(session, run, product, drafter=drafter)
    assert wiring is not None
    registry = composition.build_product_tool_registry()
    guard = ConcurrencyGuard(basis_snapshot=run.state.get("basis_snapshots", {}))
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=res,
        write_resources=res,
        product_id=PRODUCT_ID,
        concurrency_guard=guard,
        product_detail=run.state.get("product_detail"),
    )
    runner = WorkflowRunner(
        llm_service=wiring.planner,
        tool_executor=executor,
        event_sink=sink,
        conversation_store=JsonbConversationStore(session),
        registry=registry,
        playbook=playbooks.get_playbook(run.workflow_key),
        concurrency_guard=guard,
    )
    return content_driver.ContentRunner(runner, session=session, wiring=wiring)


async def _reload(session, run_id) -> WorkflowRunRow:
    run = await session.get(WorkflowRunRow, run_id)
    await session.refresh(run)
    return run


def _of(sink, event_type):
    return [e for e in sink.events if e.event_type == event_type]


def test_the_content_playbooks_name_only_registered_read_tools():
    registry = composition.build_product_tool_registry()
    for key in ("content_video", "content_live"):
        playbook = playbooks.get_playbook(key)
        validate_playbook_tools(playbook, registry)
        assert all(
            registry.get(name).classification.value == "read"
            for step in playbook.steps
            for name in step.tools
        )


@pytest.mark.asyncio
async def test_a_video_run_drafts_waits_redrafts_uses_detects_and_measures(session):
    shop, product = await seed_shop(session)
    card, run = await _content_run(session, shop, product)
    analytics, products, sink = FakeAnalytics(), SeoProducts(), InMemoryEventSink()
    res = _resources(analytics, products)
    drafter = FakeDrafter(_video_script(), _video_script(hook="Kem 279k cho da khô mùa lạnh"))

    # Leg 1 (approve): reads, rules, ONE model call, wait for the choice.
    paused = await (await _leg(session, run.id, res, drafter, sink)).run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    assert paused.status == WorkflowRunStatus.WAITING_EXTERNAL
    row = await _reload(session, run.id)
    assert lever_flows.awaiting_of(row) == "content_choice"
    assert [e.payload.tool_name for e in _of(sink, "tool.completed")] == [
        "get_content_performance",
        "get_product_information",
        "get_seo_keywords",
    ]
    summaries = [e.payload.summary for e in _of(sink, "tool.completed")]
    assert summaries[0] == "1 video gắn sản phẩm · CTR 1,9 %"
    texts = [e.payload.text for e in _of(sink, "assistant.text")]
    assert texts[0].startswith("Quy tắc của bạn: Chưa đặt trần giảm giá")
    assert texts[1] == "Đã soạn kịch bản (bản 1) · gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra"
    assert _of(sink, "workflow.status")[-1].payload.phase_narration == "Đang chờ bạn xem kịch bản"
    assert row.input_tokens == 1000 and row.output_tokens == 300
    assert len(drafter.calls) == 1
    detail = run_state.content_detail(row, awaiting="content_choice")
    assert detail["stage"] == "choice" and detail["versions"] == 1 and detail["can_redraft"] is True
    assert detail["script"]["version"] == 1 and len(detail["script"]["blocks"]) == 4
    assert detail["steps"][0]["result"] == "1 video gắn sản phẩm · CTR 1,9 %"
    assert detail["steps"][1]["result"] == "Mô tả, ảnh, từ khoá “kem dưỡng ẩm”, “ceramide”"
    assert [s["at"] is not None for s in detail["steps"]] == [True, True, True, False, False, False]

    # Soạn lại: bản 2, which sees bản 1.
    actions.redraft(row)
    await session.commit()
    await (await _leg(session, run.id, res, drafter, sink)).resume_after_external_wait(run.id)
    await session.commit()
    row = await _reload(session, run.id)
    assert lever_flows.awaiting_of(row) == "content_choice"
    assert drafter.calls[1][1] == 2 and drafter.calls[1][2]["hook_options"][0].startswith("Da khô")
    detail = run_state.content_detail(row, awaiting="content_choice")
    assert detail["versions"] == 2 and detail["can_redraft"] is False
    assert detail["script"]["version"] == 2
    with pytest.raises(actions.ContentActionRefused) as used:
        actions.redraft(row)
    assert used.value.code == "redraft_used"

    # An edit that breaks a rule is refused; a good one is kept as the seller's text.
    with pytest.raises(actions.ContentActionRefused) as bad:
        actions.use_script(row, version=2, edited_blocks={"cta": "Rẻ nhất thị trường, bấm giỏ"})
    assert bad.value.status == 422 and bad.value.field == "cta"
    actions.use_script(row, version=2, edited_blocks={"cta": "Bấm giỏ vàng ngay hôm nay"})
    await session.commit()
    await (await _leg(session, run.id, res, drafter, sink)).resume_after_external_wait(run.id)
    await session.commit()
    row = await _reload(session, run.id)
    assert lever_flows.awaiting_of(row) == "content_publish"
    assert _of(sink, "workflow.status")[-1].payload.phase_narration == "Đang chờ bạn đăng video"
    detail = run_state.content_detail(row, awaiting="content_publish")
    assert detail["wait"]["done_label"] == "Tôi đã đăng video"
    assert detail["wait"]["detect_what"] == "video mới gắn KD-030"
    assert detail["script"]["blocks"][-1]["text"] == "Bấm giỏ vàng ngay hôm nay"
    assert detail["edited"] is True

    # The video is up: "Tôi đã đăng video" → found on TikTok → measuring.
    analytics.videos.append(
        {
            "id": "new-video",
            "title": "7 ngày kem dưỡng",
            "video_post_time": f"{TODAY.isoformat()} 08:00:00",
            "product_impressions": 4_000,
            "product_clicks": 100,
            "products": [{"id": PRODUCT_ID}],
        }
    )
    actions.mark_published(row)
    await session.commit()
    done = await (await _leg(session, run.id, res, drafter, sink)).resume_after_external_wait(
        run.id
    )
    await session.commit()
    assert done.status == WorkflowRunStatus.COMPLETED
    assert done.final_response.startswith("Đã thấy trên TikTok. Juli bắt đầu đo CTR")
    row = await _reload(session, run.id)
    state = run_state.state_of(row)
    assert state["stage"] == "measuring" and state["measurement_start"] == TODAY.isoformat()
    assert state["detected"]["title"]["text"] == "7 ngày kem dưỡng"
    assert _of(sink, "tool.completed")[-1].payload.tool_name == "find_new_content"
    assert _of(sink, "tool.completed")[-1].payload.summary == "Tìm thấy 1 video mới"
    assert run_state.content_detail(row, awaiting=None)["stage"] == "measuring"
    assert len(drafter.calls) == 2
    assert products.edits == [] and products.uploads == []  # nothing written to TikTok

    # The poll's readings: day 7, then day 14 → the final verdict + calibration, once.
    with pytest.raises(lever_flows.NotMeasurable):
        await content_measurement.measure_content_run(
            session, shop.id, await _waiting_copy(session, shop, product)
        )
    report = await content_poll.poll_shop(session, shop.id, res, now=NOW + timedelta(days=8))
    assert report.measured == [run.id]
    body = await content_measurement.measure_content_run(
        session, shop.id, await _reload(session, run.id)
    )
    assert body["stage"] == "day7"
    assert body["rows"][0]["actual"] == pytest.approx(0.025)  # 100 / 4 000
    assert body["rows"][0]["before"] == pytest.approx(2_242 / 118_000)
    assert body["target"]["label"] == "CTR - Video của người bán"
    assert body["content"]["new_videos"] == 1
    await content_poll.poll_shop(session, shop.id, res, now=NOW + timedelta(days=15))
    final = await content_measurement.measure_content_run(
        session, shop.id, await _reload(session, run.id)
    )
    assert final["stage"] == "final"
    # (0.025 − 0.019) / (0.032 − 0.019) ≈ 46 % of the expected GMV → Không đạt.
    assert final["final"]["label"] == "khong_dat" and final["final"]["pct_of_expected"] == 46
    assert final["final"]["calibration"]["lever"] == "video_script"
    again = await content_measurement.measure_content_run(
        session, shop.id, await _reload(session, run.id)
    )
    assert again["final"] == final["final"]
    finals = (await session.execute(select(RunMeasurementFinal))).scalars().all()
    assert len(finals) == 1
    calibration = (await session.execute(select(LeverCalibration))).scalar_one()
    assert calibration.lever == "video_script" and calibration.readings == 1


async def _waiting_copy(session, shop, product):
    """A content run that has not started measuring (for the 409 path)."""
    _card, run = await _content_run(session, shop, product, first=False)
    return run


@pytest.mark.asyncio
async def test_the_poll_auto_detects_a_new_video_and_hands_the_run_back(session):
    shop, product = await seed_shop(session)
    _card, run = await _content_run(session, shop, product)
    analytics = FakeAnalytics()
    res = _resources(analytics)
    sink = InMemoryEventSink()
    await (await _leg(session, run.id, res, FakeDrafter(_video_script()), sink)).run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    row = await _reload(session, run.id)
    actions.use_script(row, version=1, edited_blocks=None)
    await session.commit()
    await (await _leg(session, run.id, res, FakeDrafter(), sink)).resume_after_external_wait(run.id)
    await session.commit()
    assert await content_poll.has_pollable_runs(session, shop.id)
    nothing = await content_poll.poll_shop(session, shop.id, res, now=NOW)
    assert nothing.detected == []
    analytics.videos.append(
        {
            "id": "new",
            "title": "Video mới",
            "video_post_time": f"{TODAY.isoformat()} 09:00:00",
            "product_impressions": 500,
            "product_clicks": 9,
            "products": [{"id": PRODUCT_ID}],
        }
    )
    report = await content_poll.poll_shop(session, shop.id, res, now=NOW)
    await session.commit()
    assert report.detected == [run.id]
    state = run_state.state_of(await _reload(session, run.id))
    assert state["published_by"] == "auto" and state["stage"] == "published"
    done = await (await _leg(session, run.id, res, FakeDrafter(), sink)).resume_after_external_wait(
        run.id
    )
    assert done.status == WorkflowRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_two_failed_drafts_end_the_run_without_showing_anything(session):
    shop, product = await seed_shop(session)
    _card, run = await _content_run(session, shop, product)
    res, sink = _resources(FakeAnalytics()), InMemoryEventSink()
    drafter = FakeDrafter(_video_script(cta="Cam kết 100 % hết mụn"), "not json")
    await (await _leg(session, run.id, res, drafter, sink)).run(run.id, product_ref=PRODUCT_ID)
    await session.commit()
    row = await _reload(session, run.id)
    detail = run_state.content_detail(row, awaiting="content_choice")
    assert detail["script"] is None and detail["can_redraft"] is True
    assert "chưa đạt kiểm tra" in _of(sink, "assistant.text")[-1].payload.text
    actions.redraft(row)
    await session.commit()
    done = await (await _leg(session, run.id, res, drafter, sink)).resume_after_external_wait(
        run.id
    )
    assert done.status == WorkflowRunStatus.COMPLETED
    assert "chưa soạn được kịch bản" in done.final_response
    assert (
        run_state.content_detail(await _reload(session, run.id), awaiting=None)["stage"] == "ended"
    )


@pytest.mark.asyncio
async def test_a_live_run_keeps_the_offer_under_the_cap_then_the_seller_declines(
    engine, session, monkeypatch
):
    from juli_backend.api.routes import demo_run_flows

    monkeypatch.setattr(demo_run_flows, "_enqueue_resume_lever_flow", lambda _r: "task-1")
    shop, product = await seed_shop(session)
    card, run = await _content_run(session, shop, product, kind="live", cap=10)
    analytics = FakeAnalytics()
    analytics.add_session("s-old", TODAY - timedelta(days=5), clicks=100, orders=5)
    res, sink = _resources(analytics), InMemoryEventSink()
    drafter = FakeDrafter(_live_plan(discount=8))
    await (await _leg(session, run.id, res, drafter, sink)).run(run.id, product_ref=PRODUCT_ID)
    await session.commit()
    names = [e.payload.tool_name for e in _of(sink, "tool.completed")]
    assert names == [
        "get_content_performance",
        "get_product_information",
        "find_product_promotions",
    ]
    assert (
        _of(sink, "tool.completed")[0].payload.summary
        == "1 phiên LIVE có bán sản phẩm · CTOR 5,0 %"
    )
    assert _of(sink, "assistant.text")[0].payload.text.startswith(
        "Quy tắc của bạn: Trần giảm giá 10 %"
    )
    row = await _reload(session, run.id)
    detail = run_state.content_detail(row, awaiting="content_choice")
    assert [b["label"] for b in detail["script"]["blocks"]][-1] == "Thứ tự giỏ"
    assert detail["script"]["blocks"][-1]["text"] == "1. KD-030 (ghim khi nói giá)"
    assert detail["title"] == "KD-030 · Kem dưỡng ẩm ceramide 50ml · kịch bản LIVE"

    async with api_client(engine, shop) as client:
        got = await client.get(f"/v1/demo/runs/{run.id}")
        published_early = await client.post(f"/v1/demo/runs/{run.id}/content/published")
        measured = await client.get(f"/v1/demo/runs/{run.id}/measurement")
        declined = await client.post(
            f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "tone"}
        )
        after = await client.post(f"/v1/demo/runs/{run.id}/content/use", json={"version": 1})
    assert got.status_code == 200
    data = got.json()["data"]
    assert data["awaiting"] == "content_choice" and data["content"]["kind"] == "live"
    assert data["decision_id"] == str(card.id)
    assert published_early.status_code == 409
    assert published_early.json()["detail"]["code"] == "not_awaiting_publish"
    assert measured.status_code == 409 and measured.json()["detail"]["code"] == "not_started"
    assert declined.status_code == 200, declined.text
    assert after.status_code == 409
    row = await _reload(session, run.id)
    assert row.status == "cancelled" and row.stop_reason == "cancelled_by_seller"
    assert run_state.content_detail(row, awaiting=None)["stage"] == "declined"
    reason = (await session.execute(select(DecisionReason))).scalar_one()
    assert reason.action == "decline" and reason.lever_code == "live_script"


@pytest.mark.asyncio
async def test_the_seller_step_routes_answer_202_and_422(engine, session, monkeypatch):
    from juli_backend.api.routes import demo_run_flows

    enqueued: list[uuid.UUID] = []
    monkeypatch.setattr(
        demo_run_flows, "_enqueue_resume_lever_flow", lambda r: enqueued.append(r) or "task-1"
    )
    shop, product = await seed_shop(session)
    _card, run = await _content_run(session, shop, product)
    res, sink = _resources(FakeAnalytics()), InMemoryEventSink()
    await (await _leg(session, run.id, res, FakeDrafter(_video_script()), sink)).run(
        run.id, product_ref=PRODUCT_ID
    )
    await session.commit()
    async with api_client(engine, shop) as client:
        bad = await client.post(
            f"/v1/demo/runs/{run.id}/content/use",
            json={"version": 1, "edited_blocks": {"cta": "Giá chỉ 99k"}},
        )
        unknown = await client.post(f"/v1/demo/runs/{run.id}/content/use", json={"version": 2})
        redraft = await client.post(f"/v1/demo/runs/{run.id}/content/redraft")
    assert bad.status_code == 422
    assert (
        bad.json()["detail"]["code"] == "rule_violation" and bad.json()["detail"]["field"] == "cta"
    )
    assert unknown.status_code == 422
    assert redraft.status_code == 202 and redraft.json()["status"] == "drafting"
    assert enqueued == [run.id]
    assert DETAIL["skus"][0]["seller_sku"] == "KD-030"
