"""P98 S9: the ads builder's service -- new Dịch vụ Hiển thị Sản phẩm setups (chiến dịch nhóm /
đơn): products, daily budget (>= Shopee's minimum), ROAS target or Shopee-optimised, dates,
validated against the shop, with each product's measured ad numbers beside them. Returns inputs
and facts only; the ads family (W2-F) turns them into an option. Read-only."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shopee_analytics.fmt import num, ratio
from juli_backend.services.shopee_builder import service
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.engine.contract import OptionResult
from juli_backend.services.shopee_builder.engine_families import integrate
from juli_backend.services.shopee_builder.engine_families.facts import AdsNewCampaign
from juli_backend.services.shopee_builder.specs_p98 import (
    ADS_BUDGET_FLOOR,
    AdsRequest,
    AdsSetup,
    BuilderInputError,
)
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import loader
from juli_backend.services.shopee_recommendations.env import RecoEnv

DEFAULT_DAYS = 30  # a setup without an end date: the "30 ngày đầu" horizon
NO_ADS = "Sản phẩm này chưa có số liệu quảng cáo trong 30 ngày: chưa ước tính được, cần chạy thử"


def product_ad_facts(env: RecoEnv, item: str) -> dict[str, Any]:
    """The product's measured ad numbers over the env window (placed-orders basis for the ads
    report; order lines are confirmed orders)."""
    fig = env.view.ads.product_figures.get(item)
    spend = env.view.ads.product_spend.get(item)
    pp = env.product(item)
    campaigns = [
        {
            "campaign_key": c.key,
            "name": c.name,
            "running": c.running,
            "spend": num(c.products[item]),
            "campaign_impressions": num(c.impressions),
            "campaign_clicks": num(c.clicks),
            "campaign_orders": num(c.orders),
            "campaign_gmv": num(c.gmv),
        }
        for c in env.view.ads.campaigns
        if item in c.products
    ]
    has = spend is not None and spend > ZERO
    return {
        "item_id": item,
        "name": env.name(item),
        "window_days": env.window_days,
        "spend": num(spend),
        "gmv_placed": num(fig.gmv if fig else None),
        "direct_gmv_placed": num(fig.direct_gmv if fig else None),
        "roas_broad": ratio(fig.roas_broad if fig else None, 2),
        "roas_direct": ratio(fig.roas_direct if fig else None, 2),
        "break_even_roas": ratio(pp.break_even_roas if pp else None, 2),
        "below_break_even": pp.ads_below_break_even if pp else None,
        "orders": 0 if pp is None else pp.orders,
        "campaigns": campaigns,
        "measured": has,
        "note": None if has else NO_ADS,
    }


def _setup(env: RecoEnv, s: AdsSetup) -> dict[str, Any]:
    for item in s.item_ids:
        if item in env.excluded:
            raise BuilderInputError("product_excluded", "Sản phẩm này đã bị loại trừ", item_id=item)
        if item not in env.ctx.catalog.items and env.orders_of(item) == 0:
            raise BuilderInputError("product_not_found", "Không có sản phẩm này", 404, item_id=item)
    days = None if s.end_date is None else (s.end_date - s.start_date).days + 1
    return {
        "campaign": s.campaign,
        "campaign_label": "Chiến dịch nhóm" if s.campaign == "group" else "Chiến dịch đơn",
        "name": s.name,
        "daily_budget": s.daily_budget,
        "budget_minimum": ADS_BUDGET_FLOOR,
        "roas": s.roas.model_dump(),
        "start_date": s.start_date.isoformat(),
        "end_date": None if s.end_date is None else s.end_date.isoformat(),
        "days": days,
        "total_budget": None if days is None else s.daily_budget * days,
        "products": [product_ad_facts(env, i) for i in s.item_ids],
        "inputs": s.model_dump(mode="json"),
    }


def campaign_of(s: AdsSetup) -> AdsNewCampaign:
    """A setup as the ads family's input; no end date = a 30-day horizon from the start."""
    end = s.end_date or s.start_date + timedelta(days=DEFAULT_DAYS - 1)
    return AdsNewCampaign(
        item_ids=tuple(s.item_ids),
        daily_budget=Decimal(s.daily_budget),
        start=s.start_date,
        end=end,
        roas_target=None if s.roas.target is None else Decimal(str(s.roas.target)),
        ad_type=integrate.AD_TYPE,
        label=s.name,
    )


def spec_of(s: AdsSetup) -> sp.AdsNewSpec:
    """A setup as a builder version (``kind = ads_new``): saved like any other version, its result
    in Kế hoạch is the same ``integrate`` path as here."""
    return sp.AdsNewSpec(
        kind="ads_new",
        campaign=s.campaign,
        item_ids=list(s.item_ids),
        daily_budget=s.daily_budget,
        roas_target=s.roas.target,
        start=s.start_date,
        end=s.end_date,
        name=s.name,
    )


def assemble(env: RecoEnv, req: AdsRequest, shop_id: str = "") -> dict[str, Any]:
    setups: list[dict[str, Any]] = []
    keyed: list[tuple[str, OptionResult | None]] = []
    for i, s in enumerate(req.setups):
        out = _setup(env, s)
        # ADR-122 d.8: views from spend ÷ measured CPM, extra orders measured on / off days only
        # P99: the version to send to "Chọn" / "Chạy cùng nhau" to add this setup to Kế hoạch;
        # seeded on it, so the saved version and Kế hoạch draw the same numbers
        spec = spec_of(s).model_dump(mode="json")
        ev = integrate.ads_result(env, campaign_of(s), shop_id=shop_id, seed_payload=spec)
        out["result"] = ev.result_json()
        out["spec"] = spec
        setups.append(out)
        keyed.append((str(i), ev.result))
    return {
        "as_of": env.as_of.isoformat(),
        "setups": setups,
        "budget_minimum": ADS_BUDGET_FLOOR,
        # P98: the setups' indexes in the comparison order (per-30-day Δ lợi nhuận)
        "compare": [int(k) for k in integrate.compare_keys(keyed)],
    }


async def build(
    session: AsyncSession, shop_id: uuid.UUID, req: AdsRequest, *, now: datetime
) -> dict[str, Any]:
    env = await loader.load_env(session, shop_id, as_of=req.as_of, now=now)
    if env is None:
        raise service.NoShopeeData(str(shop_id))
    return assemble(env, req, str(shop_id))


__all__ = ["assemble", "build", "product_ad_facts", "spec_of"]
