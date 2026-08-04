"""Identity mask transform — alias identities, preserve numeric magnitudes (ADR-038)."""

from __future__ import annotations

import copy
import hashlib
import hmac
from typing import Any

_DEMO_MASK_KEY = b"juli-demo-analytics-identity-v1"

_FORBIDDEN_PII_KEYS = frozenset(
    {
        "buyer_name",
        "buyer_email",
        "buyer_phone",
        "buyer_address",
        "recipient_name",
        "recipient_phone",
        "recipient_address",
        "shipping_address",
        "billing_address",
    }
)

_REMOVED_IDENTITY_KEYS = frozenset({"merchant_id", "tiktok_merchant_id"})


def _stable_alias(prefix: str, raw: str) -> str:
    digest = hmac.new(
        _DEMO_MASK_KEY,
        f"{prefix}:{raw}".encode(),
        hashlib.sha256,
    ).hexdigest()[:8]
    return f"demo-{prefix}-{digest}"


def _stable_shop_display_name(raw_name: str) -> str:
    bucket = (
        int(
            hmac.new(_DEMO_MASK_KEY, f"shop:{raw_name}".encode(), hashlib.sha256).hexdigest()[:4],
            16,
        )
        % 900
        + 100
    )
    return f"Demo Shop {bucket}"


def _stable_product_title(product_id: str) -> str:
    bucket = (
        int(
            hmac.new(
                _DEMO_MASK_KEY, f"product-title:{product_id}".encode(), hashlib.sha256
            ).hexdigest()[:4],
            16,
        )
        % 900
        + 100
    )
    return f"Demo Product {bucket}"


def _mask_product(product: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(product.get("id", ""))
    masked: dict[str, Any] = {}
    if raw_id:
        masked["id"] = _stable_alias("product", raw_id)
        masked["title"] = _stable_product_title(raw_id)
    raw_sku = product.get("sku_id")
    if raw_sku is not None:
        masked["sku_id"] = _stable_alias("sku", str(raw_sku))
    return masked


def _mask_order(order: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(order.get("id", ""))
    masked: dict[str, Any] = {}
    if raw_id:
        masked["id"] = _stable_alias("order", raw_id)
    raw_product_ref = order.get("product_id") or order.get("product_title")
    if raw_product_ref is not None:
        ref = str(raw_product_ref)
        if "product_id" in order:
            masked["product_id"] = _stable_alias("product", ref)
        if "product_title" in order:
            masked["product_title"] = _stable_product_title(ref)
    return masked


def _mask_identity(identity: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}

    raw_shop_name = identity.get("shop_display_name")
    if raw_shop_name is not None:
        masked["shop_display_name"] = _stable_shop_display_name(str(raw_shop_name))

    products = identity.get("products")
    if isinstance(products, list):
        masked["products"] = [_mask_product(item) for item in products if isinstance(item, dict)]

    orders = identity.get("orders")
    if isinstance(orders, list):
        masked["orders"] = [_mask_order(item) for item in orders if isinstance(item, dict)]

    return masked


def mask_public_analytics_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copied envelope with identity fields aliased for public Demo.

    Numeric KPI series magnitudes and availability flags are preserved unchanged.
    Raw merchant ids, real product titles, and buyer PII must not appear in output.
    """
    result = copy.deepcopy(envelope)

    identity = result.get("identity")
    if isinstance(identity, dict):
        cleaned_identity = {
            key: value for key, value in identity.items() if key not in _FORBIDDEN_PII_KEYS
        }
        result["identity"] = _mask_identity(cleaned_identity)
        for removed_key in _REMOVED_IDENTITY_KEYS:
            result["identity"].pop(removed_key, None)

    raw_shop_id = result.get("shop_id")
    if raw_shop_id is not None:
        result["shop_id"] = _stable_alias("shop", str(raw_shop_id))

    # meta carries internal implementation detail (medallion partition names,
    # dev notes referencing issue numbers) with no public value — strip it
    # rather than leak it on an unauthenticated endpoint (#633).
    result.pop("meta", None)

    return result
