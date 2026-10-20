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
e.g. ``TIKTOK_APP_KEY``), so a deployment onboards its own production/sandbox
merchants without a code edit:

- ``TIKTOK_PRODUCTION_MERCHANT_ID`` -> ``TikTokCapability.PRODUCTION_READ``
- ``TIKTOK_SANDBOX_MERCHANT_ID``    -> ``TikTokCapability.SANDBOX_WRITE``

**No default (fast track P61-D, D71.4).** These used to fall back to Juli's own
merchant ids as literals in this file. They no longer do: unset means ``""``.
Every code path that NEEDS one fails closed with :class:`MerchantIdNotConfigured`
(a ``ValueError`` naming the variable) -- through :func:`require_production_auth_id`
/ :func:`require_sandbox_auth_id`, or the equivalent ``if not ...`` guards in
``factories.py`` / ``workers/services/polling/orchestrate.py``. Paths that only
CLASSIFY (``resolve_merchant_context``) treat an unset id as "no configured
merchant", so every shop is ``SELLER_CONNECT``. API and worker boot log a
``runtime_env_missing`` warning for each unset id (``core/config/runtime_env.py``).

**Update (#1246), correcting a caveat that used to be true here:** the
transport guards that actually build outbound clients --
``integrations/tiktok/capabilities.py`` and ``factories.py``'s
``ProductionReadClientFactory`` / ``SandboxWriteClientFactory`` -- used to
hold their own independent literal copies of these two IDs, disconnected
from the env config above. #1234 alone was not enough to onboard a new
deployment: setting the two env vars correctly reclassified a merchant here,
but the transport guards still hard-compared against Juli's compiled-in
IDs and raised ``ValueError`` for any other merchant. #1246 fixed that --
``capabilities.py`` now re-exports these two names from this module instead
of redefining them, so the transport guards read the same env-configured
values as ``resolve_merchant_context``/``is_cross_merchant_lookup`` above.
Setting the two env vars now genuinely onboards a new deployment's
production/sandbox merchants end to end, transport guards included.
"""

from __future__ import annotations

import os
from enum import Enum

PRODUCTION_MERCHANT_ID_ENV = "TIKTOK_PRODUCTION_MERCHANT_ID"
SANDBOX_MERCHANT_ID_ENV = "TIKTOK_SANDBOX_MERCHANT_ID"

# No literal default (P61-D): unset is "", and a path that needs one fails closed.
PRODUCTION_AUTH_ID = os.getenv(PRODUCTION_MERCHANT_ID_ENV, "").strip()
SANDBOX_AUTH_ID = os.getenv(SANDBOX_MERCHANT_ID_ENV, "").strip()


class MerchantIdNotConfigured(ValueError):
    """A code path needs a configured merchant id and its env var is unset or empty.

    A ``ValueError`` so every caller that already refused a misconfigured merchant
    with ``ValueError`` keeps refusing; the name and ``env_var`` make the log say
    which variable to set. Never carries a value.
    """

    def __init__(self, env_var: str, *, needed_for: str) -> None:
        self.env_var = env_var
        self.needed_for = needed_for
        super().__init__(
            f"{env_var} is not set: {needed_for} needs it and refuses to run without it "
            "(there is no default merchant id; set it in the API / worker env)"
        )


def require_production_auth_id(*, needed_for: str = "production read") -> str:
    """The configured production-read merchant id, or :class:`MerchantIdNotConfigured`."""
    if not PRODUCTION_AUTH_ID:
        raise MerchantIdNotConfigured(PRODUCTION_MERCHANT_ID_ENV, needed_for=needed_for)
    return PRODUCTION_AUTH_ID


def require_sandbox_auth_id(*, needed_for: str = "sandbox write") -> str:
    """The configured sandbox-write merchant id, or :class:`MerchantIdNotConfigured`."""
    if not SANDBOX_AUTH_ID:
        raise MerchantIdNotConfigured(SANDBOX_MERCHANT_ID_ENV, needed_for=needed_for)
    return SANDBOX_AUTH_ID


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


def is_cross_merchant_lookup(
    merchant_authorization_id: str,
    capability: TikTokCapability | str,
) -> bool:
    """Return True when capability does not match the merchant authorization ID."""
    expected = _configured_merchants().get(merchant_authorization_id)
    if expected is None:
        return False
    return _capability_value(capability) != expected.value
