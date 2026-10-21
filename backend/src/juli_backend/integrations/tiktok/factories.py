"""Capability-separated TikTok client factories for P2-A1 merchant isolation."""

from __future__ import annotations

from dataclasses import dataclass

from juli_backend.integrations.tiktok.capabilities import MerchantCapability
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
    #: The ``capability`` column of the credential the token came from (P61-G,
    #: D71.6). The factories decide from it, never from a configured merchant id.
    #: ``SandboxWriteClientFactory`` refuses anything but ``sandbox_write``
    #: (including unset); the production factories refuse ``sandbox_write``.
    credential_capability: str | None = None
    #: Merchant ids carried by ``sandbox_write`` credentials, read from the DB by
    #: the caller (``credential_resolver.sandbox_write_merchant_ids``). A production
    #: factory refuses a credential whose merchant is in this set, so a mislabelled
    #: row (a production-capability row holding the sandbox merchant) is refused.
    sandbox_merchant_auth_ids: frozenset[str] = frozenset()
    #: Merchant ids carried by non-sandbox credentials (same source). The sandbox
    #: factory refuses a merchant in this set: the 2026-08-18 distinctness rule.
    production_merchant_auth_ids: frozenset[str] = frozenset()


_SANDBOX_CAPABILITY = MerchantCapability.SANDBOX_WRITE.value


def _refuse_sandbox_credential(factory: str, config: ClientFactoryConfig) -> None:
    """Shared refusal for every production factory: capability and merchant, from the credential."""
    if not config.merchant_auth_id:
        raise ValueError(f"{factory} requires a merchant auth ID; got an empty value")
    if config.credential_capability == _SANDBOX_CAPABILITY:
        raise ValueError(
            f"{factory} refuses a sandbox_write credential; it is not a seller's own shop"
        )
    if config.merchant_auth_id in config.sandbox_merchant_auth_ids:
        raise ValueError(
            f"{factory} refuses a merchant auth ID that a sandbox_write credential carries; "
            "it is not read-capable"
        )


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

    No merchant id is configured or compared to a constant (P61-G, D71.6). What keeps it
    fail-closed:

    - a ``sandbox_write`` credential is refused by its capability, and any merchant id a
      ``sandbox_write`` row carries is refused (``sandbox_merchant_auth_ids``, read from the
      DB by the caller), so the sandbox write-validation merchant is unreachable from a read;
    - an empty merchant id is refused, so a half-built config cannot get a signed client;
    - every client still carries ``ReadOnlyTransportGuard``, which allowlists by method and
      path and rejects before signing.

    Which credential reaches this factory is decided one layer up
    (``resolve_read_credential_for_shop``: only a row the shop itself owns).
    """

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        _refuse_sandbox_credential("ProductionReadClientFactory", config)
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
    """Build sandbox write-validation clients for the ``sandbox_write`` credential only."""

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        # Capability is the authority (P61-G, D71.6): the credential must be the
        # sandbox_write one, with a merchant id the connect flow stored. Unset
        # capability fails closed. Distinctness from production merchants is
        # enforced when the caller supplies them and, always, by
        # `resolve_sandbox_write_credential` before a credential reaches here.
        if config.credential_capability != _SANDBOX_CAPABILITY:
            raise ValueError(
                "SandboxWriteClientFactory requires a sandbox_write credential; "
                f"got capability {config.credential_capability!r}"
            )
        if not config.merchant_auth_id:
            raise ValueError(
                "SandboxWriteClientFactory requires a merchant auth ID; got an empty value"
            )
        if config.merchant_auth_id in config.production_merchant_auth_ids:
            raise ValueError(
                "SandboxWriteClientFactory refuses a merchant auth ID that a production "
                "credential also carries; a sandbox write must never reach a production merchant"
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

    Mirrors ``SandboxWriteClientFactory`` with the opposite rule: a ``sandbox_write`` credential
    and any merchant a ``sandbox_write`` row carries are refused (its writes are not the
    seller's shop), as is an empty merchant id. Which credential reaches this factory is decided
    one layer up (``resolve_write_credential_for_shop``: only a row the shop itself owns), and
    whether a client may be built at all (``services/execution/production_write.py``: the
    ADR-085 gates). Every client carries ``ProductionWriteGuard``, which rejects anything
    outside the listing edit allowlist before signing.
    """

    def create(self, config: ClientFactoryConfig) -> GuardedTikTokClient:
        _refuse_sandbox_credential("ProductionWriteClientFactory", config)
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
