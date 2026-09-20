"""Two signed-in sellers connecting two shops get TWO owners (issue #1970).

The defect this closes, in the line it replaces::

    owner_id = callback_user_id or _app_review_user_id()   # oauth.py:166

``_app_review_user_id()`` defaults to ``00000000-0000-4000-8000-000000000001``
— a REAL shared row, not a throwaway. Any connect whose state did not name a
user landed on it. With several trial sellers that is a cross-tenant ownership
collision: seller B's shop filed under the row seller A's shop is already
under. And it does not self-heal — ``provision_shop_and_credentials`` then
refuses the rightful owner's later attempt with "already connected to another
account", so the seller is permanently locked out of their own shop.

**Scope of what is proven here, stated because it is narrower than it looks.**
The `session` fixture is SQLite in-memory, not Postgres. These tests prove the
owner written into ``shops.user_id`` is the one the seller's signed state named
— a query-predicate-level fact. They prove NOTHING about Row Level Security:
no RLS policy exists on SQLite to enforce or to bypass. The Postgres-backed
lanes (`full-regression`, `Release-shape regression`) are where tenancy under
RLS is exercised.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.oauth_state import SELLER_CONNECT_FLOW, mint_oauth_state
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import Shop, User
from juli_backend.services.tiktok import oauth as oauth_module
from juli_backend.services.tiktok.oauth import (
    TikTokOAuthInfrastructureService,
    begin_tiktok_oauth,
    complete_tiktok_oauth_callback,
    resolve_seller_connect_owner,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"


@pytest.fixture
def tiktok_auth():
    return TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET)


@pytest.fixture
def oauth_service(tiktok_auth):
    """The REAL infrastructure service, not a double.

    A fake here would prove the wiring and nothing about the binding: the whole
    question is what the real `verify_state` returns and what the real
    provisioning writes with it.
    """
    return TikTokOAuthInfrastructureService(app_secret=APP_SECRET, tiktok_auth=tiktok_auth)


@pytest_asyncio.fixture
async def two_sellers(session):
    """Two distinct signed-in identities, as Google sign-in would produce."""
    sellers = [
        User(id=uuid.uuid4(), phone="+84900000011"),
        User(id=uuid.uuid4(), phone="+84900000022"),
    ]
    for seller in sellers:
        session.add(seller)
    await session.flush()
    return sellers


def _state_from_start(oauth_service, user_id: uuid.UUID) -> str:
    """Go through the real start entrypoint, then read the state off its URL.

    Deliberately not `mint_oauth_state` directly: this asserts the URL the route
    hands the browser really carries a state the callback accepts, which is the
    seam a wrong redirect_uri or a dropped parameter would break.
    """
    result = begin_tiktok_oauth(user_id, oauth_service=oauth_service)
    return parse_qs(urlparse(result.authorize_url).query)["state"][0]


def _exchange_returns(tiktok_auth, open_id: str, seller_name: str) -> None:
    tiktok_auth.exchange_code = MagicMock(
        return_value={
            "access_token": f"ROW_access_{open_id}",
            "refresh_token": f"ROW_refresh_{open_id}",
            "access_token_expire_in": 604800,
            "open_id": open_id,
            "seller_name": seller_name,
        }
    )


@pytest.mark.asyncio
async def test_two_signed_in_sellers_connecting_two_shops_produce_two_owners(
    session, oauth_service, tiktok_auth, two_sellers, monkeypatch
) -> None:
    """The issue's named acceptance criterion, end to end through the real service."""
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    seller_a, seller_b = two_sellers

    state_a = _state_from_start(oauth_service, seller_a.id)
    state_b = _state_from_start(oauth_service, seller_b.id)
    assert state_a != state_b

    _exchange_returns(tiktok_auth, "shop_of_a", "Shop của A")
    await complete_tiktok_oauth_callback(
        session, code="code-a", state=state_a, oauth_service=oauth_service
    )

    _exchange_returns(tiktok_auth, "shop_of_b", "Shop của B")
    await complete_tiktok_oauth_callback(
        session, code="code-b", state=state_b, oauth_service=oauth_service
    )

    shops = (await session.execute(select(Shop))).scalars().all()
    owners = {shop.tiktok_shop_id: shop.user_id for shop in shops}

    assert owners == {"shop_of_a": seller_a.id, "shop_of_b": seller_b.id}
    assert len(set(owners.values())) == 2, (
        "both shops landed on ONE owner — the cross-tenant collision #1970 closes"
    )

    app_review_id = oauth_module._app_review_user_id()
    assert app_review_id not in set(owners.values()), (
        "a seller-initiated connect bound a shop to the shared app-review row"
    )


