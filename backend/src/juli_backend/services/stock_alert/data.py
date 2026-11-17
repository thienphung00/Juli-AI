"""The facts of every variation of one shop, from the database (Part S).

Inside the shop's tenant scope; reads only. Sources:

- ``shopee_stock_history`` (``history``): the reads of the last 90 days + the newest before them;
  a listing with variations is its model rows, one without is its item row;
- ``shopee_order_lines``: units and orders per variation per day over the last 90 days
  (cancelled lines left out), resolved to the variation like the analytics engine does (stored
  variation id, else the catalogue variation with that seller SKU, else the listing's only one);
- the catalogue (``shopee_analytics.loaders.load_context``): names, the listing status and the
  seller's SKU code (``platform_items.seller_sku``: the model / parent SKU the Connector's product
  list read posts as ``item_catalog`` beside ``item_snapshot``);
- approved and executed recommendation cards on the product: their stored result
  (``result_store.measured_block``: Δ orders P50 / day over the result's own dates). A card naming
  variations (``inputs.variations``) adds to those; a whole-product card is split over the
  product's variations by their share of its orders. Units per order = the variation's own.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import STATUS_APPROVED, STATUS_EXECUTED
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.stock_alert import stock_basis as sb
from juli_backend.services.stock_alert.eligibility import SkuFacts
from juli_backend.services.stock_alert.forecast import HISTORY_DAYS, CardEffect, base_rate
from juli_backend.services.stock_alert.settings import sku_key

CANCELLED = "cancelled"
#: ``execution_state`` of an approved card whose page nobody has filled yet ("Chờ điền").
STATE_WAITING = "cho_dien"
INACTIVE_WORDS = ("deleted", "banned", "hidden", "xoá", "xóa", "khoá", "khóa", "ẩn")


@dataclass
class SkuData:
    item_id: str
    model_id: str
    reads: list[sb.Read] = field(default_factory=list)
    listing_status: str | None = None
    units: dict[date, float] = field(default_factory=lambda: defaultdict(float))
    orders: dict[date, set[str]] = field(default_factory=lambda: defaultdict(set))
    #: (ordered_at, order_ref, qty) of every line, for "units since the read"
    lines: list[tuple[datetime, str, int]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return sku_key(self.item_id, self.model_id)

    @property
    def last(self) -> sb.Read | None:
        return max(self.reads, key=lambda r: r.read_at) if self.reads else None

    def orders_between(self, start: date, end: date) -> int:
        refs: set[str] = set()
        for d, rs in self.orders.items():
            if start <= d <= end:
                refs |= rs
        return len(refs)

    def units_per_order(self) -> float:
        n = self.orders_between(date.min, date.max)
        return sum(self.units.values()) / n if n else 1.0

    def since(self, read_at: datetime) -> tuple[int, int]:
        """(units, orders) placed after ``read_at``."""
        mine = [(ref, q) for at, ref, q in self.lines if at > read_at]
        return sum(q for _, q in mine), len({ref for ref, _ in mine})


def _variation_of(catalog: Catalog, item_id: str, line: Any) -> str:
    if line.variation_id:
        return str(line.variation_id)
    info = catalog.items.get(item_id)
    variations = info.variations if info else ()
    wanted = {c for c in (line.variation_sku, line.sku) if c}
    hits = [v for v in variations if v.seller_sku and v.seller_sku in wanted]
    if len(hits) == 1:
        return hits[0].variation_id
    if len(variations) == 1:
        return variations[0].variation_id
    return ""


def _inactive(status: str | None) -> bool:
    word = (status or "").strip().lower()
    return any(w in word for w in INACTIVE_WORDS)


async def load_skus(
    session: AsyncSession, shop_id: uuid.UUID, catalog: Catalog, today: date
) -> dict[str, SkuData]:
    """Every variation the stock history knows, with its reads and order lines."""
    start = today - timedelta(days=HISTORY_DAYS)
    hist = (
        (
            await session.execute(
                select(ShopeeStockHistory)
                .where(ShopeeStockHistory.shop_id == shop_id)
                .order_by(ShopeeStockHistory.read_at)
            )
        )
        .scalars()
        .all()
    )
    with_models = {h.item_id for h in hist if h.model_id}
    skus: dict[str, SkuData] = {}
    for h in hist:
        if not h.model_id and h.item_id in with_models:
            continue  # the item row of a listing with variations is not a SKU of its own
        if sb.local_day(h.read_at) < start - timedelta(days=HISTORY_DAYS):
            continue
        key = sku_key(h.item_id, h.model_id)
        sku = skus.setdefault(key, SkuData(h.item_id, h.model_id))
        sku.reads.append(sb.Read(h.read_at, sb.basis(h.sellable, h.available)))
        sku.listing_status = h.listing_status
    for key, sku in skus.items():
        info = catalog.items.get(sku.item_id)
        status = None if info is None else info.status
        if sku.model_id and info is not None:
            v = next((v for v in info.variations if v.variation_id == sku.model_id), None)
            status = (v.status if v is not None and v.status else None) or status
        if _inactive(status):
            sku.listing_status = "deleted"
    lines = (
        (
            await session.execute(
                select(ShopeeOrderLine).where(
                    ShopeeOrderLine.shop_id == shop_id,
                    ShopeeOrderLine.ordered_at >= datetime.combine(start, datetime.min.time()),
                )
            )
        )
        .scalars()
        .all()
    )
    for ln in lines:
        if ln.status == CANCELLED or ln.qty <= 0:
            continue
        item = catalog.resolve(ln.item_id, ln.sku, ln.variation_sku)
        model = _variation_of(catalog, item, ln)
        target = skus.get(sku_key(item, model)) or skus.get(item)  # a listing without variations
        if target is None:
            continue
        day = ln.ordered_at.date()
        target.units[day] += ln.qty
        target.orders[day].add(ln.order_ref)
        target.lines.append((ln.ordered_at, ln.order_ref, int(ln.qty)))
    return skus


# ------------------------------------------------------------------------------- cards


@dataclass(frozen=True)
class CardWindow:
    product_id: str
    start: date
    end: date
    orders_per_day: float
    #: seller SKUs the card names (``inputs.variations``); empty = the whole product
    skus: tuple[str, ...] = ()


def card_windows(cards: Sequence[Mapping[str, Any]], today: date) -> list[CardWindow]:
    """The approved / running cards' windows from their stored results (pure)."""
    from juli_backend.services.shopee_recommendations import result_store

    out: list[CardWindow] = []
    for card in cards:
        products = (card.get("scope") or {}).get("product_ids") or []
        block = result_store.measured_block(card)
        dates = ((block or {}).get("own") or {}).get("dates") or {}
        per_day = result_store.per_day(block, "orders")
        if not products or per_day is None or not dates.get("from") or not dates.get("to"):
            continue
        start, end = date.fromisoformat(dates["from"]), date.fromisoformat(dates["to"])
        if end < today:
            continue
        skus = tuple(
            str(v["sku"])
            for v in (card.get("inputs") or {}).get("variations") or []
            if isinstance(v, Mapping) and v.get("sku")
        )
        for product in products:
            out.append(CardWindow(str(product), start, end, float(per_day), skus))
    return out


