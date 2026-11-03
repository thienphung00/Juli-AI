"""P90 step 2: the order export parser (``scripts/shopee_exports/orders.py``).

Synthetic workbooks in the real export's layout: 62 columns, one row per order LINE, the
headers captured from ORY's export (names only), every value invented. The buyer's columns
carry CANARIES. Checks:

- a header allowlist: the buyer columns are never decoded (a cell that would raise if decoded
  proves it), no canary reaches any post, summary, note or error;
- an unknown header, or a missing required one, stops the load;
- the order id becomes the affiliate lane's keyed hash;
- status mapping (order status + return status);
- order-level amounts repeated on each line are split by line value and the sums asserted;
- fees are None unless the order carries profit and a fee column is filled;
- line numbers do not depend on the row order of the export;
- the posts pass the gateway's own validation and land in ``shopee_order_lines`` (SQLite), the
  affiliate lane marks them, and a re-load moves a status without erasing a fee.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.ingest.gateway import validate_rows
from juli_backend.services.ingest.mapping import dataset_spec
from juli_backend.services.ingest.schemas import IngestBody
from scripts import load_shopee_exports
from scripts.shopee_exports import orders, parse
from scripts.shopee_exports.xlsx import read_columns
from tests.unit.test_shopee_affiliate_loader import CONVERSION_HEADER, _write_csv
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop

KEY = b"synthetic-order-ref-key"

#: The real header row, in the real order (62 columns).
HEADER = [
    "Mã đơn hàng",
    "Mã Kiện Hàng",
    "Ngày đặt hàng",
    "Trạng Thái Đơn Hàng",
    "Sản Phẩm Bán Chạy",
    "Lý do hủy",
    "Nhận xét từ Người mua",
    "Mã vận đơn",
    "Đơn Vị Vận Chuyển",
    "Phương thức giao hàng",
    "Loại đơn hàng",
    "Ngày giao hàng dự kiến",
    "Ngày gửi hàng",
    "Thời gian giao hàng",
    "Trạng thái Trả hàng/Hoàn tiền",
    "SKU sản phẩm",
    "Tên sản phẩm",
    "Cân nặng sản phẩm",
    "Tổng cân nặng",
    "SKU phân loại hàng",
    "Tên phân loại hàng",
    "Giá gốc",
    "Người bán trợ giá",
    "Được Shopee trợ giá",
    "Tổng số tiền được người bán trợ giá",
    "Giá ưu đãi",
    "Số lượng",
    "Số lượng sản phẩm được hoàn trả",
    "Tổng số tiền Người mua thanh toán",
    "Tổng giá trị đơn hàng (VND)",
    "Mã giảm giá của Shop",
    "Hoàn Xu",
    "Mã giảm giá của Shopee",
    "Chỉ tiêu Combo Khuyến Mãi",
    "Giảm giá từ combo Shopee",
    "Giảm giá từ Combo của Shop",
    "Shopee Xu được hoàn",
    "Số tiền được giảm khi thanh toán bằng thẻ Ghi nợ",
    "Trade-in Discount",
    "Trade-in Bonus",
    "Phí vận chuyển (dự kiến)",
    "Trade-in Bonus by Seller",
    "Phí vận chuyển mà người mua trả",
    "Phí vận chuyển tài trợ bởi Shopee (dự kiến)",
    "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
    "Tổng số tiền người mua thanh toán",
    "Thời gian hoàn thành đơn hàng",
    "Thời gian đơn hàng được thanh toán",
    "Phương thức thanh toán",
    "Phí cố định",
    "Phí Dịch Vụ",
    "Phí xử lý giao dịch",
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
]

CANARY_BUYER = "CANARY-nguoi-mua-Tran-Thi-B"
CANARY_RECIPIENT = "CANARY-nguoi-nhan-Le-Van-C"
CANARY_PHONE = "CANARY-0909123456"
CANARY_ADDRESS = "CANARY-12-duong-Nguyen-Hue"
CANARY_CITY = "CANARY-TP-Ho-Chi-Minh"
CANARY_COMMENT = "CANARY-binh-luan-giao-gio-hanh-chinh"
CANARY_TRACKING = "CANARY-SPXVN0123456789"
CANARY_PACKAGE = "CANARY-PKG-77"
CANARY_NOTE = "CANARY-ghi-chu-noi-bo"
CANARY_PRODUCT_NAME = "CANARY-ten-san-pham-bi-mat"
ORDER_A = "2610AAAAAA0001"
ORDER_B = "2610BBBBBB0002"
ORDER_C = "2610CCCCCC0003"
CANARIES = (
    CANARY_BUYER,
    CANARY_RECIPIENT,
    CANARY_PHONE,
    CANARY_ADDRESS,
    CANARY_CITY,
    CANARY_COMMENT,
    CANARY_TRACKING,
    CANARY_PACKAGE,
    CANARY_NOTE,
    CANARY_PRODUCT_NAME,
)


def _line(order_id: str, **over: str) -> dict[str, str]:
    """One synthetic line keyed by header; ``over`` replaces a header's value."""
    base = dict.fromkeys(HEADER, "0.00")
    base.update(
        {
            "Mã đơn hàng": order_id,
            "Mã Kiện Hàng": CANARY_PACKAGE,
            "Ngày đặt hàng": "2026-10-05 10:15",
            "Trạng Thái Đơn Hàng": "Hoàn thành",
            "Sản Phẩm Bán Chạy": "N",
            "Lý do hủy": "",
            "Nhận xét từ Người mua": CANARY_COMMENT,
            "Mã vận đơn": CANARY_TRACKING,
            "Đơn Vị Vận Chuyển": "Giao Hàng Nhanh",
            "Phương thức giao hàng": "Nhanh",
            "Loại đơn hàng": "",
            "Ngày giao hàng dự kiến": "2026-10-08",
            "Ngày gửi hàng": "2026-10-06",
            "Thời gian giao hàng": "2026-10-07 09:00",
            "Trạng thái Trả hàng/Hoàn tiền": "",
            "SKU sản phẩm": "SKU-A",
            "Tên sản phẩm": CANARY_PRODUCT_NAME,
            "SKU phân loại hàng": "SKU-A-1",
            "Tên phân loại hàng": CANARY_PRODUCT_NAME,
            "Giá gốc": "100000.00",
            "Giá ưu đãi": "90000.00",
            "Số lượng": "1",
            "Số lượng sản phẩm được hoàn trả": "0",
            "Tổng số tiền được người bán trợ giá": "10000.00",
            "Chỉ tiêu Combo Khuyến Mãi": "N",
            "Thời gian hoàn thành đơn hàng": "2026-10-09 12:00",
            "Thời gian đơn hàng được thanh toán": "2026-10-05 10:20",
            "Phương thức thanh toán": "COD",
            "Người Mua": CANARY_BUYER,
            "Tên Người nhận": CANARY_RECIPIENT,
            "Số điện thoại": CANARY_PHONE,
            "Tỉnh/Thành phố": CANARY_CITY,
            "TP / Quận / Huyện": CANARY_CITY,
            "Quận": CANARY_CITY,
            "Địa chỉ nhận hàng": CANARY_ADDRESS,
            "Quốc gia": "VN",
            "Ghi chú": CANARY_NOTE,
        }
    )
    base.update(over)
    return base


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _write_orders(
    path: Path,
    lines: list[dict[str, str]],
    *,
    header: list[str] | None = None,
    shared: bool = False,
    poison_buyer_cells: bool = False,
) -> Path:
    """A workbook with sheet ``orders``. ``shared`` stores strings in ``sharedStrings.xml`` like
    Excel; ``poison_buyer_cells`` makes every buyer cell reference a shared string that does not
    exist: decoding such a cell would raise, so loading proves it was never touched."""
    header = header or HEADER
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    strings: list[str] = []

    def cell(ref: str, value: str, name: str) -> str:
        if poison_buyer_cells and name in orders.BUYER_HEADERS:
            return f'<c r="{ref}" t="s"><v>99999</v></c>'
        if shared:
            strings.append(value)
            return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'

    body = []
    head = "".join(cell(f"{_col(c)}1", h, "") for c, h in enumerate(header))
    body.append(f'<row r="1">{head}</row>')
    for r, line in enumerate(lines, start=2):
        cells = "".join(
            cell(f"{_col(c)}{r}", line.get(name, ""), name) for c, name in enumerate(header)
        )
        body.append(f'<row r="{r}">{cells}</row>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{main}"><sheetData>{"".join(body)}</sheetData></worksheet>',
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
            '<sheet name="orders" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            "</Relationships>",
        )
        if shared or poison_buyer_cells:
            items = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
            archive.writestr("xl/sharedStrings.xml", f'<sst xmlns="{main}">{items}</sst>')
    return path


