"""Two shops, real Postgres, as `juli_app`: a production write goes to the enabled
shop only, through its own credential (fast track P61-B, D71.2, migration 097).

Every ADR-085 gate is armed for both shops (global flag on, kill switch off, RLS
boot check recorded, release attested, an unconsumed authorization for each
shop's product). Only shop B has a `production_write_shops` row. Then, through
the real listing handler, the real resolver, the real per-shop credential
resolver and the real guarded production client -- with only the HTTP session
replaced by `tests/support/fakes.FakeTikTokTransport`, so nothing reaches TikTok:

- shop B's write is signed with B's own access token, and B alone gets a
  `production_write_audit` row (allowed, naming its authorization) and
  `run_write_values` rows; B's authorization is consumed;
- shop A's identical request never runs live: it takes the sandbox path, says
  `simulated`, sends nothing to the fake transport, and leaves A's
  authorization unconsumed and A without an audit row;
- the runtime role cannot turn a shop on by itself (SELECT only on the table),
  and under one shop's scope the other shop's enable row is invisible.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.integrations.tiktok import ProductionWriteClientFactory
from juli_backend.services.execution import listing_handlers
from juli_backend.services.execution import production_write as production_write_module
from juli_backend.services.execution.production_write_resolver import (
    record_rls_boot_check_passed,
)
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.fakes import FakeTikTokTransport

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

OPTIMIZE = "listing.optimize_product"
#: Per tenant: the TikTok product id, the merchant id and the token its own
#: credential carries. Test data only.
SHOP_DATA = {
    "a": ("910001", "p61b-merchant-a", "p61b-token-a"),
    "b": ("920002", "p61b-merchant-b", "p61b-token-b"),
}


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID):
    """A `juli_app` async session scoped to one shop whose commits really commit."""
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
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def seeded(owner_engine, two_tenants):
    """Per tenant: its own write credential, a product, a run, an authorization.
    Shop B (only) is turned on."""
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = {}
    with owner_engine.begin() as conn:
        for key, tenant in zip(("a", "b"), two_tenants, strict=True):
            product_tt, merchant, token = SHOP_DATA[key]
            product_id, run_id, auth_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.tiktok_credentials (id, shop_id, merchant_authorization_id,"
                    " capability, shop_cipher, access_token, refresh_token, token_expires_at,"
                    " status, refresh_count, created_at, updated_at) VALUES (:id, :shop,"
                    " :merchant, 'seller_connect', :cipher, :token, 'refresh', :expires,"
                    " 'active', 0, :now, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "shop": str(tenant.shop_id),
                    "merchant": merchant,
                    "cipher": f"cipher-{key}",
                    "token": token,
                    "expires": now + timedelta(days=30),
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status,"
                    " revenue, units_sold, update_time, created_at, updated_at) VALUES (:id,"
                    " :shop, :tt, 'p61b', 'ACTIVE', 0, 0, :now, :now, :now)"
                ),
                {"id": str(product_id), "shop": str(tenant.shop_id), "tt": product_tt, "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs (id, shop_id, product_id, state, status,"
                    " prompt_version, prompt_sha256, running_seconds_elapsed, cancel_requested,"
                    " subject_ref, created_at, updated_at) VALUES (:id, :shop, :product, :state,"
                    " 'completed', 'optimize_product.v3', :sha, 0, false, :product, :now, :now)"
                ),
                {
                    "id": str(run_id),
                    "shop": str(tenant.shop_id),
                    "product": str(product_id),
                    "state": json.dumps({}),
                    "sha": "0" * 64,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.production_write_authorizations (id, shop_id,"
                    " tiktok_product_id, mutation_kind, authorized_by, expires_at, created_at)"
                    " VALUES (:id, :shop, :tt, :kind, 'owner', :expires, :now)"
                ),
                {
                    "id": str(auth_id),
                    "shop": str(tenant.shop_id),
                    "tt": product_tt,
                    "kind": OPTIMIZE,
                    "expires": now + timedelta(hours=1),
                    "now": now,
                },
            )
            rows[key] = {"shop_id": tenant.shop_id, "run_id": run_id, "auth_id": auth_id}
        conn.execute(
            text(
                "INSERT INTO public.production_write_shops (shop_id, enabled_by, reason)"
                " VALUES (:shop, 'owner', 'P61-B two-shop proof')"
            ),
            {"shop": str(rows["b"]["shop_id"])},
        )
    return rows


@pytest.fixture
def armed(monkeypatch, tmp_path):
    """Every global ADR-085 gate on, a fake transport behind the real production factory."""
    sha = "b" * 40
    attestations = tmp_path / "attestations"
    attestations.mkdir()
    (attestations / f"{sha}.json").write_text(
        json.dumps({"release_sha": sha, "outcome": "pass", "performed_by": "test"})
    )
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    monkeypatch.setenv("PRODUCTION_WRITE_KILL_SWITCH", "false")
    monkeypatch.setenv("PRODUCTION_WRITE_ATTESTATION_DIR", str(attestations))
    monkeypatch.setenv("RELEASE_SHA", sha)
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    record_rls_boot_check_passed()

    transport = FakeTikTokTransport(
        {
            product: {"id": product, "title": f"{key} old", "description": f"{key} desc"}
            for key, (product, _merchant, _token) in SHOP_DATA.items()
        }
    )

    class _Factory(ProductionWriteClientFactory):
        def create(self, config):
            client = super().create(config)
            client._session = transport
            return client

    monkeypatch.setattr(production_write_module, "ProductionWriteClientFactory", _Factory)
    sandbox = AsyncMock(return_value=object())
    monkeypatch.setattr(
        "juli_backend.services.execution.sandbox_guard.load_sandbox_write_resources", sandbox
    )
    yield transport, sandbox
    from juli_backend.services.execution import production_write_resolver

    production_write_resolver._RLS_BOOT_CHECK_PASSED = False


def _payload(rows, key):
    product, _merchant, _token = SHOP_DATA[key]
    return {
        "_execution_shop_id": str(rows[key]["shop_id"]),
        "_execution_id": str(uuid.uuid4()),
        "_execution_workflow_run_id": str(rows[key]["run_id"]),
        "product_id": product,
        "edit_body": {"title": f"{key} new title"},
    }


def _scalar(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def _audit(owner_engine, shop_id):
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT authorization_id, precondition_name, run_id"
                " FROM public.production_write_audit WHERE shop_id = :shop"
            ),
            {"shop": str(shop_id)},
        ).all()


def _consumed(owner_engine, auth_id) -> bool:
    return (
        _scalar(
            owner_engine,
            "SELECT consumed_at FROM public.production_write_authorizations WHERE id = :id",
            id=str(auth_id),
        )
        is not None
    )


async def test_shop_a_is_never_written_live_without_its_enable_row(owner_engine, seeded, armed):
    transport, sandbox = armed
    chain = []

    def _sandbox_chain(resources, payload):
        chain.append(payload["product_id"])
        return {"product_id": payload["product_id"]}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(listing_handlers, "run_optimize_product_chain", _sandbox_chain)
        async with committing_juli_app_session(seeded["a"]["shop_id"]) as session:
            outcome = await listing_handlers.optimize_product_handler(
                session, _payload(seeded, "a")
            )

    assert outcome["write_mode"] == "simulated"
    assert chain == [SHOP_DATA["a"][0]]
    sandbox.assert_awaited_once()
    assert transport.calls == []
    assert not _consumed(owner_engine, seeded["a"]["auth_id"])
    assert _audit(owner_engine, seeded["a"]["shop_id"]) == []


async def test_shop_bs_live_write_uses_bs_credential_and_writes_only_bs_rows(
    owner_engine, seeded, armed
):
    transport, sandbox = armed
    shop_a, shop_b = seeded["a"]["shop_id"], seeded["b"]["shop_id"]
    product_b, _merchant_b, token_b = SHOP_DATA["b"]

    async with committing_juli_app_session(shop_b) as session:
        outcome = await listing_handlers.optimize_product_handler(session, _payload(seeded, "b"))

    assert outcome["write_mode"] == "live"
    assert outcome["authorization_id"] == str(seeded["b"]["auth_id"])
    sandbox.assert_not_awaited()
    # Every request went out under B's own token; the one write is B's listing edit.
    assert {call["access_token"] for call in transport.calls} == {token_b}
    (edit,) = transport.writes()
    assert edit["method"] == "PUT" and edit["path"].endswith(f"/products/{product_b}")
    assert transport.listings[product_b]["title"] == "b new title"
    assert transport.listings[SHOP_DATA["a"][0]]["title"] == "a old"

    # B: one allowed audit row naming its authorization and run; A: none.
    assert _audit(owner_engine, shop_b) == [(seeded["b"]["auth_id"], None, seeded["b"]["run_id"])]
    assert _audit(owner_engine, shop_a) == []
    assert _consumed(owner_engine, seeded["b"]["auth_id"])
    assert not _consumed(owner_engine, seeded["a"]["auth_id"])

    with owner_engine.connect() as conn:
        values = conn.execute(
            text(
                "SELECT shop_id, workflow_run_id, field, before_value, after_value"
                " FROM public.run_write_values WHERE tiktok_product_id = ANY(:products)"
            ),
            {"products": [SHOP_DATA["a"][0], product_b]},
        ).all()
    assert [(row[0], row[1], row[2]) for row in values] == [
        (shop_b, seeded["b"]["run_id"], "title")
    ]
    assert (values[0][3], values[0][4]) == ("b old", "b new title")


async def test_the_runtime_role_cannot_turn_a_shop_on_and_sees_only_its_own_row(seeded):
    shop_a, shop_b = seeded["a"]["shop_id"], seeded["b"]["shop_id"]
    async with committing_juli_app_session(shop_a) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.production_write_shops"))
        ).all()
        assert visible == []
        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text(
                    "INSERT INTO public.production_write_shops (shop_id, enabled_by)"
                    " VALUES (CAST(:shop AS uuid), 'app')"
                ).bindparams(shop=str(shop_a))
            )
        await session.rollback()
    async with committing_juli_app_session(shop_b) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.production_write_shops"))
        ).all()
        assert [row[0] for row in visible] == [shop_b]
