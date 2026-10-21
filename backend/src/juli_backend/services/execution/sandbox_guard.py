"""Sandbox write capability guard for real tool executors (#305 / #301)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security.credential_resolver import resolve_sandbox_write_credential
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    SandboxWriteClientFactory,
    SandboxWriteResources,
)

NOOP_TOOL_NAMES: frozenset[str] = frozenset({"noop.ping"})


def is_noop_tool(tool_name: str) -> bool:
    """Return True for smoke-test tools that skip TikTok write guards."""
    return tool_name in NOOP_TOOL_NAMES


def build_sandbox_write_resources(
    config: ClientFactoryConfig,
    *,
    factory: SandboxWriteClientFactory | None = None,
) -> SandboxWriteResources:
    """Build sandbox write resources — P2-B6/B7 handlers must use this entrypoint.

    The credential must be the ``sandbox_write`` one (its capability, P61-G, D71.6) and name a
    merchant; ``SandboxWriteClientFactory`` enforces both and refuses anything else.
    """
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
        merchant_auth_id=credential.merchant_authorization_id or "",
        shop_cipher=credential.shop_cipher,
        credential_capability=credential.capability,
    )
    return build_sandbox_write_resources(config, factory=factory)
