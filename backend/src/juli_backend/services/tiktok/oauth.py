"""TikTok OAuth callback infrastructure — state validation and token exchange.

Business logic (shop provisioning, credential persistence) is intentionally
out of scope; see ``TikTokOAuthService`` in identity/infrastructure/auth.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import is_production, require_env
from juli_backend.core.security import (
    DEFAULT_STATE_TTL_SECONDS,
    SELLER_CONNECT_FLOW,
    mint_oauth_state,
    verify_oauth_state,
)
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import (
    AuthenticationError,
    TikTokAuth,
)
from juli_backend.repositories.repos import UsersRepo
from juli_backend.services.tiktok.credential_binding import make_binding_verifier
from juli_backend.services.tiktok.schemas import (
    TikTokOAuthCallbackResult,
    TikTokOAuthStartResult,
)

APP_REVIEW_USER_PHONE = "+849000000001"

logger = logging.getLogger(__name__)

DEFAULT_TIKTOK_BASE_URL = "https://open-api.tiktokglobalshop.com"
DEFAULT_TIKTOK_AUTH_BASE_URL = "https://auth.tiktok-shops.com"


class TikTokOAuthNotConfiguredError(RuntimeError):
    """Raised when required TikTok OAuth environment variables are missing."""


class TikTokOAuthTokenExchangeFailed(Exception):
    """Raised when TikTok rejects an authorization code exchange."""


def build_tiktok_oauth_service() -> TikTokOAuthInfrastructureService:
    """Construct the OAuth callback service from runtime environment."""
    try:
        app_secret = require_env("TIKTOK_APP_SECRET")
        app_key = require_env("TIKTOK_APP_KEY")
    except RuntimeError as exc:
        raise TikTokOAuthNotConfiguredError("TikTok OAuth is not configured") from exc

    base_url = os.environ.get("TIKTOK_BASE_URL", DEFAULT_TIKTOK_BASE_URL).strip()
    if not base_url:
        base_url = DEFAULT_TIKTOK_BASE_URL

    auth_base_url = os.environ.get("TIKTOK_AUTH_BASE_URL", DEFAULT_TIKTOK_AUTH_BASE_URL).strip()
    if not auth_base_url:
        auth_base_url = DEFAULT_TIKTOK_AUTH_BASE_URL

    tiktok_auth = TikTokAuth(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        auth_base_url=auth_base_url,
    )
    return TikTokOAuthInfrastructureService(app_secret=app_secret, tiktok_auth=tiktok_auth)


def _app_review_user_id() -> uuid.UUID:
    """The SHARED row TikTok's stateless app-review callback is filed under.

    ``00000000-0000-4000-8000-000000000001`` is a real existing user, not a
    throwaway — which is precisely why nothing seller-initiated may ever reach
    it. See :func:`resolve_seller_connect_owner`.
    """
    raw = os.environ.get(
        "TIKTOK_APP_REVIEW_USER_ID",
        "00000000-0000-4000-8000-000000000001",
    )
    return uuid.UUID(raw)


def resolve_seller_connect_owner(state_user_id: uuid.UUID | None) -> uuid.UUID:
    """Owner for a SELLER-INITIATED connect. Fails closed — issue #1970.

    THIS FUNCTION MUST NEVER FALL BACK TO :func:`_app_review_user_id`, and the
    absence of that fallback is the whole point of it existing as a named,
    separately-tested function rather than an inline ``or``.

    The line it replaces read ``owner_id = callback_user_id or
    _app_review_user_id()``. With several trial sellers connecting, every shop
    whose state failed to name a user landed on the ONE shared app-review row:
    seller B's shop owned by the row seller A's shop is already under. That is
    a cross-tenant ownership collision, and it is not self-correcting —
    ``provision_shop_and_credentials`` then refuses the real owner's later
    attempt with "already connected to another account", so the seller is
    permanently locked out of their own shop.

    A seller-initiated connect always carries a state naming its user (minted
    by :func:`begin_tiktok_oauth` from a verified JWT). If that id is somehow
    absent, the only safe answer is to refuse: an unbound connect can be
    retried, a mis-bound one cannot be undone.
    """
    if state_user_id is None:
        logger.warning("tiktok_oauth_seller_connect_owner_unresolved")
        raise Unauthorized("OAuth state does not identify the connecting user")
    return state_user_id


def tiktok_redirect_uri() -> str:
    """The callback URL registered with TikTok Partner Center.

    One reader for both halves of the handshake: the authorize URL minted by
    :func:`begin_tiktok_oauth` and the facade that completes the callback must
    name the SAME redirect_uri or TikTok rejects the code exchange.
    """
    return os.environ.get(
        "TIKTOK_REDIRECT_URI",
        "https://api.app-juli.com/v1/auth/tiktok/callback",
    ).strip()


def begin_tiktok_oauth(
    user_id: uuid.UUID,
    *,
    oauth_service: TikTokOAuthInfrastructureService | None = None,
) -> TikTokOAuthStartResult:
    """Start a seller-initiated connect for an ALREADY-AUTHENTICATED user (#1970).

    ``user_id`` must come from the verified Supabase JWT — never from a query
    parameter, a header, or a request body. It is sealed into the signed state
    here, and the callback binds the shop to exactly the id this function was
    handed. That chain is the whole cross-tenant guarantee: a caller can only
    ever connect a shop to *themselves*, because the only writable input to the
    state is a user id the JWT already proved.

    Returns the authorize URL rather than redirecting: the caller is a browser
    XHR carrying a bearer token, which cannot be attached to a top-level
    navigation.
    """
    service = oauth_service or build_tiktok_oauth_service()
    state = service.issue_state(user_id)
    url = service.tiktok_auth.generate_auth_url(tiktok_redirect_uri(), state)
    logger.info(
        "tiktok_oauth_start_issued",
        extra={"user_id": str(user_id), "flow": SELLER_CONNECT_FLOW},
    )
    return TikTokOAuthStartResult(
        authorize_url=url,
        state_expires_in=DEFAULT_STATE_TTL_SECONDS,
    )


def build_partner_oauth_facade(
    session: AsyncSession,
    infra: TikTokOAuthInfrastructureService,
) -> TikTokOAuthService:
    """Construct the Auth-owned Partner OAuth facade sharing infra TikTokAuth."""
    redirect_uri = tiktok_redirect_uri()
    return TikTokOAuthService(
        tiktok_auth=infra.tiktok_auth,
        session=session,
        redirect_uri=redirect_uri,
        app_secret=infra.app_secret,
        binding_verifier=make_binding_verifier(
            app_key=infra.tiktok_auth.app_key, app_secret=infra.app_secret
        ),
    )


async def complete_tiktok_oauth_callback(
    session: AsyncSession,
    *,
    code: str,
    state: str | None = None,
    app_key: str | None = None,
    locale: str | None = None,
    shop_region: str | None = None,
    oauth_service: TikTokOAuthInfrastructureService | None = None,
) -> TikTokOAuthCallbackResult:
    """Exchange the authorization code and persist tokens via the OAuth facade."""
    service = oauth_service or build_tiktok_oauth_service()

    # STATE IS MANDATORY IN PRODUCTION (#1748). Guarding the CSRF check with a
    # bare `if state:` made it bypassable by OMITTING the parameter — no forgery
    # needed, just leave it out. Measured on the deployed host:
    #
    #     ?code=x&state=forged   401   (verified, rejected)
    #     ?code=x                502   (never verified; exchange attempted)
    #
    # And the unverified path is not a read-only degradation. It falls through to
    # `handle_callback`, then `get_or_create`s a user, provisions a shop,
    # persists credentials and commits — bound to `_app_review_user_id()`, whose
    # default is `00000000-0000-4000-8000-000000000001`, a REAL existing user
    # rather than a throwaway. An unauthenticated caller holding a valid
    # authorization code could bind a shop's credentials to it.
    #
    # The no-state path exists for TikTok's app-review flow, whose callback
    # carries no state, so it is kept — but only outside production, where a
    # reviewer exercises it. In production a missing state is now refused
    # exactly like a forged one, which is what the threat model already claims
    # ("State parameter validated") and what this makes true.
    if not state and is_production():
        logger.warning(
            "tiktok_oauth_callback_missing_state_refused",
            extra={"environment": "production"},
        )
        raise Unauthorized("OAuth callback is missing the required state parameter")

    if state:
        # A present state means the seller started this from `/v1/auth/tiktok/start`
        # while signed in. `verify_state` rejects anything not signed by us, not
        # minted for this flow, or older than the state TTL; `resolve_seller_connect_owner`
        # then refuses to invent an owner. Between them there is no path from
        # here to `_app_review_user_id()` — deliberately (#1970).
        owner_id = resolve_seller_connect_owner(service.verify_state(state))
        try:
            token_data = await service.exchange_code(code, user_id=owner_id)
        except AuthenticationError as exc:
            raise TikTokOAuthTokenExchangeFailed from exc
        facade = build_partner_oauth_facade(session, service)
        shop = await facade.provision_shop_and_credentials(token_data, user_id=owner_id)
        await session.commit()
        return TikTokOAuthCallbackResult(
            status="ok",
            message="OAuth callback accepted; shop provisioned via Auth facade",
            open_id_present=bool(shop.tiktok_shop_id),
            access_token_expires_in=token_data.get("access_token_expire_in"),
        )

    try:
        result, token_data, callback_user_id = await service.handle_callback(
            code,
            state,
            app_key=app_key,
            locale=locale,
            shop_region=shop_region,
        )
    except AuthenticationError as exc:
        raise TikTokOAuthTokenExchangeFailed from exc

    # STATELESS APP-REVIEW PATH ONLY — unreachable in production (#1748) and
    # unreachable from the seller-initiated branch above (#1970), which returns
    # before here. `callback_user_id` is always None here (the branch condition
    # is `not state`, and `handle_callback` only derives an id from a state), so
    # this is the app-review row by construction, not by fallback.
    owner_id = callback_user_id or _app_review_user_id()
    await UsersRepo(session).get_or_create(owner_id, APP_REVIEW_USER_PHONE)
    facade = build_partner_oauth_facade(session, service)
    await facade.provision_shop_and_credentials(token_data, user_id=owner_id)
    await session.commit()
    return result


class TikTokOAuthInfrastructureService:
    """Validates OAuth callback parameters and exchanges authorization codes."""

    def __init__(self, *, app_secret: str, tiktok_auth: TikTokAuth) -> None:
        self._app_secret = app_secret
        self._tiktok_auth = tiktok_auth

    @property
    def tiktok_auth(self) -> TikTokAuth:
        return self._tiktok_auth

    @property
    def app_secret(self) -> str:
        return self._app_secret

    def issue_state(self, user_id: uuid.UUID) -> str:
        """Mint the signed state for a seller-initiated connect (#1970).

        Signed with ``TIKTOK_APP_SECRET`` — the same secret
        :meth:`verify_state` checks against, so a state this process minted is
        the only kind the callback will accept.
        """
        return mint_oauth_state(
            user_id,
            secret=self._app_secret,
            flow=SELLER_CONNECT_FLOW,
        )

    def verify_state(self, state: str) -> uuid.UUID:
        """Verify the signed state and return the embedded user id.

        Delegates to ``core.security.oauth_state`` so the signature check, the
        flow binding and the TTL are the same ones :meth:`issue_state` and the
        Auth facade use. Raises ``Unauthorized`` rather than returning ``None``
        for every rejection, so a caller cannot mistake a refusal for "no user
        named" and carry on.
        """
        return verify_oauth_state(
            state,
            secret=self._app_secret,
            expected_flow=SELLER_CONNECT_FLOW,
        ).user_id

    async def exchange_code(self, code: str, *, user_id: uuid.UUID | None = None) -> dict:
        """Exchange TikTok authorization code for access + refresh tokens."""
        logger.info(
            "tiktok_oauth_code_received",
            extra={
                "user_id": str(user_id) if user_id else None,
                "code_len": len(code),
            },
        )
        return await asyncio.to_thread(self._tiktok_auth.exchange_code, code)

    async def handle_callback(
        self,
        code: str,
        state: str | None = None,
        *,
        app_key: str | None = None,
        locale: str | None = None,
        shop_region: str | None = None,
    ) -> tuple[TikTokOAuthCallbackResult, dict, uuid.UUID | None]:
        """Validate callback parameters, verify state when present, exchange code."""
        user_id: uuid.UUID | None = None
        if state:
            user_id = self.verify_state(state)
        else:
            logger.warning(
                "tiktok_oauth_callback_missing_state",
                extra={
                    "app_key": app_key,
                    "locale": locale,
                    "shop_region": shop_region,
                },
            )

        try:
            token_data = await self.exchange_code(code, user_id=user_id)
        except AuthenticationError as exc:
            logger.warning(
                "tiktok_oauth_token_exchange_failed",
                extra={
                    "user_id": str(user_id) if user_id else None,
                    "tiktok_error_code": exc.code,
                    "request_id": exc.request_id,
                },
            )
            raise

        open_id = token_data.get("open_id")
        expires_in = token_data.get("access_token_expire_in")

        logger.info(
            "tiktok_oauth_token_exchange_completed",
            extra={
                "user_id": str(user_id) if user_id else None,
                "open_id_present": bool(open_id),
                "access_token_expires_in": expires_in,
            },
        )
        return (
            TikTokOAuthCallbackResult(
                status="ok",
                message="OAuth callback accepted; token exchange completed",
                open_id_present=bool(open_id),
                access_token_expires_in=expires_in,
            ),
            token_data,
            user_id,
        )
