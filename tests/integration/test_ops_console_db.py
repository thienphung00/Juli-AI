"""P16 Juli Ops tables on real Postgres (migration 083_ops_console).

- ``juli_app`` (the seller/runtime role) has no grant on any ops table and
  cannot call the ops-only functions; ``anon`` / ``authenticated`` neither.
- ``ops_current_shop_overrides()`` gives a shop scope only its OWN row.
- The ops path (``services/ops/access.ops_role``) switches to ``juli_ops`` and
  back, and the services (overview, settings + audit, handover) work end to end
  from a ``juli_app`` session -- the shape the API runs in.
- The seller can stamp ``users.staff_access_consent_at`` on their own row only.
- P45 (D52): ``ops_group_lift_draws()`` reads every shop's measured group comparisons
  for the EB prior only under ``juli_ops``; a shop scope still sees only its own groups
  (since migration 107: every shop holding ``pooled_training``; the filter itself is
  ``test_ops_pooled_consent_db.py``).
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
        [
            "ops_staff",
            "ops_audit_log",
            "ops_shop_settings",
            "ops_sim_scenarios",
            "ops_shop_invites",
            # P18 (D27.1, migration 085)
            "ops_shop_daily_summary",
            # P32-A (D42, migration 090)
            "ops_reviewer_accounts",
            # P33-F (D43, migration 091)
            "trial_signups",
            # D76 / D15 (migration 107): the pooled-figure contributor audit
            "pooled_contributor_sets",
        ]
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
        "SELECT * FROM public.ops_find_shop(gen_random_uuid())",
        # P45 (D52, migration 093)
        "SELECT * FROM public.ops_group_lift_draws()",
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


async def test_nested_ops_blocks_switch_once_and_restore_once(two_tenants):
    """P22: ops_role is re-entrant within a transaction -- the inner block runs in
    the role the outer one set, emits nothing, and the outer restores."""
    from tests.support.sql_counter import SqlCounter

    async with app_session() as session:
        counter = SqlCounter.attach(session.bind.engine)
        try:
            async with session.begin():
                with counter.measure() as seen:
                    async with ops_role(session):
                        async with ops_role(session):
                            inner = (
                                await session.execute(text("SELECT current_user"))
                            ).scalar_one()
                        still = (await session.execute(text("SELECT current_user"))).scalar_one()
                after = (await session.execute(text("SELECT current_user"))).scalar_one()
        finally:
            counter.detach()
    assert (inner, still, after) == ("juli_ops", "juli_ops", RUNTIME_ROLE)
    assert seen.statements == 4, seen.describe()  # switch, 2 probes, restore


async def test_handed_over_restore_rides_on_the_shop_scope(two_tenants):
    """P22: a block may hand its role restore to the next scope statement; the
    scoped read then runs as juli_app under the shop GUC, never as juli_ops."""
    from juli_backend.database.tenant_context import with_shop_scope

    tenant_a, _ = two_tenants
    async with app_session() as session:
        async with session.begin():
            async with ops_role(session) as block:
                previous = block.hand_over()
            assert previous == RUNTIME_ROLE
            # Not restored yet: the scope's own statement must do it.
            assert (await session.execute(text("SELECT current_user"))).scalar_one() == "juli_ops"
            async with with_shop_scope(session, tenant_a.shop_id, restore_role=previous):
                who, shop = (
                    await session.execute(
                        text("SELECT current_user, current_setting('app.current_shop_id', true)")
                    )
                ).one()
    assert who == RUNTIME_ROLE
    assert shop == str(tenant_a.shop_id)


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


async def test_audit_log_rows_merge_and_expire_as_juli_ops_only(two_tenants):
    """D27.6 / D27.4 (migration 085): juli_ops may UPDATE (merge) and DELETE
    (revert, retention) audit rows; juli_app still has no grant at all."""
    tenant_a, _ = two_tenants
    staff_id = uuid.uuid4()
    async with app_session() as session:
        async with session.begin():
            async with ops_role(session):
                await session.execute(
                    text(
                        "INSERT INTO public.ops_staff (id, email, role) VALUES (:i, :e, 'operator')"
                    ),
                    {"i": staff_id, "e": f"merge-{staff_id.hex[:6]}@app-juli.com"},
                )
        actor = audit.Actor(staff_id=staff_id, email="merge@app-juli.com")
        async with session.begin():
            await audit.record(
                session,
                actor,
                "settings_update",
                shop_id=tenant_a.shop_id,
                before={"stage": "trial"},
                after={"stage": "pilot"},
                field="stage",
            )
            merged = await audit.record(
                session,
                actor,
                "settings_update",
                shop_id=tenant_a.shop_id,
                before={"stage": "pilot"},
                after={"stage": "self"},
                field="stage",
            )
            assert merged is not None and merged.merged_count == 2
        async with session.begin():
            gone = await audit.record(
                session,
                actor,
                "settings_update",
                shop_id=tenant_a.shop_id,
                before={"stage": "self"},
                after={"stage": "trial"},
                field="stage",
            )
            assert gone is None
        async with session.begin():
            await audit.purge_expired(session)
    async with app_session(tenant_a.shop_id) as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text("DELETE FROM public.ops_audit_log"))


async def test_ops_summary_and_find_shop_from_a_juli_app_session(two_tenants):
    tenant_a, _ = two_tenants
    async with app_session() as session:
        listing = await overview.find_shop(session, tenant_a.shop_id)
        assert listing is not None and listing.shop_id == tenant_a.shop_id
        summary = await overview.refresh_shop_summary(session, tenant_a.shop_id)
        await session.commit()
        assert summary.payload["connection"] in ("ok", "expired", "none")
        data = await overview.build_overview(session)
        await session.commit()
    assert any(r["shop_id"] == str(tenant_a.shop_id) for r in data["shops"])


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


async def test_group_lift_draws_read_every_shop_only_through_juli_ops(owner_engine, two_tenants):
    """P45 (D52): the EB prior's cross-shop read is ops-only; tenants stay isolated."""
    import json as _json

    from juli_backend.services.action_cards.card_groups import lift_draws

    tenant_a, tenant_b = two_tenants
    comparison = {"difference": 3.0, "median_control": 0.0, "interval": [-1.0, 7.0]}
    verdict = {
        "primary": comparison,
        "metrics": {"aov|total": {"metric": "aov", "channel": "total", "primary": comparison}},
        "products": [{"product_id": "secret-product", "arm": "treated"}],
    }
    with owner_engine.begin() as conn:
        for shop_id in (tenant_a.shop_id, tenant_b.shop_id):
            conn.execute(
                text(
                    "INSERT INTO public.card_groups (id, shop_id, group_key, metric, lever, "
                    "channel, launched_on, release_on, seed, status, verdict) VALUES "
                    "(:id, :s, 'ctr|cover_image|total', 'ctr', 'cover_image', 'total', "
                    "DATE '2026-09-01', DATE '2026-09-15', 1, 'measured', CAST(:v AS json))"
                ),
                {"id": uuid.uuid4(), "s": shop_id, "v": _json.dumps(verdict)},
            )
            # D76 / D11 (migration 107): only shops that opted into pooling are drawn.
            conn.execute(
                text(
                    "INSERT INTO public.data_use_consents (id, shop_id, scope, method, "
                    "terms_version, evidence_ref, granted_by, granted_at) VALUES "
                    "(:id, :s, 'pooled_training', 'contract_paper', 'synthetic', "
                    "'synthetic/contract.pdf', 'Synthetic Director', now())"
                ),
                {"id": uuid.uuid4(), "s": shop_id},
            )
    async with app_session(tenant_a.shop_id) as session:
        async with session.begin():
            own = (await session.execute(text("SELECT shop_id FROM public.card_groups"))).scalars()
            assert set(own) == {tenant_a.shop_id}
            async with ops_role(session):
                draws = await lift_draws(session)
            after = (await session.execute(text("SELECT current_user"))).scalar_one()
    assert after == RUNTIME_ROLE
    shops = {d.shop_id for d in draws}
    assert {str(tenant_a.shop_id), str(tenant_b.shop_id)} <= shops
    types = {d.lever_type for d in draws}
    assert {("cover_image", "ctr", "total"), ("cover_image", "aov", "total")} <= types
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM public.ops_group_lift_draws()")).mappings().all()
    assert rows and all("secret-product" not in _json.dumps(r["out_comparison"]) for r in rows)
