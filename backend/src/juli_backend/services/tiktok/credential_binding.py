"""Vendor-verified capability binding for TikTok credentials (issue #1200).

## What this closes

`SandboxWriteClientFactory` asserts the credential's `sandbox_write` capability — a
value read from the `tiktok_credentials` row (P61-G, D71.6: no configured merchant id).
Nothing ever asked TikTok **which
shop the token actually reaches**, so a row could be labelled `sandbox_write`,
carry the correct `merchant_authorization_id`, pass every guard, and hold a
token authorized for the *production* shop.

That is not hypothetical. On 2026-08-18 exactly that row existed: correct
label, correct auth id, and a token TikTok reported as authorized for Fujiwa
Vietnam Store, with the same `shop_cipher` as the `production_read` row. Had a
cipher been present on it, an agent "sandbox write" would have issued a real
price update against the live store, permitted by every check in the system.
The only thing that prevented it was an unrelated NULL.

## The two invariants, and why they need nothing hardcoded

Both derive entirely from `GET /authorization/{v}/shops` — the vendor's own
answer to "who is this token?". Neither needs a pinned shop id, which matters:
a hardcoded expectation encodes facts about the operator's merchants into the
repo and goes stale the moment a shop changes.

1. **Distinctness.** No two capabilities may resolve to the same shop. This
   alone catches the 2026-08-18 case: `sandbox_write` and `production_read`
   had byte-identical ciphers. Note what it does *not* require — knowing which
   shop is the "right" one. Two capabilities pointing at one shop is provably
   wrong regardless of which shop it is.

2. **Stability (trust-on-first-use).** Once a capability has a recorded shop,
   a later credential write for that capability must resolve to the same shop.
   A change is rejected and surfaced rather than silently accepted, because the
   legitimate reason for a capability to change merchants is rare enough to
   deserve a human decision.

## Where this is enforced, and where it is not

Enforced **on write** (owner's decision, 2026-08-19), i.e. every path that
stores or refreshes a credential. Deliberately NOT enforced at resolve time, so
a row mutated after it was written — a hand fix, a database restore, a bad
migration — is not re-checked. The guarantee holds at the door but not over
time. Resolve-time enforcement is the recorded upgrade path if that residual
risk ever matters; see ADR-068's amendment.

## No migration

Both invariants are expressible with the `shop_cipher` column that already
exists, so this slice adds no schema. That also keeps Alembic `037` free for
W4-1 (ADR-081), which is the next planned migration.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Package-root imports: `services -> integrations` is an allowed edge
# (.importlinter.toml), but the depth-2 cap still applies, so reach the public
# package root rather than `.client` / `.resources.authorization`.
from juli_backend.core.security import (
    BindingVerifier,
    SandboxCollisionRefused,
    refuse_cross_shop_sandbox_collision,
)
from juli_backend.integrations.tiktok import (
    AuthorizationResource,
    TikTokCapability,
    TikTokClient,
    redact_shop_identifier,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories import TikTokCredentialRepo

logger = logging.getLogger(__name__)


class CredentialBindingError(Exception):
    """A credential's real merchant disagrees with the capability it is filed under.

    Deliberately not a subclass of the auth exceptions: this is not "the vendor
    rejected us", it is "we were about to store a credential that would let an
    agent act on the wrong shop".
    """


#: The capabilities these invariants govern. Both are *singleton, privileged*
#: bindings: exactly one merchant each, fixed for the deployment, and the pair
#: whose confusion causes an unintended production write.
#:
#: `seller_connect` is deliberately NOT here. It is the capability every seller
#: receives when connecting their own shop, so it is multi-shop by design --
#: multi-tenant onboarding (P13) depends on many rows sharing it. Applying
#: trust-on-first-use to it would break the second seller who ever connects, and
#: applying distinctness would reject the real current state, where
#: `seller_connect` and `sandbox_write` legitimately point at the same shop.
GOVERNED_CAPABILITIES: frozenset[str] = frozenset(
    {TikTokCapability.PRODUCTION_READ.value, TikTokCapability.SANDBOX_WRITE.value}
)


def _capability_value(capability: TikTokCapability | str | None) -> str:
    """`TikTokCredential.capability` is a nullable column, so rows really can
    carry `None`. Mapping that to `""` -- which is not in
    `GOVERNED_CAPABILITIES` -- makes a capability-less row *ungoverned*, which
    is the correct reading: there is no capability claim to verify against."""
    if capability is None:
        return ""
    return capability.value if isinstance(capability, TikTokCapability) else capability


def resolve_authorized_shop(*, app_key: str, app_secret: str, access_token: str) -> dict:
    """Ask TikTok which shop this access token is authorized for.

    Raises `CredentialBindingError` for zero shops (nothing to bind) and for
    more than one (ambiguous — a Partner token for these merchants maps to a
    single shop, and guessing which one is exactly the class of assumption this
    module exists to remove).
    """
    client = TikTokClient(app_key=app_key, app_secret=app_secret, access_token=access_token)
    shops = AuthorizationResource(client).list_all_shops()

    if not shops:
        raise CredentialBindingError(
            "TikTok reports this token is authorized for zero shops -- refusing to "
            "store a credential whose merchant cannot be established."
        )
    if len(shops) > 1:
        raise CredentialBindingError(
            f"TikTok reports this token is authorized for {len(shops)} shops. This "
            "module will not guess which one a capability is bound to -- bind the "
            "token to a single shop, or extend the model to carry the choice."
        )
    return shops[0]


async def verify_capability_binding(
    session: AsyncSession,
    *,
    capability: TikTokCapability | str,
    shop_cipher: str,
) -> None:
    """Apply both invariants to a freshly-resolved shop, before it is stored.

    `shop_cipher` is the vendor's own per-shop identifier, taken from
    `resolve_authorized_shop` above — never from the row being written, which
    would make the check circular.
    """
    capability_value = _capability_value(capability)

    # Multi-tenant capabilities are exempt by construction -- see
    # GOVERNED_CAPABILITIES for why applying these invariants to
    # `seller_connect` would be actively wrong rather than merely noisy.
    if capability_value not in GOVERNED_CAPABILITIES:
        logger.info(
            "tiktok_credential_binding_skipped_ungoverned_capability",
            extra={"capability": capability_value},
        )
        return

    rows = [
        row
        for row in (await session.execute(select(TikTokCredential))).scalars().all()
        if _capability_value(row.capability) in GOVERNED_CAPABILITIES
    ]

    # Invariant 1 -- distinctness. Another capability already reaching this shop
    # means one of the two is mislabelled; which one is a human's call, so this
    # refuses rather than picking.
    for row in rows:
        if row.shop_cipher != shop_cipher:
            continue
        if _capability_value(row.capability) == capability_value:
            continue
        raise CredentialBindingError(
            f"Refusing to store a {capability_value!r} credential for shop "
            f"{redact_shop_identifier(shop_cipher)}: capability "
            f"{row.capability!r} is already bound to that same shop. Two "
            "capabilities reaching one shop means one of them is mislabelled -- "
            "this is the 2026-08-18 defect (a production token filed as "
            "sandbox_write), and an agent write under the wrong label reaches the "
            "wrong merchant."
        )

    # Invariant 2 -- stability (trust-on-first-use). A capability that already
    # has a shop keeps it; a change is a decision, not a silent overwrite.
    for row in rows:
        if _capability_value(row.capability) != capability_value:
            continue
        if not row.shop_cipher or row.shop_cipher == shop_cipher:
            continue
        raise CredentialBindingError(
            f"Refusing to move capability {capability_value!r} from shop "
            f"{redact_shop_identifier(row.shop_cipher)} to "
            f"{redact_shop_identifier(shop_cipher)}. A capability changing "
            "merchants is rare enough to need a human decision -- clear the "
            "existing binding deliberately if this is intended."
        )

    logger.info(
        "tiktok_credential_binding_verified",
        extra={
            "capability": capability_value,
            "shop_cipher": redact_shop_identifier(shop_cipher),
        },
    )


async def _verify_and_return_cipher(
    session: AsyncSession,
    *,
    capability: TikTokCapability | str,
    access_token: str,
    app_key: str,
    app_secret: str,
) -> str:
    authorized_shop = resolve_authorized_shop(
        app_key=app_key, app_secret=app_secret, access_token=access_token
    )
    cipher = authorized_shop.get("cipher")
    if not cipher:
        raise CredentialBindingError(
            "TikTok returned an authorized shop with no cipher -- cannot establish which "
            "merchant this credential belongs to."
        )
    await verify_capability_binding(session, capability=capability, shop_cipher=cipher)
    return cipher


def make_binding_verifier(*, app_key: str, app_secret: str) -> BindingVerifier:
    """Build the verifier `TikTokOAuthService` is constructed with.

    Injected rather than imported, because `TikTokOAuthService` lives in `core`
    and `core -> integrations` is a forbidden edge (`.importlinter.toml`:
    core may reach only database/models/repositories). Passing a *callable*
    keeps the vendor dependency entirely on the `services` side of that line,
    where it is allowed, instead of adding a second grandfathered violation
    beside `tiktok_oauth.py`'s.

    Required at every construction site by design: a default would let a caller
    silently provision without verification, which is exactly the hole #1200
    closes.
    """

    async def _verifier(
        session: AsyncSession, *, capability: TikTokCapability | str, access_token: str
    ) -> str:
        return await _verify_and_return_cipher(
            session,
            capability=capability,
            access_token=access_token,
            app_key=app_key,
            app_secret=app_secret,
        )

    return _verifier


class ShopCipherUnresolvedError(CredentialBindingError):
    """A stored read credential has no ``shop_cipher`` and TikTok cannot supply one.

    Permanent until a human acts: the credential has been marked
    ``needs_reauth`` (so the fan-outs stop enqueueing the shop) and the seller
    must reconnect, which stores a verified cipher (P58-B, D67).
    """


#: ``(app_key=, app_secret=, access_token=) -> the single authorized shop``.
AuthorizedShopLookup = Callable[..., dict]

_CIPHER_NEEDS_REAUTH_MESSAGE = (
    "No shop_cipher stored for this credential and Get Authorized Shops could not "
    "supply one ({reason}). Every 202309 shop-scoped call needs it; reconnect the "
    "shop (re-run TikTok OAuth) to restore access."
)


async def backfill_shop_cipher(
    session: AsyncSession,
    credential: TikTokCredential,
    *,
    app_key: str,
    app_secret: str,
    lookup: AuthorizedShopLookup | None = None,
) -> str:
    """Return the credential's ``shop_cipher``, fetching and storing it when missing.

    TikTok's 202309 shop-scoped APIs (orders, products, promotions, ...) reject a
    request without ``shop_cipher`` (code 106013); ``TikTokClient`` only adds the
    query parameter when it has one. A read credential written before #1200 can
    have none, which made ``bootstrap_shop`` fail on every fan-out tick
    (2026-10-19). So: ask Get Authorized Shops (which needs no cipher), apply the
    same binding invariants the OAuth write applies, and persist it.

    A transient vendor failure propagates unchanged (the next tick retries). A
    definitive "no usable cipher" -- zero / several shops, a shop with no cipher,
    or a binding conflict -- marks the credential ``needs_reauth``, commits, and
    raises :class:`ShopCipherUnresolvedError`, so the shop stops being retried.
    """
    if credential.shop_cipher:
        return credential.shop_cipher
    find = lookup or resolve_authorized_shop
    repo = TikTokCredentialRepo(session)
    try:
        shop = await asyncio.to_thread(
            find, app_key=app_key, app_secret=app_secret, access_token=credential.access_token
        )
        cipher = str((shop or {}).get("cipher") or "").strip()
        if not cipher:
            raise CredentialBindingError("TikTok returned an authorized shop with no cipher")
        if credential.capability is not None:
            await verify_capability_binding(
                session, capability=credential.capability, shop_cipher=cipher
            )
    except CredentialBindingError as exc:
        reason = str(exc)[:300]
        await repo.mark_needs_reauth(
            credential.id, _CIPHER_NEEDS_REAUTH_MESSAGE.format(reason=reason)
        )
        await session.commit()
        logger.error(
            "tiktok_shop_cipher_unresolved",
            extra={
                "shop_id": str(credential.shop_id),
                "capability": credential.capability,
                "reason": reason,
            },
        )
        raise ShopCipherUnresolvedError(
            f"shop {credential.shop_id} has no shop_cipher and TikTok could not supply one; "
            "credential marked needs_reauth"
        ) from exc
    # Read before the guard: its savepoint rollback expires the ORM row.
    credential_id, credential_shop_id = credential.id, credential.shop_id
    try:
        # P61-H (D71.6a): a cipher that would collide with a sandbox_write credential of another
        # shop is refused like any other binding conflict.
        async with refuse_cross_shop_sandbox_collision(
            session,
            operation="shop_cipher_backfill",
            log_extra={
                "shop_id": str(credential_shop_id),
                "capability": credential.capability,
            },
        ):
            await repo.set_shop_cipher(credential_id, cipher)
    except SandboxCollisionRefused as exc:
        await repo.mark_needs_reauth(
            credential_id,
            _CIPHER_NEEDS_REAUTH_MESSAGE.format(reason="sandbox credential collision"),
        )
        await session.commit()
        raise ShopCipherUnresolvedError(
            f"shop {credential_shop_id} cipher collides with a sandbox credential; "
            "credential marked needs_reauth"
        ) from exc
    await session.commit()
    logger.warning(
        "tiktok_shop_cipher_backfilled",
        extra={
            "shop_id": str(credential.shop_id),
            "capability": credential.capability,
            "shop_cipher": redact_shop_identifier(cipher),
        },
    )
    return cipher
