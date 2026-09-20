"""A read resolves the connecting shop's OWN credential, and never another's (#1365).

Before this slice the only read resolver was
``resolve_production_read_credential``: one globally configured merchant, and
``services/action_cards/refresh.py`` silently returned ``None`` for every other
shop. A seller who had just connected was therefore scored over an empty
database with no error anywhere.

``resolve_read_credential_for_shop`` fixes that, and the whole risk of the fix
is that it must not become a way to read one merchant's data under another
merchant's shop. So the tests below are keyed on the pair that decides access:
the shop that owns the row, AND the capability the row carries.

- capability is the authority, never the shop id alone;
- ``SELLER_CONNECT`` grants reads for its own shop and nothing else, and is
  never promoted to ``PRODUCTION_READ``;
- ``SANDBOX_WRITE`` is unreachable from any read path;
- a shop with no usable credential fails LOUDLY -- it does not fall back to the
  configured merchant, and it does not return ``None``;
- a shop that does not exist and a shop that exists but is not yours are
  indistinguishable from the error (404 shape, never 403 -- no existence
  oracle).

Isolation is proven against a SYNTHETIC SECOND SHOP
(``test_two_shops_resolve_their_own_and_never_each_others``): asserting it
against the single real merchant would prove nothing about isolation.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import timedelta

import pytest

from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    resolve_production_read_credential,
    resolve_read_credential_for_shop,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    READ_CAPABILITIES,
    SANDBOX_AUTH_ID,
    TikTokCapability,
    is_read_capability,
)
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.builders import make_tenant, next_unique, utc_now_naive


async def issue_credential(
    session,
    shop,
    capability: TikTokCapability,
    *,
    access_token: str,
    merchant_authorization_id: str | None = None,
):
    """Persist one credential for ``shop`` exactly as the OAuth callback does."""
    if merchant_authorization_id is None:
        merchant_authorization_id = {
            TikTokCapability.PRODUCTION_READ: PRODUCTION_AUTH_ID,
            TikTokCapability.SANDBOX_WRITE: SANDBOX_AUTH_ID,
        }.get(capability, next_unique("seller-open-id"))
    return await TikTokCredentialRepo(session).create(
        shop.id,
        access_token,
        f"{access_token}-refresh",
        utc_now_naive() + timedelta(hours=1),
        merchant_authorization_id=merchant_authorization_id,
        capability=capability.value,
    )


async def make_second_shop(session):
    """A synthetic second shop -- its own user, its own shop row."""
    _user, shop = await make_tenant(session)
    return shop


class TestOwnCredentialResolves:
    async def test_shop_resolves_its_own_seller_connect_credential(self, session, shop):
        await issue_credential(
            session, shop, TikTokCapability.SELLER_CONNECT, access_token="seller-token"
        )

        credential = await resolve_read_credential_for_shop(session, shop.id)

        assert credential.shop_id == shop.id
        assert credential.access_token == "seller-token"

    async def test_seller_connect_is_never_promoted_to_production_read(self, session, shop):
        stored = await issue_credential(
            session, shop, TikTokCapability.SELLER_CONNECT, access_token="seller-token"
        )

        credential = await resolve_read_credential_for_shop(session, shop.id)

        assert credential.capability == TikTokCapability.SELLER_CONNECT.value
        assert credential.capability != TikTokCapability.PRODUCTION_READ.value
        # and the row itself was not rewritten on the way through
        assert stored.capability == TikTokCapability.SELLER_CONNECT.value

    async def test_configured_production_read_merchant_resolves_unchanged(self, session, shop):
        await issue_credential(
            session, shop, TikTokCapability.PRODUCTION_READ, access_token="fujiwa-token"
        )

        through_the_global_resolver = await resolve_production_read_credential(session)
        through_the_per_shop_resolver = await resolve_read_credential_for_shop(session, shop.id)

        assert through_the_global_resolver.access_token == "fujiwa-token"
        assert through_the_per_shop_resolver.access_token == "fujiwa-token"
        assert through_the_per_shop_resolver.capability == TikTokCapability.PRODUCTION_READ.value
        assert through_the_per_shop_resolver.shop_id == shop.id


class TestTwoShopsNeverCross:
    async def test_two_shops_resolve_their_own_and_never_each_others(self, session, shop):
        """The synthetic-second-shop case: A and B each hold their own
        ``SELLER_CONNECT`` credential, and each resolves only its own.

        Asserted per case on the resolved credential's identity -- shop id,
        token and merchant -- not by matching an error code, which would pass
        just as well if resolution were broken in the other direction.
        """
        other_shop = await make_second_shop(session)
        own = await issue_credential(
            session,
            shop,
            TikTokCapability.SELLER_CONNECT,
            access_token="shop-a-token",
            merchant_authorization_id="open-id-shop-a",
        )
        theirs = await issue_credential(
            session,
            other_shop,
            TikTokCapability.SELLER_CONNECT,
            access_token="shop-b-token",
            merchant_authorization_id="open-id-shop-b",
        )
        assert own.id != theirs.id and shop.id != other_shop.id

        resolved_a = await resolve_read_credential_for_shop(session, shop.id)
        resolved_b = await resolve_read_credential_for_shop(session, other_shop.id)

        assert resolved_a.id == own.id
        assert resolved_a.shop_id == shop.id
        assert resolved_a.access_token == "shop-a-token"
        assert resolved_a.merchant_authorization_id == "open-id-shop-a"

        assert resolved_b.id == theirs.id
        assert resolved_b.shop_id == other_shop.id
        assert resolved_b.access_token == "shop-b-token"
        assert resolved_b.merchant_authorization_id == "open-id-shop-b"

    async def test_resolution_holds_no_state_between_calls(self, session, shop):
        """A, then B, then A again -- the third call must not be answered from
        whatever the first two left behind (rollback assertion: resolution is
        per-call and holds no cross-request state)."""
        other_shop = await make_second_shop(session)
        await issue_credential(
            session, shop, TikTokCapability.SELLER_CONNECT, access_token="shop-a-token"
        )
        await issue_credential(
            session, other_shop, TikTokCapability.SELLER_CONNECT, access_token="shop-b-token"
        )

        first_a = await resolve_read_credential_for_shop(session, shop.id)
        b = await resolve_read_credential_for_shop(session, other_shop.id)
        second_a = await resolve_read_credential_for_shop(session, shop.id)

        assert first_a.access_token == "shop-a-token"
        assert b.access_token == "shop-b-token"
        assert second_a.access_token == "shop-a-token"
        assert second_a.shop_id == shop.id


class TestNoUsableCredentialFailsLoudly:
    async def test_shop_without_a_credential_raises_and_never_falls_back(self, session, shop):
        """The configured production merchant's credential exists -- on someone
        else's shop. The connecting shop must NOT receive it."""
        merchant_shop = await make_second_shop(session)
        await issue_credential(
            session,
            merchant_shop,
            TikTokCapability.PRODUCTION_READ,
            access_token="fujiwa-token",
        )

        with pytest.raises(NoReadCredentialForShop):
            await resolve_read_credential_for_shop(session, shop.id)

    async def test_named_error_is_a_not_found_so_routes_answer_404(self):
        assert issubclass(NoReadCredentialForShop, NotFound)

    async def test_sandbox_write_credential_is_unreachable_from_the_read_path(self, session, shop):
        await issue_credential(
            session, shop, TikTokCapability.SANDBOX_WRITE, access_token="sandbox-token"
        )

        with pytest.raises(NoReadCredentialForShop):
            await resolve_read_credential_for_shop(session, shop.id)

    async def test_nonexistent_and_cross_tenant_are_indistinguishable(self, session, shop):
        """No existence oracle: a shop that does not exist and a shop that
        exists but holds no credential raise the same error, with the same
        message once the id is masked."""
        other_shop = await make_second_shop(session)
        await issue_credential(
            session, other_shop, TikTokCapability.SELLER_CONNECT, access_token="shop-b-token"
        )
        nonexistent_shop_id = uuid.uuid4()

        with pytest.raises(NoReadCredentialForShop) as existing:
            await resolve_read_credential_for_shop(session, shop.id)
        with pytest.raises(NoReadCredentialForShop) as missing:
            await resolve_read_credential_for_shop(session, nonexistent_shop_id)

        assert type(existing.value) is type(missing.value)
        assert str(existing.value).replace(str(shop.id), "<shop>") == str(missing.value).replace(
            str(nonexistent_shop_id), "<shop>"
        )

    async def test_never_returns_none(self, session, shop):
        """The defect being fixed was a silent ``None``. Neither branch may
        hand one back.

        BOTH branches are exercised on purpose. Asserting only the success
        path is not None proves nothing this file does not already prove --
        ``test_shop_resolves_its_own_seller_connect_credential`` asserts a
        token off that same object -- while the branch that actually returned
        ``None`` in ``refresh.py`` was the one where nothing resolved. Mutating
        the resolver's final ``raise`` to ``return None`` left an
        assert-only-the-success-path version of this test green (#1365).
        """
        credential_less_shop = await make_second_shop(session)
        await issue_credential(
            session, shop, TikTokCapability.SELLER_CONNECT, access_token="seller-token"
        )

        assert await resolve_read_credential_for_shop(session, shop.id) is not None

        # The branch that used to return None: nothing usable, so it raises --
        # `pytest.raises` fails on a returned None, which is the point.
        with pytest.raises(NoReadCredentialForShop):
            await resolve_read_credential_for_shop(session, credential_less_shop.id)


class TestCallSiteContract:
    def test_signature_is_session_and_shop_id_only(self):
        """The call site (`services/action_cards/refresh.py`) passes exactly
        these two; nothing else may become required."""
        parameters = list(inspect.signature(resolve_read_credential_for_shop).parameters)

        assert parameters == ["session", "shop_id"]


class TestReadCapabilityPolicy:
    """Capability is the authority. The policy constant is asserted directly so
    a future edit that adds ``SANDBOX_WRITE`` to it fails here, not in
    production."""

    def test_sandbox_write_is_not_read_capable(self):
        assert TikTokCapability.SANDBOX_WRITE not in READ_CAPABILITIES
        assert not is_read_capability(TikTokCapability.SANDBOX_WRITE)
        assert not is_read_capability(TikTokCapability.SANDBOX_WRITE.value)

    def test_seller_connect_and_production_read_are_read_capable(self):
        assert is_read_capability(TikTokCapability.SELLER_CONNECT)
        assert is_read_capability(TikTokCapability.PRODUCTION_READ)
        assert set(READ_CAPABILITIES) == {
            TikTokCapability.SELLER_CONNECT,
            TikTokCapability.PRODUCTION_READ,
        }
