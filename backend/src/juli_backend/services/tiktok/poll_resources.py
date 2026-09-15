"""Vendor resource construction for the Fujiwa poll cycle, kept on the
`services` side of the `workers -> integrations` boundary (#1949 review fix).

`.importlinter.toml` makes `workers -> integrations` a **forbidden edge**, not
merely a depth-capped one -- no `from juli_backend.integrations.tiktok.x import
y` shape fixes it, because the target *package* is disallowed for `workers`
importers at any depth. `services -> integrations` and `services -> core` are
both allowed, so this factory lives here and is called by
`workers/tasks/fujiwa_poll_beat.py` at the `services.tiktok` package root
(depth 2) instead of that task file touching `integrations.tiktok` or
`core.security.tiktok_oauth` directly.

Same reasoning `credential_binding.make_binding_verifier`'s docstring already
gives for `TikTokOAuthService` and `core -> integrations`: keep the vendor
dependency on the side of the boundary where it is allowed, instead of adding
a second grandfathered violation beside
`workers/services/polling/orchestrate.py`'s existing one
(`docs/architecture/import-boundary-baseline.json`).

`services/action_cards/refresh.py::maybe_poll_tiktok_data` builds this same
pair inline today (it is legal there since `services -> integrations` is
allowed); it is not migrated to call this factory in this change to keep the
fix scoped to the file CI actually flagged.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import TikTokOAuthService
from juli_backend.integrations.tiktok import RateLimiter, TikTokAuth
from juli_backend.services.tiktok.credential_binding import make_binding_verifier

DEFAULT_TIKTOK_API_BASE_URL = "https://open-api.tiktokglobalshop.com"


def build_fujiwa_poll_vendor_resources(
    session: AsyncSession,
    *,
    app_key: str,
    app_secret: str,
    redirect_uri: str,
    redis_url: str,
) -> tuple[TikTokOAuthService, RateLimiter]:
    """Build one cycle's `TikTokOAuthService` + `RateLimiter` pair from env values.

    Fresh every call by design -- callers construct these per cycle so a
    missed fire needs no reset (S-NFR-6) and no stale token or rate-limit-
    window state can leak from one cycle into the next.
    """
    import redis

    tiktok_auth = TikTokAuth(
        app_key=app_key,
        app_secret=app_secret,
        base_url=os.getenv("TIKTOK_API_BASE_URL", DEFAULT_TIKTOK_API_BASE_URL),
    )
    oauth_service = TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri=redirect_uri,
        app_secret=app_secret,
        binding_verifier=make_binding_verifier(app_key=app_key, app_secret=app_secret),
    )
    rate_limiter = RateLimiter(redis.from_url(redis_url))
    return oauth_service, rate_limiter
