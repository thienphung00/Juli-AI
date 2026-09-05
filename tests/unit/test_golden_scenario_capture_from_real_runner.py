"""The committed scenario is produced by the tool, from the real runner (#1311 AC8).

    "At least one scenario is committed: captured by this tool from the real
    runner driven by the scripted-fake integration path, covering a confirm
    pause with two options and both continuations. **Hand-authored event JSON is
    not acceptable input** — if the tool cannot produce it, fix the tool."

So this module *generates* the committed fixture rather than asserting against a
file someone typed. The events come from `WorkflowRunner` — the real one —
driven by `FakeLLMService`, persisted through `PersistingEventSink` into real
`workflow_run_events` rows, and read back by `capture_run_as_scenario`. Nothing
in the scenario is authored here; the script says which tools the model calls,
and the runner decides what events that produces.

That distinction is the point of the criterion. A hand-written fixture encodes
what someone believed the runner emits. This one encodes what it emits, so when
the runner changes the fixture changes with it — and the regeneration check
below turns that into a visible diff instead of silent drift.

The two options are the two real answers to a confirm pause: approve and
decline. `resume(approved=True)` and `resume(approved=False)` are the same calls
the confirmation endpoint makes, so both continuations are real runner output.

The fixture is written on every run and compared to the committed copy. To
accept a change: run this test, inspect the diff, commit it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from juli_backend.models.models import Product, Shop, User, WorkflowRun
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from juli_backend.services.agent.golden_scenarios import (
    GoldenScenario,
    capture_run_as_scenario,
)
from juli_backend.services.agent.llm import FinalResponse, ToolCallBlock
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.prompts.composer import (
    production_version,
    prompt_sha256,
    prompt_version,
)
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import WorkflowRunner
from juli_backend.services.agent.runner.state import RunState
from juli_backend.services.agent.status import StopReason

# The scripted-fake building blocks already used to drive the real runner to a
# confirm pause. Reused rather than re-created so this capture exercises the
# same path the pause/resume suite proves, instead of a lookalike.
from tests.unit.test_agent_runner_pause_resume import (
    _full_registry,
    _pause_resume_playbook,
    _SpyToolExecutor,
    _SteppingClock,
    _turn,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "golden_scenarios"
FIXTURE_PATH = FIXTURE_DIR / "optimize_product_confirm_pause.json"

WORKFLOW_KEY = _pause_resume_playbook().workflow_key


class _NullPublisher:
    """Publish is best-effort by contract (ADR-074 d.3); capture only needs the
    committed rows, so the Redis half is a no-op here."""

    async def publish(self, channel: str, message: str) -> None:
        return None


async def _seed_run(session) -> uuid.UUID:
    """A run stamped with the REAL production prompt identity.

    `prompt_sha256` is what the staleness command compares against, so seeding a
    placeholder would make the committed scenario permanently "stale" and the
    AC7 check meaningless on the one scenario that exists.
    """
    version = production_version(WORKFLOW_KEY)
    user = User(id=uuid.uuid4(), phone=f"+8490{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name="Golden Scenario Shop")
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="tt-golden-1",
        name="Golden Scenario Product",
        status="active",
        update_time=datetime.now(UTC),
    )
    run = WorkflowRun(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        state=RunState().to_dict(),
        status="running",
        prompt_version=prompt_version(WORKFLOW_KEY, version),
        prompt_sha256=prompt_sha256(WORKFLOW_KEY, version),
    )
    session.add_all([user, shop, product, run])
    await session.flush()
    await session.commit()
    return run.id


def _script() -> list[Any]:
    return [
        _turn(ToolCallBlock(call_id="c1", tool_name="get_product_information", arguments={})),
        _turn(
            ToolCallBlock(
                call_id="c2",
                tool_name="update_product_listing",
                arguments={"title": "Tiêu đề đã tối ưu"},
            )
        ),
        _turn(FinalResponse(content="Đã xong.")),
    ]


async def _run_to_confirm_pause(engine: AsyncEngine) -> tuple[uuid.UUID, async_sessionmaker]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        run_id = await _seed_run(session)

    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=_script()),
            tool_executor=_SpyToolExecutor(result={"title": "unused"}),
            event_sink=PersistingEventSink(factory, _NullPublisher()),
            conversation_store=JsonbConversationStore(session),
            registry=_full_registry(),
            playbook=_pause_resume_playbook(),
            clock=_SteppingClock(start=1000.0, step=2.0),
        )
        result = await runner.run(run_id, product_ref="prod-golden")
        assert result.stop_reason == StopReason.PAUSED_FOR_CONFIRMATION, (
            f"the script must reach a confirm pause; got {result.stop_reason}"
        )
        await session.commit()
    return run_id, factory


async def _resume(factory: async_sessionmaker, run_id: uuid.UUID, *, approved: bool) -> None:
    async with factory() as session:
        runner = WorkflowRunner(
            llm_service=FakeLLMService(script=_script()[2:]),
            tool_executor=_SpyToolExecutor(result={"title": "unused"}),
            event_sink=PersistingEventSink(factory, _NullPublisher()),
            conversation_store=JsonbConversationStore(session),
            registry=_full_registry(),
            playbook=_pause_resume_playbook(),
            clock=_SteppingClock(start=2000.0, step=2.0),
        )
        await runner.resume(run_id, approved=approved)
        await session.commit()


async def _capture(factory: async_sessionmaker, run_id: uuid.UUID) -> GoldenScenario:
    async with factory() as session:
        return await capture_run_as_scenario(session, run_id)


async def _build_scenario(engine: AsyncEngine) -> GoldenScenario:
    """Base = the run up to the pause. Continuations = what each answer adds.

    Three runs, because a run has one outcome: one supplies the shared prefix,
    and the other two supply the divergent tails. Taking the tail as
    `events[len(base):]` keeps the continuation to exactly what the answer
    caused, which is what `append_continuation` expects to append.
    """
    base_run_id, factory = await _run_to_confirm_pause(engine)
    base = await _capture(factory, base_run_id)

    approved_run_id, _ = await _run_to_confirm_pause(engine)
    await _resume(factory, approved_run_id, approved=True)
    approved = await _capture(factory, approved_run_id)

    declined_run_id, _ = await _run_to_confirm_pause(engine)
    await _resume(factory, declined_run_id, approved=False)
    declined = await _capture(factory, declined_run_id)

    n = len(base.events)
    return base.model_copy(
        update={
            "scenario_id": "optimize-product-confirm-pause",
            "continuations": {
                "approve": approved.events[n:],
                "decline": declined.events[n:],
            },
        }
    )


def _stable(scenario: GoldenScenario) -> dict[str, Any]:
    """Everything except `captured_at`, which is expected to move."""
    blob = json.loads(scenario.model_dump_json())
    blob.pop("captured_at", None)
    return blob


@pytest.mark.asyncio
async def test_the_committed_scenario_is_what_the_tool_produces(engine: AsyncEngine):
    """Regenerate and compare. A drift here is a real change in runner output."""
    scenario = await _build_scenario(engine)

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")

    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert _stable(GoldenScenario(**committed)) == _stable(scenario)


@pytest.mark.asyncio
async def test_it_covers_a_confirm_pause_with_two_options_and_both_continuations(
    engine: AsyncEngine,
):
    scenario = await _build_scenario(engine)

    assert scenario.events, "the base scenario is empty"
    assert set(scenario.continuations) == {"approve", "decline"}, (
        f"AC8 needs two options; got {sorted(scenario.continuations)}"
    )
    for option, events in scenario.continuations.items():
        assert events, f"continuation {option!r} is empty — the answer produced no events"

    approval_events = [
        e for e in scenario.events if e["event_type"] == "workflow.approval_required"
    ]
    assert approval_events, (
        "the base scenario does not reach a confirm pause, so neither continuation "
        "is reachable from it"
    )


@pytest.mark.asyncio
async def test_the_captured_scenario_carries_the_current_production_prompt(
    engine: AsyncEngine,
):
    """A fresh capture must read as current, or AC7's command is meaningless on
    the only scenario that exists."""
    from juli_backend.services.agent.golden_scenarios.staleness import check_scenarios

    scenario = await _build_scenario(engine)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")

    results = check_scenarios(FIXTURE_DIR)
    assert results, "the staleness scan found no scenarios"
    stale = [r for r in results if r.is_stale]
    assert not stale, f"a freshly captured scenario reads as stale: {stale}"


@pytest.mark.asyncio
async def test_no_raw_vendor_identifier_survives_capture(engine: AsyncEngine):
    """Asserted by scanning the serialized scenario, not by reading it."""
    scenario = await _build_scenario(engine)
    blob = scenario.model_dump_json()

    for forbidden in ("tt-golden-1", "prod-golden"):
        assert forbidden not in blob, (
            f"raw vendor identifier {forbidden!r} survived capture into the scenario"
        )
