"""The CONFIRM pause/resume round trip across a simulated worker-process
boundary — ADR-073 decisions 1 and 5, issue #1123 / AGT-W3A.

This is the deferred P-CS kill-and-resume gate in miniature (ADR-073
decision 6's phase-gate item): serialize `RunState` to the
`workflow_runs.state` JSONB blob at the moment a run enters
`waiting_approval`, then construct a **fresh** `WorkflowRunner` from the
blob alone -- sharing no in-process object with the runner that paused --
and drive it to a terminal `stop_reason`.

This slice is a test suite, not new production surface (issue #1123's own
framing): the pause/resume mechanics it proves live inside
`services/agent/runner/core.py` as a bug fix to #1119/#1120's
`WorkflowRunner` (a validated CONFIRM-policy `ToolCallBlock` used to
dispatch immediately, exactly like an AUTO one -- issue #1123 is what
teaches `_dispatch_tool_call` to pause instead, and adds the `resume`
entry point). No new production module is introduced.

**Why this suite is DB-backed against `JsonbConversationStore`, unlike
`test_agent_runner_core.py`/`test_agent_runner_termination.py`'s
`_InMemoryConversationStore` double.** Acceptance criterion: "this slice
exercises only the JSONB-blob `ConversationStore` implementation from
P1-2 -- assert no other storage backend ... is touched anywhere in this
test suite". An in-memory Python dict never round-trips through the real
`workflow_runs.state` JSONB column, so it cannot stand in for "a second
worker process reading the same row" the way `#1118`'s own
`test_conversation_store.py` precedent does: the shared `tests/unit/conftest.py`
`engine` fixture (sqlite+aiosqlite, `Base.metadata.create_all`) -- the same
fixture that suite uses to exercise the real column, without needing a
live Postgres instance. `TestOnlyTheJsonbConversationStoreIsUsed` below
pins that this file never reaches for anything else.

**How "no shared state with runner A" is proved, not just asserted by
scoping.** `_pause_runner_a` is a module-level async function: every
collaborator runner A used (its `WorkflowRunner`, `JsonbConversationStore`,
`InMemoryEventSink`, spy `ToolExecutor`, `ToolRegistry`, `AsyncSession`)
lives only in that function's local scope. It returns a `weakref.ref` to
runner A alongside plain data (`uuid.UUID`, `dict`, `int`) -- nothing that
could keep runner A's object graph reachable. The test forces `gc.collect()`
and asserts the weakref now resolves to `None` *before* constructing
runner B, so "runner B shares no reference with runner A" is a garbage-
collector fact the test observes, not a claim about code layout.
"""

from __future__ import annotations

import ast
import gc
import uuid
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from juli_backend.models.models import Product, RunConfirmation, Shop, User, WorkflowRun
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm import AssistantTurn, FinalResponse, ToolCallBlock, Usage
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.playbooks.base import Playbook, PlaybookStep
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import NoPendingConfirmationError, WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.runner.termination import running_seconds_column_value
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import ToolPolicy, ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools

TEST_MODULE_PATH = Path(__file__).resolve()
REPO_ROOT = TEST_MODULE_PATH.parents[2]
CORE_MODULE_PATH = REPO_ROOT / "backend/src/juli_backend/services/agent/runner/core.py"


# --- shared fixtures / doubles -----------------------------------------------


class _SteppingClock:
    """A controllable fake clock: each call returns the current value, then
    advances it by `step` -- no real sleeping anywhere. Mirrors
    `test_agent_runner_termination.py`'s own helper of the same name (not
    imported from there: that module is #1120's, out of this slice's
    write path)."""

    def __init__(self, *, step: float, start: float = 0.0) -> None:
        self._value = start
        self._step = step

    def __call__(self) -> float:
        value = self._value
        self._value += self._step
        return value


class _SpyToolExecutor:
    """Records every `execute` call it receives; returns a fixed result.
    Two independent instances (one per runner) never share `calls`."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._result = result if result is not None else {"ok": True}

    def execute(
        self, *, tool_name: str, params: Any, tool_call_id: str | None = None
    ) -> dict[str, Any]:
        # tool_call_id accepted-but-ignored (#1145): core.py now always
        # passes it; this spy's `.calls` assertions stay tool_name/params
        # shaped, unchanged from before #1145.
        self.calls.append((tool_name, params))
        return dict(self._result)


def _full_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _pause_resume_playbook() -> Playbook:
    """A minimal playbook sharing the real `optimize_product_2`
    workflow_key/version (so `compose()` resolves a real prose binding),
    naming one AUTO read step and one CONFIRM write step. `update_product_listing`'s
    own registered `ToolSpec.policy` is CONFIRM (`product_write.py`) --
    that is what actually gates the pause in `_dispatch_tool_call`, not the
    step-level `policy` value below (kept CONFIRM here too so the two
    never visibly disagree, per `PlaybookStep`'s own docstring)."""
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
        termination_policy=OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    )


