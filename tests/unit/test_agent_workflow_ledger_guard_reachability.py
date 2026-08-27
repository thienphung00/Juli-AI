"""Proves issue #1145's central claim: a WRITE tool dispatched through the
*real* `WorkflowRunner` (`services/agent/runner/core.py`) -- not a
hand-built dispatch loop -- genuinely reaches `ToolExecutionLedger`'s
claim-then-execute path (#1121) and `ConcurrencyGuard.check_before_write`
(#1122). Also proves the mirror image: a READ tool dispatched through the
same real `WorkflowRunner` never touches the ledger at all (ADR-073
decision 3).

**Why this is a separate suite from `test_agent_runner_ledger.py`/
`test_agent_runner_concurrency.py`.** Those two suites already prove the
ledger and guard are individually correct against a hand-built
`ProductToolExecutor.execute(...)` call. What they cannot prove -- because
neither one drives a `WorkflowRunner` -- is reachability: that the real
block-dispatch loop (`_dispatch_tool_call` / `resume`) actually threads
`tool_call_id` all the way through. That is exactly the regression #1145
exists to fix (`core.py` never passed `tool_call_id` into `execute`, and
nothing constructed a `ConcurrencyGuard` in the loop at all) and exactly
the regression that went unnoticed through thirteen reviewed slices. Every
test below constructs a real `WorkflowRunner` and drives it through
`run()`/`resume()`, exactly as `workers/tasks/agent_workflow.py`'s
`_construct_runner` would for a live task.

**How reachability is proven, not merely asserted.** Each test installs a
spy that *wraps* the real bound method (`ledger.execute_write`,
`guard.check_before_write`) -- the spy still calls straight through to the
real implementation, so the assertions on `products.update_prices_calls`
and the real `ToolExecution` row landing in the sync DB session prove the
real machinery ran, not just that some callable was invoked. A future
regression that stops threading `tool_call_id` (or stops constructing the
ledger/guard at all) fails these tests, not just a mock-count assertion
that could stay green after a real wiring break.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from juli_backend.integrations.tiktok.factories import (
    ProductionReadResources,
    SandboxWriteResources,
)
from juli_backend.models.models import Product, Shop, ToolExecution, User, WorkflowRun
from juli_backend.orm_base import Base
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.concurrency import (
    ConcurrencyGuard,
    capture_basis_snapshot,
    extract_mutable_fields,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.ledger import LedgerStatus, ToolExecutionLedger
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
from juli_backend.services.agent.status import StopReason
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools

_SQLITE_SCHEMA_TRANSLATE_MAP = {"ops": None, "bronze": None, "gold": None, "silver": None}


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _write_only_playbook() -> Playbook:
    """One CONFIRM WRITE step (`update_product_price`) -- CONFIRM because
    that's `update_product_price`'s own registered `ToolSpec.policy`
    (`product_write.py`); this drives the run through *both* of core.py's
    `tool_call_id`-threading call sites (`_dispatch_tool_call` refuses to
    dispatch a CONFIRM call directly, `resume` is what actually calls
    `execute` once approved)."""
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id="write",
                intent="Reprice the product.",
                tools=("update_product_price",),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=replace(
            OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()
        ),  # ADR-088: narrowed playbook registers no terminal tool
    )


def _read_only_playbook() -> Playbook:
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
        ),
        termination_policy=replace(
            OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()
        ),  # ADR-088: narrowed playbook registers no terminal tool
    )


def _base_raw(**overrides) -> dict:
    raw = {
        "title": "A widget",
        "description": "A fine widget for sale",
        "status": "LIVE",
        "skus": [
            {"id": "vendor-sku-1", "price": {"tax_exclusive_price": "10000", "currency": "VND"}}
        ],
        "main_images": [{"uri": "vendor-image-uri-1", "width": 800, "height": 800}],
    }
    raw.update(overrides)
    return raw


class _FakeProductsResource:
    """Mirrors `test_agent_runner_concurrency.py`'s own double -- a WRITE
    call mutates `_details` in place, like a real vendor apply would, so a
    post-write re-read reflects the write."""

    def __init__(self, *, details: dict) -> None:
        self._details = dict(details)
        self.get_details_calls: list[str] = []
        self.update_prices_calls: list[tuple[str, dict]] = []

    def get_details(self, product_id: str) -> dict:
        self.get_details_calls.append(product_id)
        return dict(self._details)

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        return {"products": []}

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        return {"products": []}

    def update_prices(self, *, product_id: str, body: dict) -> dict:
        self.update_prices_calls.append((product_id, body))
        by_id = {sku["id"]: sku for sku in body.get("skus", [])}
        skus = [dict(sku) for sku in self._details.get("skus", [])]
        for sku in skus:
            if sku.get("id") in by_id:
                new_price = by_id[sku["id"]]["price"]
                sku["price"] = {
                    "tax_exclusive_price": new_price["amount"],
                    "currency": new_price["currency"],
                }
        self._details = {**self._details, "skus": skus}
        return {}

    def edit(self, *, product_id: str, body: dict) -> dict:
        self._details = {**self._details, **body}
        return {}


def _read_resources(products: _FakeProductsResource) -> ProductionReadResources:
    return ProductionReadResources(
        authorization=None,  # type: ignore[arg-type]
        orders=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        returns=None,  # type: ignore[arg-type]
        inventory=None,  # type: ignore[arg-type]
        analytics=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _write_resources(products: _FakeProductsResource) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=None,  # type: ignore[arg-type]
        products=products,  # type: ignore[arg-type]
        fulfillment=None,  # type: ignore[arg-type]
        promotion=None,  # type: ignore[arg-type]
    )


def _sync_ledger_session():
    """A throwaway sync SQLite engine/session for `ToolExecutionLedger`,
    independent of the async engine the `WorkflowRun` row lives on --
    mirrors `ledger.py`'s own module docstring on why this seam is
    deliberately a plain `sqlalchemy.orm.Session`, and matches
    `workers/tasks/agent_workflow.py`'s `_sync_ledger_session`."""
    engine = create_engine(
        "sqlite:///:memory:",
        execution_options={"schema_translate_map": _SQLITE_SCHEMA_TRANSLATE_MAP},
    )
    Base.metadata.create_all(engine, checkfirst=True)
    return sessionmaker(bind=engine)()


