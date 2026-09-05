"""A replay run is served by the REAL events endpoint (#1311, AC3 and AC4).

The issue is explicit about what this must prove:

    "A seeded replay run streams through the **real** /v1/demo/runs/{id}/events
    handler. The test asserts the handler was used, not that the bytes look
    right — an in-memory shortcut here is the defect this slice exists to
    prevent."

So every assertion below is made on the bytes that came back from an HTTP
request through the ASGI app. Nothing here queries `workflow_run_events`
directly to decide whether the endpoint works: reading the table proves seeding
worked and says nothing about the handler, which is exactly the substitution the
issue forbids. Two earlier attempts at this file made that substitution — one
even carried the comment "this simulates what the real endpoint does" — which is
why the distinction is spelled out rather than assumed.

The fixtures and app/client helpers are imported from the streaming matrix
module rather than re-created. That module already wires `create_app()` to a
real Postgres through the same dependency overrides production uses, and reusing
it means these tests exercise the same handler path as the live-run tests
instead of a parallel harness that could drift from it.

`ASGITransport` reads a *finite* response to completion. Replay runs are finite
by construction — the seeded scenario ends in a terminal event — so this is the
correct transport here, and no live uvicorn server is needed (see that module's
note on why an infinite live stream would need one).
"""
# ruff: noqa: F401, F811 -- pytest resolves a fixture by the *module-global name* it
# is imported under (see `_pytest.fixtures.FixtureManager.parsefactories`), so
# `pg_session_factory` et al. must be imported verbatim to stay usable as
# fixtures here; every test parameter of the same name is therefore flagged as
# "redefining" that import, which is the intended pytest cross-module-fixture
# pattern, not a real shadowing bug. Stated once at file level, the way
# `test_agent_events_lifecycle.py` states it, rather than as five per-line
# suppressions -- the debt ratchet counts each of those as its own identity.
# F401 rides along for the same reason: four fixtures are imported solely so
# pytest can discover them, and the same-named test parameters shadow the
# import rather than counting as a use.

from __future__ import annotations

import uuid
from typing import Any

import pytest

from juli_backend.services.agent.golden_scenarios import (
    GoldenScenario,
    append_continuation,
    seed_replay_run,
)

# Fixtures and helpers reused from the live-run streaming matrix, so replay runs
# are proven through the same wiring live runs are. Imported fixtures are picked
# up by pytest as if defined here.
from tests.integration.test_agent_events_streaming_matrix import (
    _disposable_postgres_url,
    _postgres_schema_ready,
    authenticated_client,
    build_app,
    pg_engine,
    pg_session_factory,
    record_ids,
    seed_run,
    seed_shop,
)
from tests.support.postgres import requires_postgres

# `requires_postgres` from tests.support.postgres, not a local skipif. Main moved
# the reachability check there and de-underscored the streaming-matrix helpers
# while this wave was open, so W6's copy imported seven names that no longer
# exist. The merge could not see that — it is a semantic conflict, the same class
# as the adversarial-refusal one #1451 records.
pytestmark = requires_postgres


def _scenario_with_a_decision(run_id: uuid.UUID) -> GoldenScenario:
    """A three-event scenario ending in a decision, with two continuations.

    Built here as a *fixture for the endpoint*, not as scenario input: AC8's
    "no hand-authored JSON" rule is about what feeds the capture tool. These
    events exist to give the handler something to stream.
    """

    def _event(seq: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_run_id": str(run_id),
            "sequence_number": seq,
            "event_type": event_type,
            "timestamp": f"2026-08-14T12:00:{seq:02d}Z",
            "payload": payload,
            "v": 1,
        }

    return GoldenScenario(
        scenario_id="replay-endpoint-fixture",
        workflow_key="optimize_product",
        prompt_sha256="a" * 64,
        captured_at="2026-08-14T12:00:00Z",
        events=[
            _event(
                0,
                "workflow.started",
                {
                    "workflow_key": "optimize_product",
                    "product_ref": "product-ref-a1b2c3d4",
                    "prompt_version": "optimize_product.v1",
                },
            ),
            _event(
                1,
                "tool.started",
                {"tool_call_id": "call-1", "tool_name": "get_product_information"},
            ),
            _event(
                2,
                "tool.completed",
                {
                    "tool_call_id": "call-1",
                    "tool_name": "get_product_information",
                    "ok": True,
                    "summary": "Xong",
                },
            ),
        ],
        continuations={},
    )


async def _seed_replay_run(session_factory, shop) -> tuple[uuid.UUID, GoldenScenario]:
    """Create a real run row via the shared helper, then seed the scenario onto it.

    `seed_run` is reused rather than hand-rolled because `workflow_runs.product_id`
    is a foreign key — a replay run is an ordinary row and has to satisfy the same
    constraints a live run does. That is the point of the design, so the fixture
    should not route around it.
    """
    run = await seed_run(session_factory, shop, status="completed")
    run_id = run.id
    scenario = _scenario_with_a_decision(run_id)
    async with session_factory() as session:
        await seed_replay_run(session, run_id, scenario)
        await session.commit()
    return run_id, scenario


