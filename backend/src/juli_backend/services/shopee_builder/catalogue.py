"""P92 B-1: the product picker -- every active listing Juli knows.

Listings come from the Connector catalogue (``platform_items`` + the newest snapshot) and from the
order lines (a product that sold but is not in the catalogue yet still appears), sorted by
90-day GMV. Per row: name, item id, 30 / 90-day orders and GMV, whether a giá vốn is set, and
whether the listing is excluded (Cài đặt › Loại trừ sản phẩm). Excluded listings are left out
unless ``include_excluded`` is asked for.

"Active": the catalogue status is not an unlisted / banned / deleted one. A listing nobody ever
bought and the catalogue does not know does not exist for Juli and is not listed.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.catalog import SKU_PREFIX
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import num
from juli_backend.services.shopee_analytics.loaders import ShopContext, product_totals_for
from juli_backend.services.shopee_builder.variations import observed_skus
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations.unit_cost import unit_cost

RECENT_DAYS = 30
SORTS = ("gmv_90d", "orders_90d", "orders_30d", "name")
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
INACTIVE_WORDS = (
    "unlist",
    "banned",
    "delete",
    "inactive",
    "hidden",
    "deleted",
    "draft",
    "da an",
    "ngung ban",
)


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.strip().lower().replace("đ", "d"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def is_active(status: str | None) -> bool:
    if not status:
        return True
    word = fold(status).replace("_", " ")
    return not any(w in word for w in INACTIVE_WORDS)


def _item_has_cost(
    ctx: ShopContext, item_id: str, observed: Mapping[str, str] | None = None
) -> tuple[bool, int, int]:
    """``(every variation has a giá vốn, with cost, variations)`` per the seller's rules.

    A variation the catalogue has no seller SKU for is looked up by the SKU text of its order lines
    (the key the profit engine costs it under): combo variations are often costed that way."""
    info = ctx.catalog.items.get(item_id)
    variations = list(info.variations) if info and info.variations else []
    pairs = (
        [(v.variation_id, v.seller_sku, v.name) for v in variations]
        if variations
        else [("", info.seller_sku if info else None, None)]
    )
    seen = {p[0] for p in pairs}
    pairs += [(vid, None, None) for vid in (observed or {}) if vid and vid not in seen]
    known = 0
    for vid, sku, name in pairs:
        sku = sku or _observed_sku(observed, vid, len(pairs))
        if unit_cost(ctx.rules, item_id, vid, seller_sku=sku, variation_name=name).known:
            known += 1
    return known == len(pairs), known, len(pairs)


def _observed_sku(observed: Mapping[str, str] | None, vid: str, n_pairs: int) -> str | None:
    if not observed:
        return None
    if vid in observed:
        return observed[vid]
    if n_pairs == 1:  # a single-model listing takes the lines that name no variation
        return observed.get("") or (next(iter(observed.values())) if len(observed) == 1 else None)
    return None


def picker(
    ctx: ShopContext,
    view: PeriodView,
    anchor: date,
    *,
    query: str | None = None,
    include_excluded: bool = False,
    sort: str = "gmv_90d",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """The picker payload for a 90-day ``view`` ending on ``anchor``."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {list(SORTS)}")
    recent_from = anchor - timedelta(days=RECENT_DAYS - 1)
    orders90: dict[str, set[str]] = defaultdict(set)
    orders30: dict[str, set[str]] = defaultdict(set)
    gmv90: dict[str, Decimal] = defaultdict(lambda: ZERO)
    gmv30: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln, _ in view.pairs:
        orders90[ln.product_id].add(ln.order_id)
        gmv90[ln.product_id] += ln.order_value
        if ln.order_date >= recent_from:
            orders30[ln.product_id].add(ln.order_id)
            gmv30[ln.product_id] += ln.order_value
    shopee = product_totals_for(view.data.product_flows, view.data.lines)
    seen_skus = observed_skus(view.lines)
    # Order lines whose SKU matched no listing carry a placeholder id ("sku:…"): they are not a
    # product the seller can act on, so they are counted apart instead of listed.
    unmatched = {i for i in orders90 if i.startswith(SKU_PREFIX) and i not in ctx.catalog.items}
    unmatched_orders = len(set().union(*(orders90[i] for i in unmatched))) if unmatched else 0
    ids = (set(ctx.catalog.items) | set(orders90)) - unmatched
    needle = fold(query) if query else None
    rows: list[dict[str, Any]] = []
    hidden = 0
    for item_id in ids:
        info = ctx.catalog.items.get(item_id)
        status = info.status if info else None
        if not is_active(status):
            continue
        excluded = item_id in view.excluded
        if excluded and not include_excluded:
            hidden += 1
            continue
        name = view.names.get(item_id) or ctx.catalog.name(item_id)
        if needle and needle not in fold(name) and needle not in item_id.lower():
            continue
        if item_id in shopee:
            gmv, basis = shopee[item_id][0], "shopee_product_period"
        else:
            gmv, basis = gmv90.get(item_id, ZERO), "order_lines"
        all_costed, with_cost, n_var = _item_has_cost(ctx, item_id, seen_skus.get(item_id))
        rows.append(
            {
                "item_id": item_id,
                "name": name,
                "status": status,
                "orders_30d": len(orders30.get(item_id, ())),
                "orders_90d": len(orders90.get(item_id, ())),
                "gmv_30d": num(gmv30.get(item_id, ZERO)),
                "gmv_90d": num(gmv),
                "gmv_basis": basis,
                "price": num(info.current_price or info.list_price) if info else None,
                "stock": info.stock if info else None,
                "variation_count": n_var if info and info.variations else 0,
                "has_cost": all_costed,
                "variations_with_cost": with_cost,
                "missing_cost_chip": None if all_costed else "thiếu giá vốn",
                "excluded": excluded,
                "exclude_reason": view.excluded.get(item_id),
            }
        )
    keys: Mapping[str, Any] = {
        "gmv_90d": lambda r: (-(r["gmv_90d"] or 0), r["item_id"]),
        "orders_90d": lambda r: (-r["orders_90d"], r["item_id"]),
        "orders_30d": lambda r: (-r["orders_30d"], r["item_id"]),
        "name": lambda r: (fold(r["name"]), r["item_id"]),
    }
    rows.sort(key=keys[sort])
    total = len(rows)
    limit = max(1, min(limit, MAX_LIMIT))
    return {
        "platform": "shopee",
        "window": view.window.json(),
        "sort": sort,
        "count": total,
        "offset": offset,
        "limit": limit,
        "products": rows[offset : offset + limit],
        "excluded_hidden": hidden,
        "unmatched_orders": unmatched_orders,
        "unmatched_label": "Đơn chưa khớp sản phẩm" if unmatched_orders else None,
        "missing_cost_count": sum(1 for r in rows if not r["has_cost"]),
    }


__all__ = ["DEFAULT_LIMIT", "SORTS", "is_active", "picker"]