def _workbook(tmp_path: Path, lines: list[dict[str, str]], **kw) -> Path:
    return _write_orders(tmp_path / "Order.all.20261001_20261031.xlsx", lines, **kw)


def _by_ref(export: orders.OrderExport, order_id: str) -> list[dict]:
    ref = parse.order_ref(order_id, KEY)
    return sorted((r for r in export.rows if r["order_ref"] == ref), key=lambda r: r["line_no"])


# --- PII


@pytest.mark.parametrize("shared", [False, True])
def test_a_buyer_cell_is_never_decoded_and_no_canary_reaches_any_output(tmp_path, shared):
    path = _workbook(
        tmp_path,
        [_line(ORDER_A), _line(ORDER_B, **{"SKU sản phẩm": "SKU-B"})],
        shared=shared,
        poison_buyer_cells=True,
    )
    export = orders.read_order_export(path, KEY)  # would raise if a buyer cell were decoded
    assert export.value_columns_read <= set(orders.READ)
    assert not export.value_columns_read & orders.BUYER_HEADERS
    assert len(export.value_columns_read) == len(orders.READ)
    assert export.ignored_headers == set(HEADER) - set(orders.READ)
    assert len(HEADER) == len(orders.READ) + len(orders.IGNORED) == 62


def test_no_canary_in_any_post_summary_note_or_error(tmp_path):
    path = _workbook(tmp_path, [_line(ORDER_A), _line(ORDER_B)])
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    everything = (
        json.dumps([p.body for p in parsed.posts], ensure_ascii=False)
        + load_shopee_exports.summary(parsed)
        + json.dumps(dict(parsed.notes), ensure_ascii=False)
        + repr(orders.read_order_export(path, KEY).rows)
    )
    for canary in (*CANARIES, ORDER_A, ORDER_B):
        assert canary not in everything
    assert [p.dataset for p in parsed.posts] == ["order_lines"]
    assert parsed.notes["Order.all.20261001_20261031.xlsx: order lines read"] == 2


