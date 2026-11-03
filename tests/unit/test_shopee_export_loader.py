"""ADR-117 step 2: Seller Centre export files → gateway posts (``scripts/shopee_exports``).

Each test writes a tiny synthetic workbook in the exports' own layout (sheet names,
headers, Vietnamese number formats) and checks the posts:

- numbers: thousands dots, decimal commas, percentages, clock times, ``-``;
- shop-stats: the L1 total, its L2 rows and their day rows become ``traffic_overview``
  (day rows) and ``traffic_overview_period`` (totals); an order type is read from a sheet
  name Excel cut at 31 characters; Shopee's own ratios are not posted;
- parentskudetail: one post per order type, variations, the flag sheets;
- discount: twin programs get ordinals 0 and 1;
- an unknown header stops the load; files the loader does not know (buyer-data exports
  among them) are never opened (the order export is the one buyer-bearing file with a parser:
  ``orders.py`` reads it by header allowlist, tested in ``test_shopee_orders_parser.py``);
- every post passes the gateway's own validation; a database host other than localhost is
  refused.

No client data: values are synthetic.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from juli_backend.services.ingest.gateway import validate_rows
from juli_backend.services.ingest.mapping import dataset_spec
from juli_backend.services.ingest.schemas import IngestBody
from scripts import load_shopee_exports
from scripts.shopee_exports import parse


def _write_xlsx(path: Path, sheets: dict[str, list[list[str | None]]]) -> Path:
    """A minimal workbook: inline-string cells, one worksheet per entry."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as archive:
        entries, rels = [], []
        for index, (name, rows) in enumerate(sheets.items(), start=1):
            entries.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(
                f'<Relationship Id="rId{index}" Target="worksheets/sheet{index}.xml" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            )
            body = []
            for r, row in enumerate(rows, start=1):
                cells = "".join(
                    f'<c r="{chr(65 + c) if c < 26 else "A" + chr(65 + c - 26)}{r}" t="inlineStr">'
                    f"<is><t>{escape(value)}</t></is></c>"
                    for c, value in enumerate(row)
                    if value is not None
                )
                body.append(f'<row r="{r}">{cells}</row>')
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                f'<worksheet xmlns="{main}"><sheetData>{"".join(body)}</sheetData></worksheet>',
            )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{main}" xmlns:r="{rel}">'
            f"<sheets>{''.join(entries)}</sheets></workbook>",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{''.join(rels)}</Relationships>",
        )
    return path


def _validates(posts: list[parse.Post]) -> None:
    for post in posts:
        spec = dataset_spec("shopee", post.dataset)
        assert spec is not None, post.dataset
        # captured_at is the file's mtime: validate against the real clock.
        validate_rows(
            spec, IngestBody.model_validate(post.body), datetime.now(UTC).replace(tzinfo=None)
        )


def _by(posts: list[parse.Post], dataset: str, order_type: str | None = None) -> list[parse.Post]:
    return [p for p in posts if p.dataset == dataset and p.body.get("order_type") == order_type]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12.345.678", 12345678),
        ("123.456,70", 123456.7),
        ("116,00", 116),
        ("4,25%", 0.0425),
        ("100,00%", 1),
        ("00:00:47", 47),
        ("-6", -6),
        ("7.5", 7.5),
        ("-", None),
        (None, None),
    ],
)
def test_vietnamese_numbers(text, value):
    assert (
        parse.number(text) == pytest.approx(value)
        if value is not None
        else parse.number(text) is None
    )


SOURCE_HEADER = [
    "Nguồn lưu lượng",
    "Tỷ lệ doanh số",
    "Doanh số (VND)",
    "Lượt hiển thị sản phẩm",
    "Lượt nhấp vào sản phẩm",
    "Tổng số đơn hàng",
    "Sản phẩm",
    "CTR",
]
ADS_HEADER = [
    "Nguồn lưu lượng",
    "Tỷ lệ doanh số",
    "Doanh số (VND)",
    "Ads Impression",
    "Tổng số đơn hàng",
    "Tỷ lệ chuyển đổi",
    "Chi phí quảng cáo",
    "ROAS quảng cáo",
]
SHOP_HEADER = ["Ngày", "Tổng doanh số (VND)", "Tổng số đơn hàng", "Số lượt truy cập"]


def _shop_stats(folder: Path) -> Path:
    by_source = [
        [],
        ["Thẻ sản phẩm"],
        SOURCE_HEADER,
        ["Thẻ sản phẩm", "100,00%", "1.500.000", "3.000", "90", "6,00", "7,00", "3,00%"],
        ["01-10-2026", "100,00%", "700.000", "1.400", "40", "3,00", "3,00", "2,86%"],
        ["02-10-2026", "100,00%", "800.000", "1.600", "50", "3,00", "4,00", "3,13%"],
        ["Cửa hàng", "10,00%", "150.000", "300", "9", "1,00", "1,00", "3,00%"],
        ["01-10-2026", "0,00%", "0", "140", "4", "0,00", "0,00", "120,00%"],
        ["02-10-2026", "100,00%", "150.000", "160", "5", "1,00", "1,00", "3,13%"],
        [],
        ["Dịch vụ Hiển thị Shopee"],
        ADS_HEADER,
        ["Quảng cáo cửa hàng", "100,00%", "600.000", "2.500", "4,00", "1,00%", "120.000", "5,00"],
        ["01-10-2026", "100,00%", "600.000", "2.500", "4,00", "1,00%", "120.000", "5,00"],
    ]
    return _write_xlsx(
        folder / "synthetic.shopee-shop-stats.20261001-20261002.xlsx",
        {
            "Đơn đã xác nhận": [
                SHOP_HEADER,
                ["01-10-2026-02-10-2026", "1.500.000", "6", "100"],
                [],
                SHOP_HEADER,
                ["01-10-2026", "700.000", "3", "45"],
                ["02-10-2026", "800.000", "3", "55"],
            ],
            "(đơn đã xác nhận)Theo nguồn...": by_source,
        },
    )


