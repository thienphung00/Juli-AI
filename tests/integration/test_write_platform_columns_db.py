"""Migration 106 on real Postgres (ADR-116 §6, D76): per-platform production-write columns.

- both tables gain ``platform`` (NOT NULL, default ``'tiktok'``) and a nullable
  ``platform_product_id``; the authorizations table its per-platform lookup index;
- RLS, policies and ``juli_app`` grants are unchanged: the audit stays append-only
  (SELECT / INSERT; UPDATE and DELETE refused), two tenants stay isolated;
- the resolver's audit write fills the old column and the new pair, under ``juli_app``;
- the operator backfill (``write_platform_backfill``) fills ``platform_product_id`` on a
  pre-106 row as the owner, and a second run changes nothing; ``juli_app`` cannot run it;
- downgrade to 105 drops the columns and ``upgrade head`` restores them.

It downgrades a revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its own.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATIONS = "production_write_authorizations"
AUDIT = "production_write_audit"
TABLES = (AUTHORIZATIONS, AUDIT)
MIGRATION_ID = "106_write_platform_columns"


@asynccontextmanager
async def app_session(shop_id: uuid.UUID):
    """A ``juli_app`` async session scoped to one shop whose commits really commit."""
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


def _columns(owner_engine, table: str) -> dict[str, tuple[str, str | None]]:
    with owner_engine.connect() as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            )
        }


def _security(owner_engine, table: str) -> tuple[bool, set[str], set[str]]:
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(:t)"),
            {"t": f"public.{table}"},
        ).scalar_one()
        grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = :t AND grantee = :role"
                ),
                {"t": table, "role": RUNTIME_ROLE},
            )
        }
        policies = {
            row[0]
            for row in conn.execute(
                text("SELECT cmd FROM pg_policies WHERE tablename = :t"), {"t": table}
            )
        }
    return bool(rls), grants, policies


def _audit_rows(owner_engine, shop_id: uuid.UUID) -> list[tuple]:
    with owner_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT tiktok_product_id, platform, platform_product_id, precondition_name "
                    "FROM public.production_write_audit WHERE shop_id = :shop ORDER BY created_at"
                ),
                {"shop": str(shop_id)},
            )
        )


def test_the_new_columns_are_present_with_their_default(owner_engine):
    for table in TABLES:
        columns = _columns(owner_engine, table)
        nullable, default = columns["platform"]
        assert nullable == "NO" and default is not None and "tiktok" in default
        assert columns["platform_product_id"][0] == "YES"
        assert columns["tiktok_product_id"][0] == "NO"  # expand-only: the old column stays
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT to_regclass("
                    "'public.ix_production_write_authorizations_platform_lookup')"
                )
            ).scalar_one()
            is not None
        )


def test_rls_policies_and_grants_are_unchanged(owner_engine):
    assert _security(owner_engine, AUDIT) == (True, {"SELECT", "INSERT"}, {"SELECT", "INSERT"})
    rls, grants, _policies = _security(owner_engine, AUTHORIZATIONS)
    assert rls is True
    assert grants == {"SELECT", "UPDATE"}  # 048, untouched


@pytest.mark.asyncio
async def test_the_resolver_writes_both_columns_and_the_audit_stays_append_only(
    owner_engine, two_tenants, monkeypatch
):
    from juli_backend.services.execution.production_write_resolver import (
        PreconditionName,
        record_refused_attempt,
    )

    monkeypatch.setenv("RELEASE_SHA", "c" * 40)
    tenant_a, tenant_b = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        await record_refused_attempt(
            session,
            run_id=tenant_a.stale_run_id,
            shop_id=tenant_a.shop_id,
            tiktok_product_id="pa-1",
            mutation_kind="update_product_listing",
            precondition=PreconditionName.APPROVAL_EXPIRED,
        )
        await session.commit()
        for statement in (
            "UPDATE public.production_write_audit SET platform_product_id = 'x' "
            "WHERE shop_id = :shop",
            "DELETE FROM public.production_write_audit WHERE shop_id = :shop",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(text(statement), {"shop": str(tenant_a.shop_id)})
            await session.rollback()

    async with app_session(tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.production_write_audit"))
        ).all()
        assert tenant_a.shop_id not in {row[0] for row in visible}

    assert _audit_rows(owner_engine, tenant_a.shop_id) == [
        ("pa-1", "tiktok", "pa-1", "approval_expired")
    ]


@pytest.mark.asyncio
async def test_the_operator_backfill_fills_old_rows_once_and_only_as_the_owner(
    owner_engine, two_tenants
):
    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.services.operations import write_platform_backfill

    _, tenant_b = two_tenants
    with owner_engine.begin() as conn:  # a row as the pre-106 code wrote it
        conn.execute(
            text(
                "INSERT INTO public.production_write_audit (id, run_id, shop_id, "
                " tiktok_product_id, mutation_kind, precondition_name, release_sha) VALUES "
                " (:id, :run, :shop, 'pb-old', 'update_product_listing', "
                " 'no_matching_authorization', :sha)"
            ),
            {
                "id": str(uuid.uuid4()),
                "run": str(tenant_b.stale_run_id),
                "shop": str(tenant_b.shop_id),
                "sha": "d" * 40,
            },
        )
    assert _audit_rows(owner_engine, tenant_b.shop_id)[-1][:3] == ("pb-old", "tiktok", None)

    async with app_session(tenant_b.shop_id) as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            await write_platform_backfill.backfill(session)
        await session.rollback()

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        dry = await write_platform_backfill.run_backfill(factory, apply=False)
        assert dry[AUDIT] >= 1
        assert _audit_rows(owner_engine, tenant_b.shop_id)[-1][2] is None  # dry run wrote nothing
        applied = await write_platform_backfill.run_backfill(factory, apply=True)
        assert applied[AUDIT] == dry[AUDIT]
        again = await write_platform_backfill.run_backfill(factory, apply=True)
        assert again == {AUTHORIZATIONS: 0, AUDIT: 0}
    finally:
        await engine.dispose()
    assert _audit_rows(owner_engine, tenant_b.shop_id)[-1][:3] == ("pb-old", "tiktok", "pb-old")


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 106's parent, then back to head."""
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

    def present() -> bool:
        return all("platform_product_id" in _columns(owner_engine, t) for t in TABLES)

    def absent() -> bool:
        return not any(
            {"platform", "platform_product_id"} & set(_columns(owner_engine, t)) for t in TABLES
        )

    def current() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert present()
    command.downgrade(cfg, parent)
    assert current() == parent and absent()
    assert _security(owner_engine, AUDIT) == (True, {"SELECT", "INSERT"}, {"SELECT", "INSERT"})
    command.upgrade(cfg, "head")
    assert present()
