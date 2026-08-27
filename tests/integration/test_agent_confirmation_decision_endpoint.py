"""Integration-tier proof for `POST /v1/demo/runs/{run_id}/confirmations/
{tool_call_id}` (ADR-075 decision 2, issue #1224 / AGT-W5A): approve really
resumes the run, the write really dispatches, and the run reaches a
terminal state -- driven through the real HTTP route, a real
`run_confirmations` row, a fake LLM, and a spy `ToolExecutor`.

This is deliberately at HTTP + `WorkflowRunner` granularity, not
`WorkflowRunner.resume()` called directly from the test (the module
docstring's own framing for why this endpoint exists at all: "the live
write path proven on 2026-08-20 was driven by calling `WorkflowRunner
.resume` directly from a test, which proves the loop, not the product").
`resume_agent_workflow.delay` is monkeypatched to schedule the same
`WorkflowRunner.resume` call a real Celery worker would make (fresh
session, fresh runner, fresh spy/fake-LLM) as a background `asyncio` task
rather than actually going through Celery/Redis -- the endpoint's own
enqueue call site is exercised for real; only the broker is stood in for.

Runs against the shared `tests/integration/conftest.py` SQLite `engine`
fixture (this file needs no Postgres-specific constraint behavior -- that
is `test_agent_confirmation_decision_postgres.py`'s job).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from juli_backend.models.models import Product, RunConfirmation, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.terminal import register_terminal_tools

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared doubles / helpers (mirrors tests/unit/test_agent_runner_pause_resume.py)
# ---------------------------------------------------------------------------


class _SpyToolExecutor:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append((tool_name, params))
        return dict(self._result)


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    register_terminal_tools(registry)
    return registry


def _single_confirm_playbook() -> Playbook:
    """A minimal playbook, sharing the real `optimize_product_2` workflow
    key/version/termination policy, naming just the one CONFIRM write step
    this suite drives -- same convention `test_agent_runner_pause_resume.py
    ::_pause_resume_playbook` established."""
    return Playbook(
        workflow_key=OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key,
        version=OPTIMIZE_PRODUCT_PLAYBOOK.version,
        steps=(
            PlaybookStep(
                step_id="5",
                intent="Publish the improved listing, once the seller approves.",
                tools=("update_product_listing",),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=replace(
            OPTIMIZE_PRODUCT_TERMINATION_POLICY, terminal_tools=()
        ),  # ADR-088: narrowed playbook registers no terminal tool
    )


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


def _stamped_prompt_pin() -> tuple[str, str]:
    """The production-pinned `(prompt_version, prompt_sha256)` for the
    Optimize Product workflow, matching what approval.py::approve_action_card
    stamps on run creation. Used by fixtures that construct WorkflowRunRow
    instances directly rather than via the real approval path."""
    from juli_backend.services.agent import playbooks as playbooks_module
    from juli_backend.services.agent import prompts as prompts_module

    workflow_key = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    version = prompts_module.production_version(workflow_key)
    return (
        prompts_module.prompt_version(workflow_key, version),
        prompts_module.prompt_sha256(workflow_key, version),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, factory: async_sessionmaker):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _session_dependency():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _session_dependency
    yield application
    application.dependency_overrides.clear()


async def _seed_shop_product(factory: async_sessionmaker) -> tuple[Shop, Product]:
    async with factory() as session:
        user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
        shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-W5A #1224 Integration Shop")
        product = Product(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_product_id="agt-1224-integration-1",
            name="Test Product",
            status="active",
            update_time=datetime.now(UTC),
        )
        session.add_all([user, shop, product])
        await session.commit()
        return shop, product


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# AC (#1224): approve -> the run resumes, the write dispatches, and the run
# reaches a terminal state -- fake LLM + spy executor
# ---------------------------------------------------------------------------


class TestApproveResumesDispatchesAndReachesTerminalState:
    async def test_approve_dispatches_the_write_exactly_once_and_completes(
        self, engine: AsyncEngine, factory: async_sessionmaker, app
    ):
        shop, product = await _seed_shop_product(factory)

        # --- Phase 1: drive a real WorkflowRunner to the CONFIRM pause,
        # exactly what `WorkflowRunner._pause_pending_confirmation` does in
        # production -- this is what leaves behind the real `workflow_runs`
        # row (waiting_approval) and the real `run_confirmations` row
        # (pending) the endpoint under test authorizes against. ------------
        async with factory() as session:
            prompt_version, prompt_sha256 = _stamped_prompt_pin()
            run = WorkflowRunRow(
                id=uuid.uuid4(),
                shop_id=shop.id,
                product_id=product.id,
                state=RunState().to_dict(),
                status="running",
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
            )
            session.add(run)
            await session.flush()
            run_id = run.id

            spy_pause = _SpyToolExecutor()
            llm_pause = FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c-listing",
                            tool_name="update_product_listing",
                            arguments={"title": "New improved title"},
                        )
                    )
                ]
            )
            runner_pause = WorkflowRunner(
                llm_service=llm_pause,
                tool_executor=spy_pause,
                event_sink=InMemoryEventSink(),
                conversation_store=JsonbConversationStore(session),
                registry=_full_registry(),
                playbook=_single_confirm_playbook(),
            )
            result_pause = await runner_pause.run(run_id, product_ref=product.tiktok_product_id)
            assert result_pause.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
            assert spy_pause.calls == [], (
                "the CONFIRM call must never reach the executor pre-approval"
            )
            await session.commit()

        # --- Phase 2: wire the endpoint's enqueue call site to a real
        # (background-task) resume, then hit the real HTTP route. ----------
        pending_tasks: list[asyncio.Task] = []
        spy_resume = _SpyToolExecutor(
            result={"title": "New improved title", "image_attached": False}
        )
        resume_results: list[Any] = []

        async def _do_resume(target_run_id: uuid.UUID, approved: bool) -> None:
            async with factory() as resume_session:
                runner_resume = WorkflowRunner(
                    llm_service=FakeLLMService(
                        script=[_turn(FinalResponse(content="Listing updated, all done."))]
                    ),
                    tool_executor=spy_resume,
                    event_sink=InMemoryEventSink(),
                    conversation_store=JsonbConversationStore(resume_session),
                    registry=_full_registry(),
                    playbook=_single_confirm_playbook(),
                )
                result = await runner_resume.resume(target_run_id, approved=approved)
                await resume_session.commit()
                resume_results.append(result)

        mock_task = MagicMock()

        def _delay_side_effect(run_id_str: str, approved: bool):
            pending_tasks.append(asyncio.ensure_future(_do_resume(uuid.UUID(run_id_str), approved)))
            async_result = MagicMock()
            async_result.id = "celery-task-id-1224-integration"
            return async_result

        mock_task.delay.side_effect = _delay_side_effect

        # Look up the option_id the pause actually wrote (binary confirm's
        # single option, "1" by construction -- resolved from the DB rather
        # than hardcoded, so this test would fail loudly if that ever changed).
        async with factory() as session:
            confirmation = (
                (
                    await session.execute(
                        select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                    )
                )
                .scalars()
                .first()
            )
            assert confirmation is not None
            option_id = confirmation.options[0]["option_id"]
            tool_call_id = confirmation.tool_call_id

        with patch("juli_backend.workers.tasks.agent_workflow.resume_agent_workflow", mock_task):
            async with _client_for(app, User(id=shop.user_id), shop) as client:
                resp = await client.post(
                    f"/v1/demo/runs/{run_id}/confirmations/{tool_call_id}",
                    json={"decision": "approve", "option_id": option_id},
                )

        assert resp.status_code == 202
        mock_task.delay.assert_called_once_with(str(run_id), True)

        # Let the "worker" (background task standing in for Celery) finish.
        await asyncio.gather(*pending_tasks)

        # --- AC: the write dispatched exactly once, with the approved params
        assert [call[0] for call in spy_resume.calls] == ["update_product_listing"]

        # --- AC: the run reaches a terminal state
        assert len(resume_results) == 1
        assert resume_results[0].stop_reason == StopReason.FINAL_RESPONSE
        assert resume_results[0].status == WorkflowRunStatus.COMPLETED

        async with factory() as session:
            refreshed_run = await session.get(WorkflowRunRow, run_id)
            assert refreshed_run is not None
            assert refreshed_run.status == "completed"
            assert refreshed_run.stop_reason == "final_response"

            confirmation_row = (
                (
                    await session.execute(
                        select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                    )
                )
                .scalars()
                .first()
            )
            assert confirmation_row.status == "approved"
            assert confirmation_row.selected_option_id == option_id


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
