"""Vendor-verified capability binding (issue #1200).

The defect these pin: a `tiktok_credentials` row could carry the correct
`capability` and `merchant_authorization_id` while holding a token authorized
for a *different* shop, and every guard would permit it — because the guards
check the row, and nothing ever asked the vendor.

`test_the_2026_08_18_state_is_rejected` reconstructs the exact state observed
that day: a production token filed under `sandbox_write`, sharing a
`shop_cipher` with the `production_read` row.
"""

from __future__ import annotations

from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
)
from juli_backend.models.models import Shop, TikTokCredential, User
from juli_backend.services.tiktok.credential_binding import (
    CredentialBindingError,
    resolve_authorized_shop,
    verify_capability_binding,
)

PRODUCTION_CIPHER = "ROW_production_cipher_example"
SANDBOX_CIPHER = "ROW_sandbox_cipher_example"


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    import uuid as _uuid

    user = User(phone=f"+1555{_uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    import uuid as _uuid2

    row = Shop(user_id=user.id, shop_name="Test", tiktok_shop_id=f"tts-{_uuid2.uuid4().hex[:12]}")
    session.add(row)
    await session.commit()
    return row


async def _add_credential(
    session: AsyncSession, shop: Shop, *, capability: str, auth_id: str, cipher: str | None
) -> TikTokCredential:
    from datetime import datetime, timedelta

    cred = TikTokCredential(
        shop_id=shop.id,
        access_token="enc:v1:x",
        refresh_token="enc:v1:y",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        merchant_authorization_id=auth_id,
        capability=capability,
        shop_cipher=cipher,
    )
    session.add(cred)
    await session.commit()
    return cred


class TestDistinctness:
    """No two capabilities may resolve to the same shop.

    Note what this invariant does NOT need: any knowledge of which shop is the
    'right' one for a capability. Two capabilities reaching one shop is provably
    wrong regardless — which is why this needs nothing hardcoded.
    """

    async def test_the_2026_08_18_state_is_rejected(self, session: AsyncSession, shop: Shop):
        """The real defect: a production token filed under sandbox_write.

        On 2026-08-18 the `sandbox_write` row had the correct label and auth id
        and a token TikTok reported as authorized for the production shop, with
        the same cipher as `production_read`. Had a cipher been present, an
        agent 'sandbox write' would have hit the live store.
        """
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.PRODUCTION_READ.value,
            auth_id=PRODUCTION_AUTH_ID,
            cipher=PRODUCTION_CIPHER,
        )

        # Now try to file a credential for the SANDBOX capability whose token
        # the vendor says reaches the PRODUCTION shop.
        with pytest.raises(CredentialBindingError) as exc:
            await verify_capability_binding(
                session,
                capability=TikTokCapability.SANDBOX_WRITE,
                shop_cipher=PRODUCTION_CIPHER,
            )
        assert "already bound" in str(exc.value)

    async def test_a_distinct_shop_is_accepted(self, session: AsyncSession, shop: Shop):
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.PRODUCTION_READ.value,
            auth_id=PRODUCTION_AUTH_ID,
            cipher=PRODUCTION_CIPHER,
        )
        await verify_capability_binding(
            session, capability=TikTokCapability.SANDBOX_WRITE, shop_cipher=SANDBOX_CIPHER
        )

    async def test_rewriting_the_same_capability_to_its_own_shop_is_fine(
        self, session: AsyncSession, shop: Shop
    ):
        """A token refresh re-writes the same capability against the same shop --
        that must not trip distinctness against its own row."""
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            auth_id=SANDBOX_AUTH_ID,
            cipher=SANDBOX_CIPHER,
        )
        await verify_capability_binding(
            session, capability=TikTokCapability.SANDBOX_WRITE, shop_cipher=SANDBOX_CIPHER
        )


class TestStabilityTrustOnFirstUse:
    async def test_moving_a_capability_to_a_new_shop_is_rejected(
        self, session: AsyncSession, shop: Shop
    ):
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            auth_id=SANDBOX_AUTH_ID,
            cipher=SANDBOX_CIPHER,
        )
        with pytest.raises(CredentialBindingError) as exc:
            await verify_capability_binding(
                session,
                capability=TikTokCapability.SANDBOX_WRITE,
                shop_cipher="ROW_some_other_shop",
            )
        assert "changing merchants" in str(exc.value)

    async def test_first_binding_for_a_capability_is_accepted(
        self, session: AsyncSession, shop: Shop
    ):
        """Trust-on-first-use: with nothing recorded yet, any shop is accepted
        and becomes the expectation for every later write."""
        await verify_capability_binding(
            session, capability=TikTokCapability.SANDBOX_WRITE, shop_cipher=SANDBOX_CIPHER
        )

    async def test_a_row_with_no_recorded_cipher_does_not_block(
        self, session: AsyncSession, shop: Shop
    ):
        """Legacy rows predate this check and have no cipher. They must not
        wedge the capability -- the first verified write establishes it."""
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            auth_id=SANDBOX_AUTH_ID,
            cipher=None,
        )
        await verify_capability_binding(
            session, capability=TikTokCapability.SANDBOX_WRITE, shop_cipher=SANDBOX_CIPHER
        )


