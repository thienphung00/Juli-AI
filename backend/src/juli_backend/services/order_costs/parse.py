"""Vendor payload -> stored rows for the two cost reads (fast track P14-C).

Pure functions, no I/O. Everything that is not an amount or an id is dropped
here: the price-detail and finance payloads carry product / SKU names, and the
order detail used for the line-item -> SKU map carries the buyer's address and
e-mail. Only ``line_items[].id``, ``sku_id`` and ``product_id`` are read from it.

Field names and shapes: the Partner API reference (local corpus
``partner_documents/api-reference/orders/get-price-detail-202407.md``,
``finance/get-transactions-by-order-202501.md``) and the bundled OAS schema;
neither endpoint has been read live yet (contract ``p14-rules-and-cost.md`` §2).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from juli_backend.models.order_costs import (
    FINANCE_AMOUNT_FIELDS,
    ORDER_LEVEL,
    PRICE_AMOUNT_FIELDS,
)

#: Fields summed into ``seller_funded_amount`` / ``platform_funded_amount``.
#: Only documented amounts; the voucher fields are excluded (see the model).
SELLER_FUNDED_FIELDS: tuple[str, ...] = (
    "subtotal_deduction_seller",
    "shipping_fee_deduction_seller",
)
PLATFORM_FUNDED_FIELDS: tuple[str, ...] = (
    "subtotal_deduction_platform",
    "shipping_fee_deduction_platform",
)

_ID_MAX = 100


def parse_amount(value: Any) -> Decimal | None:
    """A vendor amount string (``"12.50"``, ``"-30"``) as ``Decimal``; ``None`` when absent."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _id(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:_ID_MAX] if text else None


def _sum(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) if present else None


def _funded(amounts: Mapping[str, Decimal | None], fields: tuple[str, ...]) -> Decimal:
    return sum((amounts.get(name) or Decimal(0) for name in fields), Decimal(0))


# -- price detail ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PriceRow:
    """One ``order_price_details`` row (``tiktok_sku_id == ''`` is the order itself)."""

    tiktok_sku_id: str
    tiktok_product_id: str | None
    line_item_count: int
    currency: str | None
    amounts: Mapping[str, Decimal | None]

    @property
    def seller_funded_amount(self) -> Decimal:
        return _funded(self.amounts, SELLER_FUNDED_FIELDS)

    @property
    def platform_funded_amount(self) -> Decimal:
        return _funded(self.amounts, PLATFORM_FUNDED_FIELDS)


@dataclass(frozen=True)
class PriceParse:
    rows: list[PriceRow]
    #: Line items whose id the order detail did not map to a SKU (kept only in
    #: the order-level row's totals).
    unmapped_line_items: int = 0


def _price_amounts(item: Mapping[str, Any]) -> dict[str, Decimal | None]:
    return {name: parse_amount(item.get(name)) for name in PRICE_AMOUNT_FIELDS}


def line_item_skus(order_detail: Mapping[str, Any]) -> dict[str, dict[str, tuple[str, str | None]]]:
    """``GET /order/202507/orders`` data -> ``{order_id: {line_item_id: (sku_id, product_id)}}``.

    Reads ids only; the rest of the order (buyer, address, e-mail) is ignored.
    """
    out: dict[str, dict[str, tuple[str, str | None]]] = {}
    orders = order_detail.get("orders") if isinstance(order_detail, Mapping) else None
    for order in orders or []:
        if not isinstance(order, Mapping):
            continue
        order_id = _id(order.get("id"))
        if order_id is None:
            continue
        items = out.setdefault(order_id, {})
        for line in order.get("line_items") or []:
            if not isinstance(line, Mapping):
                continue
            line_id, sku_id = _id(line.get("id")), _id(line.get("sku_id"))
            if line_id and sku_id:
                items[line_id] = (sku_id, _id(line.get("product_id")))
    return out


def parse_price_detail(
    data: Mapping[str, Any], skus_by_line_item: Mapping[str, tuple[str, str | None]]
) -> PriceParse:
    """``price_detail`` data -> the order-level row + one row per SKU (line items summed)."""
    if not isinstance(data, Mapping):
        return PriceParse(rows=[])
    order_currency = _id(data.get("currency"))
    rows = [
        PriceRow(
            tiktok_sku_id=ORDER_LEVEL,
            tiktok_product_id=None,
            line_item_count=len(data.get("line_items") or []),
            currency=order_currency,
            amounts=_price_amounts(data),
        )
    ]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    products: dict[str, str | None] = {}
    unmapped = 0
    for item in data.get("line_items") or []:
        if not isinstance(item, Mapping):
            continue
        mapped = skus_by_line_item.get(_id(item.get("id")) or "")
        if mapped is None:
            unmapped += 1
            continue
        sku_id, product_id = mapped
        grouped.setdefault(sku_id, []).append(item)
        products.setdefault(sku_id, product_id)
    for sku_id in sorted(grouped):
        items = grouped[sku_id]
        per_item = [_price_amounts(item) for item in items]
        rows.append(
            PriceRow(
                tiktok_sku_id=sku_id,
                tiktok_product_id=products[sku_id],
                line_item_count=len(items),
                currency=_id(items[0].get("currency")) or order_currency,
                amounts={name: _sum(a[name] for a in per_item) for name in PRICE_AMOUNT_FIELDS},
            )
        )
    return PriceParse(rows=rows, unmapped_line_items=unmapped)


