"""Capability-separated TikTok client factories for P2-A1 merchant isolation."""

from __future__ import annotations

from dataclasses import dataclass

# Re-exported, not used by this module's own logic since #1995 removed the
# production-merchant identity check from `ProductionReadClientFactory.create`.
# `tests/unit/test_tiktok_capabilities_merchant_source.py` reads
# `factories.PRODUCTION_AUTH_ID` to prove the env-configured value reaches the
# transport layer (#1246), so the name stays bound here on purpose. The
# redundant alias is the explicit re-export form `capabilities.py` already uses.
from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_AUTH_ID as PRODUCTION_AUTH_ID,
)
from juli_backend.integrations.tiktok.capabilities import (
    SANDBOX_AUTH_ID,
    MerchantCapability,
)
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.guarded_client import GuardedTikTokClient
from juli_backend.integrations.tiktok.guards import (
    ReadOnlyTransportGuard,
    SandboxOnlyWriteGuard,
)
from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
from juli_backend.integrations.tiktok.resources.authorization import AuthorizationResource
from juli_backend.integrations.tiktok.resources.fulfillment import FulfillmentResource
from juli_backend.integrations.tiktok.resources.inventory import InventoryResource
from juli_backend.integrations.tiktok.resources.orders import OrdersResource
from juli_backend.integrations.tiktok.resources.products import ProductsResource
from juli_backend.integrations.tiktok.resources.promotion import PromotionResource
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
    inventory: InventoryResource
    analytics: AnalyticsResource
    promotion: PromotionResource


@dataclass(frozen=True)
class SandboxWriteResources:
    """Layer 2 sandbox write resources reachable only via SandboxWriteClientFactory."""

    inventory: InventoryResource
    products: ProductsResource
    fulfillment: FulfillmentResource
    promotion: PromotionResource


class ProductionReadClientFactory:
    """Build read-only clients for **any** shop's own read credential (#1995).

    Until #1995 this factory admitted exactly one merchant id -- the configured
    ``PRODUCTION_AUTH_ID``. That made the read path structurally single-tenant:
    #1365's ``resolve_read_credential_for_shop`` could resolve a connecting
    seller's own ``SELLER_CONNECT`` credential correctly, and this constructor
    then refused it one layer down, so no seller but Juli's own merchant could
    ever be polled.

    What replaces the identity equality, and why it is still fail-closed:

    - the **sandbox-write merchant is refused outright**. That credential is a
      write-validation credential and must be unreachable from every read path
      (``READ_CAPABILITIES`` in ``merchant.py`` says the same thing one layer
      up); this is the transport-level restatement of it.
    - an **empty merchant id is refused**, so a half-built config cannot get a
      signed client.
    - every client this returns still carries ``ReadOnlyTransportGuard``, which
      allowlists by *method and path* and rejects before signing. Widening which
      merchant may hold a read client does not widen what a read client may do.

    What this deliberately gives up (measured, not glossed): the #1246 check
    that a deployment reconfigured onto new merchant ids rejects Juli's *old*
    production id here. Post-#1995 a seller's own merchant id is, by
    construction, "not the configured one", so merchant identity can no longer
    distinguish a stale id from a legitimate seller. The authority for *which*
    credential reaches this factory moves up to
    ``resolve_read_credential_for_shop``, which only ever returns a row the
    shop being read owns.
    """

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        if not config.merchant_auth_id:
            raise ValueError(
                "ProductionReadClientFactory requires a merchant auth ID; got an empty value"
            )
        if SANDBOX_AUTH_ID and config.merchant_auth_id == SANDBOX_AUTH_ID:
            raise ValueError(
                "ProductionReadClientFactory refuses the SANDBOX_VN write-validation "
                f"merchant auth ID ({SANDBOX_AUTH_ID}); it is not read-capable"
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
            inventory=InventoryResource(client),
            analytics=AnalyticsResource(client),
            promotion=PromotionResource(client),
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
            products=ProductsResource(client),
            fulfillment=FulfillmentResource(client),
            promotion=PromotionResource(client),
        )
