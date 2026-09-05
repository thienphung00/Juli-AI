"""Replay a golden scenario through the real SSE endpoint (issue #1311, ADR-084 d.2).

Starting a demo run seeds the scenario's events as real workflow_run_events rows
for that run, so GET /v1/demo/runs/{id}/events serves them unmodified via the
same endpoint and protocol. Timestamps rebased to now; inter-event deltas
preserved so pacing is the run's own. When a decision request is answered,
the chosen option's continuation is appended.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import WorkflowRunEvent
from juli_backend.services.agent.events.envelope import WorkflowRunEventAdapter
from juli_backend.services.agent.golden_scenarios.scenarios import GoldenScenario


async def seed_replay_run(
    session: AsyncSession, run_id: uuid.UUID, scenario: GoldenScenario
) -> None:
    """Seed a replay run with scenario events.

    Creates workflow_run_events rows for the given run, with timestamps
    rebased to now while preserving inter-event deltas. Every event
    validates against the shared event union before insert.

    Args:
        session: async database session
        run_id: the target workflow_runs.id
        scenario: the GoldenScenario to replay

    Raises:
        ValueError: if any event does not validate
    """
    if not scenario.events:
        return

    # Compute base timestamp (now) and first event timestamp
    now = datetime.now(UTC)
    first_event_time = datetime.fromisoformat(scenario.events[0]["timestamp"])

    # Create rows for each event, rebasing timestamps AND sequence numbers.
    #
    # Sequence numbers are minted from 1, not carried over from the scenario.
    # A live run mints from `workflow_runs.state["next_sequence"]`, which starts
    # at 1, so sequence 0 never occurs in production — and the events endpoint
    # relies on that: with no `Last-Event-ID` and no `?after=` it resolves
    # `after_seq` to 0 and replays everything `> after_seq`. A row at sequence 0
    # is therefore unreachable, silently, for every client.
    #
    # A scenario numbered from 0 would lose its first event — the run's opening
    # `workflow.started` — with a 200 and no error anywhere. Caught by
    # `tests/integration/test_golden_scenario_replay_endpoint.py`, which streams
    # through the real handler; a test that read `workflow_run_events` directly
    # saw all the rows present and passed.
    #
    # Minting here rather than validating-and-rejecting is deliberate: ADR-076
    # decision 2 wants replay runs indistinguishable from live ones at the
    # endpoint, and that means adopting the live sequence semantics rather than
    # asking every scenario author to already know them.
    rows = []
    for sequence_number, event_dict in enumerate(scenario.events, start=1):
        # Parse the event timestamp and compute delta from first event
        event_time = datetime.fromisoformat(event_dict["timestamp"])
        delta = event_time - first_event_time

        # Rebase to now + delta
        new_timestamp = now + delta

        # Create a new event dict with the rebased timestamp
        replay_event_dict = event_dict.copy()
        replay_event_dict["workflow_run_id"] = str(run_id)
        replay_event_dict["timestamp"] = new_timestamp.isoformat()
        replay_event_dict["sequence_number"] = sequence_number

        # Validate against the shared event union
        try:
            WorkflowRunEventAdapter.validate_python(replay_event_dict)
        except Exception as e:
            raise ValueError(
                f"Event {event_dict.get('sequence_number')} in scenario "
                f"{scenario.scenario_id} does not validate: {e}"
            )

        # Create the database row
        row = WorkflowRunEvent(
            workflow_run_id=uuid.UUID(replay_event_dict["workflow_run_id"]),
            sequence_number=replay_event_dict["sequence_number"],
            event_type=replay_event_dict["event_type"],
            timestamp=new_timestamp,
            payload=replay_event_dict["payload"],
            v=replay_event_dict["v"],
        )
        rows.append(row)

    # Insert all rows
    for row in rows:
        session.add(row)
    await session.commit()


async def append_continuation(
    session: AsyncSession,
    run_id: uuid.UUID,
    option_id: str,
    scenario: GoldenScenario,
) -> None:
    """Append a continuation after a decision is answered.

    When a seller chooses an option in a decision request, append that
    option's continuation events to the run. The continuation is validated
    and timestamps rebased like seed_replay_run.

    Args:
        session: async database session
        run_id: the target workflow_runs.id
        option_id: the chosen option_id
        scenario: the GoldenScenario providing the continuation

    Raises:
        ValueError: if the option_id is unknown or continuation is invalid
    """
    if option_id not in scenario.continuations:
        raise ValueError(f"Unknown option_id {option_id} in scenario {scenario.scenario_id}")

    continuation_events = scenario.continuations[option_id]
    if not continuation_events:
        return

    # Get the current max sequence number for this run
    from sqlalchemy import func, select

    stmt = select(func.max(WorkflowRunEvent.sequence_number)).where(
        WorkflowRunEvent.workflow_run_id == run_id
    )
    result = await session.execute(stmt)
    max_seq = result.scalar() or -1

    # Rebase timestamps: start from now + delta from first continuation event
    now = datetime.now(UTC)
    first_cont_time = datetime.fromisoformat(continuation_events[0]["timestamp"])

    rows = []
    for idx, event_dict in enumerate(continuation_events):
        event_time = datetime.fromisoformat(event_dict["timestamp"])
        delta = event_time - first_cont_time
        new_timestamp = now + delta

        cont_event_dict = event_dict.copy()
        cont_event_dict["workflow_run_id"] = str(run_id)
        cont_event_dict["sequence_number"] = max_seq + 1 + idx
        cont_event_dict["timestamp"] = new_timestamp.isoformat()

        # Validate
        try:
            WorkflowRunEventAdapter.validate_python(cont_event_dict)
        except Exception as e:
            raise ValueError(
                f"Continuation event {idx} for option {option_id} in scenario "
                f"{scenario.scenario_id} does not validate: {e}"
            )

        row = WorkflowRunEvent(
            workflow_run_id=uuid.UUID(cont_event_dict["workflow_run_id"]),
            sequence_number=cont_event_dict["sequence_number"],
            event_type=cont_event_dict["event_type"],
            timestamp=new_timestamp,
            payload=cont_event_dict["payload"],
            v=cont_event_dict["v"],
        )
        rows.append(row)

    # Insert all rows
    for row in rows:
        session.add(row)
    await session.commit()
