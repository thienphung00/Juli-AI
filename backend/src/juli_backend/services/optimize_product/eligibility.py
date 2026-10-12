"""Which products may become optimize candidates at all: gift items never do. Pure.

A gift item (a free gift attached to orders, not sold on its own) carries no
real funnel of its own: its units ride on other products' orders, so it looks
like a top-revenue listing with a "weak" card or page. Optimizing it is noise,
and TikTok refuses to edit it anyway (Edit / Partial Edit Product 202509:
"The gift product are not allowed to be edited").

The rule, in order (the first that fires is the reason):

1. **Documented flag** — ``is_not_for_sale`` on Get Product 202309 / Search
   Products 202502: *"whether the product is not for sale and only available
   through Gift with Purchase (GWP) promotions"* (Partner Center, Create
   Product 202309). Used whenever the caller has the raw TikTok payload; Juli
   does not persist it, so most stored-catalog callers fall back to 2-3.
2. **Title marker** (heuristic) — the title contains "[Quà Tặng]", "Quà tặng",
   "Hàng tặng", "[Gift]", "Không bán" or "Không tham gia" (the existing
   ``StageDiagnosisConfig.exclude_title_patterns``), compared case- and
   diacritic-insensitively and NFC/NFD-agnostic.
3. **Token price** (heuristic) — every known (positive) SKU price is at most
   :data:`GIFT_MAX_PRICE_VND` (1,000 ₫), so the listing exists only to be given.

A product that appears only as the gift of a gift-with-purchase promotion
would be a fourth signal, but Juli's promotion tables do not tell the gift SKU
from the eligible ones, so it is not used (no guessed exclusion).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

#: The reason code a gift product carries everywhere (exclusion, retirement).
GIFT_PRODUCT = "gift_product"

#: Every known SKU price at or below this is a token price (VND).
GIFT_MAX_PRICE_VND = Decimal("1000")

#: Title markers, already folded (lower case, no diacritics, single spaces).
GIFT_TITLE_MARKERS: tuple[str, ...] = (
    "qua tang",
    "hang tang",
    "[gift]",
    "gift item",
    "khong ban",
    "khong tham gia",
)

_SPACES = re.compile(r"\s+")


def fold(text: str | None) -> str:
    """Lower case, no Vietnamese diacritics (đ → d), single spaces; NFC/NFD alike."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    return _SPACES.sub(" ", stripped).strip().lower()


def title_gift_marker(title: str | None, extra_patterns: Iterable[str] = ()) -> str | None:
    """The folded marker a title carries, else ``None``."""
    folded = fold(title)
    if not folded:
        return None
    for marker in (*GIFT_TITLE_MARKERS, *(fold(p) for p in extra_patterns)):
        if marker and marker in folded:
            return marker
    return None


def _price(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    # 0 / negative is "unknown" (a placeholder), never evidence of a token price.
    return price if price.is_finite() and price > 0 else None


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def gift_reason(
    *,
    title: str | None,
    is_not_for_sale: Any = None,
    sku_prices: Iterable[Any] = (),
    extra_patterns: Iterable[str] = (),
) -> str | None:
    """Why this product is a gift item (a short, log-ready reason), else ``None``."""
    if _truthy_flag(is_not_for_sale):
        return f"{GIFT_PRODUCT}: is_not_for_sale"
    marker = title_gift_marker(title, extra_patterns)
    if marker is not None:
        return f"{GIFT_PRODUCT}: title matches '{marker}'"
    prices = [p for p in (_price(v) for v in sku_prices) if p is not None]
    if prices and max(prices) <= GIFT_MAX_PRICE_VND:
        return f"{GIFT_PRODUCT}: every SKU price <= {GIFT_MAX_PRICE_VND} VND"
    return None


def is_gift_product(
    *,
    title: str | None,
    is_not_for_sale: Any = None,
    sku_prices: Iterable[Any] = (),
    extra_patterns: Iterable[str] = (),
) -> bool:
    return (
        gift_reason(
            title=title,
            is_not_for_sale=is_not_for_sale,
            sku_prices=sku_prices,
            extra_patterns=extra_patterns,
        )
        is not None
    )


def raw_sku_prices(product: Any) -> list[Any]:
    """SKU sale/list prices from a raw TikTok product dict (Get Product / Search Products)."""
    if not isinstance(product, dict):
        return []
    out: list[Any] = []
    for sku in product.get("skus") or []:
        price = sku.get("price") if isinstance(sku, dict) else None
        if not isinstance(price, dict):
            continue
        value = price.get("sale_price") or price.get("tax_exclusive_price")
        if value is not None:
            out.append(value)
    return out


def gift_reason_from_raw(product: Any, extra_patterns: Iterable[str] = ()) -> str | None:
    """:func:`gift_reason` over a raw TikTok product dict."""
    if not isinstance(product, dict):
        return None
    return gift_reason(
        title=str(product.get("title") or ""),
        is_not_for_sale=product.get("is_not_for_sale"),
        sku_prices=raw_sku_prices(product),
        extra_patterns=extra_patterns,
    )


def stored_product_gift_reason(product: Any) -> str | None:
    """:func:`gift_reason` over a ``products`` row (title / name and its one ``price``)."""
    if product is None:
        return None
    title = getattr(product, "title", None) or getattr(product, "name", None)
    price = getattr(product, "price", None)
    return gift_reason(title=title, sku_prices=[price] if price is not None else [])


__all__ = [
    "GIFT_MAX_PRICE_VND",
    "GIFT_PRODUCT",
    "GIFT_TITLE_MARKERS",
    "fold",
    "gift_reason",
    "gift_reason_from_raw",
    "is_gift_product",
    "raw_sku_prices",
    "stored_product_gift_reason",
    "title_gift_marker",
]
