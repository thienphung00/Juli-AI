"""The sample shop's products and id ranges -- re-exported from the backend (P100 S2-G).

The constants live in ``juli_backend.services.sample_shop.catalog`` so the API's decision seeding
(``services/sample_shop/seed.py``) needs no import of ``scripts/``. This module keeps the
generator's and the loader's imports unchanged.
"""

from juli_backend.services.sample_shop.catalog import (
    CAMPAIGNS,
    ITEM_ID_BASE,
    KEYWORDS,
    NEW_TITLE,
    PRODUCTS,
    SAMPLE_SHOP_NAME,
    SAMPLE_SHOPEE_SHOP_ID,
    SAMPLE_SHOPEE_SHOP_ID_MAX,
    SAMPLE_SHOPEE_SHOP_ID_MIN,
    TITLE_APPLIED_DAYS_BEFORE_END,
    TITLE_PRODUCT,
    VOUCHER_DAYS,
    VOUCHER_ID,
    VOUCHER_MIN_SPEND,
    VOUCHER_NAME,
    VOUCHER_PRODUCT,
    VOUCHER_QUANTITY,
    VOUCHER_START_DAYS_BEFORE_END,
    VOUCHER_TOP_UP,
    VOUCHER_USAGE,
    VOUCHER_VALUE,
    Product,
    Variation,
    in_reserved_range,
)

__all__ = [
    "CAMPAIGNS",
    "ITEM_ID_BASE",
    "KEYWORDS",
    "NEW_TITLE",
    "PRODUCTS",
    "Product",
    "SAMPLE_SHOPEE_SHOP_ID",
    "SAMPLE_SHOPEE_SHOP_ID_MAX",
    "SAMPLE_SHOPEE_SHOP_ID_MIN",
    "SAMPLE_SHOP_NAME",
    "TITLE_APPLIED_DAYS_BEFORE_END",
    "TITLE_PRODUCT",
    "VOUCHER_DAYS",
    "VOUCHER_ID",
    "VOUCHER_MIN_SPEND",
    "VOUCHER_NAME",
    "VOUCHER_PRODUCT",
    "VOUCHER_QUANTITY",
    "VOUCHER_START_DAYS_BEFORE_END",
    "VOUCHER_TOP_UP",
    "VOUCHER_USAGE",
    "VOUCHER_VALUE",
    "Variation",
    "in_reserved_range",
]
