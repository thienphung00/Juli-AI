"""Merchant capability constants and transport allowlists for P2-A1."""

from __future__ import annotations

import re
from enum import Enum

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    AUTHORIZED_SHOPS_PATH,
    CANCELLATION_SEARCH_PATH,
    CREATOR_CONTENT_DETAILS_PATH,
    FINANCE_STATEMENTS_PATH,
    INVENTORY_SEARCH_PATH,
    MARKETPLACE_CREATORS_SEARCH_PATH,
    ORDER_DETAIL_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)

# Re-exported, not redefined (#1246): these two names used to be independent
# literals in this module, disconnected from merchant.py's env-configured
# values (#1234) -- a new deployment that set the two env vars per #1234's
# onboarding docs got correct classification from merchant.py and then a
# hard ValueError from the factories below, because this module never saw
# the env config. merchant.py is the single source of truth for both names;
# this module has no independent copy to keep in sync. merchant.py has zero
# internal juli_backend imports, so this import carries no circular-import
# risk.
from juli_backend.integrations.tiktok.merchant import (
    PRODUCTION_AUTH_ID as PRODUCTION_AUTH_ID,
)
from juli_backend.integrations.tiktok.merchant import (
    SANDBOX_AUTH_ID as SANDBOX_AUTH_ID,
)


class MerchantCapability(str, Enum):
    """TikTok merchant transport capability."""

    PRODUCTION_READ = "production_read"
    SANDBOX_WRITE = "sandbox_write"


# Layer 1 production-read POST search endpoints (verified in contract-collection.md).
PRODUCTION_READ_POST_PATHS: frozenset[str] = frozenset(
    {
        ORDER_SEARCH_PATH,
        PRODUCT_SEARCH_PATH,
        RETURN_SEARCH_PATH,
        CANCELLATION_SEARCH_PATH,
        INVENTORY_SEARCH_PATH,
        MARKETPLACE_CREATORS_SEARCH_PATH,
    }
)

# Layer 1 production-read GET endpoints (exact paths).
PRODUCTION_READ_GET_EXACT: frozenset[str] = frozenset(
    {
        AUTHORIZED_SHOPS_PATH,
        ORDER_DETAIL_PATH,
        CREATOR_CONTENT_DETAILS_PATH,
        FINANCE_STATEMENTS_PATH,
        # Analytics wire set (#424/#425/#468) — GET only; A-26/A-27 / A-30 / A-35 excluded.
        ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
        ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
        ANALYTICS_SHOP_PERFORMANCE_PATH,
        ANALYTICS_BESTSELLING_PRODUCTS_PATH,
        ANALYTICS_BESTSELLING_VIDEOS_PATH,
        ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,  # A-28 live grain for ETL (#425)
        ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,  # A-29 overview for backfill (#468)
    }
)

# Layer 1 production-read GET path patterns (dynamic segments).
PRODUCTION_READ_GET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/product/\d+/products/\d+$"),
    # A-23/A-24 SEO reads (issue #1189, ADR-068 amendment). Both are pure
    # reads that mutate nothing, both were already trusted for the sandbox
    # merchant, and `docs/integrations/tiktok_api/endpoints.md` lists them as
    # Optimize Product workflow steps. Their absence here meant the playbook
    # offered the model `get_seo_keywords` while this guard rejected the call
    # before signing -- a real agent run died on `TransportGuardError`, found
    # by the #1124 live smoke once #1188 let runs execute at all.
    re.compile(r"^/product/\d+/products/seo_words$"),
    re.compile(r"^/product/\d+/products/suggestions$"),
    re.compile(r"^/affiliate_seller/\d+/marketplace_creators/[^/]+$"),
    # A-31 SKU performance detail
    re.compile(r"^/analytics/\d+/shop_skus/[^/]+/performance$"),
    # A-33 product performance detail
    re.compile(r"^/analytics/\d+/shop_products/[^/]+/performance$"),
    # A-37 shop performance per hour
    re.compile(r"^/analytics/\d+/shop/performance/\d{4}-\d{2}-\d{2}/performance_per_hour$"),
    # A-25 Get Promotion Activity (production-read)
    re.compile(r"^/promotion/\d+/activities/[^/]+$"),
)

# Known write path patterns — used by CI/static checks.
WRITE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/inventory/update$"),
    re.compile(r"/images/upload$"),
    re.compile(r"/packages/combine$"),
    re.compile(r"/packages/\d+/ship$"),
    re.compile(r"/packages/ship$"),
    re.compile(r"/orders/\d+/split$"),
    re.compile(r"/packages/\d+/uncombine$"),
    re.compile(r"/cancellations/\d+/(approve|reject)$"),
    re.compile(r"/returns/\d+/(approve|reject)$"),
    re.compile(r"/deactivate$"),
    re.compile(r"/activate$"),
    re.compile(r"/packages/sync$"),
    re.compile(r"^/product/\d+/products$"),
    re.compile(r"^/promotion/\d+/activities$"),
    re.compile(r"^/promotion/\d+/activities/\d+/products$"),
)

