"""Identity mask for every response a partner reviewer receives (P32-A, D42).

D25.6 / ADR-038 §8: **identity masked, magnitudes real**. A reviewer reads the
reference shop through the seller's own read routes; this module rewrites the
JSON those routes return so that no shop name, shop id, product / video / LIVE
title, TikTok id, seller SKU, product photo or external link survives, while
every number is left exactly as it was.

How (contract §3):

1. **Collect** identities from the payload itself -- values under identity
   keys (``shop_name``, ``product_title``, ``seller_sku``, ``tiktok_product_id``
   …) and the ``title`` / ``name`` of entity records (a dict that carries a
   TikTok-side id) -- plus the shop's catalog (:class:`MaskDictionary`, loaded
   by ``catalog.py``).
2. **Replace** each of them, wherever it occurs (whole values, inside free text,
   in dict keys), with a stable ADR-038 alias; the real shop id with the alias
   id; brand words of the shop name with ``Thương hiệu``; any 12-20 digit run
   with ``demo-id-<hash>``.
3. **Drop** image / media / link values and every external ``http(s)`` URL
   (``None``); mask buyer PII as the ops console does (``mask_pii``).

Numbers (int / float / bool) are never touched.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from juli_backend.services.analytics_kpi_masking.mask import (
    stable_alias,
    stable_label,
    stable_product_title,
    stable_shop_display_name,
)
from juli_backend.services.ops import mask_pii

BRAND_REPLACEMENT = "Thương hiệu"
_OWN_HOST_SUFFIX = "app-juli.com"
#: A titled string shorter than this is replaced only as a whole value, never
#: inside other text (a 3-letter title would eat ordinary words).
_MIN_SUBSTRING = 4
_LONG_DIGITS = re.compile(r"(?<!\d)\d{12,20}(?!\d)")
_URL = re.compile(r"^\s*https?://", re.IGNORECASE)

#: Shop-name words that are not the brand (never replaced on their own).
_BRAND_STOP_WORDS = frozenset(
    {
        "store", "shop", "official", "mall", "flagship", "vietnam", "viet", "nam", "vn",
        "the", "and", "chinh", "hang", "chính", "hãng", "cửa", "hàng", "cua", "global",
        "co", "ltd", "company", "jsc",
    }
)  # fmt: skip

#: Keys whose string value is always an identity, with the alias kind.
_TITLE_KEYS: Mapping[str, str] = {
    "shop_name": "shop",
    "shop_display_name": "shop",
    "seller_name": "shop",
    "product_title": "product",
    "product_name": "product",
    "video_title": "video",
    "live_title": "live",
    "creator_name": "creator",
    "creator_nickname": "creator",
    "nickname": "creator",
    "username": "creator",
    "handle": "creator",
    "file_name": "file",
}
_ID_KEYS: Mapping[str, str] = {
    "tiktok_shop_id": "shop",
    "shopee_shop_id": "shop",
    "shop_cipher": "shop",
    "tiktok_product_id": "product",
    "tiktok_sku_id": "sku",
    "sku_id": "sku",
    "seller_sku": "sku",
    "seller_skus": "sku",
    "video_id": "video",
    "tiktok_video_id": "video",
    "live_id": "live",
    "room_id": "live",
    "tiktok_livestream_id": "live",
    "creator_id": "creator",
    "tiktok_creator_id": "creator",
    "order_id": "order",
    "content_ref": "content",
}
#: Keys marking a dict as a record of a shop entity, so its ``title`` / ``name``
#: is that entity's title. ``product_id`` only counts when it is not a Juli UUID.
_ENTITY_MARKERS: Mapping[str, str] = {
    "tiktok_product_id": "product",
    "product_id": "product",
    "seller_sku": "product",
    "sku_id": "product",
    "video_id": "video",
    "tiktok_video_id": "video",
    "live_id": "live",
    "room_id": "live",
    "tiktok_livestream_id": "live",
}
_ENTITY_TITLE_KEYS = ("title", "name", "caption", "product_title")
_MEDIA_KEY = re.compile(
    r"^(.*_)?(image|images|image_url|image_urls|image_uri|img|photo|photos|photo_url|"
    r"thumbnail|thumbnails|thumbnail_url|thumb_url|cover|cover_url|cover_image_url|avatar|"
    r"avatar_url|picture|main_image|main_images|url|urls|link|links|share_url|play_url|"
    r"video_url|preview_url)$",
    re.IGNORECASE,
)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def title_alias(kind: str, raw: str) -> str:
    if kind == "shop":
        return stable_shop_display_name(raw)
    if kind == "product":
        return stable_product_title(raw)
    if kind == "video":
        return stable_label("Video", raw)
    if kind == "live":
        return stable_label("LIVE", raw)
    if kind == "creator":
        return stable_label("Nhà sáng tạo", raw)
    return stable_label("Tệp", raw)


def brand_terms(shop_name: str | None, extra: Iterable[str] = ()) -> tuple[str, ...]:
    """The brand words of a shop name (``Fujiwa Vietnam Store`` → ``Fujiwa``) plus extras."""
    words = re.split(r"[^\w]+", shop_name or "", flags=re.UNICODE)
    terms = {w for w in words if len(w) >= 3 and w.lower() not in _BRAND_STOP_WORDS}
    terms.update(t for t in extra if len(t) >= 3)
    return tuple(sorted(terms, key=len, reverse=True))


@dataclass
class MaskDictionary:
    """What is known about the pinned shop before reading the response."""

    #: None: no pinned shop (D42 amendment) -- nothing shop-specific to swap.
    shop_id: uuid.UUID | None
    alias_id: uuid.UUID | None
    shop_name: str | None = None
    tiktok_shop_id: str | None = None
    #: raw title -> kind (product / video / live)
    titles: dict[str, str] = field(default_factory=dict)
    #: raw id -> kind
    ids: dict[str, str] = field(default_factory=dict)
    extra_terms: tuple[str, ...] = ()


class ReviewerMasker:
    """Masks one response payload (build a new one per response)."""

    def __init__(self, dictionary: MaskDictionary) -> None:
        self._dictionary = dictionary
        self._replacements: dict[str, str] = {}
        if dictionary.shop_id is not None and dictionary.alias_id is not None:
            real = str(dictionary.shop_id)
            alias = str(dictionary.alias_id)
            self._replacements[real] = alias
            self._replacements[real.upper()] = alias
        if dictionary.shop_name:
            self._add_title("shop", dictionary.shop_name)
        if dictionary.tiktok_shop_id:
            self._add_id("shop", dictionary.tiktok_shop_id)
        for raw, kind in dictionary.titles.items():
            self._add_title(kind, raw)
        for raw, kind in dictionary.ids.items():
            self._add_id(kind, raw)
        terms = brand_terms(dictionary.shop_name, dictionary.extra_terms)
        self._brand = (
            re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE) if terms else None
        )

    # -- collect -------------------------------------------------------------------

    def _add_title(self, kind: str, raw: str) -> None:
        text = raw.strip()
        if text and text not in self._replacements:
            self._replacements[text] = title_alias(kind, text)

    def _add_id(self, kind: str, raw: Any) -> None:
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            return
        text = str(raw).strip()
        if not text or _is_uuid(text) or text in self._replacements:
            return
        self._replacements[text] = stable_alias(kind, text)

    def _collect(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self._collect(item)
            return
        if not isinstance(value, dict):
            return
        entity_kind = None
        for marker, kind in _ENTITY_MARKERS.items():
            marked = value.get(marker)
            if isinstance(marked, (str, int)) and not isinstance(marked, bool):
                if not _is_uuid(str(marked)):
                    entity_kind = kind
                    break
        for key, item in value.items():
            name = str(key)
            if name in _TITLE_KEYS and isinstance(item, str):
                self._add_title(_TITLE_KEYS[name], item)
            elif name in _ID_KEYS:
                if isinstance(item, list):
                    for one in item:
                        self._add_id(_ID_KEYS[name], one)
                else:
                    self._add_id(_ID_KEYS[name], item)
            elif entity_kind and name in _ENTITY_TITLE_KEYS and isinstance(item, str):
                self._add_title(entity_kind, item)
            if name == "product_id" and isinstance(item, (str, int)):
                self._add_id("product", item)
            self._collect(item)

    # -- replace -------------------------------------------------------------------

    def _compile(self) -> re.Pattern[str] | None:
        needles = [k for k in self._replacements if len(k) >= _MIN_SUBSTRING]
        if not needles:
            return None
        needles.sort(key=len, reverse=True)
        return re.compile("|".join(re.escape(n) for n in needles))

    def _text(self, value: str, pattern: re.Pattern[str] | None) -> str:
        whole = self._replacements.get(value.strip())
        if whole is not None:
            return whole
        out = value
        if pattern is not None:
            out = pattern.sub(lambda m: self._replacements[m.group(0)], out)
        if self._brand is not None:
            out = self._brand.sub(BRAND_REPLACEMENT, out)
        out = _LONG_DIGITS.sub(lambda m: stable_alias("id", m.group(0)), out)
        return out

    def _external_url(self, value: str) -> bool:
        if not _URL.match(value):
            return False
        host = (urlsplit(value.strip()).hostname or "").lower()
        return not (host == _OWN_HOST_SUFFIX or host.endswith("." + _OWN_HOST_SUFFIX))

    def _transform(self, value: Any, pattern: re.Pattern[str] | None, key: str | None) -> Any:
        if key is not None and _MEDIA_KEY.match(key) and isinstance(value, (str, list, dict)):
            return [] if isinstance(value, list) else None
        if isinstance(value, dict):
            return {
                (self._text(k, pattern) if isinstance(k, str) else k): self._transform(
                    v, pattern, str(k)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self._transform(item, pattern, None) for item in value]
        if isinstance(value, str):
            if self._external_url(value):
                return None
            return self._text(value, pattern)
        return value

    def mask(self, payload: Any) -> Any:
        """The masked copy of ``payload`` (the input is not modified)."""
        self._collect(payload)
        pattern = self._compile()
        return self._transform(mask_pii(payload), pattern, None)


def mask_payload(payload: Any, dictionary: MaskDictionary) -> Any:
    return ReviewerMasker(dictionary).mask(payload)


__all__ = [
    "BRAND_REPLACEMENT",
    "MaskDictionary",
    "ReviewerMasker",
    "brand_terms",
    "mask_payload",
    "title_alias",
]
