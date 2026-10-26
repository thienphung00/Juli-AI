"""Migration 107 on real Postgres (D76 / D11, ADR-116 §3): the EB prior pools consenting shops only.

- ``ops_group_lift_draws()`` returns the measured group comparisons of shops holding an
  open ``pooled_training`` grant only: a revoked grant, another scope or no grant at all
  exclude the shop; with no grant anywhere it returns nothing;
- it is read through the ``juli_ops`` path (``ops_role``) from a ``juli_app`` session,
  exactly as the Ops route does -- the SECURITY DEFINER body reads the tenant table
  ``data_use_consents`` across shops while the caller still cannot;
- signature, SECURITY DEFINER, pinned ``search_path`` and EXECUTE grants are 093's
  (``juli_ops`` yes, ``juli_app`` / PUBLIC no), before and after the round trip;
- downgrade to 106 restores 093's behaviour (every shop), ``upgrade head`` the filter.

It downgrades a revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its own.
Synthetic tenants only.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.ops.access import ops_role
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_ID = "107_ops_pooled_consent"
FUNCTION = "public.ops_group_lift_draws()"
OPS_ROLE = "juli_ops"


@asynccontextmanager
async def app_session(shop_id: uuid.UUID):
    """A ``juli_app`` session scoped to one shop (SET ROLE, like production's login)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                    v=str(shop_id)
                )
            )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def tenants(owner_engine):
    """Four synthetic shops, each with one measured group:
    granted (open pooled_training), revoked, service-only, none."""
    from tests.integration.two_tenant import seed_tenant

    labels = ("granted", "revoked", "service-only", "none")
    out = {label: seed_tenant(owner_engine, label=label) for label in labels}
    comparison = {"difference": 3.0, "median_control": 0.0, "interval": [-1.0, 7.0]}
    verdict = {
        "primary": comparison,
        "metrics": {"aov|total": {"metric": "aov", "channel": "total", "primary": comparison}},
    }
    grant = text(
        "INSERT INTO public.data_use_consents (id, shop_id, scope, method, terms_version, "
        "evidence_ref, granted_by, granted_at, revoked_at) VALUES "
        "(:id, :s, :scope, 'contract_paper', 'synthetic', 'synthetic/contract.pdf', "
        "'Synthetic Director', now() - interval '2 days', "
        "CASE WHEN :revoked THEN now() - interval '1 day' END)"
    )
    with owner_engine.begin() as conn:
        for tenant in out.values():
            conn.execute(
                text(
                    "INSERT INTO public.card_groups (id, shop_id, group_key, metric, lever, "
                    "channel, launched_on, release_on, seed, status, verdict) VALUES "
                    "(:id, :s, 'ctr|cover_image|total', 'ctr', 'cover_image', 'total', "
                    "DATE '2026-09-01', DATE '2026-09-15', 1, 'measured', CAST(:v AS json))"
                ),
                {"id": uuid.uuid4(), "s": tenant.shop_id, "v": json.dumps(verdict)},
            )
        rows = (
            ("granted", "pooled_training", False),
            ("revoked", "pooled_training", True),
            ("service-only", "service", False),
        )
        for label, scope, revoked in rows:
            conn.execute(
                grant,
                {"id": uuid.uuid4(), "s": out[label].shop_id, "scope": scope, "revoked": revoked},
            )
    return out


def _ids(tenants) -> dict[str, str]:
    return {label: str(t.shop_id) for label, t in tenants.items()}


def _drawn_as_ops(owner_engine) -> set[str]:
    """Shops in the function's output, called as ``juli_ops`` (SET LOCAL ROLE)."""
    with owner_engine.begin() as conn:
        conn.execute(text(f"SET LOCAL ROLE {OPS_ROLE}"))
        return {str(r[0]) for r in conn.execute(text(f"SELECT out_shop_id FROM {FUNCTION}"))}


