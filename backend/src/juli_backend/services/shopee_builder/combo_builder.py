"""P98 S7: the combo builder's service -- loads the shop's products, variations, costs and measured
rates, runs ``combo_options`` (count / generate / price) and returns the rows, the limit warnings
and, per row, the inputs a later engine call needs. Read-only: nothing is saved."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics.fmt import num
from juli_backend.services.shopee_builder import combo_options as co
from juli_backend.services.shopee_builder import service
from juli_backend.services.shopee_builder.engine.contract import OptionResult
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_builder.engine_families.facts import NewComboListing
from juli_backend.services.shopee_builder.specs_p98 import BuilderInputError, ComboRequest
from juli_backend.services.shopee_builder.variations import Rates, measured_rates, with_final_margin
from juli_backend.services.shopee_recommendations import loader
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.unit_cost import unit_cost

MARGIN_BASIS = {
    "price": "Biên ở giá bán (chắc chắn): sau phí sàn, giá vốn, đóng gói",
    "final": "Biên cuối (ước tính): biên ở giá bán trừ voucher shop, hoa hồng liên kết và "
    "quảng cáo đo trong 30 ngày",
}


def _check_items(env: RecoEnv, items: list[str]) -> None:
    for item in items:
        if item in env.excluded:
            raise BuilderInputError("product_excluded", "Sản phẩm này đã bị loại trừ", item_id=item)
        if item not in env.ctx.catalog.items and env.orders_of(item) == 0:
            raise BuilderInputError(
                "product_not_found", "Không có sản phẩm này", status=404, item_id=item
            )


def _dec_num(x: Decimal | None) -> int | float | None:
    return num(x)


def _row_json(row: co.PricedRow, rates: dict[str, Rates]) -> dict[str, Any]:
    o = row.option
    members = [
        {
            "item_id": m.item_id,
            "product_name": m.product_name,
            "variation_id": m.variation_id,
            "variation_name": m.variation_name,
            "quantity": m.quantity,
            "unit_price": _dec_num(m.unit_price),
        }
        for m in o.members
    ]
    return {
        "key": o.key,
        "form": o.form,
        "name": o.name,
        "option_name": o.option_name,
        "sku": o.sku,
        "units": o.units,
        "members": members,
        "suggested_stock": o.suggested_stock,
        "stock_note": o.stock_note,
        "price": _dec_num(row.price),
        "price_per_box": _dec_num(row.price_per_box),
        "separate_total": _dec_num(row.separate_total),
        "saving": _dec_num(row.saving),
        "saving_pct": _dec_num(row.saving_pct),
        "margin_pct": _dec_num(row.margin_pct),  # Biên ở giá bán (chắc chắn)
        "final_margin_pct": _dec_num(row.final_margin_pct),  # Biên cuối (ước tính)
        "final_rates": None if row.final_rates is None else row.final_rates.json(),
        "profit_per_order": _dec_num(row.profit_per_order),
        "margin_label": row.margin_label,
        "below_floor": row.below_floor,
        "floor_basis": row.floor_basis,
        "overridden": row.overridden,
        "basis": row.basis,
        "notes": list(row.notes),
        # what a later engine call needs for this option (no I/O left to do)
        "inputs": {
            "option_key": o.key,
            "item_ids": sorted({m.item_id for m in o.members}),
            "price": _dec_num(row.price),
            "profit_per_order": _dec_num(row.profit_per_order),
            "members": [
                {
                    **mj,
                    "cogs_per_unit": _dec_num(m.cost.cogs if m.cost else None),
                    "packaging": _dec_num(m.cost.packaging if m.cost else None),
                    "stock": m.stock,
                }
                for mj, m in zip(members, o.members, strict=True)
            ],
            "rates": {
                i: rates[i].json() for i in sorted({m.item_id for m in o.members}) if i in rates
            },
        },
    }


def listing_of(
    row: co.PricedRow, rows_by_item: dict[str, list[dict[str, Any]]]
) -> NewComboListing | None:
    """A priced row as a new combo listing (ADR-122 d.7): its members' order-line SKUs, and
    whether the shop already sells this pack size of the product (E3: switching only)."""
    o = row.option
    if row.price is None:
        return None
    members: list[tuple[str, str, int]] = []
    for m in o.members:
        vrow = next(
            (v for v in rows_by_item.get(m.item_id, []) if v["variation_id"] == m.variation_id),
            None,
        )
        if vrow is None or not vrow.get("sku_key"):
            return None
        members.append((m.item_id, str(vrow["sku_key"]), m.quantity))
    items = tuple(dict.fromkeys(m.item_id for m in o.members))
    sold = False
    if len(o.members) == 1:
        m = o.members[0]
        vrow = next(v for v in rows_by_item[m.item_id] if v["variation_id"] == m.variation_id)
        sold = integrate.pack_sold_today(
            rows_by_item[m.item_id], int(vrow.get("pack_count") or 1), m.quantity
        )
    return NewComboListing(
        key=o.key,
        label=o.name,
        item_ids=items,
        members=tuple(members),
        price=row.price,
        profit_per_order=row.profit_per_order,
        pack_sold_today=sold,
    )


def row_result(
    env: RecoEnv,
    row: co.PricedRow,
    rows_by_item: dict[str, list[dict[str, Any]]],
    shop_id: str = "",
) -> integrate.Evaluated | None:
    """The row's ``OptionResult`` through the listing combo family and the engine (None: the
    row has no price or a member variation without an order-line SKU)."""
    listing = listing_of(row, rows_by_item)
    if listing is None:
        return None
    return integrate.combo_listing_result(env, listing, pack_rows=rows_by_item, shop_id=shop_id)


def assemble(
    env: RecoEnv,
    rows_by_item: dict[str, list[dict[str, Any]]],
    req: ComboRequest,
    shop_id: str = "",
) -> dict[str, Any]:
    """Pure part: economics rows (+ rates) -> options -> priced rows. ``rows_by_item`` = the
    variation rows of each picked product (``variations.variation_rows`` shape)."""
    products: list[co.ProductIn] = []
    rates: dict[str, Rates] = {}
    shown: dict[str, list[dict[str, Any]]] = {}
    for pick in req.products:
        item = pick.item_id
        pairs = [(ln, pb) for ln, pb in env.view.pairs if ln.product_id == item]
        product_rates, sku_rates = measured_rates(pairs, env.view.ads.product_spend.get(item))
        if product_rates is not None:
            rates[item] = product_rates
        shown[item] = with_final_margin(rows_by_item[item], product_rates, sku_rates)
        variations = []
        for row in rows_by_item[item]:
            cost = unit_cost(
                env.rules,
                item,
                row["variation_id"],
                seller_sku=row["sku"],
                variation_name=row["name"],
            )
            variations.append(co.VariationIn.from_row(row, cost))
        products.append(co.ProductIn(item, env.name(item), tuple(variations)))
    rules, packs, picks = req.combo_rules(), req.packs(), req.picks()
    have = {p.item_id: {v.variation_id for v in p.variations} for p in products}
    for pick in req.products:
        missing = [v for v in pick.variation_ids if v not in have[pick.item_id]]
        if missing:
            raise BuilderInputError(
                "variation_not_found",
                "Không có phân loại này",
                status=404,
                item_id=pick.item_id,
                variation_ids=missing,
            )
    try:
        counted = co.count(products, picks, packs, rules)
        options = co.generate(products, picks, packs, rules)
    except co.ComboInputError as exc:
        raise BuilderInputError("bad_combo_input", str(exc)) from None
    first = req.products[0].item_id
    eco = co.Economics(env.schedule(first), env.as_of, rates)
    floor = None if req.floor_pct is None else Decimal(str(req.floor_pct))
    overrides = {k: Decimal(v) for k, v in req.overrides.items() if k in {o.key for o in options}}
    try:
        priced = co.price(options, req.price_rule.to_rule(), eco, floor, overrides)
    except co.PriceRuleError as exc:
        raise BuilderInputError("bad_price_rule", str(exc)) from None
    row_json: list[dict[str, Any]] = []
    keyed: list[tuple[str, OptionResult | None]] = []
    for r in priced:
        out = _row_json(r, rates)
        ev = row_result(env, r, rows_by_item, shop_id)
        out["result"] = ev.result_json() if ev is not None else None
        out["result_refusal"] = None if ev is None else ev.refusal_json()
        row_json.append(out)
        keyed.append((r.option.key, None if ev is None else ev.result))
    return {
        "as_of": env.as_of.isoformat(),
        "count": {
            "total": counted.total,
            "kept": counted.kept,
            "over_cap": counted.over_cap,
            "by_form": dict(counted.by_form),
        },
        "variations": shown,  # the picked products' variation rows, both margins
        "rows": row_json,
        # P98: the rows' keys in the comparison order (per-30-day Δ lợi nhuận, best first)
        "compare": integrate.compare_keys(keyed),
        "warnings": co.limit_warnings(options),
        "margin_basis": MARGIN_BASIS,
        "floor_pct": req.floor_pct,
    }


async def build(
    session: AsyncSession, shop_id: uuid.UUID, req: ComboRequest, *, now: datetime
) -> dict[str, Any]:
    env = await loader.load_env(session, shop_id, as_of=req.as_of, now=now)
    if env is None:
        raise service.NoShopeeData(str(shop_id))
    items = [p.item_id for p in req.products]
    _check_items(env, items)
    loaded = await service.variation_rows_for(session, shop_id, env, items)
    return assemble(env, loaded, req, str(shop_id))


__all__ = ["assemble", "build"]
