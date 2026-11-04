"""Synthetic income-export workbooks in the real layout (P91 D-12): the header rows are the real
ones (names only), every value, order id and name is invented.

``Doanh thu`` has three header rows (group titles, sub titles, column names), one ``Order`` row
per order and one ``Sku`` row per product. The buyer's columns carry CANARIES. The Summary sheet
starts with account lines (a canary), then the figures block the loader reconciles against.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from juli_backend.services.shop_inputs import xlsx_io

HEADER = [
    "Mã giao dịch",
    "Đơn hàng / Sản phẩm",
    "Mã đơn hàng",
    "Mã Số Thuế",
    "Mã yêu cầu hoàn tiền",
    "Mã sản phẩm",
    "Tên sản phẩm",
    "Ngày đặt hàng",
    "Ngày hoàn thành thanh toán",
    "Phương thức thanh toán",
    "Phân Loại",
    "Sản Phẩm Bán Chạy",
    "Tổng tiền đã thanh toán",
    "Giá sản phẩm",
    "Số tiền hoàn lại",
    "Phí vận chuyển Người mua trả",
    "Phí vận chuyển thực tế",
    "Phí vận chuyển được trợ giá từ Shopee",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
    "Phí vận chuyển được hoàn bởi PiShip",
    "Phí vận chuyển trả hàng (đơn giao không thành công)",
    "Sản phẩm được trợ giá từ Shopee",
    "Mã ưu đãi do Người Bán chịu",
    "Mã ưu đãi Đồng Tài Trợ do Người Bán chịu",
    "Mã hoàn xu do Người Bán chịu",
    "Mã hoàn xu Đồng Tài Trợ do Người Bán chịu",
    "Phí cố định",
    "Phí Dịch Vụ",
    "Phí xử lý giao dịch",
    "Phí hoa hồng Tiếp thị liên kết",
    "Phí dịch vụ PiShip",
    "Phí dịch vụ hiển thị NTTD (từ doanh thu đơn hàng)",
    "Thuế GTGT",
    "Thuế TNCN",
    "Phí lắp đặt người mua trả",
    "Phí lắp đặt thực tế",
    "Trade-in Bonus by Seller",
    "Người Mua",
    "Amount Paid By Buyer",
    "Transaction Fee Rate (%)",
    "Phương thức thanh toán của Người mua",
    "Buyer Payment Method Details_1",
    "Installment Plan (if applicable)",
    "Phí vận chuyển - Người bán hỗ trợ",
    "Đơn vị vận chuyển",
    "Courier Name",
    "Mã voucher",
    "Đền bù đơn mất hàng",
    "Giá sản phẩm (sau khuyến mãi)",
    "Shopee xu",
    "Shopee voucher",
    "Ngân hàng khuyến mãi thanh toán trên Thẻ Tín Dụng",
    "Shopee khuyến mãi thanh toán trên Thẻ Tín Dụng",
]

CANARY_BUYER = "CANARY-nguoi-mua-Nguyen-Thi-X"
CANARY_PAYMENT = "CANARY-thanh-toan-the-1234"
CANARY_TAX_CODE = "CANARY-0312345678"
CANARY_PRODUCT = "CANARY-ten-san-pham-bi-mat"
CANARY_VOUCHER = "CANARY-VOUCHER-TEXT"
CANARY_COURIER = "CANARY-Courier-Express"
CANARY_ACCOUNT = "CANARY-chu-tai-khoan-ngan-hang"
CANARIES = (
    CANARY_BUYER,
    CANARY_PAYMENT,
    CANARY_TAX_CODE,
    CANARY_PRODUCT,
    CANARY_VOUCHER,
    CANARY_COURIER,
    CANARY_ACCOUNT,
)

#: Columns that add up to the payout (signed, as the file states them).
PARTS = (
    "Giá sản phẩm",
    "Số tiền hoàn lại",
    "Phí vận chuyển Người mua trả",
    "Phí vận chuyển thực tế",
    "Phí vận chuyển được trợ giá từ Shopee",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
    "Phí vận chuyển được hoàn bởi PiShip",
    "Phí vận chuyển trả hàng (đơn giao không thành công)",
    "Mã ưu đãi do Người Bán chịu",
    "Mã ưu đãi Đồng Tài Trợ do Người Bán chịu",
    "Mã hoàn xu do Người Bán chịu",
    "Mã hoàn xu Đồng Tài Trợ do Người Bán chịu",
    "Phí cố định",
    "Phí Dịch Vụ",
    "Phí xử lý giao dịch",
    "Phí hoa hồng Tiếp thị liên kết",
    "Phí dịch vụ PiShip",
    "Phí dịch vụ hiển thị NTTD (từ doanh thu đơn hàng)",
    "Thuế GTGT",
    "Thuế TNCN",
    "Trade-in Bonus by Seller",
    "Đền bù đơn mất hàng",
)
SUMMARY_LABELS = [h for h in PARTS if h != "Giá sản phẩm"]


def _amount(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except ArithmeticError:  # a deliberately broken cell
        return Decimal(0)


def order_row(order_id: str, **values: object) -> dict[str, object]:
    """An ``Order`` row; ``Tổng tiền đã thanh toán`` is the signed sum of its parts unless given."""
    row: dict[str, object] = {
        "Mã giao dịch": "9001",
        "Đơn hàng / Sản phẩm": "Order",
        "Mã đơn hàng": order_id,
        "Mã Số Thuế": CANARY_TAX_CODE,
        "Mã yêu cầu hoàn tiền": "",
        "Mã sản phẩm": "-",
        "Tên sản phẩm": CANARY_PRODUCT,
        "Ngày đặt hàng": "2026-09-28",
        "Ngày hoàn thành thanh toán": "2026-10-03",
        "Phương thức thanh toán": CANARY_PAYMENT,
        "Phân Loại": "-",
        "Người Mua": CANARY_BUYER,
        "Amount Paid By Buyer": "123456",
        "Transaction Fee Rate (%)": "6.00",
        "Phương thức thanh toán của Người mua": CANARY_PAYMENT,
        "Buyer Payment Method Details_1": CANARY_PAYMENT,
        "Đơn vị vận chuyển": CANARY_COURIER,
        "Courier Name": CANARY_COURIER,
        "Mã voucher": CANARY_VOUCHER,
    }
    row.update(values)
    if "Tổng tiền đã thanh toán" not in values:
        row["Tổng tiền đã thanh toán"] = sum(_amount(row.get(p, 0)) for p in PARTS)
    return row


def sku_row(order_id: str, item_id: str, variation: str, price: int, **values: object) -> dict:
    """A ``Sku`` row: its own price, and return shipping with the OPPOSITE sign to the Order row."""
    row = order_row(
        order_id,
        **{
            "Đơn hàng / Sản phẩm": "Sku",
            "Mã sản phẩm": item_id,
            "Phân Loại": variation,
            "Giá sản phẩm": price,
            **values,
        },
    )
    return row


def _cell(value: object) -> object:
    if value is None or value == "":
        return None
    return value if isinstance(value, str) else str(value)


def doanh_thu(rows: list[dict[str, object]], header: list[str] | None = None) -> list[list[object]]:
    header = header or HEADER
    group: list[object] = [None] * len(header)
    group[0], group[12], group[37] = (
        "Thông tin đơn hàng",
        "Chi tiết doanh thu",
        "Thông tin người mua",
    )
    sub: list[object] = [None] * len(header)
    sub[12], sub[13], sub[26] = "Doanh thu đơn hàng", "Tổng tiền sản phẩm", "Phí giao dịch"
    return [group, sub, list(header), *[[_cell(r.get(h)) for h in header] for r in rows]]


def fee_details(entries: list[tuple[str, int, int]], *, spellings: int = 1) -> list[list[object]]:
    """``(order id, infrastructure fee, Voucher Xtra)`` rows under the two title rows. With
    ``spellings`` 2 the infrastructure fee has both headers (``Phí Hạ Tầng`` and ``Phí hạ tầng``),
    only the second filled."""
    if spellings == 2:
        header: list[object] = [
            "Mã giao dịch",
            "Mã đơn hàng",
            "Phí Hạ Tầng",
            "Phí hạ tầng",
            "Voucher Xtra",
        ]
    else:
        header = ["Mã giao dịch", "Mã đơn hàng", "Phí Hạ Tầng", "Voucher Xtra"]
    rows: list[list[object]] = [[None, None, "Phí Dịch Vụ"], header]
    for order_id, infra, xtra in entries:
        if spellings == 2:
            rows.append(["9001", order_id, None, str(infra), str(xtra)])
        else:
            rows.append(["9001", order_id, str(infra), str(xtra)])
    return rows


def summary(totals: dict[str, int], payout: int) -> list[list[object]]:
    rows: list[list[object]] = [["Bao cáo doanh thu"], [], [], [], ["Chi tiết báo cáo"]]
    rows.append(["Người Bán", "synthetic-shop"])
    rows.append(["Tên chủ tài khoản", CANARY_ACCOUNT])
    rows.append(["Tài khoản ngân hàng", "******0000"])
    rows.append(["Tên ngân hàng", "Bank"])
    rows.append(["Từ", "2026-10-01"])
    rows.append(["Đến", "2026-10-31"])
    rows.append(["Shop sẽ tự chịu trách nhiệm ..."])
    rows.append(["Thống kê thu nhập", None, None, "₫"])
    rows.append(["1. Tổng doanh thu", None, None, "0"])
    for label, value in totals.items():
        rows.append([None, label, str(value)])
    rows.append(["3. Tổng số tiền", None, None, str(payout)])
    return rows


def write_income(
    folder: Path,
    orders: list[dict[str, object]],
    *,
    fees: list[tuple[str, int, int]],
    name: str = "Income.T10.20261001_20261031.xlsx",
    spellings: int = 1,
    summary_override: dict[str, int] | None = None,
    extra_sheets: dict[str, list[list[object]]] | None = None,
    header: list[str] | None = None,
) -> Path:
    totals: dict[str, int] = {}
    payout = 0
    for row in orders:
        if row["Đơn hàng / Sản phẩm"] != "Order":
            continue
        payout += int(_amount(row["Tổng tiền đã thanh toán"]))
        for label in SUMMARY_LABELS:
            totals[label] = totals.get(label, 0) + int(_amount(row.get(label, 0)))
    totals.update(summary_override or {})
    sheets = [
        xlsx_io.SheetSpec("Summary", summary(totals, payout), freeze_header=False),
        xlsx_io.SheetSpec(
            "Service Fee Details", fee_details(fees, spellings=spellings), freeze_header=False
        ),
        xlsx_io.SheetSpec("Doanh thu", doanh_thu(orders, header), freeze_header=False),
    ]
    for sheet_name, sheet_rows in (extra_sheets or {}).items():
        sheets.append(xlsx_io.SheetSpec(sheet_name, sheet_rows, freeze_header=False))
    path = folder / name
    path.write_bytes(xlsx_io.write_workbook(sheets))
    return path
