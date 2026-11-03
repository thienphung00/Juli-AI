"""Reco loader wave: affiliate, ad keyword, ad change log and flash-sale metric exports.

Synthetic files in the exports' own layout (headers and number formats come from the real
Seller Centre files; every value is invented). Checks:

- each export becomes the dataset the mapping says, and every post passes the gateway's
  own validation (and lands in the period table, SQLite);
- the three affiliate dashboard exports that carry no period are not loaded without a window;
- ``ads_keyword`` rows with no keyword ("-" / the automatic-ad label) are kept;
- order lines and the ad change log are RESERVED: never in ``parsed.posts``, validated by
  their own models, and the raw order id appears nowhere (keyed hash only);
- buyer-looking columns are dropped unread and never reach any post;
- file names with spaces, ``+``, timestamps and browser copy suffixes are recognised.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.services.ingest.gateway import validate_rows
from juli_backend.services.ingest.mapping import DATASETS, dataset_spec, normalize_rows
from juli_backend.services.ingest.reserved import RESERVED_DATASETS, validate_reserved
from juli_backend.services.ingest.schemas import IngestBody
from scripts import load_shopee_exports
from scripts.shopee_exports import parse
from tests.unit.test_shopee_export_loader import _write_csv, _write_xlsx
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop

KEY = b"synthetic-test-key"
CANARY_ORDER = "2611AAAA0BBBB1"
CANARY_BUYER = "Nguyen Van Canary"
CANARY_PHONE = "0900111222"
CANARY_ADDRESS = "12 Duong Canary"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validates(parsed: parse.Parsed) -> None:
    assert load_shopee_exports.validate(parsed, _now()) == []


def _only(posts: list[parse.Post], dataset: str) -> parse.Post:
    (post,) = [p for p in posts if p.dataset == dataset]
    return post


# -- affiliate dashboard -----------------------------------------------------------------

PRODUCT_HEADER = [
    "Item id",
    "Item Name",
    "Price(₫)",
    "Sales(₫)",
    "Item Sold",
    "Orders",
    "Clicks",
    "Est.Commission(₫)",
    "ROI",
    "Total Buyers",
    "New Buyers",
]
PERFORMANCE_HEADER = [
    "Mã sản phẩm",
    "Tên sản phẩm",
    "Giá(₫)",
    "Doanh thu(₫)",
    "Sản phẩm đã bán",
    "Số đơn hàng",
    "Hoa hồng ước tính",
    "Hoa hồng ước tính(₫)",
    "ROI",
    "Tất cả người mua",
    "Người mua mới",
]


def test_affiliate_product_month_becomes_a_period_post_for_that_month(tmp_path):
    _write_csv(
        tmp_path / "affiliate_product_202609.csv",
        [
            PRODUCT_HEADER,
            ["1001", "Sản phẩm A", "50000", "500000", "10", "8", "40", "25000.5", "20.0", "7", "5"],
        ],
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed)
    post = _only(parsed.posts, "affiliate_product_period")
    assert post.body["period"] == {
        "start": "2026-09-01",
        "end": "2026-09-30",
        "granularity": "period",
    }
    assert "order_type" not in post.body
    assert post.body["rows"] == [
        {
            "item_id": "1001",
            "price": 50000,
            "sales": 500000,
            "units": 10,
            "orders": 8,
            "clicks": 40,
            "est_commission": 25000.5,
            "roi": 20,
            "buyers": 7,
            "new_buyers": 5,
        }
    ]
    assert "Sản phẩm A" not in json.dumps(post.body, ensure_ascii=False)


def test_exports_without_a_period_need_a_window(tmp_path):
    _write_csv(
        tmp_path / "ProductPerformance_202611022057.csv",
        [
            PERFORMANCE_HEADER,
            ["1001", "Sản phẩm A", "50000", "500000", "10", "8", "40", "25000.5", "20.0", "7", "5"],
        ],
    )
    _write_csv(
        tmp_path / "Open Campaign Analytics_202611022057.csv",
        [
            [
                "Tên Sản phẩm",
                "Mã Sản phẩm",
                "KOLs",
                "Doanh thu(₫)",
                "Sản phẩm đã bán",
                "Hoa hồng ước tính(₫)",
            ],
            ["Sản phẩm A", "1001", "16", "500000", "10", "25000.5"],
        ],
    )
    _write_csv(
        tmp_path / "AMSAffiliatePerformance_202611022133.csv",
        [
            [
                "Affiliate ID",
                "Affiliate Name",
                "Affiliate Username",
                "Sales(₫)",
                "Item Sold",
                "Orders",
                "Clicks",
                "Est.Commission(₫)",
                "ROI",
                "Total Buyers",
                "New Buyers",
            ],
            [
                "777001",
                "Tên Hiển Thị",
                "kol_handle",
                "300000",
                "5",
                "3",
                "25",
                "9000.25",
                "33.3",
                "3",
                "2",
            ],
        ],
    )
    without = parse.parse_folder(tmp_path)
    assert without.posts == []
    assert sum(without.notes.values()) == 3
    window = (date(2026, 10, 3), date(2026, 11, 1))
    parsed = parse.parse_folder(tmp_path, window=window)
    _validates(parsed)
    performance = _only(parsed.posts, "affiliate_product_period")
    # Their "Hoa hồng ước tính" (no unit) is the click count; the commission has the (₫) column.
    assert performance.body["rows"][0]["clicks"] == 40
    assert performance.body["rows"][0]["est_commission"] == 25000.5
    assert performance.body["period"]["start"] == "2026-10-03"
    open_campaign = _only(parsed.posts, "affiliate_open_campaign_period").body["rows"][0]
    assert open_campaign == {
        "item_id": "1001",
        "kols": 16,
        "sales": 500000,
        "units": 10,
        "est_commission": 25000.5,
    }
    partner = _only(parsed.posts, "affiliate_partner_period").body["rows"][0]
    assert partner["affiliate_id"] == "777001" and partner["account"] == "kol_handle"
    assert "Tên Hiển Thị" not in json.dumps(parsed.posts[0].body, ensure_ascii=False)


def test_campaign_terms_are_one_snapshot_day_with_the_kol_count(tmp_path):
    _write_csv(
        tmp_path / "target_campaign_202611022056.csv",
        [
            ["Type", "Commission List"],
            ["Date", "2026-11-02"],
            ["For data capacity reasons, only the last 100,000 records are exported."],
            [
                "Tên chiến dịch",
                "ID của chiến dịch",
                "Thời gian chạy",
                "Trạng thái",
                "ID sản phẩm",
                "Tên sản phẩm",
                "Tỉ lệ hoa hồng",
                "Tên tài khoản KOL",
            ],
            [
                "Chiến dịch X",
                "9001",
                "2025/01/03 16:00 - No limit",
                "ongoing",
                "1001",
                "SP A",
                "12,50%",
                "KOL cụ thể[20]",
            ],
            [
                "Chiến dịch X",
                "9001",
                "2025/01/03 16:00 - 2025/02/01 10:30",
                "ended",
                "1002",
                "SP B",
                "8,00%",
                "KOL cụ thể[3]",
            ],
        ],
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed)
    post = _only(parsed.posts, "affiliate_campaign_terms")
    assert post.body["period"] == {
        "start": "2026-11-02",
        "end": "2026-11-02",
        "granularity": "period",
    }
    first, second = post.body["rows"]
    assert first["commission_rate"] == 0.125 and first["running"] is True
    assert first["starts_on"] == "2025-01-03" and "ends_on" not in first
    assert first["targeted_kols"] == 20
    assert second["ends_on"] == "2025-02-01" and second["running"] is False


def test_each_bill_month_is_its_own_post_and_the_formula_quote_is_stripped(tmp_path):
    header = [
        "Mã đối soát",
        "Tháng đối soát",
        "Hoa hồng hằng tháng(₫)",
        "Số tiền thuế(₫)",
        "Chi phí hàng tháng(₫)",
        "Trạng thái khấu trừ",
        "Tổng khấu trừ(₫)",
        "Số dư ví của chương trình Tăng đơn cùng KOL bị cấn trừ(₫)",
        "Tổng số tiền chờ xử lý(₫)",
    ]
    _write_csv(
        tmp_path / "ValidationBill202611022134.csv",
        [
            header,
            [
                '="1000000000000001"',
                "2026-09",
                "100000.5",
                "8000.25",
                "108001",
                "Completed",
                "108001",
                "0",
                "0",
            ],
            [
                '="1000000000000002"',
                "2026-10",
                "90000",
                "7000",
                "97000",
                "Pending",
                "0",
                "0",
                "97000",
            ],
        ],
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed)
    posts = [p for p in parsed.posts if p.dataset == "affiliate_bill_period"]
    assert [p.body["period"]["start"] for p in posts] == ["2026-09-01", "2026-10-01"]
    row = posts[0].body["rows"][0]
    assert row["bill_code"] == "1000000000000001" and row["deduction_completed"] is True
    assert posts[1].body["rows"][0]["deduction_completed"] is False


# -- ads keyword -------------------------------------------------------------------------

KEYWORD_META = [
    ["Báo cáo Dịch vụ Hiển thị trả theo CPC - Shopee Việt Nam"],
    ["Tên đăng nhập", "synthetic_user"],
    ["Tên gian hàng", "Synthetic Shop"],
    ["Mã Người bán", "1"],
    ["Thời gian tạo báo cáo", "01/11/2026 10:00"],
    ["Khoảng thời gian", "29/08/2026 - 31/10/2026"],
    [],
]
KEYWORD_HEADER = [
    "Thứ tự",
    "Tên Dịch vụ Hiển thị",
    "Trạng thái",
    "Loại Dịch vụ Hiển thị",
    "Mã sản phẩm",
    "Phương thức đấu thầu",
    "Vị trí",
    "Từ khóa / Vị trí",
    "Loại từ khóa",
    "Số lượt xem",
    "Số lượt click",
    "Tỷ Lệ Click",
    "Lượt chuyển đổi",
    "Doanh số",
    "Chi phí",
    "ROAS",
]


def _keyword_file(tmp_path: Path) -> Path:
    return _write_csv(
        tmp_path / "ads_keyword_20260829-20261031.csv",
        [
            *KEYWORD_META,
            KEYWORD_HEADER,
            [
                "1",
                "Chiến dịch shop",
                "Đang diễn ra",
                "Shop",
                "-",
                "ROAS",
                "-",
                "-",
                "-",
                "1000",
                "50",
                "5.00%",
                "4",
                "400000",
                "50000",
                "8.00",
            ],
            [
                "2",
                "Chiến dịch A",
                "Đang diễn ra",
                "SP",
                "1001",
                "ROAS",
                "Tất cả",
                "Quảng cáo Tự Động",
                "-",
                "500",
                "10",
                "2.00%",
                "1",
                "100000",
                "20000",
                "5.00",
            ],
            [
                "3",
                "Chiến dịch A",
                "Tạm dừng",
                "SP",
                "1001",
                "Thủ công",
                "Tìm kiếm",
                "nước rửa chén",
                "Khớp rộng",
                "300",
                "6",
                "2.00%",
                "0",
                "-",
                "9000",
                "-",
            ],
            [
                "4",
                "Chiến dịch A",
                "Tạm dừng",
                "SP",
                "1001",
                "Thủ công",
                "Tìm kiếm",
                "nước rửa chén",
                "Khớp rộng",
                "200",
                "4",
                "2.00%",
                "0",
                "-",
                "7000",
                "-",
            ],
        ],
    )


def test_keyword_rows_without_a_keyword_are_kept(tmp_path):
    _keyword_file(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed)
    post = _only(parsed.posts, "ads_keyword_period")
    assert post.body["order_type"] == "placed"
    assert post.body["period"]["start"] == "2026-08-29"
    shop_level, auto, kw, twin = post.body["rows"]
    assert "keyword" not in shop_level and "item_id" not in shop_level
    assert "keyword" not in auto and auto["auto_placement"] is True
    assert kw["keyword"] == "nước rửa chén" and kw["keyword_type"] == "Khớp rộng"
    assert twin["ordinal"] == 1


def test_keyword_rows_map_to_distinct_ads_overlay_rows(tmp_path):
    _keyword_file(tmp_path)
    post = _only(parse.parse_folder(tmp_path).posts, "ads_keyword_period")
    spec = dataset_spec("shopee", "ads_keyword_period")
    rows = [spec.row_model.model_validate(r) for r in post.body["rows"]]
    normalized = normalize_rows(spec, rows)
    assert {n.stream for n in normalized} == {"ads"}
    assert len({(n.item_id, n.segment) for n in normalized}) == 4
    assert all(len(n.segment) <= 16 and len(n.platform_source or "") <= 64 for n in normalized)
    assert normalized[2].platform_source == "Chiến dịch A › nước rửa chén"
    assert normalized[0].platform_source == "Chiến dịch shop"


# -- ad change log (reserved) ------------------------------------------------------------


def _log(tmp_path: Path, name: str, with_item: bool) -> Path:
    meta = [
        ["Lịch sử Hoạt động cấp Dịch vụ Hiển thị Sản phẩm - Shopee Việt Nam"],
        ["Tên gian hàng", "Synthetic Shop"],
        ["Mã Người bán", "1"],
        *([["Mã sản phẩm", "1001"]] if with_item else []),
        ["Thời gian tạo báo cáo", "02/11/2026 21:39"],
        ["Khoảng thời gian", "04/10/2026 - 02/11/2026"],
        ["ID chiến dịch", "555000111"],
        [],
    ]
    return _write_csv(
        tmp_path / name,
        [
            *meta,
            ["Thời gian cập nhật", "Người thao tác", "Nền tảng", "Loại sự kiện", "Chi tiết"],
            [
                "2026-10-05 08:00:00",
                "Hệ thống: Tối ưu",
                "Ứng dụng khác",
                "Campaign Surge Optimization Triggered",
                "",
            ],
            [
                "2026-10-05 08:00:00",
                "Hệ thống: Tối ưu",
                "Ứng dụng khác",
                "Campaign Surge Optimization Triggered",
                "",
            ],
            [
                "2026-10-20 09:30:00",
                "shop_acc:staff.one",
                "Máy tính",
                "Thay đổi ngân sách",
                "Ngân sách hàng ngày: ₫100000 -> ₫150000",
            ],
            [
                "2026-11-01 10:00:00",
                "shop_acc:staff.one",
                "Máy tính",
                "Thay đổi sản phẩm cho Chiến Dịch Nhóm",
                "Thay đổi số lượng sản phẩm trong Chiến Dịch Nhóm:: 9 -> 12",
            ],
        ],
    )


def test_the_ad_change_log_is_reserved_not_posted(tmp_path):
    _log(tmp_path, "ops_log_group_555000111_04_10-02_11.csv", with_item=False)
    _log(tmp_path, "ops_log_hae_555000111_04_10-02_11.csv", with_item=True)
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert {p.dataset for p in parsed.reserved} == {"ads_change_log"}
    _validates(parsed)
    group = [p for p in parsed.reserved if p.file.startswith("ops_log_group")]
    assert [p.body["period"]["start"] for p in group] == ["2026-10-05", "2026-11-01"]
    october = group[0].body["rows"]
    assert [r["actor_kind"] for r in october] == ["system", "system", "user"]
    assert october[1]["ordinal"] == 1
    assert (october[2]["budget_from"], october[2]["budget_to"]) == (100000, 150000)
    assert group[1].body["rows"][0]["products_to"] == 12
    assert all("item_id" not in r for r in october)
    product_log = next(p for p in parsed.reserved if p.file.startswith("ops_log_hae"))
    assert product_log.body["rows"][0]["item_id"] == "1001"


# -- flash sale metrics ------------------------------------------------------------------

FLASH_HEADER = [
    "Bán hàng (đặt hàng)(₫)",
    "Bán hàng (Đơn đặt hàng được xác nhận)(₫)",
    "Đơn đặt hàng (đặt hàng)",
    "Đơn đặt hàng (Đơn đặt hàng được xác nhận)",
    "Người mua (đặt hàng)",
    "Người mua (Đơn đặt hàng được xác nhận)",
    "Tỷ lệ click vào sản phẩm (CTR)",
    "Lượt xem sản phẩm",
    "Lượt nhấp vào sản phẩm",
    "Bán hàng cho mỗi người mua (đặt hàng)(₫)",
    "Bán hàng cho mỗi người mua (đơn đặt hàng được xác nhận)(₫)",
]


def test_flash_sale_metrics_are_daily_rows_plus_a_period_total(tmp_path):
    _write_xlsx(
        tmp_path / "In_Shop_Flash_Sale_Metrics_01102026-29102026.xlsx",
        {
            "Tổng quan": [
                ["Khung thời gian", *FLASH_HEADER],
                [
                    "01-10-2026 - 29-10-2026",
                    "300.000",
                    "250.000",
                    "4",
                    "3",
                    "4",
                    "3",
                    "5,00%",
                    "90",
                    "4",
                    "75.000",
                    "83.333",
                ],
            ],
            "Chỉ Số": [
                ["Thời Gian", *FLASH_HEADER],
                [
                    "01-10-2026",
                    "300.000",
                    "250.000",
                    "4",
                    "3",
                    "4",
                    "3",
                    "5,00%",
                    "80",
                    "4",
                    "75.000",
                    "83.333",
                ],
                ["02-10-2026", "0", "0", "0", "0", "0", "0", "0,00%", "10", "0", "0", "0"],
            ],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed)
    daily = [p for p in parsed.posts if p.dataset == "promotion_daily"]
    assert {p.body["order_type"] for p in daily} == {"placed", "confirmed"}
    placed = next(p for p in daily if p.body["order_type"] == "placed")
    assert placed.body["rows"][0] == {
        "date": "2026-10-01",
        "promo_type": "Flash Sale",
        "sales": 300000,
        "orders": 4,
        "buyers": 4,
        "sales_per_buyer": 75000,
        "extra": {"product_views": 80, "product_clicks": 4},
    }
    assert placed.body["rows"][1]["sales"] == 0
    totals = [p for p in parsed.posts if p.dataset == "promotion_period"]
    assert len(totals) == 2
    confirmed = next(p for p in totals if p.body["order_type"] == "confirmed")
    assert confirmed.body["period"]["end"] == "2026-10-29"
    assert confirmed.body["rows"][0]["sales"] == 250000


# -- order lines (reserved) and the PII guard --------------------------------------------

CONVERSION_HEADER = [
    "Mã đơn hàng",
    "Trạng thái đơn hàng",
    "Trạng thái gian lận",
    "Thời gian đặt hàng",
    "Thời gian đơn hàng hoàn thành",
    "Thời gian chuyển đổi hoàn tất",
    "Mã sản phẩm",
    "Tên sản phẩm",
    "Model id",
    "L1 Ngành hàng toàn cầu",
    "Mã khuyến mãi",
    "Giá(₫)",
    "Số lượng",
    "Tên đối tác",
    "Tài khoản Tiếp thị liên kết",
    "MCN được liên kết",
    "Mã hoa hồng",
    "Loại chiến dịch",
    "Giá trị đặt hàng(₫)",
    "Số tiền hoàn(₫)",
    "Loại đơn hàng",
    "Hoa hồng Xtra trên sản phẩm(₫)",
    "Tỷ lệ hoa hồng Xtra trên sản phẩm mà Tổng số KOL quảng bá sản phẩm nhận được",
    "Ghi chú sản phẩm",
    "Kênh",
    "Chi phí(₫)",
    "Trạng thái khấu trừ",
]


def _conversion_line(order: str, item: str, when: str, **over: str) -> list[str]:
    cells = {
        "Mã đơn hàng": order,
        "Trạng thái đơn hàng": "Hoàn thành",
        "Trạng thái gian lận": "Hợp lệ",
        "Thời gian đặt hàng": when,
        "Thời gian đơn hàng hoàn thành": "",
        "Thời gian chuyển đổi hoàn tất": "",
        "Mã sản phẩm": item,
        "Tên sản phẩm": "Tên SP",
        "Model id": "9900",
        "L1 Ngành hàng toàn cầu": "Nhà cửa",
        "Mã khuyến mãi": "",
        "Giá(₫)": "50000",
        "Số lượng": "2",
        "Tên đối tác": "Creator",
        "Tài khoản Tiếp thị liên kết": "creator_handle",
        "MCN được liên kết": "",
        "Mã hoa hồng": "123",
        "Loại chiến dịch": "Chiến dịch mở rộng",
        "Giá trị đặt hàng(₫)": "100000",
        "Số tiền hoàn(₫)": "0",
        "Loại đơn hàng": "Đơn hàng trực tiếp",
        "Hoa hồng Xtra trên sản phẩm(₫)": "5000.5",
        "Tỷ lệ hoa hồng Xtra trên sản phẩm mà Tổng số KOL quảng bá sản phẩm nhận được": "9%",
        "Ghi chú sản phẩm": "ghi chú tự do",
        "Kênh": "Facebook",
        "Chi phí(₫)": "5000",
        "Trạng thái khấu trừ": "Đã khấu trừ",
    }
    cells.update(over)
    return [cells[h] for h in CONVERSION_HEADER]


def _conversions(tmp_path: Path, name: str = "SellerConversionReport_202611022133.csv") -> Path:
    return _write_csv(
        tmp_path / name,
        [
            CONVERSION_HEADER,
            _conversion_line(CANARY_ORDER, "1001", "2026-10-30 10:00:00"),
            _conversion_line(CANARY_ORDER, "1001", "2026-10-30 10:00:00"),
            _conversion_line("2611ZZZZ0YYYY2", "1002", "2026-11-01 09:00:00"),
        ],
    )


def test_order_lines_are_reserved_with_a_keyed_order_ref_and_no_raw_id(tmp_path):
    _conversions(tmp_path)
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert parsed.posts == []
    _validates(parsed)
    posts = parsed.reserved
    assert [p.dataset for p in posts] == ["affiliate_order_lines"] * 2  # October, November
    first = posts[0].body["rows"]
    assert first[0]["order_ref"] == parse.order_ref(CANARY_ORDER, KEY)
    assert first[0]["order_ref"] != parse.order_ref(CANARY_ORDER, b"another key")
    assert [r["line_no"] for r in first] == [0, 1]
    line = first[0]
    assert (line["item_id"], line["model_id"], line["price"], line["qty"]) == (
        "1001",
        "9900",
        50000,
        2,
    )
    assert line["affiliate"] is True and line["valid"] is True
    assert line["xtra_product_commission"] == 5000.5
    assert line["xtra_product_commission_kols_rate"] == 0.09
    assert (line["channel"], line["order_kind"]) == ("Facebook", "Đơn hàng trực tiếp")
    assert line["ordered_at"] == "2026-10-30T10:00:00"
    dumped = json.dumps([p.body for p in posts], ensure_ascii=False)
    assert CANARY_ORDER not in dumped
    assert "ghi chú tự do" not in dumped and "Tên SP" not in dumped


def test_buyer_looking_columns_never_reach_any_post(tmp_path):
    header = [*CONVERSION_HEADER, "Tên người mua", "Số điện thoại", "Địa chỉ nhận hàng"]
    _write_csv(
        tmp_path / "SellerConversionReport_202611022133.csv",
        [
            header,
            [
                *_conversion_line(CANARY_ORDER, "1001", "2026-10-30 10:00:00"),
                CANARY_BUYER,
                CANARY_PHONE,
                CANARY_ADDRESS,
            ],
        ],
    )
    _write_csv(
        tmp_path / "AMSAffiliatePerformance_202611022133.csv",
        [
            ["Affiliate ID", "Affiliate Name", "Affiliate Username", "Sales(₫)"],
            ["777001", "Tên", "kol_handle", "300000"],
        ],
    )
    _keyword_file(tmp_path)
    _log(tmp_path, "ops_log_group_555000111_04_10-02_11.csv", with_item=False)
    parsed = parse.parse_folder(
        tmp_path, window=(date(2026, 10, 1), date(2026, 10, 31)), order_ref_key=KEY
    )
    assert parsed.reserved and parsed.posts
    everything = (
        json.dumps([p.body for p in [*parsed.posts, *parsed.reserved]], ensure_ascii=False)
        + load_shopee_exports.summary(parsed)
        + json.dumps(dict(parsed.notes), ensure_ascii=False)
    )
    for canary in (CANARY_BUYER, CANARY_PHONE, CANARY_ADDRESS, CANARY_ORDER):
        assert canary not in everything
    assert (
        parsed.notes["SellerConversionReport_202611022133.csv: buyer-level column dropped unread"]
        == 3
    )
    # The models have no field a buyer's name could be sent in.
    for dataset in RESERVED_DATASETS.values():
        assert not {"buyer", "buyer_name", "phone", "address"} & set(dataset.row_model.model_fields)


def test_an_unknown_order_report_column_stops_the_load(tmp_path):
    _write_csv(
        tmp_path / "SellerConversionReport_202611022133.csv",
        [
            [*CONVERSION_HEADER, "Cột lạ"],
            [*_conversion_line(CANARY_ORDER, "1001", "2026-10-30 10:00:00"), "x"],
        ],
    )
    with pytest.raises(parse.UnknownColumn, match="Cột lạ"):
        parse.parse_folder(tmp_path)


def test_a_reserved_body_with_a_buyer_field_fails_its_own_validation():
    row = {
        "order_ref": "a" * 32,
        "item_id": "1",
        "ordered_at": "2026-10-30T10:00:00",
        "buyer_name": CANARY_BUYER,
    }
    body = {
        "source": "file",
        "source_version": "x",
        "captured_at": "2026-11-02T10:00:00+07:00",
        "period": {"start": "2026-10-30", "end": "2026-10-30", "granularity": "period"},
        "rows": [row],
    }
    with pytest.raises(ValueError, match="buyer_name"):
        validate_reserved("affiliate_order_lines", IngestBody.model_validate(body))


def test_reserved_names_are_not_gateway_datasets():
    assert set(RESERVED_DATASETS) == {"affiliate_order_lines", "ads_change_log"}
    for name in RESERVED_DATASETS:
        assert dataset_spec("shopee", name) is None


@pytest.mark.xfail(
    strict=True,
    reason="TODO migration 112 (shopee_order_lines) / ad change log table: register the "
    "dataset specs in mapping.DATASETS, then delete this test and the reserved names",
)
@pytest.mark.parametrize("name", sorted(RESERVED_DATASETS))
def test_gateway_accepts_the_reserved_datasets_once_their_tables_exist(name):
    assert dataset_spec("shopee", name) is not None


def test_a_dry_run_sends_nothing_and_prints_counts_only(tmp_path, capsys):
    _conversions(tmp_path)
    _log(tmp_path, "ops_log_group_555000111_04_10-02_11.csv", with_item=False)
    _keyword_file(tmp_path)
    code = load_shopee_exports.main([str(tmp_path), "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "reserved" in out and "affiliate_order_lines" in out and "ads_keyword_period" in out
    for text in (CANARY_ORDER, "creator_handle", "nước rửa chén", "Chiến dịch A"):
        assert text not in out


def test_the_http_and_database_paths_only_ever_see_gateway_datasets(tmp_path):
    _conversions(tmp_path)
    _log(tmp_path, "ops_log_group_555000111_04_10-02_11.csv", with_item=False)
    _keyword_file(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    assert {p.dataset for p in parsed.posts} <= {name for _, name in DATASETS}


# -- file names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "parser"),
    [
        ("affiliate_product_202610.csv", parse.parse_affiliate_product),
        ("affiliate_product_202610 (1).csv", parse.parse_affiliate_product),
        ("ProductPerformance_202611022057.csv", parse.parse_affiliate_product),
        ("ProductPerformance_202611022057 (2).csv", parse.parse_affiliate_product),
        ("Open Campaign Analytics_202611022057.csv", parse.parse_open_campaign),
        ("Open+Campaign+Analytics_202611022057.csv", parse.parse_open_campaign),
        ("AMSAffiliatePerformance_202611022133.csv", parse.parse_affiliate_partners),
        ("target_campaign_202611022056.csv", parse.parse_campaign_terms),
        ("ValidationBill202611022134.csv", parse.parse_affiliate_bill),
        ("ValidationBill_202611022134.csv", parse.parse_affiliate_bill),
        ("SellerConversionReport_202611022133.csv", parse.parse_seller_conversions),
        ("ads_keyword_20260829-20261031.csv", parse.parse_ads_keyword),
        ("ops_log_group_188757809_04_10-02_11.csv", parse.parse_ops_log),
        ("ops_log_hae_162013511_04_10-02_11.csv", parse.parse_ops_log),
        ("In_Shop_Flash_Sale_Metrics_01102026-29102026.xlsx", parse.parse_flash_sale_metrics),
        ("ads_general_20260829-20261031.csv", parse.parse_ads),
    ],
)
def test_file_names_are_recognised(name, parser):
    import unicodedata

    normalized = unicodedata.normalize("NFC", name)
    found = next((fn for pattern, fn in parse.PARSERS if pattern.search(normalized)), None)
    assert found is parser


@pytest.mark.parametrize(
    "name",
    [
        "Orders_202611.csv",
        "ValidationBill.csv",
        "ops_log.csv",
        "affiliate_product_2026.csv",
        "notes.txt",
    ],
)
def test_other_files_are_not_matched(name):
    assert not any(pattern.search(name) for pattern, _ in parse.PARSERS)


# -- the period table (SQLite gateway) ---------------------------------------------------


async def test_affiliate_posts_land_in_the_period_table_as_affiliate_rows(session, tmp_path):
    _write_csv(
        tmp_path / "AMSAffiliatePerformance_202611022133.csv",
        [
            [
                "Affiliate ID",
                "Affiliate Name",
                "Affiliate Username",
                "Sales(₫)",
                "Item Sold",
                "Orders",
                "Clicks",
                "Est.Commission(₫)",
                "ROI",
                "Total Buyers",
                "New Buyers",
            ],
            ["777001", "Tên", "kol_handle", "300000", "5", "3", "25", "9000.25", "33.3", "3", "2"],
            ["777002", "Tên 2", "-", "100000", "1", "1", "5", "3000", "30.0", "1", "1"],
        ],
    )
    _write_csv(
        tmp_path / "ValidationBill202611022134.csv",
        [
            ["Mã đối soát", "Tháng đối soát", "Hoa hồng hằng tháng(₫)", "Số tiền thuế(₫)"],
            ['="1000000000000001"', "2026-09", "100000.5", "8000.25"],
        ],
    )
    parsed = parse.parse_folder(tmp_path, window=(date(2026, 10, 1), date(2026, 10, 28)))
    shop = await _shop(session)
    for post in parsed.posts:
        # The gateway tests' clock is 2026-10-30: the file time (now) would be in its future.
        body = {**post.body, "captured_at": "2026-10-29T09:30:00+07:00"}
        await _ingest(session, shop, post.dataset, body)
    stored = await _rows(session, PlatformPeriodMetric, shop)
    assert {m.stream for m in stored} == {"affiliate"}
    assert {m.order_type for m in stored} == {"none"}
    partners = [m for m in stored if m.dataset == "affiliate_partner_period"]
    assert len({m.segment for m in partners}) == 2
    top = next(m for m in partners if m.platform_source == "kol_handle")
    assert (top.gmv, top.units, top.orders, top.clicks, top.buyers) == (
        Decimal("300000"),
        Decimal("5"),
        Decimal("3"),
        Decimal("25"),
        Decimal("3"),
    )
    assert top.extra == {"est_commission": 9000.25, "roi": 33.3, "new_buyers": 2}
    bill = next(m for m in stored if m.dataset == "affiliate_bill_period")
    assert bill.extra == {"commission": 100000.5, "tax": 8000.25}
    assert (bill.period_start, bill.period_end) == (date(2026, 9, 1), date(2026, 9, 30))


async def test_keyword_and_flash_total_posts_land_in_the_period_table(session, tmp_path):
    _keyword_file(tmp_path)
    _write_xlsx(
        tmp_path / "In_Shop_Flash_Sale_Metrics_01102026-29102026.xlsx",
        {
            "Tổng quan": [
                ["Khung thời gian", *FLASH_HEADER],
                [
                    "01-10-2026 - 29-10-2026",
                    "300.000",
                    "250.000",
                    "4",
                    "3",
                    "4",
                    "3",
                    "5,00%",
                    "90",
                    "4",
                    "75.000",
                    "83.333",
                ],
            ]
        },
    )
    parsed = parse.parse_folder(tmp_path)
    shop = await _shop(session)
    for post in parsed.posts:
        validate_rows(
            dataset_spec("shopee", post.dataset),
            IngestBody.model_validate(post.body),
            _now(),
        )
        if post.dataset == "ads_keyword_period":  # the gateway tests' clock is 2026-10-30
            post.body["period"]["end"] = "2026-10-29"
        # The gateway tests' clock is 2026-10-30: the file time (now) would be in its future.
        body = {**post.body, "captured_at": "2026-10-29T09:30:00+07:00"}
        await _ingest(session, shop, post.dataset, body)
    stored = await _rows(session, PlatformPeriodMetric, shop)
    keywords = [m for m in stored if m.dataset == "ads_keyword_period"]
    assert len(keywords) == 4 and {m.stream for m in keywords} == {"ads"}
    flash = [m for m in stored if m.dataset == "promotion_period"]
    assert {(m.stream, m.segment, m.order_type) for m in flash} == {
        ("promo", "flash_sale", "placed"),
        ("promo", "flash_sale", "confirmed"),
    }
    assert body_total(flash, "placed") == Decimal("300000")


def body_total(rows: list[PlatformPeriodMetric], order_type: str) -> Decimal:
    return next(m.gmv for m in rows if m.order_type == order_type)