# Layer 2 sandbox write-validation allowlist (method, path regex).
SANDBOX_ALLOWED_REQUESTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("POST", re.compile(r"^/product/\d+/inventory/search$")),
    ("POST", re.compile(r"^/product/\d+/products/\d+/inventory/update$")),
    ("POST", re.compile(r"^/product/\d+/products$")),
    ("PUT", re.compile(r"^/product/\d+/products/\d+$")),
    ("POST", re.compile(r"^/product/\d+/images/upload$")),
    ("POST", re.compile(r"^/product/\d+/files/upload$")),
    ("POST", re.compile(r"^/fulfillment/\d+/packages/combine$")),
    ("POST", re.compile(r"^/fulfillment/\d+/packages/\d+/ship$")),
    ("POST", re.compile(r"^/fulfillment/\d+/packages/ship$")),
    ("POST", re.compile(r"^/fulfillment/\d+/orders/\d+/split$")),
    ("POST", re.compile(r"^/fulfillment/\d+/packages/\d+/uncombine$")),
    ("POST", re.compile(r"^/return_refund/\d+/cancellations/\d+/approve$")),
    ("POST", re.compile(r"^/return_refund/\d+/cancellations/\d+/reject$")),
    ("POST", re.compile(r"^/return_refund/\d+/returns/\d+/approve$")),
    ("POST", re.compile(r"^/return_refund/\d+/returns/\d+/reject$")),
    ("POST", re.compile(r"^/supply_chain/\d+/packages/sync$")),
    ("POST", re.compile(r"^/promotion/\d+/activities$")),
    ("PUT", re.compile(r"^/promotion/\d+/activities/\d+$")),
    ("PUT", re.compile(r"^/promotion/\d+/activities/\d+/products$")),
    ("POST", re.compile(r"^/promotion/\d+/activities/\d+/deactivate$")),
    # Identity read (issue #1200). A sandbox credential must be able to ask the
    # vendor which shop it actually reaches, otherwise capability binding can
    # only be verified for production-read -- and the sandbox side is precisely
    # where a mislabelled token causes an unintended production write. Pure
    # read, mutates nothing, and already allowlisted for production-read.
    ("GET", re.compile(r"^/authorization/\d+/shops$")),
    # Supporting reads used during sandbox write-validation flows.
    ("GET", re.compile(r"^/product/\d+/categories$")),
    ("GET", re.compile(r"^/product/\d+/categories/\d+/attributes$")),
    ("GET", re.compile(r"^/product/\d+/prerequisites$")),
    ("GET", re.compile(r"^/product/\d+/brands$")),
    ("GET", re.compile(r"^/product/\d+/products/\d+$")),
    ("GET", re.compile(r"^/product/\d+/products/seo_words$")),
    ("GET", re.compile(r"^/product/\d+/products/suggestions$")),
    ("POST", re.compile(r"^/product/\d+/products/search$")),
    ("POST", re.compile(r"^/product/\d+/products/\d+/prices/update$")),
    ("GET", re.compile(r"^/fulfillment/\d+/combinable_packages/search$")),
    ("GET", re.compile(r"^/fulfillment/\d+/packages/\d+$")),
    ("GET", re.compile(r"^/fulfillment/\d+/packages/\d+/shipping_documents$")),
    ("GET", re.compile(r"^/promotion/\d+/activities/\d+$")),
)


def normalize_path(path: str) -> str:
    """Normalize API path for allowlist checks."""
    normalized = path.split("?", 1)[0].rstrip("/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def is_production_read_allowed(method: str, path: str) -> bool:
    """Return True when method/path is allowed on production-read transport."""
    normalized = normalize_path(path)
    method_upper = method.upper()

    if method_upper == "GET":
        if normalized in PRODUCTION_READ_GET_EXACT:
            return True
        return any(pattern.match(normalized) for pattern in PRODUCTION_READ_GET_PATTERNS)

    if method_upper == "POST" and normalized in PRODUCTION_READ_POST_PATHS:
        return True

    return False


def is_sandbox_write_allowed(method: str, path: str) -> bool:
    """Return True when method/path is allowed on sandbox write-validation transport."""
    normalized = normalize_path(path)
    method_upper = method.upper()
    return any(
        allowed_method == method_upper and pattern.match(normalized)
        for allowed_method, pattern in SANDBOX_ALLOWED_REQUESTS
    )


def path_contains_write_marker(path: str) -> bool:
    """Return True when path looks like a mutating TikTok Shop endpoint."""
    normalized = normalize_path(path)
    return any(pattern.search(normalized) for pattern in WRITE_PATH_PATTERNS)
