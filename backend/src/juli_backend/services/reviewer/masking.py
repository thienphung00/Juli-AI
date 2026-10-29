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
   in dict keys), with a stable alias; the real shop id with the alias
   id; brand words of the shop name with ``Thương hiệu``; any 12-20 digit run
   with ``id-<hash>``.

P74-A (D77): the reviewer's labels are its OWN, never "demo" (Shopee's review
reads "demo" as a product that is not live): shop ``Shop TikTok (ẩn danh)``,
titles ``Sản phẩm NNN`` / ``Video NNN`` / ``LIVE NNN`` / ``Nhà sáng tạo NNN`` /
``Tệp NNN``, ids ``an-<kind>-<hash8>`` and ``id-<hash8>``. Same scheme as ADR-038
(HMAC, stable per raw value), separate key and words; the seller / ops analytics
mask (``analytics_kpi_masking``) keeps "Demo …" / ``demo-<kind>-…``.
3. **Drop** image / media / link values and every external ``http(s)`` URL
   (``None``); mask buyer PII as the ops console does (``mask_pii``).

P75 (fail closed): the dictionary is the SECOND layer. The first is structural: every
string under a product / SKU / shop / video / LIVE / creator key (``_TITLE_KEYS``,
``_ID_KEYS``, the ``title`` / ``name`` of an entity record, the values of the
``{product_id: title}`` / ``{product_id: seller_sku}`` maps ``_TITLE_MAPS`` /
``_ID_MAPS``) is replaced by its key whether or not the catalog knows it. A product's
title alias is keyed on the product's IDENTITY (its TikTok product id; else its SKU;
else the raw title -- each resolved through ``MaskDictionary.product_refs``), so the
same product reads the same ``Sản phẩm NNN`` on every page.

Numbers (int / float / bool) are never touched.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from juli_backend.services.ops import mask_pii

