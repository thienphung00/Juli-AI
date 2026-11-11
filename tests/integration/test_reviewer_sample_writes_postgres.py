"""P100 S2-G on real Postgres under RLS, through the real app as ``juli_app``.

The unit twin is ``tests/unit/test_reviewer_sample_shopee.py`` (SQLite, no RLS). Here the loader
puts the synthetic sample shop in the database, a reviewer is pinned to it as the ``sample`` pin,
and the reviewer's own writes (owner Option A) run as ``juli_app`` in the shop's tenant scope:

- Duyệt on an open Tiêu đề / Ảnh bìa / Voucher card is the REAL approve (an approval row by the
  reviewer's user, the card ``approved``) and queues no fill job although the switch is on;
- Loại trừ and its undo, a plan card add: answered, the sample shop's rows only;
- each admitted write leaves one ``reviewer_sample_write`` audit row (written as ``juli_ops``
  inside the request's transaction before the route writes -- the P72 trap).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta

import jwt as pyjwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer import pin_cache
from scripts.sample_shop import loader
from scripts.sample_shop.generator import generate
from tests.support.postgres import owner_sync_engine, requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

SECRET = "reviewer-sample-writes-secret-0123456789"
END = date(2026, 11, 10)
NOW = datetime(2026, 11, 11, 3, 0)
REC = "/v1/demo/shopee/recommendations"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def world():
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        report = await loader.load(
            async_sessionmaker(engine, expire_on_commit=False), generate(END), now=NOW
        )
    finally:
        await engine.dispose()
    reviewer_id = uuid.uuid4()
    with owner_sync_engine() as owner, owner.begin() as conn:
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
    return {"shop": report.shop_id, "reviewer": reviewer_id}


@pytest.fixture
def app(world, monkeypatch):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("REVIEWER_SHOP_IDS", str(world["shop"]))
    monkeypatch.setenv("REVIEWER_SAMPLE_SHOP_IDS", str(world["shop"]))
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    reviewer_accounts.forget_cached()
    reviewer_catalog.forget_cached()
    pin_cache.forget_cached()
    application = create_app()
    roles: list[str] = []

    async def _session():
        from sqlalchemy.ext.asyncio import AsyncSession

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


def _headers(user_id: uuid.UUID, shop: uuid.UUID) -> dict[str, str]:
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
    return {"Authorization": f"Bearer {token}", "X-Shop-Id": str(shop)}


async def test_the_sample_reviewers_writes_run_as_juli_app_on_the_sample_shop_only(app, world):
    from httpx import ASGITransport, AsyncClient

    shop, reviewer = world["shop"], world["reviewer"]
    headers = _headers(reviewer, shop)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me = await client.get("/v1/reviewer/me", headers=headers)
        assert me.status_code == 200 and me.json()["mode"] == "sample", me.text
        listed = await client.get(f"{REC}?queue=all", headers=headers)
        assert listed.status_code == 200, listed.text
        card = next(
            c
            for c in listed.json()["cards"]
            if c["status"] == "sent" and c["change_kind"] in {"title", "cover_image"}
        )
        approved = await client.post(
            f"{REC}/{card['id']}/approve",
            json={"chosen_version": 1, "acknowledge_breaches": True},
            headers=headers,
        )
        excluded = await client.put(
            "/v1/demo/shopee/exclusions/9100000000003", json={"reason": "khac"}, headers=headers
        )
        undone = await client.delete("/v1/demo/shopee/exclusions/9100000000003", headers=headers)
        detail = await client.get(f"{REC}/{card['id']}", headers=headers)
    assert os.environ["DATABASE_URL"].startswith("postgresql")
    assert app.state.test_roles and set(app.state.test_roles) == {"juli_app"}
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved" and "simulated" not in approved.json()
    assert detail.json()["status"] == "approved"  # Đang thực hiện
    assert excluded.status_code == 200, excluded.text
    assert undone.status_code == 204, undone.text
    with owner_sync_engine() as owner, owner.connect() as conn:
        approval = conn.execute(
            text(
                "SELECT shop_id, decided_by_user_id FROM public.shop_proposal_approvals "
                "WHERE proposal_id = :p ORDER BY decided_at DESC LIMIT 1"
            ),
            {"p": uuid.UUID(card["id"])},
        ).one()
        jobs = conn.execute(
            text("SELECT count(*) FROM public.shopee_fill_jobs WHERE proposal_id = :p"),
            {"p": uuid.UUID(card["id"])},
        ).scalar_one()
        audited = conn.execute(
            text(
                "SELECT shop_id, after FROM public.ops_audit_log "
                "WHERE action = 'reviewer_sample_write' AND shop_id = :s ORDER BY at"
            ),
            {"s": shop},
        ).all()
    assert approval.shop_id == shop and approval.decided_by_user_id == reviewer
    assert jobs == 0
    assert [a.after["method"] for a in audited][-3:] == ["POST", "PUT", "DELETE"]