def test_an_error_names_a_column_never_a_cell_value(tmp_path):
    bad = _line(ORDER_A, **{"Giá gốc": CANARY_PHONE})
    path = _workbook(tmp_path, [bad])
    with pytest.raises(orders.OrderLayoutError) as stopped:
        orders.read_order_export(path, KEY)
    assert CANARY_PHONE not in str(stopped.value) and "Giá gốc" in str(stopped.value)


def test_an_unknown_header_stops_before_any_value_is_read(tmp_path):
    header = [*HEADER, "Email người mua"]
    path = _workbook(tmp_path, [_line(ORDER_A, **{"Email người mua": CANARY_BUYER})], header=header)
    with pytest.raises(parse.UnknownColumn, match="Email người mua") as stopped:
        parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert CANARY_BUYER not in str(stopped.value)
    assert path.exists()


def test_a_missing_required_header_stops_the_load(tmp_path):
    header = [h for h in HEADER if h != "Giá ưu đãi"]
    _workbook(tmp_path, [_line(ORDER_A)], header=header)
    with pytest.raises(parse.UnknownColumn, match="Giá ưu đãi"):
        parse.parse_folder(tmp_path, order_ref_key=KEY)


def test_the_header_allowlist_and_buyer_set_cover_the_real_export_exactly():
    assert set(HEADER) == set(orders.READ) | orders.IGNORED
    assert orders.BUYER_HEADERS <= orders.IGNORED
    # Columns 2, 7, 8 and 54-62 of the contract are all in the never-read set.
    never = {HEADER[i - 1] for i in (2, 7, 8, *range(54, 63))}
    assert never <= orders.IGNORED and not never & set(orders.READ)


