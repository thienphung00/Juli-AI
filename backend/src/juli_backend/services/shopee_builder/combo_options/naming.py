"""Names, SKUs and the suggested stock of a combo option. Pure and deterministic."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from juli_backend.services.shopee_builder.combo_options import config
from juli_backend.services.shopee_builder.combo_options.models import Member
from juli_backend.services.shopee_builder.specs import MAX_TITLE_CHARS

DEFAULT_NAMES = ("", "Mặc định")


def slug(text: str) -> str:
    """Upper-case ASCII letters and digits only (Vietnamese diacritics removed, đ -> D)."""
    flat = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^A-Z0-9]", "", flat.encode("ascii", "ignore").decode().upper())


def fit(text: str, limit: int) -> str:
    """``text`` cut to at most ``limit`` characters (a trailing ellipsis when cut)."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _var_label(m: Member) -> str:
    return "" if m.variation_name in DEFAULT_NAMES else m.variation_name


def multi_pack_name(members: Sequence[Member], unit: str) -> str:
    n = sum(m.quantity for m in members)
    if len(members) == 1:
        label = _var_label(members[0])
        return f"{n} {unit} – {label}" if label else f"{n} {unit}"
    parts = ", ".join(
        f"{_var_label(m) or m.variation_id or 'Mặc định'} ×{m.quantity}" for m in members
    )
    return f"{n} {unit} – {parts}"


def bundle_name(members: Sequence[Member]) -> str:
    return " + ".join(
        f"{f'{m.product_name} {_var_label(m)}'.strip()} ×{m.quantity}" for m in members
    )


def full_name(name: str) -> str:
    return fit(name, MAX_TITLE_CHARS)


def option_name(name: str) -> str:
    return fit(name, config.SHOPEE_MAX_OPTION_NAME_CHARS)


def make_sku(shop_code: str, members: Sequence[Member], bundle: bool) -> str:
    """``<SHOP>-<ITEM>-<VAR>-x<N>`` for a multi-pack of one variation. A mixed multi-pack lists
    ``<VAR>x<q>`` parts joined by ``+``; a bundle joins ``<ITEM>-<VAR>-x<q>`` parts by ``+``.
    Over the Shopee SKU length: cut and ended by 6 hex of a hash of the full text, so two long
    SKUs never collide."""
    shop = slug(shop_code) or config.DEFAULT_SHOP_CODE
    if bundle:
        body = "+".join(f"{m.item_code}-{m.var_code}-x{m.quantity}" for m in members)
    elif len(members) == 1:
        m = members[0]
        body = f"{m.item_code}-{m.var_code}-x{m.quantity}"
    else:
        tails = "+".join(f"{m.var_code}x{m.quantity}" for m in members)
        body = f"{members[0].item_code}-{tails}-x{sum(m.quantity for m in members)}"
    sku = f"{shop}-{body}"
    limit = config.SHOPEE_MAX_SKU_CHARS
    if len(sku) <= limit:
        return sku
    digest = hashlib.sha1(sku.encode(), usedforsecurity=False).hexdigest()[:6].upper()
    return sku[: limit - 7] + "-" + digest


def suggested_stock(members: Sequence[Member]) -> int | None:
    """min over members of floor(stock / quantity); ``None`` when any member's stock is unknown.
    Shopee does not sync it: the label is ``config.STOCK_NOTE``."""
    out: list[int] = []
    for m in members:
        if m.stock is None:
            return None
        out.append(max(m.stock, 0) // m.quantity)
    return min(out) if out else None
