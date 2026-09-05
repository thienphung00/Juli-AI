"""The agent-run transport uses the canonical vocabulary, not a copy of it.

Before ``services.agent_runs`` existed, ``api/routes/agent_runs.py`` could not
import ``services.agent.events.*`` or ``services.agent.status`` (the
import-boundary depth cap), so it reproduced the Redis channel format, the
terminal statuses, the terminal event types and the async DB URL locally, and
this module cross-checked each copy against its source. The service package
imports the real definitions, so the copies are gone. What remains to prove:

* the values the transport exposes *are* the canonical ones (identity, not
  equality of a hand-maintained twin);
* the route module has not grown a reproduction back;
* the replay cursor's sentinel agrees with the runner's sequence minting.
"""

from __future__ import annotations

import inspect
import uuid

from juli_backend.api.routes import agent_runs as route_module
from juli_backend.services import agent_runs
from juli_backend.services.agent.events.envelope import WorkflowCompletedEvent, WorkflowFailedEvent
from juli_backend.services.agent.events.persisting_sink import run_events_channel
from juli_backend.services.agent.status import NON_TERMINAL_STATUSES, WorkflowRunStatus
from juli_backend.workers.tasks.database import get_async_database_url


def test_run_events_channel_is_the_persisting_sink_function():
    assert agent_runs.run_events_channel is run_events_channel
    run_id = uuid.uuid4()
    assert agent_runs.run_events_channel(run_id) == f"run_events:{run_id}"


def test_run_events_database_url_matches_the_worker_task_helper(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert agent_runs.run_events_database_url() == get_async_database_url()

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@host/db")
    assert agent_runs.run_events_database_url() == get_async_database_url()
    assert agent_runs.run_events_database_url().startswith("postgresql+asyncpg://")


def test_redis_event_subscriber_is_optional(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert agent_runs.resolve_redis_event_subscriber() is None

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    subscriber = agent_runs.resolve_redis_event_subscriber()
    assert isinstance(subscriber, agent_runs.RedisEventSubscriber)
    assert isinstance(subscriber, agent_runs.EventSubscriber)


def test_terminal_run_statuses_are_derived_from_the_status_enum():
    non_terminal = {member.value for member in NON_TERMINAL_STATUSES}
    canonical = (
        {member.value for member in WorkflowRunStatus}
        - non_terminal
        - {WorkflowRunStatus.WAITING_APPROVAL.value}
    )
    assert agent_runs.TERMINAL_RUN_STATUSES == canonical
    assert agent_runs.WAITING_APPROVAL_RUN_STATUS == WorkflowRunStatus.WAITING_APPROVAL.value


def test_terminal_event_types_are_derived_from_the_envelope_classes():
    assert agent_runs.TERMINAL_EVENT_TYPES == {
        WorkflowCompletedEvent.model_fields["event_type"].default,
        WorkflowFailedEvent.model_fields["event_type"].default,
    }


def test_route_module_re_exports_rather_than_redefines():
    """The route imports the vocabulary; it does not carry literals of its own."""
    assert route_module.TERMINAL_RUN_STATUSES is agent_runs.TERMINAL_RUN_STATUSES
    assert route_module.TERMINAL_EVENT_TYPES is agent_runs.TERMINAL_EVENT_TYPES
    assert route_module.event_stream is agent_runs.event_stream

    source = inspect.getsource(route_module)
    for literal in (
        '"run_events:',
        '"waiting_approval"',
        '"workflow.completed"',
        "sqlite+aiosqlite",
    ):
        assert literal not in source, f"route module reproduces {literal!r} instead of importing it"


class TestReplayCursorResolution:
    """``Last-Event-ID`` beats ``?after=`` beats 0; a bad value degrades, never raises (#1142)."""

    def test_header_wins_over_query(self):
        assert agent_runs.resolve_after_seq("7", 3) == 7

    def test_query_used_when_header_absent(self):
        assert agent_runs.resolve_after_seq(None, 3) == 3

    def test_zero_when_neither_given(self):
        assert agent_runs.resolve_after_seq(None, None) == 0

    def test_malformed_header_falls_through_to_query(self):
        assert agent_runs.resolve_after_seq("not-a-number", 5) == 5

    def test_negative_header_clamps_to_zero_and_is_kept(self):
        assert agent_runs.resolve_after_seq("-4", 5) == 0

    def test_header_above_int4_falls_through_to_query(self):
        assert agent_runs.resolve_after_seq(str(2**31), 5) == 5

    def test_query_above_int4_falls_through_to_zero(self):
        assert agent_runs.resolve_after_seq(None, 2**31) == 0


class TestSequenceBaseAgreesWithTheReplayCursor:
    """#1195: ids are minted from 1 because 0 is the "nothing seen yet" cursor."""

    def test_first_minted_sequence_is_visible_to_a_fresh_subscriber(self):
        from juli_backend.services.agent.runner import RunState

        assert RunState().allocate_sequence() > agent_runs.resolve_after_seq(None, None)

    def test_no_minted_sequence_collides_with_the_no_cursor_sentinel(self):
        from juli_backend.services.agent.runner import RunState

        state = RunState()
        minted = [state.allocate_sequence() for _ in range(5)]
        assert 0 not in minted
        assert minted == sorted(set(minted))