def test_read_columns_touches_only_the_chosen_columns(tmp_path):
    path = _workbook(tmp_path, [_line(ORDER_A)], poison_buyer_cells=True)
    sheet = read_columns(path, "orders", lambda header: {0})
    assert sheet.value_columns_read == {0}
    assert set(sheet.rows[0]) == {0}


# --- hashing


def test_the_order_id_is_the_affiliate_lanes_keyed_hash(tmp_path):
    _workbook(tmp_path, [_line(ORDER_A), _line(ORDER_A, **{"SKU sản phẩm": "SKU-B"})])
    export = orders.read_order_export(next(tmp_path.iterdir()), KEY)
    ref = parse.order_ref(ORDER_A, KEY)
    assert {r["order_ref"] for r in export.rows} == {ref}
    assert re.fullmatch(r"[0-9a-f]{32}", ref)
    assert ref != parse.order_ref(ORDER_A, b"another shop's key")
    assert set(export.orders) == {ref}


def test_the_browser_hash_algorithm_vector_is_pinned():
    # The same message, key and expected digest are pinned in the TypeScript module's test
    # (apps/demo/src/lib/ops/orders/order-ref.test.ts): HMAC-SHA256("shopee-order|" +
    # id.trim().upper(), key), first 32 hex characters.
    assert parse.order_ref("  2610aaaaaa0001 ", b"key") == parse.order_ref("2610AAAAAA0001", b"key")
    assert parse.order_ref("2610AAAAAA0001", b"key") == "45fc017608554811b91b3b4040801ee2"
    assert (
        parse.order_ref("2610ABCDEF0001", b"synthetic-shop-key")
        == "7a067ff446e9d13be7ce845574683cfb"
    )


# --- status


@pytest.mark.parametrize(
    ("raw", "returned", "delivered", "expected"),
    [
        ("Hoàn thành", "", True, "delivered"),
        ("Đã giao", None, True, "delivered"),
        (
            "Người mua xác nhận đã nhận được hàng, tuy nhiên Người mua vẫn có thể gửi yêu cầu "
            "Trả hàng/Hoàn tiền tới ngày 2026-11-07.",
            "",
            True,
            "delivered",
        ),
        ("Đã hủy", "", False, "cancelled"),
        ("Đã hủy", "Đã Chấp Thuận Yêu Cầu", False, "cancelled"),
        ("Đang giao", "", False, "in_transit"),
        ("Chờ lấy hàng", "", False, "in_transit"),
        ("Hoàn thành", "Đã Chấp Thuận Yêu Cầu", True, "refunded_accepted"),
        ("Hoàn thành", "Đã Chấp Thuận Yêu Cầu", False, "refunded_not_received"),
        ("Hoàn thành", "Yêu Cầu Đang Chờ", True, "delivered"),
    ],
)
def test_status_mapping(raw, returned, delivered, expected):
    assert orders.map_status(raw, returned, delivered=delivered) == expected


def test_an_unknown_status_stops_and_names_the_status_text_only():
    with pytest.raises(orders.UnknownStatus) as stopped:
        orders.map_status("Trạng thái lạ tới ngày 2026-11-07", None, delivered=False)
    assert "DATE" in str(stopped.value) and "2026-11-07" not in str(stopped.value)


def test_raw_status_counts_are_kept_without_dates(tmp_path):
    long = "Người mua xác nhận đã nhận được hàng, tuy nhiên Người mua vẫn có thể gửi yêu cầu "
    _workbook(
        tmp_path,
        [
            _line(
                ORDER_A, **{"Trạng Thái Đơn Hàng": f"{long}Trả hàng/Hoàn tiền tới ngày 2026-11-07."}
            ),
            _line(
                ORDER_B, **{"Trạng Thái Đơn Hàng": f"{long}Trả hàng/Hoàn tiền tới ngày 2026-11-13."}
            ),
            _line(ORDER_C, **{"Trạng Thái Đơn Hàng": "Đã hủy"}),
        ],
    )
    export = orders.read_order_export(next(tmp_path.iterdir()), KEY)
    assert sorted(export.raw_status_counts.values()) == [1, 2]
    assert all("2026-11" not in text for text in export.raw_status_counts)