def _acl(owner_engine) -> tuple:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT p.prosecdef, p.proconfig, p.provolatile, "
                "pg_get_function_result(p.oid), "
                "has_function_privilege(:ops, p.oid, 'EXECUTE'), "
                "has_function_privilege(:app, p.oid, 'EXECUTE'), "
                "EXISTS (SELECT 1 FROM aclexplode("
                "        COALESCE(p.proacl, acldefault('f', p.proowner))) a "
                "        WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') "
                "FROM pg_proc p WHERE p.oid = to_regprocedure(:fn)"
            ),
            {"ops": OPS_ROLE, "app": RUNTIME_ROLE, "fn": FUNCTION},
        ).one()


def test_grants_and_shape_are_093s(owner_engine):
    secdef, config, volatile, result, ops_exec, app_exec, public_exec = _acl(owner_engine)
    assert secdef is True and volatile == "s"
    assert config == ["search_path=pg_catalog, public"]
    assert result.startswith("TABLE(out_shop_id uuid, out_group_id uuid")
    assert (ops_exec, app_exec, public_exec) == (True, False, False)


@pytest.mark.asyncio
async def test_only_the_shop_with_an_open_pooled_grant_is_drawn(owner_engine, tenants):
    from juli_backend.services.action_cards.card_groups import lift_draws

    ids = _ids(tenants)
    async with app_session(tenants["none"].shop_id) as session:
        async with session.begin():
            # The caller itself cannot read another shop's grants (tenant RLS) ...
            visible = (
                await session.execute(text("SELECT shop_id FROM public.data_use_consents"))
            ).scalars()
            assert list(visible) == []
            # ... but the Ops path's draws are the granted shop's, both of its comparisons.
            async with ops_role(session):
                draws = await lift_draws(session)
    mine = {d.shop_id for d in draws} & set(ids.values())
    assert mine == {ids["granted"]}
    assert {d.lever_type for d in draws if d.shop_id == ids["granted"]} == {
        ("cover_image", "ctr", "total"),
        ("cover_image", "aov", "total"),
    }
    assert _drawn_as_ops(owner_engine) & set(ids.values()) == {ids["granted"]}


def test_revoking_the_last_grant_empties_the_pool(owner_engine, tenants):
    ids = _ids(tenants)
    with owner_engine.connect() as conn:  # one transaction, rolled back at the end
        conn.execute(text(f"SET LOCAL ROLE {OPS_ROLE}"))
        before = {str(r[0]) for r in conn.execute(text(f"SELECT out_shop_id FROM {FUNCTION}"))}
        conn.execute(text("RESET ROLE"))
        conn.execute(
            text(
                "UPDATE public.data_use_consents SET revoked_at = now() "
                "WHERE shop_id = :s AND revoked_at IS NULL"
            ),
            {"s": ids["granted"]},
        )
        conn.execute(text(f"SET LOCAL ROLE {OPS_ROLE}"))
        after = list(conn.execute(text(f"SELECT out_shop_id FROM {FUNCTION}")))
        conn.rollback()
    assert ids["granted"] in before
    assert after == []
    # Rolled back: the grant is open again.
    assert ids["granted"] in _drawn_as_ops(owner_engine)


def test_juli_app_cannot_call_the_function(owner_engine, tenants):
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="permission denied") as refused:
        with owner_engine.begin() as conn:
            conn.execute(text(f"SET LOCAL ROLE {RUNTIME_ROLE}"))
            conn.execute(text(f"SELECT * FROM {FUNCTION}"))
    assert "ops_group_lift_draws" in str(refused.value)


def test_zz_downgrade_restores_093_and_upgrade_restores_the_filter(owner_engine, tenants):
    """Last in the module: downgrade to 106 (every shop drawn), then back to head."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    parent = ScriptDirectory.from_config(cfg).get_revision(MIGRATION_ID).down_revision
    assert parent == "106_write_platform_columns"

    def current() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    ids = _ids(tenants)
    acl = _acl(owner_engine)
    assert current() == MIGRATION_ID
    command.downgrade(cfg, parent)
    assert current() == parent
    assert _drawn_as_ops(owner_engine) & set(ids.values()) == set(ids.values())
    assert _acl(owner_engine) == acl
    command.upgrade(cfg, "head")
    assert current() == MIGRATION_ID
    assert _drawn_as_ops(owner_engine) & set(ids.values()) == {ids["granted"]}
    assert _acl(owner_engine) == acl
