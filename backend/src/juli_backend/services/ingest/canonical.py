"""The platform-neutral canonical rows of P101 layer 3 (T5), and the writer contract.

P101 has four layers: raw landing -> one mapper per platform -> canonical tables -> computed
tables. This module is layer 3's SHAPE only: two frozen dataclasses (:class:`OrderLine`,
:class:`OrderSettlement`), the :class:`CanonicalWriter` protocol a DB writer implements, the
precedence rule every writer applies, and :func:`profit_order_lines`, which turns canonical rows
into the one compute input (:class:`~juli_backend.services.shopee_profit.order_profit.OrderLine`).

Pure: stdlib, ``Decimal`` and the pure ``shopee_profit`` value types. No SQLAlchemy, no session,
no I/O (a unit test parses this file's imports and fails on any ORM import). The DB writer arrives
with T5 (S1), when ``shopee_order_lines`` / ``shopee_order_income`` are renamed to ``order_lines`` /
``order_settlements``; until then the canonical tables ARE the Shopee-named ones, column for column.

Field -> current Shopee column (T5 renames mechanically from this table; everything not listed
under "Renamed" or "New" keeps its name):

``OrderLine`` -> ``shopee_order_lines``

=========================  ===============================  =====================================
canonical field            current column                   note
=========================  ===============================  =====================================
shop_id, platform,         same                             key (unique with line_no)
order_ref, line_no
ordered_at, status,        same                             status = ``OrderStatus`` vocabulary
paid_at, completed_at                                       (unknown values kept raw, see mapper)
item_id, variation_id,     same
variation_name, sku,
variation_sku
qty, returned_qty          same
original_price,            same                             per unit
deal_price
shop_voucher_share,        same                             line totals (x qty)
platform_voucher_share,
bundle_discount,
seller_subsidy
**platform_subsidy**       **shopee_subsidy**               Renamed
promo_kind, voucher_code,  same
buyer_shipping_fee,
bank_promo
traffic_source,            same
ad_attributed, affiliate,
commission, kol_key,
kol_handle,
affiliate_channel,
affiliate_campaign_type,
affiliate_mcn
fee_fixed, fee_service,    same                             NULL = not stated, never 0
fee_payment, fee_other,
payout
source, source_version,    same                             lines carry no ``source_rank`` column:
raw_payload_id                                              their rank is ``SOURCE_RANK[source]``
=========================  ===============================  =====================================

``OrderSettlement`` -> ``shopee_order_income``

=========================  ===============================  =====================================
canonical field            current column                   note
=========================  ===============================  =====================================
shop_id, platform,         same                             key
order_ref
ordered_on, paid_on        same                             platform calendar day (VN)
payout, product_price,     same                             payout signed; costs positive
refund_amount
fee_fixed, fee_service,    same                             Shopee: fee_service INCLUDES fee_infra
fee_infra,                                                  and fee_voucher_xtra (never add them)
fee_voucher_xtra,
fee_payment, fee_piship,
fee_nttd,
affiliate_commission,
transaction_fee_rate
**fee_other**              (none)                           New: fees with no canonical column
                                                            (TikTok SFP, affiliate ads ...); the
                                                            per-fee split stays in the raw payload
ship_actual_cost           same
**ship_platform_subsidy**  **ship_shopee_subsidy**          Renamed
ship_buyer_paid,           same
ship_piship_refund,
ship_seller_support,
net_shipping_cost,
return_ship_refund,
return_ship_failed,
lost_compensation
seller_voucher_borne,      same
seller_coin_borne,
trade_in_bonus_seller
vat_withheld, pit_withheld same                             as reported; deducted (COST_TAX)
source, source_rank,       same
source_version,
raw_payload_id
=========================  ===============================  =====================================
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from juli_backend.services.shopee_profit.income import IncomeOrder, split_amount, split_income
from juli_backend.services.shopee_profit.order_profit import OrderLine as ProfitLine
from juli_backend.services.shopee_profit.order_profit import OrderStatus, PromoKind

ZERO = Decimal(0)
#: The day boundary of every metric (P101 T6): midnight Asia/Ho_Chi_Minh.
DAY_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
#: Fee code of ``fee_other`` in a line's income fees (beside ``income.FEE_CODES``).
FEE_OTHER = "phi_khac"

#: canonical field -> current Shopee column, for the two fields T5 renames.
LINE_RENAMES: dict[str, str] = {"platform_subsidy": "shopee_subsidy"}
SETTLEMENT_RENAMES: dict[str, str] = {"ship_platform_subsidy": "ship_shopee_subsidy"}
#: Canonical settlement fields with no Shopee column yet (T5 adds them).
SETTLEMENT_NEW_FIELDS: frozenset[str] = frozenset({"fee_other"})

LINE_KEY: tuple[str, ...] = ("shop_id", "platform", "order_ref", "line_no")
SETTLEMENT_KEY: tuple[str, ...] = ("shop_id", "platform", "order_ref")
#: Line fields a later post that leaves them NULL never erases (as ``writers.write_order_lines``).
LINE_KEEP_WHEN_NULL: tuple[str, ...] = (
    "fee_fixed",
    "fee_service",
    "fee_payment",
    "fee_other",
    "payout",
    "completed_at",
    "paid_at",
    "variation_name",
)
#: The line fee fields whose sum is the compute input's ``actual_fees``.
LINE_FEE_FIELDS: tuple[str, ...] = ("fee_fixed", "fee_service", "fee_payment", "fee_other")

_STATUS: dict[str, OrderStatus] = {s.value: s for s in OrderStatus}
_PROMO_KIND: dict[str, PromoKind] = {
    "discount": PromoKind.PROMOTION,
    "flash_sale": PromoKind.FLASH_SALE,
}


@dataclass(frozen=True, kw_only=True)
class OrderLine:
    """One order line, any platform. Money is VND; NULL (``None``) = the source did not state it,
    never 0. No buyer field exists, by design."""

    shop_id: uuid.UUID
    platform: str
    order_ref: str
    line_no: int
    ordered_at: datetime
    status: str
    paid_at: datetime | None = None
    completed_at: datetime | None = None
    item_id: str
    variation_id: str
    variation_name: str | None = None
    sku: str | None = None
    variation_sku: str | None = None
    qty: int
    returned_qty: int = 0
    original_price: Decimal
    deal_price: Decimal
    shop_voucher_share: Decimal = ZERO
    platform_voucher_share: Decimal = ZERO
    bundle_discount: Decimal = ZERO
    seller_subsidy: Decimal = ZERO
    platform_subsidy: Decimal = ZERO
    promo_kind: str = "none"
    voucher_code: str | None = None
    buyer_shipping_fee: Decimal | None = None
    bank_promo: Decimal | None = None
    traffic_source: str | None = None
    ad_attributed: bool | None = None
    affiliate: bool = False
    commission: Decimal | None = None
    kol_key: str | None = None
    kol_handle: str | None = None
    affiliate_channel: str | None = None
    affiliate_campaign_type: str | None = None
    affiliate_mcn: bool | None = None
    fee_fixed: Decimal | None = None
    fee_service: Decimal | None = None
    fee_payment: Decimal | None = None
    fee_other: Decimal | None = None
    payout: Decimal | None = None
    source: str
    source_version: str
    raw_payload_id: uuid.UUID | None = None

    @property
    def key(self) -> tuple[object, ...]:
        return (self.shop_id, self.platform, self.order_ref, self.line_no)

    @property
    def buyer_paid(self) -> Decimal:
        """``deal_price * qty - shop voucher - combo``: the value an order's amounts split by."""
        return self.deal_price * self.qty - self.shop_voucher_share - self.bundle_discount


