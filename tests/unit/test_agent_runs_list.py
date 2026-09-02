"""Polled read model for agent runs -- ``GET /v1/demo/runs`` (ADR-083 T4, #1310).

A read model, not a resource: each item is assembled from ``workflow_runs``,
the bound product, the latest ``workflow.status`` narration, and -- for a run
paused on a CONFIRM -- its pending confirmation. The service that assembles
it (``services/agent_runs/listing.py``) is tested here through the route,
since the whole point of this endpoint is the HTTP shape a client polls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from juli_backend.models.models import RunConfirmation
from tests.support.api import authenticated_client
from tests.support.builders import (
    make_product,
    make_run_event,
    make_tenant,
    make_workflow_run,
    utc_now_naive,
)

RUN_LIST_FIELDS = {
    "id",
    "status",
    "stop_reason",
    "product_name",
    "created_at",
    "completed_at",
    "running_seconds_elapsed",
    "latest_narration",
    "decision_summary",
}

# (stop_reason, status) -- every terminal pair the check constraint allows,
# one representative status per stop_reason.
TERMINAL_CASES = [
    pytest.param("final_response", "completed", id="final-response"),
    pytest.param("confirmation_declined", "completed", id="confirmation-declined"),
    pytest.param("cancelled_by_seller", "cancelled", id="cancelled-by-seller"),
    pytest.param("confirmation_expired", "cancelled", id="confirmation-expired"),
    pytest.param("wall_clock_timeout", "timed_out", id="wall-clock-timeout"),
    pytest.param("iteration_cap_exceeded", "timed_out", id="iteration-cap-exceeded"),
    pytest.param("worker_lost", "failed", id="worker-lost"),
]


async def make_confirmation(session, run, *, expires_at: datetime | None = None) -> RunConfirmation:
    """A pending ``run_confirmations`` row. Candidate for ``tests/support/builders.py``."""
    confirmation = RunConfirmation(
        workflow_run_id=run.id,
        tool_call_id="call_1",
        options=[
            {
                "option_id": "option_1",
                "proposed_change": {"price": {"from": "100", "to": "90"}},
                "rationale": "Reduce price to boost sales.",
                "params_sha": "abc123",
            }
        ],
        status="pending",
        expires_at=expires_at or (datetime.now(UTC) + timedelta(hours=2)),
    )
    session.add(confirmation)
    await session.flush()
    return confirmation


class TestTenantIsolation:
    """Each seller sees only their own shop's runs."""

    async def test_empty_shop_returns_success_true_and_no_runs(self, auth_client):
        resp = await auth_client.get("/v1/demo/runs")

        assert resp.status_code == 200
        assert resp.json() == {"success": True, "data": []}

    async def test_a_second_tenants_run_never_appears_in_the_first_tenants_list(
        self, session, tenant, auth_client
    ):
        _, shop = tenant
        own_run = await make_workflow_run(session, shop, status="queued")
        other_user, other_shop = await make_tenant(session)
        await make_workflow_run(session, other_shop, status="queued")

        own_resp = await auth_client.get("/v1/demo/runs")
        async with authenticated_client(session, user=other_user, shop=other_shop) as other_client:
            other_resp = await other_client.get("/v1/demo/runs")

        assert [item["id"] for item in own_resp.json()["data"]] == [str(own_run.id)]
        assert [item["id"] for item in other_resp.json()["data"]] != [str(own_run.id)]


