"""``data_use_consents`` on real Postgres as ``juli_app`` (ADR-116 §2, D76, migration 103).

- RLS on; ``juli_app`` granted SELECT, INSERT and UPDATE of ``revoked_at`` only;
  one policy per verb;
- two tenants (ADR-089): a grant under shop A's scope is invisible under B's, B
  cannot insert or revoke one for A, and ``require_consent`` under B says no;
- a revoked grant cannot be reopened or re-dated; no DELETE; ``juli_app`` cannot
  UPDATE any other column;
- the partial unique index allows one open grant per (shop, scope);
- D10: accepting the Terms as ``juli_app`` grants the four Terms scopes to the
  seller's shop under RLS; the operator ``backfill-terms`` (``ops_list_shops()``
  under ``juli_ops``, each owner read under their user scope, each shop written
  under its own scope) grants them to accepting owners only, and a re-run is a no-op;
- the migration's downgrade drops the table and ``upgrade head`` restores it.

It downgrades a revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its own.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.consent import (
    ConsentRequired,
    grant_consent,
    has_consent,
    require_consent,
    revoke_consent,
)
from tests.integration.two_tenant import RUNTIME_ROLE, seed_tenant

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 26, 3, 0)


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


def _rows(owner_engine, shop_id: uuid.UUID) -> list[tuple]:
    with owner_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT scope, revoked_at FROM public.data_use_consents "
                    "WHERE shop_id = :shop ORDER BY created_at"
                ),
                {"shop": str(shop_id)},
            )
        )


async def _grant(session, shop_id, scope):
    return await grant_consent(
        session,
        shop_id,
        scope=scope,
        method="contract_paper",
        terms_version="v1",
        evidence_ref="contract.docx",
        granted_by="client",
        granted_at=NOW,
    )


def test_rls_on_and_juli_app_may_select_insert_and_revoke_only(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.data_use_consents'::regclass"
            )
        ).scalar_one()
        table_grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = 'data_use_consents' "
                    "AND grantee = :role"
                ),
                {"role": RUNTIME_ROLE},
            )
        }
        update_columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE table_schema = 'public' AND table_name = 'data_use_consents' "
                    "AND grantee = :role AND privilege_type = 'UPDATE'"
                ),
                {"role": RUNTIME_ROLE},
            )
        }
        policies = {
            row[0]
            for row in conn.execute(
                text("SELECT cmd FROM pg_policies WHERE tablename = 'data_use_consents'")
            )
        }
    assert rls is True
    assert table_grants == {"SELECT", "INSERT"}
    assert update_columns == {"revoked_at"}
    assert policies == {"SELECT", "INSERT", "UPDATE"}


@pytest.mark.asyncio
async def test_a_grant_belongs_to_its_shop_only(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        await _grant(session, tenant_a.shop_id, "llm_processing")
        await session.commit()
        assert await has_consent(session, tenant_a.shop_id, "llm_processing") is True

    async with app_session(tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.data_use_consents"))
        ).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}
        # A mis-scoped check reads "no grant", never A's yes.
        with pytest.raises(ConsentRequired):
            await require_consent(session, tenant_a.shop_id, "llm_processing")
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.data_use_consents (id, shop_id, scope, method, "
                    " terms_version, evidence_ref, granted_by, granted_at) "
                    "VALUES (:id, :shop, 'pooled_training', 'email', 'v', 'r', 'b', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()
        # B cannot revoke A's grant: the UPDATE policy sees no row.
        result = await session.execute(
            text("UPDATE public.data_use_consents SET revoked_at = now() WHERE shop_id = :shop"),
            {"shop": str(tenant_a.shop_id)},
        )
        assert result.rowcount == 0
        await session.rollback()
    assert _rows(owner_engine, tenant_a.shop_id) == [("llm_processing", None)]


@pytest.mark.asyncio
async def test_revoked_is_final_and_nothing_else_is_writable(owner_engine, two_tenants):
    tenant_a, _ = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        await _grant(session, tenant_a.shop_id, "pooled_training")
        await revoke_consent(session, tenant_a.shop_id, "pooled_training", revoked_at=NOW)
        await session.commit()

        # Reopening or re-dating a revoked grant touches no row.
        for value in ("NULL", "now()"):
            result = await session.execute(
                text(
                    f"UPDATE public.data_use_consents SET revoked_at = {value} "  # nosec B608
                    "WHERE shop_id = :shop AND scope = 'pooled_training'"
                ),
                {"shop": str(tenant_a.shop_id)},
            )
            assert result.rowcount == 0
        await session.commit()

        for statement in (
            "UPDATE public.data_use_consents SET scope = 'service' WHERE shop_id = :shop",
            "DELETE FROM public.data_use_consents WHERE shop_id = :shop",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(text(statement), {"shop": str(tenant_a.shop_id)})
            await session.rollback()

        assert await has_consent(session, tenant_a.shop_id, "pooled_training") is False
    assert ("pooled_training", NOW) in _rows(owner_engine, tenant_a.shop_id)


def test_one_open_grant_per_shop_and_scope(owner_engine, two_tenants):
    _, tenant_b = two_tenants
    insert = text(
        "INSERT INTO public.data_use_consents (id, shop_id, scope, method, terms_version, "
        " evidence_ref, granted_by, granted_at) "
        "VALUES (:id, :shop, 'service', 'email', 'v', 'r', 'b', now())"
    )
    with owner_engine.begin() as conn:
        conn.execute(insert, {"id": str(uuid.uuid4()), "shop": str(tenant_b.shop_id)})
    with pytest.raises(IntegrityError, match="uq_data_use_consents_open"):
        with owner_engine.begin() as conn:
            conn.execute(insert, {"id": str(uuid.uuid4()), "shop": str(tenant_b.shop_id)})


def test_check_constraints_refuse_bad_values(owner_engine, two_tenants):
    _, tenant_b = two_tenants
    base = {
        "scope": "llm_processing",
        "method": "email",
        "sha": None,
        "granted": "2026-10-26 03:00",
        "revoked": None,
    }
    for override in (
        {"scope": "everything"},
        {"method": "zalo"},
        {"sha": "NOT-A-HASH"},
        {"revoked": "2026-10-25 03:00"},
    ):
        values = {**base, **override, "id": str(uuid.uuid4()), "shop": str(tenant_b.shop_id)}
        with pytest.raises(IntegrityError, match="ck_data_use_consents"):
            with owner_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO public.data_use_consents (id, shop_id, scope, method, "
                        " terms_version, evidence_ref, evidence_sha256, granted_by, "
                        " granted_at, revoked_at) "
                        "VALUES (:id, :shop, :scope, :method, 'v', 'r', :sha, 'b', "
                        " :granted, :revoked)"
                    ),
                    values,
                )


TERMS_SCOPES = {"service", "llm_processing", "llm_images", "llm_media"}


@asynccontextmanager
async def _unscoped_app_session():
    """A ``juli_app`` session with no tenant GUC: what an operator CLI run starts from."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _accept_terms_as_owner(owner_engine, user_id: uuid.UUID) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE public.users SET terms_date_accepted = '2026-10-18', "
                "terms_accepted_at = '2026-10-20 02:30+00' WHERE id = :id"
            ),
            {"id": str(user_id)},
        )


