"""P98 S8: the KOL builder's service -- a KOL from the KOL report, the products, the commission and
the samples (product, quantity, shipping fee) validated against the shop, with the measured numbers
of the KOL's own rows (orders, GMV, commission rate, clicks, conversion) beside them. Returns
inputs and facts only; the affiliate family (W2-F) turns them into an option. Read-only."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics import kol
from juli_backend.services.shopee_analytics.fmt import num, ratio
from juli_backend.services.shopee_builder import service
from juli_backend.services.shopee_builder.specs_p98 import BuilderInputError, KolRequest, KolSetup
from juli_backend.services.shopee_recommendations import loader
from juli_backend.services.shopee_recommendations.env import RecoEnv

NO_ROW = "Chưa có đơn của KOL này với sản phẩm này"


def _kol_json(stat: kol.KolStat) -> dict[str, Any]:
    return {
        "kol_key": stat.key,
        "handle": stat.handle,
        "channel": stat.channel,
        "orders_seen": stat.orders_seen,
        "partner_orders": num(stat.partner_orders),
        "partner_clicks": num(stat.partner_clicks),
        "clicks_per_30d": num(stat.clicks_per_30d),
        "conversion": ratio(stat.conv_raw),
        "roi_shopee": ratio(stat.roi_shopee),
        "shipments": stat.shipments,
        "typical_sample_qty": stat.typical_qty,
        "last_ship_fee": num(stat.last_ship_fee),
    }


def _product_json(model: kol.KolModel, item: str, name: str) -> dict[str, Any]:
    stat = model.pool.products.get(item)
    return {
        "item_id": item,
        "name": name,
        "current_commission_rate": None if stat is None else ratio(stat.rate),
        "current_commission_source": None if stat is None else stat.rate_source,
        "orders": 0 if stat is None else stat.orders,
        "affiliate_orders": 0 if stat is None else stat.aff_orders,
        "units_per_order": None if stat is None else ratio(stat.units_per_order, 3),
        "aov": None if stat is None else num(stat.aov),
    }


def assemble(env: RecoEnv, model: kol.KolModel, req: KolRequest) -> dict[str, Any]:
    """Pure part: the KOL model of the window + a request -> the validated setups with facts."""
    rows = {(r.kol_key, r.item_id): r for r in model.rows}
    setups: list[dict[str, Any]] = []
    for s in req.kols:
        setups.append(_setup(env, model, rows, s))
    return {
        "as_of": env.as_of.isoformat(),
        "window": model.window,
        "setups": setups,
        "labels": {
            "sample_cost": "số lượng × (giá vốn + đóng gói) + phí ship; không tính phí book KOL",
            "low_data": kol.LOW_DATA_LABEL,
        },
    }


def _setup(
    env: RecoEnv,
    model: kol.KolModel,
    rows: dict[tuple[str, str], kol.KolRow],
    s: KolSetup,
) -> dict[str, Any]:
    stat = model.pool.kols.get(s.kol_key)
    if stat is None:
        raise BuilderInputError(
            "kol_not_found", "KOL này không có trong báo cáo KOL", 404, kol_key=s.kol_key
        )
    products = []
    for item in s.item_ids:
        if item in env.excluded:
            raise BuilderInputError("product_excluded", "Sản phẩm này đã bị loại trừ", item_id=item)
        if item not in env.ctx.catalog.items and env.orders_of(item) == 0:
            raise BuilderInputError("product_not_found", "Không có sản phẩm này", 404, item_id=item)
        row = rows.get((s.kol_key, item))
        products.append(
            {
                **_product_json(model, item, env.name(item)),
                "measured": None if row is None else row.json(),
                "measured_note": NO_ROW if row is None else None,
            }
        )
    sample = None
    if s.sample is not None:
        unit = kol.sample_unit_cost(env.ctx, env.view, s.sample.item_id)
        cost = None if unit is None else s.sample.qty * unit.total + Decimal(s.sample.ship_fee)
        sample = {
            "item_id": s.sample.item_id,
            "qty": s.sample.qty,
            "ship_fee": s.sample.ship_fee,
            "unit_cost": None if unit is None else num(unit.total),
            "unit_cost_basis": None if unit is None else unit.label,
            "cost": num(cost),
            "cost_note": None if cost is not None else "chưa tính: thiếu giá vốn",
        }
    return {
        "kol": _kol_json(stat),
        "commission_pct": s.commission_pct,
        "products": products,
        "sample": sample,
        "inputs": {
            "kol_key": s.kol_key,
            "item_ids": list(s.item_ids),
            "commission_pct": s.commission_pct,
            "sample_item_id": None if s.sample is None else s.sample.item_id,
            "sample_qty": 0 if s.sample is None else s.sample.qty,
            "sample_ship_fee": 0 if s.sample is None else s.sample.ship_fee,
        },
    }


async def build(
    session: AsyncSession, shop_id: uuid.UUID, req: KolRequest, *, now: datetime
) -> dict[str, Any]:
    env = await loader.load_env(session, shop_id, as_of=req.as_of, now=now)
    if env is None:
        raise service.NoShopeeData(str(shop_id))
    model = await kol.load_model(session, shop_id, env.ctx, env.view)
    return assemble(env, model, req)


__all__ = ["assemble", "build"]