def _turn(*blocks) -> AssistantTurn:
    return AssistantTurn(blocks=tuple(blocks), usage=Usage(input_tokens=1, output_tokens=1))


async def _seed_workflow_run(session: AsyncSession) -> uuid.UUID:
    """Mirrors `test_conversation_store.py::_seed_workflow_run` -- the same
    minimal shop/product/run fixture #1118's own suite seeds, not a new
    schema shape. `state` defaults to a fresh `RunState().to_dict()` blob
    via the `WorkflowRun` model's own column default."""
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Test Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-1",
        name="Test Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=RunState().to_dict(),
        status="running",
        prompt_version="v1",
        prompt_sha256="0" * 64,
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    return run.id


# --- pause phase: runner A, isolated in its own function scope ---------------


async def _pause_runner_a(
    engine: AsyncEngine,
) -> tuple[uuid.UUID, dict[str, Any], int, weakref.ReferenceType[WorkflowRunner]]:
    """Drive a scripted `WorkflowRunner` A to `waiting_approval`, persist
    its `RunState` through the real `JsonbConversationStore`, and return
    only plain data (a run id, a state-blob dict, an event count) plus a
    `weakref` to runner A itself.

    Every object runner A depended on -- the runner, its `ConversationStore`,
    `EventSink`, spy `ToolExecutor`, `ToolRegistry`, and `AsyncSession` --
    is a local variable of this function. None of them is returned, so
    once this coroutine completes there is no reachable reference to any
    of them anywhere the caller can see -- the caller's `gc.collect()` +
    weakref check (in the test below) confirms it.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session_a:
        run_id = await _seed_workflow_run(session_a)

        store_a = JsonbConversationStore(session_a)
        registry_a = _full_registry()
        sink_a = InMemoryEventSink()
        spy_a = _SpyToolExecutor(result={"title": "unused"})
        clock_a = _SteppingClock(start=1000.0, step=2.0)
        llm_a = FakeLLMService(
            script=[
                _turn(
                    ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})
                ),
                _turn(
                    ToolCallBlock(
                        call_id="c2",
                        tool_name="update_product_listing",
                        arguments={"title": "New improved title"},
                    )
                ),
                # A third scripted turn exists but must never be consumed --
                # the run pauses after the second (CONFIRM) tool call, it
                # does not proceed to a third LLM call in this process.
                _turn(FinalResponse(content="should never be reached by runner A")),
            ]
        )

        runner_a = WorkflowRunner(
            llm_service=llm_a,
            tool_executor=spy_a,
            event_sink=sink_a,
            conversation_store=store_a,
            registry=registry_a,
            playbook=_pause_resume_playbook(),
            clock=clock_a,
        )

        result_a = await runner_a.run(run_id, product_ref="prod-1")
        assert result_a.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION
        assert result_a.status == WorkflowRunStatus.WAITING_APPROVAL
        assert len(llm_a.recorded_calls) == 2  # the 3rd scripted turn, unconsumed
        # The AUTO call (get_product_information) dispatched normally; the
        # CONFIRM call (update_product_listing) never reached ToolExecutor.
        assert [call[0] for call in spy_a.calls] == ["get_product_information"]

        # AC1: the blob persisted at the moment of pause, read back through
        # the real JsonbConversationStore -- reusing #1118's to_dict/from_dict
        # round-trip guarantee as a precondition, not re-proving it here.
        state_at_pause = await store_a.load(run_id)
        state_at_pause_dict = state_at_pause.to_dict()
        event_count = len(sink_a.events)

        weak_runner_a = weakref.ref(runner_a)

        await session_a.commit()  # make the paused row durable for a fresh session to read

    return run_id, state_at_pause_dict, event_count, weak_runner_a


class TestPauseResumeRoundTrip:
    async def test_pause_then_fresh_runner_resumes_and_completes(self, engine: AsyncEngine):
        run_id, state_at_pause, event_count_a, weak_runner_a = await _pause_runner_a(engine)

        # --- structural proof: nothing about runner A is reachable anymore ---
        gc.collect()
        assert weak_runner_a() is None, (
            "runner A must be fully garbage-collected before runner B is "
            "constructed -- proof that runner B cannot share any Python "
            "object with it, only the persisted blob."
        )

        # --- AC1 (field-by-field), continued: the state runner A left behind ---
        assert state_at_pause["pending_confirmation"] == {
            "call_id": "c2",
            "tool_name": "update_product_listing",
            "arguments": {"title": "New improved title"},
        }
        # #1195: sequences are minted from 1, so after N events the next id is
        # N+1 (it was N when minting started at 0). The invariant under test is
        # "one id per emitted event, none skipped", not the literal number.
        assert state_at_pause["next_sequence"] == event_count_a + 1 == 5
        assert state_at_pause["running_seconds_elapsed"] == 4.0  # two 2.0s iterations
        pre_pause_conversation = list(state_at_pause["conversation_window"])
        # get_product_information (AUTO): proposal + result = 2 messages.
        # update_product_listing (CONFIRM): proposal only = 1 message --
        # its result is deferred to resume, never appended by runner A.
        assert len(pre_pause_conversation) == 3

        # --- construct WorkflowRunner B: a wholly fresh object graph, a
        # fresh DB session on the same engine, reading only the row's blob ---
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session_b:
            store_b = JsonbConversationStore(session_b)
            registry_b = _full_registry()
            sink_b = InMemoryEventSink()
            spy_b = _SpyToolExecutor(result={"ok": True})
            # A huge, unrelated base value -- stands in for "a very long
            # real-world pause elapsed before this worker picked the run
            # back up". If resume() ever measured elapsed time as the gap
            # between runner A's last clock reading and runner B's first,
            # running_seconds_elapsed would explode to roughly this size.
            clock_b = _SteppingClock(start=999_999.0, step=3.0)

            runner_b = WorkflowRunner(
                llm_service=FakeLLMService(script=[_turn(FinalResponse(content="All done."))]),
                tool_executor=spy_b,
                event_sink=sink_b,
                conversation_store=store_b,
                registry=registry_b,
                playbook=_pause_resume_playbook(),
                clock=clock_b,
            )

            # resume() receives nothing but the run id and the seller's
            # (already-authorized -- W4-A's job, not this module's) decision.
            result_b = await runner_b.resume(run_id, approved=True)

            # --- AC3: runner B reaches a terminal stop_reason from the blob alone ---
            assert result_b.stop_reason == StopReason.FINAL_RESPONSE
            assert result_b.status == WorkflowRunStatus.COMPLETED
            assert result_b.final_response == "All done."
            # The approved CONFIRM call, dispatched exactly once, by
            # runner B's own spy -- runner A's spy (spy_a) never saw it.
            assert len(spy_b.calls) == 1
            assert spy_b.calls[0][0] == "update_product_listing"

            # --- AC: next_sequence survives with no reset, no reuse ---
            # Runner B's first event continues from where A stopped: A emitted
            # `event_count_a` events numbered 1..event_count_a (#1195's 1-based
            # minting), so B starts at event_count_a + 1 -- never restarting at 1.
            first_resumed_sequence = event_count_a + 1
            assert sink_b.events[0].sequence_number == first_resumed_sequence
            all_sequences = [e.sequence_number for e in sink_b.events]
            assert all_sequences == sorted(all_sequences)  # strictly increasing, no reuse
            assert min(all_sequences) == first_resumed_sequence

            # --- AC: conversation continuity, verbatim, before any post-resume append ---
            resumed_state = await store_b.load(run_id)
            assert (
                resumed_state.conversation_window[: len(pre_pause_conversation)]
                == pre_pause_conversation
            )
            assert len(resumed_state.conversation_window) > len(pre_pause_conversation)

            # --- AC: the paused wall clock resumes from where it left off,
            # excluding the simulated real-world pause gap entirely ---
            assert resumed_state.running_seconds_elapsed == 7.0  # 4.0 (A) + 3.0 (B's one turn)
            # The clock_b gap (999_999.0 vs A's last reading, ~1006.0) is
            # roughly 998_993s -- nowhere near 7.0, so a bug that summed the
            # gap in would fail this assertion by five orders of magnitude.
            assert resumed_state.running_seconds_elapsed < 100.0

            assert resumed_state.pending_confirmation is None  # resolved, not carried forward


class TestRunningSecondsColumnExcludesThePauseInterval:
    """Issue #1216, AC: "A run that pauses for approval and resumes records
    elapsed time that excludes the paused interval -- proven with a
    controlled clock, not a sleep." `TestPauseResumeRoundTrip` above already
    proves this at the `RunState` float (`resumed_state.running_seconds_
    elapsed`); this class proves the same fact at the real
    `workflow_runs.running_seconds_elapsed` INTEGER column -- the thing an
    operator or a later slice would actually query, and the thing that
    stayed `0` on every real run before this issue's fix regardless of how
    the float behaved.

    Reuses `_pause_runner_a`'s exact scripted scenario (two 2.0s iterations
    before pausing, `clock_b` starting at `999_999.0` to stand in for "a
    very long real-world pause") so the numbers here are the same ones
    `TestPauseResumeRoundTrip` already pins at the float level -- 4.0 pre-
    pause, 7.0 post-resume -- cross-checked here against the column mirror.
    """

    async def test_column_reflects_pre_pause_value_then_excludes_the_pause_after_resume(
        self, engine: AsyncEngine
    ):
        run_id, state_at_pause, _event_count_a, weak_runner_a = await _pause_runner_a(engine)
        gc.collect()
        assert weak_runner_a() is None

        factory = async_sessionmaker(engine, expire_on_commit=False)

        # --- AC1 + AC3: the column already reflects the pre-pause running
        # time, non-zero, matching the pure mirror function applied to the
        # exact float the paused blob carries ---------------------------
        async with factory() as session_check:
            paused_row = await session_check.get(WorkflowRun, run_id)
            assert paused_row is not None
            assert paused_row.running_seconds_elapsed == running_seconds_column_value(
                state_at_pause["running_seconds_elapsed"]
            )
            assert paused_row.running_seconds_elapsed == 4  # two 2.0s iterations

        # --- resume: a huge simulated real-world pause gap (clock_b starts
        # at 999_999.0) must contribute nothing to the column ------------
        async with factory() as session_b:
            store_b = JsonbConversationStore(session_b)
            runner_b = WorkflowRunner(
                llm_service=FakeLLMService(script=[_turn(FinalResponse(content="All done."))]),
                tool_executor=_SpyToolExecutor(result={"ok": True}),
                event_sink=InMemoryEventSink(),
                conversation_store=store_b,
                registry=_full_registry(),
                playbook=_pause_resume_playbook(),
                clock=_SteppingClock(start=999_999.0, step=3.0),
            )
            result_b = await runner_b.resume(run_id, approved=True)
            assert result_b.stop_reason == StopReason.FINAL_RESPONSE

            # --- AC2: the terminal row's column excludes the pause entirely,
            # read from the same session runner B just wrote through (no
            # commit needed -- mirrors how `resumed_state` is read in
            # `TestPauseResumeRoundTrip` above) ----------------------------
            final_row = await session_b.get(WorkflowRun, run_id)
            assert final_row is not None
            assert final_row.running_seconds_elapsed == 7  # 4.0 (A) + 3.0 (B) -- never ~999,000
            assert final_row.running_seconds_elapsed < 100


class TestResumeDeclined:
    """`resume(approved=False)` -- not itself one of #1123's core five
    acceptance criteria, but the other half of the branch `resume` owns;
    covered here rather than left untested."""

    async def test_declined_confirmation_ends_the_run_without_dispatching_the_tool(
        self, engine: AsyncEngine
    ):
        run_id, _state_at_pause, event_count_a, weak_runner_a = await _pause_runner_a(engine)
        gc.collect()
        assert weak_runner_a() is None

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session_b:
            store_b = JsonbConversationStore(session_b)
            spy_b = _SpyToolExecutor()
            runner_b = WorkflowRunner(
                llm_service=FakeLLMService(script=[]),  # must never be called
                tool_executor=spy_b,
                event_sink=InMemoryEventSink(),
                conversation_store=store_b,
                registry=_full_registry(),
                playbook=_pause_resume_playbook(),
            )

            result_b = await runner_b.resume(run_id, approved=False)

            assert result_b.stop_reason == StopReason.CONFIRMATION_DECLINED
            assert result_b.status == WorkflowRunStatus.COMPLETED
            assert spy_b.calls == []  # declined -- never dispatched

            resumed_state = await store_b.load(run_id)
            assert resumed_state.pending_confirmation is None
            # decline emits exactly two events (tool.completed, workflow.completed),
            # continuing from runner A's next_sequence -- no reset, no reuse.
            # The +1 is #1195's 1-based minting base (see the pause assertion above).
            assert resumed_state.next_sequence == event_count_a + 2 + 1


class _CrashingToolExecutor:
    """Raises an unhandled exception from `execute` -- standing in for a
    worker process dying mid-dispatch (issue #1181 / AGT-W5A). Deliberately
    NOT one of `ConcurrencyExhaustedError`/`ToolExecutionUnrecoverableError`
    -- those are translated outcomes `resume()` already handles and
    persists a terminal row for; this is the *unhandled* crash case the
    review finding (1178-R2) is about, which `resume()` never catches."""

    def execute(self, *, tool_name: str, params: Any, tool_call_id: str | None = None) -> dict:
        raise RuntimeError("simulated worker crash mid-dispatch")


class TestResumeEntryPersistsOffWaitingApproval:
    """Issue #1181 / AGT-W5A, review finding 1178-R2: `resume()` must
    persist a status transition off `waiting_approval` at entry, before any
    tool dispatch or LLM call -- so a crash during resume's active phase
    (simulated here by a `ToolExecutor` that raises) is reaped by the
    5-minute `worker_lost` sweep rather than the 4-hour approval-expiry
    sweep. Proven by driving the real `resume()` and reading the row back
    mid-crash, not by asserting on `RunResult` (which the crash never
    produces)."""

    async def test_the_row_leaves_waiting_approval_before_the_crashing_dispatch_completes(
        self, engine: AsyncEngine
    ):
        run_id, _state_at_pause, _event_count_a, weak_runner_a = await _pause_runner_a(engine)
        gc.collect()
        assert weak_runner_a() is None

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session_b:
            paused_row = await session_b.get(WorkflowRun, run_id)
            assert paused_row is not None
            assert paused_row.status == WorkflowRunStatus.WAITING_APPROVAL.value

            store_b = JsonbConversationStore(session_b)
            runner_b = WorkflowRunner(
                llm_service=FakeLLMService(script=[]),  # never reached -- crash precedes it
                tool_executor=_CrashingToolExecutor(),
                event_sink=InMemoryEventSink(),
                conversation_store=store_b,
                registry=_full_registry(),
                playbook=_pause_resume_playbook(),
            )

            try:
                await runner_b.resume(run_id, approved=True)
            except RuntimeError:
                pass
            else:
                raise AssertionError("expected the simulated crash to propagate out of resume()")

            # The crash happened inside the approve branch's dispatch, well
            # after resume()'s entry -- if the entry persist ran first (the
            # fix), the row already reads `running`, not `waiting_approval`,
            # despite resume() never reaching a terminal exit at all.
            crashed_row = await session_b.get(WorkflowRun, run_id)
            assert crashed_row is not None
            assert crashed_row.status == WorkflowRunStatus.RUNNING.value
            assert crashed_row.stop_reason is None
            assert crashed_row.completed_at is None


class TestResumeWithNoPendingConfirmationRaises:
    async def test_resuming_a_run_that_was_never_paused_raises(self, engine: AsyncEngine):
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            run_id = await _seed_workflow_run(session)
            store = JsonbConversationStore(session)
            runner = WorkflowRunner(
                llm_service=FakeLLMService(script=[]),
                tool_executor=_SpyToolExecutor(),
                event_sink=InMemoryEventSink(),
                conversation_store=store,
                registry=_full_registry(),
                playbook=_pause_resume_playbook(),
            )

            try:
                await runner.resume(run_id, approved=True)
            except NoPendingConfirmationError:
                pass
            else:
                raise AssertionError("expected NoPendingConfirmationError")


# --- AC7: only the JSONB-blob ConversationStore is exercised anywhere here ---


class TestOnlyTheJsonbConversationStoreIsUsed:
    def test_no_alternate_storage_backend_is_imported_in_this_module(self):
        """AST-scoped to actual `import`/`from ... import` statements --
        not a bare text `"redis" not in source` grep, which would
        false-positive on this very test's own name."""
        tree = ast.parse(TEST_MODULE_PATH.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        assert not any("redis" in mod.lower() for mod in imported_modules)

    def test_the_only_conversation_store_constructed_in_this_module_is_jsonb(self):
        tree = ast.parse(TEST_MODULE_PATH.read_text(encoding="utf-8"))
        constructed = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        store_calls = {name for name in constructed if "ConversationStore" in name}
        assert store_calls == {"JsonbConversationStore"}


# --- AC: no bare policy literal crept into the new pause/resume code path ----


class TestNoHardcodedPolicyLiteralInResumePath:
    """Same guard `test_agent_runner_termination.py::TestNoHardcodedPolicyLiterals`
    already runs over the whole of `core.py` (which now includes `resume`
    and the pause helpers this issue added) -- re-asserted here, scoped to
    this issue's own concern, so this file documents the guarantee locally
    rather than relying entirely on a sibling issue's test file."""

    def test_core_module_still_contains_no_forbidden_policy_literal(self):
        forbidden = frozenset({6, 8, 300, 4})
        tree = ast.parse(CORE_MODULE_PATH.read_text(encoding="utf-8"))
        found = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
            and node.value in forbidden
        }
        assert found == set()


# --- AC: decision requests are recorded at the pause (issue #1221 / AGT-W5A) -


class TestDecisionRequestRecordedAtPause:
    """ADR-075 decision 2 acceptance criteria, proven through the real
    `WorkflowRunner` pause path (not just `JsonbConversationStore.persist`
    in isolation -- `test_conversation_store.py`'s own coverage) -- reuses
    `_pause_runner_a`'s exact scripted scenario: the CONFIRM tool is
    `update_product_listing`, called with `{"title": "New improved
    title"}`, `call_id="c2"`."""

    async def test_reaching_a_confirm_pause_writes_exactly_one_pending_row(
        self, engine: AsyncEngine
    ):
        run_id, _state_at_pause, _event_count_a, weak_runner_a = await _pause_runner_a(engine)
        gc.collect()
        assert weak_runner_a() is None

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                    )
                )
                .scalars()
                .all()
            )

            assert len(rows) == 1
            row = rows[0]
            assert row.tool_call_id == "c2"  # the CONFIRM call's own call_id
            assert row.status == "pending"
            assert row.selected_option_id is None
            assert row.decided_at is None

            # AC: exactly one option (binary confirm is the N=1 case), and
            # storage round-trips proposed_change byte-identically -- the
            # exact dict block.arguments carried, never re-derived through
            # update_product_listing's own input_model.
            assert len(row.options) == 1
            option = row.options[0]
            assert option["option_id"] == "1"
            assert option["proposed_change"] == {"title": "New improved title"}
            assert isinstance(option["rationale"], str) and option["rationale"]
            assert isinstance(option["params_sha"], str)
            assert len(option["params_sha"]) == 64
            int(option["params_sha"], 16)  # a real hex digest

    async def test_the_persisted_row_and_the_emitted_event_carry_the_same_options(
        self, engine: AsyncEngine
    ):
        """`build_confirmation_options` is called exactly once in
        `_pause_pending_confirmation` -- the event a seller sees and the
        row #1224 authorizes against must be the same construction, not
        two independently-computed values that could drift."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session_a:
            run_id = await _seed_workflow_run(session_a)
            store_a = JsonbConversationStore(session_a)
            sink_a = InMemoryEventSink()
            llm_a = FakeLLMService(
                script=[
                    _turn(
                        ToolCallBlock(
                            call_id="c1", tool_name="get_product_information", arguments={}
                        )
                    ),
                    _turn(
                        ToolCallBlock(
                            call_id="c2",
                            tool_name="update_product_listing",
                            arguments={"title": "New improved title"},
                        )
                    ),
                ]
            )
            runner_a = WorkflowRunner(
                llm_service=llm_a,
                tool_executor=_SpyToolExecutor(result={"title": "unused"}),
                event_sink=sink_a,
                conversation_store=store_a,
                registry=_full_registry(),
                playbook=_pause_resume_playbook(),
            )
            await runner_a.run(run_id, product_ref="prod-1")
            await session_a.commit()

            approval_events = [
                e for e in sink_a.events if e.event_type == "workflow.approval_required"
            ]
            assert len(approval_events) == 1
            event_options = approval_events[0].payload.options

        async with factory() as session_check:
            row = (
                (
                    await session_check.execute(
                        select(RunConfirmation).where(RunConfirmation.workflow_run_id == run_id)
                    )
                )
                .scalars()
                .one()
            )
            persisted_options = row.options

        assert len(event_options) == len(persisted_options) == 1
        assert event_options[0].model_dump(mode="json") == persisted_options[0]
