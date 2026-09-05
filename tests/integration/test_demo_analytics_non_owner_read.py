"""The public demo read works as `juli_app`, not only as the table owner (#1613).

WHY THIS TEST HAS TO USE A NON-OWNER ROLE. Postgres exempts a table's owner
from RLS. Every assertion here would pass against the BROKEN code on an owner
connection, because the owner sees the row whether or not a tenant context is
set. That exemption is precisely what hid the bug: the API read
`gold.kpi_envelopes` as the owner until the #1339 cutover moved it to
`juli_app`, at which point the policy
`kpi_envelopes_select_gold: shop_id = app_current_shop_id()` started matching
nothing on a route that sets no context, and `/v1/demo/analytics` returned 404
in production.

So the session here is `juli_app_session(shop_id=None)` — the runtime role with
NO ambient tenant context, which is exactly what an unauthenticated public
request gets.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.gold_kpi_cache import get_gold_kpi_envelope
from tests.integration.two_tenant import juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="requires Postgres",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

_PAYLOAD = {
    "computed_at": "2026-09-05T00:00:00+00:00",
    "kpis": {
        "gmv_tiktok": 1000.0,
        "aov": 25.0,
        "ctor": 0.1,
        "live_hours": 4.0,
        "cancellation_rate": 0.02,
    },
}


def _seed_envelope(owner_engine, shop_id: uuid.UUID) -> None:
    """Write the serving row as the OWNER — the precompute worker's role, not the reader's."""
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO gold.kpi_envelopes
                    (shop_id, computed_at, envelope_version, payload)
                VALUES (:shop_id, :computed_at, 1, cast(:payload as json))
                ON CONFLICT (shop_id) DO UPDATE
                    SET payload = excluded.payload,
                        computed_at = excluded.computed_at
                """
            ).bindparams(
                shop_id=shop_id,
                computed_at=datetime.now(UTC),
                payload=__import__("json").dumps(_PAYLOAD),
            )
        )


@pytest.mark.asyncio
async def test_an_unscoped_read_as_juli_app_sees_nothing(two_tenants, owner_engine):
    """The bug's mechanism, asserted directly rather than through the handler.

    If this ever returns the row, RLS is not actually protecting the table and
    the rest of this file proves nothing.
    """
    tenant = two_tenants[0]
    _seed_envelope(owner_engine, tenant.shop_id)

    async with juli_app_session(shop_id=None) as session:
        envelope = await get_gold_kpi_envelope(session, tenant.shop_id, redis_client=None)

    assert envelope is None, (
        "an unscoped read as juli_app must see nothing — if it sees the row, RLS is not "
        "protecting gold.kpi_envelopes and this whole test is vacuous"
    )


@pytest.mark.asyncio
async def test_the_same_read_inside_the_shop_scope_returns_the_row(two_tenants, owner_engine):
    """The fix. Same role, same session shape, same row — only the scope differs."""
    tenant = two_tenants[0]
    _seed_envelope(owner_engine, tenant.shop_id)

    async with juli_app_session(shop_id=None) as session:
        async with with_shop_scope(session, tenant.shop_id):
            envelope = await get_gold_kpi_envelope(session, tenant.shop_id, redis_client=None)

        assert envelope is not None, (
            "scoping to the demo reference shop must restore the read; this is the "
            "production 404 (#1613)"
        )
        assert envelope.payload["kpis"]["gmv_tiktok"] == 1000.0


@pytest.mark.asyncio
async def test_the_scope_does_not_leak_past_the_read(two_tenants, owner_engine):
    """A scope that outlived the read would be worse than the 404 it fixes.

    The session is reused across requests in the real app, so a leaked
    `app.current_shop_id` would silently grant the NEXT caller this shop's
    visibility. Assert it is gone afterwards.
    """
    tenant = two_tenants[0]
    _seed_envelope(owner_engine, tenant.shop_id)

    async with juli_app_session(shop_id=None) as session:
        async with with_shop_scope(session, tenant.shop_id):
            assert await get_gold_kpi_envelope(session, tenant.shop_id, redis_client=None)

        after = await get_gold_kpi_envelope(session, tenant.shop_id, redis_client=None)

    assert after is None, (
        "the shop scope leaked past the read — a later unscoped query on this session "
        "could see another tenant's rows"
    )


@pytest.mark.asyncio
async def test_the_scope_does_not_expose_the_other_tenant(two_tenants, owner_engine):
    """Scoping to the demo shop must not become "scoped to everything"."""
    demo, other = two_tenants[0], two_tenants[1]
    _seed_envelope(owner_engine, demo.shop_id)
    _seed_envelope(owner_engine, other.shop_id)

    async with juli_app_session(shop_id=None) as session:
        async with with_shop_scope(session, demo.shop_id):
            mine = await get_gold_kpi_envelope(session, demo.shop_id, redis_client=None)
            theirs = await get_gold_kpi_envelope(session, other.shop_id, redis_client=None)

    assert mine is not None, "the scoped shop's own row must be readable"
    assert theirs is None, (
        "the demo scope exposed another tenant's envelope — the fix must scope to one "
        "shop, not disable the policy"
    )


