"""Resolve TikTok credentials for production sync and sandbox validation."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from juli_backend.core.security.credential_refresh import refresh_credential
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    READ_CAPABILITIES,
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
    `resolve_sandbox_write_credential` through the same package root.

    `resolve_sandbox_write_credential` must keep taking only `session` --
    every existing caller (`services/agent/composition.py`,
    `services/execution/sandbox_guard.py`) invokes it that way -- so
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


@dataclass(frozen=True)
class SandboxWriteOwner:
    """One ``sandbox_write`` credential, as the cross-tenant enumeration reports it.

    Identifiers and one boolean only -- never token material (P61-G, D71.6). ``collides`` is
    the 2026-08-18 invariant read from credentials alone: some credential of ANOTHER shop that
    is NOT ``sandbox_write`` carries the same merchant id or the same non-null shop cipher
    (migration 100, D71.6a: the sandbox shop's own ``seller_connect`` row is the same shop).
    """

    shop_id: uuid.UUID
    merchant_authorization_id: str | None
    collides: bool


class SandboxCredentialRefused(ValueError):
    """The sandbox_write credential cannot be used: it is ambiguous with a production one.

    Not a :class:`NotFound` on purpose: the credential exists and is refused, which is a
    configuration fault an operator must read, not a missing row a caller may shrug off.
    """


async def _enumerate_sandbox_write_credentials(session: AsyncSession) -> list[SandboxWriteOwner]:
    """Every ``sandbox_write`` credential across tenants, newest first.

    The one question that cannot be asked from inside a tenant scope (#2019, ADR-089
    decision 3): which shop holds the sandbox credential. On PostgreSQL it goes through
    migration 099's reviewed ``SECURITY DEFINER`` function (predicate refined by migration 100;
    identifiers + one boolean); on SQLite, where neither the function nor RLS exists, the same
    predicate runs as a plain query.

    DEPLOY ORDER: MIGRATIONS 099+100 FIRST, THEN THIS CODE (no existence probe, no silent
    fallback, like 061).
    """
    if session.get_bind().dialect.name == "postgresql":
        rows = await session.execute(
            text(
                "SELECT out_shop_id, out_merchant, out_collides "
                "FROM public.enumerate_sandbox_write_credentials()"
            )
        )
        return [SandboxWriteOwner(row[0], row[1], bool(row[2])) for row in rows.all()]

    sandbox = TikTokCredential
    other = aliased(TikTokCredential)
    collides = (
        select(other.id)
        .where(
            other.shop_id != sandbox.shop_id,
            other.capability.is_distinct_from(TikTokCapability.SANDBOX_WRITE.value),
            (
                (
                    sandbox.merchant_authorization_id.is_not(None)
                    & (other.merchant_authorization_id == sandbox.merchant_authorization_id)
                )
                | (sandbox.shop_cipher.is_not(None) & (other.shop_cipher == sandbox.shop_cipher))
            ),
        )
        .exists()
    )
    listed = await session.execute(
        select(sandbox.shop_id, sandbox.merchant_authorization_id, collides)
        .where(sandbox.capability == TikTokCapability.SANDBOX_WRITE.value)
        .order_by(sandbox.created_at.desc())
    )
    return [SandboxWriteOwner(row[0], row[1], bool(row[2])) for row in listed.all()]


async def sandbox_write_merchant_ids(session: AsyncSession) -> frozenset[str]:
    """Merchant ids carried by ``sandbox_write`` credentials -- read from the DB, never config.

    The production resolvers and factories refuse any credential holding one of these, so
    the sandbox write-validation merchant is unreachable from a read or a production write
    even if a row is mislabelled.
    """
    return frozenset(
        owner.merchant_authorization_id
        for owner in await _enumerate_sandbox_write_credentials(session)
        if owner.merchant_authorization_id
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
    sandbox_merchants = await sandbox_write_merchant_ids(session)
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
            or credential.merchant_authorization_id in sandbox_merchants
        ):
            # Unreachable through the repo's own filters; kept as the invariant
            # this function exists to hold, so a future change to either side
            # fails closed instead of widening a read. A row carrying no
            # capability at all is not read-capable either -- capability is the
            # authority, and absent is not permission.
            continue
        return await _lazy_refresh(session, credential)
    raise NoReadCredentialForShop(f"No read-capable TikTok credential for shop {shop_id}")


class NoWriteCredentialForShop(NotFound):
    """No credential this shop owns may serve a production write (fast track P61-B).

    A :class:`NotFound` for the same reason as :class:`NoReadCredentialForShop`.
    """


#: The capabilities a shop's own production write may be signed with (P61-B,
#: D71.2): the shop's OWN OAuth credential -- the row its reads use. The label
#: is Juli's (``merchant.py``), not a TikTok scope; what makes a write possible is
#: the ADR-085 gate set (``services/execution/production_write_resolver.py``) and
#: the ``ProductionWriteGuard`` allowlist, never the label alone.
#: ``SANDBOX_WRITE`` is deliberately absent: that credential writes the sandbox
#: merchant, which is never the seller's shop.
PRODUCTION_WRITE_CREDENTIAL_CAPABILITIES: tuple[TikTokCapability, ...] = READ_CAPABILITIES


async def resolve_write_credential_for_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> TikTokCredential:
    """Return the credential **this shop owns** that its production writes are signed with.

    The write-side twin of :func:`resolve_read_credential_for_shop`, with two
    more refusals: the row must name a merchant id, and that merchant must not
    be the sandbox write-validation merchant. No fallback to any configured
    merchant: a shop with nothing usable raises :class:`NoWriteCredentialForShop`.
    """
    repo = TikTokCredentialRepo(session)
    sandbox_merchants = await sandbox_write_merchant_ids(session)
    allowed = {capability.value for capability in PRODUCTION_WRITE_CREDENTIAL_CAPABILITIES}
    for capability in PRODUCTION_WRITE_CREDENTIAL_CAPABILITIES:
        try:
            credential = await repo.get_by_shop_and_capability(shop_id, capability)
        except NotFound:
            continue
        if (
            credential.shop_id != shop_id
            or credential.capability not in allowed
            or not credential.merchant_authorization_id
            or credential.merchant_authorization_id in sandbox_merchants
        ):
            continue
        return await _lazy_refresh(session, credential)
    raise NoWriteCredentialForShop(f"No write-capable TikTok credential for shop {shop_id}")


async def resolve_sandbox_write_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return the sandbox write-validation credential: the row whose capability says so.

    Identified by ``capability = sandbox_write`` and nothing else (P61-G, D71.6): no
    configured merchant id. The enumeration is the one cross-tenant read (#2019); the token is
    re-read under the owning shop's scope through the repo that decrypts it.

    Refuses (:class:`SandboxCredentialRefused`) a sandbox row with no merchant id, and one that
    *collides* with a non-sandbox credential of ANOTHER shop (same merchant id or cipher) -- the
    2026-08-18 defect, a production token filed as ``sandbox_write``, caught at resolve time
    from the credentials alone. Raises :class:`NotFound` when no sandbox credential exists.
    """
    owners = await _enumerate_sandbox_write_credentials(session)
    if not owners:
        raise NotFound("No sandbox_write credential exists")
    owner = owners[0]
    if not owner.merchant_authorization_id:
        raise SandboxCredentialRefused(
            "the sandbox_write credential carries no merchant authorization id"
        )
    if owner.collides:
        raise SandboxCredentialRefused(
            "the sandbox_write credential shares its merchant id or shop cipher with a "
            "non-sandbox credential of another shop; a sandbox write could reach a production "
            "merchant, so it is refused (reconnect the sandbox shop)"
        )
    repo = TikTokCredentialRepo(session)
    if session.get_bind().dialect.name != "postgresql":
        credential = await repo.get_by_shop_and_capability(
            owner.shop_id, TikTokCapability.SANDBOX_WRITE
        )
        return await _lazy_refresh(session, credential)
    async with with_shop_scope(session, owner.shop_id):
        credential = await repo.get_by_shop_and_capability(
            owner.shop_id, TikTokCapability.SANDBOX_WRITE
        )
        return await _lazy_refresh(session, credential)
