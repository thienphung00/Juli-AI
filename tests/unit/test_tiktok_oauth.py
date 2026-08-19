"""TDD tests for TikTok OAuth service (issue #30).

AC → Test Mapping:
- AC1 → test_initiate_oauth_returns_valid_url
- AC2 → test_oauth_callback_provisions_shop
- AC3 → test_token_refresh_before_expiry
- AC4 → test_multi_shop_oauth_connection
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import TikTokCredential, User
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo
from juli_backend.services.tiktok.credential_binding import make_binding_verifier

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
BASE_URL = "https://open-api.tiktokglobalshop.com"
REDIRECT_URI = "https://myapp.com/callback"


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET, base_url=BASE_URL)


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
        binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
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
    async def test_initiate_oauth_returns_valid_url(self, service, user, user_id):
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
    async def test_initiate_oauth_unique_states(self, service, user, user_id):
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
        assert cred.token_expires_at > datetime.now(UTC).replace(tzinfo=None)

        raw = await session.execute(
            select(TikTokCredential.access_token, TikTokCredential.refresh_token).where(
                TikTokCredential.id == cred.id
            )
        )
        stored_access_token, stored_refresh_token = raw.one()
        assert stored_access_token != "ROW_access_abc"
        assert stored_refresh_token != "ROW_refresh_xyz"

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_tampered_state(self, service, user, user_id):
        with pytest.raises(Unauthorized, match="signature"):
            await service.handle_callback("code", "tampered.state")

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_malformed_state(self, service, user, user_id):
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
            binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
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
            binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
        )
        url2 = await service.initiate_oauth(user_id)

        with pytest.raises(Unauthorized, match="already connected"):
            await service.handle_callback("code_mine", _extract_state(url2))


# ---------------------------------------------------------------------------
# AC3 — refresh_tiktok_tokens proactively refreshes before expiry
# ---------------------------------------------------------------------------


class TestTokenRefresh:
    @pytest.mark.asyncio
    async def test_token_refresh_before_expiry(self, service, tiktok_auth, session, user, user_id):
        shop = await ShopsRepo(session).create(user_id, "Expiring Shop", "shop_exp")
        near_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
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
        tiktok_auth.refresh_access_token.assert_called_once_with("old_refresh")

    @pytest.mark.asyncio
    async def test_token_refresh_skipped_when_not_near_expiry(
        self, service, tiktok_auth, session, user, user_id
    ):
        shop = await ShopsRepo(session).create(user_id, "Fresh Shop", "shop_fresh")
        far_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
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

    @pytest.mark.asyncio
    async def test_token_refresh_is_durable_across_new_session(self, tiktok_auth, engine, user_id):
        """AC: refreshed token must persist across a new session (commit boundary test).

        This is the regression test that fails on main: refresh is flushed but not
        committed, so re-reading via a new session sees stale values.
        """
        # Setup: create shop and credential
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            shop = await ShopsRepo(session).create(user_id, "Test Shop", "test_shop")
            near_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="old_access",
                refresh_token="old_refresh",
                token_expires_at=near_expiry,
            )
            shop_id = shop.id
            await session.commit()

        # Refresh in first session
        # NOTE: The service now commits internally, so durability is guaranteed
        async with factory() as session:
            service = TikTokOAuthService(
                tiktok_auth=tiktok_auth,
                session=session,
                redirect_uri=REDIRECT_URI,
                app_secret=APP_SECRET,
                binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
            )
            tiktok_auth.refresh_access_token = MagicMock(
                return_value={
                    "access_token": "refreshed_access",
                    "refresh_token": "refreshed_refresh",
                    "access_token_expire_in": 604800,
                }
            )
            credential = await service.refresh_tokens(shop_id)
            assert credential.access_token == "refreshed_access"
            assert credential.refresh_token == "refreshed_refresh"
            # The service commits internally, so no explicit commit needed here

        # Verify durability: read via NEW session
        async with factory() as session:
            persisted = await TikTokCredentialRepo(session).get_by_shop(shop_id)
            assert persisted.access_token == "refreshed_access"
            assert persisted.refresh_token == "refreshed_refresh"
            assert persisted.token_expires_at > datetime.now(UTC).replace(tzinfo=None)

    @pytest.mark.asyncio
    async def test_token_refresh_persists_rotated_refresh_token(self, tiktok_auth, engine, user_id):
        """AC: when provider returns a different refresh_token, it must be persisted."""
        from sqlalchemy import select

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            shop = await ShopsRepo(session).create(user_id, "Rotation Shop", "rotation")
            near_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="old_access",
                refresh_token="OLD_REFRESH_TOKEN",
                token_expires_at=near_expiry,
            )
            shop_id = shop.id
            await session.commit()

        # Refresh with rotated token
        async with factory() as session:
            service = TikTokOAuthService(
                tiktok_auth=tiktok_auth,
                session=session,
                redirect_uri=REDIRECT_URI,
                app_secret=APP_SECRET,
                binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
            )
            tiktok_auth.refresh_access_token = MagicMock(
                return_value={
                    "access_token": "new_access",
                    "refresh_token": "NEW_ROTATED_REFRESH_TOKEN",
                    "access_token_expire_in": 604800,
                }
            )
            credential = await service.refresh_tokens(shop_id)
            assert credential.refresh_token == "NEW_ROTATED_REFRESH_TOKEN"
            # Service commits internally

        # Verify the rotated token is persisted
        async with factory() as session:
            result = await session.execute(
                select(TikTokCredential.refresh_token).where(TikTokCredential.shop_id == shop_id)
            )
            stored_encrypted = result.scalar_one()
            # Verify it's encrypted
            assert stored_encrypted.startswith("enc:v1:")
            # Verify it decrypts to the new token
            from juli_backend.database.token_crypto import decrypt_token

            assert decrypt_token(stored_encrypted) == "NEW_ROTATED_REFRESH_TOKEN"

    @pytest.mark.asyncio
    async def test_token_refresh_retains_refresh_token_when_response_omits_it(
        self, tiktok_auth, engine, user_id
    ):
        """AC: if provider omits refresh_token, retain the existing one (no KeyError)."""
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            shop = await ShopsRepo(session).create(user_id, "Omit Shop", "omit")
            near_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="old_access",
                refresh_token="retained_refresh",
                token_expires_at=near_expiry,
            )
            shop_id = shop.id
            await session.commit()

        # Refresh with response omitting refresh_token
        async with factory() as session:
            service = TikTokOAuthService(
                tiktok_auth=tiktok_auth,
                session=session,
                redirect_uri=REDIRECT_URI,
                app_secret=APP_SECRET,
                binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
            )
            tiktok_auth.refresh_access_token = MagicMock(
                return_value={
                    "access_token": "new_access",
                    # refresh_token is missing
                    "access_token_expire_in": 604800,
                }
            )
            credential = await service.refresh_tokens(shop_id)
            # Should retain the old refresh token
            assert credential.refresh_token == "retained_refresh"
            # Service commits internally

        # Verify the old refresh token is still persisted
        async with factory() as session:
            persisted = await TikTokCredentialRepo(session).get_by_shop(shop_id)
            assert persisted.refresh_token == "retained_refresh"

    @pytest.mark.asyncio
    async def test_refresh_buffer_early_return_still_short_circuits(
        self, service, tiktok_auth, session, user, user_id
    ):
        """AC: REFRESH_BUFFER early-return still works: no HTTP call, no write."""
        shop = await ShopsRepo(session).create(user_id, "Fresh Shop", "fresh_buffer")
        far_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
        await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="still_valid",
            refresh_token="still_valid_refresh",
            token_expires_at=far_expiry,
        )

        tiktok_auth.refresh_access_token = MagicMock()

        credential = await service.refresh_tokens(shop.id)

        # Should return same token
        assert credential.access_token == "still_valid"
        # Should NOT call refresh endpoint
        tiktok_auth.refresh_access_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_persisted_refresh_token_is_encrypted(self, tiktok_auth, engine, user_id):
        """AC: persisted refresh_token must carry enc:v1: prefix (ciphertext)."""
        from sqlalchemy import select

        from juli_backend.database.token_crypto import ENCRYPTED_TOKEN_PREFIX

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            shop = await ShopsRepo(session).create(user_id, "Encrypt Shop", "encrypt")
            near_expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="old_access",
                refresh_token="plaintext_refresh",
                token_expires_at=near_expiry,
            )
            shop_id = shop.id
            await session.commit()

        # Refresh
        async with factory() as session:
            service = TikTokOAuthService(
                tiktok_auth=tiktok_auth,
                session=session,
                redirect_uri=REDIRECT_URI,
                app_secret=APP_SECRET,
                binding_verifier=make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET),
            )
            tiktok_auth.refresh_access_token = MagicMock(
                return_value={
                    "access_token": "new_access",
                    "refresh_token": "plaintext_new_refresh",
                    "access_token_expire_in": 604800,
                }
            )
            await service.refresh_tokens(shop_id)
            # Service commits internally

        # Verify column is encrypted
        async with factory() as session:
            result = await session.execute(
                select(TikTokCredential.refresh_token).where(TikTokCredential.shop_id == shop_id)
            )
            stored = result.scalar_one()
            assert stored.startswith(ENCRYPTED_TOKEN_PREFIX)


# ---------------------------------------------------------------------------
# AC4 — User can connect multiple shops
# ---------------------------------------------------------------------------


class TestMultiShopOAuth:
    @pytest.mark.asyncio
    async def test_multi_shop_oauth_connection(self, service, tiktok_auth, session, user, user_id):
        _mock_exchange(tiktok_auth, open_id="shop_A", seller_name="Shop A")
        url1 = await service.initiate_oauth(user_id)
        await service.handle_callback("code_a", _extract_state(url1))

        _mock_exchange(tiktok_auth, open_id="shop_B", seller_name="Shop B")
        url2 = await service.initiate_oauth(user_id)
        await service.handle_callback("code_b", _extract_state(url2))

        shops = await ShopsRepo(session).list(user_id)
        assert len(shops) == 2
        names = {s.shop_name for s in shops}
        assert names == {"Shop A", "Shop B"}


# ---------------------------------------------------------------------------
# MMU-10 (#562) — OAuth callback path must route writes through facade
# ---------------------------------------------------------------------------


class TestOAuthFacadeRouting:
    def test_mmu10_callback_infrastructure_delegates_to_oauth_facade(self) -> None:
        """Callback wiring must not bypass TikTokOAuthService with persist_oauth_tokens."""
        from pathlib import Path

        oauth_module = (
            Path(__file__).resolve().parents[2]
            / "backend/src/juli_backend/services/tiktok/oauth.py"
        )
        source = oauth_module.read_text(encoding="utf-8")

        assert "TikTokOAuthService" in source or "core.security.tiktok_oauth" in source, (
            "OAuth callback infrastructure must delegate to Auth & Security facade"
        )
        assert "persist_oauth_tokens" not in source, (
            "OAuth callback must not call competing app_review_store writer"
        )