@pytest.mark.asyncio
async def test_the_shop_is_owned_by_the_state_holder_not_the_app_review_row(
    session, oauth_service, tiktok_auth, two_sellers, monkeypatch
) -> None:
    """A single connect, stated as the positive claim rather than a difference.

    The two-owner test above would still pass if BOTH shops were bound to two
    *wrong* users, so this pins the owner to the identity that started the flow.
    """
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    seller_a, _ = two_sellers

    _exchange_returns(tiktok_auth, "only_shop", "Shop duy nhất")
    await complete_tiktok_oauth_callback(
        session,
        code="code-a",
        state=_state_from_start(oauth_service, seller_a.id),
        oauth_service=oauth_service,
    )

    shop = (await session.execute(select(Shop))).scalars().one()
    assert shop.user_id == seller_a.id


@pytest.mark.asyncio
async def test_a_forged_state_naming_another_user_never_reaches_provisioning(
    session, oauth_service, tiktok_auth, two_sellers, monkeypatch
) -> None:
    """Sign a state with the WRONG secret and it binds nothing.

    This is the attack the signature exists for: without it, naming a victim's
    user id in the state is enough to file your own TikTok shop under their
    account.
    """
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    _, victim = two_sellers
    forged = mint_oauth_state(victim.id, secret="not-the-app-secret", flow=SELLER_CONNECT_FLOW)

    _exchange_returns(tiktok_auth, "attacker_shop", "Shop kẻ tấn công")
    with pytest.raises(Unauthorized):
        await complete_tiktok_oauth_callback(
            session, code="code-x", state=forged, oauth_service=oauth_service
        )

    assert (await session.execute(select(Shop))).scalars().all() == []
    tiktok_auth.exchange_code.assert_not_called()


@pytest.mark.asyncio
async def test_an_expired_state_binds_nothing(
    session, oauth_service, tiktok_auth, two_sellers, monkeypatch
) -> None:
    """Validly signed, but stale — a state lifted from a log is not a credential."""
    monkeypatch.setattr(oauth_module, "is_production", lambda: False)
    seller_a, _ = two_sellers
    stale = mint_oauth_state(seller_a.id, secret=APP_SECRET, flow=SELLER_CONNECT_FLOW, now=0)

    _exchange_returns(tiktok_auth, "late_shop", "Shop muộn")
    with pytest.raises(Unauthorized, match="expired"):
        await complete_tiktok_oauth_callback(
            session, code="code-late", state=stale, oauth_service=oauth_service
        )

    assert (await session.execute(select(Shop))).scalars().all() == []


def test_resolve_seller_connect_owner_refuses_to_invent_an_owner() -> None:
    """The fail-closed guard itself, at its own boundary.

    Restoring ``return state_user_id or _app_review_user_id()`` here turns this
    test red — which is what makes the absence of that fallback a tested
    property rather than a comment.
    """
    with pytest.raises(Unauthorized):
        resolve_seller_connect_owner(None)


def test_resolve_seller_connect_owner_returns_the_state_holder() -> None:
    """The guard must not refuse everything — that would be an outage, not a fix."""
    user_id = uuid.uuid4()
    assert resolve_seller_connect_owner(user_id) == user_id
