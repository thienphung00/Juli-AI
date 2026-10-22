"""Two users, two shops, real Postgres, as `juli_app`: the OAuth callback writes under RLS (P61-I).

Owner 2026-10-22: production connects as `juli_app`; the TikTok redirect carries no JWT, so the
callback must open the owner's user scope for the shop and the shop's scope for the credential.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.core.security import SandboxCollisionRefused
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.services.tiktok import app_review_store
from tests.integration.test_p61h_oauth_sandbox_guard_two_shop_postgres import (
    _clear_sandbox,
    _credential,
    _shop,
)
from tests.support.postgres import juli_app_async_sessionmaker, owner_sync_engine, requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

CLAIMED_MESSAGE = "This TikTok shop is already connected to another account"


def _user(engine) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1556{user_id.hex[:7]}", "now": now},
        )
    return user_id


def _service(session, cipher: str) -> TikTokOAuthService:
    async def verifier(_session, *, capability, access_token):
        return cipher

    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
        session=session,
        redirect_uri="https://example.test/cb",
        app_secret="s",
        binding_verifier=verifier,
    )


def _token(open_id: str, access: str = "a") -> dict:
    return {
        "open_id": open_id,
        "access_token": access,
        "refresh_token": "r",
        "seller_name": "Shop B",
        "access_token_expire_in": 604800,
    }


def _rows(engine, open_id: str):
    with engine.connect() as conn:
        shops = conn.execute(
            text("SELECT id, user_id FROM public.shops WHERE tiktok_shop_id = :t"), {"t": open_id}
        ).all()
        creds = conn.execute(
            text(
                "SELECT c.shop_id, c.capability, c.shop_cipher FROM public.tiktok_credentials c "
                "WHERE c.merchant_authorization_id = :t"
            ),
            {"t": open_id},
        ).all()
    return shops, creds


async def _callback(user_id, open_id, cipher, access="a"):
    """One callback exactly as the route runs it: bare juli_app session, then commit."""
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        try:
            shop = await _service(session, cipher).provision_shop_and_credentials(
                _token(open_id, access), user_id=user_id
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        return shop.id


async def test_u1_connects_shop_b_as_juli_app_and_u2_is_refused_with_no_rows():
    tag = uuid.uuid4().hex[:10]
    open_id = f"p61i-{tag}"
    with owner_sync_engine() as engine:
        u1, u2 = _user(engine), _user(engine)

    shop_id = await _callback(u1, open_id, f"C{tag}")
    with owner_sync_engine() as engine:
        shops, creds = _rows(engine, open_id)
    assert [(s[0], s[1]) for s in shops] == [(shop_id, u1)]
    assert [(c[0], c[1], c[2]) for c in creds] == [(shop_id, "seller_connect", f"C{tag}")]

    with pytest.raises(Unauthorized, match=CLAIMED_MESSAGE):
        await _callback(u2, open_id, f"C{tag}", access="intruder")
    with owner_sync_engine() as engine:
        shops, creds = _rows(engine, open_id)
        owned_by_u2 = (
            engine.connect()
            .execute(text("SELECT count(*) FROM public.shops WHERE user_id = :u"), {"u": str(u2)})
            .scalar_one()
        )
    assert len(shops) == 1 and len(creds) == 1 and owned_by_u2 == 0


async def test_u1_reconnect_updates_in_place_and_resumes_a_paused_shop():
    tag = uuid.uuid4().hex[:10]
    open_id = f"p61i-re-{tag}"
    with owner_sync_engine() as engine:
        u1 = _user(engine)
    first = await _callback(u1, open_id, f"C{tag}", access="first")
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("UPDATE public.shops SET is_active = false WHERE id = :s"), {"s": str(first)}
        )

    second = await _callback(u1, open_id, f"C{tag}", access="second")
    assert second == first
    with owner_sync_engine() as engine:
        shops, creds = _rows(engine, open_id)
        active = (
            engine.connect()
            .execute(text("SELECT is_active FROM public.shops WHERE id = :s"), {"s": str(first)})
            .scalar_one()
        )
    assert len(shops) == 1 and len(creds) == 1 and active is True


async def test_the_collision_guard_still_refuses_under_the_new_scopes():
    tag = uuid.uuid4().hex[:10]
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        seller = _user(engine)
        sandbox_shop = _shop(engine, _user(engine), open_id=f"sbx-{tag}")
        _credential(
            engine,
            sandbox_shop,
            capability=TikTokCapability.SANDBOX_WRITE,
            merchant=f"sm-{tag}",
            cipher=f"S{tag}",
        )
    with pytest.raises(SandboxCollisionRefused):
        await _callback(seller, f"other-{tag}", f"S{tag}")
    with owner_sync_engine() as engine:
        shops, creds = _rows(engine, f"other-{tag}")
    assert shops == [] and creds == []  # no orphan shop, no credential


async def test_the_stateless_app_review_store_persists_as_juli_app(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    review_user = uuid.uuid4()
    monkeypatch.setenv("TIKTOK_APP_REVIEW_USER_ID", str(review_user))

    async def verifier(_session, *, capability, access_token):
        return f"R{tag}"

    monkeypatch.setattr(app_review_store, "make_binding_verifier", lambda **_kw: verifier)
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        await app_review_store.persist_oauth_tokens(session, _token(f"rev-{tag}"))
        await session.commit()
    with owner_sync_engine() as engine:
        shops, creds = _rows(engine, f"rev-{tag}")
        user_exists = (
            engine.connect()
            .execute(
                text("SELECT count(*) FROM public.users WHERE id = :u"), {"u": str(review_user)}
            )
            .scalar_one()
        )
    assert len(shops) == 1 and shops[0][1] == review_user and len(creds) == 1 and user_exists == 1
