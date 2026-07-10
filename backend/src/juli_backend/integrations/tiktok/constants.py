"""TikTok Shop Partner API version pins and path helpers."""

from __future__ import annotations

ORDER_API_VERSION = "202309"
ORDER_DETAIL_API_VERSION = "202507"
PRODUCT_API_VERSION = "202309"
PRODUCT_INVENTORY_API_VERSION = "202309"
RETURN_REFUND_SEARCH_API_VERSION = "202602"
AUTHORIZATION_API_VERSION = "202309"
AFFILIATE_SELLER_API_VERSION = "202406"
AFFILIATE_CONTENT_API_VERSION = "202412"
FINANCE_API_VERSION = "202309"

ORDER_SEARCH_PATH = f"/order/{ORDER_API_VERSION}/orders/search"
ORDER_DETAIL_PATH = f"/order/{ORDER_DETAIL_API_VERSION}/orders"

PRODUCT_SEARCH_PATH = f"/product/{PRODUCT_API_VERSION}/products/search"
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


def product_detail_path(product_id: str) -> str:
    return f"/product/{PRODUCT_API_VERSION}/products/{product_id}"


def product_inventory_update_path(product_id: str) -> str:
    return (
        f"/product/{PRODUCT_INVENTORY_API_VERSION}/products/"
        f"{product_id}/inventory/update"
    )


def marketplace_creator_path(creator_user_id: str) -> str:
    return (
        f"/affiliate_seller/{AFFILIATE_SELLER_API_VERSION}/marketplace_creators/"
        f"{creator_user_id}"
    )
