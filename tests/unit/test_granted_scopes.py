"""OAuth granted-scope persistence and the `has_scope` checker (issue #1714).

Owner code-fact (issue comment, 2026-09-07): `tiktok_credentials.scopes` already
exists (migration 001) and the OAuth *create* branch in
`core/security/tiktok_oauth.py` has always persisted it -- the *update* branch
(a re-authorising shop) silently dropped it. That is the actual defect this
slice fixes; no migration is needed, and no diagnosis resource method exists
yet to wire a scope refusal into (#1716), so the two "refused before
transport" / "call proceeds" acceptance criteria on the issue are out of
scope here.

AC -> Test mapping (issue #1714, as narrowed by the owner's comment):
- "the scope list is persisted and readable per shop" (create branch, already
  correct) -> test_callback_persists_granted_scopes_on_create
- the actual defect (update branch dropped scopes) ->
  test_callback_persists_granted_scopes_on_reauthorisation. This is the
  non-vacuous test: it drives the real production callback path twice
  (`TikTokOAuthService.handle_callback`), not a seeded row, so it can only
  pass if the update branch itself writes the column.
- has_scope() semantics -> TestHasScope
"""

from __future__ import annotations

from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import User
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo
from juli_backend.repositories.tiktok_credentials import parse_granted_scopes
from juli_backend.services.tiktok.credential_binding import make_binding_verifier

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
BASE_URL = "https://open-api.tiktokglobalshop.com"
REDIRECT_URI = "https://myapp.com/callback"

OPTIMIZE_SCOPE = "seller.product.optimize"
ORDER_SCOPE = "seller.order.read"


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
# Persistence: create branch (already correct -- confirms the baseline)
# ---------------------------------------------------------------------------


class TestGrantedScopePersistence:
    @pytest.mark.asyncio
    async def test_callback_persists_granted_scopes_on_create(
        self, service, tiktok_auth, session, user, user_id
    ):
        """GIVEN an OAuth callback carrying scopes WHEN the credential is
        stored THEN the scope list is persisted and readable per shop."""
        _mock_exchange(tiktok_auth, scopes=f"{OPTIMIZE_SCOPE},{ORDER_SCOPE}")

        url = await service.initiate_oauth(user_id)
        shop = await service.handle_callback("auth_code_123", _extract_state(url))

        cred = await TikTokCredentialRepo(session).get_by_shop(shop.id)
        assert parse_granted_scopes(cred.scopes) == {OPTIMIZE_SCOPE, ORDER_SCOPE}

    @pytest.mark.asyncio
    async def test_callback_persists_granted_scopes_from_granted_scopes_list(
        self, service, tiktok_auth, session, user, user_id
    ):
        """The vendor payload key is `granted_scopes` (a list), not `scopes`."""
        _mock_exchange(tiktok_auth, granted_scopes=[OPTIMIZE_SCOPE, ORDER_SCOPE])

        url = await service.initiate_oauth(user_id)
        shop = await service.handle_callback("auth_code_123", _extract_state(url))

        cred = await TikTokCredentialRepo(session).get_by_shop(shop.id)
        assert parse_granted_scopes(cred.scopes) == {OPTIMIZE_SCOPE, ORDER_SCOPE}

    # -----------------------------------------------------------------------
    # The actual defect: the update (re-authorisation) branch.
    #
    # This drives `TikTokOAuthService.handle_callback` TWICE for the same
    # TikTok shop -- the real producer path, exactly as a seller
    # re-authorising would hit it -- rather than seeding a credential row
    # directly and asking `has_scope`/`parse_granted_scopes` whether they can
    # read back a value we put there ourselves. Seeding the row under test is
    # exactly how this class of bug survives (a checker that trusts data a
    # broken producer never wrote). The second callback grants a DIFFERENT
    # scope set than the first, so the assertion can only pass if the update
    # branch is the one that wrote the final value.
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_callback_persists_granted_scopes_on_reauthorisation(
        self, service, tiktok_auth, session, user, user_id
    ):
        """GIVEN a shop that already has a credential WHEN it re-authorises
        with a different scope grant THEN the stored scope list reflects the
        NEW grant, not the one from the original `create`."""
        _mock_exchange(tiktok_auth, scopes=ORDER_SCOPE)
        url1 = await service.initiate_oauth(user_id)
        shop1 = await service.handle_callback("auth_code_first", _extract_state(url1))

        cred_repo = TikTokCredentialRepo(session)
        first_cred = await cred_repo.get_by_shop(shop1.id)
        assert parse_granted_scopes(first_cred.scopes) == {ORDER_SCOPE}

        # Re-authorise the SAME TikTok shop (same open_id) with a scope grant
        # that does not even overlap the first one. Only the update branch of
        # `provision_shop_and_credentials` runs this time (`get_by_merchant`
        # finds the existing row) -- production's actual re-auth path.
        _mock_exchange(tiktok_auth, scopes=OPTIMIZE_SCOPE)
        url2 = await service.initiate_oauth(user_id)
        shop2 = await service.handle_callback("auth_code_second", _extract_state(url2))
        assert shop2.id == shop1.id, (
            "re-authorisation must update the same shop, not create a new one"
        )

        updated_cred = await cred_repo.get_by_shop(shop1.id)
        assert parse_granted_scopes(updated_cred.scopes) == {OPTIMIZE_SCOPE}, (
            "update branch dropped the newly granted scope list "
            "(issue #1714 -- the create branch was never the bug)"
        )


