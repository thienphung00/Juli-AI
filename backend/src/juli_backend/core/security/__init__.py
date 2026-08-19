"""Authentication and authorization."""

from juli_backend.core.security.credential_resolver import *  # noqa: F403
from juli_backend.core.security.dependencies import get_current_user
from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.jwt import verify_supabase_jwt
from juli_backend.core.security.tiktok_oauth import BindingVerifier, TikTokOAuthService

__all__ = [
    # #1200: the verifier seam services/tiktok/credential_binding.py implements.
    # Exported here so that module can reach it at the depth-2 package root.
    "BindingVerifier",
    "TikTokOAuthService",
    "Unauthorized",
    "get_current_user",
    "verify_supabase_jwt",
]
