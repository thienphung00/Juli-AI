"""`GET /v1/auth/tiktok/start` — the route that did not exist (issue #1970).

Verified against production on 2026-09-17: the path returned **404**, and
`api/routes/auth_tiktok.py` defined only `GET /callback`. A signed-in seller
had no way to connect a shop at all, which is what blocked ADR-094's stated
entry sequence (Google sign-in, then TikTok connect).

Two properties this route lives or dies by:

* it requires the Supabase JWT — an unauthenticated caller must not be able to
  mint a state at all;
* the user id in the state comes from the verified token and from **nowhere
  else**. A `user_id` query/body parameter would hand any caller the ability to
  name a victim and bind their own shop to that person.
"""

from __future__ import annotations

import inspect
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio

from juli_backend.api.routes import auth_tiktok as route_module
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import User
from juli_backend.services.tiktok.oauth import TikTokOAuthInfrastructureService
from tests.support.api import build_app, client_for

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
START_PATH = "/v1/auth/tiktok/start"


@pytest.fixture
def oauth_service():
    return TikTokOAuthInfrastructureService(
        app_secret=APP_SECRET,
        tiktok_auth=TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET),
    )


@pytest_asyncio.fixture
async def seller(session):
    user = User(id=uuid.uuid4(), phone="+84900000033")
    session.add(user)
    await session.flush()
    return user


@pytest.fixture
def app(session, oauth_service):
    application = build_app(session)
    application.dependency_overrides[route_module.get_tiktok_oauth_service] = lambda: oauth_service
    yield application
    application.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_start_route_exists_and_is_a_get(app) -> None:
    """The 404 the issue measured in production.

    Read off the generated OpenAPI document rather than by walking
    ``app.routes``: FastAPI 0.141 nests included routers behind
    ``_IncludedRouter`` objects that expose no ``path``, so a flat scan of
    ``app.routes`` finds nothing and would fail identically whether or not the
    route exists — a test that cannot pass proves as little as one that cannot
    fail (#921 records the same version-dependent ``app.routes`` shape change).
    """
    paths = app.openapi()["paths"]
    assert START_PATH in paths, f"{START_PATH} is not registered — this is the #1970 404"
    assert "get" in paths[START_PATH]


@pytest.mark.asyncio
async def test_start_requires_a_jwt(app) -> None:
    """No bearer token, no state. The route mints an ownership claim."""
    async with client_for(app) as client:
        response = await client.get(START_PATH)

    assert response.status_code == 401, (
        "an unauthenticated caller could mint an OAuth state naming any user"
    )


@pytest.mark.asyncio
async def test_start_returns_a_partner_authorize_url_carrying_a_verifiable_state(
    app, seller, oauth_service
) -> None:
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: seller

    async with client_for(app) as client:
        response = await client.get(START_PATH)

    assert response.status_code == 200
    body = response.json()

    parsed = urlparse(body["authorize_url"])
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert "tiktokshop.com" in parsed.netloc
    assert params["app_key"] == [APP_KEY]
    assert params["redirect_uri"][0].endswith("/v1/auth/tiktok/callback")

    # The state is not merely present — it verifies back to THIS seller under
    # the same service the callback will use.
    assert oauth_service.verify_state(params["state"][0]) == seller.id

    assert body["state_expires_in"] > 0


@pytest.mark.asyncio
async def test_two_signed_in_sellers_get_states_naming_themselves(
    app, session, oauth_service
) -> None:
    """The route half of the two-owner guarantee.

    `test_tiktok_connect_owner_binding.py` proves two states produce two
    owners; this proves the route hands each seller a state naming *them*, so
    the two halves meet.
    """
    from juli_backend.core.security import get_current_user

    seller_a = User(id=uuid.uuid4(), phone="+84900000044")
    seller_b = User(id=uuid.uuid4(), phone="+84900000055")
    session.add_all([seller_a, seller_b])
    await session.flush()

    states = []
    for seller in (seller_a, seller_b):
        app.dependency_overrides[get_current_user] = lambda seller=seller: seller
        async with client_for(app) as client:
            response = await client.get(START_PATH)
        assert response.status_code == 200
        states.append(parse_qs(urlparse(response.json()["authorize_url"]).query)["state"][0])

    assert [oauth_service.verify_state(state) for state in states] == [seller_a.id, seller_b.id]


def test_start_accepts_no_caller_supplied_user_identity() -> None:
    """Signature-level guard against the hole this route would otherwise be.

    A `user_id` parameter — query, header, or body — would let any authenticated
    caller mint a state naming somebody else. The only identity input is the
    `get_current_user` dependency.
    """
    parameters = inspect.signature(route_module.tiktok_oauth_start).parameters
    assert set(parameters) == {"user", "oauth_service"}, (
        f"unexpected inputs on the start route: {sorted(parameters)}"
    )


@pytest.mark.asyncio
async def test_start_answers_503_when_tiktok_oauth_is_not_configured(session, seller) -> None:
    """Honest unavailability rather than a half-built URL with no app key."""
    from juli_backend.core.security import get_current_user

    application = build_app(session)
    application.dependency_overrides[get_current_user] = lambda: seller

    async with client_for(application) as client:
        response = await client.get(START_PATH)

    application.dependency_overrides.clear()
    assert response.status_code == 503
