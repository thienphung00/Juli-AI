"""TDD tests for P2-A1 credential isolation (#296).

Acceptance criteria:
- Token lookup never crosses Fujiwa and SANDBOX_VN boundaries
- Tests assert cross-merchant lookup impossible
- Refresh flows merchant-scoped
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
    resolve_sandbox_write_credential,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
    is_cross_merchant_lookup,
    resolve_merchant_context,
)
from juli_backend.models.models import User
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
BASE_URL = "https://open-api.tiktokglobalshop.com"
REDIRECT_URI = "https://myapp.com/callback"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _far_expiry() -> datetime:
    return _utc_now() + timedelta(days=7)


def _near_expiry() -> datetime:
    return _utc_now() + timedelta(minutes=10)


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(
        app_key=APP_KEY, app_secret=APP_SECRET, base_url=BASE_URL
    )


@pytest.fixture
def oauth_service(tiktok_auth, session):
    return TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=REDIRECT_URI,
        app_secret=APP_SECRET,
    )


async def _seed_user(session, user_id):
    user = User(id=user_id, phone="+84901234567")
    session.add(user)
    await session.flush()
    return user


async def _create_merchant_credential(
    session,
    *,
    user_id,
    merchant_auth_id: str,
    capability: TikTokCapability,
    access_token: str,
    refresh_token: str = "refresh_token",
):
    shop = await ShopsRepo(session).create(
        user_id,
        f"Shop {merchant_auth_id[:8]}",
        merchant_auth_id,
    )
    return await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=_far_expiry(),
        merchant_authorization_id=merchant_auth_id,
        capability=capability.value,
    )


class TestMerchantContext:
    def test_resolve_merchant_context_fujiwa(self):
        auth_id, capability = resolve_merchant_context(PRODUCTION_AUTH_ID)
        assert auth_id == PRODUCTION_AUTH_ID
        assert capability == TikTokCapability.PRODUCTION_READ

    def test_resolve_merchant_context_sandbox(self):
        auth_id, capability = resolve_merchant_context(SANDBOX_AUTH_ID)
        assert auth_id == SANDBOX_AUTH_ID
        assert capability == TikTokCapability.SANDBOX_WRITE

    def test_resolve_merchant_context_unknown_seller(self):
        auth_id, capability = resolve_merchant_context("seller_abc")
        assert auth_id == "seller_abc"
        assert capability == TikTokCapability.SELLER_CONNECT

    def test_is_cross_merchant_lookup_rejects_capability_mismatch(self):
        assert is_cross_merchant_lookup(
            PRODUCTION_AUTH_ID, TikTokCapability.SANDBOX_WRITE
        )
        assert is_cross_merchant_lookup(
            SANDBOX_AUTH_ID, TikTokCapability.PRODUCTION_READ
        )

    def test_is_cross_merchant_lookup_allows_matching_pair(self):
        assert not is_cross_merchant_lookup(
            PRODUCTION_AUTH_ID, TikTokCapability.PRODUCTION_READ
        )
        assert not is_cross_merchant_lookup(
            SANDBOX_AUTH_ID, TikTokCapability.SANDBOX_WRITE
        )


class TestCredentialRepoIsolation:
    @pytest.mark.asyncio
    async def test_get_by_merchant_returns_matching_credential(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        created = await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_access",
        )

        fetched = await TikTokCredentialRepo(session).get_by_merchant(
            PRODUCTION_AUTH_ID, TikTokCapability.PRODUCTION_READ
        )

        assert fetched.id == created.id
        assert fetched.access_token == "fujiwa_access"

    @pytest.mark.asyncio
    async def test_cross_merchant_lookup_fujiwa_with_sandbox_capability_raises(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_access",
        )

        with pytest.raises(NotFound, match="No credentials for merchant"):
            await TikTokCredentialRepo(session).get_by_merchant(
                PRODUCTION_AUTH_ID, TikTokCapability.SANDBOX_WRITE
            )

    @pytest.mark.asyncio
    async def test_cross_merchant_lookup_sandbox_with_production_capability_raises(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_access",
        )

        with pytest.raises(NotFound, match="No credentials for merchant"):
            await TikTokCredentialRepo(session).get_by_merchant(
                SANDBOX_AUTH_ID, TikTokCapability.PRODUCTION_READ
            )

    @pytest.mark.asyncio
    async def test_create_rejects_cross_merchant_capability(self, session, user_id):
        await _seed_user(session, user_id)
        shop = await ShopsRepo(session).create(
            user_id, "Bad Shop", PRODUCTION_AUTH_ID
        )

        with pytest.raises(ValueError, match="do not match"):
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="token",
                refresh_token="refresh",
                token_expires_at=_far_expiry(),
                merchant_authorization_id=PRODUCTION_AUTH_ID,
                capability=TikTokCapability.SANDBOX_WRITE.value,
            )


class TestCredentialResolver:
    @pytest.mark.asyncio
    async def test_resolve_production_read_credential_returns_fujiwa_only(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_access",
        )
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_access",
        )

        credential = await resolve_production_read_credential(session)

        assert credential.access_token == "fujiwa_access"
        assert credential.merchant_authorization_id == PRODUCTION_AUTH_ID
        assert credential.capability == TikTokCapability.PRODUCTION_READ.value

    @pytest.mark.asyncio
    async def test_resolve_production_read_never_falls_back_to_sandbox_only(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_only",
        )

        with pytest.raises(NotFound):
            await resolve_production_read_credential(session)

    @pytest.mark.asyncio
    async def test_resolve_sandbox_write_credential_returns_sandbox_only(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_access",
        )
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_access",
        )

        credential = await resolve_sandbox_write_credential(session)

        assert credential.access_token == "sandbox_access"
        assert credential.merchant_authorization_id == SANDBOX_AUTH_ID
        assert credential.capability == TikTokCapability.SANDBOX_WRITE.value

    @pytest.mark.asyncio
    async def test_resolve_sandbox_write_never_falls_back_to_fujiwa_only(
        self, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_only",
        )

        with pytest.raises(NotFound):
            await resolve_sandbox_write_credential(session)


class TestMerchantScopedRefresh:
    @pytest.mark.asyncio
    async def test_refresh_merchant_tokens_scoped_to_fujiwa(
        self, oauth_service, tiktok_auth, session, user_id
    ):
        await _seed_user(session, user_id)
        fujiwa = await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_old",
            refresh_token="fujiwa_refresh",
        )
        sandbox = await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_old",
            refresh_token="sandbox_refresh",
        )
        fujiwa.token_expires_at = _near_expiry()
        sandbox.token_expires_at = _near_expiry()
        await session.flush()

        tiktok_auth.refresh_access_token = MagicMock(
            return_value={
                "access_token": "fujiwa_new",
                "refresh_token": "fujiwa_new_refresh",
                "access_token_expire_in": 604800,
            }
        )

        updated = await oauth_service.refresh_merchant_tokens(
            PRODUCTION_AUTH_ID, TikTokCapability.PRODUCTION_READ
        )

        assert updated.access_token == "fujiwa_new"
        tiktok_auth.refresh_access_token.assert_called_once_with("fujiwa_refresh")

        unchanged = await TikTokCredentialRepo(session).get_by_merchant(
            SANDBOX_AUTH_ID, TikTokCapability.SANDBOX_WRITE
        )
        assert unchanged.access_token == "sandbox_old"

    @pytest.mark.asyncio
    async def test_refresh_merchant_tokens_scoped_to_sandbox(
        self, oauth_service, tiktok_auth, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_old",
            refresh_token="fujiwa_refresh",
        )
        sandbox = await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
            access_token="sandbox_old",
            refresh_token="sandbox_refresh",
        )
        sandbox.token_expires_at = _near_expiry()
        await session.flush()

        tiktok_auth.refresh_access_token = MagicMock(
            return_value={
                "access_token": "sandbox_new",
                "refresh_token": "sandbox_new_refresh",
                "access_token_expire_in": 604800,
            }
        )

        updated = await oauth_service.refresh_merchant_tokens(
            SANDBOX_AUTH_ID, TikTokCapability.SANDBOX_WRITE
        )

        assert updated.access_token == "sandbox_new"
        tiktok_auth.refresh_access_token.assert_called_once_with("sandbox_refresh")

    @pytest.mark.asyncio
    async def test_refresh_merchant_tokens_rejects_cross_merchant_pair(
        self, oauth_service, session, user_id
    ):
        await _seed_user(session, user_id)
        await _create_merchant_credential(
            session,
            user_id=user_id,
            merchant_auth_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa_access",
        )

        with pytest.raises(NotFound):
            await oauth_service.refresh_merchant_tokens(
                PRODUCTION_AUTH_ID, TikTokCapability.SANDBOX_WRITE
            )
