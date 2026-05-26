"""TDD tests for TikTok OAuth service (issue #30).

AC → Test Mapping:
- AC1 → test_initiate_oauth_returns_valid_url
- AC2 → test_oauth_callback_provisions_shop
- AC3 → test_token_refresh_before_expiry
- AC4 → test_multi_shop_oauth_connection
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio

from src.auth.exceptions import Unauthorized
from src.auth.tiktok_oauth import REFRESH_BUFFER, TikTokOAuthService
from src.data.models import User
from src.data.repos import ShopsRepo, TikTokCredentialRepo
from src.integrations.tiktok.auth import TikTokAuth

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
BASE_URL = "https://open-api.tiktokglobalshop.com"
REDIRECT_URI = "https://myapp.com/callback"


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(
        app_key=APP_KEY, app_secret=APP_SECRET, base_url=BASE_URL
    )


@pytest_asyncio.fixture
async def user(session, user_id):
    u = User(id=user_id, phone="+84901234567")
    session.add(u)
    await session.flush()
    return u


@pytest.fixture
def service(tiktok_auth, session):
    return TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=REDIRECT_URI,
        app_secret=APP_SECRET,
    )


def _mock_exchange(tiktok_auth, **overrides):
    defaults = {
        "access_token": "ROW_access_abc",
        "refresh_token": "ROW_refresh_xyz",
        "access_token_expire_in": 604800,
        "open_id": "seller_123",
        "seller_name": "Test Shop",
    }
    defaults.update(overrides)
    tiktok_auth.exchange_code = MagicMock(return_value=defaults)
    return defaults


def _extract_state(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


# ---------------------------------------------------------------------------
# AC1 — initiate_tiktok_oauth returns valid authorization URL
# ---------------------------------------------------------------------------


class TestInitiateOAuth:
    @pytest.mark.asyncio
    async def test_initiate_oauth_returns_valid_url(
        self, service, user, user_id
    ):
        url = await service.initiate_oauth(user_id)

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert "tiktokshop.com" in parsed.netloc
        assert params["app_key"] == [APP_KEY]
        assert params["redirect_uri"] == [REDIRECT_URI]
        assert "state" in params
        assert len(params["state"][0]) > 10

    @pytest.mark.asyncio
    async def test_initiate_oauth_unique_states(
        self, service, user, user_id
    ):
        """Each call produces a unique state (nonce prevents replay)."""
        url1 = await service.initiate_oauth(user_id)
        url2 = await service.initiate_oauth(user_id)
        assert _extract_state(url1) != _extract_state(url2)


# ---------------------------------------------------------------------------
# AC2 — handle_oauth_callback provisions shop + credential
# ---------------------------------------------------------------------------


class TestOAuthCallback:
    @pytest.mark.asyncio
    async def test_oauth_callback_provisions_shop(
        self, service, tiktok_auth, session, user, user_id
    ):
        _mock_exchange(tiktok_auth)

        url = await service.initiate_oauth(user_id)
        state = _extract_state(url)

        shop = await service.handle_callback("auth_code_123", state)

        assert shop.user_id == user_id
        assert shop.shop_name == "Test Shop"
        assert shop.tiktok_shop_id == "seller_123"

        cred = await TikTokCredentialRepo(session).get_by_shop(shop.id)
        assert cred.access_token == "ROW_access_abc"
        assert cred.refresh_token == "ROW_refresh_xyz"
        assert cred.token_expires_at > datetime.now(timezone.utc).replace(
            tzinfo=None
        )

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_tampered_state(
        self, service, user, user_id
    ):
        with pytest.raises(Unauthorized, match="signature"):
            await service.handle_callback("code", "tampered.state")

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_malformed_state(
        self, service, user, user_id
    ):
        with pytest.raises(Unauthorized, match="Invalid OAuth state"):
            await service.handle_callback("code", "no_dot_separator")

    @pytest.mark.asyncio
    async def test_oauth_callback_reconnects_existing_shop(
        self, service, tiktok_auth, session, user, user_id
    ):
        """Reconnecting the same TikTok shop updates credentials, not duplicates."""
        _mock_exchange(tiktok_auth)

        url1 = await service.initiate_oauth(user_id)
        shop1 = await service.handle_callback("code_1", _extract_state(url1))

        url2 = await service.initiate_oauth(user_id)
        shop2 = await service.handle_callback("code_2", _extract_state(url2))

        assert shop1.id == shop2.id
        shops = await ShopsRepo(session).list(user_id)
        assert len(shops) == 1

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_shop_claimed_by_another_user(
        self, tiktok_auth, session, user_id, other_user_id
    ):
        """A TikTok shop already connected to another user cannot be claimed."""
        other_user = User(id=other_user_id, phone="+84909999999")
        session.add(other_user)
        await session.flush()

        other_service = TikTokOAuthService(
            tiktok_auth=tiktok_auth,
            session=session,
            redirect_uri=REDIRECT_URI,
            app_secret=APP_SECRET,
        )
        _mock_exchange(tiktok_auth, open_id="contested_shop")

        url1 = await other_service.initiate_oauth(other_user_id)
        await other_service.handle_callback("code_other", _extract_state(url1))

        current_user = User(id=user_id, phone="+84901234567")
        session.add(current_user)
        await session.flush()

        service = TikTokOAuthService(
            tiktok_auth=tiktok_auth,
            session=session,
            redirect_uri=REDIRECT_URI,
            app_secret=APP_SECRET,
        )
        url2 = await service.initiate_oauth(user_id)

        with pytest.raises(Unauthorized, match="already connected"):
            await service.handle_callback("code_mine", _extract_state(url2))


# ---------------------------------------------------------------------------
# AC3 — refresh_tiktok_tokens proactively refreshes before expiry
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_token_refresh_before_expiry(
        self, service, tiktok_auth, session, user, user_id
    ):
        shop = await ShopsRepo(session).create(
            user_id, "Expiring Shop", "shop_exp"
        )
        near_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)
        await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="old_access",
            refresh_token="old_refresh",
            token_expires_at=near_expiry,
        )

        tiktok_auth.refresh_access_token = MagicMock(
            return_value={
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "access_token_expire_in": 604800,
            }
        )

        credential = await service.refresh_tokens(shop.id)

        assert credential.access_token == "new_access_token"
        assert credential.refresh_token == "new_refresh_token"
        tiktok_auth.refresh_access_token.assert_called_once_with(
            "old_refresh"
        )

    @pytest.mark.asyncio
    async def test_token_refresh_skipped_when_not_near_expiry(
        self, service, tiktok_auth, session, user, user_id
    ):
        shop = await ShopsRepo(session).create(
            user_id, "Fresh Shop", "shop_fresh"
        )
        far_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
        await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="still_valid",
            refresh_token="still_valid_refresh",
            token_expires_at=far_expiry,
        )

        tiktok_auth.refresh_access_token = MagicMock()

        credential = await service.refresh_tokens(shop.id)

        assert credential.access_token == "still_valid"
        tiktok_auth.refresh_access_token.assert_not_called()


# ---------------------------------------------------------------------------
# AC4 — User can connect multiple shops
# ---------------------------------------------------------------------------


class TestMultiShopOAuth:
    @pytest.mark.asyncio
    async def test_multi_shop_oauth_connection(
        self, service, tiktok_auth, session, user, user_id
    ):
        _mock_exchange(
            tiktok_auth, open_id="shop_A", seller_name="Shop A"
        )
        url1 = await service.initiate_oauth(user_id)
        await service.handle_callback("code_a", _extract_state(url1))

        _mock_exchange(
            tiktok_auth, open_id="shop_B", seller_name="Shop B"
        )
        url2 = await service.initiate_oauth(user_id)
        await service.handle_callback("code_b", _extract_state(url2))

        shops = await ShopsRepo(session).list(user_id)
        assert len(shops) == 2
        names = {s.shop_name for s in shops}
        assert names == {"Shop A", "Shop B"}
