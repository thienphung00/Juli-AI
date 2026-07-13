"""TikTok Shop Partner API version pins and path helpers."""

from __future__ import annotations

ORDER_API_VERSION = "202309"
ORDER_DETAIL_API_VERSION = "202507"
PRODUCT_API_VERSION = "202309"
PRODUCT_INVENTORY_API_VERSION = "202309"
FULFILLMENT_API_VERSION = "202309"
SUPPLY_CHAIN_API_VERSION = "202309"
RETURN_REFUND_SEARCH_API_VERSION = "202602"
AUTHORIZATION_API_VERSION = "202309"
AFFILIATE_SELLER_API_VERSION = "202406"
AFFILIATE_CONTENT_API_VERSION = "202412"
FINANCE_API_VERSION = "202309"
PROMOTION_API_VERSION = "202309"

ORDER_SEARCH_PATH = f"/order/{ORDER_API_VERSION}/orders/search"
ORDER_DETAIL_PATH = f"/order/{ORDER_DETAIL_API_VERSION}/orders"

PRODUCT_SEARCH_PATH = f"/product/{PRODUCT_API_VERSION}/products/search"
PRODUCT_CREATE_PATH = f"/product/{PRODUCT_API_VERSION}/products"
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


def promotion_activity_path(activity_id: str) -> str:
    return f"/promotion/{PROMOTION_API_VERSION}/activities/{activity_id}"


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
