"""Real Postgres, as `juli_app` under RLS: one grant's credentials refresh as one unit (P101 W2a).

Siblings live in other shops, invisible from the refreshing shop's scope; migration 132's
`SECURITY DEFINER` enumeration names them and the refresh writes each under its own scope. The
function answers only about a credential of the CURRENT shop, and never returns another
account's row. Seeding and read-back run as the owner.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy import text

from juli_backend.core.security.credential_refresh import RefreshStatus, refresh_credential
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.database.token_crypto import decrypt_token, encrypt_token
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _user(engine) -> uuid.UUID:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1557{user_id.hex[:7]}", "now": _now()},
        )
    return user_id


def _shop_with_credential(engine, user_id, *, grant_id, merchant) -> tuple[uuid.UUID, uuid.UUID]:
    shop_id, cred_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, created_at, "
                " updated_at) VALUES (:id, :u, :n, :t, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(user_id),
                "n": f"g-{shop_id.hex[:6]}",
                "t": f"g-{shop_id.hex}",
                "now": _now(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials (id, shop_id, merchant_authorization_id, "
                " capability, access_token, refresh_token, token_expires_at, status, "
                " refresh_count, grant_id, created_at, updated_at) "
                "VALUES (:id, :s, :m, 'seller_connect', :a, :r, :exp, 'active', 0, :g, :now, :now)"
            ),
            {
                "id": str(cred_id),
                "s": str(shop_id),
                "m": merchant,
                "a": encrypt_token("old-access"),
                "r": encrypt_token("old-refresh"),
                "exp": _now() + timedelta(hours=1),
                "g": str(grant_id),
                "now": _now(),
            },
        )
    return shop_id, cred_id


def _refresh_token_of(engine, cred_id) -> str:
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT refresh_token FROM public.tiktok_credentials WHERE id = :c"),
            {"c": str(cred_id)},
        ).scalar_one()
    return decrypt_token(raw)


async def test_a_refresh_rotates_every_sibling_of_the_grant_under_rls():
    grant_id, merchant = uuid.uuid4(), f"m-{uuid.uuid4().hex[:8]}"
    with owner_sync_engine() as engine:
        owner, stranger = _user(engine), _user(engine)
        shop_a, cred_a = _shop_with_credential(engine, owner, grant_id=grant_id, merchant=merchant)
        _, cred_b = _shop_with_credential(engine, owner, grant_id=grant_id, merchant=merchant)
        _, cred_c = _shop_with_credential(engine, stranger, grant_id=grant_id, merchant=merchant)
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": "new-a",
            "refresh_token": "new-r",
            "access_token_expire_in": 604800,
        }
    )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop_a):
            outcome = await refresh_credential(session, cred_a, auth=auth)

    assert outcome.status is RefreshStatus.REFRESHED
    with owner_sync_engine() as engine:
        assert _refresh_token_of(engine, cred_a) == "new-r"
        assert _refresh_token_of(engine, cred_b) == "new-r"
        assert _refresh_token_of(engine, cred_c) == "old-refresh"


async def test_the_enumeration_refuses_a_credential_outside_the_current_shop():
    grant_id, merchant = uuid.uuid4(), f"m-{uuid.uuid4().hex[:8]}"
    with owner_sync_engine() as engine:
        owner = _user(engine)
        _, cred_a = _shop_with_credential(engine, owner, grant_id=grant_id, merchant=merchant)
        shop_b, _ = _shop_with_credential(engine, owner, grant_id=grant_id, merchant=merchant)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop_b):
            rows = (
                await session.execute(
                    text("SELECT * FROM public.enumerate_grant_sibling_credentials(:c)"),
                    {"c": cred_a},
                )
            ).all()

    assert rows == []
