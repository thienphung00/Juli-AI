"""A completed agent write must record its outcome (#1939, W8-F / P10-8).

`workflow_outcome_records` had never held a row in production: the recorder
(`services/operations/outcome_tracking.py::record_workflow_outcome`) was only
ever called from the legacy Celery-approval path
(`services/execution/worker.py:64`), and the agent runner dispatches its
writes through `ToolExecutionLedger` instead. So #1655's outcome chain read
the state-change link as `missing` after every real agent write — correctly,
because the fact was never recorded at all.

WHAT THIS SUITE DRIVES. The two real task bodies
(`workers/tasks/agent_workflow.py`), the real `WorkflowRunner`, the real
`ProductToolExecutor`, the real `ToolExecutionLedger`, the real
`JsonbConversationStore`, the real `PersistingEventSink` and the real
`record_workflow_outcome` — over real Postgres, as `juli_app`, on sessions
whose `commit()` is a real COMMIT. Only two things are substituted, both
outside the boundary this issue is about: the LLM (`FakeLLMService`, the
production fake) and the TikTok resources, whose doubles carry the real
`ProductsResource` method signatures the handlers call.

The harness below deliberately mirrors `test_agent_workflow_task_scope.py`
rather than importing from it: that suite is the #1883 scope proof and must
stay untouched by this slice.

WHY SOME CASES ARE DRIVEN AT THE LEDGER SEAM INSTEAD OF THE TASK BODY. The
replay branch (`_resolve_existing` returning the stored result with zero
vendor calls) and the fail-closed unverifiable branch cannot be reached twice
through `_resume_agent_workflow_async`, which consumes the run's
`pending_confirmation` on its first leg and raises
`NoPendingConfirmationError` afterwards. Those cases drive the REAL
`ToolExecutionLedger` and the REAL recorder as the runner pairs them — never
a hand-inserted `tool_executions` row, because the defect being fixed is the
wiring.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_sticky_shop_scope, with_sticky_shop_scope_sync
from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.runner.ledger import (
    LedgerStatus,
    ToolExecutionLedger,
    ToolExecutionRequestPayload,
    ToolExecutionUnrecoverableError,
)
from juli_backend.services.agent.runner.outcome_recording import LedgerWriteOutcomeRecorder
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools
from juli_backend.services.operations.outcome_chain import (
    EmptyLink,
    StateChangeLink,
    load_outcome_chain,
)
from juli_backend.services.operations.outcome_tracking import (
    TERMINAL_FAILED,
    TERMINAL_SUCCEEDED,
)
from juli_backend.workers.tasks import agent_workflow
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    juli_app_sync_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

# Shaped like docs/integrations/tiktok_api/samples/products-detail-response.json,
# carrying exactly the fields the B-4 edit body draws on.
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
    handlers in this run actually call — `get_details(product_id)` and
    `edit(product_id=..., body=...)`, copied from
    `integrations/tiktok/resources/products.py`. A `**kwargs` double would
    prove routing and nothing else.

    `edit_error`, when set, is what `edit` raises — the vendor failure that
    drives a write to the ledger's `failed` terminal state.
    """

    def __init__(self, *, edit_error: Exception | None = None) -> None:
        self.get_details_calls: list[str] = []
        self.edit_calls: list[tuple[str, dict[str, Any]]] = []
        self._edit_error = edit_error

    def get_details(self, product_id: str) -> dict[str, Any]:
        self.get_details_calls.append(product_id)
        return dict(_PRODUCT_DETAIL)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edit_calls.append((product_id, dict(body)))
        if self._edit_error is not None:
            raise self._edit_error
        return {"product_id": product_id}


