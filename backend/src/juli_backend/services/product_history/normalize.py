"""Pure product normalization, hashing and diffing (D30.1a, D30.4). No I/O.

``normalize_detail`` turns a TikTok Get Product body (202309) into the fields a
``product_snapshots`` row stores; ``list_prices`` reads the SKU prices a Search
Products row already carries (so the daily reconciliation can see a price
change without re-reading the product); ``diff`` says what changed between the
product's latest snapshot and a new read, one :class:`Change` per kind.

Prices: ``list_price`` is TikTok's ``tax_exclusive_price`` (what Juli's
``update_product_price`` writes, see ``agent/runner/write_capture.py``),
``sale_price`` is ``sale_price`` when TikTok sends it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from juli_backend.models.history import (
    DESCRIPTION_MAX_CHARS,
    KIND_CATEGORY,
    KIND_CONTENT,
    KIND_PRICE,
    KIND_STATUS,
)

SHOP_ZONE = timezone(timedelta(hours=7))
#: The content fields, in diff order.
CONTENT_FIELDS: tuple[str, ...] = ("title", "description", "main_images", "attributes")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


#: Epoch magnitudes past which a value is read as ms / µs / ns rather than seconds.
#: 10**11 s is the year 5138; 10**11 ms is 1973 -- no real TikTok time is ambiguous.
_MS_FROM = 10**11
_US_FROM = 10**14
_NS_FROM = 10**17


def epoch_to_naive_utc(value: object) -> datetime | None:
    """A TikTok epoch → naive UTC; ``None`` for anything unusable. Never raises.

    The 202309 OAS documents seconds, but real Search Activities rows carry
    **millisecond** ``create_time`` / ``update_time`` (see also
    ``services/shop_diagnosis/promotions.py``), which made ``fromtimestamp``
    raise "year … is out of range" and abort the whole promotion sweep
    (P58-A, D67). So: int / float / numeric string, in seconds, ms, µs or ns;
    ``0`` / ``None`` / ``""`` / bools / junk (an open-ended ``end_time``) are
    ``None``.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    for limit, scale in ((_NS_FROM, 10**9), (_US_FROM, 10**6), (_MS_FROM, 10**3)):
        if number >= limit:
            number = number / scale
            break
    try:
        return datetime.fromtimestamp(int(number), UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def local_day(moment: datetime) -> date:
    """The shop's (UTC+7) calendar day of a naive-UTC instant."""
    return moment.replace(tzinfo=UTC).astimezone(SHOP_ZONE).date()


def local_midnight_utc(day: date) -> datetime:
    """Naive UTC instant of 00:00 UTC+7 on ``day``."""
    start = datetime(day.year, day.month, day.day, tzinfo=SHOP_ZONE)
    return start.astimezone(UTC).replace(tzinfo=None)


def plain_decimal(value: Decimal) -> str:
    """``72000`` / ``72000.5`` -- never ``7.2E+4``."""
    return format(value.normalize(), "f")


def _price_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        value = value.get("amount")
        if value is None:
            return None
    try:
        return plain_decimal(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _sku_row(sku: Mapping[str, Any]) -> dict[str, Any] | None:
    sku_id = sku.get("id") or sku.get("sku_id")
    if not sku_id:
        return None
    price = sku.get("price") if isinstance(sku.get("price"), Mapping) else {}
    assert isinstance(price, Mapping)
    return {
        "sku_id": str(sku_id),
        "seller_sku": str(sku.get("seller_sku") or "") or None,
        "list_price": _price_text(price.get("tax_exclusive_price") or price.get("amount")),
        "sale_price": _price_text(price.get("sale_price")),
        "currency": str(price.get("currency") or "") or None,
    }


def skus_of(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    """SKU id, seller SKU and prices, sorted by SKU id."""
    rows = [
        row
        for sku in raw.get("skus") or []
        if isinstance(sku, Mapping) and (row := _sku_row(sku)) is not None
    ]
    return sorted(rows, key=lambda row: row["sku_id"])


def list_prices(item: Mapping[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    """``{sku_id: (list_price, sale_price)}`` from a Search Products row or a snapshot."""
    return {row["sku_id"]: (row["list_price"], row["sale_price"]) for row in skus_of(item)}


def snapshot_prices(skus: Iterable[Mapping[str, Any]] | None) -> dict[str, tuple[Any, Any]]:
    return {
        str(row.get("sku_id")): (row.get("list_price"), row.get("sale_price"))
        for row in skus or []
        if isinstance(row, Mapping)
    }


def prices_moved(
    listed: Mapping[str, tuple[str | None, str | None]],
    stored: Mapping[str, tuple[Any, Any]],
) -> bool:
    """A list row's SKU prices differ from the snapshot's (a ``None`` side is not compared)."""
    if set(listed) != set(stored):
        return True
    for sku_id, (list_price, sale_price) in listed.items():
        old_list, old_sale = stored[sku_id]
        if list_price is not None and old_list is not None and list_price != old_list:
            return True
        if sale_price is not None and old_sale is not None and sale_price != old_sale:
            return True
    return False


def _images(raw: Mapping[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for image in raw.get("main_images") or []:
        uri = image.get("uri") if isinstance(image, Mapping) else image
        if uri:
            out.append({"uri": str(uri), "hash": sha256_text(str(uri))[:16]})
    return out


def _attributes(raw: Mapping[str, Any]) -> list[Any]:
    rows = []
    for attr in raw.get("product_attributes") or []:
        if not isinstance(attr, Mapping):
            continue
        values = sorted(
            str(v.get("id") or v.get("name") or "")
            for v in attr.get("values") or []
            if isinstance(v, Mapping)
        )
        rows.append([str(attr.get("id") or attr.get("name") or ""), values])
    return sorted(rows)


def _leaf_category(raw: Mapping[str, Any]) -> str | None:
    chains = [c for c in raw.get("category_chains") or [] if isinstance(c, Mapping)]
    leaves = [c for c in chains if c.get("is_leaf")]
    pick = leaves[-1] if leaves else (chains[-1] if chains else None)
    return str(pick.get("id")) if pick and pick.get("id") else None


@dataclass(frozen=True)
class NormalizedProduct:
    tiktok_product_id: str
    title: str | None
    description: str | None
    description_hash: str | None
    main_images: list[dict[str, str]]
    attributes_hash: str | None
    skus: list[dict[str, Any]]
    category_id: str | None
    status: str | None
    update_time: int | None
    content_hash: str
    state_hash: str

    @property
    def image_uris(self) -> list[str]:
        return [image["uri"] for image in self.main_images]


def normalize_detail(raw: Mapping[str, Any], *, product_id: str | None = None) -> NormalizedProduct:
    """One Get Product body → the snapshot fields (``ValueError`` without a product id)."""
    pid = str(raw.get("id") or raw.get("product_id") or product_id or "")
    if not pid:
        raise ValueError("product detail without an id")
    title = str(raw["title"]).strip() if raw.get("title") is not None else None
    text = raw.get("description")
    description = str(text).strip() if text is not None else None
    description_hash = sha256_text(description) if description is not None else None
    images = _images(raw)
    attributes = _attributes(raw)
    attributes_hash = sha256_text(_canonical(attributes)) if attributes else None
    content_hash = sha256_text(
        _canonical([title, description_hash, [i["uri"] for i in images], attributes_hash])
    )
    skus = skus_of(raw)
    category_id = _leaf_category(raw)
    status = str(raw.get("status") or raw.get("product_status") or "") or None
    price_part = [[s["sku_id"], s["list_price"], s["sale_price"]] for s in skus]
    state_hash = sha256_text(_canonical([content_hash, price_part, status, category_id]))
    try:
        update_time = int(str(raw.get("update_time"))) if raw.get("update_time") else None
    except ValueError:
        update_time = None
    return NormalizedProduct(
        tiktok_product_id=pid,
        title=title,
        description=description
        if description is not None and len(description) <= DESCRIPTION_MAX_CHARS
        else None,
        description_hash=description_hash,
        main_images=images,
        attributes_hash=attributes_hash,
        skus=skus,
        category_id=category_id,
        status=status,
        update_time=update_time,
        content_hash=content_hash,
        state_hash=state_hash,
    )


# -- per-field value hashes (ADR-107 amendment §6, P60-1b) --------------------------------


def _image_uri_list(value: Any) -> list[str]:
    """Ordered image URIs from a ``main_images`` value (``[{uri}]`` or ``[uri]``)."""
    uris: list[str] = []
    for image in value if isinstance(value, list | tuple) else []:
        uri = image.get("uri") if isinstance(image, Mapping) else image
        if uri:
            uris.append(str(uri))
    return uris


def _amount_text(value: Any) -> str | None:
    """A recorded SKU amount in the snapshot's price form; junk is kept verbatim."""
    if value is None or value == "":
        return None
    try:
        return plain_decimal(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return f"invalid:{value}"


def _price_pairs(value: Any) -> list[list[Any]]:
    """``[[sku_id, list_price], ...]`` sorted, from a ``price`` write value."""
    items = value if isinstance(value, list | tuple) else []
    pairs = [
        [str(item.get("sku_id")), _amount_text(item.get("amount"))]
        for item in items
        if isinstance(item, Mapping)
    ]
    return sorted(pairs, key=lambda pair: pair[0])


def _sku_ids(value: Any) -> list[str] | None:
    if not isinstance(value, list | tuple):
        return None
    return sorted(str(item.get("sku_id")) for item in value if isinstance(item, Mapping))


def field_value_hash(field_name: str, value: Any) -> str | None:
    """sha256 of one listing field's value in the form ``product_snapshots`` hashes it.

    - ``title`` / ``description``: the stripped text (``description`` equals the
      snapshot's ``description_hash``);
    - ``main_images``: the ordered URI list (``[{uri}]`` or ``[uri]``);
    - ``price``: the sorted ``[sku_id, list_price]`` pairs, amounts as
      :func:`plain_decimal` (the snapshot's ``list_price`` form);
    - anything else: its canonical JSON.

    ``None`` for a ``None`` value: nothing to compare.
    """
    if value is None:
        return None
    if field_name in ("title", "description"):
        return sha256_text(str(value).strip())
    if field_name == "main_images":
        return sha256_text(_canonical(_image_uri_list(value)))
    if field_name == "price":
        return sha256_text(_canonical(_price_pairs(value)))
    return sha256_text(_canonical(value))


@dataclass(frozen=True)
class ProductFields:
    """A product's listing fields as TikTok shows them, hashable per field (§8).

    Built from a fresh read (:meth:`of`) or a stored snapshot
    (``store.product_fields_of_snapshot``). ``list_prices`` is
    ``{sku_id: list_price}`` in :func:`plain_decimal` form.
    """

    title: str | None
    description_hash: str | None
    image_uris: tuple[str, ...]
    list_prices: Mapping[str, str | None]

    @classmethod
    def of(cls, product: NormalizedProduct) -> ProductFields:
        return cls(
            title=product.title,
            description_hash=product.description_hash,
            image_uris=tuple(product.image_uris),
            list_prices={row["sku_id"]: row["list_price"] for row in product.skus},
        )

    def field_hash(self, field_name: str, like: Any = None) -> str | None:
        """The current value's hash; for ``price`` over the SKUs ``like`` names (all if none).

        ``None`` for a field this state does not hold (Juli writes only title,
        description, main images and price).
        """
        if field_name == "title":
            return field_value_hash("title", self.title)
        if field_name == "description":
            return self.description_hash
        if field_name == "main_images":
            return field_value_hash("main_images", list(self.image_uris))
        if field_name == "price":
            skus = _sku_ids(like)
            wanted = sorted(self.list_prices) if skus is None else skus
            pairs = [[sku, self.list_prices.get(sku)] for sku in wanted]
            return sha256_text(_canonical(pairs))
        return None


@dataclass(frozen=True)
class PreviousState:
    """What ``diff`` needs from the latest ``product_snapshots`` row."""

    title: str | None
    description_hash: str | None
    image_uris: list[str]
    attributes_hash: str | None
    skus: list[dict[str, Any]]
    category_id: str | None
    status: str | None
    content_hash: str
    state_hash: str
    tiktok_update_time: int | None = None


@dataclass(frozen=True)
class Change:
    kind: str
    fields: list[str]
    details: dict[str, Any] = field(default_factory=dict)


def diff(previous: PreviousState, new: NormalizedProduct) -> list[Change]:
    """One :class:`Change` per kind that moved (content, price, category, status)."""
    if previous.state_hash == new.state_hash:
        return []
    changes: list[Change] = []
    content_fields: list[str] = []
    details: dict[str, Any] = {}
    if previous.title != new.title:
        content_fields.append("title")
        details["title"] = {"before": previous.title, "after": new.title}
    if previous.description_hash != new.description_hash:
        content_fields.append("description")
        details["description_hash"] = {
            "before": previous.description_hash,
            "after": new.description_hash,
        }
    if previous.image_uris != new.image_uris:
        content_fields.append("main_images")
        details["main_images"] = {"before": previous.image_uris, "after": new.image_uris}
    if previous.attributes_hash != new.attributes_hash:
        content_fields.append("attributes")
        details["attributes_hash"] = {
            "before": previous.attributes_hash,
            "after": new.attributes_hash,
        }
    if content_fields:
        details["content_hash"] = {"before": previous.content_hash, "after": new.content_hash}
        changes.append(Change(KIND_CONTENT, content_fields, details))

    before = snapshot_prices(previous.skus)
    after = snapshot_prices(new.skus)
    moved: dict[str, Any] = {}
    price_fields: set[str] = set()
    for sku_id in sorted(set(before) | set(after)):
        old = before.get(sku_id, (None, None))
        cur = after.get(sku_id, (None, None))
        if old == cur:
            continue
        moved[sku_id] = {
            "list_price": {"before": old[0], "after": cur[0]},
            "sale_price": {"before": old[1], "after": cur[1]},
        }
        if old[0] != cur[0]:
            price_fields.add("list_price")
        if old[1] != cur[1]:
            price_fields.add("sale_price")
    if moved:
        # ``price`` first (the seller UI reads it), then which price moved.
        changes.append(Change(KIND_PRICE, ["price", *sorted(price_fields)], {"skus": moved}))

    if previous.category_id != new.category_id:
        changes.append(
            Change(
                KIND_CATEGORY,
                ["category_id"],
                {"category_id": {"before": previous.category_id, "after": new.category_id}},
            )
        )
    if previous.status != new.status:
        changes.append(
            Change(
                KIND_STATUS,
                ["status"],
                {"status": {"before": previous.status, "after": new.status}},
            )
        )
    return changes


__all__ = [
    "CONTENT_FIELDS",
    "Change",
    "NormalizedProduct",
    "PreviousState",
    "ProductFields",
    "diff",
    "epoch_to_naive_utc",
    "field_value_hash",
    "list_prices",
    "local_day",
    "local_midnight_utc",
    "normalize_detail",
    "plain_decimal",
    "prices_moved",
    "sha256_text",
    "skus_of",
    "snapshot_prices",
]
