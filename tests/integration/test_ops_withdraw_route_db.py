"""Ops "Gỡ thẻ" through the real routes on real Postgres, as ``juli_app`` with the staff gate:
the single-card and the bulk withdraw answer 200 and write their audit row (2026-11-06: a 500
"Internal server error" on ORY). Synthetic only."""

from __future__ import annotations

import copy
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from juli_backend.api.app import create_app
from juli_backend.database import get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import product_queue, store
from tests.integration.test_shopee_reco_db import NOW, stub_card
from tests.support.postgres import juli_app_async_sessionmaker, requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

JWT_SECRET = secrets.token_urlsafe(32)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    from juli_backend.services.ops import staff as ops_staff

    ops_staff.clear_staff_cache()


@pytest.fixture
def staff_user(owner_engine):
    user_id = uuid.uuid4()
    email = f"wd-{user_id.hex[:8]}@app-juli.com"
    now = datetime.now(UTC).replace(tzinfo=None)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, email, display_name, created_at, updated_at)"
                " VALUES (:id, :phone, :email, 'Ops tester', :now, :now)"
            ),
            {"id": user_id, "phone": f"+1557{user_id.hex[:7]}", "email": email, "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.ops_staff (id, email, role, active, user_id)"
                " VALUES (:id, :email, 'operator', true, :user_id)"
            ),
            {"id": uuid.uuid4(), "email": email, "user_id": user_id},
        )
    return user_id, email


def _token(user_id: uuid.UUID, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "email": email,
        "user_metadata": {"email": email, "email_verified": True, "full_name": "Ops tester"},
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest_asyncio.fixture
async def client(staff_user) -> AsyncIterator[tuple[AsyncClient, dict[str, str], object]]:
    user_id, email = staff_user
    async with juli_app_async_sessionmaker() as factory:
        app = create_app()

        async def per_request_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = per_request_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c, {"Authorization": f"Bearer {_token(user_id, email)}"}, factory


def _card(item: str, score: float) -> dict:
    card = stub_card(item, "ads_budget")
    card["rank"] = {"position": 1, "score": score}
    card["versions"] = [{"version": 1, "status": "ok", "ranked": True, "label": "x"}]
    return card


async def _sent_cards(factory, shop_id, n: int) -> list[uuid.UUID]:
    async with factory() as session:
        async with with_shop_scope(session, shop_id):
            ids = [
                await store.save_card(
                    session,
                    shop_id,
                    copy.deepcopy(_card("7001", 1.0 - k / 10)),
                    cycle="2026-11",
                    position=1,
                    now=NOW,
                )
                for k in range(n)
            ]
            await product_queue.requeue_products(session, shop_id, ["7001"], NOW)
            await reco.publish(session, shop_id, ids, now=NOW)
        await session.commit()
    return ids


async def _audit_rows(owner_engine, shop_id) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log"
                " WHERE shop_id = :s AND action = 'reco_withdraw'"
            ),
            {"s": shop_id},
        ).scalar_one()


async def test_single_and_bulk_withdraw_answer_200_and_are_audited(
    shopee_tenants, client, owner_engine
):
    a, _ = shopee_tenants
    c, headers, factory = client
    ids = await _sent_cards(factory, a.shop_id, 3)
    before = await _audit_rows(owner_engine, a.shop_id)
    base = f"/v1/ops/shops/{a.shop_id}/shopee/recommendations"

    one = await c.post(
        f"{base}/{ids[0]}/withdraw",
        headers=headers,
        json={"reason_code": "not_fit", "note": "lỗi"},
    )
    assert one.status_code == 200, one.text
    many = await c.post(
        f"{base}/withdraw",
        headers=headers,
        json={"card_ids": [str(ids[1]), str(ids[2])], "reason_code": "not_fit", "note": "lỗi"},
    )
    assert many.status_code == 200, many.text
    assert sorted(many.json()["withdrawn"]) == sorted([str(ids[1]), str(ids[2])])
    assert await _audit_rows(owner_engine, a.shop_id) == before + 2


@pytest.mark.parametrize("state", ["approved", "changes_requested"])
async def test_single_withdraw_of_a_card_the_seller_already_acted_on(
    shopee_tenants, client, owner_engine, state
):
    a, _ = shopee_tenants
    c, headers, factory = client
    ids = await _sent_cards(factory, a.shop_id, 2)
    async with factory() as session:
        async with with_shop_scope(session, a.shop_id):
            decision = "approve" if state == "approved" else "request_change"
            await reco.decide(
                session, a.shop_id, ids[0], decision=decision, user_id=a.user_id, now=NOW
            )
        await session.commit()
    before = await _audit_rows(owner_engine, a.shop_id)
    base = f"/v1/ops/shops/{a.shop_id}/shopee/recommendations"
    one = await c.post(
        f"{base}/{ids[0]}/withdraw", headers=headers, json={"reason_code": "not_fit", "note": "lỗi"}
    )
    assert one.status_code == 200, one.text
    assert await _audit_rows(owner_engine, a.shop_id) == before + 1


SHOP_VOUCHERS = [
    {
        "kind": "voucher",
        "scope": "shop",
        "discount_type": "amount",
        "value": value,
        "min_spend": spend,
        "label": f"{value}/{spend}",
    }
    for value, spend in [(5000, 100_000), (10_000, 100_000), (10_000, 150_000), (15_000, 200_000)]
]


async def test_single_withdraw_of_a_shop_wide_builder_card(client, owner_engine):
    """2026-11-06, ORY JC-2611-0027: a builder-made shop-wide voucher (no product, 4 versions,
    draft). With no product there is no queue to renumber, so nothing flushed the card's
    ``withdrawn`` metadata before the audit row was written under ``juli_ops`` -- which has no
    grant on ``action_cards`` -- and the request answered 500 "permission denied"."""
    import os

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from juli_backend.core.config.runtime import async_database_url
    from tests.support.shopee_reco import AS_OF, seed_reco_shop

    c, headers, _ = client
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            seeded = await seed_reco_shop(session)
            await session.commit()
    finally:
        await engine.dispose()
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee"
    chosen = await c.post(
        f"{base}/builder/choose",
        headers=headers,
        json={"versions": SHOP_VOUCHERS, "chosen": 0, "as_of": AS_OF.isoformat()},
    )
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["status"] == "draft" and not chosen.json()["card"]["scope"]["product_ids"]
    card_id = chosen.json()["id"]
    before = await _audit_rows(owner_engine, seeded.shop_id)

    one = await c.post(
        f"{base}/recommendations/{card_id}/withdraw",
        headers=headers,
        json={"reason_code": "not_fit", "note": "lỗi"},
    )

    assert one.status_code == 200, one.text
    assert await _audit_rows(owner_engine, seeded.shop_id) == before + 1
    with owner_engine.connect() as conn:
        status, meta = conn.execute(
            text(
                "SELECT p.status, a.metadata_json FROM shop_proposals p"
                " JOIN action_cards a ON a.id = p.id WHERE p.id = :id"
            ),
            {"id": card_id},
        ).one()
    assert status == "withdrawn" and '"reason_code": "not_fit"' in meta
