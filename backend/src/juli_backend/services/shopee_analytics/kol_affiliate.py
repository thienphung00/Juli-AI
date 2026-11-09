"""KOL lines from the Connector's affiliate conversion report (migration 122, P96, 2026-11-06).

Phân tích › KOL used to read only the order export's lines that the report had MARKED as affiliate,
so a KOL sale the export did not hold yet (ORY's export ended 04/11) never showed. ``merge`` gives
the KOL model every affiliate line of the period, one source per order:

- an order the export holds keeps the EXPORT's line (real fees, real prices); if the export line was
  written after the report and so carries no affiliate mark, it is marked here from the report line
  (KOL, channel, commission) -- in memory, for the KOL model only;
- an order the export does not hold is built from the report line through the same
  ``to_shop_lines`` as the export (item, variation, pack, cost key, VAT); its fees are estimated by
  the fee formula (``actual_fees`` None), as for any export line without fees.

Never counted twice: report lines of an order in the export are dropped. Lines the platform's fraud
check did not pass (``valid`` False) are left out. Only the creator's public handle is read; the
table holds no buyer data. Nothing here touches the shop totals: the merged view is the KOL
model's own.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_profit import ShopeeAffiliateLine
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.engine import (
    KolTag,
    RawLine,
    ShopLine,
    build_fee_context,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.loaders import ShopContext
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import OrderStatus

PLATFORM = "shopee"


@dataclass(frozen=True)
class AffiliateLine:
    """A ``shopee_affiliate_lines`` row, detached from the ORM."""

    order_ref: str
    line_no: int
    item_id: str
    model_id: str
    price: Decimal | None
    qty: int | None
    order_value: Decimal | None
    refund_amount: Decimal | None
    commission: Decimal | None
    valid: bool | None
    order_status: str | None
    ordered_at: datetime
    completed_at: datetime | None
    kol_key: str | None
    kol_handle: str | None
    channel: str | None
    campaign_type: str | None
    mcn: bool | None


async def load_affiliate_lines(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> list[AffiliateLine]:
    """The shop's stored affiliate lines ordered within ``start`` .. ``end`` (inclusive)."""
    lo = datetime.combine(start, time.min)
    hi = datetime.combine(end + timedelta(days=1), time.min)
    rows = await session.execute(
        select(ShopeeAffiliateLine)
        .where(
            ShopeeAffiliateLine.shop_id == shop_id,
            ShopeeAffiliateLine.platform == PLATFORM,
            ShopeeAffiliateLine.ordered_at >= lo,
            ShopeeAffiliateLine.ordered_at < hi,
        )
        .order_by(ShopeeAffiliateLine.ordered_at, ShopeeAffiliateLine.order_ref)
    )
    return [
        AffiliateLine(
            order_ref=r.order_ref,
            line_no=r.line_no,
            item_id=r.item_id,
            model_id=r.model_id or "",
            price=r.price,
            qty=r.qty,
            order_value=r.order_value,
            refund_amount=r.refund_amount,
            commission=r.commission,
            valid=r.valid,
            order_status=r.order_status,
            ordered_at=r.ordered_at,
            completed_at=r.completed_at,
            kol_key=r.kol_key,
            kol_handle=r.kol_handle,
            channel=r.affiliate_channel,
            campaign_type=r.affiliate_campaign_type,
            mcn=r.affiliate_mcn,
        )
        for r in rows.scalars()
    ]


def status_of(line: AffiliateLine) -> OrderStatus:
    """The report's order status as the profit engine's: only a finished order carries profit."""
    text = (line.order_status or "").casefold()
    if any(w in text for w in ("hủy", "huỷ", "cancel")):
        return OrderStatus.CANCELLED
    refunded = line.refund_amount is not None and line.refund_amount > ZERO
    if refunded or any(w in text for w in ("hoàn tiền", "trả hàng", "refund", "return")):
        return OrderStatus.REFUNDED_ACCEPTED
    if line.completed_at is not None or any(w in text for w in ("hoàn thành", "complete")):
        return OrderStatus.DELIVERED
    return OrderStatus.IN_TRANSIT


def _unit_price(line: AffiliateLine) -> Decimal:
    qty = line.qty or 0
    if line.order_value is not None and qty > 0:
        return (line.order_value / qty).quantize(Decimal("0.01"))
    return line.price if line.price is not None else ZERO


def _raw(line: AffiliateLine) -> RawLine:
    status = status_of(line)
    deal = _unit_price(line)
    return RawLine(
        order_ref=line.order_ref,
        line_no=line.line_no,
        ordered_at=line.ordered_at,
        # to_shop_lines keeps paid lines only; a cancelled order never was a sale.
        paid_at=None if status is OrderStatus.CANCELLED else line.ordered_at,
        status=status.value,
        item_id=line.item_id,
        sku=None,
        variation_sku=None,
        qty=line.qty or 0,
        original_price=line.price if line.price is not None else deal,
        deal_price=deal,
        shop_voucher_share=ZERO,
        bundle_discount=ZERO,
        promo_kind="none",
        voucher_code=None,
        affiliate=True,
        commission=line.commission,
        fee_fixed=None,
        fee_service=None,
        fee_payment=None,
        fee_other=None,
        buyer_shipping_fee=None,
        bank_promo=None,
        ad_attributed=None,
        kol_key=line.kol_key,
        kol_handle=line.kol_handle,
        affiliate_channel=line.channel,
        affiliate_campaign_type=line.campaign_type,
        affiliate_mcn=line.mcn,
        variation_id=line.model_id,
    )


def _tag(line: AffiliateLine) -> KolTag | None:
    if not line.kol_key:
        return None
    return KolTag(line.kol_key, line.kol_handle or "", line.channel, line.campaign_type, line.mcn)


def _mark(sl: ShopLine, aff: list[AffiliateLine]) -> ShopLine:
    """An export line of an affiliate order that carries no mark yet: mark it from the report."""
    if sl.line.affiliate:
        return sl
    same = [a for a in aff if a.item_id == sl.product_id] or (aff if len(aff) == 1 else [])
    if not same:
        return sl
    first = same[0]
    commission = (
        sum((a.commission for a in same if a.commission is not None), ZERO)
        if any(a.commission is not None for a in same)
        else None
    )
    return replace(
        sl,
        line=replace(sl.line, affiliate=True, commission=commission),
        kol=sl.kol or _tag(first),
    )


def merge(view: PeriodView, ctx: ShopContext, lines: list[AffiliateLine]) -> PeriodView:
    """The KOL model's view: the export's lines (affiliate orders marked) plus every report line of
    an order the export does not hold. Costs and fees are recomputed over the merged lines."""
    usable = [a for a in lines if a.valid is not False]
    if not usable:
        return view
    by_order: dict[str, list[AffiliateLine]] = defaultdict(list)
    for a in usable:
        by_order[a.order_ref].append(a)
    in_export = {sl.line.order_id for sl in view.lines}
    marked = [
        _mark(sl, by_order[sl.line.order_id]) if sl.line.order_id in by_order else sl
        for sl in view.lines
    ]
    extra_raw = [_raw(a) for a in usable if a.order_ref not in in_export]
    extra = to_shop_lines(extra_raw, ctx.catalog, ctx.rules) if extra_raw else []
    if not extra and marked == view.lines:
        return view
    merged = [*marked, *extra]
    item_ids = sorted({sl.product_id for sl in merged})
    return replace(
        view,
        lines=merged,
        costs=resolve_costs(merged, ctx.rules),
        fees=build_fee_context(item_ids, ctx.catalog, ctx.db_schedules(item_ids)),
    )
