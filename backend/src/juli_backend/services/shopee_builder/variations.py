"""P92 B-2: per product, per variation -- only price and profit margin.

``economics`` turns the catalogue (variations and their names / SKUs), the newest item snapshots
(list and selling price per variation) and the seller's rules (giá vốn, đóng gói, số món / phân
loại, VAT) into the rows the builder's variation picker and the product page's "So sánh phân loại"
show:

- ``list_price`` / ``selling_price`` -- the snapshot's list and current price of the variation
  (the item's own when the variation has none);
- ``pack_count`` -- from the Thông số shop pack column, else read from the name ("Combo 3 hộp" = 3),
  else 1; ``price_per_unit`` = selling price / pack count;
- ``margin_pct`` -- contribution of ONE order of this variation (platform fees by the shop's fee
  schedule, giá vốn x pack, đóng gói, VAT per the P91 D-12/D-14 flags) over what the seller
  keeps. ``None`` with ``margin_label`` "chưa tính" when the seller has not stated a giá vốn: the
  1/3-of-price fallback is never used here (P92 B-7.1).

- ``final_margin_pct`` / ``final_margin_basis`` (ADR-122 d.12, "Biên cuối", ước tính) --
  ``margin_pct`` (Biên ở giá bán, chắc chắn) less the 30-day rates of shop voucher, affiliate
  commission and ad cost measured on the variation's own orders (``"variation"``), else on its
  product's (``"product"``); ``None`` / ``None`` when there is no margin or no history at all.

Pure: the caller passes what it loaded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.catalog import ItemInfo
from juli_backend.services.shopee_analytics.fmt import num, pct
from juli_backend.services.shopee_analytics.margins import Rates, final_margin, measured_rates
from juli_backend.services.shopee_analytics.rules_view import ProfitRules
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, SkuCost, profit_lines
from juli_backend.services.shopee_recommendations.unit_cost import UnitCost, scope_of, unit_cost

NOT_COUNTED = "chưa tính"
NOT_COUNTED_REASON = "Chưa có giá vốn trong Thông số shop"
PACK_SOURCE_LABELS = {
    "set": "Thông số shop",
    "name": "đọc từ tên phân loại",
    "single": "mặc định 1",
}
DEFAULT_NAME = "Mặc định"


HUNDRED = Decimal(100)
BASIS_VARIATION = "variation"
BASIS_PRODUCT = "product"


def with_final_margin(
    rows: Sequence[Mapping[str, Any]],
    product_rates: Rates | None,
    sku_rates: Mapping[str, Rates] | None = None,
) -> list[dict[str, Any]]:
    """Each row gains ``final_margin_pct`` (Biên cuối, ước tính), ``final_margin_basis`` and
    ``final_rates``; a row without history of its own takes the product's rates."""
    out: list[dict[str, Any]] = []
    for row in rows:
        own = (sku_rates or {}).get(row.get("sku_key") or "")
        rates = own or product_rates
        value = final_margin(row.get("margin_pct"), rates)
        basis = None if value is None else (BASIS_VARIATION if own else BASIS_PRODUCT)
        out.append(
            {
                **row,
                "final_margin_pct": value,
                "final_margin_basis": basis,
                "final_rates": None if value is None or rates is None else rates.json(),
            }
        )
    return out


def cost_key(item_id: str, variation_id: str, seller_sku: str | None, cost: UnitCost) -> str:
    """The SKU key the profit engine costs this variation under (``engine.to_shop_lines``):
    the seller SKU (or the item id), ``×pack`` when a pack, ``bom:<scope>`` for a bill of
    materials."""
    scope = scope_of(item_id, variation_id)
    if cost.bom:
        return f"bom:{scope}"
    base = seller_sku or item_id
    return base if cost.pack_count == 1 else f"{base}×{cost.pack_count}"