class TestResolveAuthorizedShop:
    """Ambiguity is refused rather than guessed -- guessing which shop a token
    belongs to is the class of assumption this module exists to remove."""

    def _auth_stub(self, shops):
        class _Resource:
            def __init__(self, *_args, **_kwargs):
                pass

            def list_all_shops(self):
                return shops

        return _Resource

    def test_zero_shops_is_rejected(self, monkeypatch):
        import juli_backend.services.tiktok.credential_binding as mod

        monkeypatch.setattr(mod, "AuthorizationResource", self._auth_stub([]))
        with pytest.raises(CredentialBindingError, match="zero shops"):
            resolve_authorized_shop(app_key="k", app_secret="s", access_token="t")

    def test_multiple_shops_is_rejected(self, monkeypatch):
        import juli_backend.services.tiktok.credential_binding as mod

        monkeypatch.setattr(
            mod, "AuthorizationResource", self._auth_stub([{"cipher": "a"}, {"cipher": "b"}])
        )
        with pytest.raises(CredentialBindingError, match="will not guess"):
            resolve_authorized_shop(app_key="k", app_secret="s", access_token="t")

    def test_single_shop_is_returned(self, monkeypatch):
        import juli_backend.services.tiktok.credential_binding as mod

        monkeypatch.setattr(
            mod, "AuthorizationResource", self._auth_stub([{"id": "1", "cipher": "ROW_x"}])
        )
        assert (
            resolve_authorized_shop(app_key="k", app_secret="s", access_token="t")["cipher"]
            == "ROW_x"
        )


class TestSandboxCanAskWhoItIs:
    """#1200 needs the identity read permitted for sandbox-write too, otherwise
    binding can only be verified for production-read -- and the sandbox side is
    exactly where a mislabelled token causes an unintended production write."""

    def test_authorized_shops_is_allowed_on_sandbox_write_transport(self):
        from juli_backend.integrations.tiktok.guards import SandboxOnlyWriteGuard

        SandboxOnlyWriteGuard().assert_allowed("GET", "/authorization/202309/shops")


class TestSellerConnectIsExempt:
    """`seller_connect` is multi-shop BY DESIGN and must not be governed.

    It is the capability every seller receives when connecting their own shop,
    so many rows legitimately share it — multi-tenant onboarding (P13) depends
    on exactly that. These tests exist because the first version of this module
    governed it, which broke multi-shop OAuth and would have rejected the real
    production state, where `seller_connect` and `sandbox_write` point at the
    same shop.
    """

    async def test_a_second_seller_connect_shop_is_allowed(self, session: AsyncSession, shop: Shop):
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SELLER_CONNECT.value,
            auth_id="seller-a",
            cipher="ROW_seller_a",
        )
        # A different seller connecting a different shop: must not trip TOFU.
        await verify_capability_binding(
            session, capability=TikTokCapability.SELLER_CONNECT, shop_cipher="ROW_seller_b"
        )

    async def test_seller_connect_may_share_a_shop_with_a_governed_capability(
        self, session: AsyncSession, shop: Shop
    ):
        """The real state on 2026-08-19: `seller_connect` and `sandbox_write`
        both point at the sandbox shop. That is correct and must be allowed."""
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            auth_id=SANDBOX_AUTH_ID,
            cipher=SANDBOX_CIPHER,
        )
        await verify_capability_binding(
            session, capability=TikTokCapability.SELLER_CONNECT, shop_cipher=SANDBOX_CIPHER
        )

    async def test_a_governed_capability_still_cannot_take_a_seller_connect_shop(
        self, session: AsyncSession, shop: Shop
    ):
        """Exemption is one-directional: `seller_connect` rows are ignored when
        judging a governed capability, so they can never launder a bad binding
        into `sandbox_write`."""
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.PRODUCTION_READ.value,
            auth_id=PRODUCTION_AUTH_ID,
            cipher=PRODUCTION_CIPHER,
        )
        await _add_credential(
            session,
            shop,
            capability=TikTokCapability.SELLER_CONNECT.value,
            auth_id="seller-a",
            cipher=PRODUCTION_CIPHER,
        )
        with pytest.raises(CredentialBindingError):
            await verify_capability_binding(
                session,
                capability=TikTokCapability.SANDBOX_WRITE,
                shop_cipher=PRODUCTION_CIPHER,
            )