async def _seed_run(session) -> tuple[uuid.UUID, uuid.UUID, str]:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Reachability Test Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-reach-1",
        name="Reach Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=RunState().to_dict(),
        status="running",
        prompt_version="optimize_product.v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id, shop.id, product.tiktok_product_id


class TestWriteReachesLedgerAndGuardThroughARealRun:
    """The regression #1145 exists to prevent: #1121's ledger and #1122's
    guard were correct and fully unit-tested in isolation, but provably
    unreachable from any real `WorkflowRunner` run."""

    async def test_confirm_write_reaches_ledger_claim_then_execute_and_guard_check(
        self, engine: AsyncEngine
    ):
        products = _FakeProductsResource(details=_base_raw())
        sync_session = _sync_ledger_session()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as seed_session:
            run_id, shop_id, product_ref = await _seed_run(seed_session)
            await seed_session.commit()

        async with factory() as session:
            ledger = ToolExecutionLedger(sync_session, shop_id=shop_id)
            guard = ConcurrencyGuard(
                basis_snapshot=capture_basis_snapshot(extract_mutable_fields(_base_raw()))
            )

            ledger_calls: list[dict] = []
            real_execute_write = ledger.execute_write

            def _spy_execute_write(**kwargs):
                ledger_calls.append({k: v for k, v in kwargs.items() if k != "perform"})
                return real_execute_write(**kwargs)

            ledger.execute_write = _spy_execute_write  # type: ignore[method-assign]

            guard_calls: list[dict] = []
            real_check_before_write = guard.check_before_write

            def _spy_check_before_write(**kwargs):
                guard_calls.append(kwargs)
                return real_check_before_write(**kwargs)

            guard.check_before_write = _spy_check_before_write  # type: ignore[method-assign]

            tool_executor = ProductToolExecutor(
                registry=_full_registry(),
                write_resources=_write_resources(products),
                product_id="p1",
                sku_refs={"S1": "vendor-sku-1"},
                ledger=ledger,
                workflow_run_id=run_id,
                concurrency_guard=guard,
            )
            runner = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[
                        _turn(
                            ToolCallBlock(
                                call_id="c1",
                                tool_name="update_product_price",
                                arguments={
                                    "skus": [
                                        {"sku_ref": "S1", "amount": "10000", "currency": "VND"}
                                    ]
                                },
                            )
                        ),
                        _turn(FinalResponse(content="Repriced.")),
                    ]
                ),
                tool_executor=tool_executor,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=_write_only_playbook(),
            )

            paused = await runner.run(run_id, product_ref=product_ref)
            assert paused.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION

            resumed = await runner.resume(run_id, approved=True)
            assert resumed.stop_reason == StopReason.FINAL_RESPONSE

        # --- guard: check_before_write was genuinely reached, exactly once ---
        assert len(guard_calls) == 1
        assert guard_calls[0]["operation"] == "update_product_price"

        # --- ledger: execute_write was genuinely reached, exactly once, with
        # the real tool_call_id core.py's `resume()` threaded through -----
        assert len(ledger_calls) == 1
        assert ledger_calls[0]["operation"] == "update_product_price"
        assert ledger_calls[0]["tool_call_id"] == "c1"
        assert ledger_calls[0]["workflow_run_id"] == run_id

        # --- the vendor write actually ran (perform() was reached) ---------
        assert products.update_prices_calls

        # --- the REAL ledger persisted a claim-then-execute row -- the
        # strongest proof this is the genuine ToolExecutionLedger machinery,
        # not just a function that happened to be called -------------------
        row = (
            sync_session.query(ToolExecution)
            .filter_by(workflow_run_id=run_id, tool_call_id="c1", operation="update_product_price")
            .one()
        )
        assert row.status == LedgerStatus.SUCCEEDED.value

        sync_session.close()


