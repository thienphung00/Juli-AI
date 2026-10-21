"""P64 (D73, D73.2a) on real Postgres under RLS, through the real app as ``juli_app``.

The unit twin is ``tests/unit/test_reviewer_sandbox_live.py`` (SQLite, no RLS). Here:

1. a reviewer (reviewer claims, owns no shop) pinned to a shop holding ONLY a ``sandbox_write``
   row gets ``mode=sandbox``, ``writes_enabled=true`` -- the pin check reads the credentials,
   ``production_write_shops`` and migration 099/100's definer function inside the reviewer's
   read scope, as ``juli_app``;
2. the same shop with a ``production_write_shops`` row: writes disabled, masked;
3. ``resolve_read_credential_for_shop`` as ``juli_app`` returns the sandbox row for its own shop
   and refuses another shop;
4. ``enumerate_pollable_shops`` (migration 074's function + the P64 addition) lists it;
5. a reviewer execute resolves the sandbox credential under the reviewer's scope and builds
   exactly one ``SandboxWriteClientFactory`` client for the sandbox merchant (TikTok faked).

Every test asserts it really runs on Postgres as ``juli_app`` (no silent fallback).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from sqlalchemy import text

from juli_backend.core.security import (
    NoReadCredentialForShop,
    resolve_read_credential_for_shop,
)
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import SandboxWriteClientFactory, TikTokCapability
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

SECRET = "reviewer-sandbox-live-secret-0123456789"
PRODUCT_ID = "1730000000000000042"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _seed_shop(engine, *, name: str) -> uuid.UUID:
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO public.users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1555{user_id.hex[:7]}"},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id) "
                "VALUES (:id, :u, :n, :t)"
            ),
            {"id": shop_id, "u": user_id, "n": name, "t": f"76{shop_id.int % 10**17:017d}"},
        )
    return shop_id


def _seed_credential(engine, shop_id, *, capability: TikTokCapability, merchant: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, access_token, "
                " refresh_token, token_expires_at, scopes, status, refresh_count) "
                "VALUES (:id, :s, :m, :c, :ci, 'sbx-access', 'r', :exp, "
                " 'seller.product.basic', 'active', 0)"
            ),
            {
                "id": uuid.uuid4(),
                "s": shop_id,
                "m": merchant,
                "c": capability.value,
                "ci": f"cipher-{merchant}",
                "exp": _now() + timedelta(days=30),
            },
        )


def _seed_card(engine, shop_id) -> uuid.UUID:
    product_id, card_id = uuid.uuid4(), uuid.uuid4()
    payload = {
        "diagnosis": {
            "version": "adr106-v1",
            "as_of": "2026-10-21",
            "rank": 1,
            "status": "weak",
            "status_label": "Yếu",
            "stage": {"code": "card", "label": "Thẻ sản phẩm"},
            "lever": {"code": "title", "label": "Tiêu đề", "action": "Viết lại"},
            "main_kpi": {"key": "ctr", "label": "CTR", "value": "1,2%", "raw": 0.012},
            "trigger": {"code": "below_median", "gap": 0.3, "sentence": "CTR thấp"},
            "recoverable_gmv_per_day": 990000.0,
            "product_title": "Sandbox áo thun",
            "tiktok_product_id": PRODUCT_ID,
        }
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, title, "
                "status, update_time) VALUES (:id, :s, :t, 'Sandbox áo thun', "
                "'Sandbox áo thun', 'ACTIVATE', now())"
            ),
            {"id": product_id, "s": shop_id, "t": PRODUCT_ID},
        )
        conn.execute(
            text(
                "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                "subject_id, revision, priority, severity, title, description, "
                "recommendation_payload, status, surfaced_at, computed_at) VALUES "
                "(:id, :s, 'optimize_product_2', 'product', :p, 1, 1, 'medium', "
                "'Tối ưu tiêu đề', '', :payload, 'active', now(), now())"
            ),
            {"id": card_id, "s": shop_id, "p": str(product_id), "payload": json.dumps(payload)},
        )
    return card_id


def _seed_reviewer(engine) -> uuid.UUID:
    reviewer_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.ops_reviewer_accounts (id, user_id, email, role, platform, "
                "expires_at, created_by) VALUES (:id, :u, :e, 'reviewer', 'shopee', :exp, "
                "'owner@app-juli.com')"
            ),
            {
                "id": uuid.uuid4(),
                "u": reviewer_id,
                "e": f"shopee-review-{reviewer_id.hex[:6]}@app-juli.com",
                "exp": _now() + timedelta(days=30),
            },
        )
    return reviewer_id


def _clear_sandbox(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE capability = 'sandbox_write'")
        )


@pytest.fixture
def world():
    """A fresh sandbox shop (only its sandbox_write row), a production shop, a reviewer."""
    tag = uuid.uuid4().hex[:8]
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        sandbox_shop = _seed_shop(engine, name=f"Juli Sandbox {tag}")
        _seed_credential(
            engine,
            sandbox_shop,
            capability=TikTokCapability.SANDBOX_WRITE,
            merchant=f"sbx-{tag}",
        )
        production_shop = _seed_shop(engine, name=f"Production {tag}")
        _seed_credential(
            engine,
            production_shop,
            capability=TikTokCapability.PRODUCTION_READ,
            merchant=f"prod-{tag}",
        )
        card_id = _seed_card(engine, sandbox_shop)
        reviewer_id = _seed_reviewer(engine)
    return {
        "sandbox": sandbox_shop,
        "production": production_shop,
        "card": card_id,
        "reviewer": reviewer_id,
        "merchant": f"sbx-{tag}",
    }


@pytest.fixture
def app(world, monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(world["sandbox"]))
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    reviewer_accounts.forget_cached()
    reviewer_catalog.forget_cached()
    application = create_app()
    roles: list[str] = []

    async def _session():
        # Production's shape: one connection as juli_app; what a request commits stays.
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        from juli_backend.core.config.runtime import async_database_url

        engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SET ROLE juli_app"))
                roles.append((await conn.execute(text("SELECT current_user"))).scalar_one())
                await conn.commit()
                session = AsyncSession(
                    bind=conn, expire_on_commit=False, join_transaction_mode="rollback_only"
                )
                try:
                    yield session
                finally:
                    await session.close()
                    await conn.commit()
        finally:
            await engine.dispose()

    application.dependency_overrides[get_session] = _session
    application.state.test_roles = roles
    return application


def _headers(user_id: uuid.UUID, shop: object | None = None) -> dict[str, str]:
    token = pyjwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "email": "shopee-review@app-juli.com",
            "email_verified": True,
            "session_id": f"pg-{uuid.uuid4().hex[:6]}",
            "app_metadata": {"juli_role": "reviewer", "juli_platform": "shopee"},
        },
        SECRET,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    if shop is not None:
        headers["X-Shop-Id"] = str(shop)
    return headers


async def _client(app):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _assert_real_postgres_as_juli_app(app) -> None:
    assert os.environ["DATABASE_URL"].startswith("postgresql")
    assert app.state.test_roles and set(app.state.test_roles) == {"juli_app"}


async def test_1_reviewer_on_a_sandbox_only_shop_is_live(app, world):
    async with await _client(app) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(world["reviewer"]))
        shop = await client.get(
            "/v1/reviewer/shop", headers=_headers(world["reviewer"], world["sandbox"])
        )
    _assert_real_postgres_as_juli_app(app)
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["mode"] == "sandbox" and body["writes_enabled"] is True
    assert body["shop"]["id"] == str(world["sandbox"])  # unmasked
    assert shop.status_code == 200, shop.text
    assert shop.json()["connection"]["capability"] == "sandbox_write"
    assert shop.json()["connection"]["scopes"] == ["seller.product.basic"]
    assert "sbx-access" not in shop.text and world["merchant"] not in shop.text


async def test_2_a_production_write_row_on_the_pin_disables_writes(app, world):
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.production_write_shops (shop_id, enabled_by) VALUES (:s, 'o')"
            ),
            {"s": world["sandbox"]},
        )
    async with await _client(app) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(world["reviewer"]))
        execute = await client.post(
            f"/v1/reviewer/decisions/{world['card']}/execute",
            json={"title": "Mới"},
            headers=_headers(world["reviewer"]),
        )
    _assert_real_postgres_as_juli_app(app)
    assert me.status_code == 200, me.text
    assert me.json()["mode"] == "masked" and me.json()["writes_enabled"] is False
    assert str(world["sandbox"]) not in me.text  # masked again
    assert execute.status_code == 403
    assert execute.headers["x-juli-reviewer-denied"] == "sandbox_only"


async def test_3_sandbox_row_reads_only_its_own_shop_as_juli_app(world):
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "juli_app"
        async with with_shop_scope(session, world["sandbox"]):
            own = await resolve_read_credential_for_shop(session, world["sandbox"])
            assert own.shop_id == world["sandbox"]
            assert own.capability == TikTokCapability.SANDBOX_WRITE.value
            assert own.merchant_authorization_id == world["merchant"]
        other = _seed_shop_without_credentials()
        async with with_shop_scope(session, other):
            with pytest.raises(NoReadCredentialForShop):
                await resolve_read_credential_for_shop(session, other)
        async with with_shop_scope(session, world["production"]):
            prod = await resolve_read_credential_for_shop(session, world["production"])
            assert prod.capability == TikTokCapability.PRODUCTION_READ.value


def _seed_shop_without_credentials() -> uuid.UUID:
    with owner_sync_engine() as engine:
        return _seed_shop(engine, name="No credential")


async def test_4_the_sandbox_shop_is_pollable(world):
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "juli_app"
        pollable = {shop.shop_id for shop in await enumerate_pollable_shops(session)}
    assert world["sandbox"] in pollable
    assert world["production"] in pollable


async def test_5_reviewer_execute_resolves_the_sandbox_credential_under_rls(
    app, world, monkeypatch
):
    configs: list[Any] = []

    class FakeProducts:
        detail = {
            "id": PRODUCT_ID,
            "title": "Sandbox áo thun",
            "description": "<p>cũ</p>",
            "category_chains": [{"id": "601", "is_leaf": True}],
            "main_images": [{"uri": "tos-1"}],
        }

        def get_details(self, product_id):
            return dict(self.detail)

        def edit(self, *, product_id, body):
            self.detail = {**self.detail, "title": body["title"]}

    products = FakeProducts()

    def fake_resources(_factory, config):
        configs.append(config)
        return type("Resources", (), {"products": products})()

    monkeypatch.setattr(SandboxWriteClientFactory, "create_resources", fake_resources)
    async with await _client(app) as client:
        execute = await client.post(
            f"/v1/reviewer/decisions/{world['card']}/execute",
            json={"title": "Tiêu đề mới"},
            headers=_headers(world["reviewer"], world["sandbox"]),
        )
    _assert_real_postgres_as_juli_app(app)
    assert execute.status_code == 200, execute.text
    assert execute.json()["read_back"]["listing"]["title"] == "Tiêu đề mới"
    assert len(configs) == 1
    assert configs[0].merchant_auth_id == world["merchant"]
    assert configs[0].credential_capability == "sandbox_write"
    with owner_sync_engine() as engine, engine.connect() as conn:
        audited = conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log "
                "WHERE action = 'reviewer_sandbox_execute' AND shop_id = :s"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
    assert audited == 1
    reviewer_sandbox.forget_sync_slots()
