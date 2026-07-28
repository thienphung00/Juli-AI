"""TikTok Shop Partner API integration — package-root public facade.

Import callers from ``juli_backend.integrations.tiktok`` only. Leaf modules
(``resources/*``, ``guarded_client``, ``guards``, ``capabilities``, etc.) remain
internal until explicitly re-exported here for a migration slice.
"""

from __future__ import annotations

from juli_backend.integrations.tiktok.auth import (
    DEFAULT_OPEN_API_BASE_URL,
    TikTokAuth,
)
from juli_backend.integrations.tiktok.business_account_holder_auth import (
    TikTokBusinessAccountHolderAuth,
)
from juli_backend.integrations.tiktok.business_advertiser_auth import (
    TikTokBusinessAdvertiserAuth,
)
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    INVENTORY_SEARCH_PATH,
    MARKETPLACE_CREATORS_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    ResourceNotFoundError,
    TikTokAPIError,
    TikTokSystemError,
    TransportGuardError,
    error_from_response,
)
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionReadResources,
    SandboxWriteClientFactory,
    SandboxWriteResources,
)
from juli_backend.integrations.tiktok.mapping import (
    analytics_snapshot_key,
    expand_analytics_live_session,
    expand_analytics_product_detail,
    expand_analytics_product_list_item,
    expand_analytics_shop_performance,
    expand_analytics_shop_performance_per_hour,
    expand_analytics_sku_detail,
    expand_analytics_sku_list_item,
    expand_inventory_search,
    expand_order_line_items,
    normalize_creator,
    normalize_inventory,
    normalize_livestream,
    normalize_order,
    normalize_product,
    normalize_return,
    normalize_statement,
)
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
    is_cross_merchant_lookup,
    resolve_merchant_context,
)
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter
from juli_backend.integrations.tiktok.resources import (
    AnalyticsResource,
    AuthorizationResource,
    CreatorsResource,
    FulfillmentResource,
    InventoryResource,
    LivestreamsResource,
    OrdersResource,
    ProductsResource,
    PromotionResource,
    ReturnsResource,
    SettlementsResource,
    strip_nones,
)
from juli_backend.integrations.tiktok.schemas import TikTokSchemaError
from juli_backend.integrations.tiktok.signing import sign_request

__all__ = [
    # Authentication
    "TikTokAuth",
    "TikTokBusinessAdvertiserAuth",
    "TikTokBusinessAccountHolderAuth",
    "DEFAULT_OPEN_API_BASE_URL",
    # HTTP client
    "TikTokClient",
    # Request signing
    "sign_request",
    # Rate limiting
    "RateLimiter",
    # API path constants (polling / analytics backfill)
    "ANALYTICS_BESTSELLING_PRODUCTS_PATH",
    "ANALYTICS_BESTSELLING_VIDEOS_PATH",
    "ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH",
    "ANALYTICS_LIVE_PERFORMANCE_LIST_PATH",
    "ANALYTICS_SHOP_PERFORMANCE_PATH",
    "ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH",
    "ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH",
    "INVENTORY_SEARCH_PATH",
    "MARKETPLACE_CREATORS_SEARCH_PATH",
    "ORDER_SEARCH_PATH",
    "PRODUCT_SEARCH_PATH",
    "RETURN_SEARCH_PATH",
    "analytics_shop_performance_per_hour_path",
    "analytics_shop_product_performance_path",
    "analytics_shop_sku_performance_path",
    "promotion_activity_path",
    # Client factories (production-read / sandbox-write)
    "ClientFactoryConfig",
    "ProductionReadClientFactory",
    "ProductionReadResources",
    "SandboxWriteClientFactory",
    "SandboxWriteResources",
    # Merchant capability isolation
    "PRODUCTION_AUTH_ID",
    "SANDBOX_AUTH_ID",
    "TikTokCapability",
    "is_cross_merchant_lookup",
    "resolve_merchant_context",
    # Vendor → ingest mapping
    "analytics_snapshot_key",
    "expand_analytics_live_session",
    "expand_analytics_product_detail",
    "expand_analytics_product_list_item",
    "expand_analytics_shop_performance",
    "expand_analytics_shop_performance_per_hour",
    "expand_analytics_sku_detail",
    "expand_analytics_sku_list_item",
    "expand_inventory_search",
    "expand_order_line_items",
    "normalize_creator",
    "normalize_inventory",
    "normalize_livestream",
    "normalize_order",
    "normalize_product",
    "normalize_return",
    "normalize_statement",
    # Resources
    "strip_nones",
    "AnalyticsResource",
    "AuthorizationResource",
    "CreatorsResource",
    "FulfillmentResource",
    "InventoryResource",
    "LivestreamsResource",
    "OrdersResource",
    "ProductsResource",
    "PromotionResource",
    "ReturnsResource",
    "SettlementsResource",
    # Exceptions
    "TikTokAPIError",
    "AuthenticationError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "RateLimitError",
    "TikTokSystemError",
    "TransportGuardError",
    "error_from_response",
    # Selective — OAuth verify_connection caller slice
    "TikTokSchemaError",
]
