"""P16 Juli Ops tables on real Postgres (migration 083_ops_console).

- ``juli_app`` (the seller/runtime role) has no grant on any ops table and
  cannot call the ops-only functions; ``anon`` / ``authenticated`` neither.
- ``ops_current_shop_overrides()`` gives a shop scope only its OWN row.
- The ops path (``services/ops/access.ops_role``) switches to ``juli_ops`` and
  back, and the services (overview, settings + audit, handover) work end to end
  from a ``juli_app`` session -- the shape the API runs in.
- The seller can stamp ``users.staff_access_consent_at`` on their own row only.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_scoped_tables import get_ops_only_tables
from juli_backend.repositories.identity import UsersRepo
from juli_backend.services.ops import audit, invites, overview
from juli_backend.services.ops import mailer as ops_mailer
from juli_backend.services.ops import overrides as ov
from juli_backend.services.ops import settings as ops_settings
from juli_backend.services.ops.access import ops_role
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

OPS_TABLES = [t for _, t in get_ops_only_tables()]
ACTOR = audit.Actor(staff_id=None, email="tester@app-juli.com")


@asynccontextmanager
async def app_session(shop_id: uuid.UUID | None = None):
    """A ``juli_app`` session (SET ROLE on the owner connection, like production's login)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            if shop_id is not None:
                await conn.execute(
                    text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                        v=str(shop_id)
                    )
                )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


def test_every_ops_table_is_classified_and_rls_enabled(owner_engine):
    assert sorted(OPS_TABLES) == sorted(
        ["ops_staff", "ops_audit_log", "ops_shop_settings", "ops_sim_scenarios", "ops_shop_invites"]
    )
    with owner_engine.connect() as conn:
        for table in OPS_TABLES:
            rls = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
            ).scalar_one()
            assert rls is True, table
            for role in (RUNTIME_ROLE, "anon", "authenticated"):
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    allowed = conn.execute(
                        text("SELECT has_table_privilege(:r, :t, :v)"),
                        {"r": role, "t": f"public.{table}", "v": verb},
                    ).scalar_one()
                    assert allowed is False, (role, table, verb)


@pytest.mark.parametrize("table", ["ops_staff", "ops_shop_settings", "ops_audit_log"])
async def test_juli_app_cannot_read_ops_tables(two_tenants, table):
    tenant_a, _ = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text(f"SELECT * FROM public.{table}"))  # nosec B608


@pytest.mark.parametrize(
    "call",
    [
        "SELECT * FROM public.ops_list_shops()",
        "SELECT * FROM public.ops_transfer_shop(gen_random_uuid(), gen_random_uuid())",
    ],
)
async def test_juli_app_cannot_call_ops_only_functions(two_tenants, call):
    tenant_a, _ = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text(call))


