"""Resolve TikTok credentials for production sync and sandbox validation."""

from __future__ import annotations

import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_refresh import refresh_credential
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    READ_CAPABILITIES,
    SANDBOX_AUTH_ID,
    TikTokAuth,
    TikTokCapability,
    is_read_capability,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokCredentialRepo

_DEFAULT_BASE_URL = "https://open-api.tiktokglobalshop.com"


def build_refresh_auth_from_env() -> TikTokAuth | None:
    """Build the `TikTokAuth` both the lazy layer and the beat
    (`workers/tasks/credential_refresh_beat.py`) refresh through (ADR-081
    decision 1, rows 1 and 2), from env -- the same `TIKTOK_APP_KEY`/
    `TIKTOK_APP_SECRET`/`TIKTOK_API_BASE_URL` pattern
    `services/action_cards/refresh.py::_poll_env_ready` and
    `services/cdp_speed/targeted_fetch_executor.py::partner_fetch_env_ready`
    already use.

    Public (not `_`-prefixed) so the beat task can reach it at the
    `core.security` package root (`from juli_backend.core.security import
    credential_resolver`) without a depth-3 deep import
    (`workers -> core.security.credential_resolver` is depth 3;
    `.importlinter.toml`'s `max_cross_package_depth` caps at 2) --
    mirroring how `services/agent/composition.py` already reaches
    `resolve_production_read_credential` through the same package root.

    Both `resolve_production_read_credential` and
    `resolve_sandbox_write_credential` must keep taking only `session` --
    every existing caller (`services/agent/composition.py`,
    `services/execution/sandbox_guard.py`,
    `workers/services/polling/orchestrate.py`) invokes them that way -- so
    there is no per-call app-credential parameter to thread through; env is
    the only seam available here. Returns `None` when TikTok app
    credentials are not configured, in which case the lazy layer (and the
    beat) are a no-op: the same as every resolve before this slice existed.
    """
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        return None
    base_url = os.getenv("TIKTOK_API_BASE_URL", "").strip() or _DEFAULT_BASE_URL
    return TikTokAuth(app_key=app_key, app_secret=app_secret, base_url=base_url)


async def _lazy_refresh(session: AsyncSession, credential: TikTokCredential) -> TikTokCredential:
    """ADR-081 decision 1, row 2 -- the lazy layer: covers beat downtime, so
    a worker that was down when the beat should have run still gets a warm
    token on the next hot-path resolve.

    Issues **no vendor call on every hot-path resolve**: `refresh_credential`
    carries its own freshness guard (`REFRESH_BUFFER`, 24h) and returns
    `fresh` immediately, without touching the vendor, for any credential
    outside the window -- this function does not duplicate that check, it
    just always calls through and lets the one guarded door decide.
    """
    auth = build_refresh_auth_from_env()
    if auth is None:
        return credential
    outcome = await refresh_credential(session, credential.id, auth=auth, force=False)
    return outcome.credential


async def _enumerate_owning_shop(
    session: AsyncSession,
    merchant_authorization_id: str,
    capability: TikTokCapability,
) -> uuid.UUID | None:
    """Which shop owns the configured merchant's credential — the one question
    that cannot be asked from inside a tenant scope (#2019, ADR-089 decision 3).

    `tiktok_credentials_select_public` carries qual `(shop_id =
    app_current_shop_id())` and the runtime connects as `juli_app`
    (`rolbypassrls = f`), so a scope-less read of this table returns nothing.
    But the scope the read needs is built FROM the row it is trying to read:
    `run_fujiwa_poll_cycle` enters `with_sticky_shop_scope(credential.shop_id)`
    on the line after the resolve. That circularity is what ADR-089 decision 3
    reserves an enumeration for, and migration 061 is this one — a reviewed,
    named `SECURITY DEFINER` function returning an identifier and nothing else.
    No token material crosses the tenant boundary; the tokens are read back
    below, under real scope, through the repo that decrypts them.

    Returns `None` when the function finds no such credential, and also on
    SQLite, where the function does not exist and RLS does not either. Both
    send the caller to the same unscoped repo read: on SQLite that is the only
    path and behaves exactly as it did before this slice, and on Postgres it is
    a read that is about to raise the canonical `NotFound` anyway. Branching on
    the dialect rather than probing for the function mirrors
    `workers/tasks/credential_refresh_beat.py`, which enumerates the same table
    the same way.

    DEPLOY ORDER: MIGRATION 061 FIRST, THEN THIS CODE. The branch above is on
    the DIALECT, not on whether the function exists, so against a Postgres that
    has not run 061 this raises `asyncpg.UndefinedFunctionError` rather than
    falling back to the old unscoped read. Measured, not assumed, during #2019
    review. That is deliberate -- a silent fallback would re-introduce exactly
    the scope-less read this exists to remove, and would do it invisibly. But it
    means shipping the code ahead of the migration changes the outage's shape
    instead of ending it. Expand-only migrations are safe to apply early; this
    one creates a function nothing calls until this code lands.
    """
    if session.get_bind().dialect.name != "postgresql":
        return None
    result = await session.execute(
        text(
            "SELECT out_shop_id FROM public.enumerate_credential_owner_shop(:merchant, :capability)"
        ).bindparams(
            merchant=merchant_authorization_id,
            capability=capability.value,
        )
    )
    return result.scalar_one_or_none()