async def load_card_windows(
    session: AsyncSession, shop_id: uuid.UUID, today: date, now: datetime | None = None
) -> list[CardWindow]:
    """Windows of the cards that are running (executed) or filled; an approved card still in
    "Chờ điền" has not started, so it adds nothing."""
    from juli_backend.services.shopee_recommendations import execution_state, store

    rows = await store.list_cards(session, shop_id, statuses=[STATUS_APPROVED, STATUS_EXECUTED])
    waiting = {
        str(c["card_id"])
        for c in (
            await execution_state.execution_states(
                session, shop_id, now=now or datetime.combine(today, datetime.min.time())
            )
        )["cards"]
        if c["state"] == STATE_WAITING
    }
    return card_windows(
        [card for p, card in rows if not (p.status == STATUS_APPROVED and str(p.id) in waiting)],
        today,
    )


async def load_orders_through(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The day of the shop's newest order line (any status); None with no order data at all."""
    newest = await session.scalar(
        select(func.max(ShopeeOrderLine.ordered_at)).where(ShopeeOrderLine.shop_id == shop_id)
    )
    return None if newest is None else newest.date()


def _seller_sku(catalog: Catalog, item_id: str, model_id: str) -> str | None:
    info = catalog.items.get(item_id)
    if info is None:
        return None
    if not model_id:
        return info.seller_sku
    v = next((v for v in info.variations if v.variation_id == model_id), None)
    return None if v is None else v.seller_sku


def effects_for(
    sku: SkuData,
    siblings: Sequence[SkuData],
    windows: Sequence[CardWindow],
    catalog: Catalog,
    today: date,
) -> tuple[list[CardEffect], list[date]]:
    """The card effects on one variation and the end days of the cards on its product."""
    effects: list[CardEffect] = []
    ends: list[date] = []
    recent = today - timedelta(days=30)
    for w in windows:
        if w.product_id != sku.item_id:
            continue
        ends.append(w.end)
        if w.skus:
            mine = _seller_sku(catalog, sku.item_id, sku.model_id)
            if mine is None or mine not in w.skus:
                continue
            named = [s for s in siblings if _seller_sku(catalog, s.item_id, s.model_id) in w.skus]
            share = 1.0 / max(len(named), 1)
        else:
            counts = {s.key: s.orders_between(recent, today) for s in siblings}
            if not any(counts.values()):
                counts = {s.key: s.orders_between(date.min, date.max) for s in siblings}
            total = sum(counts.values())
            share = counts.get(sku.key, 0) / total if total else 1.0 / max(len(siblings), 1)
        units = w.orders_per_day * share * sku.units_per_order()
        if units > 0:
            effects.append(CardEffect(max(w.start, today), w.end, units))
    return effects, ends


# ------------------------------------------------------------------------------- facts


@dataclass(frozen=True)
class SkuState:
    facts: SkuFacts
    stock: sb.StockNow | None
    last_read_at: datetime | None = None


def facts_of(
    skus: Mapping[str, SkuData],
    catalog: Catalog,
    windows: Sequence[CardWindow],
    today: date,
    now: datetime,
    orders_through: date | None = None,
) -> list[SkuState]:
    """The facts of every variation with a usable stock read; ``stock`` None = no usable read.
    Days after ``orders_through`` (the shop's newest order line) are missing, not zero-sale."""
    by_item: dict[str, list[SkuData]] = defaultdict(list)
    for s in skus.values():
        by_item[s.item_id].append(s)
    out: list[SkuState] = []
    start = today - timedelta(days=HISTORY_DAYS)
    for sku in skus.values():
        last = sku.last
        units_since, orders_since = sku.since(last.read_at) if last else (0, 0)
        now_stock = sb.stock_now(last, now, units_since=units_since, orders_since=orders_since)
        zeros = sb.zero_days(sku.reads, start, today - timedelta(days=1))
        if orders_through is not None:
            zeros |= {
                orders_through + timedelta(days=n) for n in range(1, (today - orders_through).days)
            }  # no order data those days: out of the rate, numerator and denominator
        orders_30 = sku.orders_between(today - timedelta(days=30), today - timedelta(days=1))
        firsts = [min(sku.units)] if sku.units else []
        if sku.reads:
            firsts.append(sb.local_day(min(r.read_at for r in sku.reads)))
        first = min(firsts) if firsts else today
        effects, ends = effects_for(sku, by_item[sku.item_id], windows, catalog, today)
        zero_since = sb.zero_since(sku.reads)
        if zero_since is None and now_stock is not None and now_stock.stock == 0:
            zero_since = today  # the orders since the read took it to 0
        info = catalog.items.get(sku.item_id)
        variation = None
        if info is not None and sku.model_id:
            v = next((v for v in info.variations if v.variation_id == sku.model_id), None)
            variation = None if v is None else v.name
        code = _seller_sku(catalog, sku.item_id, sku.model_id) or None
        if code and variation:
            others = [_seller_sku(catalog, o.item_id, o.model_id) for o in by_item[sku.item_id]]
            if others.count(code) > 1 or (info is not None and info.seller_sku == code):
                code = None  # the same code on other variations or the parent: the name tells apart
        facts = SkuFacts(
            item_id=sku.item_id,
            model_id=sku.model_id,
            product_name=catalog.name(sku.item_id),
            variation_name=variation,
            listing_status=sku.listing_status,
            orders_30=orders_30,
            orders_total=sku.orders_between(start, today),
            history_days=(today - first).days,
            stock=0 if now_stock is None else now_stock.stock,
            base=base_rate(
                sku.units, today, zero_stock_days=zeros, orders_30=orders_30, first_day=first
            ),
            zero_since=zero_since,
            effects=tuple(effects),
            card_ends=tuple(ends),
            sku_code=code,
            orders_through=orders_through,
        )
        out.append(SkuState(facts, now_stock, last.read_at if last else None))
    return out


async def load_states(
    session: AsyncSession, shop_id: uuid.UUID, today: date, now: datetime
) -> tuple[list[SkuState], Catalog]:
    from juli_backend.services.shopee_analytics.loaders import load_context

    ctx = await load_context(session, shop_id)
    skus = await load_skus(session, shop_id, ctx.catalog, today)
    windows = await load_card_windows(session, shop_id, today, now) if skus else []
    through = await load_orders_through(session, shop_id)
    return facts_of(skus, ctx.catalog, windows, today, now, through), ctx.catalog


__all__ = [
    "CardWindow",
    "SkuData",
    "SkuState",
    "card_windows",
    "effects_for",
    "facts_of",
    "load_orders_through",
    "load_skus",
    "load_states",
]