@pytest.mark.asyncio
async def test_accepting_the_terms_as_juli_app_grants_the_terms_scopes(owner_engine):
    from juli_backend.services import privacy

    tenant = seed_tenant(owner_engine, label="tenant-accepts")
    async with _unscoped_app_session() as session:
        state = await privacy.record_consent(
            session, tenant.user_id, terms_date=privacy.LEGAL_TERMS_DATE, liability_clause=True
        )
        await session.commit()
    assert state.needs_terms_acceptance is False
    rows = _rows(owner_engine, tenant.shop_id)
    assert {scope for scope, revoked in rows if revoked is None} == TERMS_SCOPES
    assert len(rows) == len(TERMS_SCOPES)


@pytest.mark.asyncio
async def test_backfill_terms_grants_accepting_owners_only_and_reruns_as_a_noop(owner_engine):
    from juli_backend.services.consent import cli

    accepted = seed_tenant(owner_engine, label="tenant-backfill-accepted")
    never = seed_tenant(owner_engine, label="tenant-backfill-never")
    _accept_terms_as_owner(owner_engine, accepted.user_id)

    async def run(*argv):
        return await cli.run_command(
            cli.build_parser().parse_args(list(argv)), _unscoped_app_session
        )

    code, out = await run("backfill-terms")
    assert code == 0 and "DRY RUN" in out
    assert _rows(owner_engine, accepted.shop_id) == []

    code, out = await run("backfill-terms", "--apply")
    assert code == 0, out
    assert "failed_shops=0 failed_owners=0" in out
    assert {s for s, r in _rows(owner_engine, accepted.shop_id) if r is None} == TERMS_SCOPES
    assert _rows(owner_engine, never.shop_id) == []

    code, out = await run("backfill-terms", "--apply")
    assert code == 0 and "granted=0" in out
    assert len(_rows(owner_engine, accepted.shop_id)) == len(TERMS_SCOPES)


@pytest.mark.asyncio
async def test_operator_grant_and_revoke_one_shop_as_juli_app(owner_engine):
    from juli_backend.services.consent import cli

    tenant = seed_tenant(owner_engine, label="tenant-contract")
    base = ["--shop-id", str(tenant.shop_id), "--scope", "pooled_training"]
    grant = [
        "grant",
        *base,
        "--method",
        "contract_paper",
        "--terms-version",
        "hd-2026",
        "--evidence-ref",
        "contract.pdf",
        "--granted-by",
        "client director",
        "--apply",
    ]
    parser = cli.build_parser()
    code, out = await cli.run_command(parser.parse_args(grant), _unscoped_app_session)
    assert code == 0 and ": granted" in out
    code, out = await cli.run_command(
        parser.parse_args(["revoke", *base, "--apply"]), _unscoped_app_session
    )
    assert code == 0 and ": revoked" in out
    [(scope, revoked)] = _rows(owner_engine, tenant.shop_id)
    assert scope == "pooled_training" and revoked is not None


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 103's parent, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def exists() -> bool:
        with owner_engine.connect() as conn:
            return (
                conn.execute(text("SELECT to_regclass('public.data_use_consents')")).scalar_one()
                is not None
            )

    def head() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert exists()
    command.downgrade(cfg, "102_shops_tiktok_numeric_id")
    assert head() == "102_shops_tiktok_numeric_id" and not exists()
    command.upgrade(cfg, "head")
    assert exists()
