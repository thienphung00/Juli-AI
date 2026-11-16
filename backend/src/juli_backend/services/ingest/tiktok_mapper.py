"""TikTok Shop raw payloads -> canonical rows (P101 W2, layer 2). Pure: no DB, no network, no clock.

The only place TikTok field names meet the canonical shape (:mod:`.canonical`); shared code never
branches on the platform. Nothing is stored here: the caller passes ``raw_payload_id`` (the raw
landing row the payload came from) and writes the result through a ``CanonicalWriter``.

Inputs (field names as the repo already reads them: ``services/order_costs/parse.py``,
``models/order_status.py``, fixtures ``tests/fixtures/tiktok_order_costs`` and
``tests/fixtures/tiktok_privacy``; the W0 probe ``fasttrack/contracts/p101-w0-probe-docs.md``):

- one ``data.orders[]`` element of order search / detail (202309 shape): ``id``, ``status``,
  ``create_time`` / ``paid_time`` / ``delivery_time`` (unix seconds), ``payment.currency``,
  ``payment.seller_discount`` / ``platform_discount`` / ``shipping_fee``, and ``line_items[]``
  (``id``, ``product_id``, ``sku_id``, ``sku_name``, ``seller_sku``, ``original_price``,
  ``sale_price``, ``seller_discount``, ``platform_discount``, ``display_status``, ``currency``);
- optionally its ``price_detail`` data (202407; ``line_items[].voucher_deduction_seller`` /
  ``voucher_deduction_platform``);
- optionally its ``statement_transactions`` data (finance 202501; ``sku_transactions[]`` with
  ``revenue_breakdown``, ``fee_tax_breakdown.fee`` / ``.tax``, ``shipping_cost_breakdown``).

Rules:

- ``platform = "tiktok"``; ``order_ref = ref_of(order id)`` (identity by default: the TikTok
  order id; pass a keyed hash to match the Shopee lanes, see the W2 report).
- One canonical line per TikTok line item, ``qty = 1`` (TikTok repeats a line item per unit).
  ``line_no`` = the item's place after sorting the line items by their numeric ``id`` (0-based),
  so a refetch that returns them in another order gives every item the same ``line_no``.
- ``deal_price = original_price - seller_discount``: the price after the SELLER's promotion and
  before TikTok's, as Shopee's "Giá ưu đãi" (``buyer_paid`` = original - all seller-funded).
  ``seller_discount -> seller_subsidy``, ``platform_discount -> platform_subsidy``.
- Vouchers: a price-detail line's ``voucher_deduction_seller`` / ``_platform`` is used only when
  it reads as an amount within the line's seller / platform discount (the docs describe these
  fields as type codes such as ``1020000``; probe D.6). Then the voucher moves out of the
  subsidy: ``shop_voucher_share = voucher``, ``seller_subsidy = seller_discount - voucher`` (and
  the same for the platform side), so ``buyer_paid`` is unchanged. Otherwise the whole seller
  discount stays promotion (TikTok lumps promo + voucher; see W0 B.5) and the warning
  ``price_detail_voucher_not_amount`` is returned.
- Per-line amounts are taken per line. Only when NO line item states ``seller_discount`` /
  ``platform_discount`` are the order's ``payment.*`` discounts split over the lines pro rata by
  line value (``original_price * qty``; ``income.split_amount``: whole cents, shares add up),
  warning ``discount_split_pro_rata``. ``payment.shipping_fee`` (order level) is split the same
  way into ``buyer_shipping_fee``, as the Shopee order export's order-level amounts are.
- Status (Shopee's ``OrderStatus`` vocabulary): DELIVERED / COMPLETED -> ``delivered``; any
  cancellation spelling -> ``cancelled`` (also per line, from ``display_status``, for a partial
  cancel); every other known pre-delivery status (UNPAID ... IN_TRANSIT; Shopee files
  "chưa thanh toán" as in transit too) -> ``in_transit``. An unknown status is kept raw (lower
  case, enum characters only) with warning ``status_unrecognised:<raw>``, never a crash;
  ``canonical.compute_status`` keeps such a line out of profit.
- Money is ``Decimal`` from the payload strings; an order or statement whose currency is not
  VND is skipped (no lines, no settlement) with warning ``currency_not_vnd``.
- Timestamps: unix seconds -> aware UTC ``datetime``.
- Settlement: a statement with no SKU transaction or only zero amounts is UNSETTLED -> ``None``
  (missing is not zero). TikTok reports deductions negative; canonical costs are positive, so a
  fee / tax / actual shipping is stored as ``-value`` (sign convention: probe D.4). Fees with a
  canonical column go there (commission -> ``fee_fixed``, the Shopee "Phí cố định"; transaction
  fees -> ``fee_payment``; voucher-xtra, cashback and VN infrastructure fees -> ``fee_service``,
  which on Shopee INCLUDES those two; ``affiliate_commission_amount`` -> ``affiliate_commission``).
  Every other fee key (SFP, affiliate ads / partner commission, LIVE specials ...) is summed into
  ``fee_other``; its per-key split is returned as ``fee_other_breakdown`` and stays in the raw
  payload. The Shopee-only columns (piship, nttd, voucher_xtra, infra, coin, trade-in, lost
  compensation, transaction fee rate, seller voucher borne) stay ``None``.
- No buyer field is read; PII never reaches a canonical row.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from juli_backend.models.ingest import SOURCE_API, SOURCE_RANK
from juli_backend.models.order_status import is_cancelled_status
from juli_backend.services.ingest.canonical import (
    ZERO,
    OrderLine,
    OrderSettlement,
    day_of,
)
from juli_backend.services.order_costs.parse import parse_amount
from juli_backend.services.shopee_profit.income import split_amount
from juli_backend.services.shopee_profit.order_profit import OrderStatus

PLATFORM = "tiktok"
CURRENCY = "VND"
ORDER_SOURCE_VERSION = "tiktok:order/202309"
STATEMENT_SOURCE_VERSION = "tiktok:finance/202501"

WARN_CURRENCY = "currency_not_vnd"
WARN_STATUS = "status_unrecognised"
WARN_PRO_RATA = "discount_split_pro_rata"
WARN_VOUCHER = "price_detail_voucher_not_amount"
WARN_NO_ID = "order_without_id"
WARN_NO_TIME = "order_without_create_time"
WARN_NO_LINES = "order_without_line_items"

_DELIVERED = frozenset({"DELIVERED", "COMPLETED"})
_IN_TRANSIT = frozenset(
    {
        "UNPAID",
        "ON_HOLD",
        "AWAITING_SHIPMENT",
        "PARTIALLY_SHIPPING",
        "AWAITING_COLLECTION",
        "IN_TRANSIT",
        "SHIPPED",
    }
)

#: ``fee_tax_breakdown.fee`` keys -> canonical column. Anything not here and not ignored is
#: ``fee_other``.
FEE_COLUMNS: dict[str, str] = {
    "platform_commission_amount": "fee_fixed",
    "dynamic_commission_amount": "fee_fixed",
    "tsp_commission_amount": "fee_fixed",
    "referral_fee_amount": "fee_fixed",
    "transaction_fee_amount": "fee_payment",
    "credit_card_handling_fee_amount": "fee_payment",
    "seller_paylater_handling_fee_amount": "fee_payment",
    "voucher_xtra_service_fee_amount": "fee_service",
    "bonus_cashback_service_fee_amount": "fee_service",
    "vn_fix_infrastructure_fee": "fee_service",
    "affiliate_commission_amount": "affiliate_commission",
}
#: Fee keys that are not a cost of the order: cash-timing pairs, and a second representation of
#: a fee already counted. Kept in the raw payload, never summed.
IGNORED_FEES: frozenset[str] = frozenset(
    {
        "affiliate_commission_deposit",
        "affiliate_commission_release",
        "affiliate_commission_amount_before_pit",
    }
)
#: ``fee_tax_breakdown.tax`` keys -> canonical column (stored as reported, never in profit).
TAX_COLUMNS: dict[str, str] = {
    "vat_amount": "vat_withheld",
    "local_vat_amount": "vat_withheld",
    "pit_amount": "pit_withheld",
}

_ENUM_CHARS = re.compile(r"[^A-Za-z0-9_]")
_SEPARATORS = re.compile(r"[\s\-]+")
_ID_MAX = 64


@dataclass(frozen=True)
class MappedOrder:
    """One TikTok order mapped: its lines, its settlement (``None`` = not settled yet), the
    ``fee_other`` split by TikTok fee key, and the warnings (codes, no payload values but a
    bounded status / currency code)."""

    lines: tuple[OrderLine, ...] = ()
    settlement: OrderSettlement | None = None
    fee_other_breakdown: Mapping[str, Decimal] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MappedSettlement:
    settlement: OrderSettlement | None
    fee_other_breakdown: Mapping[str, Decimal]
    warnings: tuple[str, ...]


# -- small readers --------------------------------------------------------------------------


def _map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, limit: int = _ID_MAX) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:limit] if text else None


def _money(value: Any) -> Decimal | None:
    return parse_amount(value)


def _time(value: Any) -> datetime | None:
    seconds = parse_amount(value)
    if seconds is None or seconds <= 0:
        return None
    return datetime.fromtimestamp(int(seconds), tz=UTC)


def _code(value: Any) -> str:
    return _ENUM_CHARS.sub("", _SEPARATORS.sub("_", str(value).strip()))[:_ID_MAX].lower()


def _id_order(item: tuple[int, Mapping[str, Any]]) -> tuple[int, int, str, int]:
    """Sort key of a line item: numeric ids first by value, then text ids, then position."""
    position, line = item
    raw = _text(line.get("id")) or ""
    if raw.isdigit():
        return (0, int(raw), "", position)
    return (1 if raw else 2, 0, raw, position)


def _currency_ok(*codes: Any) -> bool:
    stated = [str(c).strip().upper() for c in codes if _text(c)]
    return all(code == CURRENCY for code in stated)


def map_status(raw: Any) -> tuple[str, str | None]:
    """``(stored status, warning or None)`` for a TikTok order / line status."""
    if is_cancelled_status(raw):
        return OrderStatus.CANCELLED.value, None
    key = str(raw or "").strip().upper().replace(" ", "_")
    if key in _DELIVERED:
        return OrderStatus.DELIVERED.value, None
    if key in _IN_TRANSIT:
        return OrderStatus.IN_TRANSIT.value, None
    code = _code(raw) or "unknown"
    return code, f"{WARN_STATUS}:{code}"


# -- order -> lines -------------------------------------------------------------------------


def _voucher(detail: Mapping[str, Any], name: str, ceiling: Decimal) -> Decimal | None:
    """A price-detail voucher field, when it reads as an amount within ``ceiling``."""
    amount = _money(detail.get(name))
    if amount is None or amount < 0 or amount > ceiling:
        return None
    return amount


def _discounts(
    items: Sequence[Mapping[str, Any]], payment: Mapping[str, Any], originals: Sequence[Decimal]
) -> tuple[list[Decimal], list[Decimal], bool]:
    """Per-line seller and platform discounts; pro rata from ``payment`` when no line states one."""
    per_line = any(
        _money(it.get("seller_discount")) is not None
        or _money(it.get("platform_discount")) is not None
        for it in items
    )
    if per_line:
        return (
            [_money(it.get("seller_discount")) or ZERO for it in items],
            [_money(it.get("platform_discount")) or ZERO for it in items],
            False,
        )
    seller = _money(payment.get("seller_discount")) or ZERO
    platform = _money(payment.get("platform_discount")) or ZERO
    split = bool(seller or platform)
    return split_amount(seller, originals), split_amount(platform, originals), split


def map_order_lines(
    order: Mapping[str, Any],
    *,
    shop_id: uuid.UUID,
    order_ref: str,
    raw_payload_id: uuid.UUID | None = None,
    price_detail: Mapping[str, Any] | None = None,
) -> tuple[list[OrderLine], list[str]]:
    """One order's canonical lines and warnings (the order's currency is checked by the caller)."""
    warnings: list[str] = []
    ordered_at = _time(order.get("create_time"))
    if ordered_at is None:
        return [], [WARN_NO_TIME]
    raw_items = [it for it in order.get("line_items") or [] if isinstance(it, Mapping)]
    if not raw_items:
        return [], [WARN_NO_LINES]
    items = [it for _, it in sorted(enumerate(raw_items), key=_id_order)]
    payment = _map(order.get("payment"))
    order_status, warning = map_status(order.get("status"))
    if warning:
        warnings.append(warning)
    paid_at = _time(order.get("paid_time"))
    delivered_at = _time(order.get("delivery_time"))

    originals = [
        _money(it.get("original_price")) or _money(it.get("sale_price")) or ZERO for it in items
    ]
    seller, platform, split = _discounts(items, payment, originals)
    if split:
        warnings.append(WARN_PRO_RATA)
    shipping = _money(payment.get("shipping_fee"))
    shipping_shares = split_amount(shipping, originals) if shipping is not None else None
    details = {
        _text(d.get("id")): d
        for d in _map(price_detail).get("line_items") or []
        if isinstance(d, Mapping)
    }

    lines: list[OrderLine] = []
    voucher_rejected = False
    for line_no, item in enumerate(items):
        status = order_status
        if order_status != OrderStatus.CANCELLED.value and is_cancelled_status(
            item.get("display_status")
        ):
            status = OrderStatus.CANCELLED.value
        original, seller_off, platform_off = originals[line_no], seller[line_no], platform[line_no]
        shop_voucher = platform_voucher = ZERO
        detail = details.get(_text(item.get("id")))
        if detail is not None:
            for name, ceiling in (
                ("voucher_deduction_seller", seller_off),
                ("voucher_deduction_platform", platform_off),
            ):
                if detail.get(name) in (None, ""):
                    continue
                amount = _voucher(detail, name, ceiling)
                if amount is None:
                    voucher_rejected = True
                elif name.endswith("seller"):
                    shop_voucher = amount
                else:
                    platform_voucher = amount
        seller_subsidy = seller_off - shop_voucher
        if seller_subsidy > 0:
            promo_kind = "discount"
        elif shop_voucher > 0:
            promo_kind = "voucher"
        else:
            promo_kind = "none"
        lines.append(
            OrderLine(
                shop_id=shop_id,
                platform=PLATFORM,
                order_ref=order_ref,
                line_no=line_no,
                ordered_at=ordered_at,
                status=status,
                paid_at=paid_at,
                completed_at=delivered_at if status == OrderStatus.DELIVERED.value else None,
                item_id=_text(item.get("product_id")) or "",
                variation_id=_text(item.get("sku_id")) or "",
                variation_name=_text(item.get("sku_name"), 128),
                variation_sku=_text(item.get("seller_sku"), 128),
                qty=1,
                original_price=original,
                deal_price=original - seller_subsidy,
                shop_voucher_share=shop_voucher,
                platform_voucher_share=platform_voucher,
                seller_subsidy=seller_subsidy,
                platform_subsidy=platform_off - platform_voucher,
                promo_kind=promo_kind,
                buyer_shipping_fee=shipping_shares[line_no] if shipping_shares else None,
                source=SOURCE_API,
                source_version=ORDER_SOURCE_VERSION,
                raw_payload_id=raw_payload_id,
            )
        )
    if voucher_rejected:
        warnings.append(WARN_VOUCHER)
    return lines, warnings


# -- statement -> settlement ----------------------------------------------------------------


def _add(totals: dict[str, Decimal], name: str, amount: Decimal | None) -> None:
    if amount is not None:
        totals[name] = totals.get(name, ZERO) + amount


def _is_settled(data: Mapping[str, Any], txs: Sequence[Mapping[str, Any]]) -> bool:
    """Any non-zero amount anywhere in the order's transactions (sandbox: all zero = unsettled)."""
    if not txs:
        return False

    def nonzero(node: Any) -> bool:
        if isinstance(node, Mapping):
            return any(nonzero(v) for v in node.values())
        if isinstance(node, list):
            return any(nonzero(v) for v in node)
        return bool(_money(node))

    keys = ("revenue_amount", "settlement_amount", "fee_and_tax_amount", "shipping_cost_amount")
    return any(nonzero(data.get(k)) for k in keys) or any(
        nonzero({k: v for k, v in tx.items() if k not in ("sku_id", "statement_id", "quantity")})
        for tx in txs
    )