class _UnreachableResource:
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
    real prose binding."""
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
    with owner_sync_engine() as engine:
        yield engine


@pytest.fixture
def app_sync_sessionmaker():
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
    tiktok_product_id = f"agt-1939-{uuid.uuid4().hex[:10]}"

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
                "name": "Outcome recording shop",
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
    ledger, the conversation store, the event sink, the outcome recorder and
    the scopes — is the production code path.
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


def _outcome_rows(engine, run_id: uuid.UUID) -> list[Any]:
    """Every `workflow_outcome_records` row joined to this run's executions on
    `execution_id` — read back as the OWNER, so the assertion sees what is in
    the table rather than what one scope may read."""
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT r.id, r.execution_id, r.workflow_id, r.execution_status, "
                    "       r.approval_id, r.metrics_json, e.status AS ledger_status "
                    "FROM public.workflow_outcome_records r "
                    "JOIN public.tool_executions e ON e.id = r.execution_id "
                    "WHERE e.workflow_run_id = :run_id"
                ),
                {"run_id": str(run_id)},
            )
        )


def _run_row(engine, run_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT status, stop_reason FROM public.workflow_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).one_or_none()


async def _drive_write_to_completion(
    monkeypatch, factory, app_sync_sessionmaker, products, run_id
) -> None:
    """Both real task bodies over a seeded `queued` run: leg 1 pauses at
    `waiting_approval`, leg 2 resumes with approval and dispatches the write
    through the ledger."""
    with _worker_bound_to_juli_app(
        monkeypatch, factory, app_sync_sessionmaker, products, _RUN_LEG_SCRIPT
    ):
        await agent_workflow._run_agent_workflow_async(str(run_id))
    with _worker_bound_to_juli_app(
        monkeypatch, factory, app_sync_sessionmaker, products, _RESUME_LEG_SCRIPT
    ):
        await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)


# ---------------------------------------------------------------------------
# The one string coupling this slice relies on, pinned.
# ---------------------------------------------------------------------------


def test_the_ledgers_terminal_vocabulary_is_the_recorders_terminal_vocabulary():
    """`WorkflowRunner` reports the ledger's own terminal state
    (`LedgerStatus`) as `record_workflow_outcome`'s `execution_status`, which
    `_realtime_execution_status` compares against `TERMINAL_SUCCEEDED`.
    `LedgerStatus`'s docstring calls the two vocabularies "string-compatible
    with, but deliberately distinct from" each other — this pins the
    compatibility half, so a rename on either side fails here instead of
    silently recording every write as a failure."""
    assert LedgerStatus.SUCCEEDED.value == TERMINAL_SUCCEEDED
    assert LedgerStatus.FAILED.value == TERMINAL_FAILED


# ---------------------------------------------------------------------------
# AC1 — a succeeded agent write leaves exactly one outcome row, and the chain
#       reports the state-change link populated.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_a_succeeded_write_records_an_outcome_the_chain_can_join(
    owner_engine, app_sync_sessionmaker, monkeypatch
):
    """RED on the pre-fix code: the ledger never called the recorder, so the
    join returns zero rows and `load_outcome_chain` reports the state-change
    link as `missing` ("a write completed ... but no workflow_outcome_records
    row joins to it on execution_id")."""
    run_id, shop_id, _ = _seed_queued_run(owner_engine)
    products = _FakeProductsResource()

    async with juli_app_async_sessionmaker() as factory:
        await _drive_write_to_completion(
            monkeypatch, factory, app_sync_sessionmaker, products, run_id
        )

        finished = _run_row(owner_engine, run_id)
        assert finished is not None
        assert finished.status == WorkflowRunStatus.COMPLETED.value, (
            f"the run must have completed before its outcome is judged; it is "
            f"{finished.status!r} with stop_reason={finished.stop_reason!r}"
        )
        assert len(products.edit_calls) == 1, (
            f"the approved CONFIRM write must have dispatched exactly once, got "
            f"{len(products.edit_calls)}"
        )

        rows = _outcome_rows(owner_engine, run_id)
        assert len(rows) == 1, (
            f"a completed agent write must leave exactly one workflow_outcome_records "
            f"row joined on execution_id, got {len(rows)}"
        )
        assert rows[0].ledger_status == "succeeded", (
            f"the joined ledger row must be the succeeded write, got {rows[0].ledger_status!r}"
        )
        assert rows[0].execution_status == "succeeded", (
            f"the recorded outcome must carry the write's own terminal status, got "
            f"{rows[0].execution_status!r}"
        )
        assert rows[0].workflow_id == WORKFLOW_KEY, (
            f"the recorded workflow_id must be the playbook's own WORKFLOW_KEY "
            f"({WORKFLOW_KEY!r}), never the prompt-directory name, got "
            f"{rows[0].workflow_id!r}"
        )
        metrics = json.loads(rows[0].metrics_json)
        assert metrics["workflow_id"] == WORKFLOW_KEY, (
            "the metrics envelope must be the one build_workflow_outcome_metrics "
            f"builds for this workflow, got {metrics.get('workflow_id')!r}"
        )

        # The chain is the consumer this slice exists to serve, and it must
        # read the row back as `juli_app` under the run's own shop scope.
        async with factory() as session:
            async with with_sticky_shop_scope(session, shop_id):
                chain = await load_outcome_chain(session, run_id)

    assert isinstance(chain.state_change, StateChangeLink), (
        "the chain's state-change link must be POPULATED after a completed agent "
        f"write, got an empty link: {chain.state_change}"
    )
    assert [r.execution_status for r in chain.state_change.records] == ["succeeded"], (
        f"the populated link must carry this write's own record, got {chain.state_change.records}"
    )


# ---------------------------------------------------------------------------
# AC2 — the replayed write records exactly one outcome (the recorder's own
#       idempotency, not a re-implementation).
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_a_replayed_write_records_exactly_one_outcome(owner_engine, app_sync_sessionmaker):
    """The REAL ledger and the REAL recorder, paired exactly as the runner
    pairs them, over one unchanged idempotency key twice.

    The second `execute_write` takes `_resolve_existing`'s `succeeded` branch
    and makes ZERO vendor calls; the second `record` finds the existing row
    through `record_workflow_outcome`'s own `get_by_execution_id` and inserts
    nothing.
    """
    run_id, shop_id, tiktok_product_id = _seed_queued_run(owner_engine)
    vendor_calls: list[str] = []

    def _perform() -> dict[str, Any]:
        vendor_calls.append("edit")
        return {"ok": True, "updated": True}

    async with juli_app_async_sessionmaker() as factory:
        recorder = LedgerWriteOutcomeRecorder(_scoped_factory(factory, shop_id), shop_id=shop_id)
        sync_session = app_sync_sessionmaker()
        try:
            with with_sticky_shop_scope_sync(sync_session, shop_id):
                ledger = ToolExecutionLedger(
                    sync_session, shop_id=shop_id, workflow_id=WORKFLOW_KEY
                )
                for _ in range(2):
                    ledger.execute_write(
                        workflow_run_id=run_id,
                        tool_call_id="c-replay",
                        operation="update_product_listing",
                        perform=_perform,
                        request_payload=ToolExecutionRequestPayload(product_id=tiktok_product_id),
                    )
                    await recorder.record(
                        workflow_run_id=run_id,
                        tool_call_id="c-replay",
                        operation="update_product_listing",
                        execution_status="succeeded",
                    )
        finally:
            sync_session.close()

    assert vendor_calls == ["edit"], (
        f"the replay must make ZERO vendor calls (the ledger replays its stored "
        f"result), got {vendor_calls}"
    )
    rows = _outcome_rows(owner_engine, run_id)
    assert len(rows) == 1, (
        f"the replayed write must leave exactly one outcome row — the recorder's own "
        f"read-then-insert idempotency — got {len(rows)}"
    )


# ---------------------------------------------------------------------------
# AC3 — a FAILED write records an outcome too. Stated decision: YES.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_a_failed_write_records_what_the_pr_says_it_does(
    owner_engine, app_sync_sessionmaker, monkeypatch
):
    """DECISION, stated in the PR and asserted here: a failed write DOES
    record an outcome, mirroring the legacy caller
    (`services/execution/worker.py`, which passes `execution_status` and
    `error_message` on its failure path).

    The record carries `execution_status='failed'` and the envelope's realtime
    cadence renders the failure — it never claims the write succeeded. The
    chain's state-change link therefore reads POPULATED with a failed record
    rather than `unavailable`; the record's own status is what says what
    happened.
    """
    run_id, shop_id, _ = _seed_queued_run(owner_engine)
    products = _FakeProductsResource(edit_error=RuntimeError("vendor rejected the edit"))

    async with juli_app_async_sessionmaker() as factory:
        with _worker_bound_to_juli_app(
            monkeypatch, factory, app_sync_sessionmaker, products, _RUN_LEG_SCRIPT
        ):
            await agent_workflow._run_agent_workflow_async(str(run_id))
        with _worker_bound_to_juli_app(
            monkeypatch, factory, app_sync_sessionmaker, products, _RESUME_LEG_SCRIPT
        ):
            await agent_workflow._resume_agent_workflow_async(str(run_id), approved=True)

    assert len(products.edit_calls) == 1, (
        f"the write must have been attempted exactly once, got {len(products.edit_calls)}"
    )
    rows = _outcome_rows(owner_engine, run_id)
    assert len(rows) == 1, (
        f"a failed agent write must leave exactly one outcome row recording the "
        f"failure, got {len(rows)}"
    )
    assert rows[0].ledger_status == "failed", (
        f"the joined ledger row must be the failed write, got {rows[0].ledger_status!r}"
    )
    assert rows[0].execution_status == "failed", (
        f"the recorded outcome must say the write failed, got {rows[0].execution_status!r}"
    )
    realtime = json.loads(rows[0].metrics_json)["cadences"][0]
    assert "vendor rejected the edit" in realtime["execution_status"], (
        "the realtime cadence must carry the vendor's own error message, got "
        f"{realtime['execution_status']!r}"
    )


