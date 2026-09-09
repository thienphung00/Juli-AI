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
the runner changes the fixture changes with it.

The two options are the two real answers to a confirm pause: approve and
decline. `resume(approved=True)` and `resume(approved=False)` are the same calls
the confirmation endpoint makes, so both continuations are real runner output.

**The fixture is a recorded output, not an input (issue #1677).** A normal test
run only *compares* a fresh capture against the committed copy — it never
writes `FIXTURE_PATH`. `captured_at` is produced from a fixed clock
(`_fixed_clock` below) rather than wall-clock `now()`, and the whole build runs
under a frozen system clock (`_FROZEN_SYSTEM_CLOCK`), so the comparison is
byte-identical and deterministic instead of being made to pass by restamping
the field every run. To accept an intentional change in what the runner
produces: run the committed-scenario test with `JULI_REGENERATE_GOLDEN_SCENARIOS=1`
set, inspect the diff, commit it —

    JULI_REGENERATE_GOLDEN_SCENARIOS=1 python -m pytest \\
        tests/unit/test_golden_scenario_capture_from_real_runner.py::test_the_committed_scenario_is_what_the_tool_produces

Regeneration is that explicit, separately-invoked step; it is never a side
effect of `pytest tests/unit`.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from freezegun import freeze_time
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

# Injected into `capture_run_as_scenario` instead of wall-clock `now()` (#1677,
# AC3). Fixed so a fresh capture's `captured_at` is byte-identical to the
# committed fixture's, rather than differing on every run and being "fixed" by
# restamping the file.
_FIXED_CAPTURE_INSTANT = datetime(2026, 1, 1, tzinfo=UTC)


def _fixed_clock() -> datetime:
    return _FIXED_CAPTURE_INSTANT


# `WorkflowRunner`/`PersistingEventSink` stamp each event's `timestamp` (and
# derived fields like `expires_at`) from wall-clock `datetime.now(UTC)` inside
# `runner/core.py` -- out of this issue's owned paths, so it cannot be given an
# injectable clock here. `freeze_time` pins that wall clock for the duration of
# `_build_scenario` instead, the same "freeze the system clock the code already
# reads" approach `run-ledger-panel.test.tsx` uses for its expiry countdown
# (`vi.setSystemTime`), so every event in the captured scenario is deterministic
# too, not just `captured_at`.
_FROZEN_SYSTEM_CLOCK = "2026-01-01T00:00:00+00:00"

# Each `_build_scenario` run seeds a fresh `WorkflowRun` row; a random
# `uuid.uuid4()` id would make `workflow_run_id` differ on every invocation
# regardless of the clock, defeating a byte-identical comparison for a reason
# that has nothing to do with runner behavior. Fixed per branch instead.
_BASE_RUN_ID = uuid.UUID("00000000-0000-0000-0000-00000000b453")
_APPROVED_RUN_ID = uuid.UUID("00000000-0000-0000-0000-00000000a99e")
_DECLINED_RUN_ID = uuid.UUID("00000000-0000-0000-0000-00000000dec1")


# Explicit, separately-invoked regeneration switch (#1677). Unset (the default,
# and every normal `pytest tests/unit` run): the committed-scenario test only
# reads and compares. Set: it overwrites the committed fixture with a fresh
# capture, for a human to diff and decide whether to commit.
_REGENERATE_ENV_VAR = "JULI_REGENERATE_GOLDEN_SCENARIOS"


class _NullPublisher:
    """Publish is best-effort by contract (ADR-074 d.3); capture only needs the
    committed rows, so the Redis half is a no-op here."""

    async def publish(self, channel: str, message: str) -> None:
        return None


async def _seed_run(session, run_id: uuid.UUID) -> uuid.UUID:
    """A run stamped with the REAL production prompt identity.

    `prompt_sha256` is what the staleness command compares against, so seeding a
    placeholder would make the committed scenario permanently "stale" and the
    AC7 check meaningless on the one scenario that exists.

    `run_id` is caller-supplied (fixed, per #1677) rather than generated here —
    a random id would make the captured `workflow_run_id` differ on every
    invocation for a reason unrelated to runner behavior, defeating a
    byte-identical comparison against the committed fixture.
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
        id=run_id,
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


async def _run_to_confirm_pause(
    engine: AsyncEngine, run_id: uuid.UUID
) -> tuple[uuid.UUID, async_sessionmaker]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        run_id = await _seed_run(session, run_id)

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
        return await capture_run_as_scenario(session, run_id, clock=_fixed_clock)


async def _build_scenario(engine: AsyncEngine) -> GoldenScenario:
    """Base = the run up to the pause. Continuations = what each answer adds.

    Three runs, because a run has one outcome: one supplies the shared prefix,
    and the other two supply the divergent tails. Taking the tail as
    `events[len(base):]` keeps the continuation to exactly what the answer
    caused, which is what `append_continuation` expects to append.

    The whole build runs under a frozen system clock and fixed run ids
    (#1677), so two invocations of this function produce byte-identical
    scenarios unless the runner's actual behavior changed.
    """
    with freeze_time(_FROZEN_SYSTEM_CLOCK):
        base_run_id, factory = await _run_to_confirm_pause(engine, _BASE_RUN_ID)
        base = await _capture(factory, base_run_id)

        approved_run_id, _ = await _run_to_confirm_pause(engine, _APPROVED_RUN_ID)
        await _resume(factory, approved_run_id, approved=True)
        approved = await _capture(factory, approved_run_id)

        declined_run_id, _ = await _run_to_confirm_pause(engine, _DECLINED_RUN_ID)
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


def _as_dict(scenario: GoldenScenario) -> dict[str, Any]:
    return json.loads(scenario.model_dump_json())


@pytest.mark.asyncio
async def test_the_committed_scenario_is_what_the_tool_produces(engine: AsyncEngine):
    """Compare a fresh capture to the committed copy. A drift here is a real
    change in runner output.

    This test never writes `FIXTURE_PATH` by default (#1677) — it only reads
    the committed copy and compares. `captured_at` is produced from
    `_fixed_clock`, not wall-clock `now()`, so the two are byte-identical
    (including `captured_at`) when nothing has drifted, and the comparison is
    a real assertion rather than a self-fulfilling restamp.

    To accept an intentional change in what the runner produces, regenerate
    explicitly:

        JULI_REGENERATE_GOLDEN_SCENARIOS=1 python -m pytest \\
            tests/unit/test_golden_scenario_capture_from_real_runner.py::test_the_committed_scenario_is_what_the_tool_produces

    then inspect the diff and commit it.
    """
    scenario = await _build_scenario(engine)

    if os.environ.get(_REGENERATE_ENV_VAR):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")

    assert FIXTURE_PATH.exists(), (
        f"{FIXTURE_PATH} is missing; regenerate with {_REGENERATE_ENV_VAR}=1 against this test"
    )
    mtime_before = FIXTURE_PATH.stat().st_mtime_ns
    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert _as_dict(GoldenScenario(**committed)) == _as_dict(scenario)
    assert FIXTURE_PATH.stat().st_mtime_ns == mtime_before, (
        "comparing against the committed fixture must never write it (#1677)"
    )


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
    engine: AsyncEngine, tmp_path: Path
):
    """A fresh capture must read as current, or AC7's command is meaningless on
    the only scenario that exists.

    Writes into a scratch directory (`tmp_path`), never into the committed
    fixture (#1677) — `check_scenarios` takes an arbitrary directory, and this
    test only needs a scenario file to scan, not the tracked one.
    """
    from juli_backend.services.agent.golden_scenarios.staleness import check_scenarios

    scenario = await _build_scenario(engine)
    scratch_path = tmp_path / "optimize_product_confirm_pause.json"
    scratch_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")

    results = check_scenarios(tmp_path)
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
