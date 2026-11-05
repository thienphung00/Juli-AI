"""P92 B-10 "Giá thị trường": the product's price per unit against page 1 of Shopee's public
search for its main keywords (collected weekly by the Connector, ``market_search``).

For a product: take the newest page-1 capture of each of its 1-3 main keywords, drop ads and the
product's own listing, read the pack of every card from its title (``unit_price``), keep the cards
of the SAME unit that share words with the product's title, and compute the per-unit median, P25
and P75 plus the 5 closest cards. Nothing is invented: no keyword / no capture / fewer than
``MIN_SIMILAR`` similar cards = ``available: false`` with the reason and no numbers. A capture
older than ``STALE_AFTER_DAYS`` still shows, with its date and ``stale: true`` ("cũ").

The public tables are Ops-only, so the read is made in a short ``ops_role`` block (the seller's
Demo route reads the same public rows through this service only).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import MarketListingsReadRepo
from juli_backend.services.ingest import market as ingest_market
from juli_backend.services.market_stats import median, percentile
from juli_backend.services.ops.access import ops_role
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import unit_price as up
from juli_backend.services.shopee_recommendations import loader

STALE_AFTER_DAYS = 14
MIN_SIMILAR = 3
MIN_SIMILARITY = 0.25
CLOSEST = 5
PLATFORM_UTC_OFFSET = timedelta(hours=7)
NOTE = (
    "Giá các gian hàng khác trên trang 1 kết quả tìm kiếm công khai của Shopee, quy về cùng đơn "
    "vị; chỉ là bối cảnh, không phải căn cứ tạo thẻ giá."
)
REASONS = {
    "no_keyword": "Sản phẩm chưa có từ khoá chính (Ops tạo ở trang Từ khoá).",
    "no_capture": "Chưa thu thập trang tìm kiếm cho các từ khoá của sản phẩm.",
    "no_similar": "Trang tìm kiếm có ít hơn 3 sản phẩm giống để so giá.",
    "market_closed": "Không đọc được dữ liệu thị trường.",
}


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def _card(row: Any) -> dict[str, Any]:
    extra = row.extra or {}
    return {
        "item_id": row.platform_item_id,
        "title": row.title or "",
        "shop_title": extra.get("shop_title"),
        "price": _f(row.price),
        "price_min": extra.get("price_min"),
        "price_max": extra.get("price_max"),
        "sold_monthly": _f(row.sold_monthly),
        "sold_lifetime": _f(row.sold_lifetime),
        "pos": row.pos,
        "is_ad": bool(extra.get("is_ad")),
    }


def _day(collected_at: datetime) -> date:
    return (collected_at + PLATFORM_UTC_OFFSET).date()


def _own(
    title: str, rows: Sequence[Mapping[str, Any]], variation_id: str | None
) -> dict[str, Any] | None:
    """The variation the comparison is made for: the named one, else the cheapest per unit."""
    priced = [r for r in rows if r.get("selling_price")]
    if not priced:
        return None
    if variation_id is not None:
        chosen = next((r for r in priced if r["variation_id"] == variation_id), None)
        if chosen is None:
            return None
    else:
        chosen = min(priced, key=lambda r: r["selling_price"] / max(int(r["pack_count"]), 1))
    return dict(chosen)


def _position(per_unit: float | None, p25: float | None, p75: float | None) -> str | None:
    if per_unit is None or p25 is None or p75 is None:
        return None
    return "below_p25" if per_unit < p25 else "above_p75" if per_unit > p75 else "within"


def _pct(value: float | None, base: float | None) -> float | None:
    return None if value is None or not base else round((value / base - 1) * 100, 1)


def _unit_block(unit: str) -> dict[str, Any]:
    spec = up.UNITS[unit]
    return {"key": unit, "label": spec["label"], "per_label": spec["per_label"]}


def compute(
    *,
    item_id: str,
    name: str,
    keywords: Sequence[str],
    captures: Mapping[str, tuple[datetime, Sequence[Any]]],
    variation_rows: Sequence[Mapping[str, Any]],
    variation_id: str | None,
    draft_price: float | None,
    today: date,
    closest: bool = True,
) -> dict[str, Any]:
    """The payload (pure). ``captures``: keyword -> (collected_at, page-1 snapshot rows)."""
    base: dict[str, Any] = {
        "item_id": item_id,
        "name": name,
        "available": False,
        "reason": None,
        "keyword": None,
        "collected_on": None,
        "age_days": None,
        "stale": False,
        "stale_after_days": STALE_AFTER_DAYS,
        "keywords": [],
        "unit": None,
        "own": None,
        "market": None,
        "closest": None if closest else None,
        "marker": None,
        "note": NOTE,
    }
    if not keywords:
        return {**base, "reason": "no_keyword"}
    seen_kw = [k for k in keywords if k in captures]
    if not seen_kw:
        return {**base, "reason": "no_capture"}

    own_row = _own(name, variation_rows, variation_id)
    own_q = up.parse(name, multiplier=False)
    pack = int(own_row["pack_count"]) if own_row else 1
    own_total = up.Quantity(own_q.unit, own_q.qty * pack, own_q.source)
    own_block: dict[str, Any] | None = None
    own_unit_price: float | None = None
    if own_row:
        own_unit_price = up.per_unit_price(float(own_row["selling_price"]), own_total)
        prices = [float(r["selling_price"]) for r in variation_rows if r.get("selling_price")]
        own_block = {
            "variation_id": own_row["variation_id"],
            "selling_price": own_row["selling_price"],
            "price_min": min(prices),
            "price_max": max(prices),
            "pack_count": pack,
            "price_per_unit": None if own_unit_price is None else round(own_unit_price),
        }

    pool: dict[str, dict[str, Any]] = {}
    per_keyword: list[dict[str, Any]] = []
    newest: datetime | None = None
    for keyword in seen_kw:
        collected_at, cards = captures[keyword]
        day = _day(collected_at)
        similar_here = 0
        for row in cards:
            card = _card(row)
            if card["is_ad"] or card["item_id"] == item_id or not card["price"]:
                continue
            quantity = up.parse(card["title"])
            if quantity.unit != own_total.unit:
                continue
            sim = up.similarity(name, card["title"])
            if sim < MIN_SIMILARITY:
                continue
            per_unit = up.per_unit_price(card["price"], quantity)
            if per_unit is None:
                continue
            similar_here += 1
            current = pool.get(card["item_id"])
            if current is None or card["pos"] < current["position"]:
                pool[card["item_id"]] = {
                    **{k: card[k] for k in ("item_id", "shop_title", "price", "price_min")},
                    "name": card["title"],
                    "shop_name": card["shop_title"],
                    "price_max": card["price_max"],
                    "pack_count": round(quantity.qty) if quantity.unit == "hop" else 1,
                    "quantity": round(quantity.qty, 2),
                    "price_per_unit": round(per_unit),
                    "sold_monthly": card["sold_monthly"],
                    "sold_lifetime": card["sold_lifetime"],
                    "position": card["pos"],
                    "is_ad": False,
                    "similarity": round(sim, 2),
                }
        age = (today - day).days
        per_keyword.append(
            {
                "keyword": keyword,
                "collected_on": day.isoformat(),
                "age_days": age,
                "stale": age > STALE_AFTER_DAYS,
                "n_cards": len(cards),
                "n_similar": similar_here,
            }
        )
        newest = collected_at if newest is None or collected_at > newest else newest
    assert newest is not None
    collected_on = _day(newest)
    age = (today - collected_on).days
    out = {
        **base,
        "keyword": max(per_keyword, key=lambda k: k["n_similar"])["keyword"],
        "collected_on": collected_on.isoformat(),
        "age_days": age,
        "stale": age > STALE_AFTER_DAYS,
        "keywords": per_keyword,
        "unit": _unit_block(own_total.unit),
        "own": own_block,
    }
    listings = list(pool.values())
    if len(listings) < MIN_SIMILAR:
        return {**out, "reason": "no_similar", "n_similar": len(listings)}
    unit_prices = [float(x["price_per_unit"]) for x in listings]
    med, p25, p75 = (
        median(unit_prices),
        percentile(unit_prices, 0.25),
        percentile(unit_prices, 0.75),
    )
    position = _position(own_unit_price, p25, p75)
    market = {
        "n_similar": len(listings),
        "median": None if med is None else round(med),
        "p25": None if p25 is None else round(p25),
        "p75": None if p75 is None else round(p75),
        "own_vs_median_pct": _pct(own_unit_price, med),
        "position": position,
    }
    marker = None
    if draft_price is not None and draft_price > 0 and own_row is not None:
        draft_unit = up.per_unit_price(draft_price, own_total)
        marker = {
            "price": draft_price,
            "pack_count": pack,
            "price_per_unit": None if draft_unit is None else round(draft_unit),
            "position": _position(draft_unit, p25, p75),
            "vs_median_pct": _pct(draft_unit, med),
        }
    near = sorted(listings, key=lambda x: (-x["similarity"], x["position"], x["item_id"]))[:CLOSEST]
    return {
        **out,
        "available": True,
        "market": market,
        "closest": near if closest else None,
        "marker": marker,
    }


async def market_price(
    session: AsyncSession,
    shop_id: uuid.UUID,
    item_id: str,
    *,
    variation_id: str | None,
    draft_price: float | None,
    as_of: date | None,
    now: datetime,
    closest: bool = True,
) -> dict[str, Any]:
    """Load the product, its main keywords and their captures, and compute the payload."""
    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise builder.NoShopeeData(str(shop_id))
    if not (item_id in env.ctx.catalog.items or env.orders_of(item_id) > 0):
        raise LookupError(item_id)
    rows = (await builder.variation_rows_for(session, shop_id, env, [item_id]))[item_id]
    keywords = (await ingest_market.shop_keywords(session, shop_id)).get(item_id, [])
    captures: Mapping[str, tuple[datetime, Sequence[Any]]] = {}
    closed = False
    if keywords:
        try:
            async with session.begin_nested(), ops_role(session):
                captures = await MarketListingsReadRepo(session).latest_page1(keywords)
        except Exception:
            closed = True
    out = compute(
        item_id=item_id,
        name=env.name(item_id),
        keywords=keywords,
        captures=captures,
        variation_rows=rows,
        variation_id=variation_id,
        draft_price=draft_price,
        today=(now + PLATFORM_UTC_OFFSET).date(),
        closest=closest,
    )
    if closed:
        out["reason"] = "market_closed"
    out["reason_text"] = REASONS.get(out["reason"]) if out["reason"] else None
    return out


__all__ = ["REASONS", "compute", "market_price"]
