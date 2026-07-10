"""Capability-separated TikTok client factories for P2-A1 merchant isolation."""

from __future__ import annotations

from dataclasses import dataclass

from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    MerchantCapability,
)
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.guarded_client import GuardedTikTokClient
from juli_backend.integrations.tiktok.guards import (
    ReadOnlyTransportGuard,
    SandboxOnlyWriteGuard,
)

DEFAULT_BASE_URL = "https://open-api.tiktokglobalshop.com"


@dataclass(frozen=True)
class ClientFactoryConfig:
    """Inputs required to build a guarded TikTok client."""

    app_key: str
    app_secret: str
    access_token: str
    merchant_auth_id: str
    shop_cipher: str | None = None
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 15


class ProductionReadClientFactory:
    """Build Fujiwa production-read clients with read-only transport guard."""

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        if config.merchant_auth_id != PRODUCTION_AUTH_ID:
            raise ValueError(
                "ProductionReadClientFactory requires Fujiwa merchant auth ID "
                f"({PRODUCTION_AUTH_ID}); got {config.merchant_auth_id}"
            )
        inner = TikTokClient(
            app_key=config.app_key,
            app_secret=config.app_secret,
            access_token=config.access_token,
            base_url=config.base_url,
            shop_cipher=config.shop_cipher,
            timeout=config.timeout,
        )
        return GuardedTikTokClient(
            inner,
            guard=ReadOnlyTransportGuard(),
            capability=MerchantCapability.PRODUCTION_READ,
            merchant_auth_id=config.merchant_auth_id,
        )


class SandboxWriteClientFactory:
    """Build SANDBOX_VN write-validation clients with sandbox-only transport guard."""

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        if config.merchant_auth_id != SANDBOX_AUTH_ID:
            raise ValueError(
                "SandboxWriteClientFactory requires SANDBOX_VN merchant auth ID "
                f"({SANDBOX_AUTH_ID}); got {config.merchant_auth_id}"
            )
        inner = TikTokClient(
            app_key=config.app_key,
            app_secret=config.app_secret,
            access_token=config.access_token,
            base_url=config.base_url,
            shop_cipher=config.shop_cipher,
            timeout=config.timeout,
        )
        return GuardedTikTokClient(
            inner,
            guard=SandboxOnlyWriteGuard(),
            capability=MerchantCapability.SANDBOX_WRITE,
            merchant_auth_id=config.merchant_auth_id,
        )
