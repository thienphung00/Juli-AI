"""P64 walkthrough fixes for the sandbox "Tạo sản phẩm" run (D73.3).

1. The reviewer may edit the proposed title / description before confirming the create
   (it was refused with "Bước này không có nội dung sửa được."); the create sends exactly
   the edit and the audit records it.
2. A brand / manufacturer name the source TITLE does not carry (the sandbox listing held a
   real customer's name in its VN "Manufacturer/Trader Name / Address" attributes and its
   description) is never copied into the create body, never shown to the model, and a
   draft that still names one is refused before the reviewer is asked (once more, then the
   run ends) and again at execution.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import select

from juli_backend.models.models import RunConfirmation
from juli_backend.services import shop_rules
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm.blocks import (
    AssistantTurn,
    FinalResponse,
    ToolCallBlock,
    Usage,
)
from juli_backend.services.agent.playbooks.create_product import CREATE_PRODUCT_PLAYBOOK
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools import catalog_create as cc
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.agent_runs import confirmations
from tests.support.api import authenticated_client
from tests.support.builders import make_tenant, make_workflow_run
from tests.unit.test_reviewer_sandbox_create_product import (
    CONTEXT,
    SOURCE_ID,
    FakeProducts,
    _sandbox,
)

#: The source the reviewer saw: brand "No brand", the customer's name in the two VN
#: manufacturer attributes and in a description bullet.
SOURCE_TITLE = "Bình Nước Thép Không Gỉ Chính Hãng 750ml"
CUSTOMER = "Fujiwa"
MANUFACTURER_ATTRS = [
    {"id": "100149", "name": "Xuất xứ", "is_requried": True, "type": "PRODUCT_PROPERTY"},
    {"id": "101489", "name": "Manufacturer/Trader Name", "is_requried": True,
     "type": "PRODUCT_PROPERTY"},
    {"id": "101490", "name": "Manufacturer/Trader Address", "is_requried": True,
     "type": "PRODUCT_PROPERTY"},
    {"id": "101164", "name": "Kiểu", "is_requried": False, "type": "PRODUCT_PROPERTY"},
]  # fmt: skip


class BrandedProducts(FakeProducts):
    def __init__(self, *, attributes: list[dict[str, Any]] | None = None, **source: Any) -> None:
        super().__init__(attributes=attributes)
        self.source = source

    def get_details(self, product_id: str) -> dict[str, Any]:
        detail = super().get_details(product_id)
        if product_id != SOURCE_ID:
            return detail
        detail = copy.deepcopy(detail)
        detail.update(
            {
                "title": SOURCE_TITLE,
                "brand": {"id": "", "name": "No brand"},
                "description": (
                    f"<ul><li><strong>{CUSTOMER}</strong> bình giữ nhiệt</li>"
                    "<li>Thép không gỉ 304, dung tích 750ml</li></ul>"
                ),
                "product_attributes": [
                    {"id": "100149", "name": "Xuất xứ",
                     "values": [{"id": "1000854", "name": "Việt Nam"}]},
                    {"id": "101489", "name": "Manufacturer/Trader Name",
                     "values": [{"name": CUSTOMER}]},
                    {"id": "101490", "name": "Manufacturer/Trader Address",
                     "values": [{"name": CUSTOMER}]},
                    {"id": "101164", "name": "Kiểu",
                     "values": [{"name": f"Bình {CUSTOMER} Pro"}]},
                ],
            }
        )  # fmt: skip
        detail.update(self.source)
        return detail


def _input(title: str, description: str = "Bình nước thép không gỉ 750ml.\n\nDùng hằng ngày."):
    return cc.CreateProductInput(
        category_id="605254", title=title, description=description, reason_vi="Cùng danh mục."
    )


# -- 2. the brand never travels -----------------------------------------------------------


def test_the_source_brand_terms_are_the_manufacturer_values_the_title_lacks():
    detail = BrandedProducts().get_details(SOURCE_ID)
    assert cc.source_brand_terms(detail) == [CUSTOMER]
    # Named by the title itself: not a leak.
    named = {**detail, "title": f"Bình nước {CUSTOMER} 750ml"}
    assert cc.source_brand_terms(named) == []


def test_the_model_never_reads_the_customer_name_in_the_source_description():
    out = cc.handle_get_category_candidates(
        _sandbox(BrandedProducts()), CONTEXT, cc.GetCategoryCandidatesInput()
    )
    shown = str(out.source_description)
    assert CUSTOMER not in shown and "Thép không gỉ 304" in shown


def test_manufacturer_values_absent_from_the_title_are_never_copied():
    attrs = [a for a in MANUFACTURER_ATTRS if a["id"] in ("100149", "101164")]
    products = BrandedProducts(attributes=attrs)
    out = cc.handle_create_product(
        _sandbox(products), CONTEXT, _input("Bình nước thép không gỉ 750ml dùng hằng ngày")
    )
    assert out.ok, out
    body = products.created[0]
    assert CUSTOMER not in str(body)
    # Xuất xứ (a TikTok option) is copied; the free-text "Kiểu" naming the customer is not.
    assert body["product_attributes"] == [
        {"id": "100149", "values": [{"id": "1000854", "name": "Việt Nam"}]}
    ]


def test_a_required_manufacturer_attribute_is_refused_rather_than_leaked():
    products = BrandedProducts(attributes=MANUFACTURER_ATTRS)
    check = cc.handle_check_listing_requirements(
        _sandbox(products), CONTEXT, cc.CheckListingRequirementsInput(category_id="605254")
    )
    assert check.ok is False and check.error_code == "required_attribute_missing"
    assert check.missing == ["Manufacturer/Trader Name", "Manufacturer/Trader Address"]
    assert CUSTOMER not in check.summary_vi
    assert "không sao chép tên thương hiệu" in check.summary_vi
    created = cc.handle_create_product(
        _sandbox(products), CONTEXT, _input("Bình nước thép không gỉ 750ml dùng hằng ngày")
    )
    assert created.error_code == "required_attribute_missing" and products.created == []


def test_a_manufacturer_the_title_names_is_copied():
    products = BrandedProducts(attributes=MANUFACTURER_ATTRS, title=f"Bình nước {CUSTOMER} 750ml")
    out = cc.handle_create_product(
        _sandbox(products), CONTEXT, _input(f"Bình nước {CUSTOMER} thép không gỉ 750ml")
    )
    assert out.ok, out
    copied = {row["id"] for row in products.created[0]["product_attributes"]}
    assert {"101489", "101490"} <= copied


@pytest.mark.parametrize(
    ("title", "description", "field"),
    [
        (f"Bình Nước Thép Không Gỉ {CUSTOMER} 750ml Dùng Hàng Ngày", None, "title"),
        (
            "Bình nước thép không gỉ 750ml dùng hằng ngày",
            f"Bình {CUSTOMER} 750ml bền đẹp.",
            "description",
        ),
        # A foreign proper name the source title does not carry (not in any attribute).
        ("Bình Nước Thép Không Gỉ Zojirushi 750ml", None, "title"),
    ],
)  # fmt: skip
def test_a_draft_naming_a_brand_is_refused_before_the_create(title, description, field):
    products = BrandedProducts(attributes=MANUFACTURER_ATTRS[:1])
    params = _input(title, description) if description else _input(title)
    refusal = cc.precheck_create_product(_sandbox(products), CONTEXT, params)
    assert refusal is not None and refusal.error_code == "brand_not_in_source"
    assert CUSTOMER not in refusal.summary_vi and "Zojirushi" not in refusal.summary_vi
    assert field in refusal.model_hint
    out = cc.handle_create_product(_sandbox(products), CONTEXT, params)
    assert out.ok is False and out.error_code == "brand_not_in_source"
    assert products.created == []


def test_ordinary_vietnamese_drafts_pass_the_brand_check():
    products = BrandedProducts(attributes=MANUFACTURER_ATTRS[:1])
    for title in (
        "Bình Nước Thép Không Gỉ 750ml Dùng Hàng Ngày",
        "Combo 2 bình nước thép không gỉ 750ml free size, có zip",
    ):
        assert cc.precheck_create_product(_sandbox(products), CONTEXT, _input(title)) is None


# -- runner: refused before the pause, drafted once more -----------------------------------


class ScriptedLLM:
    """Proposes ``create_product`` with each title in turn; ends after any other result."""

    def __init__(self, titles: Sequence[str]) -> None:
        self.titles = list(titles)
        self.seen: list[Any] = []

    async def complete(self, *, messages, system, tools, config, tool_choice=None, **_: Any):
        del system, tools, config, tool_choice
        self.seen = list(messages)
        last = messages[-1] if messages else {}
        if (
            isinstance(last, dict)
            and last.get("role") == "tool"
            and last.get("tool_name") == cc.CREATE_PRODUCT_TOOL
            and "error" not in (last.get("content") or {})
        ):
            return _turn(FinalResponse(content="Đã tạo sản phẩm, TikTok đang duyệt."))
        if not self.titles:
            return _turn(FinalResponse(content="Juli dừng."))
        title = self.titles.pop(0)
        return _turn(
            ToolCallBlock(
                call_id=f"call-{len(self.titles)}",
                tool_name=cc.CREATE_PRODUCT_TOOL,
                arguments=_input(title).model_dump(),
            )
        )


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=0, output_tokens=0))


class InMemoryStore:
    def __init__(self) -> None:
        self.states: dict[uuid.UUID, RunState] = {}

    async def load(self, workflow_run_id: uuid.UUID) -> RunState:
        state = self.states.setdefault(workflow_run_id, RunState())
        state.prompt_version = state.prompt_version or "create_product.v1"
        state.prompt_sha256 = state.prompt_sha256 or "0" * 64
        return state

    async def persist(self, workflow_run_id, state, **kwargs) -> None:
        self.states[workflow_run_id] = state


def _runner(products, store, sink, llm) -> WorkflowRunner:
    registry = ToolRegistry()
    cc.register_catalog_create_tools(registry)
    register_terminal_tools(registry)
    resources = _sandbox(products)
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=resources,
        write_resources=resources,
        product_id=SOURCE_ID,
    )
    return WorkflowRunner(
        llm_service=llm,
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=CREATE_PRODUCT_PLAYBOOK,
    )


def _completed(sink: InMemoryEventSink) -> list[Any]:
    return [e.payload for e in sink.events if e.event_type == "tool.completed"]


async def test_a_branded_draft_is_refused_and_the_clean_redraft_reaches_the_reviewer():
    products, store, sink = (
        BrandedProducts(attributes=MANUFACTURER_ATTRS[:1]),
        InMemoryStore(),
        InMemoryEventSink(),
    )
    clean = "Bình Nước Thép Không Gỉ 750ml Dùng Hàng Ngày"
    llm = ScriptedLLM([f"Bình Nước Thép Không Gỉ {CUSTOMER} 750ml Dùng Hàng Ngày", clean])
    run_id = uuid.uuid4()
    paused = await _runner(products, store, sink, llm).run(run_id, product_ref=SOURCE_ID)

    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL, paused
    state = store.states[run_id]
    assert state.pending_confirmation["arguments"]["title"] == clean
    (refused,) = _completed(sink)
    assert refused.ok is False and CUSTOMER not in refused.summary  # the reviewer's line
    model_view = [m for m in state.conversation_window if m.get("role") == "tool"]
    assert CUSTOMER in str(model_view[0]["content"])  # the model is told what to drop
    approval = [e.payload for e in sink.events if e.event_type == "workflow.approval_required"]
    assert CUSTOMER not in str(approval)
    assert products.created == []  # nothing written before the confirmation


async def test_two_branded_drafts_in_a_row_end_the_run_without_asking():
    products, store, sink = (
        BrandedProducts(attributes=MANUFACTURER_ATTRS[:1]),
        InMemoryStore(),
        InMemoryEventSink(),
    )
    branded = f"Bình Nước Thép Không Gỉ {CUSTOMER} 750ml Dùng Hàng Ngày"
    run_id = uuid.uuid4()
    result = await _runner(products, store, sink, ScriptedLLM([branded, branded])).run(
        run_id, product_ref=SOURCE_ID
    )
    assert result.status != WorkflowRunStatus.WAITING_APPROVAL
    assert not [e for e in sink.events if e.event_type == "workflow.approval_required"]
    assert products.created == []


# -- 1. the reviewer edits the create proposal ---------------------------------------------

PROPOSED = _input("Bình Nước Thép Không Gỉ 750ml Dùng Hàng Ngày").model_dump()


async def _waiting_create_run(session, shop):
    run = await make_workflow_run(
        session,
        shop,
        status="waiting_approval",
        workflow_key="create_product",
        prompt_version="create_product.v1",
        state={
            "pending_confirmation": {
                "call_id": "call-1",
                "tool_name": cc.CREATE_PRODUCT_TOOL,
                "arguments": dict(PROPOSED),
            }
        },
    )
    session.add(
        RunConfirmation(
            workflow_run_id=run.id,
            tool_call_id="call-1",
            options=[
                {
                    "option_id": "1",
                    "proposed_change": dict(PROPOSED),
                    "rationale": "x",
                    "params_sha": compute_params_sha(dict(PROPOSED)),
                }
            ],
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )
    )
    await session.commit()
    return run


@pytest.fixture
def enqueued(monkeypatch) -> list[Any]:
    from juli_backend.api.routes import agent_runs

    calls: list[Any] = []
    monkeypatch.setattr(
        agent_runs,
        "_enqueue_resume_agent_workflow",
        lambda run_id, *, approved: calls.append((run_id, approved)) or "task-resume",
    )
    return calls


async def _confirm(session, user, shop, run, body):
    async with authenticated_client(session, user=user, shop=shop) as client:
        return await client.post(f"/v1/demo/runs/{run.id}/confirmations/call-1", json=body)


async def test_the_create_confirmation_accepts_the_reviewers_edit(session, enqueued):
    user, shop = await make_tenant(session)
    run = await _waiting_create_run(session, shop)
    title = "Bình nước thép không gỉ 750ml bản người duyệt sửa"
    description = "Mô tả người duyệt sửa: bình thép không gỉ 750ml, giữ nhiệt tốt."
    resp = await _confirm(
        session,
        user,
        shop,
        run,
        {
            "decision": "approve",
            "option_id": "1",
            "edited_values": {"title": title, "description": description},
        },
    )
    assert resp.status_code == 202, resp.text
    await session.refresh(run)
    pending = run.state["pending_confirmation"]
    expected = {**PROPOSED, "title": title, "description": description}
    assert pending["arguments"] == expected
    assert pending["params_sha"] == compute_params_sha(expected)
    assert pending["edited_fields"] == ["description", "title"]
    assert enqueued == [(run.id, True)]


@pytest.mark.parametrize(
    ("edited", "field", "fragment"),
    [
        ({"title": "Quá ngắn"}, "title", "từ 25 đến 255"),
        ({"description": "x" * 5_001}, "description", "tối đa 5.000 ký tự"),
        ({"title": "Bình nước thép không gỉ 750ml hàng xịn nhất"}, "title", '"xịn nhất"'),
    ],
)
async def test_a_create_edit_that_breaks_a_rule_is_refused(
    session, enqueued, edited, field, fragment
):
    user, shop = await make_tenant(session)
    run = await _waiting_create_run(session, shop)
    await shop_rules.set_rule(
        session,
        shop.id,
        rule_key="banned_terms",
        scope_ref=None,
        value=["xịn nhất"],
        set_by="seller",
        set_by_user_id=user.id,
    )
    await session.commit()
    resp = await _confirm(
        session, user, shop, run, {"decision": "approve", "option_id": "1", "edited_values": edited}
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "rule_violation" and detail["field"] == field
    assert fragment in detail["message"]
    confirmation = (await session.execute(select(RunConfirmation))).scalar_one()
    assert confirmation.status == "pending"
    assert enqueued == []


async def test_the_create_executes_exactly_the_edit(session):
    """Real runner + executor: pause at consent, bind the edit, resume, create."""
    _user, shop = await make_tenant(session)
    products, store, sink = (
        BrandedProducts(attributes=MANUFACTURER_ATTRS[:1]),
        InMemoryStore(),
        InMemoryEventSink(),
    )
    run_id = uuid.uuid4()
    llm = ScriptedLLM(["Bình Nước Thép Không Gỉ 750ml Dùng Hàng Ngày"])
    paused = await _runner(products, store, sink, llm).run(run_id, product_ref=SOURCE_ID)
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL

    row = await make_workflow_run(
        session,
        shop,
        status="waiting_approval",
        workflow_key="create_product",
        state=store.states[run_id].to_dict(),
    )
    edited = "Bình nước thép không gỉ 750ml, bản người duyệt sửa"
    await confirmations._apply_seller_edits(session, row, {"title": edited})
    store.states[run_id] = RunState.from_dict(cast(dict, row.state))

    done = await _runner(products, store, sink, llm).resume(run_id, approved=True)
    assert done.status == WorkflowRunStatus.COMPLETED, done
    assert products.created[-1]["title"] == edited
    assert _completed(sink)[-1].summary.endswith("· theo bản bạn sửa")
    assert "mã 1737000000000000001" in _completed(sink)[-1].summary
