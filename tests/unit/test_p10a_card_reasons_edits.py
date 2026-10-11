"""AC-10.1 (fast track P10-A): the recommendation card, seller reasons + 7-day
cooldown, and consent with edits (contract ``fasttrack/contracts/p10-quyet-dinh.md``
§1-§3).

- §1: ``recommendation.card`` on ``GET /v1/demo/decisions`` -- seller SKU + "+N",
  status, main KPI with target = the D22 reference rate, GMV per month, reasons,
  lever and executor, change fields, before/after, GMV method.
- §2: ``POST /v1/demo/decisions/{id}/reject``, ``POST /v1/demo/runs/{id}/decline``
  and the existing revert each require one known ``reason_code`` (422 otherwise),
  store it with note / who / when, and stay tenant-scoped (another shop's id is a
  404 and stores nothing). Card generation skips the (product, lever) for 7 days
  unless the weak stage's rate moved > 20 % relative.
- §3: ``edited_values`` on the confirmations endpoint are validated against the
  shop's rules (422 ``rule_violation``, Vietnamese message, field) and the write
  -- against a fake TikTok product -- uses exactly the edited value, which the
  before/after record keeps; the tool summary says "theo bản bạn sửa".
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.integrations.tiktok.factories import SandboxWriteResources
from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.models import ActionCard, InventoryItem, RunConfirmation
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services import decision_reasons, run_changes, shop_rules
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    emit_optimize_product_cards,
    plan_optimize_product_cards,
)
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent_runs import confirmations
from juli_backend.services.demo_decisions import CardContext, build_card_block
from tests.support.api import authenticate, authenticated_client, build_app, client_for
from tests.support.builders import make_product, make_tenant, make_workflow_run
from tests.unit.test_optimize_product_decision_cards import (
    _optimize_cards,
    _score,
    _seed_shop,
)

ROOT = Path(__file__).resolve().parents[2]


class Enqueued:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, Any]] = []

    def resume(self, run_id: uuid.UUID, *, approved: bool) -> str:
        self.calls.append((run_id, approved))
        return "task-resume"

    def run(self, run_id: uuid.UUID) -> str:
        self.calls.append((run_id, None))
        return "task-run"


@pytest.fixture
def enqueued(monkeypatch) -> Enqueued:
    from juli_backend.api.routes import agent_runs, demo_run_changes

    recorder = Enqueued()
    monkeypatch.setattr(agent_runs, "_enqueue_resume_agent_workflow", recorder.resume)
    monkeypatch.setattr(demo_run_changes, "_enqueue_resume_agent_workflow", recorder.resume)
    monkeypatch.setattr(demo_run_changes, "_enqueue_run_agent_workflow", recorder.run)
    return recorder


async def _reasons(session) -> list[DecisionReason]:
    return list((await session.execute(select(DecisionReason))).scalars().all())


# =========================================================================== §1 the card


@pytest_asyncio.fixture
async def shop_a(session):
    return await _seed_shop(session, "A")


@pytest.mark.asyncio
async def test_the_decisions_list_carries_the_card_block(session, shop_a):
    from juli_backend.models.models import Product, User

    await _score(session, shop_a)
    user = await session.get(User, shop_a.user_id)
    top = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    product = await session.get(Product, uuid.UUID(top.subject_id))
    for sku_id, seller_sku in (("s-2", "SM-013"), ("s-1", "SM-012"), ("s-3", None)):
        session.add(
            InventoryItem(
                shop_id=shop_a.id,
                tiktok_product_id=product.tiktok_product_id,
                tiktok_sku_id=f"{product.tiktok_product_id}-{sku_id}",
                quantity=5,
                seller_sku=seller_sku,
                update_time=datetime(2026, 10, 1),
            )
        )
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop_a) as client:
        resp = await client.get("/v1/demo/decisions")

    assert resp.status_code == 200, resp.text
    items = [i for i in resp.json()["data"] if i["recommendation"].get("diagnosis")]
    assert items
    first = next(i for i in items if i["id"] == str(top.id))["recommendation"]
    card, diagnosis = first["card"], first["diagnosis"]
    assert card["seller_sku"] == "SM-012"
    assert card["seller_sku_more"] == 2
    assert card["product_title"] == product.title
    assert card["workflow_label"] == "Tối ưu sản phẩm"
    assert card["updated_at"].endswith("Z")
    assert card["status"] == "pending"
    basis = diagnosis["recoverable_gmv_basis"]
    assert card["main_kpi"] == {
        "key": basis["stage_rate"],
        "label": "CTR - Thẻ sản phẩm",
        "current": pytest.approx(basis["current_rate"]),
        "target": pytest.approx(basis["reference_rate"]),
        "unit": "ratio",
    }
    assert card["expected_gmv_per_month"] == round(diagnosis["recoverable_gmv_per_day"] * 30)
    assert 0 < len(card["reason_short"].split()) <= 6
    assert diagnosis["trigger"]["sentence"] in card["reason_full"]
    # Title evidence is Juli's own reading here, never presented as TikTok's.
    assert card["tiktok_codes"] == []
    assert "Juli đánh giá: Tiêu đề quá ngắn" in card["reason_full"]
    assert card["lever"] == {"code": "title", "label": "Tiêu đề", "executor": "juli"}
    assert card["change_fields"] == [{"field": "title", "label": "Tiêu đề"}]
    assert card["before_after"] == []
    assert card["gmv_method"].startswith("lượt hiển thị × (CTR mục tiêu − CTR hiện tại)")
    # Additive: the existing fields are unchanged.
    assert first["diagnosis"]["lever"]["code"] == "title"
    assert OPTIMIZE_PRODUCT_WORKFLOW_KEY not in resp.text


def _payload(**diagnosis: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "stage": {"code": "page", "label": "x"},
        "lever": {
            "code": "description",
            "label": "mô tả",
            "action": "Viết lại mô tả",
            "detail": "Viết lại mô tả",
            "evidence": [
                {"code": "DESC_LESS_THAN_FIVE_HUNDRED_CHARS", "source": "tiktok"},
                {"code": "TITLE_LESS_THAN_40_CHARACTERS", "source": "local"},
            ],
        },
        "main_kpi": {"key": "ctor", "label": "CTOR", "value": "5.4 %", "raw": 0.054},
        "trigger": {"code": "shop_median", "gap": 0.31, "sentence": "CTOR thấp hơn 31 %"},
        "recoverable_gmv_per_day": 70000.0,
        "recoverable_gmv_basis": {
            "label": "x",
            "stage_rate": "ctor",
            "current_rate": 0.054,
            "reference_rate": 0.059,
            "reference": "shop_median",
            "volume_per_day": 300.0,
            "aov": 200000.0,
            "window_days": 30,
        },
        "product_title": "Son môi số 12 màu đỏ cam thời thượng",
    }
    base.update(diagnosis)
    return {"diagnosis": base}


def _card(status: str = "active", computed_days_ago: int = 1) -> ActionCard:
    return ActionCard(
        id=uuid.uuid4(),
        status=status,
        computed_at=datetime.now(UTC) - timedelta(days=computed_days_ago),
        subject_type="product",
        subject_id=str(uuid.uuid4()),
    )


def test_card_block_fields_follow_the_contract():
    block = build_card_block(_card(), _payload(), None)
    assert block is not None
    assert block["main_kpi"] == {
        "key": "ctor",
        "label": "CTOR - Thẻ sản phẩm",
        "current": 0.054,
        "target": 0.059,
        "unit": "ratio",
    }
    assert block["expected_gmv_per_month"] == 2_100_000
    assert block["tiktok_codes"] == ["Mô tả quá ngắn"]
    assert "TikTok chẩn đoán: Mô tả quá ngắn." in block["reason_full"]
    assert "5,4 %" in block["reason_full"] and "5,9 %" in block["reason_full"]
    assert block["reason_short"] == "Khách xem nhưng ít đặt hàng"
    assert block["lever"] == {"code": "description", "label": "Mô tả", "executor": "juli"}
    assert block["gmv_method"] == (
        "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, "
        "ước tính theo quy tắc"
    )
    assert block["seller_sku"] is None and block["seller_sku_more"] == 0
    # A legacy card (no diagnosis) gets no block.
    assert build_card_block(_card(), {"workflow_name": "x"}, None) is None


@pytest.mark.parametrize(
    ("lever", "label", "executor", "field"),
    [
        ("cover_image", "Ảnh bìa", "juli_with_photo", "main_images"),
        ("product_discount", "Giảm giá sản phẩm", "seller_center", "product_discount"),
        ("flash_sale", "Flash sale", "seller_center", "flash_sale"),
        ("shipping_discount", "Giảm phí vận chuyển", "seller_center", "shipping_discount"),
        ("buy_more_save_more", "Mua nhiều giảm nhiều", "seller_center", "buy_more_save_more"),
    ],
)
def test_every_lever_has_its_label_and_executor(lever, label, executor, field):
    payload = _payload(lever={"code": lever, "label": "x", "action": "x", "evidence": []})
    block = build_card_block(_card(), payload, None)
    assert block["lever"] == {"code": lever, "label": label, "executor": executor}
    assert block["change_fields"] == [{"field": field, "label": label}]


def test_card_status_mapping():
    def status(card, context=None, **diagnosis):
        return build_card_block(card, _payload(**diagnosis), context)["status"]

    assert status(_card("dismissed")) == "rejected"
    assert status(_card("withdrawn")) == "expired"
    assert status(_card("active", computed_days_ago=15)) == "expired"
    product = SimpleNamespace(title="Tên đã đổi bên ngoài Juli", name="x", tiktok_product_id="p")
    assert status(_card(), CardContext(product=product)) == "expired"
    assert status(_card("approved")) == "running"
    run = SimpleNamespace(id=uuid.uuid4(), status="completed")
    writes = [
        SimpleNamespace(field="description", before_value="<p>cũ</p>", after_value="<p>mới</p>")
    ]
    applied = build_card_block(
        _card("approved"), _payload(), CardContext(latest_run=run, writes=writes)
    )
    assert applied["status"] == "applied"
    assert applied["before_after"] == [
        {"field": "description", "label": "Mô tả", "before": "<p>cũ</p>", "after": "<p>mới</p>"}
    ]
    assert status(_card()) == "pending"


# =========================================================================== §2 reasons


async def _surfaced_card(session, shop, product, *, lever: str = "title") -> ActionCard:
    payload = {
        "workflow_key": OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        "diagnosis": {
            "lever": {"code": lever},
            "stage": {"code": "card"},
            "recoverable_gmv_basis": {"stage_rate": "ctr", "current_rate": 0.02},
        },
    }
    card = ActionCard(
        shop_id=shop.id,
        workflow_key=OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        subject_type="product",
        subject_id=str(product.id),
        priority=1,
        severity="warning",
        title="Viết lại tiêu đề",
        description="x",
        recommendation_payload=json.dumps(payload),
        status="active",
        surfaced_at=datetime.now(UTC),
        computed_at=datetime.now(UTC),
    )
    session.add(card)
    await session.flush()
    return card


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{}, {"reason_code": "nope"}, {"reason_code": "other", "note": "x" * 301}, {"note": "x"}],
)
async def test_reject_requires_one_known_reason(session, body):
    user, shop = await make_tenant(session)
    card = await _surfaced_card(session, shop, await make_product(session, shop))
    await session.commit()
    async with authenticated_client(session, user=user, shop=shop) as client:
        resp = await client.post(f"/v1/demo/decisions/{card.id}/reject", json=body)
    assert resp.status_code == 422, resp.text
    assert await _reasons(session) == []
    assert card.status == "active"


@pytest.mark.asyncio
async def test_reject_stores_the_reason_and_takes_the_card_off_the_desk(session):
    user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _surfaced_card(session, shop, product)
    await session.commit()

    async with authenticated_client(session, user=user, shop=shop) as client:
        resp = await client.post(
            f"/v1/demo/decisions/{card.id}/reject",
            json={"reason_code": "editing_myself", "note": "  Tôi tự sửa tuần này  "},
        )
        listed = await client.get("/v1/demo/decisions")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rejected"
    (row,) = await _reasons(session)
    assert (row.action, row.reason_code, row.note) == (
        "reject",
        "editing_myself",
        "Tôi tự sửa tuần này",
    )
    assert (row.shop_id, row.action_card_id, row.product_id) == (shop.id, card.id, product.id)
    assert (row.lever_code, row.basis_stage_rate, row.basis_rate) == ("title", "ctr", 0.02)
    assert row.decided_by_user_id == user.id
    assert row.cooldown_until - row.decided_at == timedelta(days=7)
    assert body["cooldown_until"].startswith(row.cooldown_until.isoformat()[:19])
    await session.refresh(card)
    assert card.status == "dismissed" and card.dismissed_at is not None
    assert all(item["id"] != str(card.id) for item in listed.json()["data"])


@pytest.mark.asyncio
async def test_reject_is_tenant_scoped(session):
    _user_a, shop_a = await make_tenant(session)
    user_b, shop_b = await make_tenant(session)
    card_a = await _surfaced_card(session, shop_a, await make_product(session, shop_a))
    await session.commit()
    async with authenticated_client(session, user=user_b, shop=shop_b) as client:
        resp = await client.post(
            f"/v1/demo/decisions/{card_a.id}/reject", json={"reason_code": "other"}
        )
    assert resp.status_code == 404
    assert await _reasons(session) == []
    await session.refresh(card_a)
    assert card_a.status == "active"


async def _waiting_run(session, shop, *, with_card: bool = True):
    product = await make_product(session, shop)
    card = await _surfaced_card(session, shop, product, lever="description") if with_card else None
    if card is not None:
        card.status = "approved"
    arguments = {"description": "<p>Mô tả mới Juli viết cho sản phẩm</p>"}
    run = await make_workflow_run(
        session,
        shop,
        product=product,
        status="waiting_approval",
        action_card_id=card.id if card else None,
        state={
            "pending_confirmation": {
                "call_id": "call-1",
                "tool_name": "update_product_listing",
                "arguments": arguments,
            },
            "product_detail": {"title": "Son môi Fujiwa số 12", "description": "<p>cũ</p>"},
        },
    )
    session.add(
        RunConfirmation(
            workflow_run_id=run.id,
            tool_call_id="call-1",
            options=[
                {
                    "option_id": "1",
                    "proposed_change": arguments,
                    "rationale": "x",
                    "params_sha": compute_params_sha(arguments),
                }
            ],
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )
    )
    await session.commit()
    return run, card, product


@pytest.mark.asyncio
async def test_decline_needs_a_reason_then_ends_the_run_without_writing(session, enqueued):
    user, shop = await make_tenant(session)
    run, card, product = await _waiting_run(session, shop)

    async with authenticated_client(session, user=user, shop=shop) as client:
        missing = await client.post(f"/v1/demo/runs/{run.id}/decline", json={})
        unknown = await client.post(
            f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "brand_mismatch"}
        )
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "tone", "note": "Hơi cứng"}
        )
        again = await client.post(f"/v1/demo/runs/{run.id}/decline", json={"reason_code": "tone"})

    assert (missing.status_code, unknown.status_code) == (422, 422)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "declined"
    # The ordinary decline: the row flips, the resume task ends the run (approved=False).
    confirmation = (await session.execute(select(RunConfirmation))).scalar_one()
    assert confirmation.status == "declined"
    assert enqueued.calls == [(run.id, False)]
    (row,) = await _reasons(session)
    assert (row.action, row.reason_code, row.note) == ("decline", "tone", "Hơi cứng")
    assert (row.workflow_run_id, row.product_id, row.lever_code) == (
        run.id,
        product.id,
        "description",
    )
    await session.refresh(card)
    assert card.status == "dismissed"
    # A second decline finds nothing pending (the worker has not ended the run yet).
    assert again.status_code == 404
    assert again.json()["detail"]["error_code"] == "confirmation_not_found"
    assert len(await _reasons(session)) == 1


@pytest.mark.asyncio
async def test_decline_is_tenant_scoped(session, enqueued):
    _user_a, shop_a = await make_tenant(session)
    user_b, shop_b = await make_tenant(session)
    run_a, _card, _product = await _waiting_run(session, shop_a)
    async with authenticated_client(session, user=user_b, shop=shop_b) as client:
        resp = await client.post(f"/v1/demo/runs/{run_a.id}/decline", json={"reason_code": "tone"})
    assert resp.status_code == 404
    assert await _reasons(session) == []
    assert enqueued.calls == []


async def _finished_run(session, shop):
    product = await make_product(session, shop, tiktok_product_id=f"p-{uuid.uuid4().hex[:8]}")
    card = await _surfaced_card(session, shop, product)
    card.status = "approved"
    run = await make_workflow_run(
        session,
        shop,
        product=product,
        status="completed",
        action_card_id=card.id,
        subject_ref=str(product.id),
    )
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=run.id,
            tool_call_id="c0",
            tool_name="update_product_listing",
            tiktok_product_id=product.tiktok_product_id,
            field="title",
            before_value="Tên cũ",
            after_value="Juli viết",
            after_source="read_back",
        )
    )
    await session.commit()
    return run, card, product


def _live_title(title: str):
    async def _read(session, shop_id, tiktok_product_id):
        return {"title": title, "description": "", "main_images": []}

    return _read


@pytest_asyncio.fixture
async def partial_active_run_index(engine):
    """SQLite builds ``uq_workflow_runs_active_shop_product`` without its Postgres
    predicate; recreate it partial, as Postgres has it (see test_run_changes_revert)."""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("DROP INDEX IF EXISTS uq_workflow_runs_active_shop_product"))
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_workflow_runs_active_shop_product ON workflow_runs "
                "(shop_id, workflow_key, subject_type, subject_ref) WHERE status IN "
                "('queued', 'running', 'waiting_approval', 'waiting_external')"
            )
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("partial_active_run_index")
async def test_revert_requires_a_reason_and_stores_it(session, enqueued):
    from juli_backend.api.routes import demo_run_changes

    user, shop = await make_tenant(session)
    run, card, product = await _finished_run(session, shop)
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    app.dependency_overrides[demo_run_changes.get_live_product_reader] = lambda: _live_title(
        "Juli viết"
    )
    async with client_for(app) as client:
        missing = await client.post(f"/v1/demo/runs/{run.id}/revert")
        unknown = await client.post(f"/v1/demo/runs/{run.id}/revert", json={"reason_code": "tone"})
        resp = await client.post(
            f"/v1/demo/runs/{run.id}/revert", json={"reason_code": "metrics_dropped"}
        )

    assert (missing.status_code, unknown.status_code) == (422, 422)
    assert resp.status_code == 202, resp.text
    (row,) = await _reasons(session)
    assert (row.action, row.reason_code, row.note) == ("revert", "metrics_dropped", None)
    assert (row.workflow_run_id, row.product_id, row.action_card_id) == (
        run.id,
        product.id,
        card.id,
    )
    assert row.decided_by_user_id == user.id
    await session.refresh(card)
    assert card.status == "dismissed"


@pytest.mark.asyncio
async def test_revert_is_tenant_scoped(session, enqueued):
    _user_a, shop_a = await make_tenant(session)
    user_b, shop_b = await make_tenant(session)
    run_a, _card, _product = await _finished_run(session, shop_a)
    async with authenticated_client(session, user=user_b, shop=shop_b) as client:
        resp = await client.post(f"/v1/demo/runs/{run_a.id}/revert", json={"reason_code": "other"})
    assert resp.status_code == 404
    assert await _reasons(session) == []
    assert enqueued.calls == []


# =========================================================================== §2 cooldown


def _emission_config() -> DecisionEmissionConfig:
    return DecisionEmissionConfig(cooldown_days=7)


async def _emit(session, shop, at: datetime):
    op = await plan_optimize_product_cards(session, shop.id, now=at)
    decisions = await emit_optimize_product_cards(
        session, shop.id, op, computed_at=at, emission_config=_emission_config()
    )
    await session.commit()
    return decisions


@pytest.mark.asyncio
async def test_cooldown_suppresses_re_proposal_and_lifts_after_seven_days(session, shop_a):
    from juli_backend.models.models import User

    await _score(session, shop_a)
    top = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    user = await session.get(User, shop_a.user_id)
    async with authenticated_client(session, user=user, shop=shop_a) as client:
        resp = await client.post(
            f"/v1/demo/decisions/{top.id}/reject", json={"reason_code": "not_convincing"}
        )
    assert resp.status_code == 200, resp.text
    reason = (await _reasons(session))[0]

    def for_product(decisions):
        return [d for d in decisions if d.subject_id == top.subject_id]

    # Same data, inside 7 days: the (product, lever) is not proposed again.
    (inside,) = for_product(await _emit(session, shop_a, reason.decided_at.replace(tzinfo=UTC)))
    assert inside.suppressed_reason == "decision_cooldown"
    assert inside.card.id == top.id and inside.card.status == "dismissed"
    later = reason.decided_at.replace(tzinfo=UTC) + timedelta(days=6, hours=23)
    (still,) = for_product(await _emit(session, shop_a, later))
    assert still.suppressed_reason == "decision_cooldown"
    actives = [
        c for c in await _optimize_cards(session, shop_a.id) if c.subject_id == top.subject_id
    ]
    assert actives == []

    # After 7 days the same proposal comes back as a new revision.
    after = reason.decided_at.replace(tzinfo=UTC) + timedelta(days=7, minutes=1)
    (back,) = for_product(await _emit(session, shop_a, after))
    assert back.suppressed_reason is None
    assert back.card.id != top.id and back.card.status == "active"
    assert back.card.supersedes_card_id == top.id


@pytest.mark.asyncio
async def test_no_data_change_lifts_the_cooldown_early(session, shop_a):
    """D24.21 (1): strictly 7 days -- even a > 20 % move keeps the cooldown."""
    from juli_backend.models.models import User

    await _score(session, shop_a)
    top = next(c for c in await _optimize_cards(session, shop_a.id) if c.priority == 1)
    user = await session.get(User, shop_a.user_id)
    async with authenticated_client(session, user=user, shop=shop_a) as client:
        await client.post(f"/v1/demo/decisions/{top.id}/reject", json={"reason_code": "other"})
    reason = (await _reasons(session))[0]
    at = reason.decided_at.replace(tzinfo=UTC) + timedelta(days=1)

    # The CTR the card was proposed on was 0.02; record it as if it had been
    # 0.026 (current is 23 % lower -- the old "clear change") -> still cooling.
    reason.basis_rate = 0.026
    await session.commit()
    decisions = await _emit(session, shop_a, at)
    (kept,) = [d for d in decisions if d.subject_id == top.subject_id]
    assert kept.suppressed_reason == "decision_cooldown"
    assert not hasattr(decision_reasons, "clearly_changed")


@pytest.mark.asyncio
async def test_cooldowns_are_per_shop(session):
    user_a, shop_a = await make_tenant(session)
    _user_b, shop_b = await make_tenant(session)
    card = await _surfaced_card(session, shop_a, await make_product(session, shop_a))
    await decision_reasons.record_reason(
        session,
        shop_id=shop_a.id,
        action="reject",
        reason_code="other",
        note=None,
        decided_by_user_id=user_a.id,
        card=card,
        product_id=decision_reasons.product_id_of(card),
    )
    await session.commit()
    assert len(await decision_reasons.active_cooldowns(session, shop_a.id)) == 1
    assert await decision_reasons.active_cooldowns(session, shop_b.id) == {}


# =========================================================================== §3 edits


async def _post_confirmation(session, user, shop, run, body):
    async with authenticated_client(session, user=user, shop=shop) as client:
        return await client.post(f"/v1/demo/runs/{run.id}/confirmations/call-1", json=body)


@pytest.mark.asyncio
async def test_an_edited_consent_binds_the_run_to_the_edited_values(session, enqueued):
    user, shop = await make_tenant(session)
    run, _card, _product = await _waiting_run(session, shop)
    edited = "<p>Mô tả bạn sửa: son lì, lâu trôi, màu đỏ cam</p>"

    resp = await _post_confirmation(
        session,
        user,
        shop,
        run,
        {"decision": "approve", "option_id": "1", "edited_values": {"description": edited}},
    )

    assert resp.status_code == 202, resp.text
    await session.refresh(run)
    pending = run.state["pending_confirmation"]
    assert pending["arguments"] == {"description": edited}
    assert pending["params_sha"] == compute_params_sha({"description": edited})
    assert pending["edited_fields"] == ["description"]
    assert enqueued.calls == [(run.id, True)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("edited_values", "field", "fragment"),
    [
        ({"description": "   "}, "description", "không được để trống"),
        ({"description": "x" * 10_001}, "description", "tối đa 10.000 ký tự"),
        ({"title": "Son môi Fujiwa số 12 chính hãng"}, "title", "không đề xuất sửa tiêu đề"),
        ({"description": "<p>Son môi số 12 không còn tên hãng</p>"}, "description", '"Fujiwa"'),
    ],
)
async def test_an_edit_that_breaks_a_rule_is_refused_with_a_vietnamese_reason(
    session, enqueued, edited_values, field, fragment
):
    user, shop = await make_tenant(session)
    run, _card, _product = await _waiting_run(session, shop)
    run.state = {
        **run.state,
        "product_detail": {"description": "<p>Son môi Fujiwa số 12</p>"},
    }
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key="protected_terms",
        scope_ref=None,
        value=["Fujiwa"],
        set_by="seller",
        set_by_user_id=user.id,
    )
    await session.commit()

    resp = await _post_confirmation(
        session,
        user,
        shop,
        run,
        {"decision": "approve", "option_id": "1", "edited_values": edited_values},
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "rule_violation"
    assert detail["field"] == field
    assert fragment in detail["message"]
    confirmation = (await session.execute(select(RunConfirmation))).scalar_one()
    assert confirmation.status == "pending"
    assert enqueued.calls == []


def test_title_length_limits_are_tiktoks():
    proposed = {"title": "Một tiêu đề Juli đề xuất đủ dài"}
    with pytest.raises(shop_rules.ListingEditViolation, match="từ 25 đến 255"):
        shop_rules.validate_listing_edits(
            {"title": "Quá ngắn"}, proposed=proposed, current=None, protected_terms=[]
        )
    with pytest.raises(shop_rules.ListingEditViolation, match="từ 25 đến 255"):
        shop_rules.validate_listing_edits(
            {"title": "x" * 256}, proposed=proposed, current=None, protected_terms=[]
        )
    ok = "Tiêu đề người bán sửa, đủ hai mươi lăm ký tự"
    assert shop_rules.validate_listing_edits(
        {"title": ok}, proposed=proposed, current=None, protected_terms=[]
    ) == {"title": ok}
    # Unchanged from the proposal: nothing to bind.
    assert (
        shop_rules.validate_listing_edits(
            proposed, proposed=proposed, current=None, protected_terms=[]
        )
        == {}
    )


PRODUCT_ID = "1736363193934775939"
DETAIL: dict[str, Any] = {
    "id": PRODUCT_ID,
    "title": "Nồi lẩu điện Juli viết cho bạn",
    "description": "<p>mô tả</p>",
    "status": "ACTIVATE",
    "category_chains": [{"id": "601693", "is_leaf": True, "local_name": "Nồi điện"}],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "main_images": [{"uri": "tos-1", "width": 800, "height": 800}],
    "skus": [{"id": "sku-1", "price": {"currency": "VND", "tax_exclusive_price": "599000"}}],
}


class FakeProducts:
    def __init__(self) -> None:
        self.detail = copy.deepcopy(DETAIL)
        self.edits: list[dict[str, Any]] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.detail)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edits.append(copy.deepcopy(body))
        for key in ("title", "description", "main_images"):
            self.detail[key] = copy.deepcopy(body[key])
        return {}


class ListRecorder:
    def __init__(self) -> None:
        self.writes: list[Any] = []

    def record(self, *, tool_name, tool_call_id, tiktok_product_id, writes) -> None:
        self.writes.extend(writes)


class InMemoryStore:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states.setdefault(workflow_run_id, RunState())
        state.prompt_version = state.prompt_version or "optimize_product.v3"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id, state, **kwargs) -> None:
        self.states[workflow_run_id] = state


def _runner(products, store, sink, recorder, plan, guard=None, detail=None) -> WorkflowRunner:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    resources = cast(SandboxWriteResources, SimpleNamespace(products=products))
    guard = guard or ConcurrencyGuard()
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=resources,
        write_resources=resources,
        product_id=PRODUCT_ID,
        concurrency_guard=guard,
        write_value_recorder=recorder,
        revert_expected=plan.expected,
        product_detail=detail or guard.get_product_detail(),
    )
    return WorkflowRunner(
        llm_service=run_changes.RevertPlanner(plan),
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=run_changes.REVERT_LISTING_PLAYBOOK,
        concurrency_guard=guard,
    )


@pytest.mark.asyncio
async def test_the_write_uses_the_edited_value_and_says_so(session):
    """Real runner + executor against a fake TikTok product: pause at consent,
    bind the seller's edit through the confirmation service, resume."""
    _user, shop = await make_tenant(session)
    plan = run_changes.RevertPlan(
        reverts_run_id=str(uuid.uuid4()),
        restore={"title": "Nồi lẩu điện mini 1.5L"},
        expected={"title": DETAIL["title"]},
    )
    products, store, sink, recorder = (
        FakeProducts(),
        InMemoryStore(),
        InMemoryEventSink(),
        ListRecorder(),
    )
    run_id = uuid.uuid4()
    paused = await _runner(products, store, sink, ListRecorder(), plan).run(
        run_id, product_ref=PRODUCT_ID
    )
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    assert products.edits == []

    # The confirmation endpoint's edit step, on the run's real state blob.
    row = await make_workflow_run(
        session, shop, status="waiting_approval", state=store.states[run_id].to_dict()
    )
    edited = "Nồi lẩu điện mini 1.5L chính hãng, bản bạn sửa"
    await confirmations._apply_seller_edits(session, row, {"title": edited})
    store.states[run_id] = RunState.from_dict(row.state)

    # The resume leg: a fresh runner, as in a fresh worker process.
    state = store.states[run_id]
    guard = ConcurrencyGuard(basis_snapshot=state.basis_snapshots)
    resumed = _runner(products, store, sink, recorder, plan, guard, state.product_detail)
    done = await resumed.resume(run_id, approved=True)

    assert done.status == WorkflowRunStatus.COMPLETED, done
    assert products.edits[-1]["title"] == edited
    assert [(w.field, w.after) for w in recorder.writes] == [("title", edited)]
    completed = [
        e.payload
        for e in sink.events
        if e.event_type == "tool.completed" and e.payload.tool_name == "update_product_listing"
    ]
    assert completed[-1].summary == "Hoàn tất theo bản bạn sửa"


# =========================================================================== migration


def test_migration_079_is_short_chained_and_tenant_scoped():
    text = (
        ROOT / "backend/src/juli_backend/database/migrations/versions/079_decision_reasons.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "079_decision_reasons"' in text
    assert len("079_decision_reasons") <= 32
    assert 'down_revision: str | None = "078_rules_and_write_values"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "decision_reasons")] == "tenant_direct"
    migrations = ROOT / "backend/src/juli_backend/database/migrations"
    deferred = (migrations / "deferred/074_users_placeholder_phone_cleanup.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision: str | None = "084_onboarding_speed"' in deferred