# ---------------------------------------------------------------------------
# The absent-key case — the DEFAULT before this slice, not an edge.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_a_write_whose_payload_carries_no_workflow_id_is_skipped_not_raised(
    owner_engine, app_sync_sessionmaker
):
    """A ledger constructed with no `workflow_id` — every legacy row, and
    every row written before this slice — leaves `payload_json` without the
    key `extract_workflow_id` demands. The recorder must SKIP AND LOG, never
    let the resulting `ValueError` escape into the write path: the accounting
    must never kill an otherwise-successful write.
    """
    run_id, shop_id, tiktok_product_id = _seed_queued_run(owner_engine)

    async with juli_app_async_sessionmaker() as factory:
        recorder = LedgerWriteOutcomeRecorder(_scoped_factory(factory, shop_id), shop_id=shop_id)
        sync_session = app_sync_sessionmaker()
        try:
            with with_sticky_shop_scope_sync(sync_session, shop_id):
                ledger = ToolExecutionLedger(sync_session, shop_id=shop_id)
                result = ledger.execute_write(
                    workflow_run_id=run_id,
                    tool_call_id="c-legacy",
                    operation="update_product_listing",
                    perform=lambda: {"ok": True},
                    request_payload=ToolExecutionRequestPayload(product_id=tiktok_product_id),
                )
                await recorder.record(
                    workflow_run_id=run_id,
                    tool_call_id="c-legacy",
                    operation="update_product_listing",
                    execution_status="succeeded",
                )
        finally:
            sync_session.close()

    assert result == {"ok": True}, (
        "the write itself must be unaffected by the accounting that follows it"
    )
    assert _outcome_rows(owner_engine, run_id) == [], (
        "a payload with no workflow_id records nothing — skip and log, never raise"
    )


