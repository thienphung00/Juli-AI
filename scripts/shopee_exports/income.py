"""The income export (Tài chính › Doanh thu, ``Income.T<m>.<from>_<to>.xlsx``) → ``order_income``
posts: what Shopee ACTUALLY charged and paid out per order (P91 D-12).

Sheets (measured on ORY's August-October 2026 files):

- ``Summary`` - the month's totals by label. Read for the reconciliation only, through a
  column allowlist (the seller's account lines are never decoded).
- ``Service Fee Details`` - two title rows then ``Mã giao dịch, Mã đơn hàng, Phí Hạ Tầng
  [, Phí hạ tầng], Voucher Xtra``: the two parts of the order's ``Phí Dịch Vụ``. Some files carry
  the infrastructure fee under both spellings: the cells are summed.
- ``Shipping Fee Discrepancy`` (some months) - never opened; the shipping actually charged is in
  ``Doanh thu``.
- ``Doanh thu`` - three header rows (group titles, sub titles, column names), then one ``Order``
  row per order and one ``Sku`` row per product of it.

THE ORDER ROW IS THE AUTHORITY for an order's money; ``Sku`` rows only split it per product (item
id and variation name, kept in ``IncomeFile.products``, not posted). The two row kinds disagree on
sign for the return-shipping columns (Order negative, Sku positive), so a Sku row is never summed
into an order.

SIGNS: the file shows a cost as a negative number and an income as a positive one. The posted row
states every cost as a POSITIVE amount the seller bore (a fee reversal is negative), ``payout``
and ``net_shipping_cost`` keep their meaning (payout can be negative; net shipping is cost minus
what Shopee, the buyer and PiShip paid back).

PRIVACY: as the order export, THE ALLOWLIST IS BY HEADER. Every header must be in :data:`READ`
(its cells are decoded) or :data:`IGNORED` (known, never decoded); any other header stops the
load with ``UnknownColumn``. The buyer's name and payment method, the invoice tax code, the
product name and the voucher text are ``IGNORED``. The order id is hashed as it is read
(``parse.order_ref``, the same key path as the order export) and never kept.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.shopee_exports import parse
from scripts.shopee_exports.orders import money
from scripts.shopee_exports.xlsx import read_cells, read_columns

SHEET_INCOME = "Doanh thu"
SHEET_FEES = "Service Fee Details"
SHEET_SUMMARY = "Summary"
INCOME_MARKER = "Mã đơn hàng"
KIND_HEADER = "Đơn hàng / Sản phẩm"
ORDER_ROW = "Order"
SKU_ROW = "Sku"
MAX_INCOME_ROWS = 1_000

#: header -> field, the columns whose cells are decoded on ``Doanh thu``.
READ: dict[str, str] = {
    KIND_HEADER: "kind",
    "Mã đơn hàng": "order_id",
    "Mã sản phẩm": "item_id",
    "Phân Loại": "variation",
    "Ngày đặt hàng": "ordered_on",
    "Ngày hoàn thành thanh toán": "paid_on",
    "Tổng tiền đã thanh toán": "payout",
    "Giá sản phẩm": "product_price",
    "Số tiền hoàn lại": "refund",
    "Phí vận chuyển Người mua trả": "ship_buyer_paid",
    "Phí vận chuyển thực tế": "ship_actual",
    "Phí vận chuyển được trợ giá từ Shopee": "ship_shopee_subsidy",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)": "return_ship_refund",
    "Phí vận chuyển được hoàn bởi PiShip": "ship_piship_refund",
    "Phí vận chuyển trả hàng (đơn giao không thành công)": "return_ship_failed",
    "Phí vận chuyển - Người bán hỗ trợ": "ship_seller_support",
    "Mã ưu đãi do Người Bán chịu": "voucher_seller",
    "Mã ưu đãi Đồng Tài Trợ do Người Bán chịu": "voucher_cofunded",
    "Mã hoàn xu do Người Bán chịu": "coin_seller",
    "Mã hoàn xu Đồng Tài Trợ do Người Bán chịu": "coin_cofunded",
    "Phí cố định": "fee_fixed",
    "Phí Dịch Vụ": "fee_service",
    "Phí xử lý giao dịch": "fee_payment",
    "Phí hoa hồng Tiếp thị liên kết": "affiliate_commission",
    "Phí dịch vụ PiShip": "fee_piship",
    "Phí dịch vụ hiển thị NTTD (từ doanh thu đơn hàng)": "fee_nttd",
    "Thuế GTGT": "vat_withheld",
    "Thuế TNCN": "pit_withheld",
    "Trade-in Bonus by Seller": "trade_in_bonus_seller",
    "Đền bù đơn mất hàng": "lost_compensation",
    "Transaction Fee Rate (%)": "transaction_fee_rate",
}

#: Known headers whose cells are NEVER decoded: the buyer, how they paid, the invoice tax code,
#: the product name, the voucher text, couriers, and amounts with no destination here.
IGNORED: frozenset[str] = frozenset(
    {
        "Mã giao dịch",
        "Mã Số Thuế",
        "Mã yêu cầu hoàn tiền",
        "Tên sản phẩm",
        "Phương thức thanh toán",
        "Sản Phẩm Bán Chạy",
        "Sản phẩm được trợ giá từ Shopee",
        "Phí lắp đặt người mua trả",
        "Phí lắp đặt thực tế",
        "Người Mua",
        "Amount Paid By Buyer",
        "Phương thức thanh toán của Người mua",
        "Buyer Payment Method Details_1",
        "Installment Plan (if applicable)",
        "Đơn vị vận chuyển",
        "Courier Name",
        "Mã voucher",
        "Giá sản phẩm (sau khuyến mãi)",
        "Shopee xu",
        "Shopee voucher",
        "Ngân hàng khuyến mãi thanh toán trên Thẻ Tín Dụng",
        "Shopee khuyến mãi thanh toán trên Thẻ Tín Dụng",
    }
)

#: Headers that must never have a value read, whatever else changes.
BUYER_HEADERS: frozenset[str] = frozenset(
    {
        "Người Mua",
        "Amount Paid By Buyer",
        "Phương thức thanh toán của Người mua",
        "Buyer Payment Method Details_1",
        "Mã Số Thuế",
        "Tên sản phẩm",
        "Mã voucher",
        "Mã yêu cầu hoàn tiền",
        "Courier Name",
        "Đơn vị vận chuyển",
        "Installment Plan (if applicable)",
    }
)

REQUIRED = (KIND_HEADER, "Mã đơn hàng", "Tổng tiền đã thanh toán", "Giá sản phẩm")

FEE_READ: dict[str, str] = {
    "Mã đơn hàng": "order_id",
    "Phí Hạ Tầng": "infra",
    "Phí hạ tầng": "infra_alt",
    "Voucher Xtra": "xtra",
}
FEE_IGNORED: frozenset[str] = frozenset({"Mã giao dịch"})

#: Columns whose signed sum over an order's money is its payout (checked on every order).
PAYOUT_PARTS = (
    "product_price",
    "refund",
    "ship_buyer_paid",
    "ship_actual",
    "ship_shopee_subsidy",
    "return_ship_refund",
    "ship_piship_refund",
    "return_ship_failed",
    "voucher_seller",
    "voucher_cofunded",
    "coin_seller",
    "coin_cofunded",
    "fee_fixed",
    "fee_service",
    "fee_payment",
    "affiliate_commission",
    "fee_piship",
    "fee_nttd",
    "vat_withheld",
    "pit_withheld",
    "trade_in_bonus_seller",
    "lost_compensation",
)
#: Summary label -> the ``Doanh thu`` field whose Order rows must add up to it (signed).
SUMMARY_FIELDS: dict[str, str] = {
    "Phí vận chuyển Người mua trả": "ship_buyer_paid",
    "Phí vận chuyển được trợ giá từ Shopee": "ship_shopee_subsidy",
    "Phí vận chuyển thực tế": "ship_actual",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)": "return_ship_refund",
    "Phí vận chuyển được hoàn bởi PiShip": "ship_piship_refund",
    "Phí vận chuyển trả hàng (đơn giao không thành công)": "return_ship_failed",
    "Phí hoa hồng Tiếp thị liên kết": "affiliate_commission",
    "Phí cố định": "fee_fixed",
    "Phí Dịch Vụ": "fee_service",
    "Phí dịch vụ PiShip": "fee_piship",
    "Phí xử lý giao dịch": "fee_payment",
    "Phí dịch vụ hiển thị NTTD (từ doanh thu đơn hàng)": "fee_nttd",
    "Trade-in Bonus by Seller": "trade_in_bonus_seller",
    "Thuế GTGT": "vat_withheld",
    "Thuế TNCN": "pit_withheld",
    "Số tiền hoàn lại": "refund",
    "Mã ưu đãi do Người Bán chịu": "voucher_seller",
    "Mã ưu đãi Đồng Tài Trợ do Người Bán chịu": "voucher_cofunded",
    "Mã hoàn xu do Người Bán chịu": "coin_seller",
    "Mã hoàn xu Đồng Tài Trợ do Người Bán chịu": "coin_cofunded",
    "3. Tổng số tiền": "payout",
}

_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})")
ZERO = Decimal(0)


class IncomeLayoutError(ValueError):
    """The export's layout is not what this parser asserts (never carries a cell value)."""