def map_statement(
    data: Mapping[str, Any],
    *,
    shop_id: uuid.UUID,
    order_ref: str,
    raw_payload_id: uuid.UUID | None = None,
    ordered_at: datetime | None = None,
    statement_times: Mapping[str, Any] | None = None,
) -> MappedSettlement:
    """One order's ``statement_transactions`` data -> its settlement (``None`` when unsettled).

    ``statement_times``: statement id -> ``statement_time`` (unix seconds, from the statements
    list); ``paid_on`` is the VN day of the latest one, else ``None``."""
    data = _map(data)
    if not _currency_ok(data.get("currency")):
        return MappedSettlement(None, {}, (f"{WARN_CURRENCY}:{_code(data.get('currency'))}",))
    txs = [tx for tx in data.get("sku_transactions") or [] if isinstance(tx, Mapping)]
    if not _is_settled(data, txs):
        return MappedSettlement(None, {}, ())

    columns: dict[str, Decimal] = {}
    other: dict[str, Decimal] = {}
    statement_ids: set[str] = set()
    for tx in txs:
        if sid := _text(tx.get("statement_id")):
            statement_ids.add(sid)
        revenue = _map(tx.get("revenue_breakdown"))
        _add(columns, "product_price", _money(revenue.get("subtotal_before_discount_amount")))
        for name in ("refund_subtotal_before_discount_amount", "seller_discount_refund_amount"):
            amount = _money(revenue.get(name))
            _add(columns, "refund_amount", -amount if amount is not None else None)
        breakdown = _map(tx.get("fee_tax_breakdown"))
        for key, value in _map(breakdown.get("fee")).items():
            amount = _money(value)
            if amount is None or key in IGNORED_FEES:
                continue
            column = FEE_COLUMNS.get(key)
            if column is None:
                _add(other, key, -amount)
            else:
                _add(columns, column, -amount)
        for key, value in _map(breakdown.get("tax")).items():
            column, amount = TAX_COLUMNS.get(key), _money(value)
            if column is not None and amount is not None:
                _add(columns, column, -amount)
        shipping = _map(tx.get("shipping_cost_breakdown"))
        actual = _money(shipping.get("actual_shipping_fee_amount"))
        _add(columns, "ship_actual_cost", -actual if actual is not None else None)
        _add(columns, "ship_buyer_paid", _money(shipping.get("customer_paid_shipping_fee_amount")))
        subsidy = _money(
            _map(shipping.get("supplementary_component")).get(
                "platform_shipping_fee_discount_amount"
            )
        )
        if subsidy is None:
            subsidy = _money(shipping.get("shipping_fee_discount_amount"))
        _add(columns, "ship_platform_subsidy", subsidy)

    payout = _money(data.get("settlement_amount"))
    if payout is None:
        payout = sum((_money(tx.get("settlement_amount")) or ZERO for tx in txs), ZERO)
    net_shipping = _money(data.get("shipping_cost_amount"))
    if net_shipping is None:
        sku_shipping = [_money(tx.get("shipping_cost_amount")) for tx in txs]
        stated = [s for s in sku_shipping if s is not None]
        net_shipping = sum(stated, ZERO) if stated else None
    created = _time(data.get("order_create_time")) or ordered_at
    times = [t for t in (_time(_map(statement_times).get(s)) for s in sorted(statement_ids)) if t]
    settlement = OrderSettlement(
        shop_id=shop_id,
        platform=PLATFORM,
        order_ref=order_ref,
        ordered_on=day_of(created) if created else None,
        paid_on=day_of(max(times)) if times else None,
        payout=payout,
        net_shipping_cost=-net_shipping if net_shipping is not None else None,
        fee_other=sum(other.values(), ZERO) if other else None,
        source=SOURCE_API,
        source_rank=SOURCE_RANK[SOURCE_API],
        source_version=STATEMENT_SOURCE_VERSION,
        raw_payload_id=raw_payload_id,
        **columns,
    )
    return MappedSettlement(settlement, dict(sorted(other.items())), ())