@dataclass(frozen=True, kw_only=True)
class OrderSettlement:
    """What the platform actually charged and paid for one order. Every cost is a POSITIVE amount
    the seller bore (a reversal is negative); ``payout`` is signed. ``None`` = not stated.

    ``vat_withheld`` / ``pit_withheld`` are the tax the platform's own settlement data REPORTS as
    withheld, stored exactly as reported; :func:`profit_order_lines` passes them through so profit
    deducts them (``COST_TAX``), as on Shopee (owner 2026-11-16). Juli never declares or guesses
    a tax rate: no reported amount, no tax."""

    shop_id: uuid.UUID
    platform: str
    order_ref: str
    ordered_on: date | None = None
    paid_on: date | None = None
    payout: Decimal | None = None
    product_price: Decimal | None = None
    refund_amount: Decimal | None = None
    fee_fixed: Decimal | None = None
    fee_service: Decimal | None = None
    fee_infra: Decimal | None = None
    fee_voucher_xtra: Decimal | None = None
    fee_payment: Decimal | None = None
    fee_piship: Decimal | None = None
    fee_nttd: Decimal | None = None
    affiliate_commission: Decimal | None = None
    transaction_fee_rate: Decimal | None = None
    fee_other: Decimal | None = None
    ship_actual_cost: Decimal | None = None
    ship_platform_subsidy: Decimal | None = None
    ship_buyer_paid: Decimal | None = None
    ship_piship_refund: Decimal | None = None
    ship_seller_support: Decimal | None = None
    net_shipping_cost: Decimal | None = None
    return_ship_refund: Decimal | None = None
    return_ship_failed: Decimal | None = None
    lost_compensation: Decimal | None = None
    seller_voucher_borne: Decimal | None = None
    seller_coin_borne: Decimal | None = None
    trade_in_bonus_seller: Decimal | None = None
    # Stored as reported; never an input of profit (see the class docstring).
    vat_withheld: Decimal | None = None
    pit_withheld: Decimal | None = None
    source: str
    source_rank: int
    source_version: str
    raw_payload_id: uuid.UUID | None = None

    @property
    def key(self) -> tuple[object, ...]:
        return (self.shop_id, self.platform, self.order_ref)