def test_shop_stats_becomes_daily_sources_period_totals_and_shop_overview(tmp_path):
    _shop_stats(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (daily,) = _by(parsed.posts, "traffic_overview", "confirmed")
    rows = daily.body["rows"]
    total = [r for r in rows if r["source"] == "psd_label_product_card" and "sub_source" not in r]
    shop_page = [r for r in rows if r.get("sub_source") == "Cửa hàng"]
    ads = [r for r in rows if r["source"] == "psd_label_shopee_ads"]
    assert [r["date"] for r in total] == ["2026-10-01", "2026-10-02"]
    assert [r["product_clicks"] for r in shop_page] == [4, 5]
    assert ads[0]["sub_source"] == "Quảng cáo cửa hàng" and ads[0]["ads_expense"] == 120000
    # Shopee's own CTR is not posted (it can exceed 1 on an L2 row); the counts are.
    assert all("ctr" not in r for r in rows)
    (totals,) = _by(parsed.posts, "traffic_overview_period", "confirmed")
    assert totals.body["period"] == {
        "start": "2026-10-01",
        "end": "2026-10-02",
        "granularity": "period",
    }
    assert {r.get("sub_source") for r in totals.body["rows"]} == {
        None,
        "Cửa hàng",
        "Quảng cáo cửa hàng",
    }
    (overview,) = _by(parsed.posts, "shop_overview", "confirmed")
    assert [r["visitors"] for r in overview.body["rows"]] == [45, 55]  # the total row skipped


def test_an_unknown_header_stops_the_load(tmp_path):
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20261001-20261002.xlsx",
        {"Đơn đã xác nhận": [[*SHOP_HEADER, "Cột mới"], ["01-10-2026", "1", "1", "1", "1"]]},
    )
    with pytest.raises(parse.UnknownColumn, match="Cột mới") as stopped:
        parse.parse_folder(tmp_path)
    assert str(stopped.value) == "Cột mới"


def test_files_the_loader_does_not_know_are_never_opened(tmp_path):
    (tmp_path / "Orders_202611.csv").write_bytes(b"not a workbook")
    (tmp_path / "sales_composition_20261001-20261028.xlsx").write_bytes(b"not a workbook")
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert sorted(parsed.skipped_files) == [
        "Orders_202611.csv",
        "sales_composition_20261001-20261028.xlsx",
    ]


PRODUCT_HEADER = [
    "Mã sản phẩm",
    "Sản phẩm",
    "Tình trạng sản phẩm hiện tại",
    "Mã phân loại hàng",
    "Tên Phân Loại",
    "Trạng thái phân loại sản phẩm hiện tại",
    "SKU phân loại",
    "SKU sản phẩm",
    "Doanh số (Đơn đã đặt) (VND)",
    "Doanh số (Đơn đã xác nhận) (VND)",
    "Lượt xem sản phẩm",
    "Đơn hàng đã đặt",
    "Đơn đã xác nhận",
]