async def test_overrides_function_returns_only_the_scoped_shops_row(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    with owner_engine.begin() as conn:
        for shop_id, limit in ((tenant_a.shop_id, 2), (tenant_b.shop_id, 9)):
            conn.execute(
                text(
                    "INSERT INTO public.ops_shop_settings (shop_id, stage, card_daily_limit) "
                    "VALUES (:s, 'pilot', :l) ON CONFLICT (shop_id) DO UPDATE "
                    "SET card_daily_limit = EXCLUDED.card_daily_limit"
                ),
                {"s": shop_id, "l": limit},
            )
    async with app_session(tenant_a.shop_id) as session:
        current = await ov.shop_overrides(session, tenant_a.shop_id)
        assert current.card_daily_limit == 2 and current.stage == "pilot"
        # asking for B under A's scope gets the defaults, never B's row
        assert await ov.shop_overrides(session, tenant_b.shop_id) == ov.DEFAULT_OVERRIDES
    async with app_session(None) as session:
        assert await ov.shop_overrides(session, tenant_a.shop_id) == ov.DEFAULT_OVERRIDES


async def test_ops_role_switches_and_restores(two_tenants):
    tenant_a, _ = two_tenants
    async with app_session() as session:
        async with session.begin():
            async with ops_role(session):
                inside = (await session.execute(text("SELECT current_user"))).scalar_one()
            after = (await session.execute(text("SELECT current_user"))).scalar_one()
    assert (inside, after) == ("juli_ops", RUNTIME_ROLE)


async def test_settings_audit_and_overview_from_a_juli_app_session(two_tenants):
    tenant_a, tenant_b = two_tenants
    async with app_session() as session:
        view = await ops_settings.update_settings(
            session, ACTOR, tenant_a.shop_id, {"card_open_limit": 12, "stage": "self"}
        )
        await session.commit()
        assert view.overrides["card_open_limit"] == 12
        entries = await audit.list_entries(session, shop_id=tenant_a.shop_id)
        assert entries[0].action == "settings_update" and entries[0].after["card_open_limit"] == 12
        await session.commit()
        data = await overview.build_overview(session)
        await session.commit()
    ids = {row["shop_id"] for row in data["shops"]}
    assert {str(tenant_a.shop_id), str(tenant_b.shop_id)} <= ids
    row_a = next(r for r in data["shops"] if r["shop_id"] == str(tenant_a.shop_id))
    assert row_a["stage"] == "self"


async def test_audit_log_is_append_only_for_juli_ops(two_tenants):
    async with app_session() as session:
        async with session.begin():
            await audit.record(session, ACTOR, "probe")
        with pytest.raises(Exception, match="permission denied"):
            async with session.begin():
                async with ops_role(session):
                    await session.execute(text("DELETE FROM public.ops_audit_log"))


async def test_handover_moves_the_shop_through_the_definer_function(owner_engine):
    from tests.integration.two_tenant import seed_tenant

    shop_tenant = seed_tenant(owner_engine, label=f"handover-{uuid.uuid4().hex[:6]}")
    seller = seed_tenant(owner_engine, label=f"seller-{uuid.uuid4().hex[:6]}")
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.users SET email = 'seller.p16@gmail.com' WHERE id = :u"),
            {"u": seller.user_id},
        )

    class Quiet:
        async def send_invite(self, mail):
            return False

    ops_mailer.set_mailer(Quiet())
    try:
        async with app_session() as session:
            listing = await overview.find_shop(session, shop_tenant.shop_id)
            created = await invites.create_invite(
                session, ACTOR, listing, email="seller.p16@gmail.com", keep_ops_access=True
            )
            await session.commit()
        token = created.accept_url.split("#")[1]
        from juli_backend.models.models import User

        async with app_session() as session:
            user = User(id=seller.user_id, email="seller.p16@gmail.com")
            result = await invites.accept_invite(session, token, user, keep_ops_access=True)
            await session.commit()
        assert result["kept_ops_access"] is True
    finally:
        ops_mailer.set_mailer(None)
    with owner_engine.connect() as conn:
        owner = conn.execute(
            text("SELECT user_id FROM public.shops WHERE id = :s"), {"s": shop_tenant.shop_id}
        ).scalar_one()
        runs = conn.execute(
            text("SELECT count(*) FROM public.workflow_runs WHERE shop_id = :s"),
            {"s": shop_tenant.shop_id},
        ).scalar_one()
    assert owner == seller.user_id
    assert runs > 0


async def test_seller_stamps_consent_on_own_row_only(two_tenants, owner_engine):
    tenant_a, tenant_b = two_tenants
    async with app_session() as session:
        await UsersRepo(session).record_staff_access_consent(tenant_a.user_id)
        await session.commit()
        async with session.begin():
            # No user GUC → the users UPDATE policy matches no row (RLS, not an error).
            await session.execute(
                text("UPDATE public.users SET staff_access_consent_at = now() WHERE id = :u"),
                {"u": tenant_b.user_id},
            )
    with owner_engine.connect() as conn:
        stamped = conn.execute(
            text("SELECT staff_access_consent_at IS NOT NULL FROM public.users WHERE id = :u"),
            {"u": tenant_a.user_id},
        ).scalar_one()
        other = conn.execute(
            text("SELECT staff_access_consent_at IS NULL FROM public.users WHERE id = :u"),
            {"u": tenant_b.user_id},
        ).scalar_one()
    assert stamped is True
    assert other is True


async def test_disconnect_as_juli_app_under_the_shops_scope(owner_engine):
    from juli_backend.services.ops import disconnect
    from tests.integration.two_tenant import seed_tenant

    tenant = seed_tenant(owner_engine, label=f"disc-{uuid.uuid4().hex[:6]}")

    class Quiet:
        async def send_invite(self, mail):
            return False

        async def send_notice(self, *, to, subject, body):
            return False

    ops_mailer.set_mailer(Quiet())
    try:
        async with app_session() as session:
            listing = await overview.find_shop(session, tenant.shop_id)
            await session.commit()
            result = await disconnect.disconnect_shop(
                session, ACTOR, listing, reason="probe", confirm_name=listing.shop_name
            )
            await session.commit()
    finally:
        ops_mailer.set_mailer(None)
    assert result.credentials_revoked >= 1
    with owner_engine.connect() as conn:
        active = conn.execute(
            text("SELECT is_active FROM public.shops WHERE id = :s"), {"s": tenant.shop_id}
        ).scalar_one()
        statuses = set(
            conn.execute(
                text("SELECT status FROM public.tiktok_credentials WHERE shop_id = :s"),
                {"s": tenant.shop_id},
            ).scalars()
        )
    assert active is False and statuses == {"needs_reauth"}
