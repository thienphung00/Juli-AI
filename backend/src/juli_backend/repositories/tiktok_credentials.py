"""TikTok OAuth credentials and per-endpoint sync cursors.

Tokens are encrypted at rest (``database.token_crypto``). Every method that
hands a credential back first calls :func:`_hydrate_decrypted_tokens`, which
exposes the plaintext to the caller *without* dirtying the ORM columns -- so a
later ``flush()`` cannot accidentally write plaintext over the ciphertext.

Layering note: this module imports ``integrations.tiktok`` for
:class:`TikTokCapability` and :func:`is_cross_merchant_lookup`. That edge is
outside the ``repositories -> {models, database}`` matrix in
``.importlinter.toml`` and is carried in the import-boundary baseline on
purpose: the merchant/capability pairing is the value domain of the
``capability`` column, and the guard belongs next to the write it protects.
Moving the enum and the merchant map under ``models`` would retire the entry.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import set_committed_value

from juli_backend.database.exceptions import NotFound
from juli_backend.database.token_crypto import decrypt_token, encrypt_token
from juli_backend.integrations.tiktok import TikTokCapability, is_cross_merchant_lookup
from juli_backend.models.models import TikTokCredential, TikTokSyncState
from juli_backend.repositories._base import SessionRepo, utc_now_naive

NEEDS_REAUTH = "needs_reauth"


def _hydrate_decrypted_tokens(credential: TikTokCredential) -> TikTokCredential:
    """Expose plaintext tokens to the caller without marking the columns dirty."""
    set_committed_value(credential, "access_token", decrypt_token(credential.access_token))
    set_committed_value(credential, "refresh_token", decrypt_token(credential.refresh_token))
    return credential


def _capability_value(capability: TikTokCapability | str) -> str:
    return capability.value if isinstance(capability, TikTokCapability) else capability


class TikTokCredentialRepo(SessionRepo):
    async def create(
        self,
        shop_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        scopes: str | None = None,
        *,
        merchant_authorization_id: str | None = None,
        capability: str | None = None,
        shop_cipher: str | None = None,
    ) -> TikTokCredential:
        if merchant_authorization_id and capability:
            if is_cross_merchant_lookup(merchant_authorization_id, capability):
                raise ValueError("merchant_authorization_id and capability do not match")

        credential = TikTokCredential(
            id=uuid.uuid4(),
            shop_id=shop_id,
            merchant_authorization_id=merchant_authorization_id,
            capability=capability,
            shop_cipher=shop_cipher,
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token),
            token_expires_at=token_expires_at,
            scopes=scopes,
        )
        return _hydrate_decrypted_tokens(await self._add(credential))

    # -- reads (newest credential wins) -------------------------------------

    async def get_by_merchant(
        self,
        merchant_authorization_id: str,
        capability: TikTokCapability | str,
    ) -> TikTokCredential:
        """Newest credential for a merchant authorization id + capability pair.

        A pair the merchant map says cannot exist (production merchant asked
        for with the sandbox capability, or vice versa) is reported as
        :class:`NotFound` before touching the database, so a cross-merchant
        lookup can never return a row (#1234).
        """
        capability_value = _capability_value(capability)
        missing = NotFound(
            f"No credentials for merchant {merchant_authorization_id} "
            f"with capability {capability_value}"
        )
        if is_cross_merchant_lookup(merchant_authorization_id, capability_value):
            raise missing
        return await self._newest(
            TikTokCredential.merchant_authorization_id == merchant_authorization_id,
            TikTokCredential.capability == capability_value,
            missing=missing,
        )

    async def get_by_shop_and_capability(
        self,
        shop_id: uuid.UUID,
        capability: TikTokCapability | str,
    ) -> TikTokCredential:
        capability_value = _capability_value(capability)
        return await self._newest(
            TikTokCredential.shop_id == shop_id,
            TikTokCredential.capability == capability_value,
            missing=NotFound(
                f"No credentials found for shop {shop_id} with capability {capability_value}"
            ),
        )

    async def get_by_shop(self, shop_id: uuid.UUID) -> TikTokCredential:
        return await self._newest(
            TikTokCredential.shop_id == shop_id,
            missing=NotFound(f"No credentials found for shop {shop_id}"),
        )

    async def _newest(self, *criteria: Any, missing: NotFound) -> TikTokCredential:
        stmt = (
            select(TikTokCredential)
            .where(*criteria)
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
        credential = await self._one_or_none(stmt)
        if credential is None:
            raise missing
        return _hydrate_decrypted_tokens(credential)

    async def list_expiring_within(
        self,
        window: timedelta,
        *,
        now: datetime | None = None,
    ) -> list[TikTokCredential]:
        """Credentials whose access token expires within ``window`` of ``now``.

        This is the refresh beat's scan predicate (ADR-081 decisions 2/7/9).
        Rows already flagged ``needs_reauth`` are excluded even when inside the
        window: a terminal credential is not retried by the warm-keeping beat,
        only revived by the reactive layer.
        """
        cutoff = (now if now is not None else utc_now_naive()) + window
        stmt = (
            select(TikTokCredential)
            .where(
                TikTokCredential.token_expires_at <= cutoff,
                TikTokCredential.status != NEEDS_REAUTH,
            )
            .order_by(TikTokCredential.token_expires_at.asc())
        )
        return [_hydrate_decrypted_tokens(row) for row in await self._all(stmt)]

    # -- writes -------------------------------------------------------------

    async def update_tokens(
        self,
        credential_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
    ) -> TikTokCredential:
        credential = await self._require(credential_id)
        self._set_token_triad(credential, access_token, refresh_token, token_expires_at)
        await self._session.flush()
        return _hydrate_decrypted_tokens(credential)

    async def mark_refreshed(
        self,
        credential_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        refresh_token_expires_at: datetime | None = None,
    ) -> TikTokCredential:
        """Persist a successful rotation and its health signal (ADR-081 decisions 4/7).

        Beyond the token triad: ``last_refreshed_at`` is stamped, ``refresh_count``
        goes up by exactly one, and ``last_refresh_error`` is cleared -- a
        credential that was flagged and has since refreshed carries no stale
        error. ``refresh_token_expires_at`` is only written when supplied; the
        vendor rarely sends it, and omitting it must not clobber a value we
        captured earlier.
        """
        credential = await self._require(credential_id)
        self._set_token_triad(credential, access_token, refresh_token, token_expires_at)
        credential.last_refreshed_at = utc_now_naive()
        credential.refresh_count = credential.refresh_count + 1
        credential.last_refresh_error = None
        if refresh_token_expires_at is not None:
            credential.refresh_token_expires_at = refresh_token_expires_at
        await self._session.flush()
        return _hydrate_decrypted_tokens(credential)

    async def mark_needs_reauth(self, credential_id: uuid.UUID, error: str) -> TikTokCredential:
        """Flip a credential terminal, keeping its last-known-good tokens (ADR-081).

        Only ``status`` and ``last_refresh_error`` change. The tokens stay so an
        operator can diagnose without SSH; the refresh layers simply stop
        trusting them.
        """
        credential = await self._require(credential_id)
        credential.status = NEEDS_REAUTH
        credential.last_refresh_error = error
        await self._session.flush()
        return _hydrate_decrypted_tokens(credential)

    async def _require(self, credential_id: uuid.UUID) -> TikTokCredential:
        credential = await self._session.get(TikTokCredential, credential_id)
        if credential is None:
            raise NotFound(f"Credential {credential_id} not found")
        return credential

    @staticmethod
    def _set_token_triad(
        credential: TikTokCredential,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
    ) -> None:
        credential.access_token = encrypt_token(access_token)
        credential.refresh_token = encrypt_token(refresh_token)
        credential.token_expires_at = token_expires_at


# Sync-state dictionary key <-> TikTok endpoint. The dictionary shape is what
# the polling layer passes around; the endpoint name is what the table stores.
# LIVE endpoints A-26..A-29 are intentionally absent (#424).
_ENDPOINT_STATE_KEYS: dict[str, str] = {
    "orders": "orders_last_update_time",
    "products": "products_last_update_time",
    "returns": "returns_last_update_time",
    "inventory": "inventory_last_sync_at",
    "shop_sku_performance": "shop_sku_performance_last_sync_at",
    "shop_product_performance": "shop_product_performance_last_sync_at",
    "shop_performance": "shop_performance_last_sync_at",
    "shop_performance_per_hour": "shop_performance_per_hour_last_sync_at",
    "bestselling_products": "bestselling_products_last_sync_at",
    "bestselling_videos": "bestselling_videos_last_sync_at",
    "promotion_activity": "promotion_activity_last_sync_at",
}
_STATE_KEY_ENDPOINTS = {state_key: endpoint for endpoint, state_key in _ENDPOINT_STATE_KEYS.items()}


class TikTokSyncStateRepo(SessionRepo):
    """Incremental sync cursors, one row per ``(shop, endpoint)``."""

    async def load(self, shop_id: uuid.UUID) -> dict[str, Any]:
        """Return ``{state_key: last_update_time}`` for every known endpoint with a row."""
        rows = await self._all(select(TikTokSyncState).where(TikTokSyncState.shop_id == shop_id))
        state: dict[str, Any] = {}
        for row in rows:
            state_key = _ENDPOINT_STATE_KEYS.get(row.endpoint)
            if state_key is not None:
                state[state_key] = row.last_update_time
        return state

    async def save(self, shop_id: uuid.UUID, sync_state: dict[str, Any]) -> None:
        """Write the non-null cursors in ``sync_state``; unknown keys are ignored."""
        cursors = {
            _STATE_KEY_ENDPOINTS[state_key]: int(last_update_time)
            for state_key, last_update_time in sync_state.items()
            if state_key in _STATE_KEY_ENDPOINTS and last_update_time is not None
        }
        if not cursors:
            return

        existing_rows = await self._all(
            select(TikTokSyncState).where(
                TikTokSyncState.shop_id == shop_id,
                TikTokSyncState.endpoint.in_(cursors),
            )
        )
        existing = {row.endpoint: row for row in existing_rows}
        for endpoint, last_update_time in cursors.items():
            row = existing.get(endpoint)
            if row is None:
                self._session.add(
                    TikTokSyncState(
                        id=uuid.uuid4(),
                        shop_id=shop_id,
                        endpoint=endpoint,
                        last_update_time=last_update_time,
                    )
                )
            else:
                row.last_update_time = last_update_time
        await self._session.flush()


__all__ = ["NEEDS_REAUTH", "TikTokCredentialRepo", "TikTokSyncStateRepo"]