# --- splitting


def test_split_by_weight_adds_up_exactly():
    parts = orders.split_by_weight(Decimal("1000.00"), [Decimal(1), Decimal(1), Decimal(1)])
    assert sum(parts) == Decimal("1000.00") and sorted(parts) == [
        Decimal("333.33"),
        Decimal("333.33"),
        Decimal("333.34"),
    ]
    assert orders.split_by_weight(Decimal("5"), [Decimal(0), Decimal(0)]) == [
        Decimal("2.50"),
        Decimal("2.50"),
    ]
    assert orders.split_by_weight(Decimal(0), [Decimal(7)]) == [Decimal(0)]
    weights = [Decimal(3), Decimal(2)]
    assert orders.split_by_weight(Decimal("100.00"), weights) == [
        Decimal("60.00"),
        Decimal("40.00"),
    ]


def _multi_line_order(order_id: str = ORDER_A, **order_level: str) -> list[dict[str, str]]:
    """Two lines (GMV 270.000 and 90.000), order-level amounts REPEATED on both."""
    shared = {
        "Tổng giá trị đơn hàng (VND)": "350000.00",
        "Mã giảm giá của Shop": "4000.00",
        "Mã giảm giá của Shopee": "9000.00",
        "Giảm giá từ Combo của Shop": "0.00",
        "Số tiền được giảm khi thanh toán bằng thẻ Ghi nợ": "1000.00",
        "Phí vận chuyển mà người mua trả": "20000.00",
        "Phí cố định": "40000.00",
        "Phí Dịch Vụ": "10000.00",
        "Phí xử lý giao dịch": "22000.00",
        **order_level,
    }
    return [
        _line(
            order_id,
            **{"Giá ưu đãi": "90000.00", "Số lượng": "3", "SKU sản phẩm": "SKU-A", **shared},
        ),
        _line(
            order_id,
            **{"Giá ưu đãi": "90000.00", "Số lượng": "1", "SKU sản phẩm": "SKU-B", **shared},
        ),
    ]


def test_order_level_amounts_repeated_on_each_line_are_split_by_line_value(tmp_path):
    _workbook(tmp_path, _multi_line_order())
    export = orders.read_order_export(next(tmp_path.iterdir()), KEY)
    first, second = _by_ref(export, ORDER_A)
    assert (first["sku"], second["sku"]) == ("SKU-A", "SKU-B")
    # 270.000 : 90.000 = 3 : 1
    assert (first["shop_voucher_share"], second["shop_voucher_share"]) == (3000, 1000)
    assert (first["platform_voucher_share"], second["platform_voucher_share"]) == (6750, 2250)
    assert (first["bank_promo"], second["bank_promo"]) == (750, 250)
    assert (first["buyer_shipping_fee"], second["buyer_shipping_fee"]) == (15000, 5000)
    assert (first["fee_fixed"], second["fee_fixed"]) == (30000, 10000)
    assert (first["fee_service"], second["fee_service"]) == (7500, 2500)
    assert (first["fee_payment"], second["fee_payment"]) == (16500, 5500)
    for name, total in (
        ("shop_voucher_share", 4000),
        ("fee_payment", 22000),
        ("buyer_shipping_fee", 20000),
    ):
        assert first[name] + second[name] == total
    assert first["promo_kind"] == "discount"  # original 100.000 > deal 90.000
    summary = next(iter(export.orders.values()))
    assert (summary.lines, summary.gmv, summary.order_value) == (
        2,
        Decimal(360000),
        Decimal(350000),
    )
    assert summary.shop_voucher == Decimal(4000) and summary.fees_filled and summary.paid


def test_a_voucher_only_on_the_first_line_is_the_same_order_amount(tmp_path):
    lines = _multi_line_order()
    lines[1]["Mã giảm giá của Shop"] = "0.00"
    _workbook(tmp_path, lines)
    first, second = _by_ref(orders.read_order_export(next(tmp_path.iterdir()), KEY), ORDER_A)
    assert first["shop_voucher_share"] + second["shop_voucher_share"] == 4000