class TestRunVisibility:
    """Which runs appear, and what they carry."""

    async def test_a_queued_run_with_no_events_is_visible(self, auth_client, session, shop):
        await make_workflow_run(session, shop, status="queued")

        resp = await auth_client.get("/v1/demo/runs")

        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["status"] == "queued"
        assert data[0]["stop_reason"] is None

    @pytest.mark.parametrize("stop_reason, status", TERMINAL_CASES)
    async def test_terminal_stop_reason_is_reported_verbatim(
        self, auth_client, session, shop, stop_reason, status
    ):
        run = await make_workflow_run(
            session, shop, status=status, stop_reason=stop_reason, completed_at=datetime.now(UTC)
        )

        resp = await auth_client.get("/v1/demo/runs")

        data = resp.json()["data"]
        assert [item["id"] for item in data] == [str(run.id)]
        assert data[0]["stop_reason"] == stop_reason

    async def test_includes_the_bound_products_seller_facing_name(self, auth_client, session, shop):
        product = await make_product(session, shop, name="Awesome Blue Sneakers")
        await make_workflow_run(session, shop, product=product, status="running")

        resp = await auth_client.get("/v1/demo/runs")

        assert resp.json()["data"][0]["product_name"] == "Awesome Blue Sneakers"


class TestLatestNarration:
    """The most recent ``workflow.status`` event's narration, or none."""

    async def test_the_most_recent_status_events_narration_wins(self, auth_client, session, shop):
        run = await make_workflow_run(session, shop, status="running")
        await make_run_event(session, run.id, 1, payload={"phase_narration": "starting"})
        await make_run_event(session, run.id, 2, payload={"phase_narration": "finishing"})

        resp = await auth_client.get("/v1/demo/runs")

        assert resp.json()["data"][0]["latest_narration"] == "finishing"

    async def test_no_status_event_yet_reports_no_narration(self, auth_client, session, shop):
        run = await make_workflow_run(session, shop, status="running")
        await make_run_event(session, run.id, 1, event_type="workflow.started", payload={})

        resp = await auth_client.get("/v1/demo/runs")

        assert resp.json()["data"][0]["latest_narration"] is None


class TestPendingDecisionSummary:
    """A ``waiting_approval`` run carries its pending decision's expiry."""

    async def test_waiting_approval_run_carries_tool_call_id_and_expiry(
        self, auth_client, session, shop
    ):
        run = await make_workflow_run(
            session, shop, status="waiting_approval", waiting_approval_since=datetime.now(UTC)
        )
        expires_at = datetime.now(UTC) + timedelta(hours=2)
        await make_confirmation(session, run, expires_at=expires_at)

        resp = await auth_client.get("/v1/demo/runs")

        summary = resp.json()["data"][0]["decision_summary"]
        assert summary["tool_call_id"] == "call_1"
        assert datetime.fromisoformat(summary["expires_at"]).replace(tzinfo=UTC) == expires_at

    async def test_a_run_not_waiting_on_approval_carries_no_decision_summary(
        self, auth_client, session, shop
    ):
        await make_workflow_run(session, shop, status="running")

        resp = await auth_client.get("/v1/demo/runs")

        assert resp.json()["data"][0]["decision_summary"] is None


class TestPagination:
    """The ``limit`` query parameter actually bounds the page."""

    async def test_limit_returns_at_most_that_many_newest_first(self, auth_client, session, shop):
        # created_at has only second resolution under SQLite's CURRENT_TIMESTAMP;
        # stamp each row explicitly so "newest first" has something to sort by.
        base = utc_now_naive()
        runs = [
            await make_workflow_run(
                session, shop, status="queued", created_at=base + timedelta(seconds=i)
            )
            for i in range(5)
        ]

        resp = await auth_client.get("/v1/demo/runs", params={"limit": 2})

        data = resp.json()["data"]
        assert len(data) == 2
        assert [item["id"] for item in data] == [str(runs[-1].id), str(runs[-2].id)]


class TestResponseShape:
    """The response exposes exactly the documented fields -- nothing internal."""

    async def test_each_item_exposes_exactly_the_documented_fields(
        self, auth_client, session, shop
    ):
        run = await make_workflow_run(session, shop, status="running", running_seconds_elapsed=42)
        await make_run_event(session, run.id, 1)

        resp = await auth_client.get("/v1/demo/runs")

        assert resp.json()["data"][0].keys() == RUN_LIST_FIELDS
