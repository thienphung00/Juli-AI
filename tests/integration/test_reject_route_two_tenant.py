"""Two tenants, real Postgres, through the real app as `juli_app`: "Từ chối" (fast track P61-D).

`POST /v1/demo/decisions/{id}/reject` under row-level security, with the real
`get_active_shop` setting the tenant scope from `X-Shop-Id`:

- shop B cannot reject shop A's card (404) and nothing is written anywhere;
- A's reject stores one reason, closes the card and writes one `dismissed`
  card event, all under A's scope;
- a repeat of A's reject is a 200 that writes nothing more (idempotent);
- after A rejected, B still gets 404 -- the idempotent answer is not an
  existence oracle.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


def _payload() -> str:
    return json.dumps(
        {
            "workflow_key": "optimize_product_2",
            "diagnosis": {
                "lever": {"code": "title"},
                "stage": {"code": "card"},
                "recoverable_gmv_basis": {"stage_rate": "ctr", "current_rate": 0.02},
            },
        }
    )


@pytest.fixture(scope="module")
def world(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    cards: dict[uuid.UUID, uuid.UUID] = {}
    with owner_engine.begin() as conn:
        for tenant in (tenant_a, tenant_b):
            card_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                    "subject_id, revision, priority, severity, title, description, "
                    "recommendation_payload, status, surfaced_at, computed_at) VALUES "
                    "(:id, :s, 'optimize_product_2', 'product', :p, 1, 1, 'warning', "
                    "'Viết lại tiêu đề', '', :payload, 'active', now(), now())"
                ),
                {
                    "id": card_id,
                    "s": tenant.shop_id,
                    "p": str(tenant.product_id),
                    "payload": _payload(),
                },
            )
            cards[tenant.shop_id] = card_id
    return tenant_a, tenant_b, cards


@pytest.fixture
def app(world, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from juli_backend.api.app import create_app
    from juli_backend.core.config.runtime import async_database_url
    from juli_backend.core.security import get_current_user
    from juli_backend.database import User, get_session

    application = create_app()
    acting: dict[str, uuid.UUID] = {}

    async def _session():
        # Like production's get_session, as the runtime role: what the request
        # committed stays committed; `get_active_shop` sets the tenant scope.
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

    async def _user():
        # The token check is not under test here; the tenant path after it is.
        return User(id=acting["user_id"], phone="+15550000000", display_name="seller")

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_current_user] = _user
    application.state.acting = acting
    return application


async def _reject(app, user_id: uuid.UUID, shop_id: uuid.UUID, card_id: uuid.UUID, code: str):
    from httpx import ASGITransport, AsyncClient

    app.state.acting["user_id"] = user_id
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            f"/v1/demo/decisions/{card_id}/reject",
            json={"reason_code": code},
            headers={"X-Shop-Id": str(shop_id)},
        )


def _state(owner_engine, card_id: uuid.UUID) -> tuple[str, int, int]:
    with owner_engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM public.action_cards WHERE id = :c"), {"c": card_id}
        ).scalar_one()
        reasons = conn.execute(
            text("SELECT count(*) FROM public.decision_reasons WHERE action_card_id = :c"),
            {"c": card_id},
        ).scalar_one()
        dismissed = conn.execute(
            text(
                "SELECT count(*) FROM public.card_events "
                "WHERE card_id = :c AND event_type = 'dismissed'"
            ),
            {"c": card_id},
        ).scalar_one()
    return status, reasons, dismissed


@pytest.mark.asyncio
async def test_b_cannot_reject_as_card_and_a_repeat_is_a_no_op(app, world, owner_engine):
    tenant_a, tenant_b, cards = world
    card_a = cards[tenant_a.shop_id]

    # B, under B's own shop scope, names A's card: not found, nothing written.
    cross = await _reject(app, tenant_b.user_id, tenant_b.shop_id, card_a, "other")
    assert cross.status_code == 404, cross.text
    assert _state(owner_engine, card_a) == ("active", 0, 0)

    # B cannot borrow A's scope either: A's shop id is not B's to name.
    borrowed = await _reject(app, tenant_b.user_id, tenant_a.shop_id, card_a, "other")
    assert borrowed.status_code in (403, 404), borrowed.text
    assert _state(owner_engine, card_a) == ("active", 0, 0)

    first = await _reject(app, tenant_a.user_id, tenant_a.shop_id, card_a, "not_convincing")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "rejected"
    assert _state(owner_engine, card_a) == ("dismissed", 1, 1)

    again = await _reject(app, tenant_a.user_id, tenant_a.shop_id, card_a, "other")
    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    assert _state(owner_engine, card_a) == ("dismissed", 1, 1), "a repeat wrote again"

    after = await _reject(app, tenant_b.user_id, tenant_b.shop_id, card_a, "other")
    assert after.status_code == 404, "the idempotent answer leaked A's card to B"

    # B's own card is untouched by all of the above.
    assert _state(owner_engine, cards[tenant_b.shop_id]) == ("active", 0, 0)
    with owner_engine.connect() as conn:
        b_rows = conn.execute(
            text("SELECT count(*) FROM public.decision_reasons WHERE shop_id = :s"),
            {"s": tenant_b.shop_id},
        ).scalar_one()
    assert b_rows == 0
