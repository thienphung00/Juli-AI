"""P22: how many database round trips each Juli Ops request makes, on real Postgres.

Production pays ~220 ms per round trip (VPS -> Supabase pooler in us-west-2),
so these counts ARE the latency budget. Every request here runs the real auth
path (a signed Supabase JWT through ``get_current_user``, then the ops staff
gate) on a fresh ``juli_app`` session per request -- the production shape,
with RLS, the ``juli_ops`` role switch and the tenant GUCs all live.

Each endpoint is called twice and the SECOND call is counted: the first warms
asyncpg's per-connection prepared-statement cache and the in-process staff
cache, which is the steady state a staff member's browser sees. The cold
(first) call of ``/me`` is asserted separately so a cache-miss regression shows
too.

Run with ``-s`` to print every endpoint's statement list.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from juli_backend.api.app import create_app
from juli_backend.database import get_session
from tests.support.postgres import juli_app_async_sessionmaker, requires_postgres
from tests.support.sql_counter import Seen, SqlCounter

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

JWT_SECRET = secrets.token_urlsafe(32)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    from juli_backend.workers.tasks import shop_diagnosis as diagnosis_tasks

    monkeypatch.setattr(diagnosis_tasks, "enqueue_shop_diagnosis", lambda *a, **k: None)
    from juli_backend.services.ops import staff as ops_staff

    clear = getattr(ops_staff, "clear_staff_cache", None)
    if clear is not None:
        clear()


@pytest.fixture(scope="module")
def staff_user(owner_engine):
    """An Admin staff member already bound to their Supabase user."""
    user_id = uuid.uuid4()
    email = f"rt-{user_id.hex[:8]}@app-juli.com"
    now = datetime.now(UTC).replace(tzinfo=None)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, email, display_name, created_at, updated_at)"
                " VALUES (:id, :phone, :email, 'Ops tester', :now, :now)"
            ),
            {"id": user_id, "phone": f"+1556{user_id.hex[:7]}", "email": email, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.ops_staff (id, email, role, active, user_id)"
                " VALUES (:id, :email, 'admin', true, :user_id)"
            ),
            {"id": uuid.uuid4(), "email": email, "user_id": user_id},
        )
    return user_id, email


def _token(user_id: uuid.UUID, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "email": email,
        "user_metadata": {"email": email, "email_verified": True, "full_name": "Ops tester"},
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


class Probe:
    def __init__(self, client: AsyncClient, counter: SqlCounter, headers: dict[str, str]):
        self.client = client
        self.counter = counter
        self.headers = headers

    async def once(self, method: str, path: str, *, ok: tuple[int, ...] = (), **kwargs) -> Seen:
        with self.counter.measure() as seen:
            response = await self.client.request(method, path, headers=self.headers, **kwargs)
        assert response.status_code < 400 or response.status_code in ok, (
            path,
            response.status_code,
            response.text,
        )
        return seen

    async def warm(self, method: str, path: str, **kwargs) -> Seen:
        await self.once(method, path, **kwargs)
        seen = await self.once(method, path, **kwargs)
        print(f"\n== {method} {path}\n{seen.describe()}")
        return seen


@pytest_asyncio.fixture
async def probe(two_tenants, staff_user) -> AsyncIterator[Probe]:
    user_id, email = staff_user
    async with juli_app_async_sessionmaker() as factory:
        engine = factory.kw["bind"]
        counter = SqlCounter.attach(engine)
        app = create_app()

        async def per_request_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = per_request_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield Probe(client, counter, {"Authorization": f"Bearer {_token(user_id, email)}"})
        counter.detach()


# Upper bounds, in round trips (statements + BEGIN/COMMIT/ROLLBACK). Each was
# measured on this branch and given no slack beyond what a data-dependent
# branch can add; raising one is a latency regression of ~220 ms per unit.
BOUNDS: dict[str, int] = {}


async def _check(probe: Probe, name: str, method: str, path: str, **kwargs) -> Seen:
    seen = await probe.warm(method, path, **kwargs)
    bound = BOUNDS.get(name)
    if bound is not None:
        assert seen.round_trips <= bound, f"{name}: {seen.describe()}"
    return seen


async def test_ops_me(probe):
    await _check(probe, "me", "GET", "/v1/ops/me")


async def test_ops_overview(probe):
    await _check(probe, "overview", "GET", "/v1/ops/overview")


async def test_ops_settings(probe, two_tenants):
    shop = two_tenants[0].shop_id
    await _check(probe, "settings", "GET", f"/v1/ops/shops/{shop}/settings")


async def test_ops_simulation(probe, two_tenants):
    shop = two_tenants[0].shop_id
    await _check(probe, "simulation", "GET", f"/v1/ops/shops/{shop}/simulation")


async def test_ops_view_session(probe, two_tenants):
    shop = two_tenants[0].shop_id
    await _check(
        probe, "view_session", "POST", f"/v1/ops/shops/{shop}/view-session", json={"mode": "view"}
    )


@pytest.mark.parametrize("tail", ["decisions", "runs", "analysis", "rules"])
async def test_ops_view_as(probe, two_tenants, tail):
    shop = two_tenants[0].shop_id
    # The seeded shop has no diagnosis report, so analysis answers 404 "No
    # analysis yet" -- after the full auth + view-scope path, which is what
    # this counts.
    ok = (404,) if tail == "analysis" else ()
    await _check(probe, f"view_{tail}", "GET", f"/v1/ops/shops/{shop}/view/{tail}", ok=ok)


async def test_ops_rules(probe, two_tenants):
    shop = two_tenants[0].shop_id
    await _check(probe, "rules", "GET", f"/v1/ops/shops/{shop}/rules")