# ---------------------------------------------------------------------------
# has_scope()
# ---------------------------------------------------------------------------


class TestHasScope:
    @pytest.mark.asyncio
    async def test_has_scope_true_when_granted(self, session, user, user_id):
        shop = await ShopsRepo(session).create(user_id, "Scoped Shop", "shop_scoped")
        cred_repo = TikTokCredentialRepo(session)
        await cred_repo.create(
            shop_id=shop.id,
            access_token="tok",
            refresh_token="ref",
            token_expires_at=_future(),
            scopes=f"{OPTIMIZE_SCOPE},{ORDER_SCOPE}",
        )

        assert await cred_repo.has_scope(shop.id, OPTIMIZE_SCOPE) is True

    @pytest.mark.asyncio
    async def test_has_scope_false_when_scope_not_granted(self, session, user, user_id):
        shop = await ShopsRepo(session).create(user_id, "Partial Shop", "shop_partial")
        cred_repo = TikTokCredentialRepo(session)
        await cred_repo.create(
            shop_id=shop.id,
            access_token="tok",
            refresh_token="ref",
            token_expires_at=_future(),
            scopes=ORDER_SCOPE,
        )

        assert await cred_repo.has_scope(shop.id, OPTIMIZE_SCOPE) is False

    @pytest.mark.asyncio
    async def test_has_scope_false_when_scopes_column_is_null(self, session, user, user_id):
        """A shop authorised before #1714 has NULL in `scopes`.

        Fail closed: NULL reads as "not granted", never as "unknown" --
        an absent record must never read as a grant. See
        `TikTokCredentialRepo.has_scope` docstring for the full reasoning.
        """
        shop = await ShopsRepo(session).create(user_id, "Pre-fix Shop", "shop_prefix")
        cred_repo = TikTokCredentialRepo(session)
        await cred_repo.create(
            shop_id=shop.id,
            access_token="tok",
            refresh_token="ref",
            token_expires_at=_future(),
            scopes=None,
        )

        assert await cred_repo.has_scope(shop.id, OPTIMIZE_SCOPE) is False

    @pytest.mark.asyncio
    async def test_has_scope_false_when_scopes_column_is_empty_string(self, session, user, user_id):
        shop = await ShopsRepo(session).create(user_id, "Empty Scope Shop", "shop_empty")
        cred_repo = TikTokCredentialRepo(session)
        await cred_repo.create(
            shop_id=shop.id,
            access_token="tok",
            refresh_token="ref",
            token_expires_at=_future(),
            scopes="",
        )

        assert await cred_repo.has_scope(shop.id, OPTIMIZE_SCOPE) is False

    @pytest.mark.asyncio
    async def test_has_scope_raises_not_found_when_shop_has_no_credential(
        self, session, user, user_id
    ):
        """No credential row at all is a different condition ("not connected")
        than "connected but scope missing" -- it is not collapsed into a bare
        False."""
        shop = await ShopsRepo(session).create(user_id, "Unconnected Shop", "shop_unconnected")

        with pytest.raises(NotFound):
            await TikTokCredentialRepo(session).has_scope(shop.id, OPTIMIZE_SCOPE)


# ---------------------------------------------------------------------------
# parse_granted_scopes() -- pure parsing helper
# ---------------------------------------------------------------------------


class TestParseGrantedScopes:
    def test_parses_comma_separated_list(self):
        assert parse_granted_scopes(f"{OPTIMIZE_SCOPE},{ORDER_SCOPE}") == {
            OPTIMIZE_SCOPE,
            ORDER_SCOPE,
        }

    def test_strips_whitespace_and_drops_empty_entries(self):
        assert parse_granted_scopes(f" {OPTIMIZE_SCOPE} , , {ORDER_SCOPE} ") == {
            OPTIMIZE_SCOPE,
            ORDER_SCOPE,
        }

    @pytest.mark.parametrize("value", [None, "", "   ", ",,,"])
    def test_empty_or_null_input_parses_to_empty_set(self, value):
        assert parse_granted_scopes(value) == frozenset()


def _future():
    from datetime import UTC, datetime, timedelta

    return datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