def test_two_different_amounts_on_one_orders_lines_stop_the_load(tmp_path):
    lines = _multi_line_order()
    lines[1]["Phí cố định"] = "41000.00"
    _workbook(tmp_path, lines)
    with pytest.raises(orders.OrderLayoutError, match="Phí cố định"):
        orders.read_order_export(next(tmp_path.iterdir()), KEY)


def test_a_shop_combo_makes_the_line_a_bundle_and_precedence_is_combo_discount_voucher(tmp_path):
    lines = [
        _line(ORDER_A, **{"Giảm giá từ Combo của Shop": "5000.00"}),
        _line(
            ORDER_B,
            **{
                "Mã giảm giá của Shop": "2000.00",
                "Giá gốc": "90000.00",
                "Tổng số tiền được người bán trợ giá": "0.00",
            },
        ),
        _line(ORDER_C, **{"Giá gốc": "90000.00", "Tổng số tiền được người bán trợ giá": "0.00"}),
    ]
    _workbook(tmp_path, lines)
    export = orders.read_order_export(next(tmp_path.iterdir()), KEY)
    kinds = {o: _by_ref(export, o)[0]["promo_kind"] for o in (ORDER_A, ORDER_B, ORDER_C)}
    assert kinds == {ORDER_A: "bundle", ORDER_B: "voucher", ORDER_C: "none"}
    assert _by_ref(export, ORDER_A)[0]["bundle_discount"] == 5000


def test_seller_and_shopee_subsidy_and_returns_are_kept(tmp_path):
    _workbook(
        tmp_path,
        [
            _line(
                ORDER_A,
                **{
                    "Số lượng": "2",
                    "Số lượng sản phẩm được hoàn trả": "1",
                    "Tổng số tiền được người bán trợ giá": "20000.00",
                    "Được Shopee trợ giá": "3000.00",
                },
            )
        ],
    )
    (line,) = _by_ref(orders.read_order_export(next(tmp_path.iterdir()), KEY), ORDER_A)
    assert (line["qty"], line["returned_qty"]) == (2, 1)
    assert (line["seller_subsidy"], line["shopee_subsidy"]) == (20000, 3000)
    assert (
        line["completed_at"] == "2026-10-09T12:00:00" and line["paid_at"] == "2026-10-05T10:20:00"
    )


# --- fees


def test_fees_are_none_unless_the_order_carries_profit_and_a_fee_is_filled(tmp_path):
    fees = {"Phí cố định": "4000.00", "Phí xử lý giao dịch": "2000.00"}
    _workbook(
        tmp_path,
        [
            _line(ORDER_A, **fees),  # delivered, filled
            _line(ORDER_B),  # delivered, every fee column 0.00: not settled yet
            _line(ORDER_C, **{**fees, "Trạng Thái Đơn Hàng": "Đã hủy"}),  # cancelled
        ],
    )
    export = orders.read_order_export(next(tmp_path.iterdir()), KEY)
    a, b, c = (_by_ref(export, o)[0] for o in (ORDER_A, ORDER_B, ORDER_C))
    assert (a["fee_fixed"], a["fee_service"], a["fee_payment"]) == (4000, 0, 2000)
    assert not {"fee_fixed", "fee_service", "fee_payment"} & set(b)
    assert not {"fee_fixed", "fee_service", "fee_payment"} & set(c)
    assert export.fee_totals == {"fee_fixed": 4000, "fee_service": 0, "fee_payment": 2000}


def test_a_dash_or_missing_settlement_time_is_none(tmp_path):
    _workbook(
        tmp_path,
        [
            _line(
                ORDER_A,
                **{"Thời gian đơn hàng được thanh toán": "-", "Thời gian hoàn thành đơn hàng": ""},
            )
        ],
    )
    (line,) = _by_ref(orders.read_order_export(next(tmp_path.iterdir()), KEY), ORDER_A)
    assert "paid_at" not in line and "completed_at" not in line


# --- numbering


