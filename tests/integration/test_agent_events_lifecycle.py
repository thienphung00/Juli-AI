"""Lifecycle and crash-resume proofs for the real-Postgres event stream (ADR-074
d.6, #1131).

Sibling of `test_agent_events_streaming_matrix.py`, which owns the Postgres
fixtures, the scripted runner, the fake Redis bus and the SSE helpers this
module imports rather than redefines. Skipped without a reachable Postgres
`DATABASE_URL` -- see that module's docstring.
"""

# ruff: noqa: F811 -- pytest resolves a fixture by the *module-global name* it
# is imported under (see `_pytest.fixtures.FixtureManager.parsefactories`), so
# `pg_session_factory` et al. must be imported verbatim to stay usable as
# fixtures here; every test parameter of the same name is therefore flagged as
# "redefining" that import, which is the intended pytest cross-module-fixture
# pattern, not a real shadowing bug.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services.agent.events.persisting_sink import (
    PersistingEventSink,
    run_events_channel,
)
from tests.integration.test_agent_events_streaming_matrix import (
    FakeRedisBus,
    ScriptedEvent,
    ScriptedFakeRunner,
    _disposable_postgres_url,
    _postgres_schema_ready,
    authenticated_client,
    build_app,
    parse_sse_block,
    pg_engine,
    pg_session_factory,
    record_ids,
    seed_run,
    seed_shop,
    standard_script,
)
from tests.support.event_stream import FakePubSub, RecordingSubscriber
from tests.support.postgres import requires_postgres

pytestmark = requires_postgres