class TestReadToolNeverTouchesTheLedger:
    """ADR-073 decision 3: reads skip the ledger entirely -- proven here
    from a real `WorkflowRunner.run()`, not a hand-built `execute()` call."""

    async def test_read_only_run_makes_zero_ledger_calls_and_zero_rows(self, engine: AsyncEngine):
        products = _FakeProductsResource(details=_base_raw())
        sync_session = _sync_ledger_session()

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as seed_session:
            run_id, shop_id, product_ref = await _seed_run(seed_session)
            await seed_session.commit()

        async with factory() as session:
            ledger = ToolExecutionLedger(sync_session, shop_id=shop_id)
            ledger_calls: list[dict] = []
            real_execute_write = ledger.execute_write

            def _spy_execute_write(**kwargs):
                ledger_calls.append(kwargs)
                return real_execute_write(**kwargs)

            ledger.execute_write = _spy_execute_write  # type: ignore[method-assign]

            tool_executor = ProductToolExecutor(
                registry=_full_registry(),
                read_resources=_read_resources(products),
                product_id="p1",
                ledger=ledger,
                workflow_run_id=run_id,
            )
            runner = WorkflowRunner(
                llm_service=FakeLLMService(
                    script=[
                        _turn(
                            ToolCallBlock(
                                call_id="r1", tool_name="get_product_information", arguments={}
                            )
                        ),
                        _turn(FinalResponse(content="Here is the product.")),
                    ]
                ),
                tool_executor=tool_executor,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=_read_only_playbook(),
            )

            result = await runner.run(run_id, product_ref=product_ref)
            assert result.stop_reason == StopReason.FINAL_RESPONSE

        assert ledger_calls == []
        assert sync_session.query(ToolExecution).count() == 0
        sync_session.close()
