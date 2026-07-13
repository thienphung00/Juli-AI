"""Sandbox write capability guard for real tool executors (#305 / #301)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_resolver import resolve_sandbox_write_credential
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    SandboxWriteClientFactory,
    SandboxWriteResources,
)
from juli_backend.integrations.tiktok.merchant import SANDBOX_AUTH_ID

NOOP_TOOL_NAMES: frozenset[str] = frozenset({"noop.ping"})


def is_noop_tool(tool_name: str) -> bool:
    """Return True for smoke-test tools that skip TikTok write guards."""
    return tool_name in NOOP_TOOL_NAMES


def build_sandbox_write_resources(
    config: ClientFactoryConfig,
    *,
    factory: SandboxWriteClientFactory | None = None,
) -> SandboxWriteResources:
    """Build SANDBOX_VN write resources — P2-B6/B7 handlers must use this entrypoint."""
    if config.merchant_auth_id != SANDBOX_AUTH_ID:
        raise ValueError(
            "Sandbox write tools require SANDBOX_VN merchant auth ID "
            f"({SANDBOX_AUTH_ID}); got {config.merchant_auth_id}"
        )
    return (factory or SandboxWriteClientFactory()).create_resources(config)


async def load_sandbox_write_resources(
    session: AsyncSession,
    *,
    app_key: str,
    app_secret: str,
    factory: SandboxWriteClientFactory | None = None,
) -> SandboxWriteResources:
    """Resolve SANDBOX_VN credentials and return guarded write resources."""
    credential = await resolve_sandbox_write_credential(session)
    config = ClientFactoryConfig(
        app_key=app_key,
        app_secret=app_secret,
        access_token=credential.access_token,
        merchant_auth_id=SANDBOX_AUTH_ID,
        shop_cipher=credential.shop_cipher,
    )
    return build_sandbox_write_resources(config, factory=factory)
