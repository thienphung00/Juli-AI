"""Merchant authorization IDs and capability tags for P2-A1 isolation."""

from __future__ import annotations

from enum import Enum

PRODUCTION_AUTH_ID = "7658073774813611784"
SANDBOX_AUTH_ID = "7658096633384781588"


class TikTokCapability(str, Enum):
    """How a stored credential may be used in outbound TikTok traffic."""

    PRODUCTION_READ = "production_read"
    SANDBOX_WRITE = "sandbox_write"
    SELLER_CONNECT = "seller_connect"


_KNOWN_MERCHANTS: dict[str, TikTokCapability] = {
    PRODUCTION_AUTH_ID: TikTokCapability.PRODUCTION_READ,
    SANDBOX_AUTH_ID: TikTokCapability.SANDBOX_WRITE,
}


def resolve_merchant_context(
    merchant_authorization_id: str,
) -> tuple[str, TikTokCapability]:
    """Map a TikTok OAuth ``open_id`` to merchant auth ID + capability."""
    capability = _KNOWN_MERCHANTS.get(merchant_authorization_id)
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
    expected = _KNOWN_MERCHANTS.get(merchant_authorization_id)
    if expected is None:
        return False
    return _capability_value(capability) != expected.value