#: Settlement fields a later post that leaves them NULL never erases (as ``income.py``).
SETTLEMENT_STATED: tuple[str, ...] = tuple(
    f.name
    for f in fields(OrderSettlement)
    if f.name not in (*SETTLEMENT_KEY, "source", "source_rank", "source_version", "raw_payload_id")
)


class CanonicalWriter(Protocol):
    """Writes canonical rows (layer 3). The DB implementation arrives with T5.

    Contract, for both methods:

    - idempotent on the key (lines: ``LINE_KEY``; settlements: ``SETTLEMENT_KEY``): writing the
      same rows twice stores the same state and returns the same count;
    - precedence: a row replaces the stored one when its rank is the same or higher
      (:func:`replaces`; equal rank = the latest write wins); a lower rank never overwrites.
      A settlement's rank is ``source_rank``; a line's is ``SOURCE_RANK[source]`` (it has no
      rank column), the rule ``gateway._upsert`` already applies;
    - on a replace, a field the incoming row leaves ``None`` keeps the stored value for the
      ``*_KEEP_WHEN_NULL`` / ``SETTLEMENT_STATED`` fields (:func:`merge_line`,
      :func:`merge_settlement`), so a later partial read never erases a stated amount;
    - every row's ``shop_id`` / ``platform`` must equal the call's (else ``ValueError``);
    - returns the number of rows inserted or replaced (rows a higher rank kept are not counted).
    """

    async def upsert_order_lines(
        self, shop_id: uuid.UUID, platform: str, lines: Sequence[OrderLine]
    ) -> int: ...

    async def upsert_settlements(
        self, shop_id: uuid.UUID, platform: str, rows: Sequence[OrderSettlement]
    ) -> int: ...


def replaces(stored_rank: int, incoming_rank: int) -> bool:
    """Whether a row of ``incoming_rank`` replaces a stored row of ``stored_rank``: same or
    higher wins (equal = latest), lower never overwrites. The SQL writers say the same with
    ``stored_rank <= excluded.source_rank`` (``ingest/income.py``)."""
    return incoming_rank >= stored_rank


def merge_line(stored: OrderLine, incoming: OrderLine) -> OrderLine:
    """``incoming`` over ``stored`` (same key; the caller has checked :func:`replaces`)."""
    keep = {name: getattr(stored, name) for name in LINE_KEEP_WHEN_NULL}
    return replace(
        incoming,
        **{name: value for name, value in keep.items() if getattr(incoming, name) is None},
    )


def merge_settlement(stored: OrderSettlement, incoming: OrderSettlement) -> OrderSettlement:
    """``incoming`` over ``stored`` (same key; the caller has checked :func:`replaces`)."""
    return replace(
        incoming,
        **{
            name: getattr(stored, name)
            for name in SETTLEMENT_STATED
            if getattr(incoming, name) is None
        },
    )


def check_scope(
    shop_id: uuid.UUID, platform: str, rows: Sequence[OrderLine | OrderSettlement]
) -> None:
    """``ValueError`` when a row belongs to another shop or platform than the call's."""
    for row in rows:
        if row.shop_id != shop_id or row.platform != platform:
            raise ValueError("canonical row outside the call's shop / platform")


# -- canonical -> compute input -------------------------------------------------------------


