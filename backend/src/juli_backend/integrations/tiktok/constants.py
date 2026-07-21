"""TikTok Shop Partner API version pins and path helpers."""

from __future__ import annotations

ORDER_API_VERSION = "202309"
ORDER_DETAIL_API_VERSION = "202507"
PRODUCT_API_VERSION = "202309"
PRODUCT_LISTING_API_VERSION = "202312"
PRODUCT_SEO_API_VERSION = "202405"
PRODUCT_INVENTORY_API_VERSION = "202309"
FULFILLMENT_API_VERSION = "202309"
SUPPLY_CHAIN_API_VERSION = "202309"
RETURN_REFUND_SEARCH_API_VERSION = "202602"
AUTHORIZATION_API_VERSION = "202309"
AFFILIATE_SELLER_API_VERSION = "202406"
AFFILIATE_CONTENT_API_VERSION = "202412"
FINANCE_API_VERSION = "202309"
PROMOTION_API_VERSION = "202309"
ANALYTICS_API_VERSION = "202509"
ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION = "202510"
ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION = "202605"
ANALYTICS_BESTSELLING_API_VERSION = "202511"

ORDER_SEARCH_PATH = f"/order/{ORDER_API_VERSION}/orders/search"
ORDER_DETAIL_PATH = f"/order/{ORDER_DETAIL_API_VERSION}/orders"

PRODUCT_SEARCH_PATH = f"/product/{PRODUCT_API_VERSION}/products/search"
PRODUCT_CREATE_PATH = f"/product/{PRODUCT_API_VERSION}/products"
PRODUCT_CATEGORIES_PATH = f"/product/{PRODUCT_API_VERSION}/categories"
PRODUCT_PREREQUISITES_PATH = f"/product/{PRODUCT_LISTING_API_VERSION}/prerequisites"
PRODUCT_BRANDS_PATH = f"/product/{PRODUCT_API_VERSION}/brands"
PRODUCT_SEO_WORDS_PATH = f"/product/{PRODUCT_SEO_API_VERSION}/products/seo_words"
PRODUCT_SUGGESTIONS_PATH = f"/product/{PRODUCT_SEO_API_VERSION}/products/suggestions"
PRODUCT_IMAGE_UPLOAD_PATH = f"/product/{PRODUCT_API_VERSION}/images/upload"
PRODUCT_FILE_UPLOAD_PATH = f"/product/{PRODUCT_API_VERSION}/files/upload"
INVENTORY_SEARCH_PATH = f"/product/{PRODUCT_INVENTORY_API_VERSION}/inventory/search"

RETURN_SEARCH_PATH = (
    f"/return_refund/{RETURN_REFUND_SEARCH_API_VERSION}/returns/search"
)
CANCELLATION_SEARCH_PATH = (
    f"/return_refund/{RETURN_REFUND_SEARCH_API_VERSION}/cancellations/search"
)

AUTHORIZED_SHOPS_PATH = f"/authorization/{AUTHORIZATION_API_VERSION}/shops"

MARKETPLACE_CREATORS_SEARCH_PATH = (
    f"/affiliate_seller/{AFFILIATE_SELLER_API_VERSION}/marketplace_creators/search"
)
CREATOR_CONTENT_DETAILS_PATH = (
    f"/affiliate_seller/{AFFILIATE_CONTENT_API_VERSION}/open_collaborations/creator_content_details"
)
FINANCE_STATEMENTS_PATH = f"/finance/{FINANCE_API_VERSION}/statements"

PROMOTION_CREATE_PATH = f"/promotion/{PROMOTION_API_VERSION}/activities"