# ---------------------------------------------------------------------------
# The fail-closed unverifiable case — ADR-073 decision 3.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_an_unverifiable_write_still_fails_closed_and_records_no_new_claim(
    owner_engine, app_sync_sessionmaker
):
    """A `failed` row found on retry with no `verify_applied` read-back is
    ADR-073 decision 3's "never a maybe-duplicate write": the ledger marks it
    failed again and raises `ToolExecutionUnrecoverableError`.

    Adding the recorder must not swallow, delay or alter that raise — and the
    unverifiable attempt records nothing of its own, because the ledger does
    not know what happened and an outcome row would claim more certainty than
    it has.
    """
    run_id, shop_id, tiktok_product_id = _seed_queued_run(owner_engine)

    def _perform_that_fails() -> dict[str, Any]:
        raise RuntimeError("vendor timed out")

    async with juli_app_async_sessionmaker() as factory:
        recorder = LedgerWriteOutcomeRecorder(_scoped_factory(factory, shop_id), shop_id=shop_id)
        sync_session = app_sync_sessionmaker()
        try:
            with with_sticky_shop_scope_sync(sync_session, shop_id):
                ledger = ToolExecutionLedger(
                    sync_session, shop_id=shop_id, workflow_id=WORKFLOW_KEY
                )
                with pytest.raises(RuntimeError, match="vendor timed out"):
                    ledger.execute_write(
                        workflow_run_id=run_id,
                        tool_call_id="c-unverifiable",
                        operation="update_product_listing",
                        perform=_perform_that_fails,
                        request_payload=ToolExecutionRequestPayload(product_id=tiktok_product_id),
                    )
                await recorder.record(
                    workflow_run_id=run_id,
                    tool_call_id="c-unverifiable",
                    operation="update_product_listing",
                    execution_status="failed",
                    error_message="vendor timed out",
                )
                recorded_after_failure = _outcome_rows(owner_engine, run_id)

                with pytest.raises(ToolExecutionUnrecoverableError):
                    ledger.execute_write(
                        workflow_run_id=run_id,
                        tool_call_id="c-unverifiable",
                        operation="update_product_listing",
                        perform=_perform_that_fails,
                        request_payload=ToolExecutionRequestPayload(product_id=tiktok_product_id),
                    )
        finally:
            sync_session.close()

    assert len(recorded_after_failure) == 1, (
        "the first, genuinely-failed attempt records its own outcome"
    )
    rows = _outcome_rows(owner_engine, run_id)
    assert [r.id for r in rows] == [r.id for r in recorded_after_failure], (
        "the fail-closed unverifiable attempt must add no outcome of its own — the "
        "ledger does not know whether that write landed"
    )


# ---------------------------------------------------------------------------
# The chain before the fix, held as documentation of what `missing` meant.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_a_run_that_never_dispatched_a_write_still_reports_an_empty_link(
    owner_engine, app_sync_sessionmaker
):
    """W8's shipped semantics are unmoved: a run with no execution at all
    still carries an EXPLAINED empty link, never a null and never a spurious
    populated one."""
    run_id, shop_id, _ = _seed_queued_run(owner_engine)

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with with_sticky_shop_scope(session, shop_id):
                chain = await load_outcome_chain(session, run_id)

    assert isinstance(chain.state_change, EmptyLink), (
        f"a run with no dispatched write has no state change to report, got {chain.state_change}"
    )
    assert chain.state_change.reason is not None, "an empty link always carries its reason"


def _scoped_factory(factory, shop_id: uuid.UUID):
    """The production shape of the recorder's session seam: a fresh session
    per record, already holding a sticky shop scope — exactly what
    `agent_workflow._shop_scoped_session_factory` hands it."""

    @contextlib.asynccontextmanager
    async def _scoped():
        async with factory() as session:
            async with with_sticky_shop_scope(session, shop_id):
                yield session

    return _scoped
