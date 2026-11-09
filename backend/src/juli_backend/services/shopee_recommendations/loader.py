"""Load a :class:`RecoEnv` for one shop inside its tenant scope.

Reads go through the analytics loaders (one view of the history window, the same numbers the
screens show) and a few extra repositories for the live ads / voucher settings. The caller
holds the shop scope (``with_shop_scope`` / ``get_active_shop``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import PlatformDailyMetricsRepo, PlatformPromotionsRepo
from juli_backend.services import shop_rules
from juli_backend.services.shopee_analytics import kol, loaders, service
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_recommendations import config, store
from juli_backend.services.shopee_recommendations.env import (
    CampaignSetting,
    RecoEnv,
    VoucherSetting,
)
from juli_backend.services.shopee_recommendations.listing import Keyword, Listing

ADS_DAILY = "ads_campaign_daily"


def _d(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):  # an unreadable setting is "not known"
        return None


async def load_campaign_settings(
    session: AsyncSession, shop_id: uuid.UUID, ctx: loaders.ShopContext, window: Window
) -> dict[str, CampaignSetting]:
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id, datasets=[ADS_DAILY], start=window.start, end=window.end, any_item=True
    )
    latest: dict[str, Any] = {}
    changes: dict[str, int] = {}
    previous: dict[str, Decimal | None] = {}
    week_start = window.end - timedelta(days=6)
    for r in sorted(rows, key=lambda r: (r.day, r.captured_at)):
        if r.segment != "all":
            latest[r.segment] = r
            roas = _d((r.extra or {}).get("roi_two_target"))
            if r.segment in previous and previous[r.segment] != roas and r.day >= week_start:
                changes[r.segment] = changes.get(r.segment, 0) + 1
            previous[r.segment] = roas
    out: dict[str, CampaignSetting] = {}
    for seg, r in latest.items():
        extra = r.extra or {}
        name = r.platform_source or seg
        setting = CampaignSetting(
            key=seg,
            name=name,
            daily_budget=_d(extra.get("daily_budget")),
            roas_target=_d(extra.get("roi_two_target")),
            purpose=ctx.purposes.get(seg) or ctx.purposes.get(name),
            campaign_id=None if extra.get("campaign_id") is None else str(extra["campaign_id"]),
            roas_changes_7d=changes.get(seg, 0),
        )
        out[seg] = setting
        out[name] = setting
    return out


async def load_voucher_settings(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> list[VoucherSetting]:
    rows = await PlatformPromotionsRepo(session).overlapping(
        shop_id,
        promo_types=["voucher"],
        start=window.start - timedelta(days=60),
        end=window.end,
    )
    newest: dict[str, Any] = {}
    for r in rows:
        extra = r.extra or {}
        vid = extra.get("voucher_id")
        if vid is None:
            continue
        key = str(vid)
        if key not in newest or r.captured_at >= newest[key].captured_at:
            newest[key] = r
    out = []
    for vid, r in sorted(newest.items()):
        e = r.extra or {}
        out.append(
            VoucherSetting(
                voucher_id=vid,
                name=r.program_name,
                value=_d(e.get("discount_amount")),
                pct=_d(e.get("discount_percent")),
                max_value=_d(e.get("max_value")),
                min_spend=_d(e.get("min_spend")),
                usage_limit=None if e.get("usage_limit") is None else int(e["usage_limit"]),
                starts_at=r.starts_at.isoformat() if r.starts_at else None,
                ends_at=r.ends_at.isoformat() if r.ends_at else None,
            )
        )
    return out


def usage_rate_of(env_view: Any) -> Decimal | None:
    """Mean usage rate of the shop's own past vouchers (u of contract 7); None if unknown."""
    rates = []
    for v in env_view.data.vouchers.rows:
        if v.by_shopee or v.usage_rate is None:
            continue
        r = v.usage_rate
        rates.append(r / 100 if r > 1 else r)
    if not rates:
        return None
    return sum(rates, Decimal(0)) / len(rates)


def listing_from(src: loaders.ListingSource, env: RecoEnv) -> Listing:
    """The audited listing of one product: the snapshot's title / cover / price (the catalogue
    and the newest order line stand in when there is no snapshot) and its keyword key list."""
    head = src.header
    title = (head.title if head and head.title else None) or env.ctx.catalog.name(src.item_id)
    price = head.current_price if head and head.current_price else None
    if price is None:
        prices = [p for sku in env.skus_of(src.item_id) if (p := env.current_price(sku))]
        price = min(prices) if prices else None
    images = list(head.image_urls) if head else []
    keywords = []
    for seed in src.seeds:
        m = src.market.get(seed.keyword)
        keywords.append(
            Keyword(
                seed.keyword,
                seed.role,
                None if m is None or m.volume is None else int(m.volume),
                None if m is None or m.difficulty is None else float(m.difficulty),
            )
        )
    return Listing(
        item_id=src.item_id,
        title=title,
        cover_url=images[0] if images else None,
        image_count=len(images),
        price=price,
        keywords=tuple(sorted(keywords, key=lambda k: (k.role, k.keyword))),
    )


async def load_env(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    as_of: date | None = None,
    now: Any = None,
) -> RecoEnv | None:
    """The environment for ``as_of`` (default: the newest day the shop has data for); None when
    the shop has no Shopee numbers."""
    anchor = as_of or await loaders.default_as_of(session, shop_id)
    if anchor is None:
        return None
    window = Window(anchor - timedelta(days=config.HISTORY_DAYS - 1), anchor)
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, window)
    env = RecoEnv(ctx=ctx, view=view, as_of=anchor)
    env.campaigns = await load_campaign_settings(session, shop_id, ctx, window)
    env.vouchers = await load_voucher_settings(session, shop_id, window)
    env.usage_rate = usage_rate_of(view)
    env.locked = await store.locked_products(session, shop_id, now)
    env.calibration = await store.load_calibrations(session, shop_id)
    env.acceptance = await store.load_acceptance(session, shop_id)
    env.sim = await store.load_sim(session, shop_id)
    env.banned_terms = tuple(await shop_rules.banned_terms(session, shop_id))
    env.kol = (await kol.load_model(session, shop_id, ctx, view)).pool
    # every active listing, sold or not: hide / relist / title of a listing nobody bought lately
    wanted = [
        *env.listing_item_ids(),
        *(i for i in env.view.active_items if i not in env.excluded),
    ]
    sources = await loaders.load_listing_sources(session, shop_id, list(dict.fromkeys(wanted)))
    env.listings = {item: listing_from(src, env) for item, src in sources.items()}
    return env
