"""C9 (E150): the order lines to COUNT when a stored combo holds its parent beside its own lines.

A Connector answer with a collapsed combo (one line, the combo's whole price) posted after the
combo's split lines replaced line 0 only: the order then held the combo total AND the other split
lines. The stored rows are never deleted or changed here; the reader gets copies with the combo's
real content, only when the evidence is certain:

1. the sibling line still names the post that wrote it; that post (``ingest_raw_payloads``) holds
   the whole split, adding up to the collapsed line's total (and, for a settled order, to the
   settlement's goods total): line 0 takes back its own quantity and price; else
2. the settlement's goods total equals the collapsed line plus the non-combo lines, the siblings
   are the same item in a combo WITH a combo discount, and what is left for line 0 is a whole
   number of the siblings' one unit price.

Anything else is returned as stored (``order_consistency`` shows the mismatch per day).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_EXTENSION, IngestRawPayload
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine

BUNDLE = "bundle"
PLATFORM_SHOPEE = "shopee"
#: VND a total may miss by (the split rounds to cents).
TOLERANCE = Decimal(1)
_CONTENT = ("original_price", "deal_price", "seller_subsidy", "bundle_discount")


def _total(lines: Iterable[Any]) -> Decimal:
    return sum((Decimal(ln.deal_price) * ln.qty for ln in lines), Decimal(0))


def _same(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= TOLERANCE


def collapsed_parent(lines: Sequence[ShopeeOrderLine]) -> ShopeeOrderLine | None:
    """The one line of an order that MAY be a combo's collapsed parent: a Connector combo line
    with no combo discount beside combo lines of the same item that have one."""
    bundles = [ln for ln in lines if ln.promo_kind == BUNDLE and ln.source == SOURCE_EXTENSION]
    if len(bundles) < 2 or bundles[0].platform != PLATFORM_SHOPEE:
        return None
    parents = [ln for ln in bundles if ln.bundle_discount == 0]
    if len(parents) != 1 or parents[0].qty <= 0:
        return None
    siblings = [ln for ln in bundles if ln is not parents[0]]
    if any(ln.item_id != parents[0].item_id for ln in siblings):
        return None
    return parents[0] if _total(siblings) < _total(parents) else None


def _copy(line: ShopeeOrderLine, **changed: Any) -> ShopeeOrderLine:
    """A detached copy: never added to a session, so the stored row is not touched."""
    values = {c.key: getattr(line, c.key) for c in ShopeeOrderLine.__table__.columns}
    return ShopeeOrderLine(**{**values, **changed})


def _posted(payload: Any, order_ref: str) -> dict[int, dict[str, Any]]:
    rows = payload.get("rows") if isinstance(payload, dict) else None
    return {
        int(r.get("line_no") or 0): r
        for r in rows or []
        if isinstance(r, dict) and r.get("order_ref") == order_ref
    }


def from_payload(
    lines: Sequence[ShopeeOrderLine],
    parent: ShopeeOrderLine,
    payload: Any,
    product_price: Decimal | None,
) -> ShopeeOrderLine | None:
    """Line 0 as the siblings' own post had it, or None when that post does not prove it."""
    posted = _posted(payload, parent.order_ref)
    if set(posted) != {ln.line_no for ln in lines}:
        return None
    own = posted[parent.line_no]
    try:
        amounts = {
            no: Decimal(str(r["deal_price"])) * int(Decimal(str(r["qty"])))
            for no, r in posted.items()
        }
        combo = sum(
            (amounts[no] for no, r in posted.items() if r.get("promo_kind") == BUNDLE), Decimal(0)
        )
        values = {name: Decimal(str(own.get(name) or 0)) for name in _CONTENT}
        qty = int(Decimal(str(own["qty"])))
    except (KeyError, ArithmeticError, ValueError):
        return None
    named = own.get("variation_sku") or own.get("sku")
    if own.get("promo_kind") != BUNDLE or not named or qty <= 0:
        return None
    if not _same(combo, _total([parent])):
        return None
    if product_price is not None and not _same(sum(amounts.values(), Decimal(0)), product_price):
        return None
    return _copy(parent, qty=qty, **values)


