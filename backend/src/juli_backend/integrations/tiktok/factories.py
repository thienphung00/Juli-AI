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
    ProductionWriteGuard,
    ReadOnlyTransportGuard,
    SandboxOnlyWriteGuard,
)
from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
from juli_backend.integrations.tiktok.resources.authorization import AuthorizationResource
from juli_backend.integrations.tiktok.resources.fulfillment import FulfillmentResource
from juli_backend.integrations.tiktok.resources.inventory import InventoryResource
from juli_backend.integrations.tiktok.resources.order_costs import OrderCostsResource
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
    #: Per-order price detail + finance transactions (P14-C). Defaulted so the
    #: many hand-built test bundles stay valid; the factory always sets it.
    order_costs: OrderCostsResource | None = None


@dataclass(frozen=True)
class SandboxWriteResources:
    """Layer 2 sandbox write resources reachable only via SandboxWriteClientFactory."""

    inventory: InventoryResource
    products: ProductsResource
    fulfillment: FulfillmentResource
    promotion: PromotionResource


@dataclass(frozen=True)
class ProductionWriteResources:
    """A seller's own-shop write resources (fast track P61-B, D71.2).

    Only ``products``: the listing edit, the cover upload and the reads around
    them (``ProductionWriteGuard``'s allowlist). Reachable only through
    ``ProductionWriteClientFactory``, which ``services/execution`` builds only
    after every ADR-085 gate has passed for this shop and this mutation.
    """

    products: ProductsResource


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
        # FAIL CLOSED, and never `if SANDBOX_AUTH_ID and ...`. That
        # short-circuit was the shape this guard first shipped in (#1995
        # review), and it inverts the refusal: with
        # `TIKTOK_SANDBOX_MERCHANT_ID` set to an empty string the constant is
        # `""`, the `and` is False, and the sandbox write-validation merchant
        # is silently ADMITTED to the read factory -- the one thing this guard
        # and `READ_CAPABILITIES` exist to prevent. The pre-#1995 check
        # (`!= PRODUCTION_AUTH_ID`) failed closed under the same
        # misconfiguration, so the short-circuit was a regression, not a
        # pre-existing hole.
        #
        # An unusable sandbox constant is a DEPLOYMENT FAULT, not permission to
        # skip the check: a factory that cannot say which merchant is the
        # sandbox one cannot honour the exclusion, so it refuses to build a
        # signed client at all. `merchant.py` supplies a hardcoded fallback
        # today, which is why the value is non-empty in practice -- that is
        # luck, and an explicitly-empty env var defeats it.
        if not SANDBOX_AUTH_ID:
            raise ValueError(
                "ProductionReadClientFactory cannot enforce the SANDBOX_VN exclusion: "
                "SANDBOX_AUTH_ID is empty (TIKTOK_SANDBOX_MERCHANT_ID is set to an empty "
                "value). Refusing to build a read client rather than admitting a merchant "
                "this guard can no longer exclude."
            )
        if config.merchant_auth_id == SANDBOX_AUTH_ID:
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
            order_costs=OrderCostsResource(client),
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


class ProductionWriteClientFactory:
    """Build a seller's own-shop write client (fast track P61-B, D71.2).

    Mirrors ``SandboxWriteClientFactory`` with the opposite merchant rule: the
    sandbox write-validation merchant is refused (its writes are not the
    seller's shop), as is an empty merchant id, and -- fail closed like
    ``ProductionReadClientFactory`` -- an empty ``SANDBOX_AUTH_ID`` that would
    make that exclusion impossible to honour. Which credential reaches this
    factory is decided one layer up (``resolve_write_credential_for_shop``:
    only a row the shop itself owns), and whether a client may be built at all
    (``services/execution/production_write.py``: the ADR-085 gates). Every
    client carries ``ProductionWriteGuard``, which rejects anything outside the
    listing edit allowlist before signing.
    """

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        if not config.merchant_auth_id:
            raise ValueError(
                "ProductionWriteClientFactory requires a merchant auth ID; got an empty value"
            )
        if not SANDBOX_AUTH_ID:
            raise ValueError(
                "ProductionWriteClientFactory cannot enforce the SANDBOX_VN exclusion: "
                "SANDBOX_AUTH_ID is empty (TIKTOK_SANDBOX_MERCHANT_ID is set to an empty "
                "value). Refusing to build a production write client."
            )
        if config.merchant_auth_id == SANDBOX_AUTH_ID:
            raise ValueError(
                "ProductionWriteClientFactory refuses the SANDBOX_VN write-validation "
                f"merchant auth ID ({SANDBOX_AUTH_ID}); it is not a seller's own shop"
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
            guard=ProductionWriteGuard(),
            capability=MerchantCapability.PRODUCTION_WRITE,
            merchant_auth_id=config.merchant_auth_id,
        )

    def create_resources(self, config: ClientFactoryConfig) -> ProductionWriteResources:
        return ProductionWriteResources(products=ProductsResource(self.create(config)))
