"""P61-H (owner 2026-10-21, D71.6a): a credential WRITE that would create a cross-shop collision
with a ``sandbox_write`` credential is refused, with no partial write.

SQLite twin (the enumeration predicate runs as a plain query there). The PostgreSQL twin -- RLS,
the migration-100 function, as ``juli_app`` -- is
``tests/integration/test_p61h_oauth_sandbox_guard_two_shop_postgres.py``.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from juli_backend.core.security import (
    SandboxCollisionRefused,
    refuse_cross_shop_sandbox_collision,
    resolve_sandbox_write_credential,
)
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.tiktok.credential_binding import (
    ShopCipherUnresolvedError,
    backfill_shop_cipher,
)
from tests.support.builders import make_tenant, make_user, utc_now_naive


async def _issue(session, shop, capability, merchant, *, cipher=None):
    return await TikTokCredentialRepo(session).create(
        shop.id,
        "tok",
        "tok-refresh",
        utc_now_naive() + timedelta(days=30),
        merchant_authorization_id=merchant,
        capability=capability.value,
        shop_cipher=cipher,
    )


def _service(session, cipher):
    async def verifier(_session, *, capability, access_token):
        return cipher

    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
        session=session,
        redirect_uri="https://example.test/cb",
        app_secret="s",
        binding_verifier=verifier,
    )


def _token(open_id):
    return {
        "open_id": open_id,
        "access_token": "a",
        "refresh_token": "r",
        "seller_name": "Shop",
        "access_token_expire_in": 604800,
    }


async def _count(session, model):
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _sandbox_shop(session):
    _user, shop = await make_tenant(session)
    await _issue(session, shop, TikTokCapability.SANDBOX_WRITE, "sbx-merchant", cipher="SBX-CIPHER")
    return shop


async def test_seller_connect_on_the_sandbox_shop_is_refused_even_for_the_same_shop(session):
    """D73 (2026-10-22) tightens P61-H: the sandbox shop keeps only its `sandbox_write` row."""
    sandbox = await _sandbox_shop(session)
    sandbox_user_id, sandbox_id = sandbox.user_id, sandbox.id
    sandbox.tiktok_shop_id = "sbx-open-id"
    await session.flush()
    creds_before = await _count(session, TikTokCredential)

    with pytest.raises(SandboxCollisionRefused):
        await _service(session, "SBX-CIPHER").provision_shop_and_credentials(
            _token("sbx-open-id"),
            user_id=sandbox_user_id,
            capability=TikTokCapability.SELLER_CONNECT,
        )

    assert await _count(session, TikTokCredential) == creds_before
    assert (await resolve_sandbox_write_credential(session)).shop_id == sandbox_id


async def test_another_shops_oauth_carrying_the_sandbox_cipher_is_refused_without_a_write(
    session, caplog
):
    await _sandbox_shop(session)
    seller = await make_user(session)
    shops_before = await _count(session, Shop)
    creds_before = await _count(session, TikTokCredential)

    with caplog.at_level(logging.WARNING), pytest.raises(SandboxCollisionRefused) as refused:
        await _service(session, "SBX-CIPHER").provision_shop_and_credentials(
            _token("other-open-id"), user_id=seller.id
        )

    assert isinstance(refused.value, Unauthorized)
    assert "SBX-CIPHER" not in str(refused.value)
    assert await _count(session, Shop) == shops_before
    assert await _count(session, TikTokCredential) == creds_before
    record = next(
        r
        for r in caplog.records
        if r.message == "tiktok_credential_write_refused_sandbox_collision"
    )
    assert getattr(record, "operation") == "oauth_provision"
    # The sandbox is still usable afterwards.
    assert (
        await resolve_sandbox_write_credential(session)
    ).merchant_authorization_id == "sbx-merchant"


async def test_another_shops_oauth_carrying_the_sandbox_merchant_is_refused(session):
    await _sandbox_shop(session)
    seller = await make_user(session)
    creds_before = await _count(session, TikTokCredential)

    with pytest.raises(SandboxCollisionRefused):
        # merchant id == the OAuth open_id (D71.6); a different cipher does not save it.
        await _service(session, "OWN-CIPHER").provision_shop_and_credentials(
            _token("sbx-merchant"), user_id=seller.id
        )

    assert await _count(session, TikTokCredential) == creds_before


async def test_an_unrelated_shop_connects_normally(session):
    await _sandbox_shop(session)
    seller = await make_user(session)

    shop = await _service(session, "OWN-CIPHER").provision_shop_and_credentials(
        _token("seller-open-id"), user_id=seller.id
    )

    row = (
        await session.execute(select(TikTokCredential).where(TikTokCredential.shop_id == shop.id))
    ).scalar_one()
    assert (row.capability, row.shop_cipher) == ("seller_connect", "OWN-CIPHER")


async def test_a_sandbox_write_pointing_at_another_shops_cipher_is_refused(session):
    _user, prod = await make_tenant(session)
    await _issue(session, prod, TikTokCapability.SELLER_CONNECT, "prod-merchant", cipher="PROD-C")
    operator = await make_user(session)
    shops_before = await _count(session, Shop)
    creds_before = await _count(session, TikTokCredential)

    with pytest.raises(SandboxCollisionRefused):
        await _service(session, "PROD-C").provision_shop_and_credentials(
            _token("sbx-open-id"),
            user_id=operator.id,
            capability=TikTokCapability.SANDBOX_WRITE,
        )

    assert await _count(session, Shop) == shops_before
    assert await _count(session, TikTokCredential) == creds_before


async def test_a_sandbox_write_with_its_own_cipher_is_allowed(session):
    _user, prod = await make_tenant(session)
    await _issue(session, prod, TikTokCapability.SELLER_CONNECT, "prod-merchant", cipher="PROD-C")
    operator = await make_user(session)

    shop = await _service(session, "SBX-C").provision_shop_and_credentials(
        _token("sbx-open-id"), user_id=operator.id, capability=TikTokCapability.SANDBOX_WRITE
    )

    assert (await resolve_sandbox_write_credential(session)).shop_id == shop.id


async def test_a_reconnect_of_an_existing_shop_onto_the_sandbox_cipher_rolls_back_the_update(
    session,
):
    await _sandbox_shop(session)
    _user, seller_shop = await make_tenant(session, tiktok_shop_id="seller-open-id")
    row = await _issue(
        session, seller_shop, TikTokCapability.SELLER_CONNECT, "seller-open-id", cipher="OLD-C"
    )

    with pytest.raises(SandboxCollisionRefused):
        await _service(session, "SBX-CIPHER").provision_shop_and_credentials(
            _token("seller-open-id"), user_id=seller_shop.user_id
        )

    await session.refresh(row)
    assert row.shop_cipher == "OLD-C"


async def test_the_cipher_backfill_path_is_guarded(session):
    await _sandbox_shop(session)
    _user, seller_shop = await make_tenant(session)
    row = await _issue(session, seller_shop, TikTokCapability.SELLER_CONNECT, "m-seller")

    with pytest.raises(ShopCipherUnresolvedError):
        await backfill_shop_cipher(
            session,
            row,
            app_key="k",
            app_secret="s",
            lookup=lambda **_kw: {"cipher": "SBX-CIPHER"},
        )

    await session.refresh(row)
    assert row.shop_cipher is None
    assert row.status == "needs_reauth"


async def test_a_clean_backfill_and_a_token_refresh_are_not_blocked(session):
    await _sandbox_shop(session)
    _user, seller_shop = await make_tenant(session)
    row = await _issue(session, seller_shop, TikTokCapability.SELLER_CONNECT, "m-seller")

    assert (
        await backfill_shop_cipher(
            session, row, app_key="k", app_secret="s", lookup=lambda **_kw: {"cipher": "FINE-C"}
        )
        == "FINE-C"
    )
    # The refresh store rewrites tokens only -- identity columns are never touched by it.
    refreshed = await TikTokCredentialRepo(session).mark_refreshed(
        row.id, "a2", "r2", utc_now_naive() + timedelta(days=7)
    )
    assert (refreshed.shop_cipher, refreshed.merchant_authorization_id) == ("FINE-C", "m-seller")


async def test_a_preexisting_collision_is_not_blamed_on_an_unrelated_write(session):
    sandbox = await _sandbox_shop(session)
    _user, other = await make_tenant(session)
    await _issue(session, other, TikTokCapability.SELLER_CONNECT, "m-other", cipher="SBX-CIPHER")
    assert sandbox is not None

    async with refuse_cross_shop_sandbox_collision(session, operation="unrelated"):
        _user2, third = await make_tenant(session)
        await _issue(session, third, TikTokCapability.SELLER_CONNECT, "m-third", cipher="THIRD-C")