def day_of(moment: datetime) -> date:
    """The VN calendar day of a timestamp (naive = UTC, as the tables store it)."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(DAY_ZONE).date()


def compute_status(value: str) -> OrderStatus:
    """The ``OrderStatus`` of a stored status. A value outside the vocabulary (a mapper kept it
    raw and flagged it) counts as ``in_transit``: no fee and no profit until it is understood,
    never silently ``delivered``."""
    return _STATUS.get(value, OrderStatus.IN_TRANSIT)


def _cost_key(line: OrderLine) -> str:
    return line.variation_sku or line.sku or line.variation_id or line.item_id


def _actual_fees(line: OrderLine) -> Decimal | None:
    stated = [v for v in (getattr(line, n) for n in LINE_FEE_FIELDS) if v is not None]
    return sum(stated, ZERO) if stated else None


def _income_order(settlement: OrderSettlement) -> IncomeOrder:
    # The REPORTED withheld tax is deducted (owner 2026-11-16); never a declared or guessed rate.
    return IncomeOrder(
        order_ref=settlement.order_ref,
        fee_fixed=settlement.fee_fixed,
        fee_service=settlement.fee_service,
        fee_payment=settlement.fee_payment,
        fee_piship=settlement.fee_piship,
        fee_nttd=settlement.fee_nttd,
        affiliate_commission=settlement.affiliate_commission,
        net_shipping_cost=settlement.net_shipping_cost,
        return_ship_refund=settlement.return_ship_refund,
        return_ship_failed=settlement.return_ship_failed,
        refund_amount=settlement.refund_amount,
        lost_compensation=settlement.lost_compensation,
        vat_withheld=settlement.vat_withheld,
        pit_withheld=settlement.pit_withheld,
        seller_coin_borne=settlement.seller_coin_borne,
        trade_in_bonus_seller=settlement.trade_in_bonus_seller,
        payout=settlement.payout,
    )


def profit_order_lines(
    lines: Sequence[OrderLine], settlement: OrderSettlement | None = None
) -> list[ProfitLine]:
    """The compute input for ONE order: its canonical lines (+ its settlement, when settled).

    - ``actual_fees`` = the sum of the line's stated ``fee_*`` fields, ``None`` when none is;
    - a settlement is split over the lines by ``buyer_paid`` (``income.split_income``, whole
      cents, shares add up) and wins over ``actual_fees`` in ``line_profit``; its ``fee_other``
      is split the same way and charged as fee ``FEE_OTHER``; VAT / PIT are never passed;
    - ``order_date`` is the VN calendar day of ``ordered_at``; the cost key is the variation SKU,
      else the SKU, else the variation / item id (the analytics loader's pack and BOM keys stay
      there);
    - lines with ``qty <= 0`` (fully returned before shipping) are left out: the compute input
      requires a positive quantity.
    """
    refs = {line.order_ref for line in lines}
    if len(refs) > 1:
        raise ValueError("profit_order_lines takes the lines of one order")
    if settlement is not None and refs and settlement.order_ref not in refs:
        raise ValueError("settlement belongs to another order")
    out = [
        ProfitLine(
            order_id=line.order_ref,
            sku=_cost_key(line),
            product_id=line.item_id,
            order_date=day_of(line.ordered_at),
            qty=line.qty,
            original_price=line.original_price,
            deal_price=line.deal_price,
            shop_voucher_share=line.shop_voucher_share,
            bundle_discount=line.bundle_discount,
            promo_kind=_PROMO_KIND.get(line.promo_kind, PromoKind.NONE),
            ad_attributed=bool(line.ad_attributed),
            affiliate=line.affiliate,
            commission=line.commission if line.affiliate else None,
            actual_fees=_actual_fees(line),
            buyer_shipping_fee=line.buyer_shipping_fee,
            bank_promo=line.bank_promo,
            status=compute_status(line.status),
        )
        for line in sorted(lines, key=lambda ln: ln.line_no)
        if line.qty > 0
    ]
    if settlement is None or not out:
        return out
    weights = [ln.buyer_paid for ln in out]
    shares = split_income(_income_order(settlement), weights)
    other = (
        split_amount(settlement.fee_other, weights) if settlement.fee_other is not None else None
    )
    result: list[ProfitLine] = []
    for i, (line, share) in enumerate(zip(out, shares, strict=True)):
        if other is not None:
            share = replace(share, fees=(*share.fees, (FEE_OTHER, other[i])))
        result.append(replace(line, income=share))
    return result
