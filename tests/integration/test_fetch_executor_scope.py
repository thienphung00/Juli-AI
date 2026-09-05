"""The fetch executor's own statements survive with no ambient tenant scope (#1631).

WHY THIS DRIVES THE REAL EXECUTOR. A first draft of this file called
`with_shop_scope` and `TikTokSyncStateRepo` directly and never invoked
`execute_targeted_fetch_to_bronze`. It passed — and kept passing when the
executor's scope was deleted and when the UPDATE grant was revoked, because it
was exercising the helpers rather than the code under change. It proved nothing.
These tests call the executor.

WHY A NON-OWNER ROLE. Postgres exempts a table's owner from RLS, so all of this
passes against broken code on an owner connection. Sessions are
`juli_app_session(shop_id=None)`: the runtime role, no ambient tenant context —
the state the failing beat was actually in.

WHY NO SCOPE AROUND THE FETCH. The orchestrator already wraps the whole bronze
stage, and that scope does not survive the multi-minute vendor fetch (#1630).
Adjacency to each statement is the property that works, so these assert the
executor's statements survive with nothing established beforehand.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import TikTokCredential
from juli_backend.services.cdp_speed import targeted_fetch_executor as tfe
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    PartnerFetchEnv,
    execute_targeted_fetch_to_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FetchResource,
    TargetedFetchPlan,
)
from tests.integration.two_tenant import juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="requires Postgres",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

_ENV = PartnerFetchEnv(
    app_key="test-app-key",
    app_secret="test-app-secret",
    redirect_uri="https://example.test/cb",
    redis_url="redis://localhost:6379/0",
)

#: Cursor values are unique PER RUN. A fixed value lets a row left behind by an
#: earlier run satisfy the assertion without any UPDATE being issued — which is
#: exactly how an earlier draft of this file passed with the UPDATE grant
#: revoked, proving nothing about migration 055.
_RUN = int(uuid.uuid4().int % 1_000_000) * 10

_PLAN_RESOURCE = FetchResource(
    name="orders", endpoint_path="/api/orders/search", resource_attr="orders"
)


def _plan(shop_key: str) -> TargetedFetchPlan:
    return TargetedFetchPlan(catalog_id=None, shop_id=shop_key, resources=(_PLAN_RESOURCE,))


def _credential(shop_id: uuid.UUID) -> TikTokCredential:
    """A credential that satisfies credential_belongs_to_job, built not persisted."""
    return TikTokCredential(
        id=uuid.uuid4(),
        shop_id=shop_id,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        access_token="test-token",
        refresh_token="test-refresh",
    )


async def _shop_key(shop_id: uuid.UUID) -> str:
    async with juli_app_session(shop_id=shop_id) as scoped:
        return (
            await scoped.execute(
                text("SELECT tiktok_shop_id FROM shops WHERE id = :sid").bindparams(sid=shop_id)
            )
        ).scalar()


async def _run_executor(session, shop_id: uuid.UUID, shop_key: str, cursor: int, monkeypatch):
    """Drive the real executor with the vendor call stubbed out.

    Only `_run_plan_resource` is replaced — every statement this change touches
    (the shop read, the sync-state load, the sync-state save) still runs for real.
    """

    async def _stub_resource(*_args, sync_state=None, **_kwargs):
        # Stand in for a fetch that advanced the cursor, so `save` has work.
        if sync_state is not None:
            sync_state["orders_last_update_time"] = cursor

    monkeypatch.setattr(tfe, "_run_plan_resource", _stub_resource)

    async def _resolve(_session, sid):
        return _credential(sid)

    # Vendor token refresh is not what this change touches, and it raises
    # NotFound without a real credential row. Stubbed so the test exercises the
    # executor's own database statements rather than TikTok auth.
    async def _refresh(_session):
        return _credential(shop_id)

    monkeypatch.setattr(tfe, "resolve_production_read_credential", _refresh)

    return await execute_targeted_fetch_to_bronze(
        session,
        shop_id=shop_id,
        shop_key=shop_key,
        fetch_plan=_plan(shop_key),
        idempotency_key=f"test-{uuid.uuid4()}",
        env=_ENV,
        resolve_credential=_resolve,
    )


async def _cursor(shop_id: uuid.UUID) -> int | None:
    async with juli_app_session(shop_id=shop_id) as reader:
        return (
            await reader.execute(
                text(
                    "SELECT last_update_time FROM tiktok_sync_state "
                    "WHERE shop_id = :sid AND endpoint = 'orders'"
                ).bindparams(sid=shop_id)
            )
        ).scalar()


@pytest.mark.asyncio
async def test_the_executor_saves_sync_state_with_no_ambient_scope(two_tenants, monkeypatch):
    """The production failure after #1627: the post-fetch save was unscoped."""
    tenant = two_tenants[0]
    shop_key = await _shop_key(tenant.shop_id)
    assert shop_key, "fixture problem: the seeded shop has no tiktok_shop_id"

    async with juli_app_session(shop_id=None) as session:
        await _run_executor(session, tenant.shop_id, shop_key, _RUN + 1, monkeypatch)

    assert await _cursor(tenant.shop_id) == _RUN + 1, (
        "the executor did not persist its sync cursor; the save must assert its own "
        "scope rather than rely on one set before the fetch"
    )