async def _resolve_configured_merchant_credential(
    session: AsyncSession,
    merchant_authorization_id: str,
    capability: TikTokCapability,
) -> TikTokCredential:
    """Enumerate the owning shop, then do the real read inside that shop's scope.

    The shape `credential_refresh_beat` already runs in production: enumerate
    identifiers across tenants, then enter `with_shop_scope` and do every
    actual data access under it.

    `_lazy_refresh` stays INSIDE the scope deliberately. It UPDATEs and commits,
    and `tiktok_credentials_update_public` carries the same `shop_id` qual as
    the select policy, so the tenant scope is exactly the authority that write
    needs. Widening a cross-tenant exemption to cover a write on a token table
    would buy nothing and cost isolation.

    The read itself is still `get_by_merchant`, not a second hand-written
    query, so the cross-merchant guard (#1234), the newest-wins ordering and the
    canonical `NotFound` message all stay in the one place they already live.
    """
    repo = TikTokCredentialRepo(session)
    shop_id = await _enumerate_owning_shop(session, merchant_authorization_id, capability)
    if shop_id is None:
        credential = await repo.get_by_merchant(merchant_authorization_id, capability)
        return await _lazy_refresh(session, credential)
    async with with_shop_scope(session, shop_id):
        credential = await repo.get_by_merchant(merchant_authorization_id, capability)
        return await _lazy_refresh(session, credential)


async def resolve_production_read_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return Fujiwa production-read credentials — never falls back to latest."""
    return await _resolve_configured_merchant_credential(
        session,
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )


class NoReadCredentialForShop(NotFound):
    """No credential this shop owns may serve a read (#1365).

    Subclasses :class:`NotFound` on purpose: every route boundary that already
    translates ``NotFound`` answers 404, so a shop that does not exist and a
    shop that exists but is not the caller's are indistinguishable from the
    outside -- never a 403, which would be an existence oracle.

    This error replaces the silent ``None`` the read path used to hand back for
    any shop other than the one configured merchant. A shop scored over an
    empty database is a defect, and it must be loud.
    """


async def resolve_read_credential_for_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> TikTokCredential:
    """Return the credential **this shop owns** that may serve a read.

    Keyed on the pair that actually decides access -- the owning shop AND the
    capability the row carries:

    - only rows whose ``shop_id`` is ``shop_id`` are considered, so there is no
      path by which one merchant's data is read under another merchant's shop;
    - only ``READ_CAPABILITIES`` are considered, checked again on the way out,
      so a ``SANDBOX_WRITE`` credential is unreachable from here;
    - the capability is returned exactly as stored -- a ``SELLER_CONNECT``
      credential is never rewritten or treated as ``PRODUCTION_READ``;
    - there is **no fallback** to the configured production merchant. A shop
      with nothing usable raises :class:`NoReadCredentialForShop`.

    Holds no state between calls: every resolve is a fresh query, so a rollback
    cannot leave a cached resolution behind that lets a shop keep reading
    through a credential it does not own.
    """
    repo = TikTokCredentialRepo(session)
    for capability in READ_CAPABILITIES:
        try:
            credential = await repo.get_by_shop_and_capability(shop_id, capability)
        except NotFound:
            continue
        stored_capability = credential.capability
        if (
            credential.shop_id != shop_id
            or stored_capability is None
            or not is_read_capability(stored_capability)
        ):
            # Unreachable through the repo's own filters; kept as the invariant
            # this function exists to hold, so a future change to either side
            # fails closed instead of widening a read. A row carrying no
            # capability at all is not read-capable either -- capability is the
            # authority, and absent is not permission.
            continue
        return await _lazy_refresh(session, credential)
    raise NoReadCredentialForShop(f"No read-capable TikTok credential for shop {shop_id}")


async def resolve_sandbox_write_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return SANDBOX_VN write-validation credentials.

    Scoped through the same enumeration as the production read: the defect
    #2019 reports is identical here, because the shape is identical — a
    configured merchant id, no caller-supplied shop, and a policy keyed on a
    shop the caller does not yet know. It has not been seen in production only
    because the sandbox path runs far less often than a beat on a
    fifteen-minute cadence.
    """
    return await _resolve_configured_merchant_credential(
        session,
        SANDBOX_AUTH_ID,
        TikTokCapability.SANDBOX_WRITE,
    )
