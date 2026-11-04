"""The order export (Đơn hàng › Xuất, ``Order.all.<from>_<to>.xlsx``, sheet ``orders``) →
``order_lines`` posts, with the buyer's data never read (P90 step 2, G-03).

The file has 62 columns and one row per order LINE. Nine of them are buyer data (recipient,
phone, address, buyer name, comment, note, country, tracking id) and four more are
identifiers or free text. THE ALLOWLIST IS BY HEADER: the header row is read first, every
header must be in :data:`READ` (its value is used) or :data:`IGNORED` (known, its cells are
never decoded); any other header stops the load with ``UnknownColumn`` (Seller Centre changed
the export: fix the table here, never guess). Cells of unchosen columns are not touched (see
``xlsx.read_columns``), and the headers whose values WERE read are recorded in
``OrderExport.value_columns_read`` so a test can assert no buyer column was read.

The order id never leaves this module: it is hashed (``parse.order_ref``, the affiliate
lane's keyed HMAC) as each row is read. Errors name a column and a count, never a cell value.

Layout facts measured on ORY's October and November 2026 exports (``fasttrack/contracts/
p90-fields.md`` A19), asserted here on every load:

- the price, quantity and subsidy columns are per LINE; ``Giá ưu đãi`` x ``Số lượng`` is the
  line's GMV;
- every other money column (shop / Shopee voucher, combo, bank promotion, buyer shipping, the
  three fees, order value) is per ORDER and is REPEATED on each of the order's lines. The
  order's amount is the one distinct non-zero value; two different non-zero values on one
  order's lines raise :class:`OrderLayoutError`. The amount is then SPLIT across the lines by
  line GMV (largest remainder, to the cent), and the sums are asserted equal to the order's;
- fees are None unless the order carries profit (delivered / refund accepted) and at least one
  of the three is non-zero (an all-zero fee block is an export that has not settled yet).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts.shopee_exports import parse
from scripts.shopee_exports.xlsx import read_columns

SHEET = "orders"
CENT = Decimal("0.01")

#: header -> (field, scope). These are the ONLY columns whose cells are ever decoded.
READ: dict[str, tuple[str, str]] = {
    "Mã đơn hàng": ("order_id", "order"),
    "Ngày đặt hàng": ("ordered_at", "order"),
    "Trạng Thái Đơn Hàng": ("status", "order"),
    "Thời gian giao hàng": ("delivered_at", "order"),
    "Trạng thái Trả hàng/Hoàn tiền": ("return_status", "line"),
    "SKU sản phẩm": ("sku", "line"),
    "SKU phân loại hàng": ("variation_sku", "line"),
    "Giá gốc": ("original_price", "line"),
    "Được Shopee trợ giá": ("shopee_subsidy", "line"),
    "Tổng số tiền được người bán trợ giá": ("seller_subsidy", "line"),
    "Giá ưu đãi": ("deal_price", "line"),
    "Số lượng": ("qty", "line"),
    "Số lượng sản phẩm được hoàn trả": ("returned_qty", "line"),
    "Tổng giá trị đơn hàng (VND)": ("order_value", "order"),
    "Mã giảm giá của Shop": ("shop_voucher", "order"),
    "Mã giảm giá của Shopee": ("platform_voucher", "order"),
    "Giảm giá từ combo Shopee": ("shopee_combo", "order"),
    "Giảm giá từ Combo của Shop": ("shop_combo", "order"),
    "Số tiền được giảm khi thanh toán bằng thẻ Ghi nợ": ("bank_promo", "order"),
    "Phí vận chuyển mà người mua trả": ("buyer_shipping_fee", "order"),
    "Tổng số tiền người mua thanh toán": ("buyer_total", "order"),
    "Thời gian hoàn thành đơn hàng": ("completed_at", "order"),
    "Thời gian đơn hàng được thanh toán": ("paid_at", "order"),
    "Phí cố định": ("fee_fixed", "order"),
    "Phí Dịch Vụ": ("fee_service", "order"),
    "Phí xử lý giao dịch": ("fee_payment", "order"),
}

#: Known headers whose cells are NEVER decoded: buyer data, identifiers, free text, names, and
#: columns with no destination column (carrier, weights, coins, trade-in, payment method ...).
IGNORED: frozenset[str] = frozenset(
    {
        "Mã Kiện Hàng",
        "Sản Phẩm Bán Chạy",
        "Lý do hủy",
        "Nhận xét từ Người mua",
        "Mã vận đơn",
        "Đơn Vị Vận Chuyển",
        "Phương thức giao hàng",
        "Loại đơn hàng",
        "Ngày giao hàng dự kiến",
        "Ngày gửi hàng",
        "Tên sản phẩm",
        "Cân nặng sản phẩm",
        "Tổng cân nặng",
        "Tên phân loại hàng",
        "Người bán trợ giá",
        "Tổng số tiền Người mua thanh toán",
        "Hoàn Xu",
        "Chỉ tiêu Combo Khuyến Mãi",
        "Shopee Xu được hoàn",
        "Trade-in Discount",
        "Trade-in Bonus",
        "Phí vận chuyển (dự kiến)",
        "Trade-in Bonus by Seller",
        "Phí vận chuyển tài trợ bởi Shopee (dự kiến)",
        "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
        "Phương thức thanh toán",
        "Tiền ký quỹ",
        "Người Mua",
        "Tên Người nhận",
        "Số điện thoại",
        "Tỉnh/Thành phố",
        "TP / Quận / Huyện",
        "Quận",
        "Địa chỉ nhận hàng",
        "Quốc gia",
        "Ghi chú",
    }
)

#: Headers that must never have a value read, whatever else changes (the buyer's own data).
BUYER_HEADERS: frozenset[str] = frozenset(
    {
        "Mã Kiện Hàng",
        "Nhận xét từ Người mua",
        "Mã vận đơn",
        "Người Mua",
        "Tên Người nhận",
        "Số điện thoại",
        "Tỉnh/Thành phố",
        "TP / Quận / Huyện",
        "Quận",
        "Địa chỉ nhận hàng",
        "Quốc gia",
        "Ghi chú",
    }
)

#: Headers that must be present: without them a line cannot be formed.
REQUIRED = (
    "Mã đơn hàng",
    "Ngày đặt hàng",
    "Trạng Thái Đơn Hàng",
    "SKU sản phẩm",
    "Giá gốc",
    "Giá ưu đãi",
    "Số lượng",
)

ORDER_MONEY = (
    "order_value",
    "shop_voucher",
    "platform_voucher",
    "shopee_combo",
    "shop_combo",
    "bank_promo",
    "buyer_shipping_fee",
    "buyer_total",
    "fee_fixed",
    "fee_service",
    "fee_payment",
)

DELIVERED = "delivered"
CANCELLED = "cancelled"
IN_TRANSIT = "in_transit"
REFUNDED_ACCEPTED = "refunded_accepted"
REFUNDED_NOT_RECEIVED = "refunded_not_received"
PROFIT_STATUSES = frozenset({DELIVERED, REFUNDED_ACCEPTED})

#: Raw "Trạng Thái Đơn Hàng" (a date in the text is replaced by DATE) -> status. A buyer who
#: confirmed receipt may still ask for a return until a date: the order is delivered.
_STATUS_PREFIXES: tuple[tuple[str, str], ...] = (
    ("hoàn thành", DELIVERED),
    ("đã giao", DELIVERED),
    ("người mua xác nhận đã nhận được hàng", DELIVERED),
    ("đã hủy", CANCELLED),
    ("đang hủy", CANCELLED),
    ("chưa thanh toán", IN_TRANSIT),
    ("chờ xác nhận", IN_TRANSIT),
    ("chờ lấy hàng", IN_TRANSIT),
    ("chờ giao hàng", IN_TRANSIT),
    ("đang giao", IN_TRANSIT),
    ("đang vận chuyển", IN_TRANSIT),
    ("đang xử lý", IN_TRANSIT),
    ("cần xử lý", IN_TRANSIT),
    ("đã xử lý", IN_TRANSIT),
    ("đã gửi hàng", IN_TRANSIT),
    ("đang chuẩn bị", IN_TRANSIT),
)
_DATE_IN_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$")
_ACCEPTED = "chấp thuận"


class OrderLayoutError(ValueError):
    """The export's layout is not what this parser asserts (never carries a cell value)."""


