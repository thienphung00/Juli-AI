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
5. D73.4: the reviewer's Duyệt is the seller's own approve -- on the sandbox pin it creates
   the agent run (``workflow_runs`` + ``action_card_approvals`` under the seller's RLS scope,
   as ``juli_app``), enqueues it (faked) and audits ``reviewer_sandbox_approve``; it builds
   no TikTok client (the worker writes, through the sandbox factory);
6. D73.3: the "Tạo sản phẩm" card is inserted (once) under the seller's RLS scope and its
   approve starts the ``create_product`` run; 6b (P65, D74): likewise the "Tạo khuyến mãi"
   card and the ``create_promotion`` run.

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
from juli_backend.services.reviewer import config as reviewer_config
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
            f"/v1/demo/decisions/{world['card']}/approve",
            headers=_headers(world["reviewer"], reviewer_config.shop_alias_id(world["sandbox"])),
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


async def test_5_reviewer_approve_starts_the_agent_run_under_rls(app, world, monkeypatch):
    queued: list[Any] = []
    built: list[Any] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-1",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_approval_baseline",
        lambda shop_id, run_id: None,
    )
    monkeypatch.setattr(
        SandboxWriteClientFactory, "create_resources", lambda *a, **k: built.append(a)
    )
    async with await _client(app) as client:
        approve = await client.post(
            f"/v1/demo/decisions/{world['card']}/approve",
            headers=_headers(world["reviewer"], world["sandbox"]),
        )
    _assert_real_postgres_as_juli_app(app)
    assert approve.status_code == 202, approve.text
    run_id = approve.json()["data"]["run_id"]
    assert [str(r) for r in queued] == [run_id]
    assert built == []
    with owner_sync_engine() as engine, engine.connect() as conn:
        run = conn.execute(
            text("SELECT shop_id, workflow_key, status FROM public.workflow_runs WHERE id = :r"),
            {"r": run_id},
        ).one()
        approvals = conn.execute(
            text(
                "SELECT approved_by_user_id FROM public.action_card_approvals "
                "WHERE action_card_id = :c"
            ),
            {"c": world["card"]},
        ).all()
        audited = conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log "
                "WHERE action = 'reviewer_sandbox_approve' AND shop_id = :s"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
    assert run.shop_id == world["sandbox"]
    assert run.workflow_key == "optimize_product_2" and run.status == "queued"
    assert [row.approved_by_user_id for row in approvals] == [world["reviewer"]]
    assert audited == 1
    reviewer_sandbox.forget_sync_slots()


async def test_6_the_create_product_card_and_run_under_rls(app, world, monkeypatch):
    """D73.3: the reviewer's "Tạo sản phẩm" card is a real row (inserted under the seller's
    RLS scope as juli_app) and its approve starts the create_product run on the sandbox shop."""
    queued: list[Any] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-1",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_approval_baseline",
        lambda shop_id, run_id: None,
    )
    headers = _headers(world["reviewer"], world["sandbox"])
    async with await _client(app) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        again = await client.get("/v1/demo/decisions", headers=headers)
        assert listed.status_code == 200, listed.text
        cards = [
            item
            for item in listed.json()["data"]
            if (item["recommendation"].get("card") or {}).get("lever", {}).get("code")
            == "create_product"
        ]
        assert len(cards) == 1
        assert [i["id"] for i in again.json()["data"]].count(cards[0]["id"]) == 1
        approve = await client.post(f"/v1/demo/decisions/{cards[0]['id']}/approve", headers=headers)
    _assert_real_postgres_as_juli_app(app)
    assert approve.status_code == 202, approve.text
    run_id = approve.json()["data"]["run_id"]
    assert [str(r) for r in queued] == [run_id]
    with owner_sync_engine() as engine, engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT count(*) FROM public.action_cards "
                "WHERE shop_id = :s AND workflow_key = 'create_product'"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
        run = conn.execute(
            text("SELECT workflow_key, status FROM public.workflow_runs WHERE id = :r"),
            {"r": run_id},
        ).one()
    assert rows == 1
    assert run.workflow_key == "create_product" and run.status == "queued"
    reviewer_sandbox.forget_sync_slots()