def from_settlement(
    lines: Sequence[ShopeeOrderLine], parent: ShopeeOrderLine, product_price: Decimal | None
) -> ShopeeOrderLine | None:
    """Line 0 = the combo total less its siblings, when the settlement proves the total and the
    rest is whole units of the siblings' one price; else None (left as stored)."""
    if product_price is None:
        return None
    plain = [ln for ln in lines if ln.promo_kind != BUNDLE]
    siblings = [ln for ln in lines if ln.promo_kind == BUNDLE and ln is not parent]
    if not _same(_total([parent]) + _total(plain), product_price):
        return None
    units = {
        (Decimal(ln.deal_price), Decimal(ln.bundle_discount) / ln.qty) for ln in siblings if ln.qty
    }
    if len(units) != 1:
        return None
    ((price, discount),) = units
    rest = _total([parent]) - _total(siblings)
    if price <= 0 or rest <= 0 or rest % price != 0:
        return None
    qty = int(rest / price)
    return _copy(
        parent,
        qty=qty,
        deal_price=price,
        original_price=price,
        seller_subsidy=Decimal(0),
        bundle_discount=discount * qty,
    )


async def counted_lines(
    session: AsyncSession, shop_id: uuid.UUID, rows: Sequence[ShopeeOrderLine]
) -> list[ShopeeOrderLine]:
    """``rows`` (whole orders) with each proven collapsed combo replaced by a copy holding its
    real content. No query is made when no order looks like one."""
    out = list(rows)
    by_order: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(out):
        by_order[row.order_ref].append(i)
    suspects: dict[str, tuple[list[int], ShopeeOrderLine]] = {}
    for ref, idxs in by_order.items():
        if len(idxs) < 2:
            continue
        parent = collapsed_parent([out[i] for i in idxs])
        if parent is not None:
            suspects[ref] = (idxs, parent)
    if not suspects:
        return out
    prices = await _product_prices(session, shop_id, sorted(suspects))
    raw_ids = {
        out[i].raw_payload_id
        for idxs, parent in suspects.values()
        for i in idxs
        if out[i].raw_payload_id not in (None, parent.raw_payload_id)
    }
    payloads: dict[uuid.UUID, Any] = {}
    if raw_ids:
        found = await session.execute(
            select(IngestRawPayload.id, IngestRawPayload.payload).where(
                IngestRawPayload.shop_id == shop_id, IngestRawPayload.id.in_(raw_ids)
            )
        )
        payloads = {raw_id: payload for raw_id, payload in found}
    for ref, (idxs, parent) in suspects.items():
        lines = [out[i] for i in idxs]
        fixed = _resolve(lines, parent, payloads, prices.get(ref))
        if fixed is not None:
            out[next(i for i in idxs if out[i] is parent)] = fixed
    return out


def _resolve(
    lines: Sequence[ShopeeOrderLine],
    parent: ShopeeOrderLine,
    payloads: Mapping[uuid.UUID, Any],
    product_price: Decimal | None,
) -> ShopeeOrderLine | None:
    sources = [
        ln.raw_payload_id
        for ln in lines
        if ln.promo_kind == BUNDLE and ln is not parent and ln.raw_payload_id in payloads
    ]
    if sources and sources[0] is not None:
        fixed = from_payload(lines, parent, payloads[sources[0]], product_price)
        if fixed is not None:
            return fixed
    return from_settlement(lines, parent, product_price)


async def _product_prices(
    session: AsyncSession, shop_id: uuid.UUID, refs: Sequence[str]
) -> dict[str, Decimal]:
    found = await session.execute(
        select(ShopeeOrderIncome.order_ref, ShopeeOrderIncome.product_price).where(
            ShopeeOrderIncome.shop_id == shop_id,
            ShopeeOrderIncome.platform == PLATFORM_SHOPEE,
            ShopeeOrderIncome.order_ref.in_(refs),
            ShopeeOrderIncome.product_price.is_not(None),
        )
    )
    return {ref: price for ref, price in found}
