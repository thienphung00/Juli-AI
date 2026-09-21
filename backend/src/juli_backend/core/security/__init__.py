"""Authentication and authorization."""

from juli_backend.core.security.credential_resolver import *  # noqa: F403
from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    resolve_production_read_credential,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
)
from juli_backend.core.security.dependencies import get_current_user
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksUnavailableError, supabase_jwks_url
from juli_backend.core.security.jwt import verify_supabase_jwt
from juli_backend.core.security.oauth_state import (
    DEFAULT_STATE_TTL_SECONDS,
    SELLER_CONNECT_FLOW,
    OAuthState,
    mint_oauth_state,
    verify_oauth_state,
)
from juli_backend.core.security.tiktok_oauth import BindingVerifier, TikTokOAuthService

__all__ = [
    # #1200: the verifier seam services/tiktok/credential_binding.py implements.
    # Exported here so that module can reach it at the depth-2 package root.
    "BindingVerifier",
    # #1970: the signed-OAuth-`state` primitive, exported at this package root
    # rather than deep-imported. `services/tiktok/oauth.py` mints and verifies
    # the state on the seller-connect path and is capped at cross-package depth
    # 2 by `.importlinter.toml`, so `core.security.oauth_state` is unreachable
    # from there -- the boundary check fails on it by name.
    "DEFAULT_STATE_TTL_SECONDS",
    # #1282: exported at the package root (rather than a deep import of
    # `core.security.jwks`) so `workers/agent_runtime_boot.py` -- capped at
    # cross-package depth 2 by `.importlinter.toml` -- can reach it for the
    # extended boot check 5.
    "JwksUnavailableError",
    "OAuthState",
    "SELLER_CONNECT_FLOW",
    # #1365: the per-shop read resolver and its named failure, exported at the
    # package root so the read path (`services/action_cards/refresh.py`, capped
    # at cross-package depth 2) can resolve the credential the REQUESTED shop
    # owns instead of the one globally configured merchant's.
    "NoReadCredentialForShop",
    "TikTokOAuthService",
    "Unauthorized",
    "get_current_user",
    "mint_oauth_state",
    # #1293: exported at the package root so services/action_cards/refresh.py --
    # capped at cross-package depth 2 by `.importlinter.toml` -- can resolve the
    # production-read shop before deciding whether to poll.
    "resolve_production_read_credential",
    "resolve_read_credential_for_shop",
    # #1969: sandbox write-validation credential resolver, already imported at
    # this package root by workers/services/polling/sync.py,
    # services/agent/composition.py, and integration tests -- genuinely
    # exported here rather than relying on the wildcard-import bleed-through
    # `credential_resolver` had no `__all__` to stop.
    "resolve_sandbox_write_credential",
    "supabase_jwks_url",
    "verify_oauth_state",
    "verify_supabase_jwt",
]