async def test_6b_the_create_promotion_card_and_run_under_rls(app, world, monkeypatch):
    """P65 (D74): the reviewer's "Tạo khuyến mãi" card is a real row (inserted under the
    seller's RLS scope as juli_app, once) and its approve starts the create_promotion run on
    the sandbox shop, its opening context carrying the shop's discount range."""
    queued: list[Any] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-1",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_approval_baseline",
        lambda shop_id, run_id: None,
    )
    headers = _headers(world["reviewer"], world["sandbox"])
    async with await _client(app) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        again = await client.get("/v1/demo/decisions", headers=headers)
        assert listed.status_code == 200, listed.text
        cards = [
            item
            for item in listed.json()["data"]
            if (item["recommendation"].get("card") or {}).get("lever", {}).get("code")
            == "create_promotion"
        ]
        assert len(cards) == 1
        assert cards[0]["recommendation"]["card"]["workflow_label"] == "Khuyến mãi"
        assert [i["id"] for i in again.json()["data"]].count(cards[0]["id"]) == 1
        approve = await client.post(f"/v1/demo/decisions/{cards[0]['id']}/approve", headers=headers)
    _assert_real_postgres_as_juli_app(app)
    assert approve.status_code == 202, approve.text
    run_id = approve.json()["data"]["run_id"]
    assert [str(r) for r in queued] == [run_id]
    with owner_sync_engine() as engine, engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT count(*) FROM public.action_cards "
                "WHERE shop_id = :s AND workflow_key = 'create_promotion'"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
        run = conn.execute(
            text("SELECT workflow_key, status, state FROM public.workflow_runs WHERE id = :r"),
            {"r": run_id},
        ).one()
    assert rows == 1
    assert run.workflow_key == "create_promotion" and run.status == "queued"
    state = run.state if isinstance(run.state, dict) else json.loads(run.state)
    opening = json.loads(state["conversation_window"][0]["content"])
    assert opening["shop_rules"]["discount"]["max_pct"] == 30
    reviewer_sandbox.forget_sync_slots()


async def test_7_reviewer_sets_a_stability_band_on_the_sandbox_pin_under_rls(app, world):
    """P64 (D73.4): "Đặt ngưỡng" writes the sandbox shop's own ``shop_rules`` row as juli_app."""
    async with await _client(app) as client:
        put = await client.put(
            "/v1/demo/rules/stability_band",
            json={"scope_ref": "ctr", "value": 7.5, "set_by": "seller"},
            headers=_headers(world["reviewer"], world["sandbox"]),
        )
        read = await client.get(
            "/v1/demo/rules", headers=_headers(world["reviewer"], world["sandbox"])
        )
    _assert_real_postgres_as_juli_app(app)
    assert put.status_code == 200, put.text
    assert read.status_code == 200, read.text
    assert read.json()["data"]["stability_band"]["ctr"]["set_by"] == "seller"
    with owner_sync_engine() as engine, engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT shop_id, rule_key, scope_ref, set_by_user_id FROM public.shop_rules "
                "WHERE rule_key = 'stability_band' AND set_by_user_id = :u"
            ),
            {"u": world["reviewer"]},
        ).all()
    assert [(r.shop_id, r.scope_ref) for r in rows] == [(world["sandbox"], "ctr")]


async def test_8_a_production_pin_refuses_the_reviewers_rule_write(app, world):
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.production_write_shops (shop_id, enabled_by) VALUES (:s, 'o')"
            ),
            {"s": world["sandbox"]},
        )
    async with await _client(app) as client:
        put = await client.put(
            "/v1/demo/rules/stability_band",
            json={"scope_ref": "ctr", "value": 7.5, "set_by": "seller"},
            headers=_headers(world["reviewer"], reviewer_config.shop_alias_id(world["sandbox"])),
        )
    _assert_real_postgres_as_juli_app(app)
    assert put.status_code == 403
    assert put.headers["x-juli-reviewer-denied"] == "sandbox_only"
    with owner_sync_engine() as engine, engine.connect() as conn:
        written = conn.execute(
            text("SELECT count(*) FROM public.shop_rules WHERE shop_id = :s"),
            {"s": world["sandbox"]},
        ).scalar_one()
        refused = conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log "
                "WHERE action = 'reviewer_write_refused' AND shop_id = :s"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
    assert written == 0 and refused == 1