@pytest.mark.asyncio
async def test_the_cursor_can_advance_more_than_once(two_tenants, monkeypatch):
    """THE SECOND RUN IS THE ONE THAT MATTERS (migration 055).

    `save` inserts the first time and UPDATEs every time after. juli_app held
    SELECT and INSERT but not UPDATE, so sync could advance its cursor exactly
    once and then failed with `permission denied for table tiktok_sync_state`.

    A test that runs the executor once passes with that gap wide open. The two
    refusals are easy to conflate: RLS says "new row violates row-level security
    policy"; a missing GRANT says "permission denied for table".
    """
    tenant = two_tenants[1]
    shop_key = await _shop_key(tenant.shop_id)

    async with juli_app_session(shop_id=None) as session:
        await _run_executor(session, tenant.shop_id, shop_key, _RUN + 1, monkeypatch)
    assert await _cursor(tenant.shop_id) == _RUN + 1

    async with juli_app_session(shop_id=None) as session:
        await _run_executor(session, tenant.shop_id, shop_key, _RUN + 2, monkeypatch)

    assert await _cursor(tenant.shop_id) == _RUN + 2, (
        "the sync cursor did not advance past its first value; juli_app needs "
        "UPDATE on tiktok_sync_state, not just INSERT"
    )


@pytest.mark.asyncio
async def test_the_executor_leaves_no_scope_behind(two_tenants, monkeypatch):
    """A scope outliving the executor would grant later work this tenant's view."""
    tenant = two_tenants[0]
    shop_key = await _shop_key(tenant.shop_id)

    async with juli_app_session(shop_id=None) as session:
        await _run_executor(session, tenant.shop_id, shop_key, _RUN + 5, monkeypatch)
        after = (await session.execute(text("SELECT app_current_shop_id()::text"))).scalar()

    assert after is None, f"scope leaked out of the executor (app.current_shop_id={after!r})"


@pytest.mark.asyncio
async def test_the_other_tenant_cannot_see_the_saved_cursor(two_tenants, monkeypatch):
    """Scoping must stay one shop wide."""
    mine, theirs = two_tenants[0], two_tenants[1]
    shop_key = await _shop_key(mine.shop_id)

    async with juli_app_session(shop_id=None) as session:
        await _run_executor(session, mine.shop_id, shop_key, _RUN + 7, monkeypatch)

    async with juli_app_session(shop_id=theirs.shop_id) as other:
        visible = (
            await other.execute(
                text("SELECT count(*) FROM tiktok_sync_state WHERE shop_id = :sid").bindparams(
                    sid=mine.shop_id
                )
            )
        ).scalar()

    assert visible == 0, "the other tenant can see this shop's sync state"
