"""TikTok OAuth service: authorization flow, shop provisioning, token refresh.

Orchestrates TikTokAuth (integrations/tiktok) with the persistence layer (data)
to provide a complete OAuth lifecycle for connecting TikTok Shops.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_refresh import (
    REFRESH_BUFFER,
    RefreshOutcome,
    RefreshStatus,
    refresh_credential,
)
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import (
    TikTokAuth,
    TikTokCapability,
    resolve_merchant_context,
)
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
    ) -> Shop:
        """Single write owner for ``shops`` + ``tiktok_credentials`` (Partner OAuth)."""
        open_id = token_data.get("open_id")
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not open_id or not access_token or not refresh_token:
            raise Unauthorized("Incomplete TikTok token payload")

        seller_name = token_data.get("seller_name", "TikTok Shop")
        shops_repo = ShopsRepo(self._session)
        cred_repo = TikTokCredentialRepo(self._session)

        existing = await shops_repo.get_by_tiktok_id(open_id)

        if existing and existing.user_id == user_id:
            shop = existing
        elif existing:
            logger.warning(
                "tiktok_shop_already_claimed",
                extra={
                    "tiktok_shop_id": open_id,
                    "user_id": str(user_id),
                },
            )
            raise Unauthorized("This TikTok shop is already connected to another account")
        else:
            shop = await shops_repo.create(
                user_id=user_id,
                shop_name=seller_name,
                tiktok_shop_id=open_id,
            )

        expires_at = access_token_expires_at(token_data.get("access_token_expire_in"))
        merchant_authorization_id, capability = resolve_merchant_context(open_id)
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

        logger.info(
            "tiktok_oauth_completed",
            extra={"user_id": str(user_id), "shop_id": str(shop.id)},
        )
        return shop

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
        """Build an HMAC-signed state parameter encoding user_id + nonce."""
        payload = json.dumps({"user_id": str(user_id), "nonce": secrets.token_urlsafe(16)})
        encoded = base64.urlsafe_b64encode(payload.encode()).decode()
        signature = hmac.new(
            self._app_secret.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        return f"{encoded}.{signature}"

    def _verify_state(self, state: str) -> uuid.UUID:
        """Verify HMAC signature and extract user_id from state parameter."""
        parts = state.split(".", 1)
        if len(parts) != 2:
            raise Unauthorized("Invalid OAuth state")

        encoded, signature = parts
        expected = hmac.new(self._app_secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(signature, expected):
            raise Unauthorized("Invalid OAuth state signature")

        try:
            payload = json.loads(base64.urlsafe_b64decode(encoded))
            return uuid.UUID(payload["user_id"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise Unauthorized(f"Malformed OAuth state: {exc}")