# -- one order ------------------------------------------------------------------------------


def map_order(
    order: Mapping[str, Any],
    *,
    shop_id: uuid.UUID,
    raw_payload_id: uuid.UUID | None = None,
    price_detail: Mapping[str, Any] | None = None,
    statement: Mapping[str, Any] | None = None,
    statement_raw_payload_id: uuid.UUID | None = None,
    statement_times: Mapping[str, Any] | None = None,
    ref_of: Callable[[str], str] | None = None,
) -> MappedOrder:
    """One TikTok order (+ its price detail and statement, when fetched) -> canonical rows.

    A non-VND order or statement skips the whole order: no lines, no settlement."""
    order = _map(order)
    order_id = _text(order.get("id"))
    if order_id is None:
        return MappedOrder(warnings=(WARN_NO_ID,))
    payment = _map(order.get("payment"))
    item_currencies = [it.get("currency") for it in order.get("line_items") or [] if _map(it)]
    statement_currency = _map(statement).get("currency")
    if not _currency_ok(payment.get("currency"), *item_currencies, statement_currency):
        stated = payment.get("currency") or statement_currency
        return MappedOrder(warnings=(f"{WARN_CURRENCY}:{_code(stated)}",))
    ref = ref_of(order_id) if ref_of else order_id
    lines, warnings = map_order_lines(
        order,
        shop_id=shop_id,
        order_ref=ref,
        raw_payload_id=raw_payload_id,
        price_detail=price_detail,
    )
    if statement is None:
        return MappedOrder(lines=tuple(lines), warnings=tuple(warnings))
    mapped = map_statement(
        statement,
        shop_id=shop_id,
        order_ref=ref,
        raw_payload_id=statement_raw_payload_id,
        ordered_at=_time(order.get("create_time")),
        statement_times=statement_times,
    )
    return MappedOrder(
        lines=tuple(lines),
        settlement=mapped.settlement,
        fee_other_breakdown=mapped.fee_other_breakdown,
        warnings=(*warnings, *mapped.warnings),
    )
