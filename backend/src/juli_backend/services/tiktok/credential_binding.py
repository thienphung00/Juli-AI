"""Vendor-verified capability binding for TikTok credentials (issue #1200).

## What this closes

`SandboxWriteClientFactory` asserts `merchant_auth_id == SANDBOX_AUTH_ID` — a
value read from the `tiktok_credentials` row. Nothing ever asked TikTok **which
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

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Package-root imports: `services -> integrations` is an allowed edge
# (.importlinter.toml), but the depth-2 cap still applies, so reach the public
# package root rather than `.client` / `.resources.authorization`.
from juli_backend.core.security import BindingVerifier
from juli_backend.integrations.tiktok import (
    AuthorizationResource,
    TikTokCapability,
    TikTokClient,
    redact_shop_identifier,
)
from juli_backend.models.models import TikTokCredential

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


def _capability_value(capability: TikTokCapability | str) -> str:
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
