"""P22 round-trip regressions that run without Postgres (SQLite).

SQLite has no roles and no GUCs, so the scope / role statements the production
path sends are no-ops here; the exact Postgres counts are pinned in
``tests/integration/test_ops_round_trips.py``. What IS provable here, and runs
at every tier:

- the resolved-staff cache: a second Ops request makes no ``ops_staff`` read;
- a staff change through ``PUT /v1/ops/staff`` is seen at once (cache cleared);
- the run list makes the same number of statements for 1 run as for 5 (the
  per-run narration / confirmation N+1 is gone).
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.core.security import get_current_user
from juli_backend.models.models import User
from juli_backend.models.ops import OpsStaff
from tests.support.api import build_app, client_for
from tests.support.builders import make_run_event, make_tenant, make_user, make_workflow_run
from tests.support.sql_counter import SqlCounter


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


async def _staff(session, role: str = "admin") -> User:
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True, user_id=user.id))
    await session.flush()
    return user


def _client_as(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)  # a route's rollback expires it, like a new request
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app)


def _ops_staff_reads(seen) -> int:
    return sum(1 for e in seen.events if "FROM ops_staff" in e)


async def test_second_ops_request_does_not_read_ops_staff(session):
    user = await _staff(session)
    counter = SqlCounter.attach(session.bind)
    try:
        async with _client_as(session, user) as client:
            with counter.measure() as first:
                assert (await client.get("/v1/ops/me")).status_code == 200
            with counter.measure() as second:
                assert (await client.get("/v1/ops/me")).status_code == 200
    finally:
        counter.detach()
    assert _ops_staff_reads(first) == 1, first.describe()
    # The only statement left is the test double's own `refresh(user)`.
    assert _ops_staff_reads(second) == 0, second.describe()
    assert second.statements <= 1, second.describe()


async def test_a_role_change_through_this_process_is_seen_at_once(session):
    admin = await _staff(session, "admin")
    viewer = await _staff(session, "viewer")
    async with _client_as(session, viewer) as client:
        assert (await client.get("/v1/ops/me")).json()["role"] == "viewer"  # now cached
    async with _client_as(session, admin) as client:
        response = await client.put(
            "/v1/ops/staff", json={"email": viewer.email, "role": "operator", "active": True}
        )
        assert response.status_code == 200, response.text
    async with _client_as(session, viewer) as client:
        assert (await client.get("/v1/ops/me")).json()["role"] == "operator"


async def test_deactivation_through_this_process_locks_out_at_once(session):
    admin = await _staff(session, "admin")
    viewer = await _staff(session, "viewer")
    async with _client_as(session, viewer) as client:
        assert (await client.get("/v1/ops/me")).status_code == 200
    async with _client_as(session, admin) as client:
        response = await client.put(
            "/v1/ops/staff", json={"email": viewer.email, "role": "viewer", "active": False}
        )
        assert response.status_code == 200, response.text
    async with _client_as(session, viewer) as client:
        assert (await client.get("/v1/ops/me")).status_code == 403


async def _view_runs_statements(session, runs: int) -> int:
    _, shop = await make_tenant(session)
    for _ in range(runs):
        run = await make_workflow_run(session, shop, status="waiting_approval")
        await make_run_event(session, run.id, 1, payload={"phase_narration": "Đang xem"})
    user = await _staff(session)
    counter = SqlCounter.attach(session.bind)
    try:
        async with _client_as(session, user) as client:
            await client.get("/v1/ops/me")  # staff cache warm
            with counter.measure() as seen:
                response = await client.get(f"/v1/ops/shops/{shop.id}/view/runs")
    finally:
        counter.detach()
    assert response.status_code == 200, response.text
    assert len(response.json()["data"]) == runs
    return seen.statements


async def test_view_runs_statement_count_does_not_grow_with_runs(session):
    one = await _view_runs_statements(session, 1)
    five = await _view_runs_statements(session, 5)
    assert five == one, f"1 run: {one} statements, 5 runs: {five}"