BRAND_REPLACEMENT = "Thương hiệu"
_OWN_HOST_SUFFIX = "app-juli.com"
#: A titled string shorter than this is replaced only as a whole value, never
#: inside other text (a 3-letter title would eat ordinary words).
_MIN_SUBSTRING = 4
#: A title cut short with "…" (a card heading keeps a title's first 59 characters):
#: the run of text before the ellipsis, back to a separator.
_TRUNCATED = re.compile(r"([^·:\n“”\"()]{12,})…")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{12,20}(?!\d)")
_URL = re.compile(r"^\s*https?://", re.IGNORECASE)
#: What a reviewer sees for a masked shop's name (P74-A, D77). Not the seller / ops analytics
#: alias ``stable_shop_display_name`` ("Demo Shop NNN"): Shopee's review reads "demo" as a
#: product that is not live. One fixed label -- stable, and nothing of the real name in it.
REVIEWER_SHOP_LABEL = "Shop TikTok (ẩn danh)"
#: The reviewer mask's own HMAC key (stable aliases; not the analytics mask's key).
_REVIEWER_MASK_KEY = b"juli-reviewer-identity-v1"
#: Title word per entity kind (P74-A): a neutral label + a stable 3-digit bucket.
_TITLE_LABELS: Mapping[str, str] = {
    "product": "Sản phẩm",
    "video": "Video",
    "live": "LIVE",
    "creator": "Nhà sáng tạo",
}
_FILE_LABEL = "Tệp"

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
    # P75: every other key a reviewer-reachable response names a product / shop with.
    "product_label": "product",
    "item_name": "product",
    "sku_name": "product",
    "shop_title": "shop",
    "live_name": "live",
    "video_name": "video",
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
    # P75: seller SKU codes are short codes (``AB270-T``), never caught by the digit rule.
    "sku": "sku",
    "skus": "sku",
    "sku_ids": "sku",
    "tiktok_sku_ids": "sku",
    "sku_code": "sku",
    "sku_codes": "sku",
    "seller_sku_code": "sku",
    "seller_sku_codes": "sku",
    "sku_ref": "sku",
    "basket_skus": "sku",
}
#: P75: ``{product id: title}`` maps (the shop diagnosis report's ``titles``) and
#: ``{product id: seller SKU}`` maps (its ``seller_skus``): their VALUES are identities.
_TITLE_MAPS: Mapping[str, str] = {
    "titles": "product",
    "product_titles": "product",
    "product_names": "product",
}
_ID_MAPS: Mapping[str, str] = {"seller_skus": "sku", "skus_by_product": "sku"}
#: Where a record names its product, best first (P75: one alias per product).
_PRODUCT_ID_KEYS = ("tiktok_product_id", "product_id")
_SKU_REF_KEYS = ("tiktok_sku_id", "sku_id", "seller_sku", "sku")
#: Where a record names its video / LIVE / creator (their title alias is keyed on it).
_OWN_ID_KEYS: Mapping[str, tuple[str, ...]] = {
    "video": ("tiktok_video_id", "video_id"),
    "live": ("tiktok_livestream_id", "live_id", "room_id"),
    "creator": ("tiktok_creator_id", "creator_id"),
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
    "tiktok_sku_id": "product",
    "sku": "product",
}
#: P75: a ranking table (``{"stream": …, "down": [rows], "up": [rows]}``) names its rows
#: ``{"id", "name"}`` only: the stream says what a row is.
_STREAM_ROW_KIND: Mapping[str, str] = {
    "product_card": "product",
    "shop_tab": "product",
    "seller_video": "video",
    "affiliate_video": "video",
    "seller_live": "live",
    "affiliate_live": "live",
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


#: An alias the mask itself produced (a second pass, or an already-masked shop list).
_ALIAS = re.compile(
    r"^(an-[a-z]+-[0-9a-f]{8}|id-[0-9a-f]{8}|(Sản phẩm|Video|LIVE|Nhà sáng tạo|Tệp) \d{3})$"
)


def _is_alias(value: str) -> bool:
    return _ALIAS.match(value) is not None


def _scalar(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text or None


def _entity_kind(record: Mapping[str, Any]) -> str | None:
    """The entity a record describes (its ``title`` / ``name`` is that entity's title)."""
    for marker, kind in _ENTITY_MARKERS.items():
        text = _scalar(record.get(marker))
        if text is not None and not _is_uuid(text):
            return kind
    return None


def _digest(scope: str, raw: str) -> str:
    return hmac.new(_REVIEWER_MASK_KEY, f"{scope}:{raw}".encode(), hashlib.sha256).hexdigest()


def id_alias(kind: str, raw: str) -> str:
    """``an-<kind>-<hash8>`` (``id-<hash8>`` for a bare digit run): stable, never "demo"."""
    digest = _digest(f"id:{kind}", raw)[:8]
    return f"id-{digest}" if kind == "id" else f"an-{kind}-{digest}"


def title_alias(kind: str, raw: str) -> str:
    """``Shop TikTok (ẩn danh)`` for a shop, else ``<label> NNN`` (stable per raw title)."""
    if kind == "shop":
        return REVIEWER_SHOP_LABEL
    label = _TITLE_LABELS.get(kind, _FILE_LABEL)
    bucket = int(_digest(f"title:{kind}", raw)[:4], 16) % 900 + 100
    return f"{label} {bucket}"


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
    #: P75: any reference to a product (its Juli UUID, a TikTok SKU id, a seller SKU,
    #: a raw title) -> its TikTok product id, so every page aliases it the same way.
    product_refs: dict[str, str] = field(default_factory=dict)


class ReviewerMasker:
    """Masks one response payload (build a new one per response)."""

    def __init__(self, dictionary: MaskDictionary) -> None:
        self._dictionary = dictionary
        self._refs = dictionary.product_refs
        self._replacements: dict[str, str] = {}
        #: P75c: raw title -> the identity its free-text alias is keyed on; titles that
        #: several identities share fall back to the raw-text alias.
        self._title_identity: dict[str, str] = {}
        self._shared: set[str] = set()
        #: Every raw title (for a title cut short with "…").
        self._title_texts: set[str] = set()
        #: What a ``{"id", "name"}`` row is inside the ranking table being walked.
        self._row_kind: str | None = None
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
            identity = self._refs.get(raw.strip()) if kind == "product" else None
            self._add_title(kind, raw, identity)
        for raw, kind in dictionary.ids.items():
            self._add_id(kind, raw)
        terms = brand_terms(dictionary.shop_name, dictionary.extra_terms)
        self._brand = (
            re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE) if terms else None
        )

    # -- collect -------------------------------------------------------------------

    def _add_title(self, kind: str, raw: str, identity: str | None = None) -> None:
        text = raw.strip()
        if kind == "shop" and text == REVIEWER_SHOP_LABEL:
            # Already masked (P74-A: the shop list masks each masked pin itself).
            return
        if not text or _is_alias(text):
            return
        self._title_texts.add(text)
        if identity is not None:
            held = self._title_identity.get(text)
            if held is None and text not in self._shared:
                # P75: an identity-keyed alias wins over a raw-text one (free text then
                # reads the same alias as the product's own fields).
                self._replacements[text] = title_alias(kind, identity)
                self._title_identity[text] = identity
            elif held is not None and held != identity:
                # P75c: two products share this title; free text names neither of them.
                self._replacements[text] = title_alias(kind, text)
                self._shared.add(text)
                del self._title_identity[text]
        elif text not in self._replacements:
            self._replacements[text] = title_alias(kind, self._refs.get(text, text))

    # -- identity (P75) --------------------------------------------------------------

    def _entity(self, record: Mapping[str, Any]) -> str | None:
        kind = _entity_kind(record)
        if kind is None and self._row_kind is not None and "name" in record:
            text = _scalar(record.get("id"))
            if text is not None and not _is_uuid(text):
                return self._row_kind
        return kind

    def _enter(self, record: Mapping[str, Any]) -> str | None:
        """Note a ranking table's row kind; returns the kind to restore after it."""
        previous = self._row_kind
        stream = record.get("stream")
        if isinstance(stream, str) and stream in _STREAM_ROW_KIND:
            self._row_kind = _STREAM_ROW_KIND[stream]
        return previous

    def _product_identity(self, record: Mapping[str, Any]) -> str | None:
        """The record's product: TikTok product id, else via its SKU, else None."""
        for key in _PRODUCT_ID_KEYS:
            text = _scalar(record.get(key))
            if text is None:
                continue
            if _is_uuid(text):
                mapped = self._refs.get(text)
                if mapped:
                    return mapped
                continue
            return text
        if self._row_kind == "product":
            text = _scalar(record.get("id"))
            if text is not None and not _is_uuid(text):
                return text
        for key in _SKU_REF_KEYS:
            text = _scalar(record.get(key))
            if text is not None and not _is_uuid(text):
                return self._refs.get(text) or f"sku:{text}"
        return None

    def _identity(self, kind: str, record: Mapping[str, Any]) -> str | None:
        if kind == "product":
            return self._product_identity(record)
        keys = _OWN_ID_KEYS.get(kind, ())
        for key in (*keys, "id") if self._row_kind == kind else keys:
            text = _scalar(record.get(key))
            if text is not None and not _is_uuid(text):
                return text
        return None

    def _title_value(self, kind: str, record: Mapping[str, Any], raw: str) -> str:
        """The alias of a title field, by key (fail closed: never the raw value)."""
        text = raw.strip()
        if not text or _is_alias(text) or (kind == "shop" and text == REVIEWER_SHOP_LABEL):
            return raw
        identity = self._identity(kind, record)
        if identity is None:
            known = self._replacements.get(text)
            if known is not None:
                return known
            identity = self._refs.get(text, text) if kind == "product" else text
        return title_alias(kind, identity)

    def _id_value(self, kind: str, raw: str, pattern: re.Pattern[str] | None) -> str:
        text = raw.strip()
        if not text or _is_uuid(text) or _is_alias(text):
            return self._text(raw, pattern)
        return self._replacements.get(text) or id_alias(kind, text)

    def _add_id(self, kind: str, raw: Any) -> None:
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            return
        text = str(raw).strip()
        if not text or _is_uuid(text) or text in self._replacements:
            return
        self._replacements[text] = id_alias(kind, text)

    def _collect(self, value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                self._collect(item)
            return
        if not isinstance(value, dict):
            return
        previous = self._enter(value)
        try:
            self._collect_record(value)
        finally:
            self._row_kind = previous

    def _collect_record(self, value: dict[Any, Any]) -> None:
        entity_kind = self._entity(value)
        if entity_kind is not None and entity_kind == self._row_kind:
            self._add_id(entity_kind, value.get("id"))
        for key, item in value.items():
            name = str(key)
            if name in _TITLE_MAPS and isinstance(item, dict):
                self._collect_map(item, _TITLE_MAPS[name], title=True)
                continue
            if name in _ID_MAPS and isinstance(item, dict):
                self._collect_map(item, _ID_MAPS[name], title=False)
                continue
            if name in _TITLE_KEYS and isinstance(item, str):
                kind = _TITLE_KEYS[name]
                self._add_title(kind, item, self._identity(kind, value))
            elif name in _ID_KEYS:
                if isinstance(item, list):
                    for one in item:
                        self._add_id(_ID_KEYS[name], one)
                else:
                    self._add_id(_ID_KEYS[name], item)
            elif entity_kind and name in _ENTITY_TITLE_KEYS and isinstance(item, str):
                self._add_title(entity_kind, item, self._identity(entity_kind, value))
            if name == "product_id" and isinstance(item, (str, int)):
                self._add_id("product", item)
            self._collect(item)

    def _collect_map(self, mapping: Mapping[Any, Any], kind: str, *, title: bool) -> None:
        """``{product id: title}`` / ``{product id: seller SKU}`` (P75)."""
        for key, item in mapping.items():
            product = str(key).strip()
            self._add_id("product", product)
            if not isinstance(item, str):
                continue
            if title:
                identity = self._refs.get(product, product) if _is_uuid(product) else product
                self._add_title(kind, item, identity or None)
            else:
                self._add_id(kind, item)

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
        out = _TRUNCATED.sub(self._truncated, value) if "…" in value else value
        if pattern is not None:
            out = pattern.sub(lambda m: self._replacements[m.group(0)], out)
        if self._brand is not None:
            out = self._brand.sub(BRAND_REPLACEMENT, out)
        out = _LONG_DIGITS.sub(lambda m: id_alias("id", m.group(0)), out)
        return out

    def _truncated(self, match: re.Match[str]) -> str:
        """P75: a known title cut short with "…" is still that title."""
        segment = match.group(1)
        head = segment.strip()
        for raw in self._title_texts:
            if len(raw) > len(head) and raw.startswith(head):
                return segment.replace(head, self._replacements[raw]) + "…"
        return match.group(0)

    def _external_url(self, value: str) -> bool:
        if not _URL.match(value):
            return False
        host = (urlsplit(value.strip()).hostname or "").lower()
        return not (host == _OWN_HOST_SUFFIX or host.endswith("." + _OWN_HOST_SUFFIX))

    def _transform(self, value: Any, pattern: re.Pattern[str] | None, key: str | None) -> Any:
        if key is not None and _MEDIA_KEY.match(key) and isinstance(value, (str, list, dict)):
            return [] if isinstance(value, list) else None
        if isinstance(value, dict):
            previous = self._enter(value)
            try:
                entity = self._entity(value)
                return {
                    (self._text(k, pattern) if isinstance(k, str) else k): self._field(
                        value, str(k), v, pattern, entity
                    )
                    for k, v in value.items()
                }
            finally:
                self._row_kind = previous
        if isinstance(value, list):
            return [self._transform(item, pattern, None) for item in value]
        if isinstance(value, str):
            if self._external_url(value):
                return None
            return self._text(value, pattern)
        return value

    def _field(
        self,
        record: Mapping[str, Any],
        name: str,
        value: Any,
        pattern: re.Pattern[str] | None,
        entity: str | None,
    ) -> Any:
        """One field of a record: identity keys are aliased by KEY (P75, fail closed)."""
        if isinstance(value, str):
            kind = _TITLE_KEYS.get(name) or (entity if name in _ENTITY_TITLE_KEYS else None)
            if kind is not None:
                return self._title_value(kind, record, value)
            if name in _ID_KEYS:
                return self._id_value(_ID_KEYS[name], value, pattern)
        elif isinstance(value, list) and name in _ID_KEYS:
            return [
                self._id_value(_ID_KEYS[name], item, pattern)
                if isinstance(item, str)
                else self._transform(item, pattern, None)
                for item in value
            ]
        elif isinstance(value, dict) and (name in _TITLE_MAPS or name in _ID_MAPS):
            return self._map(value, name, pattern)
        return self._transform(value, pattern, name)

    def _map(
        self, mapping: Mapping[Any, Any], name: str, pattern: re.Pattern[str] | None
    ) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for key, item in mapping.items():
            product = str(key).strip()
            masked_key = self._id_value("product", product, pattern)
            if not isinstance(item, str):
                out[masked_key] = self._transform(item, pattern, None)
            elif name in _TITLE_MAPS:
                out[masked_key] = self._title_value(
                    _TITLE_MAPS[name], {"product_id": product}, item
                )
            else:
                out[masked_key] = self._id_value(_ID_MAPS[name], item, pattern)
        return out

    def mask(self, payload: Any) -> Any:
        """The masked copy of ``payload`` (the input is not modified)."""
        self._collect(payload)
        pattern = self._compile()
        return self._transform(mask_pii(payload), pattern, None)


def mask_payload(payload: Any, dictionary: MaskDictionary) -> Any:
    return ReviewerMasker(dictionary).mask(payload)


__all__ = [
    "BRAND_REPLACEMENT",
    "REVIEWER_SHOP_LABEL",
    "MaskDictionary",
    "ReviewerMasker",
    "brand_terms",
    "id_alias",
    "mask_payload",
    "title_alias",
]
