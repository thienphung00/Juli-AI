"""Authentication and authorization."""

from juli_backend.core.security.credential_resolver import *  # noqa: F403
from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    resolve_production_read_credential,
    resolve_read_credential_for_shop,
)
from juli_backend.core.security.dependencies import get_current_user
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwks import JwksUnavailableError, supabase_jwks_url
from juli_backend.core.security.jwt import verify_supabase_jwt
from juli_backend.core.security.tiktok_oauth import BindingVerifier, TikTokOAuthService

__all__ = [
    # #1200: the verifier seam services/tiktok/credential_binding.py implements.
    # Exported here so that module can reach it at the depth-2 package root.
    "BindingVerifier",
    # #1282: exported at the package root (rather than a deep import of
    # `core.security.jwks`) so `workers/agent_runtime_boot.py` -- capped at
    # cross-package depth 2 by `.importlinter.toml` -- can reach it for the
    # extended boot check 5.
    "JwksUnavailableError",
    # #1365: the per-shop read resolver and its named failure, exported at the
    # package root so the read path (`services/action_cards/refresh.py`, capped
    # at cross-package depth 2) can resolve the credential the REQUESTED shop
    # owns instead of the one globally configured merchant's.
    "NoReadCredentialForShop",
    "TikTokOAuthService",
    "Unauthorized",
    "get_current_user",
    # #1293: exported at the package root so services/action_cards/refresh.py --
    # capped at cross-package depth 2 by `.importlinter.toml` -- can resolve the
    # production-read shop before deciding whether to poll.
    "resolve_production_read_credential",
    "resolve_read_credential_for_shop",
    "supabase_jwks_url",
    "verify_supabase_jwt",
]
