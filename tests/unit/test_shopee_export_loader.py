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
  among them) are never opened;
- every post passes the gateway's own validation; a database host other than localhost is
  refused.

No client data: values are synthetic.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
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
    (tmp_path / "Order.all.20261001_20261028.xlsx").write_bytes(b"not a workbook")
    (tmp_path / "sales_composition_20261001-20261028.xlsx").write_bytes(b"not a workbook")
    parsed = parse.parse_folder(tmp_path)
    assert parsed.posts == []
    assert sorted(parsed.skipped_files) == [
        "Order.all.20261001_20261028.xlsx",
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
    assert [r["promo_type"] for r in chart.body["rows"]] == ["Tất cả", "Mua Kèm Deal Sốc"]


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
