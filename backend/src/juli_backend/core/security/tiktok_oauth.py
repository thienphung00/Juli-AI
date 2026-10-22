"""TikTok OAuth service: authorization flow, shop provisioning, token refresh.

Orchestrates TikTokAuth (integrations/tiktok) with the persistence layer (data)
to provide a complete OAuth lifecycle for connecting TikTok Shops.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import NoReturn, Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_refresh import (
    REFRESH_BUFFER,
    RefreshOutcome,
    RefreshStatus,
    refresh_credential,
)
from juli_backend.core.security.credential_resolver import (
    SandboxCollisionRefused,
    refuse_cross_shop_sandbox_collision,
)
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.oauth_state import (
    SELLER_CONNECT_FLOW,
    mint_oauth_state,
    verify_oauth_state,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import with_shop_scope, with_user_scope
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo
from juli_backend.services.tiktok.token_expiry import access_token_expires_at

logger = logging.getLogger(__name__)

# Re-exported for backward compatibility: this used to be the module that
# defined REFRESH_BUFFER (30 minutes). The single source of truth is now
# core/security/credential_refresh.py (24 hours, ADR-081 decision 2), shared
# with W4-3's beat scan predicate.
__all__ = ["BindingVerifier", "REFRESH_BUFFER", "TikTokOAuthService"]


class BindingVerifier(Protocol):
    """Verifies which merchant a credential's token really reaches (issue #1200).

    Defined here, in `core`, rather than imported from `services`: a
    `core -> services` import is a forbidden edge, and even a `TYPE_CHECKING`
    guard does not help — the boundary checker reads the AST, not the runtime
    graph. Structural typing means the `services`-side implementation satisfies
    this without either package importing the other's concrete module.

    Returns the verified `shop_cipher`; raises when the token's real merchant
    disagrees with the capability it is being filed under.
    """

    async def __call__(
        self,
        session: AsyncSession,
        *,
        capability: TikTokCapability | str,
        access_token: str,
    ) -> str: ...


def _unwrap_for_legacy_caller(outcome: RefreshOutcome) -> TikTokCredential:
    """Translate a :class:`RefreshOutcome` back into the pre-#1231 contract.

    ``transient``/``needs_reauth`` re-raise the exact vendor exception
    ``refresh_credential`` caught, so a caller of ``refresh_tokens`` /
    ``refresh_merchant_tokens`` observes the identical failure it always did.
    ``locked`` returns whatever credential we have rather than raising: no
    caller of these two methods ever encountered lock contention before
    (there was no lock), so there is no old behaviour to preserve for that
    case, and failing the caller over a few hundred milliseconds of
    contention would itself be a regression relative to doing nothing.
    """
    if outcome.status in (RefreshStatus.TRANSIENT, RefreshStatus.NEEDS_REAUTH):
        if outcome.error is not None:
            raise outcome.error
    return outcome.credential


class TikTokOAuthService:
    """Manages TikTok OAuth lifecycle: initiate, callback, token refresh."""

    def __init__(
        self,
        tiktok_auth: TikTokAuth,
        session: AsyncSession,
        redirect_uri: str,
        app_secret: str,
        binding_verifier: BindingVerifier,
    ) -> None:
        self._tiktok_auth = tiktok_auth
        self._session = session
        self._redirect_uri = redirect_uri
        self._app_secret = app_secret
        # Issue #1200. Required, never defaulted: a default would let a caller
        # provision a credential without verifying which merchant its token
        # actually reaches, which is the hole this closes. Injected rather than
        # imported because `core -> integrations` is a forbidden edge.
        self._binding_verifier = binding_verifier

    async def initiate_oauth(self, user_id: uuid.UUID) -> str:
        """Generate TikTok authorization URL with signed state parameter."""
        state = self._build_state(user_id)
        url = self._tiktok_auth.generate_auth_url(self._redirect_uri, state)
        logger.info("tiktok_oauth_initiated", extra={"user_id": str(user_id)})
        return url

    async def handle_callback(self, code: str, state: str) -> Shop:
        """Exchange auth code for tokens, provision shop + credential.

        Verifies the HMAC-signed state, exchanges the authorization code via
        TikTokAuth, then creates (or reconnects) a Shop with its credential.
        """
        user_id = self._verify_state(state)
        token_data = await asyncio.to_thread(self._tiktok_auth.exchange_code, code)
        return await self.provision_shop_and_credentials(token_data, user_id=user_id)

    async def provision_shop_and_credentials(
        self,
        token_data: dict,
        *,
        user_id: uuid.UUID,
        capability: TikTokCapability | None = None,
    ) -> Shop:
        """Provision under the write-time sandbox-collision guard (P61-H, D71.6a).

        The whole write (shop + credential) runs in a savepoint; if it would give a
        ``sandbox_write`` credential a cross-shop collision -- another shop's non-sandbox
        credential carrying its merchant id or cipher, or a ``sandbox_write`` row reaching
        another shop's -- nothing is written and :class:`SandboxCollisionRefused` is raised.
        """
        async with refuse_cross_shop_sandbox_collision(
            self._session,
            operation="oauth_provision",
            log_extra={
                "user_id": str(user_id),
                "tiktok_shop_id": token_data.get("open_id"),
                "capability": capability.value if capability else None,
            },
        ):
            return await self._provision_shop_and_credentials(
                token_data, user_id=user_id, capability=capability
            )

    async def _provision_shop_and_credentials(
        self,
        token_data: dict,
        *,
        user_id: uuid.UUID,
        capability: TikTokCapability | None = None,
    ) -> Shop:
        """Single write owner for ``shops`` + ``tiktok_credentials`` (Partner OAuth).

        The merchant identity is the OAuth ``open_id`` the connect flow returned (P61-G,
        D71.6: nothing configured). The capability is, in order: the one the caller asked for
        (an operator provisioning the ``sandbox_write`` credential), the capability this
        shop's existing credential for this merchant already carries (a re-authorisation
        refreshes the same row, so a reconnected sandbox shop stays ``sandbox_write``), else
        ``seller_connect`` -- what every seller who connects their own shop holds. The
        injected binding verifier then checks which shop the token really reaches.
        """
        open_id = token_data.get("open_id")
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not open_id or not access_token or not refresh_token:
            raise Unauthorized("Incomplete TikTok token payload")

        seller_name = token_data.get("seller_name", "TikTok Shop")
        shops_repo = ShopsRepo(self._session)
        cred_repo = TikTokCredentialRepo(self._session)

        # P61-I (owner, 2026-10-22): the callback carries no JWT, so the request session has no
        # tenant scope, and on `juli_app` (RLS enforced, ADR-086) both inserts below are refused
        # without one. The owner is the verified-state user (`resolve_seller_connect_owner`),
        # so the shop lookup/insert runs under THAT user's scope, and the credential rows under
        # the (new or existing) shop's scope -- the narrowest scope each table's policy keys on.
        async with with_user_scope(self._session, user_id):
            shop = await self._claim_or_create_shop(
                shops_repo,
                open_id=open_id,
                seller_name=seller_name,
                user_id=user_id,
            )
            await self._session.flush()

        async with with_shop_scope(self._session, shop.id):
            await self._write_credentials(
                cred_repo,
                shop,
                token_data=token_data,
                open_id=open_id,
                access_token=access_token,
                refresh_token=refresh_token,
                capability=capability,
            )

        logger.info(
            "tiktok_oauth_completed",
            extra={"user_id": str(user_id), "shop_id": str(shop.id)},
        )
        return shop

    async def _claim_or_create_shop(
        self,
        shops_repo: ShopsRepo,
        *,
        open_id: str,
        seller_name: str,
        user_id: uuid.UUID,
    ) -> Shop:
        """The connecting user's shop for ``open_id``: reconnect it, or create it.

        Runs under the owner's USER scope, where a shop owned by ANOTHER account is invisible
        (``shops_select_public`` is keyed on the user). So "already connected to another
        account" is no longer a lookup result: the insert hits the unique constraint on
        ``shops.tiktok_shop_id`` and that violation is translated back into the same error.
        """
        existing = await shops_repo.get_by_tiktok_id(open_id)
        if existing and existing.user_id == user_id:
            # P16 (D25.13): a shop paused by a deauthorization or by Juli Ops
            # "Huỷ kết nối" resumes when its seller reconnects.
            existing.is_active = True
            return existing
        if existing:
            self._refuse_claimed_shop(open_id, user_id)
        try:
            # Savepoint: the unique violation must not poison the caller's transaction.
            async with self._session.begin_nested():
                return await shops_repo.create(
                    user_id=user_id,
                    shop_name=seller_name,
                    tiktok_shop_id=open_id,
                )
        except IntegrityError as exc:
            if "tiktok_shop_id" not in str(exc.orig):
                raise
            raced = await shops_repo.get_by_tiktok_id(open_id)
            if raced is not None and raced.user_id == user_id:
                raced.is_active = True
                return raced
            self._refuse_claimed_shop(open_id, user_id)

    @staticmethod
    def _refuse_claimed_shop(open_id: str, user_id: uuid.UUID) -> NoReturn:
        logger.warning(
            "tiktok_shop_already_claimed",
            extra={
                "tiktok_shop_id": open_id,
                "user_id": str(user_id),
            },
        )
        raise Unauthorized("This TikTok shop is already connected to another account")

    async def _write_credentials(
        self,
        cred_repo: TikTokCredentialRepo,
        shop: Shop,
        *,
        token_data: dict,
        open_id: str,
        access_token: str,
        refresh_token: str,
        capability: TikTokCapability | None,
    ) -> None:
        """Create or refresh the shop's credential row, under the shop's scope."""
        expires_at = access_token_expires_at(token_data.get("access_token_expire_in"))
        merchant_authorization_id = open_id
        if capability is None:
            existing_capability = (
                await self._session.execute(
                    select(TikTokCredential.capability)
                    .where(
                        TikTokCredential.shop_id == shop.id,
                        TikTokCredential.merchant_authorization_id == merchant_authorization_id,
                        TikTokCredential.capability.is_not(None),
                    )
                    .order_by(TikTokCredential.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            capability = (
                TikTokCapability(existing_capability)
                if existing_capability
                else TikTokCapability.SELLER_CONNECT
            )
        if capability is not TikTokCapability.SANDBOX_WRITE:
            # D73 (owner, 2026-10-22): the sandbox shop keeps ONLY its `sandbox_write` row. A
            # seller OAuth must not mint a `seller_connect` (or any other non-sandbox)
            # credential for a shop that already holds one -- same shop included (tightens
            # P61-H). The shop's own rows are visible under its scope; the refusal is the
            # generic connect error and the surrounding savepoint leaves nothing written.
            holds_sandbox = (
                await self._session.execute(
                    select(TikTokCredential.id)
                    .where(
                        TikTokCredential.shop_id == shop.id,
                        TikTokCredential.capability == TikTokCapability.SANDBOX_WRITE.value,
                    )
                    .limit(1)
                )
            ).first()
            if holds_sandbox is not None:
                logger.warning(
                    "tiktok_oauth_refused_shop_holds_sandbox_write",
                    extra={"shop_id": str(shop.id), "capability": capability.value},
                )
                raise SandboxCollisionRefused(frozenset({shop.id}))
        scopes = token_data.get("scopes")
        if scopes is None and token_data.get("granted_scopes") is not None:
            granted = token_data.get("granted_scopes")
            if isinstance(granted, list):
                scopes = ",".join(str(scope) for scope in granted)
            else:
                scopes = str(granted)

        # Issue #1200: ask the vendor which shop this token actually reaches,
        # and refuse the write if that disagrees with the capability it is being
        # filed under. Before this, the capability was asserted by a column and
        # verified by nothing -- a production token filed as `sandbox_write`
        # passed every guard (observed 2026-08-18). Runs BEFORE any write, so a
        # mislabelled credential is never persisted even briefly.
        verified_cipher = await self._binding_verifier(
            self._session, capability=capability, access_token=access_token
        )

        try:
            existing_cred = await cred_repo.get_by_merchant(
                merchant_authorization_id,
                capability,
            )
            await cred_repo.update_tokens(
                credential_id=existing_cred.id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
            )
            # The verified cipher is the binding; record it on the row so the
            # next write's distinctness/TOFU check has something to compare to.
            existing_cred.shop_cipher = verified_cipher
            # Issue #1714: a re-authorisation is exactly when the granted scope
            # list changes (the seller approved a newly requested scope, or
            # revoked one) -- the create branch below has always persisted
            # `scopes`, but this update branch dropped it, so a shop that
            # re-authorised kept whatever stale (often empty/None) scope list
            # its first `create` wrote. Assigning here, same as `shop_cipher`
            # above, relies on the caller's flush/commit to persist it.
            existing_cred.scopes = scopes
            # P16 (D25.13): fresh tokens end a "needs_reauth" state (an expired
            # authorization, or a Juli Ops disconnect) -- reconnecting resumes.
            existing_cred.status = "active"
            existing_cred.last_refresh_error = None
        except NotFound:
            await cred_repo.create(
                shop_id=shop.id,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                scopes=scopes,
                merchant_authorization_id=merchant_authorization_id,
                capability=capability.value,
                shop_cipher=verified_cipher,
            )

    async def refresh_tokens(self, shop_id: uuid.UUID) -> TikTokCredential:
        """Proactively refresh tokens if within REFRESH_BUFFER of expiry.

        Thin wrapper over ``credential_refresh.refresh_credential`` (ADR-081
        decision 4) -- kept exactly as ADR-081 specifies so the pre-#1231
        call sites (``orchestrate.py``, ``targeted_fetch_executor.py``) keep
        raising on refresh failure precisely as before, until W4-3 moves them
        onto the resolver directly ("nothing outside this slice breaks").
        """
        cred_repo = TikTokCredentialRepo(self._session)
        credential = await cred_repo.get_by_shop(shop_id)
        outcome = await refresh_credential(self._session, credential.id, auth=self._tiktok_auth)
        return _unwrap_for_legacy_caller(outcome)

    async def refresh_merchant_tokens(
        self,
        merchant_authorization_id: str,
        capability: TikTokCapability | str,
    ) -> TikTokCredential:
        """Refresh tokens for a merchant authorization ID + capability pair.

        Thin wrapper -- see ``refresh_tokens`` docstring.
        """
        cred_repo = TikTokCredentialRepo(self._session)
        credential = await cred_repo.get_by_merchant(merchant_authorization_id, capability)
        outcome = await refresh_credential(self._session, credential.id, auth=self._tiktok_auth)
        return _unwrap_for_legacy_caller(outcome)

    def _build_state(self, user_id: uuid.UUID) -> str:
        """Mint the signed seller-connect state (see ``core.security.oauth_state``).

        Delegates rather than re-implementing: this module and
        ``services/tiktok/oauth.py`` had two copies of the same HMAC
        construction, and #1970's TTL + flow binding had to land in both to
        mean anything.
        """
        return mint_oauth_state(
            user_id,
            secret=self._app_secret,
            flow=SELLER_CONNECT_FLOW,
        )

    def _verify_state(self, state: str) -> uuid.UUID:
        """Verify the signed state and return the user id it names."""
        return verify_oauth_state(
            state,
            secret=self._app_secret,
            expected_flow=SELLER_CONNECT_FLOW,
        ).user_id
