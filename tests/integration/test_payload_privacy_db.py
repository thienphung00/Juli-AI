"""Payload allowlist, pseudonym keys and the clean-up on real Postgres (ADR-116 §4, migration 104).

- ``shop_pseudonym_keys``: RLS on; ``juli_app`` granted SELECT and INSERT only; one
  policy per verb;
- two tenants (ADR-089): A's key is invisible under B's scope, B cannot insert a
  key for A, and the same platform buyer gets different pseudonyms in A and B;
- a bronze order written as ``juli_app`` under its shop's scope stores no buyer
  field, and its ``buyer_id`` is the HMAC under the stored key;
- the clean-up command: ``juli_app`` may not apply it; as the owner a dry run
  changes nothing and creates no key, ``--apply`` cleans and re-keys, a second
  apply changes nothing;
- migration 104's downgrade drops the table and ``upgrade head`` restores it.

It downgrades a revision, so it is in
``tests/conftest.py::_DESTRUCTIVE_MIGRATION_MODULES`` and gets a database of its own.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.integrations.tiktok.mapping import normalize_order
from juli_backend.services.etl import append_targeted_order_payload
from juli_backend.services.privacy.payload_cleanup import _can_update, run_cleanup
from juli_backend.services.privacy.pseudonym import (
    buyer_pseudonym,
    pseudonymize_buyer_id,
    shop_pseudonym_key,
)
from tests.integration.two_tenant import RUNTIME_ROLE, seed_tenant

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests/fixtures/tiktok_privacy/order_search_202309_order.json"
BUYER = "7494011223344556677"
NOW = datetime(2026, 10, 26, 3, 0)
PII_MARKER = "PII_MARKER"


def _order() -> dict:
    data = json.loads(FIXTURE.read_text("utf-8"))
    data.pop("_source", None)
    return data


def _async_url() -> str:
    from juli_backend.core.config.runtime import async_database_url

    return async_database_url(os.environ["DATABASE_URL"])


@asynccontextmanager
async def app_session(shop_id: uuid.UUID):
    """A ``juli_app`` async session scoped to one shop whose commits really commit."""
    engine = create_async_engine(_async_url())
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


def _key_count(owner_engine, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM public.shop_pseudonym_keys WHERE shop_id = :s"),
            {"s": str(shop_id)},
        ).scalar_one()


def test_rls_on_and_juli_app_may_select_and_insert_only(owner_engine):
    with owner_engine.connect() as conn:
        rls = conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.shop_pseudonym_keys'::regclass"
            )
        ).scalar_one()
        grants = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND table_name = 'shop_pseudonym_keys' "
                    "AND grantee = :role"
                ),
                {"role": RUNTIME_ROLE},
            )
        }
        policies = {
            row[0]
            for row in conn.execute(
                text("SELECT cmd FROM pg_policies WHERE tablename = 'shop_pseudonym_keys'")
            )
        }
    assert rls is True
    assert grants == {"SELECT", "INSERT"}
    assert policies == {"SELECT", "INSERT"}


@pytest.mark.asyncio
async def test_keys_and_pseudonyms_belong_to_their_shop(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        a_id = await pseudonymize_buyer_id(session, tenant_a.shop_id, BUYER)
        await session.commit()
    assert _key_count(owner_engine, tenant_a.shop_id) == 1

    async with app_session(tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.shop_pseudonym_keys"))
        ).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}
        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.shop_pseudonym_keys (id, shop_id, key_ciphertext) "
                    "VALUES (:id, :shop, 'enc:p1:shop_pseudonym_key:x')"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()
        for statement in (
            "UPDATE public.shop_pseudonym_keys SET key_ciphertext = 'enc:p1:shop_pseudonym_key:y'",
            "DELETE FROM public.shop_pseudonym_keys",
        ):
            with pytest.raises(DBAPIError, match="permission denied"):
                await session.execute(text(statement))
            await session.rollback()
        b_id = await pseudonymize_buyer_id(session, tenant_b.shop_id, BUYER)
        await session.commit()
    assert a_id != b_id
    assert _key_count(owner_engine, tenant_a.shop_id) == 1


@pytest.mark.asyncio
async def test_a_bronze_order_written_as_juli_app_stores_no_buyer_field(owner_engine, two_tenants):
    tenant_a, _ = two_tenants
    async with app_session(tenant_a.shop_id) as session:
        await append_targeted_order_payload(
            session,
            shop_id=tenant_a.shop_id,
            payload=normalize_order(_order()),
            received_at=datetime(2026, 10, 26, 3, 0, tzinfo=UTC),
            source_event_id="privacy-db-1",
        )
        key = await shop_pseudonym_key(session, tenant_a.shop_id)
        await session.commit()
    with owner_engine.connect() as conn:
        payload = conn.execute(
            text(
                "SELECT payload FROM bronze.order_raw_payloads "
                "WHERE shop_id = :s AND source_event_id = 'privacy-db-1'"
            ),
            {"s": str(tenant_a.shop_id)},
        ).scalar_one()
    assert PII_MARKER not in json.dumps(payload, ensure_ascii=False)
    assert "recipient_address" not in payload and "user_id" not in payload
    assert payload["buyer_id"] == buyer_pseudonym(key, BUYER)


def _seed_legacy(owner_engine, shop_id: uuid.UUID) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO bronze.order_raw_payloads (id, shop_id, received_at, "
                " ingest_source, payload, tiktok_order_id, source_event_id) "
                "VALUES (:id, :shop, :now, 'targeted_fetch', CAST(:payload AS json), 'o1', "
                " 'legacy-1')"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop": str(shop_id),
                "now": NOW,
                "payload": json.dumps(normalize_order(_order())),
            },
        )


def _legacy_payload(owner_engine, shop_id: uuid.UUID) -> dict:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT payload FROM bronze.order_raw_payloads "
                "WHERE shop_id = :s AND source_event_id = 'legacy-1'"
            ),
            {"s": str(shop_id)},
        ).scalar_one()


@pytest.mark.asyncio
async def test_cleanup_is_refused_to_juli_app_and_dry_run_then_apply_as_owner(
    owner_engine, two_tenants
):
    # A tenant of its own: the two shared ones already hold keys from the tests above.
    tenant_b = seed_tenant(owner_engine, label="tenant-cleanup")
    _seed_legacy(owner_engine, tenant_b.shop_id)
    assert _key_count(owner_engine, tenant_b.shop_id) == 0

    async with app_session(tenant_b.shop_id) as session:
        assert await _can_update(session) is False

    engine = create_async_engine(_async_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            assert await _can_update(session) is True

        dry = await run_cleanup(factory, apply=False, only=[tenant_b.shop_id])
        assert dry.tables["bronze.order_raw_payloads"].changed == 1
        assert PII_MARKER in json.dumps(_legacy_payload(owner_engine, tenant_b.shop_id))
        assert _key_count(owner_engine, tenant_b.shop_id) == 0

        applied = await run_cleanup(factory, apply=True)
        assert applied.shops >= 3
        assert applied.tables["bronze.order_raw_payloads"].changed == 1
        cleaned = _legacy_payload(owner_engine, tenant_b.shop_id)
        assert PII_MARKER not in json.dumps(cleaned, ensure_ascii=False)
        assert _key_count(owner_engine, tenant_b.shop_id) == 1

        again = await run_cleanup(factory, apply=True)
        assert all(count.changed == 0 for count in again.tables.values())
    finally:
        await engine.dispose()

    async with app_session(tenant_b.shop_id) as session:
        key = await shop_pseudonym_key(session, tenant_b.shop_id)
    assert cleaned["buyer_id"] == buyer_pseudonym(key, BUYER)


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 104's parent, then back to head."""
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    parent = ScriptDirectory.from_config(cfg).get_revision("104_shop_pseudonym_keys").down_revision

    def exists() -> bool:
        with owner_engine.connect() as conn:
            return (
                conn.execute(text("SELECT to_regclass('public.shop_pseudonym_keys')")).scalar_one()
                is not None
            )

    def current() -> str:
        with owner_engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert exists()
    command.downgrade(cfg, parent)
    assert current() == parent and not exists()
    command.upgrade(cfg, "head")
    assert exists()
