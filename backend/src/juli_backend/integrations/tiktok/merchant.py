"""Merchant authorization IDs and capability tags for P2-A1 isolation.

The production/sandbox merchant IDs below are Juli-internal operator labels,
not vendor facts: TikTok's ``GET /authorization/{v}/shops``
(``AuthorizationResource.list_all_shops()``) returns ``AuthorizedShop`` with
``id``/``cipher``/``name``/``region`` only -- there is no "this shop is our
sandbox" field to derive it from (issue #1234). What TikTok *can* tell us --
which shop a token actually reaches -- is already resolved by
``services/tiktok/credential_binding.py::resolve_authorized_shop`` /
``verify_capability_binding`` on every credential write; this module does not
duplicate that call.

So the two IDs and their capability pairing are sourced from environment
configuration, following this codebase's ``os.getenv(...)`` convention (see
e.g. ``TIKTOK_APP_KEY``), so a new deployment can onboard its own
production/sandbox merchants without a code edit:

- ``TIKTOK_PRODUCTION_MERCHANT_ID`` -> ``TikTokCapability.PRODUCTION_READ``
- ``TIKTOK_SANDBOX_MERCHANT_ID``    -> ``TikTokCapability.SANDBOX_WRITE``

**Honesty note (required, not glossed over):** when either variable is
unset, the constant below falls back to Juli's own already-committed
merchant ID as a literal default, purely so this deployment's existing
behaviour is unchanged by this refactor. That literal is Juli's value, not a
placeholder -- it is still a hardcoded merchant ID living in source. A NEW
deployment MUST set both env vars to onboard its own production/sandbox
merchants; leaving them unset means a new deployment's own shops will not
match either fallback ID (extremely unlikely to collide) and will resolve to
``SELLER_CONNECT``, never silently to Juli's ``PRODUCTION_READ`` /
``SANDBOX_WRITE`` treatment of Juli's own shops.
"""

from __future__ import annotations

import os
from enum import Enum

# Fallback defaults are Juli's own IDs, already committed in this file prior
# to #1234 -- kept only so an unconfigured deployment (this one, today)
# behaves identically to before. See module docstring "Honesty note".
PRODUCTION_AUTH_ID = os.getenv("TIKTOK_PRODUCTION_MERCHANT_ID", "7658073774813611784").strip()
SANDBOX_AUTH_ID = os.getenv("TIKTOK_SANDBOX_MERCHANT_ID", "7658096633384781588").strip()


class TikTokCapability(str, Enum):
    """How a stored credential may be used in outbound TikTok traffic."""

    PRODUCTION_READ = "production_read"
    SANDBOX_WRITE = "sandbox_write"
    SELLER_CONNECT = "seller_connect"


def _configured_merchants() -> dict[str, TikTokCapability]:
    """Merchant ID -> capability, read live from module-level env config.

    Recomputed per call (not module-level, and not cached) so it always
    reflects the current ``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID`` values
    -- which tests reload via env vars rather than mutating a frozen dict.
    """
    mapping: dict[str, TikTokCapability] = {}
    if PRODUCTION_AUTH_ID:
        mapping[PRODUCTION_AUTH_ID] = TikTokCapability.PRODUCTION_READ
    if SANDBOX_AUTH_ID:
        mapping[SANDBOX_AUTH_ID] = TikTokCapability.SANDBOX_WRITE
    return mapping


def resolve_merchant_context(
    merchant_authorization_id: str,
) -> tuple[str, TikTokCapability]:
    """Map a TikTok OAuth ``open_id`` to merchant auth ID + capability."""
    capability = _configured_merchants().get(merchant_authorization_id)
    if capability is not None:
        return merchant_authorization_id, capability
    return merchant_authorization_id, TikTokCapability.SELLER_CONNECT


def _capability_value(capability: TikTokCapability | str) -> str:
    if isinstance(capability, TikTokCapability):
        return capability.value
    return capability


def is_cross_merchant_lookup(
    merchant_authorization_id: str,
    capability: TikTokCapability | str,
) -> bool:
    """Return True when capability does not match the merchant authorization ID."""
    expected = _configured_merchants().get(merchant_authorization_id)
    if expected is None:
        return False
    return _capability_value(capability) != expected.value
