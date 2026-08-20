"""Resolve TikTok credentials for production sync and sandbox validation."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_refresh import refresh_credential
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokAuth,
    TikTokCapability,
)
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories.repos import TikTokCredentialRepo

_DEFAULT_BASE_URL = "https://open-api.tiktokglobalshop.com"


def build_refresh_auth_from_env() -> TikTokAuth | None:
    """Build the `TikTokAuth` both the lazy layer and the beat
    (`workers/tasks/credential_refresh_beat.py`) refresh through (ADR-081
    decision 1, rows 1 and 2), from env -- the same `TIKTOK_APP_KEY`/
    `TIKTOK_APP_SECRET`/`TIKTOK_API_BASE_URL` pattern
    `services/action_cards/refresh.py::_poll_env_ready` and
    `services/cdp_speed/targeted_fetch_executor.py::partner_fetch_env_ready`
    already use.

    Public (not `_`-prefixed) so the beat task can reach it at the
    `core.security` package root (`from juli_backend.core.security import
    credential_resolver`) without a depth-3 deep import
    (`workers -> core.security.credential_resolver` is depth 3;
    `.importlinter.toml`'s `max_cross_package_depth` caps at 2) --
    mirroring how `services/agent/composition.py` already reaches
    `resolve_production_read_credential` through the same package root.

    Both `resolve_production_read_credential` and
    `resolve_sandbox_write_credential` must keep taking only `session` --
    every existing caller (`services/agent/composition.py`,
    `services/execution/sandbox_guard.py`,
    `workers/services/polling/orchestrate.py`) invokes them that way -- so
    there is no per-call app-credential parameter to thread through; env is
    the only seam available here. Returns `None` when TikTok app
    credentials are not configured, in which case the lazy layer (and the
    beat) are a no-op: the same as every resolve before this slice existed.
    """
    app_key = os.getenv("TIKTOK_APP_KEY", "").strip()
    app_secret = os.getenv("TIKTOK_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        return None
    base_url = os.getenv("TIKTOK_API_BASE_URL", "").strip() or _DEFAULT_BASE_URL
    return TikTokAuth(app_key=app_key, app_secret=app_secret, base_url=base_url)


async def _lazy_refresh(session: AsyncSession, credential: TikTokCredential) -> TikTokCredential:
    """ADR-081 decision 1, row 2 -- the lazy layer: covers beat downtime, so
    a worker that was down when the beat should have run still gets a warm
    token on the next hot-path resolve.

    Issues **no vendor call on every hot-path resolve**: `refresh_credential`
    carries its own freshness guard (`REFRESH_BUFFER`, 24h) and returns
    `fresh` immediately, without touching the vendor, for any credential
    outside the window -- this function does not duplicate that check, it
    just always calls through and lets the one guarded door decide.
    """
    auth = build_refresh_auth_from_env()
    if auth is None:
        return credential
    outcome = await refresh_credential(session, credential.id, auth=auth, force=False)
    return outcome.credential


async def resolve_production_read_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return Fujiwa production-read credentials — never falls back to latest."""
    credential = await TikTokCredentialRepo(session).get_by_merchant(
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )
    return await _lazy_refresh(session, credential)


async def resolve_sandbox_write_credential(
    session: AsyncSession,
) -> TikTokCredential:
    """Return SANDBOX_VN write-validation credentials."""
    credential = await TikTokCredentialRepo(session).get_by_merchant(
        SANDBOX_AUTH_ID,
        TikTokCapability.SANDBOX_WRITE,
    )
    return await _lazy_refresh(session, credential)