class TestTheRealHandlerServesAReplayRun:
    """AC3. Every assertion is on the HTTP response body."""

    @pytest.mark.asyncio
    async def test_a_seeded_replay_run_streams_through_the_real_endpoint(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run_id, _ = await _seed_replay_run(pg_session_factory, shop)

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            response = await client.get(f"/v1/demo/runs/{run_id}/events")

        assert response.status_code == 200, response.text
        body = response.text

        # The handler's own SSE framing — id/event/data per record. If this file
        # had queried the table instead, none of this would be exercised.
        assert "event: workflow.started" in body
        assert "event: tool.completed" in body
        assert record_ids(body) == [1, 2, 3], (
            f"the endpoint did not stream the seeded sequence in order: {record_ids(body)}"
        )

    @pytest.mark.asyncio
    async def test_another_shops_replay_run_is_not_served(self, pg_session_factory):
        """A replay run is an ordinary row, so it must inherit ordinary
        ownership. If replay bypassed `_resolve_owned_run`, this would leak."""
        _, owner_shop = await seed_shop(pg_session_factory)
        other_user, other_shop = await seed_shop(pg_session_factory)
        run_id, _ = await _seed_replay_run(pg_session_factory, owner_shop)

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, other_user, other_shop) as client:
            response = await client.get(f"/v1/demo/runs/{run_id}/events")

        assert response.status_code == 404, (
            "another shop's replay run must 404, never 403 — a 403 confirms the run exists"
        )


class TestReconnectIsGaplessAndDuplicateFree:
    """AC4. Same `Last-Event-ID` semantics as a live run, proven over HTTP."""

    @pytest.mark.asyncio
    async def test_last_event_id_resumes_without_gap_or_duplicate(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run_id, _ = await _seed_replay_run(pg_session_factory, shop)

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            full = await client.get(f"/v1/demo/runs/{run_id}/events")
            resumed = await client.get(
                f"/v1/demo/runs/{run_id}/events", headers={"Last-Event-ID": "1"}
            )

        assert full.status_code == 200 and resumed.status_code == 200
        all_ids = record_ids(full.text)
        resumed_ids = record_ids(resumed.text)

        # Gapless: resuming after 0 yields exactly the remainder.
        assert resumed_ids == [i for i in all_ids if i > 1], (
            f"reconnect was not gapless: full={all_ids} resumed={resumed_ids}"
        )
        # Duplicate-free: the record already delivered is not re-sent.
        assert 1 not in resumed_ids, "the last delivered event was re-sent after reconnect"
        assert len(resumed_ids) == len(set(resumed_ids)), "reconnect delivered duplicates"

    @pytest.mark.asyncio
    async def test_the_after_query_parameter_agrees_with_the_header(self, pg_session_factory):
        """The endpoint accepts both; a replay run must not diverge between them,
        or a client that uses one gets a different run than a client using the
        other."""
        user, shop = await seed_shop(pg_session_factory)
        run_id, _ = await _seed_replay_run(pg_session_factory, shop)

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            via_header = await client.get(
                f"/v1/demo/runs/{run_id}/events", headers={"Last-Event-ID": "1"}
            )
            via_query = await client.get(f"/v1/demo/runs/{run_id}/events?after=1")

        assert record_ids(via_header.text) == record_ids(via_query.text)


class TestContinuationsThroughTheEndpoint:
    """AC5, proven the same way — over HTTP, not by reading the table."""

    @pytest.mark.asyncio
    async def test_answering_appends_only_the_chosen_continuation(self, pg_session_factory):
        user, shop = await seed_shop(pg_session_factory)
        run_id, scenario = await _seed_replay_run(pg_session_factory, shop)

        chosen = {
            "workflow_run_id": str(run_id),
            "sequence_number": 4,
            "event_type": "workflow.completed",
            "timestamp": "2026-08-14T12:00:03Z",
            "payload": {"stop_reason": "final_response"},
            "v": 1,
        }
        not_chosen = dict(
            chosen,
            event_type="workflow.failed",
            payload={"status": "failed", "stop_reason": "tool_error_unrecoverable"},
        )
        scenario = scenario.model_copy(
            update={"continuations": {"opt-a": [chosen], "opt-b": [not_chosen]}}
        )

        async with pg_session_factory() as session:
            await append_continuation(session, run_id, "opt-a", scenario)
            await session.commit()

        app = build_app(pg_session_factory, subscriber=None)
        async with authenticated_client(app, user, shop) as client:
            response = await client.get(f"/v1/demo/runs/{run_id}/events")

        body = response.text
        assert "event: workflow.completed" in body, "the chosen continuation was not streamed"
        assert "event: workflow.failed" not in body, (
            "an option the seller did not choose was streamed to them"
        )
