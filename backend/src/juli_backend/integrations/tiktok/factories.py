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
from juli_backend.integrations.tiktok.resources.authorization import AuthorizationResource
from juli_backend.integrations.tiktok.resources.fulfillment_writes import FulfillmentWriteResource
from juli_backend.integrations.tiktok.resources.inventory import InventoryResource
from juli_backend.integrations.tiktok.resources.orders import OrdersResource
from juli_backend.integrations.tiktok.resources.product_writes import ProductWriteResource
from juli_backend.integrations.tiktok.resources.products import ProductsResource
from juli_backend.integrations.tiktok.resources.returns import ReturnsResource

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


@dataclass(frozen=True)
class ProductionReadResources:
    """Layer 1 read resources wired to a Fujiwa production-read client."""

    authorization: AuthorizationResource
    orders: OrdersResource
    products: ProductsResource
    returns: ReturnsResource


@dataclass(frozen=True)
class SandboxWriteResources:
    """Layer 2 sandbox write-validation resources — SANDBOX_VN only."""

    inventory: InventoryResource
    products: ProductWriteResource
    fulfillment: FulfillmentWriteResource


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

    def create_resources(self, config: ClientFactoryConfig) -> ProductionReadResources:
        client = self.create(config)
        return ProductionReadResources(
            authorization=AuthorizationResource(client),
            orders=OrdersResource(client),
            products=ProductsResource(client),
            returns=ReturnsResource(client),
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

    def create_resources(self, config: ClientFactoryConfig) -> SandboxWriteResources:
        client = self.create(config)
        return SandboxWriteResources(
            inventory=InventoryResource(client),
            products=ProductWriteResource(client),
            fulfillment=FulfillmentWriteResource(client),
        )
