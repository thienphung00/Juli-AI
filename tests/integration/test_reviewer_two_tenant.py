"""P32-A (D42) two-tenant proof on real Postgres, through the real app as ``juli_app``.

- ``ops_reviewer_accounts`` is unreadable / unwritable for ``juli_app``;
- a reviewer pinned to shop A reads A's cards (masked) through the seller routes
  under A's RLS scope, never B's; B's id -- or A's real id -- in ``X-Shop-Id``
  is 403;
- the simulation of A's card writes only the audit row; B's card is 404;
- a write route as the reviewer is 403 and changes nothing.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
from sqlalchemy import text

from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer.config import shop_alias_id
from tests.integration.two_tenant import juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

SECRET = "reviewer-two-tenant-secret-0123456789"
A_NAME = "Fujiwa Vietnam Store"
A_TITLE = "Nồi chiên không dầu Fujiwa 5L"
B_NAME = "Mộc Lan Fashion"
B_TITLE = "Áo thun nữ Mộc Lan"


def _payload(title: str, tiktok_id: str) -> str:
    return json.dumps(
        {
            "diagnosis": {
                "version": "adr106-v1",
                "as_of": "2026-10-13",
                "rank": 1,
                "status": "weak",
                "status_label": "Yếu",
                "stage": {"code": "card", "label": "Thẻ sản phẩm"},
                "lever": {"code": "title", "label": "Tiêu đề", "action": "Viết lại"},
                "main_kpi": {"key": "ctr", "label": "CTR", "value": "1,2%", "raw": 0.012},
                "trigger": {"code": "below_median", "gap": 0.3, "sentence": "CTR thấp"},
                "recoverable_gmv_per_day": 990000.0,
                "product_title": title,
                "tiktok_product_id": tiktok_id,
            }
        }
    )


@pytest.fixture(scope="module")
def world(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    reviewer_id = uuid.uuid4()
    cards = {}
    with owner_engine.begin() as conn:
        for tenant, name, title in ((tenant_a, A_NAME, A_TITLE), (tenant_b, B_NAME, B_TITLE)):
            conn.execute(
                text("UPDATE public.shops SET shop_name = :n WHERE id = :s"),
                {"n": name, "s": tenant.shop_id},
            )
            tiktok_id = conn.execute(
                text(
                    "UPDATE public.products SET title = :t WHERE id = :p "
                    "RETURNING tiktok_product_id"
                ),
                {"t": title, "p": tenant.product_id},
            ).scalar_one()
            card_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                    "subject_id, revision, priority, severity, title, description, "
                    "recommendation_payload, status, surfaced_at, computed_at) VALUES "
                    "(:id, :s, 'optimize_product_2', 'product', :p, 1, 1, 'medium', :title, '', "
                    ":payload, 'active', now(), now())"
                ),
                {
                    "id": card_id,
                    "s": tenant.shop_id,
                    "p": str(tenant.product_id),
                    "title": f"Tối ưu: {title}",
                    "payload": _payload(title, tiktok_id),
                },
            )
            cards[tenant.shop_id] = card_id
        conn.execute(
            text(
                "INSERT INTO public.ops_reviewer_accounts (id, user_id, email, role, platform, "
                "expires_at, created_by) VALUES (:id, :u, 'shopee-review@app-juli.com', "
                "'reviewer', 'shopee', :exp, 'owner@app-juli.com')"
            ),
            {
                "id": uuid.uuid4(),
                "u": reviewer_id,
                "exp": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
            },
        )
    return tenant_a, tenant_b, reviewer_id, cards


@pytest.fixture
def app(world, monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    tenant_a, *_ = world
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(tenant_a.shop_id))
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    reviewer_accounts.forget_cached()
    reviewer_catalog.forget_cached()
    application = create_app()

    async def _session():
        # Like production's get_session: what the request committed stays committed,
        # even when the request ends in an HTTPException (the gate commits the audit
        # row of a refused write, then raises 403).
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        from juli_backend.core.config.runtime import async_database_url

        engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SET ROLE juli_app"))
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
    return application


def _headers(user_id: uuid.UUID, shop: object | None) -> dict[str, str]:
    token = pyjwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "email": "shopee-review@app-juli.com",
            "email_verified": True,
            "session_id": "pg-session-1",
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


async def test_juli_app_cannot_touch_reviewer_accounts(world):
    tenant_a, *_ = world
    async with juli_app_session(tenant_a.shop_id) as session:
        with pytest.raises(Exception, match="permission denied"):
            await session.execute(text("SELECT * FROM public.ops_reviewer_accounts"))


async def test_reviewer_reads_only_the_pinned_shop(app, world, owner_engine):
    tenant_a, tenant_b, reviewer_id, cards = world
    alias = shop_alias_id(tenant_a.shop_id)
    async with await _client(app) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, None))
        listed = await client.get("/v1/demo/decisions", headers=_headers(reviewer_id, alias))
        as_b = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, tenant_b.shop_id)
        )
        as_a = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, tenant_a.shop_id)
        )
        sim_a = await client.post(
            f"/v1/reviewer/decisions/{cards[tenant_a.shop_id]}/simulate",
            json={"step": "execute"},
            headers=_headers(reviewer_id, alias),
        )
        sim_b = await client.post(
            f"/v1/reviewer/decisions/{cards[tenant_b.shop_id]}/simulate",
            json={"step": "execute"},
            headers=_headers(reviewer_id, alias),
        )
        approve = await client.post(
            f"/v1/demo/decisions/{cards[tenant_a.shop_id]}/approve",
            headers=_headers(reviewer_id, alias),
        )
    assert me.status_code == 200, me.text
    assert me.json()["shop"]["id"] == str(alias)
    assert listed.status_code == 200, listed.text
    ids = [c["id"] for c in listed.json()["data"]]
    assert str(cards[tenant_a.shop_id]) in ids and str(cards[tenant_b.shop_id]) not in ids
    for text_ in (me.text, listed.text, sim_a.text):
        for secret in (
            A_NAME,
            "Fujiwa",
            A_TITLE,
            B_NAME,
            B_TITLE,
            str(tenant_a.shop_id),
            str(tenant_b.shop_id),
        ):
            assert secret not in text_, secret
    assert as_b.status_code == 403 and as_a.status_code == 403
    assert sim_a.status_code == 200, sim_a.text
    assert sim_a.json()["simulated"] is True
    assert sim_b.status_code == 404
    assert approve.status_code == 403
    with owner_engine.connect() as conn:
        statuses = (
            conn.execute(
                text("SELECT status FROM public.action_cards WHERE id = ANY(:ids)"),
                {"ids": list(cards.values())},
            )
            .scalars()
            .all()
        )
        runs = conn.execute(
            text("SELECT count(*) FROM public.workflow_runs WHERE action_card_id = ANY(:ids)"),
            {"ids": list(cards.values())},
        ).scalar_one()
        audited = (
            conn.execute(
                text(
                    "SELECT action FROM public.ops_audit_log "
                    "WHERE actor_email = 'reviewer:shopee:shopee-review@app-juli.com' ORDER BY at"
                )
            )
            .scalars()
            .all()
        )
    assert set(statuses) == {"active"} and runs == 0
    assert "reviewer_sign_in" in audited
    assert "reviewer_simulated_execute" in audited
    assert "reviewer_write_refused" in audited
