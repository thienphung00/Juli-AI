"""P22: how many database round trips each Juli Ops request makes, on real Postgres.

Production pays ~395 ms per round trip (VPS in Asia -> Supabase pooler in
us-west-2, measured 2026-10-12; ~220 ms when P22 was written), so these counts
ARE the latency budget. Every request here runs the real auth
path (a signed Supabase JWT through ``get_current_user``, then the ops staff
gate) on a fresh ``juli_app`` session per request -- the production shape,
with RLS, the ``juli_ops`` role switch and the tenant GUCs all live.

Each endpoint is called twice and the SECOND call is counted: the first warms
asyncpg's per-connection prepared-statement cache and the in-process caches
(the staff row and the signed-in user, 60 s; a shop's cap + tunables and the
system banner, 30 s), which is the steady state a staff member's browser sees.
The cache-MISS paths are asserted separately (``*_cold*``) so a regression in
either shows.

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
    _forget_caches()


def _forget_caches() -> None:
    from juli_backend.services.ops import settings as ops_settings
    from juli_backend.services.ops import staff as ops_staff
    from juli_backend.services.ops import system_cap

    ops_staff.clear_staff_cache()
    ops_settings.forget_cap_and_tunables()
    system_cap.forget_banner()


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
# branch can add; raising one is a latency regression of ~395 ms per unit.
#
# Before P22 (same data, same harness): me 12, overview 24, settings 35,
# simulation 44, view_session 33, view_decisions 23, view_runs 28 (+2 per
# extra run), view_analysis 22, view_rules 22, rules 22.
#
# Before P29 (P22 bounds; savepoints now counted once): me 4, overview 12,
# settings 14, simulation 16, view_session 11, view_decisions 12, view_runs 13,
# view_analysis 11, view_rules 12, rules 12, costs_system 13, costs 27 (two
# shops; 4 per shop), terms 18 (3 per shop), staff 9, audit 9, shop_terms 13,
# shop_invites 12, shop_runs 12, shop_view_term 12.
#
# P29: the signed-in user is cached beside the staff row (-4 everywhere: no
# auth transaction at all on a warm request), the listing + settings row and
# Tổng quan's four ops reads are one statement each, "Xem như shop" finds the
# shop and enters the seller's scope in one statement, the fleet pages move one
# scope from shop to shop, and a request's last scope / role block skips its
# restore (the transaction's end discards SET LOCAL anyway).
BOUNDS: dict[str, int] = {
    "me": 0,
    "overview": 4,
    "settings": 6,  # cap + tunables cached; the miss is test_ops_settings_cold_cap
    "simulation": 9,
    "view_session": 5,
    "view_decisions": 7,
    "view_runs": 8,
    "view_analysis": 6,
    # P23 (D29.9): +1 for the seller's default bands (one fused statement).
    "view_rules": 7,
    "rules": 7,
    "costs_system": 0,  # cached 30 s; the miss is test_ops_costs_system_cold
    "costs": 9,  # two shops: 2 per shop
    "terms": 9,  # two shops: 2 per shop
    "staff": 4,
    "audit": 4,
    "shop_terms": 6,
    "shop_invites": 5,
    "shop_runs": 6,
    "shop_view_term": 6,
}


async def _check(probe: Probe, name: str, method: str, path: str, **kwargs) -> Seen:
    seen = await probe.warm(method, path, **kwargs)
    bound = BOUNDS.get(name)
    if bound is not None:
        assert seen.round_trips <= bound, f"{name}: {seen.describe()}"
    return seen


async def test_ops_me(probe):
    await _check(probe, "me", "GET", "/v1/ops/me")


async def test_ops_me_cold_cache(probe):
    """The first request of a staff member on a worker: the staff row is read.

    auth (BEGIN, user GUC, users, COMMIT) + BEGIN, role switch, ops_staff,
    role restore, ROLLBACK -- and no COMMIT for a read-only resolution.
    """
    await probe.once("GET", "/v1/ops/me")  # warm asyncpg's statement cache
    _forget_caches()
    seen = await probe.once("GET", "/v1/ops/me")
    print(f"\n== GET /v1/ops/me (cold staff cache)\n{seen.describe()}")
    assert seen.round_trips <= 9, seen.describe()


async def test_ops_costs_system_cold(probe):
    """The banner figure on a cache miss: the spend and both settings rows in
    ONE statement (was the spend plus two SAVEPOINT-wrapped reads: 9)."""
    await probe.once("GET", "/v1/ops/costs/system")
    _forget_caches()
    await probe.once("GET", "/v1/ops/me")  # re-warm the user + staff caches only
    seen = await probe.once("GET", "/v1/ops/costs/system")
    print(f"\n== GET /v1/ops/costs/system (cold banner)\n{seen.describe()}")
    assert seen.round_trips <= 3, seen.describe()


async def test_ops_settings_cold_cap(probe, two_tenants):
    """Settings on a cap/tunables cache miss: + the scope (carrying the role
    switch back) and the read; no restore after it."""
    from juli_backend.services.ops import settings as ops_settings

    shop = two_tenants[0].shop_id
    await probe.once("GET", f"/v1/ops/shops/{shop}/settings")
    ops_settings.forget_cap_and_tunables()
    seen = await probe.once("GET", f"/v1/ops/shops/{shop}/settings")
    print(f"\n== GET settings (cold cap cache)\n{seen.describe()}")
    assert seen.round_trips <= 8, seen.describe()


async def test_ops_user_cache_never_serves_another_user(probe, owner_engine, two_tenants):
    """The users read is cached per VERIFIED ``sub``: a second staff member's
    token resolves to that member, never to the first one's cached entry; and a
    signed-in seller who is not staff is never cached (403, users re-read)."""
    probe_email = (await probe.client.get("/v1/ops/me", headers=probe.headers)).json()["email"]
    other_id = uuid.uuid4()
    other_email = f"rt2-{other_id.hex[:8]}@app-juli.com"
    now = datetime.now(UTC).replace(tzinfo=None)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, email, display_name, created_at, updated_at)"
                " VALUES (:id, :phone, :email, 'Ops 2', :now, :now)"
            ),
            {"id": other_id, "phone": f"+1557{other_id.hex[:7]}", "email": other_email, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.ops_staff (id, email, role, active, user_id)"
                " VALUES (:id, :email, 'viewer', true, :user_id)"
            ),
            {"id": uuid.uuid4(), "email": other_email, "user_id": other_id},
        )
    other = {"Authorization": f"Bearer {_token(other_id, other_email)}"}
    for _ in range(2):
        body = (await probe.client.get("/v1/ops/me", headers=other)).json()
        assert body["email"] == other_email and body["role"] == "viewer"
        mine = (await probe.client.get("/v1/ops/me", headers=probe.headers)).json()
        assert mine["email"] == probe_email and mine["role"] == "admin"

    seller = two_tenants[0]
    seller_headers = {"Authorization": f"Bearer {_token(seller.user_id, 'seller@example.com')}"}
    for _ in range(2):
        with probe.counter.measure() as seen:
            response = await probe.client.get("/v1/ops/me", headers=seller_headers)
        assert response.status_code == 403
        assert any(e.startswith("SELECT users.id") for e in seen.events), seen.describe()


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


@pytest.mark.parametrize(
    "name,path",
    [
        ("costs_system", "/v1/ops/costs/system"),
        ("costs", "/v1/ops/costs"),
        ("terms", "/v1/ops/terms"),
        ("staff", "/v1/ops/staff"),
        ("audit", "/v1/ops/audit"),
    ],
)
async def test_ops_fleet_pages(probe, name, path):
    await _check(probe, name, "GET", path)


@pytest.mark.parametrize("tail", ["terms", "invites", "runs", "view/term"])
async def test_ops_shop_pages(probe, two_tenants, tail):
    shop = two_tenants[0].shop_id
    await _check(probe, f"shop_{tail.replace('/', '_')}", "GET", f"/v1/ops/shops/{shop}/{tail}")


async def test_one_shop_summary_refresh(two_tenants):
    """The per-shop cost of "Làm mới" / a first overview: the numbers under the
    shop's scope plus the upsert in an ops block (was 24 round trips)."""
    from juli_backend.services.ops import overview

    shop = two_tenants[0].shop_id
    async with juli_app_async_sessionmaker() as factory:
        counter = SqlCounter.attach(factory.kw["bind"])
        try:
            async with factory() as session:
                await overview.refresh_shop_summary(session, shop)  # warm statement cache
                await session.rollback()
                with counter.measure() as seen:
                    await overview.refresh_shop_summary(session, shop)
                await session.rollback()
        finally:
            counter.detach()
    print(f"\n== refresh_shop_summary (one shop)\n{seen.describe()}")
    assert seen.round_trips <= 12, seen.describe()
