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

from juli_backend.api.routes.ops import get_ops_user
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

    app.dependency_overrides[get_ops_user] = current
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


# -- P29: the signed-in user cache ---------------------------------------------------


def test_user_cache_is_per_sub_and_never_refreshed_by_hits(monkeypatch):
    from juli_backend.services.ops import staff as ops_staff

    clock = [1000.0]
    monkeypatch.setattr(ops_staff.time, "monotonic", lambda: clock[0])
    a, b = uuid.uuid4(), uuid.uuid4()
    ops_staff.remember_user(ops_staff.OpsUser(id=a, email="a@app-juli.com"))
    hit = ops_staff.cached_user(a)
    assert hit is not None and hit.email == "a@app-juli.com" and hit.cached
    assert ops_staff.cached_user(b) is None  # another sub never sees a's entry
    clock[0] += 40
    ops_staff.remember_user(hit)  # a cache hit is not re-stored: no TTL refresh
    clock[0] += 25  # 65 s after the read
    assert ops_staff.cached_user(a) is None


def test_clear_staff_cache_forgets_users_too():
    from juli_backend.services.ops import staff as ops_staff

    user_id = uuid.uuid4()
    ops_staff.remember_user(ops_staff.OpsUser(id=user_id, email="x@app-juli.com"))
    ops_staff.clear_staff_cache()
    assert ops_staff.cached_user(user_id) is None


async def test_put_staff_drops_the_user_cache(session):
    """A staff change made through this process re-reads everyone at once."""
    from juli_backend.services.ops import staff as ops_staff

    admin = await _staff(session, "admin")
    ops_staff.remember_user(ops_staff.OpsUser(id=admin.id, email=admin.email))
    async with _client_as(session, admin) as client:
        response = await client.put(
            "/v1/ops/staff", json={"email": "new-1@app-juli.com", "role": "viewer"}
        )
    assert response.status_code == 200
    assert ops_staff.cached_user(admin.id) is None


async def test_a_settings_change_is_seen_through_the_cap_cache(session):
    """P29: GET settings caches the cap + tunables for 30 s; a PUT through this
    process forgets the shop's entry, so the next GET shows the new value."""
    admin = await _staff(session, "admin")
    _, shop = await make_tenant(session)
    url = f"/v1/ops/shops/{shop.id}/settings"
    async with _client_as(session, admin) as client:
        first = (await client.get(url)).json()["settings"]["overrides"]
        assert first["openai_monthly_cap_usd"] is None
        put = await client.put(url, json={"changes": {"openai_monthly_cap_usd": 7}})
        assert put.status_code == 200, put.text
        again = (await client.get(url)).json()["settings"]["overrides"]
    assert again["openai_monthly_cap_usd"] == 7.0