def unit_margin(
    item_id: str,
    key: str,
    cost: UnitCost,
    list_price: Decimal,
    selling_price: Decimal,
    schedule: FeeSchedule,
    on: date,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    """``(margin rate, profit per unit, reason)`` of one order of one sold unit at
    ``selling_price``; ``(None, None, reason)`` when it cannot be computed."""
    if cost.cogs is None:
        return None, None, "cost_missing"
    line = OrderLine(
        order_id="variation:1",
        sku=key,
        product_id=item_id,
        order_date=on,
        qty=1,
        original_price=max(list_price, selling_price),
        deal_price=selling_price,
    )
    sku_cost = SkuCost(key, cost.cogs, cost.packaging or ZERO, vat=cost.vat)
    pb = profit_lines([line], {key: sku_cost}, schedule=schedule)[0][1]
    if pb.contribution is None:
        return None, None, ",".join(pb.missing) or "profit_unknown"
    revenue = pb.revenue
    if revenue <= 0:
        return None, pb.contribution, "no_revenue"
    return pb.contribution / revenue, pb.contribution, None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d if d > 0 else None


def observed_skus(lines: Iterable[Any]) -> dict[str, dict[str, str]]:
    """item id -> variation id (``""`` = none) -> the seller SKU text the item's newest order lines
    carry for it. The catalogue often has no seller SKU for a model (a single-model listing, a
    combo variation); the order lines do, and the shop's giá vốn is keyed by it, so the builder
    must look costs up by the same text the profit engine does (``ShopLine.base_key``)."""
    newest: dict[tuple[str, str], tuple[Any, str]] = {}
    for sl in lines:
        base = getattr(sl, "base_key", "") or ""
        if not base or base == sl.product_id:
            continue
        vid = sl.variation_id
        key = (sl.product_id, vid)
        prev = newest.get(key)
        if prev is None or sl.ordered_on >= prev[0]:
            newest[key] = (sl.ordered_on, base)
    out: dict[str, dict[str, str]] = {}
    for (item, vid), (_, base) in newest.items():
        out.setdefault(item, {})[vid] = base
    return out


def variation_rows(
    item_id: str,
    info: ItemInfo | None,
    snapshot_variations: Sequence[Mapping[str, Any]],
    *,
    rules: ProfitRules,
    schedule: FeeSchedule,
    on: date,
    item_list_price: Decimal | None = None,
    item_current_price: Decimal | None = None,
    observed: Mapping[str, str] | None = None,
    product_rates: Rates | None = None,
    sku_rates: Mapping[str, Rates] | None = None,
) -> list[dict[str, Any]]:
    """The variations of one product (one row without variations). ``observed`` = variation id ->
    the SKU text on the order lines (:func:`observed_skus`), used where the catalogue has none.
    ``product_rates`` / ``sku_rates`` (:func:`measured_rates`) add Biên cuối to every row."""
    snaps = {str(s.get("variation_id") or ""): s for s in snapshot_variations}
    base_list = _dec(item_list_price) or _dec(info.list_price if info else None)
    base_now = _dec(item_current_price) or _dec(info.current_price if info else None)
    catalogued = list(info.variations) if info else []
    entries: list[tuple[str, str | None, str | None]] = [
        (v.variation_id, v.name, v.seller_sku) for v in catalogued
    ]
    seen = {e[0] for e in entries}
    entries += [(vid, None, None) for vid in snaps if vid and vid not in seen]
    seen = {e[0] for e in entries}
    entries += [(vid, None, None) for vid in (observed or {}) if vid and vid not in seen]
    if not entries:
        entries = [("", None, info.seller_sku if info else None)]
    entries = [
        (vid, name, sku or _observed_for(observed, vid, entries)) for vid, name, sku in entries
    ]
    rows: list[dict[str, Any]] = []
    for variation_id, name, sku in sorted(entries, key=lambda e: (e[0] == "", e[0])):
        snap = snaps.get(variation_id) or {}
        own_list, own_now = _dec(snap.get("list_price")), _dec(snap.get("current_price"))
        listed = own_list or own_now or base_list
        selling = own_now or own_list or base_now or base_list
        cost = unit_cost(rules, item_id, variation_id, seller_sku=sku, variation_name=name)
        key = cost_key(item_id, variation_id, sku, cost)
        margin: Decimal | None = None
        profit_unit: Decimal | None = None
        reason: str | None = "price_missing"
        if listed is not None and selling is not None:
            margin, profit_unit, reason = unit_margin(
                item_id, key, cost, listed, selling, schedule, on
            )
        per_unit = safe_div(selling, Decimal(cost.pack_count)) if selling is not None else None
        rows.append(
            {
                "variation_id": variation_id,
                "name": name or DEFAULT_NAME,
                "sku": sku,
                "sku_key": key,
                "list_price": num(listed),
                "selling_price": num(selling),
                "pack_count": cost.pack_count,
                "pack_source": cost.pack_source,
                "pack_source_label": PACK_SOURCE_LABELS[cost.pack_source],
                "price_per_unit": num(per_unit),
                "margin_pct": pct(pct_points(margin)),
                "profit_per_unit": num(profit_unit),
                "margin_label": None if margin is not None else NOT_COUNTED,
                "margin_reason": None
                if margin is not None
                else (NOT_COUNTED_REASON if reason == "cost_missing" else reason),
                "has_cost": cost.known,
                "stock": snap.get("stock"),
            }
        )
    return with_final_margin(rows, product_rates, sku_rates)


def with_orders(
    rows: Sequence[dict[str, Any]], lines: Iterable[Any], item_id: str
) -> list[dict[str, Any]]:
    """P96: each row's ``orders_30d`` (orders in the window holding its SKU; a listing with one row
    counts every order of the item) and the rows ordered best seller first, then in stock, then
    unknown stock, sold out last -- so the builder's default is a variation that sells."""
    mine = [ln for ln in lines if ln.product_id == item_id]
    single = len(rows) == 1
    out = []
    for row in rows:
        key = row.get("sku_key")
        orders = {ln.order_id for ln in mine if single or (key and ln.sku == key)}
        out.append({**row, "orders_30d": len(orders)})

    def stock_rank(row: Mapping[str, Any]) -> int:
        stock = row.get("stock")
        return 1 if stock is None else (0 if stock > 0 else 2)

    out.sort(key=lambda r: (-r["orders_30d"], stock_rank(r)))
    return out


def _observed_for(
    observed: Mapping[str, str] | None,
    variation_id: str,
    entries: Sequence[tuple[str, str | None, str | None]],
) -> str | None:
    """The SKU text of the order lines for this variation; a listing with a single model takes the
    lines that carry no variation (older lines, before the catalogue named the model)."""
    if not observed:
        return None
    if variation_id in observed:
        return observed[variation_id]
    if len(entries) == 1 and observed:
        return observed.get("") or (next(iter(observed.values())) if len(observed) == 1 else None)
    return None


def economics(
    item_id: str,
    name: str,
    rows: list[dict[str, Any]],
    *,
    vat: Mapping[str, Any],
) -> dict[str, Any]:
    """The payload of ``GET .../products/{item}/variations``."""
    return {
        "item_id": item_id,
        "name": name,
        "variations": rows,
        "columns": ["list_price", "selling_price", "price_per_unit", "margin_pct"],
        "final_margin_note": "Biên cuối (ước tính) = biên ở giá bán trừ tỉ lệ voucher shop, "
        "hoa hồng liên kết và chi phí quảng cáo đo trong 30 ngày",
        "margin_basis": "Biên của một đơn gồm 1 đơn vị bán của phân loại này, sau phí sàn, "
        "giá vốn, đóng gói" + (" và VAT" if vat.get("basis") == "after_vat" else ""),
        "vat": dict(vat),
        "missing_cost": [r["variation_id"] for r in rows if not r["has_cost"]],
    }


__all__ = [
    "NOT_COUNTED",
    "Rates",
    "cost_key",
    "economics",
    "final_margin",
    "measured_rates",
    "observed_skus",
    "unit_margin",
    "variation_rows",
    "with_final_margin",
    "with_orders",
]

__all__ = ["Rates", "final_margin", "measured_rates"]  # re-exported (ADR-122 d.12 one math)