class TestLifecycle:
    """Terminal close, late-joiner replay, and a checkpoint cancellation all
    show up on the SSE stream itself."""

    async def test_terminal_event_closes_the_live_stream_via_real_http(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        channel = run_events_channel(run.id)

        async def _emit_once_subscribed() -> None:
            await bus.wait_until_subscribed(channel)
            runner = ScriptedFakeRunner(
                session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
            )
            await runner.run(standard_script("p1"), final_status="completed")

        app = build_app(pg_session_factory, subscriber=bus)
        task = asyncio.create_task(_emit_once_subscribed())
        try:
            async with authenticated_client(app, user, shop) as client:
                # Bounded well under the heartbeat interval: a terminal event
                # that failed to close the stream would hang past the timeout
                # instead of the request completing naturally.
                resp = await asyncio.wait_for(
                    client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0
                )
        finally:
            await task

        assert record_ids(resp.text) == [1, 2, 3]
        records = [b for b in resp.text.strip("\n").split("\n\n") if b and not b.startswith(":")]
        assert "workflow.completed" in records[-1]

    async def test_late_joiner_on_terminal_run_gets_full_replay_and_never_subscribes(
        self, pg_session_factory
    ):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        runner = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await runner.run(standard_script("p1"), final_status="completed")

        subscriber = RecordingSubscriber(FakePubSub())
        app = build_app(pg_session_factory, subscriber=subscriber)
        async with authenticated_client(app, user, shop) as client:
            # A "late joiner": connects only after the run is already terminal.
            resp = await asyncio.wait_for(client.get(f"/v1/demo/runs/{run.id}/events"), timeout=2.0)

        assert record_ids(resp.text) == [1, 2, 3]
        assert subscriber.calls == [], (
            "a run already terminal at connect must never attempt to subscribe -- "
            "late joiners are free (ADR-074 decision 3)"
        )

    async def test_cancel_at_checkpoint_is_visible_on_the_stream(self, pg_session_factory):
        """`POST /cancel`'s own contract (202, idempotent, transport-only) is
        already proven at unit level (`test_agent_run_events_api.py`) -- the
        actual checkpoint-cancellation signal into a runner's run state is
        out of this route's and this slice's scope. This proves the one piece
        the transport layer owns: once a run reaches a cancellation
        checkpoint (simulated by the runner emitting the failure-class
        terminal the real runner would), that event is visible on an
        already-open SSE stream and closes it.
        """
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        channel = run_events_channel(run.id)

        app = build_app(pg_session_factory, subscriber=bus)
        async with authenticated_client(app, user, shop) as client:
            cancel_resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")
            assert cancel_resp.status_code == 202

            async def _reach_checkpoint_once_subscribed() -> None:
                await bus.wait_until_subscribed(channel)
                runner = ScriptedFakeRunner(
                    session_factory=pg_session_factory,
                    sink=sink,
                    run_id=run.id,
                    starting_sequence=1,
                )
                await runner.run(
                    [
                        ScriptedEvent(
                            "workflow.failed",
                            {"status": "cancelled", "stop_reason": "cancelled_by_seller"},
                        )
                    ],
                    final_status="cancelled",
                )

            task = asyncio.create_task(_reach_checkpoint_once_subscribed())
            try:
                resp = await asyncio.wait_for(
                    client.get(f"/v1/demo/runs/{run.id}/events"), timeout=5.0
                )
            finally:
                await task

        records = [
            r for r in (parse_sse_block(b) for b in resp.text.strip("\n").split("\n\n")) if r
        ]
        assert len(records) == 1
        assert records[0]["event"] == "workflow.failed"
        assert "cancelled_by_seller" in records[0]["data"]

        async with pg_session_factory() as session:
            refreshed = await session.get(WorkflowRunRow, run.id)
            assert refreshed.status == "cancelled"


class TestCrashResume:
    """A crash-redelivered task attempt against the same starting sequence
    leaves no duplicate events and exactly one completion (#1118's
    ``next_sequence`` survival plus #1125's non-defaultable sequence number,
    exercised together for the first time)."""

    async def test_two_attempts_against_one_blob_produce_no_dupe_events_and_one_completion(
        self, pg_session_factory
    ):
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        script = standard_script("crash-resume-ref")

        # Attempt 1: the task runs to completion and persists the advanced blob.
        attempt_1 = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await attempt_1.run(script, final_status="completed", persist_state=True)

        async with pg_session_factory() as session:
            after_attempt_1 = await session.get(WorkflowRunRow, run.id)
            assert after_attempt_1.state == {"next_sequence": 4}
            assert after_attempt_1.status == "completed"

        # Attempt 2: a crash-redelivered Celery task (`acks_late=True`,
        # ADR-074 d.4) that never observed attempt 1's write -- it
        # reconstructs from the SAME starting `next_sequence` and re-emits
        # the byte-identical script.
        attempt_2 = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await attempt_2.run(script, final_status="completed", persist_state=False)

        async with pg_session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(WorkflowRunEventRow)
                        .where(WorkflowRunEventRow.workflow_run_id == run.id)
                        .order_by(WorkflowRunEventRow.sequence_number)
                    )
                )
                .scalars()
                .all()
            )

        assert [r.sequence_number for r in rows] == [1, 2, 3], (
            "two full task attempts against the same starting sequence must leave no duplicate rows"
        )
        completed_rows = [r for r in rows if r.event_type == "workflow.completed"]
        assert len(completed_rows) == 1, "exactly one completion must survive the replayed attempt"
        assert completed_rows[0].payload == {"stop_reason": "final_response"}

    async def test_duplicate_sequence_number_is_rejected_by_the_database(self, pg_session_factory):
        """Direct proof this is a REAL Postgres constraint, not app-level
        idempotency alone: a raw duplicate INSERT for one
        ``(workflow_run_id, sequence_number)`` is rejected by the database."""
        user, shop = await seed_shop(pg_session_factory)
        run = await seed_run(pg_session_factory, shop, status="running")
        bus = FakeRedisBus()
        sink = PersistingEventSink(pg_session_factory, bus)
        runner = ScriptedFakeRunner(
            session_factory=pg_session_factory, sink=sink, run_id=run.id, starting_sequence=1
        )
        await runner.run([standard_script("dup-probe")[0]], persist_state=False)

        async with pg_session_factory() as session:
            session.add(
                WorkflowRunEventRow(
                    workflow_run_id=run.id,
                    sequence_number=1,
                    event_type="workflow.status",
                    timestamp=datetime.now(UTC),
                    payload={"phase_narration": "duplicate probe"},
                    v=1,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()


# Fixtures pytest resolves by module-global name (see the file-level note above).
__all__ = [
    "FakeRedisBus",
    "ScriptedEvent",
    "ScriptedFakeRunner",
    "_disposable_postgres_url",
    "_postgres_schema_ready",
    "authenticated_client",
    "build_app",
    "parse_sse_block",
    "pg_engine",
    "pg_session_factory",
    "record_ids",
    "seed_run",
    "seed_shop",
    "standard_script",
]
