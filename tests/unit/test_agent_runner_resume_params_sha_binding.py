"""`WorkflowRunner.resume()`'s own consent-binding re-verification (ADR-075
decision 2, issue #1224 review round 2).

Round 1 shipped consent binding only at `api/routes/agent_runs.py`'s
confirmation-authorization endpoint -- correct as far as it went, but ADR-075
decision 2 attributes the re-hash to "the resume task" itself, and Review
flagged that a check living solely at the endpoint holds only because that
endpoint happens to be `resume_agent_workflow`'s sole enqueuer today, not
because `WorkflowRunner.resume()` enforces it as its own invariant. #1225 is
about to add a second driver of this method (the decline branch); a security
control whose soundness depends on "there is exactly one caller" is not a
structural guarantee.

This suite drives `WorkflowRunner.resume(approved=True)` **directly** --
never through the HTTP endpoint -- with a `state.pending_confirmation`
carrying a `params_sha` that the confirmation-authorization endpoint would
have stamped onto it after its own validation (`agent_runs.py`'s approve
branch: `pending_state["params_sha"] = expected_params_sha`, written before
`resume_agent_workflow` is enqueued). `WorkflowRunner` has no database access
beyond `ConversationStore` (`core.py`'s own opening docstring) -- this stamped
value is the ONLY channel by which `resume()` can independently re-derive and
compare "what was consented to" against "what is about to execute", entirely
from state it already loads.

AC -> test map:
- a `params_sha` mismatch never executes the tool, proven with a spy
  executor recording zero calls (not a log line, not a status check alone)
  -> `test_mismatched_params_sha_executes_nothing`
- the run reaches a real terminal state on mismatch, not a hang or an
  uncaught exception -> same test, `result.stop_reason`/`result.status`
  assertions
- a MATCHING `params_sha` still executes normally (this is a
  re-verification, not a new blanket refusal) -> `test_matching_params_sha_still_executes`
- a resume call that never had endpoint-level consent binding at all (no
  `params_sha` key present -- every existing caller of this method before
  this slice, including this repo's own `test_agent_runner_pause_resume.py`)
  is unaffected: a true no-op, not a new failure -> `test_absent_params_sha_is_a_true_noop`
- RED proof: the mismatch check is reproduced as failing-for-the-right-reason
  against a monkeypatched version of `WorkflowRunner.resume` with the check
  disabled, proving the test itself would catch a regression that silently
  removed the check -> `test_red_proof_the_check_actually_gates_dispatch`
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.confirmation import compute_params_sha
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

pytestmark = pytest.mark.asyncio

PROPOSED_CHANGE = {"title": "New improved title"}


class _SpyToolExecutor:
    """Records every `execute` call it receives -- the "spy executor
    recording zero calls" the acceptance criterion names explicitly,
    rather than a log-line or status-only proof."""

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
    return registry


def _single_confirm_playbook() -> Playbook:
    return Playbook(
        workflow_key="optimize_product_2",
        version=1,
        steps=(
            PlaybookStep(
                step_id="5",
                intent="Publish the improved listing, once the seller approves.",
                tools=("update_product_listing",),
                policy=ToolPolicy.CONFIRM,
            ),
        ),
        termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    )


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


@pytest_asyncio.fixture
async def shop_and_product(session: AsyncSession) -> tuple[Shop, Product]:
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="AGT-W5A #1224 Resume Binding Shop")
    session.add(shop)
    await session.flush()
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=f"agt-1224-resume-{uuid.uuid4()}",
        name="Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    session.add(product)
    await session.flush()
    await session.commit()
    return shop, product


async def _seed_run_at_pause(
    session: AsyncSession,
    shop: Shop,
    product: Product,
    *,
    arguments: dict[str, Any],
    confirmed_params_sha: str | None,
) -> uuid.UUID:
    """Seeds a `workflow_runs` row already at `waiting_approval` with a
    `pending_confirmation` blob shaped exactly like a real CONFIRM pause
    would leave it, PLUS the `params_sha` key the confirmation-authorization
    endpoint's approve branch stamps on before enqueueing
    (`agent_runs.py::submit_confirmation_decision`) -- `None` to simulate a
    caller (or a pre-#1224-review-round-2 test) that never went through
    that endpoint at all.
    """
    pending_confirmation: dict[str, Any] = {
        "call_id": "call-listing-1",
        "tool_name": "update_product_listing",
        "arguments": arguments,
    }
    if confirmed_params_sha is not None:
        pending_confirmation["params_sha"] = confirmed_params_sha

    state = RunState(pending_confirmation=pending_confirmation)
    run = WorkflowRunRow(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=state.to_dict(),
        status="waiting_approval",
        prompt_version="optimize_product_2/v1",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.commit()
    return run.id


def _build_runner(
    session: AsyncSession, spy: _SpyToolExecutor, llm: FakeLLMService
) -> WorkflowRunner:
    return WorkflowRunner(
        llm_service=llm,
        tool_executor=spy,
        event_sink=InMemoryEventSink(),
        conversation_store=JsonbConversationStore(session),
        registry=_full_registry(),
        playbook=_single_confirm_playbook(),
    )


# ---------------------------------------------------------------------------
# AC: a params_sha mismatch never executes the tool -- spy executor, zero calls
# ---------------------------------------------------------------------------


async def test_mismatched_params_sha_executes_nothing(session: AsyncSession, shop_and_product):
    shop, product = shop_and_product
    # The confirmed hash reflects a DIFFERENT title than what `arguments`
    # (the run's reconstructed pending_confirmation) now names -- the exact
    # shape of drift ADR-075 decision 2 calls a hard failure.
    stale_confirmed_sha = compute_params_sha({"title": "A DIFFERENT title than what was shown"})
    run_id = await _seed_run_at_pause(
        session,
        shop,
        product,
        arguments=PROPOSED_CHANGE,
        confirmed_params_sha=stale_confirmed_sha,
    )

    spy = _SpyToolExecutor()
    llm = FakeLLMService(
        script=[]
    )  # must never be consumed -- mismatch refuses before any LLM call
    runner = _build_runner(session, spy, llm)

    result = await runner.resume(run_id, approved=True)

    assert spy.calls == [], "the tool must never execute on a params_sha mismatch"
    assert llm.recorded_calls == (), (
        "the LLM must never be re-entered either -- refused before dispatch"
    )
    assert result.stop_reason == StopReason.CONCURRENCY_CONFLICT
    assert result.status == WorkflowRunStatus.FAILED

    await session.refresh(run := await session.get(WorkflowRunRow, run_id))
    assert run.status == "failed"
    assert run.stop_reason == "concurrency_conflict"


# ---------------------------------------------------------------------------
# AC: a MATCHING params_sha still executes -- this is a re-verification,
# never a blanket new refusal
# ---------------------------------------------------------------------------


async def test_matching_params_sha_still_executes(session: AsyncSession, shop_and_product):
    shop, product = shop_and_product
    confirmed_sha = compute_params_sha(PROPOSED_CHANGE)
    run_id = await _seed_run_at_pause(
        session,
        shop,
        product,
        arguments=PROPOSED_CHANGE,
        confirmed_params_sha=confirmed_sha,
    )

    spy = _SpyToolExecutor(result={"title": "New improved title", "image_attached": False})
    llm = FakeLLMService(script=[_turn(FinalResponse(content="All done."))])
    runner = _build_runner(session, spy, llm)

    result = await runner.resume(run_id, approved=True)

    assert [call[0] for call in spy.calls] == ["update_product_listing"]
    assert result.stop_reason == StopReason.FINAL_RESPONSE
    assert result.status == WorkflowRunStatus.COMPLETED


# ---------------------------------------------------------------------------
# AC: no params_sha key present at all (every caller before this slice,
# including this repo's own pause/resume suite) is a true no-op
# ---------------------------------------------------------------------------


async def test_absent_params_sha_is_a_true_noop(session: AsyncSession, shop_and_product):
    shop, product = shop_and_product
    run_id = await _seed_run_at_pause(
        session,
        shop,
        product,
        arguments=PROPOSED_CHANGE,
        confirmed_params_sha=None,
    )

    spy = _SpyToolExecutor(result={"title": "New improved title", "image_attached": False})
    llm = FakeLLMService(script=[_turn(FinalResponse(content="All done."))])
    runner = _build_runner(session, spy, llm)

    result = await runner.resume(run_id, approved=True)

    assert [call[0] for call in spy.calls] == ["update_product_listing"]
    assert result.stop_reason == StopReason.FINAL_RESPONSE
    assert result.status == WorkflowRunStatus.COMPLETED


# ---------------------------------------------------------------------------
# RED proof: with the check disabled, the same mismatch DOES execute --
# demonstrating this test suite would have caught the pre-review-round-2 gap
# ---------------------------------------------------------------------------


async def test_red_proof_the_check_actually_gates_dispatch(
    session: AsyncSession, shop_and_product, monkeypatch
):
    """Monkeypatches `compute_params_sha` (as imported into `core.py`) to
    always agree with whatever it is compared against, simulating "the
    check is not really there" -- the exact regression this suite exists
    to catch. Asserts the spy DOES get called in that scenario, proving
    `test_mismatched_params_sha_executes_nothing` is not vacuously true
    (e.g. because nothing about this playbook ever reaches ToolExecutor
    regardless of the check)."""
    from juli_backend.services.agent.runner import core as core_module

    shop, product = shop_and_product
    stale_confirmed_sha = compute_params_sha({"title": "A DIFFERENT title than what was shown"})
    run_id = await _seed_run_at_pause(
        session,
        shop,
        product,
        arguments=PROPOSED_CHANGE,
        confirmed_params_sha=stale_confirmed_sha,
    )

    def _always_agrees(_arguments: dict[str, Any]) -> str:
        return stale_confirmed_sha

    monkeypatch.setattr(core_module, "compute_params_sha", _always_agrees)

    spy = _SpyToolExecutor(result={"title": "New improved title", "image_attached": False})
    llm = FakeLLMService(script=[_turn(FinalResponse(content="All done."))])
    runner = _build_runner(session, spy, llm)

    result = await runner.resume(run_id, approved=True)

    assert [call[0] for call in spy.calls] == ["update_product_listing"], (
        "with the check neutralized, the tool DOES execute -- confirming "
        "test_mismatched_params_sha_executes_nothing's failure would be for "
        "the right reason, not a fixture artifact"
    )
    assert result.stop_reason == StopReason.FINAL_RESPONSE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