# --- the route itself, and the class of routes it belongs to ----------------


def _no_redis(app, monkeypatch) -> None:
    """Force the Redis path off for app-level probes. Two reasons, both load-bearing.

    CORRECTNESS FIRST: this file is about RLS emptying a DATABASE read. A Redis
    cache hit would serve the envelope and let an unscoped route answer 200 while
    the read underneath it is still broken — the guard would pass on exactly the
    bug it exists to catch.

    And practically: CI runs a redis service, and the shared async client is
    created once per process, so a client built in an earlier test's event loop
    raises "Event loop is closed" when reused here. Locally there is no Redis, so
    this only ever showed up in CI.

    THE DEPENDENCY OVERRIDE IS THE HALF THAT WORKS. `demo_analytics` binds
    `get_shared_redis_client` at import, so patching it on its source module
    never reaches the route. Verified by simulating CI — patching the BOUND name
    to a client that raises on use, then removing the override: both app-level
    tests fail with CI's exact error, and pass with it. The monkeypatch is kept
    only for a route that resolves the factory dynamically.
    """
    from juli_backend.api.routes.demo_analytics import get_demo_redis_client

    monkeypatch.setattr(
        "juli_backend.services.kpi_cache.redis_client.get_shared_redis_client",
        lambda *a, **k: None,
    )
    app.dependency_overrides[get_demo_redis_client] = lambda: None


def _public_demo_get_paths(app) -> list[str]:
    """Discover public demo GETs from the app rather than listing them here.

    Discovery is the point: a NEW public demo read is covered the day it is
    added, without anyone remembering to extend a list. That is what makes this
    a guard against the class rather than a second test for one route.
    """
    schema = app.openapi()
    return sorted(
        path
        for path, ops in schema.get("paths", {}).items()
        if path.startswith("/v1/demo") and "get" in {m.lower() for m in ops}
    )


@pytest.mark.asyncio
async def test_the_route_returns_the_envelope_as_juli_app(two_tenants, owner_engine, monkeypatch):
    """End to end through the app, on a session that is subject to RLS.

    Against the pre-fix handler this is the production 404.
    """
    from httpx import ASGITransport, AsyncClient

    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    tenant = two_tenants[0]
    _seed_envelope(owner_engine, tenant.shop_id)
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(tenant.shop_id))

    app = create_app()
    _no_redis(app, monkeypatch)
    async with juli_app_session(shop_id=None) as session:

        async def _session_override():
            yield session

        app.dependency_overrides[get_session] = _session_override
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/demo/analytics")

    assert response.status_code == 200, (
        "the public demo read must work as juli_app, not only as the table owner; "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    assert "computed_at" in body, f"envelope missing computed_at: {sorted(body)}"
    missing = {"gmv_tiktok", "aov", "ctor", "live_hours", "cancellation_rate"} - set(
        body.get("kpis") or {}
    )
    assert not missing, (
        f"envelope missing the KPIs deploy.sh's verify_api_shape requires: {sorted(missing)}"
    )


@pytest.mark.asyncio
async def test_no_public_demo_read_is_emptied_by_rls(two_tenants, owner_engine, monkeypatch):
    """THE CLASS GUARD (#1613 AC4).

    Every public demo GET, discovered from the app, exercised on a session with
    NO ambient tenant context. A route that reads a tenant-scoped table without
    establishing scope returns an RLS-emptied 404 here — caught in CI instead of
    by a failed production deploy, which is how this one was found.

    A route that requires auth answers 401/403 and is not a public read, so it
    is not this guard's business.
    """
    from httpx import ASGITransport, AsyncClient

    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    tenant = two_tenants[0]
    _seed_envelope(owner_engine, tenant.shop_id)
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(tenant.shop_id))

    app = create_app()
    _no_redis(app, monkeypatch)
    paths = _public_demo_get_paths(app)
    assert paths, "discovered no public demo GET routes — the guard is checking nothing"

    emptied: list[tuple[str, int, str]] = []
    async with juli_app_session(shop_id=None) as session:

        async def _session_override():
            yield session

        app.dependency_overrides[get_session] = _session_override
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in paths:
                if "{" in path:  # needs an id we cannot invent; not a bare public read
                    continue
                response = await client.get(path)
                if response.status_code in (401, 403):
                    continue  # authenticated route: it resolves its own scope
                if response.status_code == 404:
                    emptied.append((path, response.status_code, response.text[:160]))

    assert not emptied, (
        "these public demo reads returned 404 with no tenant context, which is what RLS "
        "does to an unscoped read as juli_app — wrap the read in with_shop_scope(session, "
        f"<the shop the route already resolves>): {emptied}"
    )