def test_line_numbers_do_not_depend_on_the_row_order_of_the_export(tmp_path):
    lines = _multi_line_order()
    _write_orders(tmp_path / "Order.all.20261001_20261031.xlsx", lines)
    _write_orders(tmp_path / "Order.all.20261101_20261130.xlsx", list(reversed(lines)))
    one = orders.read_order_export(tmp_path / "Order.all.20261001_20261031.xlsx", KEY)
    two = orders.read_order_export(tmp_path / "Order.all.20261101_20261130.xlsx", KEY)
    assert sorted(one.rows, key=lambda r: r["line_no"]) == sorted(
        two.rows, key=lambda r: r["line_no"]
    )


# --- posts and the gateway


def _posts(tmp_path: Path, lines: list[dict[str, str]]):
    _workbook(tmp_path, lines)
    return parse.parse_folder(tmp_path, order_ref_key=KEY)


def test_posts_are_one_per_order_month_and_pass_the_gateways_validation(tmp_path):
    lines = [
        _line(ORDER_A),
        _line(ORDER_B, **{"Ngày đặt hàng": "2026-11-01 08:00"}),
    ]
    parsed = _posts(tmp_path, lines)
    assert [p.dataset for p in parsed.posts] == ["order_lines", "order_lines"]
    assert [p.body["period"]["start"] for p in parsed.posts] == ["2026-10-05", "2026-11-01"]
    spec = dataset_spec("shopee", "order_lines")
    assert spec is not None
    for post in parsed.posts:
        validate_rows(
            spec, IngestBody.model_validate(post.body), datetime.now(UTC).replace(tzinfo=None)
        )
    assert "order_type" not in parsed.posts[0].body


def test_order_lines_are_posted_before_the_affiliate_lane(tmp_path):
    _write_csv(
        tmp_path / "SellerConversionReport_202611022133.csv",
        [CONVERSION_HEADER, _conversion_row(ORDER_A, "1001", "2026-10-05 10:15:00", cost="900")],
    )
    parsed = _posts(tmp_path, [_line(ORDER_A)])
    assert [p.dataset for p in parsed.posts] == ["order_lines", "affiliate_order_lines"]


def _conversion_row(order_id: str, item_id: str, when: str, *, cost: str) -> list[str]:
    row = dict.fromkeys(CONVERSION_HEADER, "")
    row.update(
        {
            "Mã đơn hàng": order_id,
            "Trạng thái đơn hàng": "Hoàn thành",
            "Trạng thái gian lận": "Hợp lệ",
            "Thời gian đặt hàng": when,
            "Mã sản phẩm": item_id,
            "Model id": "",
            "Giá(₫)": "90000",
            "Số lượng": "1",
            "Chi phí(₫)": cost,
        }
    )
    return [row[h] for h in CONVERSION_HEADER]


async def test_order_lines_land_in_the_table_and_a_reload_moves_status_without_erasing_fees(
    session, tmp_path
):
    shop = await _shop(session)
    fees = {"Phí cố định": "4000.00", "Phí xử lý giao dịch": "2000.00"}
    parsed = _posts(tmp_path, [_line(ORDER_A, **fees), *_multi_line_order(ORDER_B)])
    (post,) = parsed.posts
    body = {**post.body, "captured_at": "2026-10-29T09:30:00+07:00"}
    await _ingest(session, shop, "order_lines", body)
    stored = await _rows(session, ShopeeOrderLine, shop)
    assert len(stored) == 3 and {s.platform for s in stored} == {"shopee"}
    assert all(s.order_ref == s.order_ref.lower() and len(s.order_ref) == 32 for s in stored)
    one = next(s for s in stored if s.order_ref == parse.order_ref(ORDER_A, KEY))
    assert (one.qty, one.original_price, one.deal_price) == (1, Decimal(100000), Decimal(90000))
    assert (one.seller_subsidy, one.fee_fixed, one.fee_payment) == (
        Decimal(10000),
        Decimal(4000),
        Decimal(2000),
    )
    assert (one.sku, one.variation_sku, one.item_id) == ("SKU-A", "SKU-A-1", "sku:SKU-A-1")
    assert one.ad_attributed is None and one.affiliate is False
    assert one.paid_at == datetime(2026, 10, 5, 10, 20)

    # A later export of the same orders: the status moved, the fee columns were not filled.
    later_lines = [
        _line(
            ORDER_A,
            **{
                "Trạng Thái Đơn Hàng": "Hoàn thành",
                "Trạng thái Trả hàng/Hoàn tiền": "Đã Chấp Thuận Yêu Cầu",
            },
        ),
        *_multi_line_order(ORDER_B),
    ]
    reparsed = _posts(tmp_path, later_lines)
    await _ingest(
        session,
        shop,
        "order_lines",
        {**reparsed.posts[0].body, "captured_at": "2026-10-29T09:40:00+07:00"},
    )
    stored = await _rows(session, ShopeeOrderLine, shop)
    assert len(stored) == 3
    one = next(s for s in stored if s.order_ref == parse.order_ref(ORDER_A, KEY))
    assert one.status == "refunded_accepted"
    assert one.fee_fixed == Decimal(4000)  # a NULL fee in the later export erased nothing
    assert one.completed_at == datetime(2026, 10, 9, 12, 0)


