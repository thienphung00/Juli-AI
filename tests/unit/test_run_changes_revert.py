"""AC-8.3 (fast track P8-C): before/after on every write, and the "Hoàn tác" run.

Covers, against a fake TikTok product (no network):

- the executor records each changed field's value read right before the write
  and right after it (or the value sent, when the read-back still shows the old
  one), through the recorder, and the SQL recorder is idempotent;
- a revert run driven by the real ``WorkflowRunner`` with the revert playbook
  and planner reads the product, pauses for the same CONFIRM consent, restores
  the before-values on approval, and emits the ordinary SSE event types;
- a revert refuses -- writing nothing -- when the live field no longer holds
  Juli's after-value (S-FR-8), both at the API-side check and at the write;
- ``start_revert`` refuses honestly (unfinished, nothing written, price, a
  revert of a revert, already reverted) and otherwise creates the run;
- the routes: 202 + new run id, 409 with a Vietnamese message, 404 for another
  shop's run, the changes read.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from juli_backend.integrations.tiktok.factories import SandboxWriteResources
from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue
from juli_backend.orm_base import Base
from juli_backend.services import run_changes
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.conversation_store import PendingConfirmationWrite
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.runner.write_capture import (
    AFTER_SOURCE_INTENDED,
    AFTER_SOURCE_READ_BACK,
    FieldWrite,
)
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    register_product_write_tools,
)

PRODUCT_ID = "1736363193934775939"

DETAIL: dict[str, Any] = {
    "id": PRODUCT_ID,
    "title": "Nồi lẩu điện mini 1.5L",
    "description": "<p>mô tả cũ</p>",
    "status": "ACTIVATE",
    "category_chains": [{"id": "601693", "is_leaf": True, "local_name": "Nồi điện"}],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "main_images": [
        {"uri": "tos-old-1", "width": 800, "height": 800},
        {"uri": "tos-old-2", "width": 800, "height": 800},
    ],
    "skus": [{"id": "sku-1", "price": {"currency": "VND", "tax_exclusive_price": "599000"}}],
}


class FakeProducts:
    """A TikTok product whose edits take effect (or not, under review)."""

    def __init__(self, detail: dict[str, Any], *, apply_edits: bool = True) -> None:
        self.detail = copy.deepcopy(detail)
        self.apply_edits = apply_edits
        self.edits: list[dict[str, Any]] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        return copy.deepcopy(self.detail)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edits.append(copy.deepcopy(body))
        if self.apply_edits:
            for key in ("title", "description", "main_images"):
                self.detail[key] = copy.deepcopy(body[key])
        return {}


def _resources(products: FakeProducts) -> SandboxWriteResources:
    """The executor only ever touches `.products` on its resource bundles."""
    return cast(SandboxWriteResources, SimpleNamespace(products=products))


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class ListRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, *, tool_name, tool_call_id, tiktok_product_id, writes) -> None:
        self.calls.append(
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tiktok_product_id": tiktok_product_id,
                "writes": list(writes),
            }
        )


def _executor(products: FakeProducts, recorder: Any, **kwargs: Any) -> ProductToolExecutor:
    resources = _resources(products)
    return ProductToolExecutor(
        registry=_registry(),
        read_resources=resources,
        write_resources=resources,
        product_id=PRODUCT_ID,
        product_detail=copy.deepcopy(products.detail),
        write_value_recorder=recorder,
        **kwargs,
    )


# --- before/after capture ---------------------------------------------------------


def test_a_listing_write_records_each_changed_field_before_and_after():
    products = FakeProducts(DETAIL)
    recorder = ListRecorder()
    executor = _executor(products, recorder)

    executor.execute(
        tool_name="update_product_listing",
        params=UpdateProductListingInput(title="Nồi lẩu điện mini 1.5L chống dính"),
        tool_call_id="call-1",
    )

    assert len(products.edits) == 1
    [call] = recorder.calls
    assert call["tool_call_id"] == "call-1"
    assert call["tiktok_product_id"] == PRODUCT_ID
    assert call["writes"] == [
        FieldWrite(
            "title",
            "Nồi lẩu điện mini 1.5L",
            "Nồi lẩu điện mini 1.5L chống dính",
            AFTER_SOURCE_READ_BACK,
        )
    ], "description and images were sent unchanged, so they are not recorded"


def test_a_write_under_review_records_the_value_juli_sent():
    """TikTok may still show the old title right after the edit (review)."""
    products = FakeProducts(DETAIL, apply_edits=False)
    recorder = ListRecorder()
    _executor(products, recorder).execute(
        tool_name="update_product_listing",
        params=UpdateProductListingInput(description="<p>mô tả mới</p>"),
        tool_call_id="call-1",
    )

    [call] = recorder.calls
    assert call["writes"] == [
        FieldWrite("description", "<p>mô tả cũ</p>", "<p>mô tả mới</p>", AFTER_SOURCE_INTENDED)
    ]


def test_reads_are_never_recorded():
    products = FakeProducts(DETAIL)
    recorder = ListRecorder()
    executor = _executor(products, recorder)
    spec = _registry().get("get_product_information")
    executor.execute(
        tool_name="get_product_information", params=spec.input_model(), tool_call_id="r"
    )
    assert recorder.calls == []


def _sync_session() -> Session:
    engine = create_engine(
        "sqlite://",
        execution_options={
            "schema_translate_map": {"ops": None, "bronze": None, "gold": None, "silver": None}
        },
    )
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def test_the_sql_recorder_writes_one_row_per_field_and_is_idempotent():
    session = _sync_session()
    user = User(id=uuid.uuid4(), phone="+84910000001")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="s", is_active=True)
    run = WorkflowRunRow(
        id=uuid.uuid4(),
        shop_id=shop.id,
        subject_ref="p-1",
        state={},
        status="running",
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, run])
    session.commit()
    recorder = run_changes.SqlWriteValueRecorder(session, shop_id=shop.id, workflow_run_id=run.id)
    writes = [
        FieldWrite("title", "old", "new", AFTER_SOURCE_READ_BACK),
        FieldWrite("main_images", ["a"], ["b"], AFTER_SOURCE_INTENDED),
    ]

    recorder.record(
        tool_name="update_product_listing",
        tool_call_id="c1",
        tiktok_product_id=PRODUCT_ID,
        writes=writes,
    )
    recorder.record(  # a redelivered task replays the same call
        tool_name="update_product_listing",
        tool_call_id="c1",
        tiktok_product_id=PRODUCT_ID,
        writes=writes,
    )

    rows = session.execute(select(RunWriteValue).order_by(RunWriteValue.field)).scalars().all()
    assert [(r.field, r.before_value, r.after_value, r.after_source) for r in rows] == [
        ("main_images", ["a"], ["b"], "intended"),
        ("title", "old", "new", "read_back"),
    ]
    assert {r.shop_id for r in rows} == {shop.id}


# --- the revert run, end to end through the real runner ------------------------------


class InMemoryStore:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}
        self.status: dict[uuid.UUID, WorkflowRunStatus] = {}
        self.stop_reason: dict[uuid.UUID, StopReason | None] = {}
        self.confirmations: list[PendingConfirmationWrite] = []

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states.setdefault(workflow_run_id, RunState())
        state.prompt_version = state.prompt_version or "optimize_product.v3"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id, state, **kwargs) -> None:
        self.states[workflow_run_id] = state
        if kwargs.get("status") is not None:
            self.status[workflow_run_id] = kwargs["status"]
            self.stop_reason[workflow_run_id] = kwargs.get("stop_reason")
        if kwargs.get("pending_confirmation") is not None:
            self.confirmations.append(kwargs["pending_confirmation"])


#: What Juli's original run wrote: the title and the photos.
PLAN = run_changes.RevertPlan(
    reverts_run_id=str(uuid.uuid4()),
    restore={"title": "Nồi lẩu điện mini 1.5L", "main_images": ["tos-old-1", "tos-old-2"]},
    expected={"title": "Nồi lẩu điện Juli viết", "main_images": ["tos-new"]},
)


def _after_juli_write() -> dict[str, Any]:
    detail = copy.deepcopy(DETAIL)
    detail["title"] = "Nồi lẩu điện Juli viết"
    detail["main_images"] = [{"uri": "tos-new", "width": 800, "height": 800}]
    return detail


def _revert_runner(products: FakeProducts, store: InMemoryStore, sink, recorder, guard):
    resources = _resources(products)
    registry = _registry()
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=resources,
        write_resources=resources,
        product_id=PRODUCT_ID,
        concurrency_guard=guard,
        write_value_recorder=recorder,
        restore_main_image_uris=PLAN.restore_main_image_uris,
        revert_expected=PLAN.expected,
        product_detail=guard.get_product_detail(),
    )
    return WorkflowRunner(
        llm_service=run_changes.RevertPlanner(PLAN),
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=run_changes.REVERT_LISTING_PLAYBOOK,
        concurrency_guard=guard,
    )


async def _run_to_confirmation(products, store, sink):
    run_id = uuid.uuid4()
    first = _revert_runner(products, store, sink, ListRecorder(), ConcurrencyGuard())
    result = await first.run(run_id, product_ref=PRODUCT_ID)
    return run_id, result


@pytest.mark.asyncio
async def test_a_revert_run_pauses_for_consent_then_restores_the_before_values():
    products = FakeProducts(_after_juli_write())
    store, sink = InMemoryStore(), InMemoryEventSink()

    run_id, paused = await _run_to_confirmation(products, store, sink)

    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    assert products.edits == [], "nothing is written before the seller confirms"
    approval = [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert len(approval) == 1
    assert approval[0].payload.tool_name == "update_product_listing"
    assert approval[0].payload.proposed_change == {
        "title": "Nồi lẩu điện mini 1.5L",
        "restore_previous_images": True,
    }
    assert len(store.confirmations) == 1

    # The resume leg: a fresh runner, as in a fresh worker process.
    state = store.states[run_id]
    guard = ConcurrencyGuard(basis_snapshot=state.basis_snapshots)
    recorder = ListRecorder()
    resumed = _revert_runner(products, store, sink, recorder, guard)
    resumed._tool_executor._product_detail = state.product_detail  # as _construct_runner does
    done = await resumed.resume(run_id, approved=True)

    assert done.status == WorkflowRunStatus.COMPLETED
    assert done.stop_reason == StopReason.FINAL_RESPONSE
    assert "khôi phục" in (done.final_response or "")
    [edit] = products.edits
    assert edit["title"] == "Nồi lẩu điện mini 1.5L"
    assert edit["main_images"] == [{"uri": "tos-old-1"}, {"uri": "tos-old-2"}]
    assert products.detail["title"] == "Nồi lẩu điện mini 1.5L"

    # The revert is itself recorded: Juli's value before, the original after.
    [call] = recorder.calls
    assert {w.field: (w.before, w.after) for w in call["writes"]} == {
        "title": ("Nồi lẩu điện Juli viết", "Nồi lẩu điện mini 1.5L"),
        "main_images": (["tos-new"], ["tos-old-1", "tos-old-2"]),
    }

    # The UI timeline: the ordinary event types, tool steps in playbook order.
    types = [e.event_type for e in sink.events]
    assert set(types) <= {
        "workflow.started",
        "workflow.status",
        "assistant.text",
        "tool.started",
        "tool.completed",
        "workflow.approval_required",
        "workflow.completed",
        "workflow.failed",
    }
    completed_tools = [e.payload.tool_name for e in sink.events if e.event_type == "tool.completed"]
    assert completed_tools == [
        "get_product_information",
        "update_product_listing",
        "check_product_status",
    ]
    assert all(e.payload.summary for e in sink.events if e.event_type == "tool.completed"), (
        "every completed step carries the runner's seller-facing summary"
    )
    assert types[-1] == "workflow.completed"


@pytest.mark.asyncio
async def test_a_revert_refuses_when_the_field_changed_while_waiting_for_consent():
    products = FakeProducts(_after_juli_write())
    store, sink = InMemoryStore(), InMemoryEventSink()
    run_id, _ = await _run_to_confirmation(products, store, sink)

    products.detail["title"] = "Người bán tự sửa tiêu đề"  # an external change (S-FR-8)

    state = store.states[run_id]
    guard = ConcurrencyGuard(basis_snapshot=state.basis_snapshots)
    resumed = _revert_runner(products, store, sink, ListRecorder(), guard)
    resumed._tool_executor._product_detail = state.product_detail
    done = await resumed.resume(run_id, approved=True)

    assert products.edits == [], "Juli does not overwrite an external change"
    assert done.stop_reason == StopReason.CONCURRENCY_CONFLICT
    assert sink.events[-1].event_type == "workflow.failed"


@pytest.mark.asyncio
async def test_a_declined_revert_writes_nothing_and_says_so():
    products = FakeProducts(_after_juli_write())
    store, sink = InMemoryStore(), InMemoryEventSink()
    run_id, _ = await _run_to_confirmation(products, store, sink)

    resumed = _revert_runner(products, store, sink, ListRecorder(), ConcurrencyGuard())
    done = await resumed.resume(run_id, approved=False)

    assert products.edits == []
    assert done.stop_reason == StopReason.CONFIRMATION_DECLINED
    assert "từ chối" in (done.final_response or "")


# --- start_revert and the routes (SQLite) ------------------------------------------


@pytest_asyncio.fixture
async def db(engine):
    """SQLite gets `uq_workflow_runs_active_shop_product` without its Postgres
    predicate (`postgresql_where`), which would forbid a finished run and its
    revert from sharing a subject. Recreate it partial, as Postgres has it."""
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
    return engine


async def _seed(session, *, label: str = "a", status: str = "completed", writes=None):
    user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=f"{label} shop", is_active=True)
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=PRODUCT_ID,
        name="Nồi lẩu",
        status="ACTIVATE",
        update_time=datetime(2026, 10, 1),
    )
    run = WorkflowRunRow(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        subject_ref=str(product.id),
        state={},
        status=status,
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    for i, (field, before, after) in enumerate(
        writes if writes is not None else [("title", "Nồi lẩu điện mini 1.5L", "Juli viết")]
    ):
        session.add(
            RunWriteValue(
                shop_id=shop.id,
                workflow_run_id=run.id,
                tool_call_id=f"c{i}",
                tool_name="update_product_listing",
                tiktok_product_id=PRODUCT_ID,
                field=field,
                before_value=before,
                after_value=after,
                after_source="read_back",
            )
        )
    await session.commit()
    return shop, run


def _live(title: str):
    async def _read(session, shop_id, tiktok_product_id):
        detail = copy.deepcopy(DETAIL)
        detail["title"] = title
        return detail

    return _read


@pytest.mark.asyncio
async def test_start_revert_creates_a_queued_run_linked_to_the_original(db, session):
    shop, run = await _seed(session)
    session.add(
        RunRevertQuestion(
            shop_id=shop.id, workflow_run_id=run.id, breaches=[{"metric": "ctr"}], status="open"
        )
    )
    await session.commit()

    started = await run_changes.start_revert(
        session,
        shop_id=shop.id,
        run_id=run.id,
        started_by_user_id=shop.user_id,
        read_live_product=_live("Juli viết"),
    )
    await session.commit()

    revert = await session.get(WorkflowRunRow, started.run_id)
    assert revert.status == "queued"
    assert revert.reverts_run_id == run.id
    assert revert.product_id == run.product_id
    plan = run_changes.revert_plan_from_state(revert.state)
    assert plan is not None
    assert plan.restore == {"title": "Nồi lẩu điện mini 1.5L"}
    assert plan.expected == {"title": "Juli viết"}
    question = (await session.execute(select(RunRevertQuestion))).scalar_one()
    assert (question.status, question.revert_run_id) == ("reverted", revert.id)


@pytest.mark.asyncio
async def test_start_revert_refuses_an_external_change_with_a_vietnamese_reason(db, session):
    shop, run = await _seed(session)
    with pytest.raises(run_changes.RevertRefused) as refused:
        await run_changes.start_revert(
            session,
            shop_id=shop.id,
            run_id=run.id,
            started_by_user_id=None,
            read_live_product=_live("Người bán đã sửa"),
        )
    assert refused.value.code == "external_change"
    assert refused.value.fields == ("title",)
    assert "Juli không ghi đè" in refused.value.message_vi
    assert (await session.execute(select(WorkflowRunRow))).scalars().all() == [run]


@pytest.mark.parametrize(
    ("status", "writes", "code"),
    [
        ("running", None, "not_finished"),
        ("completed", [], "nothing_written"),
        ("completed", [("price", [{"sku_id": "s"}], [{"sku_id": "s2"}])], "price_not_reverted"),
    ],
)
@pytest.mark.asyncio
async def test_start_revert_refuses_what_it_cannot_honestly_undo(db, session, status, writes, code):
    shop, run = await _seed(session, status=status, writes=writes)
    with pytest.raises(run_changes.RevertRefused) as refused:
        await run_changes.start_revert(
            session,
            shop_id=shop.id,
            run_id=run.id,
            started_by_user_id=None,
            read_live_product=_live("Juli viết"),
        )
    assert refused.value.code == code
    assert refused.value.message_vi


@pytest.mark.asyncio
async def test_a_revert_is_not_revertible_and_a_run_is_reverted_once(db, session):
    shop, run = await _seed(session)
    started = await run_changes.start_revert(
        session,
        shop_id=shop.id,
        run_id=run.id,
        started_by_user_id=None,
        read_live_product=_live("Juli viết"),
    )
    await session.commit()

    with pytest.raises(run_changes.RevertRefused) as in_progress:
        await run_changes.start_revert(
            session,
            shop_id=shop.id,
            run_id=run.id,
            started_by_user_id=None,
            read_live_product=_live("Juli viết"),
        )
    assert in_progress.value.code == "revert_in_progress"

    revert = await session.get(WorkflowRunRow, started.run_id)
    revert.status = "completed"
    session.add(
        RunWriteValue(
            shop_id=shop.id,
            workflow_run_id=revert.id,
            tool_call_id="revert-write",
            tool_name="update_product_listing",
            tiktok_product_id=PRODUCT_ID,
            field="title",
            before_value="Juli viết",
            after_value="Nồi lẩu điện mini 1.5L",
            after_source="read_back",
        )
    )
    await session.commit()

    for target, code in ((run.id, "already_reverted"), (revert.id, "is_revert")):
        with pytest.raises(run_changes.RevertRefused) as refused:
            await run_changes.start_revert(
                session,
                shop_id=shop.id,
                run_id=target,
                started_by_user_id=None,
                read_live_product=_live("Nồi lẩu điện mini 1.5L"),
            )
        assert refused.value.code == code


@pytest.mark.asyncio
async def test_another_shops_run_is_not_found(db, session):
    _shop_a, run_a = await _seed(session, label="a")
    shop_b, _run_b = await _seed(session, label="b")
    with pytest.raises(run_changes.RevertRunNotFound):
        await run_changes.start_revert(
            session,
            shop_id=shop_b.id,
            run_id=run_a.id,
            started_by_user_id=None,
            read_live_product=_live("Juli viết"),
        )


def _client(engine, shop: Shop, *, live_title: str = "Juli viết") -> AsyncClient:
    from juli_backend.api.app import create_app
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.api.routes import demo_run_changes
    from juli_backend.core.security import get_current_user
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=shop.user_id)
    application.dependency_overrides[get_active_shop] = lambda: shop
    application.dependency_overrides[demo_run_changes.get_live_product_reader] = lambda: _live(
        live_title
    )
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


@pytest.fixture
def no_celery(monkeypatch):
    from juli_backend.api.routes import demo_run_changes

    enqueued: list[uuid.UUID] = []

    def _enqueue(run_id):
        enqueued.append(run_id)
        return "task-1"

    monkeypatch.setattr(demo_run_changes, "_enqueue_run_agent_workflow", _enqueue)
    return enqueued


@pytest.mark.asyncio
async def test_the_revert_route_202s_and_enqueues_the_new_run(db, session, no_celery):
    shop, run = await _seed(session)
    async with _client(db, shop) as client:
        before = await client.get(f"/v1/demo/runs/{run.id}/changes")
        resp = await client.post(f"/v1/demo/runs/{run.id}/revert")
        after = await client.get(f"/v1/demo/runs/{run.id}/changes")

    assert before.status_code == 200
    body = before.json()
    assert body["changes"][0]["field"] == "title"
    assert body["changes"][0]["before"] == "Nồi lẩu điện mini 1.5L"
    assert body["changes"][0]["after"] == "Juli viết"
    assert body["revert"]["available"] is True

    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    assert data["reverts_run_id"] == str(run.id)
    assert data["status"] == "queued"
    assert data["fields"] == ["title"]
    assert no_celery == [uuid.UUID(data["run_id"])]

    assert after.json()["revert"]["available"] is False
    assert after.json()["revert"]["reason_code"] == "revert_in_progress"
    assert after.json()["revert"]["runs"][0]["run_id"] == data["run_id"]


@pytest.mark.asyncio
async def test_the_revert_route_409s_with_the_reason_on_an_external_change(db, session, no_celery):
    shop, run = await _seed(session)
    async with _client(db, shop, live_title="Người bán đã sửa") as client:
        resp = await client.post(f"/v1/demo/runs/{run.id}/revert")
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "external_change"
    assert detail["fields"] == ["title"]
    assert "Juli không ghi đè" in detail["message"]
    assert no_celery == []


@pytest.mark.asyncio
async def test_the_routes_404_for_another_shops_run(db, session, no_celery):
    _shop_a, run_a = await _seed(session, label="a")
    shop_b, _ = await _seed(session, label="b")
    async with _client(db, shop_b) as client:
        changes = await client.get(f"/v1/demo/runs/{run_a.id}/changes")
        revert = await client.post(f"/v1/demo/runs/{run_a.id}/revert")
    assert changes.status_code == 404
    assert revert.status_code == 404
    assert no_celery == []


def test_the_revert_plan_round_trips_through_run_state():
    state = RunState().to_dict()
    state["revert_plan"] = PLAN.to_state()
    restored = RunState.from_dict(state).to_dict()
    assert run_changes.revert_plan_from_state(restored) == PLAN
    assert run_changes.revert_plan_from_state({}) is None
    assert PLAN.restore_main_image_uris == ("tos-old-1", "tos-old-2")


def test_migration_078_is_short_chained_and_tenant_scoped():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "backend/src/juli_backend/database/migrations/versions/078_rules_and_write_values.py"
    )
    text = path.read_text(encoding="utf-8")
    assert 'revision: str = "078_rules_and_write_values"' in text
    assert len("078_rules_and_write_values") <= 32
    assert 'down_revision: str | None = "077_metric_rankings"' in text
    for table in ("run_write_values", "shop_rules", "run_revert_questions"):
        assert f'"{table}"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text

    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    for table in ("run_write_values", "shop_rules", "run_revert_questions"):
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"