def test_parentskudetail_posts_each_order_type_with_variations_and_flags(tmp_path):
    _write_xlsx(
        tmp_path / "parentskudetail.20261001_20261028.xlsx",
        {
            "Sản Phẩm Hiệu Quả Tốt": [
                PRODUCT_HEADER,
                [
                    "1001",
                    "Găng tay",
                    "Đang hoạt động",
                    "-",
                    "-",
                    "-",
                    "-",
                    "G1",
                    "300.000",
                    "250.000",
                    "900",
                    "3",
                    "2",
                ],
                [
                    "1001",
                    "Găng tay",
                    "Đang hoạt động",
                    "2001",
                    "Hộp 3",
                    "Đang hoạt động",
                    "G1-3",
                    "G1",
                    "100.000",
                    "100.000",
                    "-",
                    "1",
                    "1",
                ],
            ],
            "Tối ưu chiến dịch DVHT": [["Mã sản phẩm", "Sản phẩm"], ["1001", "Găng tay"]],
            "Theo dõi hiệu quả chiến dịc...": [["Mã sản phẩm", "Sản phẩm"]],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (placed,) = _by(parsed.posts, "product_period", "placed")
    (confirmed,) = _by(parsed.posts, "product_period", "confirmed")
    assert [(r["variation_id"], r["orders"]) for r in placed.body["rows"]] == [("", 3), ("2001", 1)]
    assert [r["sales"] for r in confirmed.body["rows"]] == [250000, 100000]
    assert confirmed.body["rows"][1]["seller_sku"] == "G1-3"
    assert confirmed.body["rows"][0]["seller_sku"] == "G1"
    (flags,) = _by(parsed.posts, "product_flags")
    assert flags.body["rows"] == [{"item_id": "1001", "flag": "ads_optimize"}]


PROMO_HEADER = [
    "Tên chương trình",
    "Loại khuyến mãi",
    "Thời gian diễn ra chương trình",
    "Trạng thái",
    "Bán hàng (đặt hàng) (VND)",
    "Bán hàng (Đơn đặt hàng được xác nhận) (VND)",
    "Các giao dịch gói đặt hàng (đặt hàng)",
]


def test_twin_promotion_programs_get_ordinals(tmp_path):
    run = "10:30 15-06-2026 - 09:30 12-12-2026"
    _write_xlsx(
        tmp_path / "discount_20261001-20261028.xlsx",
        {
            "Biểu đồ": [
                ["Ngày", "Loại khuyến mãi", "Bán hàng (đặt hàng) (VND)"],
                ["01-10-2026", "Tất cả", "837.540"],
                ["01-10-2026", "Mua Kèm Deal Sốc", "0"],
                ["02-10-2026", "Tất cả", "900.000"],
            ],
            "Danh sách hiệu suất": [
                PROMO_HEADER,
                [
                    "Giảm giá",
                    "Chương Trình Khuyến Mãi",
                    run,
                    "Đang diễn ra",
                    "900.000",
                    "880.000",
                    "-",
                ],
                [
                    "Giảm giá",
                    "Chương Trình Khuyến Mãi",
                    run,
                    "Đang diễn ra",
                    "99.000",
                    "99.000",
                    "-",
                ],
            ],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (programs,) = _by(parsed.posts, "promotions", "confirmed")
    assert [(r["ordinal"], r["sales"]) for r in programs.body["rows"]] == [(0, 880000), (1, 99000)]
    assert programs.body["rows"][0]["starts_at"] == "2026-06-15T10:30:00"
    (chart,) = _by(parsed.posts, "promotion_daily", "placed")
    assert [r["promo_type"] for r in chart.body["rows"]] == [
        "Tất cả",
        "Mua Kèm Deal Sốc",
        "Tất cả",
    ]


def test_a_long_daily_file_is_cut_into_months(tmp_path):
    rows = [SHOP_HEADER] + [
        [f"{d:02d}-{m:02d}-2026", "1", "1", "1"] for m in (1, 2) for d in range(1, 29)
    ]
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20260101-20260228.xlsx", {"Đơn đã xác nhận": rows}
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    periods = [p.body["period"] for p in _by(parsed.posts, "shop_overview", "confirmed")]
    assert [(p["start"], p["end"]) for p in periods] == [
        ("2026-01-01", "2026-01-28"),
        ("2026-02-01", "2026-02-28"),
    ]


def test_a_remote_database_is_refused_without_the_explicit_flag():
    with pytest.raises(SystemExit, match="refusing database host"):
        load_shopee_exports._require_local("postgresql://u@db.example.supabase.co/postgres", False)
    assert (
        load_shopee_exports._require_local("postgresql://postgres@127.0.0.1:55433/x", False) is None
    )


def test_http_posts_name_the_loader_so_cloudflare_lets_them_through(monkeypatch):
    """Cloudflare answers the default ``Python-urllib`` agent with 403 / error 1010."""
    sent = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"duplicate": false}'

    def fake_urlopen(request, timeout):
        sent.append(request)
        return _Response()

    monkeypatch.setattr(load_shopee_exports.urllib.request, "urlopen", fake_urlopen)
    post = load_shopee_exports.Post(file="f.xlsx", dataset="promotions", body={"rows": []})
    outcome = load_shopee_exports.send_http([post], "https://api.example.test/", "jci_x")
    assert outcome == {"stored": 1}
    assert sent[0].get_header("User-agent") == load_shopee_exports.USER_AGENT
    assert sent[0].full_url == "https://api.example.test/v1/ingest/shopee/promotions"


def test_a_rate_limit_waits_and_resends_the_same_post(monkeypatch):
    """120 posts / shop / 10 min: a 429 waits ``retry_after_seconds`` and carries on."""
    import io
    import urllib.error

    answers = iter(["429", "ok", "ok"])
    urls = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"duplicate": false}'

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        if next(answers) == "429":
            body = io.BytesIO(b'{"detail":{"code":"rate_limited","retry_after_seconds":5}}')
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, body)
        return _Response()

    slept = []
    monkeypatch.setattr(load_shopee_exports.urllib.request, "urlopen", fake_urlopen)
    posts = [
        load_shopee_exports.Post(file="a.xlsx", dataset="promotions", body={}),
        load_shopee_exports.Post(file="b.xlsx", dataset="shop_overview", body={}),
    ]
    outcome = load_shopee_exports.send_http(posts, "https://x.test", "jci_x", sleep=slept.append)
    assert outcome == {"stored": 2}
    assert slept == [6]
    assert [u.rsplit("/", 1)[1] for u in urls] == ["promotions", "promotions", "shop_overview"]


def test_any_other_error_still_stops_the_load(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 403, "No", {}, io.BytesIO(b"error code: 1010")
        )

    monkeypatch.setattr(load_shopee_exports.urllib.request, "urlopen", fake_urlopen)
    post = load_shopee_exports.Post(file="a.xlsx", dataset="promotions", body={})
    slept: list[float] = []
    with pytest.raises(SystemExit, match="HTTP 403"):
        load_shopee_exports.send_http([post], "https://x.test", "jci_x", sleep=slept.append)
    assert slept == []


# -- flash sale, voucher, ads reports (D81.7) ---------------------------------------------

FLASH_HEADER = [
    "Khung giờ",
    "Lượt Nhắc Nhở",
    "Lượt xem sản phẩm",
    "Lượt nhấp vào sản phẩm",
    "Tỷ lệ click vào sản phẩm (CTR)",
    "Bán hàng (đặt hàng)(₫)",
    "Bán hàng (Đơn đặt hàng được xác nhận)(₫)",
    "Đơn đặt hàng (đặt hàng)",
    "Đơn đặt hàng (Đơn đặt hàng được xác nhận)",
]
VOUCHER_HEADER = [
    "Tên mã giảm giá",
    "Mã giảm giá",
    "Khung Thời Gian",
    "Trạng thái",
    "Người tạo",
    "Loại Voucher",
    "Loại ưu đãi",
    "Nhận",
    "Đơn đặt hàng (đặt hàng)",
    "Đơn đặt hàng (Đơn đặt hàng được xác nhận)",
    "Tỷ lệ sử dụng (đặt hàng)",
    "Bán hàng (đặt hàng) (VND)",
    "Bán hàng (Đơn đặt hàng được xác nhận) (VND)",
    "Chi phí (đặt hàng) (VND)",
]


def test_flash_sale_slots_become_promotions_per_month(tmp_path):
    slots = [
        ["12:00-14:00 04-09-2026", "3", "900", "40", "4,44%", "500.000", "450.000", "5", "4"],
        ["23:00-01:00 05-09-2026  +1", "0", "10", "20", "200,00%", "0", "0", "0", "0"],
        ["23:00-01:00 05-09-2026  +1", "1", "5", "1", "20,00%", "9.000", "9.000", "1", "1"],
        ["09:00-10:00 02-10-2026", "-", "-", "-", "-", "-", "-", "-", "-"],
    ]
    _write_xlsx(
        tmp_path / "flash_sale_performance_list_30102026.xlsx",
        {"Danh sách hiệu suất": [FLASH_HEADER, *slots]},
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    months = _by(parsed.posts, "promotions", "confirmed")
    assert [(p.body["period"]["start"], p.body["period"]["end"]) for p in months] == [
        ("2026-09-01", "2026-09-30"),
        ("2026-10-01", "2026-10-30"),
    ]
    first, overnight, twin = months[0].body["rows"]
    assert first["promo_type"] == "Flash Sale"
    assert first["program_name"] == "Flash Sale 12:00-14:00"
    assert first["sales"] == 450000
    assert first["extra"] == {"reminders": 3, "product_views": 900, "product_clicks": 40}
    # "+1" = ends the next day; the CTR above 100 % is not posted (the counts give it).
    assert overnight["ends_at"] == "2026-09-06T01:00:00"
    assert "ctr" not in overnight
    assert (overnight["ordinal"], twin["ordinal"]) == (0, 1)


def test_vouchers_become_promotions_without_the_code(tmp_path):
    seller = [
        "Giảm 5 phần trăm",
        "CODE12345",
        "01-10-2026 - 15-10-2026",
        "Đang diễn ra",
        "Người bán đã tạo",
        "Voucher Cửa Hàng",
        "Khuyến Mãi",
        "30",
        "4",
        "3",
        "13,33%",
        "400.000",
        "300.000",
        "20.000",
    ]
    shopee = [
        "Voucher do Shopee tạo",
        "SHOPEE999",
        "-",
        "-",
        "Shopee đã tạo",
        "Voucher Ưu Đãi Follower",
        "Khuyến Mãi",
        "5",
        "1",
        "1",
        "20,00%",
        "1.000",
        "1.000",
        "0",
    ]
    _write_xlsx(
        tmp_path / "voucher_20261001-20261029.xlsx",
        {
            "Tổng quan": [["Khung thời gian"], ["01-10-2026 - 29-10-2026"]],
            "Danh sách hiệu suất": [VOUCHER_HEADER, seller, shopee],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (placed,) = _by(parsed.posts, "promotions", "placed")
    (confirmed,) = _by(parsed.posts, "promotions", "confirmed")
    mine, theirs = placed.body["rows"]
    assert placed.body["period"] == {
        "start": "2026-10-01",
        "end": "2026-10-29",
        "granularity": "period",
    }
    assert (mine["promo_type"], mine["status"]) == ("Voucher", "Đang diễn ra")
    assert (mine["starts_at"], mine["ends_at"]) == ("2026-10-01T00:00:00", "2026-10-15T23:59:00")
    assert mine["sales"] == 400000
    assert confirmed.body["rows"][0]["sales"] == 300000
    assert mine["extra"] == {
        "claims": 30,
        "usage_rate": pytest.approx(0.1333),
        "voucher_cost": 20000,
        "created_by_shopee": False,
    }
    # No run dates in the export: the period's first day, flagged.
    assert (theirs["starts_at"], theirs["ends_at"]) == ("2026-10-01T00:00:00", None)
    assert theirs["extra"]["run_dates_unknown"] is True
    assert theirs["extra"]["created_by_shopee"] is True
    assert theirs["status"] is None
    assert "CODE12345" not in str(placed.body) and "SHOPEE999" not in str(placed.body)
    assert parsed.notes[
        "voucher_20261001-20261029.xlsx: sheet not loaded (daily / summary): Tổng quan"
    ]


def _write_csv(path: Path, lines: list[list[str]]) -> Path:
    path.write_text(
        "\n".join(",".join(f'"{cell}"' for cell in line) for line in lines) + "\n",
        encoding="utf-8-sig",
    )
    return path


ADS_META = [
    ["Báo cáo Dịch vụ Hiển thị trả theo CPC - Shopee Việt Nam"],
    ["Tên đăng nhập", "synthetic_user"],
    ["Tên gian hàng", "Synthetic Shop"],
    ["Mã Người bán", "1"],
    ["Thời gian tạo báo cáo", "01/11/2026 10:00"],
    ["Khoảng thời gian", "01/08/2026 - 31/10/2026"],
    [],
]
ADS_HEADER_ROW = [
    "Thứ tự",
    "Tên Dịch vụ Hiển thị",
    "Trạng thái",
    "Mã sản phẩm",
    "Phương thức đấu thầu",
    "Ngày bắt đầu",
    "Số lượt xem",
    "Số lượt click",
    "Tỷ Lệ Click",
    "Lượt chuyển đổi",
    "Lượt chuyển đổi trực tiếp",
    "Sản phẩm đã bán",
    "Doanh số",
    "Chi phí",
    "ROAS",
    "ACOS",
]


def test_cpc_ads_report_is_one_period_post_never_cut_into_days(tmp_path):
    shop_level = ["1", "Quảng cáo A", "Đang diễn ra", "-", "GMV Max", "01/08/2026 00:00:00"]
    shop_level += ["10000", "250", "2.50%", "12", "10", "15", "1200000", "300000", "4.00", "0.25"]
    product = ["2", "Quảng cáo B", "Đã dừng", "1234567890", "ROAS", "01/08/2026 00:00:00"]
    product += ["500", "5", "1.00%", "-", "-", "-", "-", "10000", "-", "-"]
    _write_csv(
        tmp_path / "ads_general_20260801-20261031.csv",
        [*ADS_META, ADS_HEADER_ROW, shop_level, product],
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (post,) = parsed.posts
    assert post.dataset == "ads_campaign_period"
    assert post.body["period"] == {
        "start": "2026-08-01",
        "end": "2026-10-31",
        "granularity": "period",
    }
    assert post.body["order_type"] == "placed"
    first, second = post.body["rows"]
    assert first == {
        "campaign_name": "Quảng cáo A",
        "running": True,
        "ads_impressions": 10000,
        "ad_clicks": 250,
        "ctr": 0.025,
        "conversions": 12,
        "direct_conversions": 10,
        "units_sold": 15,
        "sales": 1200000,
        "ads_expense": 300000,
        "ads_roas": 4,
        "acos": 0.25,
    }
    assert second["item_id"] == "1234567890"
    assert second["running"] is False
    assert "sales" not in second


def test_group_campaign_report_posts_product_rows_not_the_campaign_total(tmp_path):
    meta = [["Ad Group - Chiến Dịch Nhóm - 1 Report - Shopee Việt Nam"], *ADS_META[1:]]
    header = [
        "Thứ tự",
        "Chiến dịch / Tên sản phẩm",
        "Mã sản phẩm",
        "Trạng thái chiến dịch",
        "Số lượt xem",
        "Số lượt click",
        "Doanh số",
        "Chi phí",
    ]
    _write_csv(
        tmp_path / "Dữ+liệu-Chiến+Dịch+Nhóm-188757809-01_08_2026-31_10_2026.csv",
        [
            *meta,
            header,
            ["1", "Nhóm X", "-", "Đang diễn ra", "300", "30", "900", "90"],
            ["1.1", "Sản phẩm một", "1001", "-", "100", "10", "300", "30"],
            ["1.2", "Sản phẩm hai", "1002", "-", "200", "20", "600", "60"],
            ["2", "Nhóm rỗng", "-", "Tạm dừng", "7", "1", "-", "5"],
        ],
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (post,) = parsed.posts
    rows = post.body["rows"]
    assert [(r["campaign_name"], r.get("item_id"), r["ads_impressions"]) for r in rows] == [
        ("Nhóm X", "1001", 100),
        ("Nhóm X", "1002", 200),
        ("Nhóm rỗng", None, 7),
    ]
    assert rows[0]["running"] is True and rows[2]["running"] is False
    assert sum(r["ads_impressions"] for r in rows if r["campaign_name"] == "Nhóm X") == 300


def test_an_ads_report_with_an_unknown_header_stops_the_load(tmp_path):
    row = ["1", "A", "-", "-", "-", "-", "1", "1", "1%", "-", "-", "-", "-", "1", "-", "-", "x"]
    _write_csv(
        tmp_path / "ads_general_20260801-20261031.csv",
        [*ADS_META, [*ADS_HEADER_ROW, "Cột lạ"], row],
    )
    with pytest.raises(parse.UnknownColumn) as stopped:
        parse.parse_folder(tmp_path)
    assert "Cột lạ" in str(stopped.value)


def test_buyer_level_and_unlisted_reports_are_never_opened(tmp_path):
    for name in (
        "Orders_202611.csv",
        "Quản lý đánh giá_202611.xlsx",
        "ValidationBill.csv",
        "Dữ+liệu+Dịch+vụ+Hiển+thị+Sản+Phẩm-160675212-02_08_2026-02_11_2026.csv",
    ):
        (tmp_path / name).write_bytes(b"\xff\xfe not a csv a parser could read")
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert len(parsed.skipped_files) == 4


# -- productoverview and traffic_overview (shop visits) ----------------------------------

OVERVIEW_HEADER = [
    "Ngày",
    "Lượt truy cập sản phẩm",
    "Tỷ lệ thoát Trang sản phẩm",
    "Người mua đã đặt hàng",
    "Doanh số (Đơn đã đặt) (VND)",
    "Tỷ lệ chuyển đổi (Đơn đã đặt)",
    "Người mua có đơn đã xác nhận",
    "Doanh số (Đơn đã xác nhận) (VND)",
    "Tỷ lệ chuyển đổi (Đơn đã xác nhận)",
]


def test_product_overview_posts_each_order_type_from_one_row(tmp_path):
    _write_xlsx(
        tmp_path / "productoverview20261001-20261002.xlsx",
        {
            "overview": [
                OVERVIEW_HEADER,
                ["01-10-2026", "200", "40,00%", "5", "900.000", "2,50%", "4", "700.000", "2,00%"],
                ["02-10-2026", "-", "-", "-", "-", "-", "-", "-", "-"],
                ["03-10-2026", "100", "10,00%", "1", "50.000", "1,00%", "-", "-", "-"],
            ]
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (placed,) = _by(parsed.posts, "product_overview", "placed")
    (confirmed,) = _by(parsed.posts, "product_overview", "confirmed")
    assert placed.body["period"]["granularity"] == "day"
    first = placed.body["rows"][0]
    assert first == {
        "date": "2026-10-01",
        "product_visitors": 200,
        "bounce_rate": 0.4,
        "buyers": 5,
        "sales": 900000,
        "conversion_rate": 0.025,
    }
    # The same row's confirmed columns land on the confirmed post only.
    assert confirmed.body["rows"][0]["sales"] == 700000
    assert confirmed.body["rows"][0]["buyers"] == 4
    # An empty day keeps its row (the date alone); a missing column is not posted.
    assert placed.body["rows"][1] == {"date": "2026-10-02"}
    assert "sales" not in confirmed.body["rows"][2]


def test_a_product_overview_rate_above_one_is_not_posted_but_the_counts_stay(tmp_path):
    _write_xlsx(
        tmp_path / "productoverview20261001-20261002.xlsx",
        {
            "overview": [
                OVERVIEW_HEADER,
                ["01-10-2026", "2", "50,00%", "3", "900.000", "150,00%", "3", "900.000", "1,00%"],
                ["02-10-2026", "2", "50,00%", "1", "100.000", "50,00%", "1", "100.000", "1,00%"],
            ]
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)  # would be refused with the rate in
    (placed,) = _by(parsed.posts, "product_overview", "placed")
    assert "conversion_rate" not in placed.body["rows"][0]
    assert placed.body["rows"][0]["buyers"] == 3
    assert placed.body["rows"][1]["conversion_rate"] == 0.5
    note = "product_overview.conversion_rate above 1 not posted"
    assert [n for n in parsed.notes if n.endswith(note)] != []


TRAFFIC_HEADER = ["Ngày", "Lượt truy cập", "Tỉ lệ thoát trang", "Người theo dõi mới"]


def test_shop_traffic_reads_every_device_sheet(tmp_path):
    _write_xlsx(
        tmp_path / "traffic_overview_20261001_20261002.xlsx",
        {
            "Tất cả": [
                TRAFFIC_HEADER,
                ["01-10-2026", "300", "55,50%", "-3"],
                ["02-10-2026", "250", "-", "2"],
            ],
            "Máy tính": [TRAFFIC_HEADER, ["01-10-2026", "20", "10,00%", "0"]],
            "Ứng dụng": [TRAFFIC_HEADER, ["01-10-2026", "280", "58,00%", "-3"]],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (post,) = _by(parsed.posts, "shop_traffic")
    assert post.body.get("order_type") is None
    rows = {(r["date"], r["device"]): r for r in post.body["rows"]}
    assert set(rows) == {
        ("2026-10-01", "all"),
        ("2026-10-02", "all"),
        ("2026-10-01", "pc"),
        ("2026-10-01", "app"),
    }
    assert rows[("2026-10-01", "all")] == {
        "date": "2026-10-01",
        "device": "all",
        "visitors": 300,
        "bounce_rate": 0.555,
        "new_followers": -3,  # net: more unfollows than follows
    }
    assert "bounce_rate" not in rows[("2026-10-02", "all")]


def test_a_shop_traffic_sheet_that_is_not_a_device_stops_the_load(tmp_path):
    _write_xlsx(
        tmp_path / "traffic_overview_20261001_20261002.xlsx",
        {"Khác": [TRAFFIC_HEADER, ["01-10-2026", "1", "1,00%", "0"]]},
    )
    with pytest.raises(parse.UnknownColumn):
        parse.parse_folder(tmp_path)


# -- G-01: a derived rate above 1 must not refuse the post -------------------------------

CONVERSION_HEADER = [*SHOP_HEADER, "Tỷ lệ chuyển đổi đơn hàng"]


def test_g01_conversion_rate_above_one_is_dropped_and_the_counts_are_untouched(tmp_path):
    # A tiny day: more orders than visitors, so Shopee's own ratio is 300 %.
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20261001-20261002.xlsx",
        {
            "Đơn Đã Thanh Toán": [
                CONVERSION_HEADER,
                ["01-10-2026-02-10-2026", "900.000", "7", "5", "140,00%"],
                [],
                CONVERSION_HEADER,
                ["01-10-2026", "600.000", "3", "1", "300,00%"],
                ["02-10-2026", "300.000", "4", "50", "8,00%"],
            ]
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)  # the gateway's own models: no refusal
    (post,) = _by(parsed.posts, "shop_overview", "paid")
    assert post.body["rows"] == [
        {"date": "2026-10-01", "sales": 600000, "orders": 3, "visitors": 1},
        {"date": "2026-10-02", "sales": 300000, "orders": 4, "visitors": 50},
    ]


def test_g01_the_loader_reports_no_refusal(tmp_path):
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20261001-20261001.xlsx",
        {"Đơn đã xác nhận": [CONVERSION_HEADER, ["01-10-2026", "5.000", "2", "1", "200,00%"]]},
    )
    parsed = parse.parse_folder(tmp_path)
    assert load_shopee_exports.validate(parsed, datetime.now(UTC).replace(tzinfo=None)) == []


# -- G-02: a monthly roll-up is not a run of days ----------------------------------------


@pytest.mark.parametrize(
    ("days", "span", "kind"),
    [
        ([], None, "day"),
        ([date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)], None, "day"),
        ([date(2026, 1, d) for d in (1, 2, 5)], (date(2026, 1, 1), date(2026, 1, 31)), "day"),
        # One row per month, each the 1st: a roll-up, whatever its length.
        ([date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)], None, "month"),
        ([date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)], None, "month"),
        # Day-level evidence beats a long window: Jan 28 -> Feb 1 is a gap, not a month.
        (
            [date(2026, 1, 27), date(2026, 1, 28), date(2026, 2, 1), date(2026, 2, 2)],
            (date(2026, 1, 1), date(2026, 3, 31)),
            "day",
        ),
        # Cannot tell: a single 1st with a window longer than a day, a skipped month, or
        # scattered days over a long window.
        ([date(2026, 1, 1)], (date(2026, 1, 1), date(2026, 1, 31)), "ambiguous"),
        ([date(2026, 1, 1)], None, "ambiguous"),
        ([date(2026, 1, 1), date(2026, 3, 1)], None, "ambiguous"),
        (
            [date(2026, 1, 4), date(2026, 2, 9)],
            (date(2026, 1, 1), date(2026, 3, 31)),
            "ambiguous",
        ),
        # A single day that is not the 1st can only be a day; so can a one-day file.
        ([date(2026, 1, 9)], None, "day"),
        ([date(2026, 1, 1)], (date(2026, 1, 1), date(2026, 1, 1)), "day"),
    ],
)
def test_g02_granularity_is_read_from_the_rows(days, span, kind):
    assert parse.granularity(days, span) == kind


MONTH_ROWS = [
    ["01-01-2026", "300.000", "30", "100"],
    ["01-02-2026", "200.000", "20", "80"],
    ["01-03-2026", "100.000", "10", "40"],
]


def _monthly_workbook(folder: Path) -> Path:
    # Jan-Mar 2026 and a file that ends on the 15th: the last month is partial.
    sheet = [SHOP_HEADER, ["01-01-2026-15-03-2026", "600.000", "60", "220"], [], SHOP_HEADER]
    return _write_xlsx(
        folder / "synthetic.shopee-shop-stats.20260101-20260315.xlsx",
        {
            "Đơn hàng đã đặt": [*sheet, *MONTH_ROWS],
            "Đơn đã xác nhận": [*sheet, *MONTH_ROWS],
        },
    )


def test_g02_monthly_rows_become_one_period_post_per_month_never_day_rows(tmp_path):
    _monthly_workbook(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    assert _by(parsed.posts, "shop_overview", "placed") == []
    assert _by(parsed.posts, "shop_overview", "confirmed") == []
    months = _by(parsed.posts, "shop_overview_period", "confirmed")
    assert [(p.body["period"]["start"], p.body["period"]["end"]) for p in months] == [
        ("2026-01-01", "2026-01-31"),
        ("2026-02-01", "2026-02-28"),
        ("2026-03-01", "2026-03-15"),  # cut at the file's last day
    ]
    assert {p.body["period"]["granularity"] for p in months} == {"period"}
    assert [p.body["rows"] for p in months][0] == [{"sales": 300000, "orders": 30, "visitors": 100}]
    assert len(_by(parsed.posts, "shop_overview_period", "placed")) == 3
    assert sum(c for n, c in parsed.notes.items() if "monthly roll-up, 3 months" in n) == 2


def test_g02_a_daily_file_next_to_a_monthly_one_is_unchanged(tmp_path):
    _monthly_workbook(tmp_path)
    _shop_stats(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (daily,) = _by(parsed.posts, "shop_overview", "confirmed")
    assert [r["date"] for r in daily.body["rows"]] == ["2026-10-01", "2026-10-02"]


def test_g02_an_unclear_sheet_is_skipped_with_a_reason_never_guessed(tmp_path):
    scattered = [SHOP_HEADER, ["04-01-2026", "1", "1", "1"], ["09-02-2026", "1", "1", "1"]]
    name = "synthetic.shopee-shop-stats.20260101-20260331.xlsx"
    _write_xlsx(tmp_path / name, {"Đơn đã xác nhận": scattered})
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert "granularity cannot be told" in parsed.skipped_reasons[name]
    assert any("granularity cannot be told" in note for note in parsed.notes)
    assert "granularity cannot be told" in load_shopee_exports.summary(parsed)


def test_g02_a_monthly_traffic_sheet_goes_to_the_period_dataset(tmp_path):
    header = ["Nguồn lưu lượng", "Doanh số (VND)", "Lượt nhấp vào sản phẩm"]
    sheet = [
        ["Thẻ sản phẩm"],
        header,
        ["Thẻ sản phẩm", "900.000", "90"],
        ["01-01-2026", "500.000", "50"],
        ["01-02-2026", "400.000", "40"],
    ]
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20260101-20260228.xlsx",
        {"(đơn đã xác nhận)Theo nguồn...": sheet},
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    assert _by(parsed.posts, "traffic_overview", "confirmed") == []
    months = _by(parsed.posts, "traffic_overview_period", "confirmed")
    periods = [(p.body["period"]["start"], p.body["period"]["end"]) for p in months]
    assert periods == [("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]
    assert months[0].body["rows"] == [
        {"source": "psd_label_product_card", "sales": 500000, "product_clicks": 50}
    ]


@pytest.mark.parametrize("kind", ["productoverview", "traffic"])
def test_g02_monthly_rows_in_a_dataset_without_a_period_twin_are_skipped(tmp_path, kind):
    if kind == "productoverview":
        name = "productoverview20260101-20260228.xlsx"
        _write_xlsx(
            tmp_path / name,
            {
                "overview": [
                    OVERVIEW_HEADER,
                    ["01-01-2026", "1", "1,00%", "1", "1", "1,00%", "1", "1", "1,00%"],
                    ["01-02-2026", "1", "1,00%", "1", "1", "1,00%", "1", "1", "1,00%"],
                ]
            },
        )
    else:
        name = "traffic_overview_20260101_20260228.xlsx"
        _write_xlsx(
            tmp_path / name,
            {
                "Tất cả": [
                    TRAFFIC_HEADER,
                    ["01-01-2026", "1", "1,00%", "0"],
                    ["01-02-2026", "1", "1,00%", "0"],
                ]
            },
        )
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert "monthly roll-up" in parsed.skipped_reasons[name]


# -- G-23: Flash Sale day rows from two files on one key ---------------------------------

CHART_HEADER = ["Ngày", "Loại khuyến mãi", "Bán hàng (đặt hàng) (VND)", "Đơn đặt hàng (đặt hàng)"]
FLASH_DAY_HEADER = ["Thời Gian", "Bán hàng (đặt hàng)(₫)", "Đơn đặt hàng (đặt hàng)"]


def _flash_pair(folder: Path) -> None:
    # discount says 100 / 1 and 200 / 2 for Oct 1-2 plus Oct 3; the metrics file covers Oct 1-2
    # with its own figures. Oct 3 only the discount file has.
    _write_xlsx(
        folder / "discount_20261001-20261003.xlsx",
        {
            "Biểu đồ": [
                CHART_HEADER,
                ["01-10-2026", "Flash Sale", "100", "1"],
                ["02-10-2026", "Flash Sale", "200", "2"],
                ["03-10-2026", "Flash Sale", "300", "3"],
                ["01-10-2026", "Voucher", "50", "1"],
            ]
        },
    )
    _write_xlsx(
        folder / "In_Shop_Flash_Sale_Metrics_01102026-02102026.xlsx",
        {
            "Chỉ Số": [
                FLASH_DAY_HEADER,
                ["01-10-2026", "111", "11"],
                ["02-10-2026", "222", "22"],
            ]
        },
    )


def test_g23_the_flash_sale_metrics_file_owns_the_days_it_covers(tmp_path):
    _flash_pair(tmp_path)
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    flash = {}
    for post in _by(parsed.posts, "promotion_daily", "placed"):
        for row in post.body["rows"]:
            if row["promo_type"] == "Flash Sale":
                assert row["date"] not in flash, "one source per key"
                flash[row["date"]] = (post.file, row["sales"])
    assert flash == {
        "2026-10-01": ("In_Shop_Flash_Sale_Metrics_01102026-02102026.xlsx", 111),
        "2026-10-02": ("In_Shop_Flash_Sale_Metrics_01102026-02102026.xlsx", 222),
        "2026-10-03": ("discount_20261001-20261003.xlsx", 300),  # only the discount file
    }
    # The discount file's other promotion types are untouched.
    discount_types = [
        r["promo_type"]
        for p in _by(parsed.posts, "promotion_daily", "placed")
        if p.file.startswith("discount")
        for r in p.body["rows"]
    ]
    assert sorted(discount_types) == ["Flash Sale", "Voucher"]
    assert any("2 Flash Sale day rows dropped" in note for note in parsed.notes)


def test_g23_the_result_does_not_depend_on_file_order(tmp_path):
    _flash_pair(tmp_path)
    forward = parse.parse_folder(tmp_path)

    def keyed(p):
        return sorted(
            (post.body["order_type"], r["date"], r["promo_type"], r.get("sales"))
            for post in p.posts
            if post.dataset == "promotion_daily"
            for r in post.body["rows"]
        )

    # Reverse the post order the way a different file sort would.
    backward = parse.Parsed(posts=list(reversed(forward.posts)))
    parse._one_flash_sale_owner(backward)
    assert keyed(forward) == keyed(backward)


def test_shopee_conversion_ratio_above_one_is_not_posted_and_the_post_still_validates(tmp_path):
    header = [*SHOP_HEADER, "Tỷ lệ chuyển đổi đơn hàng"]
    _write_xlsx(
        tmp_path / "synthetic.shopee-shop-stats.20261001-20261002.xlsx",
        {
            "Đơn đã xác nhận": [
                header,
                ["01-10-2026-02-10-2026", "300.000", "3", "3", "100,00%"],
                [],
                header,
                ["01-10-2026", "100.000", "1", "2", "50,00%"],
                ["02-10-2026", "200.000", "2", "1", "200,00%"],  # orders > visitors
            ],
        },
    )
    parsed = parse.parse_folder(tmp_path)
    _validates(parsed.posts)
    (overview,) = _by(parsed.posts, "shop_overview", "confirmed")
    assert [r["orders"] for r in overview.body["rows"]] == [1, 2]
    assert all("conversion_rate" not in r for r in overview.body["rows"])