async def test_the_catalogue_resolves_the_item_by_sku(session, tmp_path):
    from juli_backend.models.platform_data import PlatformItem

    shop = await _shop(session)
    session.add(
        PlatformItem(
            id=__import__("uuid").uuid4(),
            shop_id=shop.id,
            platform="shopee",
            item_id="9001",
            variation_id="9002",
            seller_sku="SKU-A-1",
            source="file",
            source_rank=2,
            source_version="t",
            mapper_version=1,
            captured_at=datetime(2026, 10, 29),
            updated_at=datetime(2026, 10, 29),
            first_seen_on=date(2026, 10, 1),
            last_seen_on=date(2026, 10, 28),
            extra={},
        )
    )
    await session.flush()
    parsed = _posts(tmp_path, [_line(ORDER_A)])
    await _ingest(
        session,
        shop,
        "order_lines",
        {**parsed.posts[0].body, "captured_at": "2026-10-29T09:30:00+07:00"},
    )
    (line,) = await _rows(session, ShopeeOrderLine, shop)
    assert (line.item_id, line.variation_id) == ("9001", "9002")


async def test_the_affiliate_lane_marks_existing_lines_and_never_creates_one(session, tmp_path):
    shop = await _shop(session)
    _write_csv(
        tmp_path / "SellerConversionReport_202611022133.csv",
        [
            CONVERSION_HEADER,
            _conversion_row(ORDER_A, "1001", "2026-10-05 10:15:00", cost="900"),
            _conversion_row("2610ZZZZZZ0009", "1001", "2026-10-05 11:00:00", cost="500"),
        ],
    )
    parsed = _posts(tmp_path, [_line(ORDER_A), _line(ORDER_B)])
    assert [p.dataset for p in parsed.posts] == ["order_lines", "affiliate_order_lines"]
    for post in parsed.posts:
        await _ingest(
            session, shop, post.dataset, {**post.body, "captured_at": "2026-10-29T09:30:00+07:00"}
        )
    stored = await _rows(session, ShopeeOrderLine, shop)
    assert len(stored) == 2  # the unmatched affiliate order created nothing
    marked = {s.order_ref: s for s in stored}
    a = marked[parse.order_ref(ORDER_A, KEY)]
    b = marked[parse.order_ref(ORDER_B, KEY)]
    assert (a.affiliate, a.commission, a.traffic_source) == (True, Decimal(900), "affiliate")
    assert (b.affiliate, b.commission) == (False, None)


def test_the_cli_hashes_with_the_shops_key_when_the_master_and_shop_id_are_given(monkeypatch):
    import uuid

    from juli_backend.services.ingest import order_ref

    shop = uuid.uuid4()
    monkeypatch.setenv(order_ref.ENV_MASTER, "synthetic-master-key-for-tests-only")
    assert load_shopee_exports._shop_order_ref_key(shop) == order_ref.shop_key(
        b"synthetic-master-key-for-tests-only", shop
    )
    assert load_shopee_exports._shop_order_ref_key(None) is None
    monkeypatch.delenv(order_ref.ENV_MASTER)
    assert load_shopee_exports._shop_order_ref_key(shop) is None