# -- finance transactions -------------------------------------------------------------------


@dataclass(frozen=True)
class FinanceRow:
    """One ``order_finance_transactions`` row (both ids ``''`` is the order's totals)."""

    tiktok_sku_id: str
    statement_id: str
    quantity: int | None
    currency: str | None
    amounts: Mapping[str, Decimal | None]
    fee_breakdown: dict[str, str] = field(default_factory=dict)
    shipping_breakdown: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FinanceParse:
    rows: list[FinanceRow]
    order_create_time: datetime | None
    #: TikTok returned SKU transactions: the order has (at least partly) settled.
    settled: bool


def _flat_amounts(source: Any, prefix: str = "") -> dict[str, str]:
    """``{"a": "1", "n": {"b": "2"}}`` -> ``{"a": "1", "n.b": "2"}`` (amount strings only)."""
    out: dict[str, str] = {}
    if not isinstance(source, Mapping):
        return out
    for key, value in source.items():
        name = f"{prefix}{key}"
        if isinstance(value, Mapping):
            out.update(_flat_amounts(value, f"{name}."))
        elif parse_amount(value) is not None:
            out[name] = str(value).strip()
    return out


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _quantity(value: Any) -> int | None:
    number = parse_amount(value)
    return int(number) if number is not None else None


def _sku_finance_row(tx: Mapping[str, Any], currency: str | None) -> FinanceRow | None:
    sku_id = _id(tx.get("sku_id"))
    if sku_id is None:
        return None
    revenue = _mapping(tx.get("revenue_breakdown"))
    fee_tax = _mapping(tx.get("fee_tax_breakdown"))
    fees = _mapping(fee_tax.get("fee"))
    shipping = tx.get("shipping_cost_breakdown")
    lookup: dict[str, Any] = {**fees, **revenue}
    for name in ("revenue_amount", "settlement_amount", "fee_tax_amount", "shipping_cost_amount"):
        lookup[name] = tx.get(name)
    return FinanceRow(
        tiktok_sku_id=sku_id,
        statement_id=_id(tx.get("statement_id")) or ORDER_LEVEL,
        quantity=_quantity(tx.get("quantity")),
        currency=currency,
        amounts={name: parse_amount(lookup.get(name)) for name in FINANCE_AMOUNT_FIELDS},
        fee_breakdown=_flat_amounts(fee_tax),
        shipping_breakdown=_flat_amounts(shipping),
    )


def _merge(a: FinanceRow, b: FinanceRow) -> FinanceRow:
    """Two transactions for the same (SKU, statement): amounts and quantity summed."""
    amounts = {name: _sum((a.amounts[name], b.amounts[name])) for name in FINANCE_AMOUNT_FIELDS}
    quantity = (
        None if a.quantity is None and b.quantity is None else (a.quantity or 0) + (b.quantity or 0)
    )

    def add(x: dict[str, str], y: dict[str, str]) -> dict[str, str]:
        merged = dict(x)
        for key, value in y.items():
            total = _sum((parse_amount(merged.get(key)), parse_amount(value)))
            merged[key] = str(total) if total is not None else value
        return merged

    return FinanceRow(
        tiktok_sku_id=a.tiktok_sku_id,
        statement_id=a.statement_id,
        quantity=quantity,
        currency=a.currency,
        amounts=amounts,
        fee_breakdown=add(a.fee_breakdown, b.fee_breakdown),
        shipping_breakdown=add(a.shipping_breakdown, b.shipping_breakdown),
    )


def parse_statement_transactions(data: Mapping[str, Any]) -> FinanceParse:
    """``statement_transactions`` data -> the order-level row + one row per (SKU, statement)."""
    if not isinstance(data, Mapping):
        return FinanceParse(rows=[], order_create_time=None, settled=False)
    currency = _id(data.get("currency"))
    created = parse_amount(data.get("order_create_time"))
    create_time = (
        datetime.fromtimestamp(int(created), tz=UTC).replace(tzinfo=None)
        if created is not None and created > 0
        else None
    )
    order_lookup = {
        "revenue_amount": data.get("revenue_amount"),
        "settlement_amount": data.get("settlement_amount"),
        # The order level names it ``fee_and_tax_amount``; the SKU level ``fee_tax_amount``.
        "fee_tax_amount": data.get("fee_and_tax_amount", data.get("fee_tax_amount")),
        "shipping_cost_amount": data.get("shipping_cost_amount"),
    }
    order_row = FinanceRow(
        tiktok_sku_id=ORDER_LEVEL,
        statement_id=ORDER_LEVEL,
        quantity=None,
        currency=currency,
        amounts={name: parse_amount(order_lookup.get(name)) for name in FINANCE_AMOUNT_FIELDS},
    )
    by_key: dict[tuple[str, str], FinanceRow] = {}
    for tx in data.get("sku_transactions") or []:
        if not isinstance(tx, Mapping):
            continue
        row = _sku_finance_row(tx, currency)
        if row is None:
            continue
        key = (row.tiktok_sku_id, row.statement_id)
        by_key[key] = _merge(by_key[key], row) if key in by_key else row
    sku_rows = [by_key[key] for key in sorted(by_key)]
    return FinanceParse(
        rows=[order_row, *sku_rows], order_create_time=create_time, settled=bool(sku_rows)
    )