def normal(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def _day(text: str | None, column: str) -> date | None:
    if text is None or text.strip() in ("", "-"):
        return None
    match = _DAY.match(text.strip())
    if match is None:
        raise IncomeLayoutError(f"column {column!r}: a cell is not a date")
    return date.fromisoformat(match.group(1))


def _amount(text: str | None, column: str) -> Decimal:
    try:
        return money(text, column) or ZERO
    except ValueError as exc:
        raise IncomeLayoutError(str(exc)) from None


def _num(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


@dataclass
class ReconRow:
    """One Summary line against the sum of the month's Order rows (both signed, as in the file)."""

    label: str
    summary: Decimal
    orders: Decimal

    @property
    def diff(self) -> Decimal:
        return self.orders - self.summary


@dataclass
class IncomeFile:
    file: str
    period: tuple[date, date]
    #: order_ref -> the posted row (cost amounts positive).
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: order_ref -> (item id, variation name, product price) of its ``Sku`` rows.
    products: dict[str, list[tuple[str, str, Decimal]]] = field(default_factory=dict)
    order_rows: int = 0
    sku_rows: int = 0
    #: Orders whose payout is not the sum of their parts.
    unreconciled: int = 0
    #: Orders in Doanh thu with no Service Fee Details row.
    without_fee_details: int = 0
    recon: list[ReconRow] = field(default_factory=list)
    value_columns_read: set[str] = field(default_factory=set)
    ignored_headers: set[str] = field(default_factory=set)

    @property
    def refs(self) -> set[str]:
        return set(self.orders)


def _choose(header: list[str]) -> set[int]:
    names = [normal(h) for h in header]
    for name in names:
        if name and name not in READ and name not in IGNORED:
            raise parse.UnknownColumn(name)
    missing = [name for name in REQUIRED if name not in names]
    if missing:
        raise parse.UnknownColumn(f"missing column {missing[0]}")
    return {i for i, name in enumerate(names) if name in READ}


def _choose_fees(header: list[str]) -> set[int]:
    names = [normal(h) for h in header]
    for name in names:
        if name and name not in FEE_READ and name not in FEE_IGNORED:
            raise parse.UnknownColumn(f"{SHEET_FEES}: {name}")
    if "Mã đơn hàng" not in names:
        raise parse.UnknownColumn(f"{SHEET_FEES}: missing column Mã đơn hàng")
    return {i for i, name in enumerate(names) if name in FEE_READ}


def _fee_details(path: Path, key: bytes) -> dict[str, tuple[Decimal, Decimal]]:
    """order_ref -> (infrastructure fee, Voucher Xtra fee), signed as in the file."""
    sheet = read_columns(path, SHEET_FEES, _choose_fees, header_marker="Mã đơn hàng")
    names = [normal(h) for h in sheet.header]
    column = {FEE_READ[name]: i for i, name in enumerate(names) if name in FEE_READ}
    out: dict[str, tuple[Decimal, Decimal]] = {}
    for row in sheet.rows:
        order_id = row.get(column["order_id"])
        if order_id is None or not order_id.strip():
            continue
        infra = sum(
            (
                _amount(row.get(column[k]), "Phí Hạ Tầng")
                for k in ("infra", "infra_alt")
                if k in column
            ),
            ZERO,
        )
        xtra = _amount(row.get(column["xtra"]), "Voucher Xtra") if "xtra" in column else ZERO
        ref = parse.order_ref(order_id, key)
        old = out.get(ref, (ZERO, ZERO))
        out[ref] = (old[0] + infra, old[1] + xtra)
    return out


def read_summary(path: Path) -> dict[str, Decimal]:
    """The Summary sheet as ``{label: amount}``: item labels sit in column B with the amount in
    column C, group totals in column A with the amount in column D. Only these four columns are
    decoded, and only from the figures block on (the account lines above it are never read)."""
    rows = read_cells(path, SHEET_SUMMARY, (0, 1, 2, 3), first_row=12)
    out: dict[str, Decimal] = {}
    for row in rows:
        for label_col, value_col in ((1, 2), (0, 3)):
            label, value = row.get(label_col), row.get(value_col)
            if label and value and label.strip():
                try:
                    out[normal(label)] = money(value, "Summary") or ZERO
                except ValueError:
                    continue  # a currency symbol or a note, not an amount
    return out


def _row_values(row: dict[int, str | None], column: dict[str, int]) -> dict[str, str | None]:
    return {name: row.get(idx) for name, idx in column.items()}


def read_income(path: Path, key: bytes) -> IncomeFile:
    """Parse one income export; raises ``UnknownColumn`` / ``IncomeLayoutError``."""
    period = parse._file_period(path)
    result = IncomeFile(file=path.name, period=period)
    sheet = read_columns(path, SHEET_INCOME, _choose, header_marker=INCOME_MARKER)
    names = [normal(h) for h in sheet.header]
    result.ignored_headers = {n for n in names if n in IGNORED}
    result.value_columns_read = {names[i] for i in sheet.value_columns_read}
    column = {READ[name]: i for i, name in enumerate(names) if name in READ}
    label = {field_name: header for header, field_name in READ.items()}
    fees = _fee_details(path, key)

    sums: dict[str, dict[str, Decimal]] = {}
    seen_orders: Counter[str] = Counter()
    for raw in sheet.rows:
        cells = _row_values(raw, column)
        kind = (cells.get("kind") or "").strip()
        order_id = cells.get("order_id")
        if not order_id or not order_id.strip() or kind not in (ORDER_ROW, SKU_ROW):
            continue
        ref = parse.order_ref(order_id, key)
        if kind == SKU_ROW:
            result.sku_rows += 1
            item = (cells.get("item_id") or "").strip()
            result.products.setdefault(ref, []).append(
                (
                    item if item.isdigit() else "",
                    (cells.get("variation") or "").strip()[:120],
                    _amount(cells.get("product_price"), label["product_price"]),
                )
            )
            continue
        result.order_rows += 1
        seen_orders[ref] += 1
        money_fields = {
            name: _amount(cells.get(name), label[name])
            for name in READ.values()
            if name not in ("kind", "order_id", "item_id", "variation", "ordered_on", "paid_on")
            and name != "transaction_fee_rate"
        }
        acc = sums.setdefault(ref, defaultdict(Decimal))
        for name, value in money_fields.items():
            acc[name] += value
        # Dates and the rate are the order's own (the first Order row states them).
        row = result.orders.setdefault(ref, {"order_ref": ref})
        ordered = _day(cells.get("ordered_on"), label["ordered_on"])
        paid = _day(cells.get("paid_on"), label["paid_on"])
        if ordered is not None:
            row.setdefault("ordered_on", ordered.isoformat())
        if paid is not None:
            row.setdefault("paid_on", paid.isoformat())
        rate_text = cells.get("transaction_fee_rate")
        if rate_text and rate_text.strip() not in ("", "-"):
            rate = _amount(rate_text, label["transaction_fee_rate"]) / 100
            if ZERO <= rate <= 1:
                row.setdefault("transaction_fee_rate", float(rate))

    for ref, row in result.orders.items():
        s = sums[ref]
        infra, xtra = fees.get(ref, (None, None))
        if infra is None:
            result.without_fee_details += 1
        if sum((s[name] for name in PAYOUT_PARTS), ZERO) != s["payout"]:
            result.unreconciled += 1
        ship_actual = -s["ship_actual"]
        net_shipping = (
            ship_actual - s["ship_shopee_subsidy"] - s["ship_buyer_paid"] - s["ship_piship_refund"]
        )
        row.update(
            {
                "payout": _num(s["payout"]),
                "product_price": _num(s["product_price"]),
                "refund_amount": _num(-s["refund"]),
                "fee_fixed": _num(-s["fee_fixed"]),
                "fee_service": _num(-s["fee_service"]),
                "fee_payment": _num(-s["fee_payment"]),
                "fee_piship": _num(-s["fee_piship"]),
                "fee_nttd": _num(-s["fee_nttd"]),
                "affiliate_commission": _num(-s["affiliate_commission"]),
                "ship_actual_cost": _num(ship_actual),
                "ship_shopee_subsidy": _num(s["ship_shopee_subsidy"]),
                "ship_buyer_paid": _num(s["ship_buyer_paid"]),
                "ship_piship_refund": _num(s["ship_piship_refund"]),
                "ship_seller_support": _num(abs(s["ship_seller_support"])),
                "net_shipping_cost": _num(net_shipping),
                "return_ship_refund": _num(-s["return_ship_refund"]),
                "return_ship_failed": _num(-s["return_ship_failed"]),
                "lost_compensation": _num(s["lost_compensation"]),
                "vat_withheld": _num(-s["vat_withheld"]),
                "pit_withheld": _num(-s["pit_withheld"]),
                "seller_voucher_borne": _num(-(s["voucher_seller"] + s["voucher_cofunded"])),
                "seller_coin_borne": _num(-(s["coin_seller"] + s["coin_cofunded"])),
                "trade_in_bonus_seller": _num(-s["trade_in_bonus_seller"]),
            }
        )
        if infra is not None and xtra is not None:
            row["fee_infra"] = _num(-infra)
            row["fee_voucher_xtra"] = _num(-xtra)

    totals = read_summary(path)
    for text, field_name in SUMMARY_FIELDS.items():
        if text in totals:
            ordered_sum = sum((sums[ref][field_name] for ref in sums), ZERO)
            result.recon.append(ReconRow(text, totals[text], ordered_sum))
    return result


def parse_income_export(path: Path, parsed: parse.Parsed) -> None:
    """``Income.T<m>.<from>_<to>.xlsx`` → ``order_income`` posts of at most 1 000 orders each,
    their period the file's own (the PAYOUT period: an order may have been placed earlier)."""
    key = parse._order_ref_key(parsed)
    income = read_income(path, key)
    rows = sorted(income.orders.values(), key=lambda r: (r.get("paid_on", ""), r["order_ref"]))
    captured = parse._captured_at(path)
    start, end = income.period
    for offset in range(0, len(rows), MAX_INCOME_ROWS):
        chunk = rows[offset : offset + MAX_INCOME_ROWS]
        parsed.posts.append(
            parse.Post(
                "order_income",
                parse._body(chunk, start, end, "period", None, captured),
                path.name,
            )
        )
    parsed.income_files.append(income)
    file = path.name
    parsed.notes[f"{file}: income orders read"] += income.order_rows
    parsed.notes[f"{file}: income product rows read"] += income.sku_rows
    if income.unreconciled:
        parsed.notes[f"{file}: orders whose payout is not the sum of their parts"] += (
            income.unreconciled
        )
    if income.without_fee_details:
        parsed.notes[f"{file}: orders without a Service Fee Details row"] += (
            income.without_fee_details
        )
    parsed.notes[f"{file}: columns never read (buyer, payment, tax code, names, voucher text)"] += (
        len(income.ignored_headers)
    )
