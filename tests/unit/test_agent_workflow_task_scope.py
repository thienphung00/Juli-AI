"""The agent-run worker path must run inside a tenant scope (#1883).

`workers/tasks/agent_workflow.py::_run_agent_workflow_async` and
`_resume_agent_workflow_async` entered no scope at all. Since the RLS cutover
of 2026-09-07 the worker connects as `juli_app`, so `_load_context`'s very
first read — `session.get(WorkflowRun, run_id)` on a policied table — returns
nothing and every run dies on its first statement. Verified on production
2026-09-10 (`select current_user` -> `juli_app`); no run had been attempted
since 2026-08-27, so it had not yet surfaced.

WHY A STICKY SCOPE AND NOT `reapply_shop_scope`. The run loop commits
constantly and from inside other modules: `JsonbConversationStore.persist`
commits on every turn, `ToolExecutionLedger` commits four times around every
write. `SET LOCAL` dies at each of those, so "re-apply after the callee
returns" would have to be spelled at call sites this task shell does not own.
`with_sticky_shop_scope` holds instead.

WHAT THIS SUITE DRIVES. The real `WorkflowRunner`, the real
`ProductToolExecutor`, the real `ToolExecutionLedger`, the real
`JsonbConversationStore` and the real `PersistingEventSink` — over real
Postgres, as `juli_app`, on sessions whose `commit()` is a real COMMIT. Only
two things are substituted, and both are outside the boundary this issue is
about: the LLM (`FakeLLMService`, the production fake from
`services/agent/llm/fake.py`) and the TikTok resources, whose doubles are
bound to the real `ProductsResource` method signatures the handlers call.

The round trip is the gate-walk shape end to end: leg 1 reads the product and
proposes a CONFIRM write, pausing at `waiting_approval`; leg 2 resumes with
the seller's approval and the write dispatches through the ledger, leaving a
`tool_executions` row. Every one of those tables is RLS-gated.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text

from juli_backend.database.tenant_context import with_sticky_shop_scope
from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.models.models import ToolExecution, WorkflowRun
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.workers.tasks import agent_workflow
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    juli_app_sync_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

# Shaped like docs/integrations/tiktok_api/samples/products-detail-response.json,
# carrying exactly the fields the B-4 edit body draws on. Lifted from
# `test_agent_product_detail_survives_pause.py::DETAIL` and extended with the
# `main_images` that `_extract_main_image_refs` requires.
_PRODUCT_DETAIL: dict[str, Any] = {
    "id": "1736363193934775939",
    "title": "Nồi lẩu điện mini 1.5L có nắp kính",
    "description": "<p>mô tả</p>",
    "status": "ACTIVE",
    "category_chains": [
        {"id": "849672", "is_leaf": False, "local_name": "Nhà bếp", "parent_id": "0"},
        {"id": "601693", "is_leaf": True, "local_name": "Nồi điện", "parent_id": "849672"},
    ],
    "main_images": [
        {"uri": "tos-maliva-i-o3syd03w52-us/img-1", "width": 800, "height": 800},
    ],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "skus": [
        {
            "id": "1734952449674217079",
            "price": {"currency": "VND", "tax_exclusive_price": "599000"},
            "inventory": [{"quantity": 7, "warehouse_id": "7272949914115966726"}],
        }
    ],
}


class _FakeProductsResource:
    """A `ProductsResource` double carrying the real method signatures the two
    handlers in this run actually call.

    `get_details(product_id)` and `edit(product_id=..., body=...)` are copied
    from `integrations/tiktok/resources/products.py`. A `**kwargs` double would
    prove routing and nothing else — it cannot fail when the real call would.
    """

    def __init__(self) -> None:
        self.get_details_calls: list[str] = []
        self.edit_calls: list[tuple[str, dict[str, Any]]] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        self.get_details_calls.append(product_id)
        return dict(_PRODUCT_DETAIL)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edit_calls.append((product_id, dict(body)))
        return {"product_id": product_id}


class _UnreachableResource:
    """Stands in for the bundle members this run never touches.

    Not `None`: a `None` would read as "optional", and any accidental call
    would be an `AttributeError` on `NoneType` that says nothing about which
    resource was reached. This says it.
    """

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"this run must not reach {name!r} on an unrelated marketplace resource"
        )


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=_UnreachableResource(),
        orders=_UnreachableResource(),
        products=products,
        returns=_UnreachableResource(),
        inventory=_UnreachableResource(),
        analytics=_UnreachableResource(),
        promotion=_UnreachableResource(),
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=_UnreachableResource(),
        products=products,
        fulfillment=_UnreachableResource(),
        promotion=_UnreachableResource(),
    )


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _read_then_confirm_playbook() -> Playbook:
    """One AUTO read step and one CONFIRM write step, on the real
    `optimize_product_2` workflow_key/version so `compose()` still resolves a
    real prose binding. Same shape as
    `test_agent_runner_pause_resume.py::_pause_resume_playbook`."""
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id="read",
                intent="Read the product.",
                tools=("get_product_information",),
                policy=ToolPolicy.AUTO,
            ),
            PlaybookStep(
                step_id="write",
                intent="Publish the improved listing.",
                tools=("update_product_listing",),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=replace(OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()),
    )


def _turn(*blocks: Any) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


_RUN_LEG_SCRIPT = [
    _turn(ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})),
    _turn(
        ToolCallBlock(
            call_id="c2",
            tool_name="update_product_listing",
            arguments={"title": "Nồi lẩu điện mini 1.5L — nắp kính chịu nhiệt"},
        )
    ),
]

_RESUME_LEG_SCRIPT = [_turn(FinalResponse(content="Listing updated."))]


@pytest.fixture
def owner_engine():
    """A sync engine as the table owner, for seeding and for reading back."""
    with owner_sync_engine() as engine:
        yield engine


@pytest.fixture
def app_sync_sessionmaker():
    """The ledger's sync `Session`, as `juli_app`.

    In production `_sync_ledger_session` builds this from the worker's own
    `DATABASE_URL`, which is the `juli_app` URL. Here `DATABASE_URL` is the
    owner's, and an owner connection is RLS-exempt — so substituting the ROLE,
    and only the role, is what keeps the `tool_executions` writes under the
    policies they face in production. The scope wrapping around it stays
    production code.
    """
    with juli_app_sync_sessionmaker() as maker:
        yield maker


def _seed_queued_run(engine) -> tuple[uuid.UUID, uuid.UUID, str]:
    """One user, one shop, one product and one `queued` run — the state the
    Celery task is enqueued against."""
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    product_id = uuid.uuid4()
    run_id = uuid.uuid4()
    tiktok_product_id = f"agt-1883-{uuid.uuid4().hex[:10]}"

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": "Sticky scope shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products "
                "(id, shop_id, tiktok_product_id, name, status, update_time, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, :name, 'ACTIVE', :now, :now, :now)"
            ),
            {
                "id": str(product_id),
                "shop_id": str(shop_id),
                "tiktok_id": tiktok_product_id,
                "name": "Nồi lẩu điện mini",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs "
                "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :product_id, CAST(:state AS jsonb), 'queued', "
                " :prompt_version, :prompt_sha256, :now, :now)"
            ),
            {
                "id": str(run_id),
                "state": json.dumps(RunState().to_dict()),
                "shop_id": str(shop_id),
                "product_id": str(product_id),
                "prompt_version": "optimize_product_2/v1",
                "prompt_sha256": "0" * 64,
                "now": now,
            },
        )
    return run_id, shop_id, tiktok_product_id


@contextlib.contextmanager
def _worker_bound_to_juli_app(
    monkeypatch, factory, sync_sessionmaker, products: _FakeProductsResource, script: list
):
    """Bind the task module's seams: `juli_app` sessions, a fake LLM, fake
    marketplace resources. Everything else — the runner, the executor, the
    ledger, the conversation store, the event sink and the scopes — is the
    production code path.
    """
    monkeypatch.setattr(agent_workflow, "_ensure_session_factory", lambda: factory)

    @contextlib.contextmanager
    def _juli_app_ledger_session():
        session = sync_sessionmaker()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(agent_workflow, "_sync_ledger_session", _juli_app_ledger_session)
    monkeypatch.setattr(
        agent_workflow, "_default_llm_service", lambda: FakeLLMService(script=list(script))
    )
    monkeypatch.setattr(agent_workflow, "_default_tool_registry", _full_registry)
    monkeypatch.setattr(agent_workflow, "_default_playbook", _read_then_confirm_playbook)

    async def _fake_read_resources(session, shop_id=None):
        return _read_resources(products)

    async def _fake_write_resources(session):
        return _write_resources(products)

    monkeypatch.setattr(agent_workflow, "_default_read_resources", _fake_read_resources)
    monkeypatch.setattr(agent_workflow, "_default_write_resources", _fake_write_resources)
    monkeypatch.delenv("REDIS_URL", raising=False)
    yield


def _run_row(engine, run_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT status, stop_reason FROM public.workflow_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).one_or_none()


# ---------------------------------------------------------------------------
# AC — an agent run completes under RLS.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_an_agent_run_completes_under_rls(owner_engine, app_sync_sessionmaker, monkeypatch):
    """Drives the two real task bodies over a `queued` run, as `juli_app`.

    RED on the pre-fix code: with no scope open, `_load_context`'s
    `session.get(WorkflowRun, run_id)` reads zero rows and the task raises
    `LookupError('workflow_runs row not found')` before the runner is ever
    constructed — so the run stays `queued` forever and the crash handler
    cannot write a terminal event either.

    GREEN: leg 1 pauses at `waiting_approval` with its events persisted, leg 2
    dispatches the approved write through the ledger and the run reaches
    `completed` with a readable `tool_executions` row.
    """
    run_id, shop_id, tiktok_product_id = _seed_queued_run(owner_engine)
    products = _FakeProductsResource()

    async with juli_app_async_sessionmaker() as factory:
        with _worker_bound_to_juli_app(
            monkeypatch, factory, app_sync_sessionmaker, products, _RUN_LEG_SCRIPT
        ):
            await agent_workflow._run_agent_workflow_async(str(run_id))

        paused = _run_row(owner_engine, run_id)
        assert paused is not None, "the seeded run row must still exist"
        assert paused.status == WorkflowRunStatus.WAITING_APPROVAL.value, (
            f"leg 1 must reach waiting_approval under RLS; the run is {paused.status!r} "
            f"with stop_reason={paused.stop_reason!r} — a `queued` row here means the "
            f"task never got past its first gated read"
        )
        assert set(products.get_details_calls) == {tiktok_product_id}, (
            "the AUTO read must have dispatched against the run's own bound product "
            f"and nothing else, got {products.get_details_calls}"
        )

        with _worker_bound_to_juli_app(
            monkeypatch, factory, app_sync_sessionmaker, products, _RESUME_LEG_SCRIPT
        ):
            await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)

    finished = _run_row(owner_engine, run_id)
    assert finished is not None
    assert finished.status == WorkflowRunStatus.COMPLETED.value, (
        f"leg 2 must reach a terminal completed status under RLS; the run is "
        f"{finished.status!r} with stop_reason={finished.stop_reason!r}"
    )
    assert len(products.edit_calls) == 1, (
        f"the approved CONFIRM write must have dispatched exactly once, got "
        f"{len(products.edit_calls)}"
    )

    # Every row the run wrote must be readable back under the run's own shop
    # scope — the async session's rows and the sync ledger's alike.
    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with with_sticky_shop_scope(session, shop_id):
                run_rows = (
                    (await session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id)))
                    .scalars()
                    .all()
                )
                events = (
                    (
                        await session.execute(
                            select(WorkflowRunEventRow).where(
                                WorkflowRunEventRow.workflow_run_id == run_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                executions = (
                    (
                        await session.execute(
                            select(ToolExecution).where(ToolExecution.workflow_run_id == run_id)
                        )
                    )
                    .scalars()
                    .all()
                )

    assert len(run_rows) == 1, "the workflow_runs row must be readable under the shop scope"
    assert len(events) > 0, (
        "PersistingEventSink must have persisted this run's events — every insert it "
        "makes is against the RLS-gated workflow_run_events"
    )
    assert [e.tool_name for e in executions] == ["update_product_listing"], (
        f"the ledger must have written exactly one tool_executions row for the approved "
        f"write, got {[e.tool_name for e in executions]} — a ledger running outside the "
        f"shop scope cannot insert into that table at all"
    )
    assert executions[0].status == "succeeded", (
        f"the ledger row must be marked succeeded after the write returned, got "
        f"{executions[0].status!r}"
    )
