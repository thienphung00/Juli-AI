"""Merchant capability constants and transport allowlists for P2-A1."""

from __future__ import annotations

import re
from enum import Enum

from juli_backend.integrations.tiktok.constants import (
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

PRODUCTION_AUTH_ID = "7658073774813611784"
SANDBOX_AUTH_ID = "7658096633384781588"


class MerchantCapability(str, Enum):
    """TikTok merchant transport capability."""

    PRODUCTION_READ = "production_read"
    SANDBOX_WRITE = "sandbox_write"


# Layer 1 production-read POST search endpoints (verified in contract-collection.md).
PRODUCTION_READ_POST_PATHS: frozenset[str] = frozenset({
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
    CANCELLATION_SEARCH_PATH,
    INVENTORY_SEARCH_PATH,
    MARKETPLACE_CREATORS_SEARCH_PATH,
})

# Layer 1 production-read GET endpoints (exact paths).
PRODUCTION_READ_GET_EXACT: frozenset[str] = frozenset({
    AUTHORIZED_SHOPS_PATH,
    ORDER_DETAIL_PATH,
    CREATOR_CONTENT_DETAILS_PATH,
    FINANCE_STATEMENTS_PATH,
})

# Layer 1 production-read GET path patterns (dynamic segments).
PRODUCTION_READ_GET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/product/\d+/products/\d+$"),
    re.compile(r"^/affiliate_seller/\d+/marketplace_creators/[^/]+$"),
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