# Analytics GET paths — contract-collection.md §A-31–A-39 (wire set for #424).
ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH = (
    f"/analytics/{ANALYTICS_API_VERSION}/shop_skus/performance"
)
ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH = (
    f"/analytics/{ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION}/shop_products/performance"
)
ANALYTICS_SHOP_PERFORMANCE_PATH = f"/analytics/{ANALYTICS_API_VERSION}/shop/performance"
ANALYTICS_BESTSELLING_PRODUCTS_PATH = (
    f"/analytics/{ANALYTICS_BESTSELLING_API_VERSION}/products/bestselling"
)
ANALYTICS_BESTSELLING_VIDEOS_PATH = (
    f"/analytics/{ANALYTICS_BESTSELLING_API_VERSION}/videos/bestselling"
)

# LIVE / doc-sample analytics paths — reference-tier only (do not allowlist for poll).
ANALYTICS_LIVE_PERFORMANCE_LIST_PATH = (
    f"/analytics/{ANALYTICS_API_VERSION}/shop_lives/performance"
)
ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH = (
    f"/analytics/{ANALYTICS_API_VERSION}/shop_lives/overview_performance"
)


def promotion_activity_path(activity_id: str) -> str:
    return f"/promotion/{PROMOTION_API_VERSION}/activities/{activity_id}"


def analytics_shop_sku_performance_path(sku_id: str) -> str:
    """A-31 Get Shop SKU Performance Detail."""
    return f"/analytics/{ANALYTICS_API_VERSION}/shop_skus/{sku_id}/performance"


def analytics_shop_product_performance_path(product_id: str) -> str:
    """A-33 Get Shop Product Performance Detail."""
    return f"/analytics/{ANALYTICS_API_VERSION}/shop_products/{product_id}/performance"


def analytics_shop_performance_per_hour_path(date: str) -> str:
    """A-37 Get Shop Performance Per Hour (`date` = YYYY-MM-DD)."""
    return (
        f"/analytics/{ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION}/shop/performance/"
        f"{date}/performance_per_hour"
    )


def promotion_activity_products_path(activity_id: str) -> str:
    return f"/promotion/{PROMOTION_API_VERSION}/activities/{activity_id}/products"


def promotion_deactivate_path(activity_id: str) -> str:
    return f"/promotion/{PROMOTION_API_VERSION}/activities/{activity_id}/deactivate"


def product_detail_path(product_id: str) -> str:
    return f"/product/{PRODUCT_API_VERSION}/products/{product_id}"


def product_inventory_update_path(product_id: str) -> str:
    return (
        f"/product/{PRODUCT_INVENTORY_API_VERSION}/products/"
        f"{product_id}/inventory/update"
    )


def product_edit_path(product_id: str) -> str:
    return f"/product/{PRODUCT_API_VERSION}/products/{product_id}"


def category_attributes_path(category_id: str) -> str:
    return f"/product/{PRODUCT_API_VERSION}/categories/{category_id}/attributes"


def product_prices_update_path(product_id: str) -> str:
    return f"/product/{PRODUCT_API_VERSION}/products/{product_id}/prices/update"


def fulfillment_combine_packages_path() -> str:
    return f"/fulfillment/{FULFILLMENT_API_VERSION}/packages/combine"


def fulfillment_ship_package_path(package_id: str) -> str:
    return f"/fulfillment/{FULFILLMENT_API_VERSION}/packages/{package_id}/ship"


def fulfillment_batch_ship_path() -> str:
    return f"/fulfillment/{FULFILLMENT_API_VERSION}/packages/ship"


def fulfillment_split_order_path(order_id: str) -> str:
    return f"/fulfillment/{FULFILLMENT_API_VERSION}/orders/{order_id}/split"


def fulfillment_uncombine_package_path(package_id: str) -> str:
    return f"/fulfillment/{FULFILLMENT_API_VERSION}/packages/{package_id}/uncombine"


def supply_chain_confirm_shipment_path() -> str:
    return f"/supply_chain/{SUPPLY_CHAIN_API_VERSION}/packages/sync"


def marketplace_creator_path(creator_user_id: str) -> str:
    return (
        f"/affiliate_seller/{AFFILIATE_SELLER_API_VERSION}/marketplace_creators/"
        f"{creator_user_id}"
    )