class UnknownStatus(ValueError):
    """An order status the mapping does not know (a status string is not buyer data)."""


@dataclass
class OrderSummary:
    """Order-level totals kept for reconciliation; none of it is posted."""

    ref: str
    ordered_at: datetime
    status: str
    lines: int = 0
    order_value: Decimal = Decimal(0)
    buyer_total: Decimal = Decimal(0)
    gmv: Decimal = Decimal(0)
    shop_voucher: Decimal = Decimal(0)
    platform_voucher: Decimal = Decimal(0)
    paid: bool = False
    fees_filled: bool = False


@dataclass
class OrderExport:
    file: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    orders: dict[str, OrderSummary] = field(default_factory=dict)
    #: Normalised raw status text (dates replaced) -> lines.
    raw_status_counts: Counter[str] = field(default_factory=Counter)
    #: Headers whose cell values were decoded; never contains a buyer column.
    value_columns_read: set[str] = field(default_factory=set)
    ignored_headers: set[str] = field(default_factory=set)
    #: Sum of fee columns, per component (all lines' split amounts).
    fee_totals: dict[str, Decimal] = field(default_factory=dict)


def normal(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def map_status(raw: str, return_status: str | None, *, delivered: bool) -> str:
    """``OrderStatus`` value of a line from the order status text and the return status."""
    text = normal(raw).casefold()
    status = next((s for prefix, s in _STATUS_PREFIXES if text.startswith(prefix)), None)
    if status is None:
        raise UnknownStatus(_DATE_IN_TEXT.sub("DATE", normal(raw))[:120])
    if status != CANCELLED and return_status and _ACCEPTED in normal(return_status).casefold():
        return REFUNDED_ACCEPTED if delivered else REFUNDED_NOT_RECEIVED
    return status


def money(text: str | None, column: str) -> Decimal | None:
    if text is None or text.strip() in ("", "-"):
        return None
    cell = text.strip()
    if not _NUMBER.match(cell):
        raise OrderLayoutError(f"column {column!r}: a cell is not a plain number")
    value = Decimal(cell)
    if value.as_tuple().exponent < -2 and value != value.quantize(CENT):
        raise OrderLayoutError(f"column {column!r}: a cell has more than two decimals")
    return value


def stamp(text: str | None, column: str) -> datetime | None:
    if text is None or text.strip() in ("", "-"):
        return None
    match = _TIME.match(text.strip())
    if match is None:
        raise OrderLayoutError(f"column {column!r}: a cell is not a date and time")
    day, hour, minute, second = match.groups()
    return datetime.fromisoformat(f"{day}T{hour}:{minute}:{second or '00'}")


def _cents(value: Decimal) -> int:
    scaled = value * 100
    if scaled != scaled.to_integral_value():
        raise OrderLayoutError("an amount has more than two decimals")
    return int(scaled)


def split_by_weight(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """``total`` cut into cents proportional to ``weights`` (equal when all are zero); the
    pieces add up to ``total`` exactly. Integer arithmetic only (largest remainder, ties to the
    earlier line), so the browser module can reproduce it digit for digit."""
    count = len(weights)
    if count == 0:
        raise ValueError("no lines to split over")
    cents = _cents(total)
    shares = [_cents(w) for w in weights]
    if sum(shares) <= 0:
        shares = [1] * count
    weight_sum = sum(shares)
    parts = [divmod(cents * share, weight_sum) for share in shares]
    pieces = [quotient for quotient, _ in parts]
    left = cents - sum(pieces)
    for i in sorted(range(count), key=lambda i: (-parts[i][1], i))[:left]:
        pieces[i] += 1
    return [Decimal(piece) * CENT for piece in pieces]


def _choose(header: list[str]) -> set[int]:
    """The column indexes to read; stops on an unknown header or a missing required one."""
    names = [normal(h) for h in header]
    for name in names:
        if name not in READ and name not in IGNORED:
            raise parse.UnknownColumn(name)
    missing = [name for name in REQUIRED if name not in names]
    if missing:
        raise parse.UnknownColumn(f"missing column {missing[0]}")
    return {i for i, name in enumerate(names) if name in READ}


def _distinct(values: list[Decimal | None], column: str) -> Decimal:
    nonzero = {v for v in values if v}
    if len(nonzero) > 1:
        raise OrderLayoutError(f"column {column!r}: differs between the lines of one order")
    return next(iter(nonzero), Decimal(0))


def _first(values: list[Any], column: str) -> Any:
    present = {v for v in values if v is not None}
    if len(present) > 1:
        raise OrderLayoutError(f"column {column!r}: differs between the lines of one order")
    return next(iter(present), None)


def _num(value: Decimal | None) -> int | float:
    value = value or Decimal(0)
    return int(value) if value == value.to_integral_value() else float(value)


def read_order_export(path: Path, key: bytes) -> OrderExport:
    """Parse one export; raises ``UnknownColumn`` / ``OrderLayoutError`` / ``UnknownStatus``."""
    result = OrderExport(file=path.name)
    sheet = read_columns(path, SHEET, _choose)
    names = [normal(h) for h in sheet.header]
    result.ignored_headers = {n for n in names if n in IGNORED}
    result.value_columns_read = {names[i] for i in sheet.value_columns_read}
    column = {READ[name][0]: i for i, name in enumerate(names) if name in READ}
    label = {READ[name][0]: name for name in READ}

    raw_by_order: dict[str, list[dict[str, str | None]]] = defaultdict(list)
    for row in sheet.rows:
        cells = {name: row.get(idx) for name, idx in column.items()}
        order_id = cells["order_id"]
        if order_id is None or not order_id.strip():
            continue
        raw_by_order[parse.order_ref(order_id, key)].append(cells)

    for ref, cell_rows in raw_by_order.items():
        ordered = _first([stamp(c["ordered_at"], label["ordered_at"]) for c in cell_rows], "date")
        if ordered is None:
            raise OrderLayoutError(f"column {label['ordered_at']!r}: an order has no date")
        delivered = any(stamp(c.get("delivered_at"), "delivered") for c in cell_rows)
        completed = _first(
            [stamp(c.get("completed_at"), label["completed_at"]) for c in cell_rows], "c"
        )
        paid = _first([stamp(c.get("paid_at"), label["paid_at"]) for c in cell_rows], "p")
        order_level = {
            name: _distinct([money(c.get(name), label[name]) for c in cell_rows], label[name])
            for name in ORDER_MONEY
            if name in column
        }
        lines = []
        for cells in cell_rows:
            qty = money(cells["qty"], label["qty"]) or Decimal(0)
            if qty != qty.to_integral_value() or qty < 0:
                raise OrderLayoutError(f"column {label['qty']!r}: not a whole quantity")
            original = money(cells["original_price"], label["original_price"]) or Decimal(0)
            deal = money(cells["deal_price"], label["deal_price"]) or Decimal(0)
            status = map_status(
                cells["status"] or "",
                cells.get("return_status"),
                delivered=delivered or completed is not None,
            )
            result.raw_status_counts[_DATE_IN_TEXT.sub("DATE", normal(cells["status"] or ""))] += 1
            lines.append(
                {
                    "sku": (cells["sku"] or "").strip()[:120] or None,
                    "variation_sku": (cells.get("variation_sku") or "").strip()[:120] or None,
                    "qty": qty,
                    "returned_qty": money(cells.get("returned_qty"), label["returned_qty"])
                    or Decimal(0),
                    "original_price": original,
                    "deal_price": deal,
                    "seller_subsidy": money(cells.get("seller_subsidy"), label["seller_subsidy"])
                    or Decimal(0),
                    "shopee_subsidy": money(cells.get("shopee_subsidy"), label["shopee_subsidy"])
                    or Decimal(0),
                    "status": status,
                    "gmv": deal * qty,
                }
            )
        # Canonical numbering: independent of the order the export lists the lines in.
        lines.sort(
            key=lambda ln: (
                ln["sku"] or "",
                ln["variation_sku"] or "",
                ln["original_price"],
                ln["deal_price"],
                ln["qty"],
            )
        )
        weights = [ln["gmv"] for ln in lines]
        profit = any(ln["status"] in PROFIT_STATUSES for ln in lines)
        shares: dict[str, list[Decimal]] = {}
        for name in ("shop_voucher", "platform_voucher", "shopee_combo", "shop_combo"):
            shares[name] = split_by_weight(order_level.get(name, Decimal(0)), weights)
        for name in ("bank_promo", "buyer_shipping_fee"):
            shares[name] = split_by_weight(order_level.get(name, Decimal(0)), weights)
        fees_filled = profit and any(
            order_level.get(name) for name in ("fee_fixed", "fee_service", "fee_payment")
        )
        for name in ("fee_fixed", "fee_service", "fee_payment"):
            shares[name] = split_by_weight(order_level.get(name, Decimal(0)), weights)
        # Assert: every split adds up to the order's amount.
        for name, parts in shares.items():
            if sum(parts) != order_level.get(name, Decimal(0)):
                raise OrderLayoutError(f"column {label[name]!r}: split does not add up")

        summary = OrderSummary(
            ref=ref,
            ordered_at=ordered,
            status=lines[0]["status"],
            lines=len(lines),
            order_value=order_level.get("order_value", Decimal(0)),
            buyer_total=order_level.get("buyer_total", Decimal(0)),
            gmv=sum(weights, Decimal(0)),
            shop_voucher=order_level.get("shop_voucher", Decimal(0)),
            platform_voucher=order_level.get("platform_voucher", Decimal(0)),
            paid=paid is not None,
            fees_filled=bool(fees_filled),
        )
        result.orders[ref] = summary
        for number, ln in enumerate(lines):
            shop_voucher = shares["shop_voucher"][number]
            bundle = shares["shop_combo"][number]
            if bundle > 0:
                kind = "bundle"
            elif ln["seller_subsidy"] > 0 or ln["original_price"] > ln["deal_price"]:
                kind = "discount"
            elif shop_voucher > 0:
                kind = "voucher"
            else:
                kind = "none"
            row: dict[str, Any] = {
                "order_ref": ref,
                "line_no": number,
                "ordered_at": ordered.isoformat(timespec="seconds"),
                "status": ln["status"],
                "qty": _num(ln["qty"]),
                "returned_qty": _num(ln["returned_qty"]),
                "original_price": _num(ln["original_price"]),
                "deal_price": _num(ln["deal_price"]),
                "seller_subsidy": _num(ln["seller_subsidy"]),
                "shopee_subsidy": _num(ln["shopee_subsidy"]),
                "shop_voucher_share": _num(shop_voucher),
                "platform_voucher_share": _num(
                    shares["platform_voucher"][number] + shares["shopee_combo"][number]
                ),
                "bundle_discount": _num(bundle),
                "promo_kind": kind,
                "buyer_shipping_fee": _num(shares["buyer_shipping_fee"][number]),
                "bank_promo": _num(shares["bank_promo"][number]),
            }
            if ln["sku"]:
                row["sku"] = ln["sku"]
            if ln["variation_sku"]:
                row["variation_sku"] = ln["variation_sku"]
            if completed is not None:
                row["completed_at"] = completed.isoformat(timespec="seconds")
            if paid is not None:
                row["paid_at"] = paid.isoformat(timespec="seconds")
            if fees_filled:
                for name in ("fee_fixed", "fee_service", "fee_payment"):
                    amount = shares[name][number]
                    row[name] = _num(amount)
                    result.fee_totals[name] = result.fee_totals.get(name, Decimal(0)) + amount
            result.rows.append(row)
    return result


#: The columns of the second pass (``read_variation_names``): the line's identity and the
#: variation NAME, a product attribute ("Combo 3 hộp") that the main pass leaves undecoded.
VARIATION_COLUMNS = (
    "Mã đơn hàng",
    "SKU sản phẩm",
    "SKU phân loại hàng",
    "Tên phân loại hàng",
    "Giá gốc",
    "Giá ưu đãi",
    "Số lượng",
)
VARIATION_NAME_WIDTH = 120


def _line_signature(
    ref: str, sku: str | None, variation_sku: str | None, original: Decimal, deal: Decimal, qty: Any
) -> tuple[Any, ...]:
    return (ref, sku or None, variation_sku or None, Decimal(original), Decimal(deal), Decimal(qty))


def read_variation_names(path: Path, key: bytes) -> dict[tuple[Any, ...], list[str]]:
    """``(order_ref, sku, variation_sku, original price, deal price, qty)`` -> the variation
    names of the lines of that signature, in file order (P91 D-12).

    Combo variations share one SKU, so the name ("Combo 3 hộp") is what tells the packs apart.
    It is read in a pass of its own, over these seven columns only (``VARIATION_COLUMNS``), so
    the main pass - and the browser parser's parity with it - is unchanged. The name is a
    product attribute, not buyer data; the order id is hashed as it is read."""
    sheet = read_columns(
        path,
        SHEET,
        lambda header: {
            i for i, name in enumerate(normal(h) for h in header) if name in VARIATION_COLUMNS
        },
    )
    names = [normal(h) for h in sheet.header]
    column = {name: i for i, name in enumerate(names) if name in VARIATION_COLUMNS}
    if "Tên phân loại hàng" not in column or "Mã đơn hàng" not in column:
        return {}
    found: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for row in sheet.rows:
        order_id = row.get(column["Mã đơn hàng"])
        name = (row.get(column["Tên phân loại hàng"]) or "").strip()
        if not order_id or not order_id.strip() or not name:
            continue

        def amount(title: str, row: dict[int, str | None] = row) -> Decimal:
            idx = column.get(title)
            return (money(row.get(idx), title) if idx is not None else None) or Decimal(0)

        sku_idx, var_idx = column.get("SKU sản phẩm"), column.get("SKU phân loại hàng")
        signature = _line_signature(
            parse.order_ref(order_id, key),
            (row.get(sku_idx) or "").strip()[:120] if sku_idx is not None else None,
            (row.get(var_idx) or "").strip()[:120] if var_idx is not None else None,
            amount("Giá gốc"),
            amount("Giá ưu đãi"),
            amount("Số lượng"),
        )
        found[signature].append(name[:VARIATION_NAME_WIDTH])
    return dict(found)


def add_variation_names(rows: list[dict[str, Any]], names: dict[tuple[Any, ...], list[str]]) -> int:
    """Put ``variation_name`` on the posted rows whose signature has one; twins (same signature)
    take the names in line order. Returns how many rows got a name."""
    taken: Counter[tuple[Any, ...]] = Counter()
    named = 0
    for row in sorted(rows, key=lambda r: (r["order_ref"], r["line_no"])):
        signature = _line_signature(
            row["order_ref"],
            row.get("sku"),
            row.get("variation_sku"),
            Decimal(str(row["original_price"])),
            Decimal(str(row["deal_price"])),
            row["qty"],
        )
        candidates = names.get(signature)
        if not candidates:
            continue
        row["variation_name"] = candidates[min(taken[signature], len(candidates) - 1)]
        taken[signature] += 1
        named += 1
    return named


def parse_order_export(path: Path, parsed: parse.Parsed) -> None:
    """``Order.all.<from>_<to>.xlsx`` → ``order_lines`` posts, one per order month (≤ 1 000
    lines each)."""
    key = parse._order_ref_key(parsed)
    export = read_order_export(path, key)
    named = add_variation_names(export.rows, read_variation_names(path, key))
    file = path.name
    by_month: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in export.rows:
        by_month[date.fromisoformat(row["ordered_at"][:10]).replace(day=1)].append(row)
    captured = parse._captured_at(path)
    for _, rows in sorted(by_month.items()):
        rows.sort(key=lambda r: (r["ordered_at"], r["order_ref"], r["line_no"]))
        for offset in range(0, len(rows), parse.MAX_ORDER_LINE_ROWS):
            chunk = rows[offset : offset + parse.MAX_ORDER_LINE_ROWS]
            chunk_days = sorted(date.fromisoformat(r["ordered_at"][:10]) for r in chunk)
            parsed.posts.append(
                parse.Post(
                    "order_lines",
                    parse._body(chunk, chunk_days[0], chunk_days[-1], "period", None, captured),
                    file,
                )
            )
    parsed.notes[f"{file}: order lines read"] += len(export.rows)
    parsed.notes[f"{file}: orders read"] += len(export.orders)
    parsed.notes[f"{file}: order lines with a variation name"] += named
    parsed.notes[f"{file}: columns never read (buyer data, identifiers, free text, names)"] += len(
        export.ignored_headers
    )
