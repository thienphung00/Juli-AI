"""Merchant capability tags (P2-A1 isolation) -- identity comes from the credential.

**No merchant id lives in code or env (fast track P61-G, D71.6, owner 2026-10-21).**
A merchant's identity is the ``merchant_authorization_id`` the connect flow stored on the
credential row, verified against TikTok's ``GET /authorization/{v}/shops`` by
``services/tiktok/credential_binding.py`` (distinctness + trust-on-first-use, no pinned ids).
The sandbox write-validation credential is the row whose own ``capability`` is
:attr:`TikTokCapability.SANDBOX_WRITE`; nothing compares a merchant id to a configured one.
``TIKTOK_PRODUCTION_MERCHANT_ID`` / ``TIKTOK_SANDBOX_MERCHANT_ID`` and the
``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID`` constants are gone (D71.4 had already removed the
literal defaults).

This module is only the vocabulary and the READ rule: which capabilities exist, and which of
them may serve a read. The safety invariants the old constants enforced now live next to the
data they need (a DB lookup, never a constant):

- sandbox writes can never reach a production merchant: ``SandboxWriteClientFactory`` requires
  the credential's capability to be ``sandbox_write``, and
  ``core/security/credential_resolver.py::resolve_sandbox_write_credential`` refuses a sandbox
  row whose merchant or shop cipher is shared with any non-sandbox credential;
- production paths never use the sandbox credential: the read / write resolvers and the
  production factories refuse a ``sandbox_write`` capability and any merchant id carried by a
  ``sandbox_write`` row.
"""

from __future__ import annotations

from enum import Enum


class TikTokCapability(str, Enum):
    """How a stored credential may be used in outbound TikTok traffic."""

    PRODUCTION_READ = "production_read"
    SANDBOX_WRITE = "sandbox_write"
    SELLER_CONNECT = "seller_connect"


def _capability_value(capability: TikTokCapability | str) -> str:
    if isinstance(capability, TikTokCapability):
        return capability.value
    return capability


#: Capabilities a READ may be served from, most specific first (#1365).
#:
#: This is the one place that says which capability grants a read, so the
#: capability -- not the shop id -- stays the authority. ``SELLER_CONNECT`` is
#: here because a seller who has just finished OAuth holds exactly that, and it
#: grants reads **for its own shop and nothing else**: membership in this tuple
#: is not a promotion to ``PRODUCTION_READ``, and the ordering only decides
#: which of a shop's own rows is preferred when it holds both.
#:
#: ``SANDBOX_WRITE`` is deliberately absent and must stay absent: the sandbox
#: merchant's credential is a write-validation credential and is unreachable
#: from any read path.
READ_CAPABILITIES: tuple[TikTokCapability, ...] = (
    TikTokCapability.PRODUCTION_READ,
    TikTokCapability.SELLER_CONNECT,
)


def is_read_capability(capability: TikTokCapability | str) -> bool:
    """Return True when a credential carrying ``capability`` may serve a read."""
    value = _capability_value(capability)
    return any(value == read.value for read in READ_CAPABILITIES)
