"""Seller Centre export files → ingest gateway posts (ADR-117 §1-§3).

Pure: a folder of exports in, a list of :class:`Post` out, nothing sent. Only the
export kinds below are read; any other file (in particular the ``Đơn hàng`` and
``Quản lý đánh giá`` exports, which carry buyer data, HĐDV 5.1) is listed as skipped
and never opened.

- ``*.shopee-shop-stats.<from>-<to>.xlsx``:
  ``Đơn hàng đã đặt`` / ``Đơn đã xác nhận`` / ``Đơn Đã Thanh Toán`` → ``shop_overview``;
  ``(đơn …)Theo nguồn lưu lượng`` day rows → ``traffic_overview``, total rows →
  ``traffic_overview_period``; ``Theo sản phẩm (đơn …)`` → ``item_by_source_period``.
- ``parentskudetail.<from>_<to>.xlsx``: ``Sản Phẩm Hiệu Quả Tốt`` → ``product_period``;
  the flag sheets → ``product_flags``.
- ``discount_<from>-<to>.xlsx``: ``Biểu đồ`` → ``promotion_daily``;
  ``Danh sách hiệu suất`` → ``promotions``.
- ``productoverview<from>-<to>.xlsx``: ``overview`` → ``product_overview``.
- ``traffic_overview_<from>_<to>.xlsx``: ``Tất cả`` / ``Máy tính`` / ``Ứng dụng`` →
  ``shop_traffic``.

A header the parser does not know raises :class:`UnknownColumn` (Seller Centre changed
the export: fix the table here, never guess). Numbers are Vietnamese-formatted text
("12.345.678", "123.456,70", "4,25%"); ``-`` is no value.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from scripts.shopee_exports.xlsx import Rows, read_workbook

SOURCE_VERSION = "seller-centre-xlsx-1"
MAX_ROWS = 2_000
MAX_PERIOD_DAYS = 31
PLATFORM_TZ = timedelta(hours=7)

_DAY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
_RANGE = re.compile(r"^\d{2}-\d{2}-\d{4}\s*-\s*\d{2}-\d{2}-\d{4}$")
_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")
_CLOCK = re.compile(r"^(\d+):(\d{2}):(\d{2})$")
_RUN = re.compile(
    r"^(\d{2}):(\d{2}) (\d{2})-(\d{2})-(\d{4})\s*-\s*(\d{2}):(\d{2}) (\d{2})-(\d{2})-(\d{4})$"
)
_FILE_PERIOD = re.compile(r"(\d{8})[-_](\d{8})\.xlsx$")


class UnknownColumn(ValueError):
    """An export header this parser has no field for."""


@dataclass
class Post:
    """One ``POST /v1/ingest/shopee/{dataset}`` body, plus where it came from."""

    dataset: str
    body: dict[str, Any]
    file: str


@dataclass
class Parsed:
    posts: list[Post] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    #: (file, reason) for rows / cards deliberately not loaded.
    notes: Counter[str] = field(default_factory=Counter)


# -- values ------------------------------------------------------------------------------


def number(text: str | None) -> int | float | None:
    """A Seller Centre cell as a JSON number; ``-`` / empty → None."""
    if text is None:
        return None
    raw = text.strip()
    if raw in ("", "-"):
        return None
    clock = _CLOCK.match(raw)
    if clock:
        hours, minutes, seconds = (int(part) for part in clock.groups())
        return hours * 3600 + minutes * 60 + seconds
    percent = raw.endswith("%")
    if percent:
        raw = raw[:-1].strip()
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif _THOUSANDS.match(raw):
        raw = raw.replace(".", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"not a number: {text!r}") from None
    if percent:
        value = value / 100
    return int(value) if value == value.to_integral_value() else float(value)


def day(text: str) -> date:
    match = _DAY.match(text.strip())
    if match is None:
        raise ValueError(f"not a DD-MM-YYYY day: {text!r}")
    dd, mm, yyyy = (int(part) for part in match.groups())
    return date(yyyy, mm, dd)


def _is_day(text: str | None) -> bool:
    return bool(text) and bool(_DAY.match(str(text).strip()))


def _blank(row: list[str | None]) -> bool:
    return not any(cell not in (None, "") for cell in row)


def _file_period(path: Path) -> tuple[date, date]:
    match = _FILE_PERIOD.search(path.name)
    if match is None:
        raise ValueError(f"no YYYYMMDD period in {path.name}")
    start, end = (datetime.strptime(part, "%Y%m%d").date() for part in match.groups())
    return start, end


def _captured_at(path: Path) -> str:
    """The export's file time, in the platform's zone (GMT+7)."""
    stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC) + PLATFORM_TZ
    return stamp.replace(tzinfo=None).isoformat(timespec="seconds") + "+07:00"


# -- column tables -----------------------------------------------------------------------

#: ``(field, order_type or None)``; None = the same for every order type. ``None`` as the
#: field = a column read but not posted (Shopee's own derived share, a duplicate).
Column = tuple[str | None, str | None]
PLACED, CONFIRMED, PAID = "placed", "confirmed", "paid"

SHOP_OVERVIEW: dict[str, Column] = {
    "Tổng doanh số (VND)": ("sales", None),
    "Doanh số không bao gồm trợ giá bởi Shopee": ("sales_excl_shopee_subsidy", None),
    "Tổng số đơn hàng": ("orders", None),
    "Doanh số trên mỗi đơn hàng": ("sales_per_order", None),
    "Lượt nhấp vào sản phẩm": ("product_clicks", None),
    "Số lượt truy cập": ("visitors", None),
    "Tỷ lệ chuyển đổi đơn hàng": ("conversion_rate", None),
    "Đơn đã hủy": ("cancelled_orders", None),
    "Doanh số đơn hủy": ("cancelled_sales", None),
    "Đơn đã hoàn trả / hoàn tiền": ("returned_orders", None),
    "Doanh số các đơn Trả hàng/Hoàn tiền": ("returned_sales", None),
    "số người mua": ("buyers", None),
    "số người mua mới": ("new_buyers", None),
    "số người mua hiện tại": ("existing_buyers", None),
    "số người mua tiềm năng": ("potential_buyers", None),
    "Tỉ lệ quay lại của người mua": ("repeat_purchase_rate", None),
}
SHOP_OVERVIEW_SHEETS: dict[str, str] = {
    "Đơn hàng đã đặt": PLACED,
    "Đơn đã xác nhận": CONFIRMED,
    "Đơn Đã Thanh Toán": PAID,
}

#: ``(đơn …)Theo nguồn lưu lượng`` / ``Theo sản phẩm (đơn …)``: the per-source metric set.
SOURCE_METRICS: dict[str, Column] = {
    "Tỷ lệ doanh số": (None, None),
    "Doanh số (VND)": ("sales", None),
    "Lượt hiển thị sản phẩm": ("product_impressions", None),
    "Lượt xem Livestream": ("live_views", None),
    "Lượt xem Video": ("video_views", None),
    "Lượt xem nội dung": ("content_views", None),
    "Ads Impression": ("ads_impressions", None),
    "Lượt nhấp vào sản phẩm": ("product_clicks", None),
    "Tổng số đơn hàng": ("orders", None),
    "Sản phẩm": ("units", None),
    # Shopee's own ratios of the counts above are not posted: an L2 source can have more
    # clicks than impressions, so the ratio exceeds 1
    # and the gateway's rate guard (a fraction in [0, 1]) would refuse it. Readers compute
    # CTR and click-to-order rates from the posted counts.
    "CTR": (None, None),
    "Tỷ lệ chuyển đổi đơn hàng": (None, None),
    "Tỷ lệ chuyển đổi": ("conversion", None),
    "Doanh số trên mỗi đơn hàng": ("sales_per_order", None),
    "Người mua": ("buyers", None),
    "Lượt hiển thị sản phẩm duy nhất": ("unique_product_impressions", None),
    "Người xem Livestream": ("live_viewers", None),
    "Người xem Video": ("video_viewers", None),
    "Người xem nội dung": ("content_viewers", None),
    "Lượt nhấp sản phẩm duy nhất": ("unique_product_clicks", None),
    "Chi phí quảng cáo": ("ads_expense", None),
    "ROAS quảng cáo": ("ads_roas", None),
}
L1_GROUPS: dict[str, str] = {
    "Thẻ sản phẩm": "psd_label_product_card",
    "Live": "psd_label_seller_live",
    "Video": "psd_label_seller_video",
    "Tiếp thị liên kết": "psd_label_affiliate",
    "Dịch vụ Hiển thị Shopee": "psd_label_shopee_ads",
}
#: Matched on short fragments: Excel cuts sheet names at 31 characters ("…đã xác n...").
_SHEET_ORDER_TYPE = (("đã đặt", PLACED), ("đã xác", CONFIRMED), ("đã thanh", PAID))

PRODUCT_PERIOD: dict[str, Column] = {
    "Doanh số (Đơn đã đặt) (VND)": ("sales", PLACED),
    "Doanh số (Đơn đã xác nhận) (VND)": ("sales", CONFIRMED),
    "Lượt xem sản phẩm": ("product_impressions", None),
    "Lượt nhấp vào sản phẩm": ("product_clicks", None),
    "CTR": ("ctr", None),
    "Tỷ lệ chuyển đổi đơn (Đơn đã đặt)": ("product_clicks_to_orders_rate", PLACED),
    "Tỷ lệ chuyển đổi đơn (Đơn đã xác nhận)": ("product_clicks_to_orders_rate", CONFIRMED),
    "Đơn hàng đã đặt": ("orders", PLACED),
    "Đơn đã xác nhận": ("orders", CONFIRMED),
    "Sản phẩm (Đơn đã đặt)": ("units", PLACED),
    "Sản phẩm (Đơn đã xác nhận)": ("units", CONFIRMED),
    "Người mua đã đặt hàng": ("buyers", PLACED),
    "Người mua có đơn đã xác nhận": ("buyers", CONFIRMED),
    "Tỷ lệ chuyển đổi (Đơn đã đặt)": ("conversion_rate", PLACED),
    "Tỷ lệ chuyển đổi (Đơn đã xác nhận)": ("conversion_rate", CONFIRMED),
    "Doanh thu trên mỗi đơn (Đơn đã đặt) (VND)": ("sales_per_order", PLACED),
    "Doanh thu trên mỗi đơn (Đơn đã xác nhận) (VND)": ("sales_per_order", CONFIRMED),
    "Lượt hiển thị sản phẩm duy nhất": ("unique_product_impressions", None),
    "Lượt nhấp sản phẩm duy nhất": ("unique_product_clicks", None),
    "Lượt truy cập sản phẩm": ("product_visitors", None),
    "Lượt xem trang sản phẩm": ("product_page_views", None),
    "Số lượng khách thoát trang sản phẩm": ("bounced_visitors", None),
    "Tỷ lệ thoát Trang sản phẩm": ("bounce_rate", None),
    "Lượt click từ Trang tìm kiếm": ("search_clicks", None),
    "Lượt thích": ("likes", None),
    "Lượt truy cập sản phẩm (Thêm vào giỏ hàng)": ("atc_visitors", None),
    "Sản phẩm (Thêm vào giỏ hàng)": ("atc_units", None),
    "Tỷ lệ chuyển đổi (theo lượt thêm vào giỏ hàng)": ("atc_rate", None),
    "Tỷ lệ mua lại (Đơn đã đặt)": ("repeat_purchase_rate", PLACED),
    "Tỷ lệ đặt hàng lặp lại (Đơn hàng đã được xác nhận)": ("repeat_purchase_rate", CONFIRMED),
    "Số ngày trung bình mà Người mua quay lại đặt hàng (Đơn đã đặt)": (
        "repeat_purchase_days",
        PLACED,
    ),
    "Số ngày trung bình để lặp lại đơn hàng (Đơn hàng đã được xác nhận)": (
        "repeat_purchase_days",
        CONFIRMED,
    ),
}
_PRODUCT_IDENTITY = {
    "Mã sản phẩm",
    "Sản phẩm",
    "Tình trạng sản phẩm hiện tại",
    "Mã phân loại hàng",
    "Tên Phân Loại",
    "Trạng thái phân loại sản phẩm hiện tại",
    "SKU phân loại",
    "SKU sản phẩm",
}
#: ``parentskudetail`` flag sheets, matched by prefix (Excel cuts sheet names at 31).
FLAG_SHEETS: tuple[tuple[str, str], ...] = (
    ("Sản Phẩm Mới", "new_product"),
    ("Giá cạnh tranh", "price_competitive"),
    ("Giá không cạnh tranh", "price_uncompetitive"),
    ("Tăng trưởng cùng DVHT", "ads_grow"),
    ("Tối ưu chiến dịch DVHT", "ads_optimize"),
    ("Theo dõi hiệu quả chiến dịc", "ads_track"),
)
PRODUCTS_SHEET = "Sản Phẩm Hiệu Quả Tốt"

PROMOTION: dict[str, Column] = {
    "Bán hàng (đặt hàng) (VND)": ("sales", PLACED),
    "Bán hàng (Đơn đặt hàng được xác nhận) (VND)": ("sales", CONFIRMED),
    "Đơn đặt hàng (đặt hàng)": ("orders", PLACED),
    "Đơn đặt hàng (Đơn đặt hàng được xác nhận)": ("orders", CONFIRMED),
    "Đơn vị được bán (đặt hàng)": ("units", PLACED),
    "Đơn vị được bán (đơn đặt hàng được xác nhận)": ("units", CONFIRMED),
    "Người mua (đặt hàng)": ("buyers", PLACED),
    "Người mua (Đơn đặt hàng được xác nhận)": ("buyers", CONFIRMED),
    "Bán hàng cho mỗi người mua (đặt hàng) (VND)": ("sales_per_buyer", PLACED),
    "Bán hàng cho mỗi người mua (đơn đặt hàng được xác nhận) (VND)": ("sales_per_buyer", CONFIRMED),
}
#: Bundle / add-on breakdown columns: '-' in every Ory export so far; not posted.
_PROMOTION_IGNORED_PREFIXES = (
    "Các giao dịch gói",
    "Bán hàng của các mặt hàng chính",
    "Bán hàng bổ trợ",
    "Đơn vị của các mặt hàng",
    "Doanh số bán hàng của các mặt hàng chính",
)

PRODUCT_OVERVIEW: dict[str, Column] = {
    "Lượt truy cập sản phẩm": ("product_visitors", None),
    "Lượt xem trang sản phẩm": ("product_page_views", None),
    "Sản phẩm được truy cập": ("products_visited", None),
    "Số lượng khách thoát trang sản phẩm": ("bounced_visitors", None),
    "Tỷ lệ thoát Trang sản phẩm": ("bounce_rate", None),
    "Lượt click từ Trang tìm kiếm": ("search_clicks", None),
    "Lượt thích": ("likes", None),
    "Lượt truy cập sản phẩm (Thêm vào giỏ hàng)": ("atc_visitors", None),
    "Sản phẩm (Thêm vào giỏ hàng)": ("atc_units", None),
    "Tỷ lệ chuyển đổi (theo lượt thêm vào giỏ hàng)": ("atc_rate", None),
    "Người mua đã đặt hàng": ("buyers", PLACED),
    "Sản phẩm (Đơn đã đặt)": ("units", PLACED),
    "Số sản phẩm đã bán": ("products_sold", PLACED),
    "Doanh số (Đơn đã đặt) (VND)": ("sales", PLACED),
    "Tỷ lệ chuyển đổi (Đơn đã đặt)": ("conversion_rate", PLACED),
    "Người mua có đơn đã xác nhận": ("buyers", CONFIRMED),
    "Sản phẩm (Đơn đã xác nhận)": ("units", CONFIRMED),
    "Sản phẩm được duyệt": ("products_sold", CONFIRMED),
    "Doanh số (Đơn đã xác nhận) (VND)": ("sales", CONFIRMED),
    "Tỷ lệ chuyển đổi (Đơn đã xác nhận)": ("conversion_rate", CONFIRMED),
    "Tỷ lệ chuyển đổi (Từ Đơn đã đặt thành Đơn đã xác nhận)": (
        "extra.placed_to_confirmed_rate",
        None,
    ),
}

SHOP_TRAFFIC: dict[str, Column] = {
    "Lượt xem": ("page_views", None),
    "Số lượt xem trung bình": ("avg_page_views", None),
    "Thời gian xem trung bình": ("avg_stay_time", None),
    "Tỉ lệ thoát trang": ("bounce_rate", None),
    "Lượt truy cập": ("visitors", None),
    "Số khách truy cập mới": ("new_visitors", None),
    "Số khách truy cập hiện tại": ("existing_visitors", None),
    "Người theo dõi mới": ("new_followers", None),
}
SHOP_TRAFFIC_SHEETS: dict[str, str] = {"Tất cả": "all", "Máy tính": "pc", "Ứng dụng": "app"}


def _columns(header: list[str | None], table: dict[str, Column]) -> list[Column | None]:
    """The table entry for each header cell (``None`` for the day / identity columns)."""
    out: list[Column | None] = []
    for cell in header:
        name = (cell or "").strip()
        if name in table:
            out.append(table[name])
        elif name in ("", "Ngày", "Loại Đơn Hàng", "Nguồn lưu lượng", "Loại khuyến mãi"):
            out.append(None)
        else:
            raise UnknownColumn(name)
    return out


def _values(
    row: list[str | None], columns: list[Column | None], order_type: str | None
) -> dict[str, Any]:
    """The row's posted fields for one order type (columns of another type skipped)."""
    out: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for cell, column in zip(row, columns, strict=False):
        if column is None:
            continue
        name, column_type = column
        if name is None:
            continue
        if column_type is not None and column_type != order_type:
            continue
        value = number(cell)
        if value is None:
            continue
        if name.startswith("extra."):
            extra[name.removeprefix("extra.")] = value
        else:
            out[name] = value
    if extra:
        out["extra"] = extra
    return out


# -- bodies ------------------------------------------------------------------------------


def _months(start: date, end: date) -> Iterator[tuple[date, date]]:
    """``[start, end]`` cut at calendar months, so no piece exceeds 31 days."""
    cursor = start
    while cursor <= end:
        next_month = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
        piece_end = min(end, next_month - timedelta(days=1))
        yield cursor, piece_end
        cursor = piece_end + timedelta(days=1)


def _daily_posts(
    dataset: str,
    rows: list[dict[str, Any]],
    *,
    order_type: str | None,
    captured_at: str,
    file: str,
) -> list[Post]:
    if not rows:
        return []
    days = sorted(date.fromisoformat(row["date"]) for row in rows)
    posts = []
    for start, end in _months(days[0], days[-1]):
        piece = [row for row in rows if start <= date.fromisoformat(row["date"]) <= end]
        if not piece:
            continue
        # The body's period is the piece's own days, never a month end past the data.
        start, end = (
            min(date.fromisoformat(r["date"]) for r in piece),
            max(date.fromisoformat(r["date"]) for r in piece),
        )
        for offset in range(0, len(piece), MAX_ROWS):
            posts.append(
                Post(
                    dataset,
                    _body(
                        piece[offset : offset + MAX_ROWS],
                        start,
                        end,
                        "day",
                        order_type,
                        captured_at,
                    ),
                    file,
                )
            )
    return posts


def _period_post(
    dataset: str,
    rows: list[dict[str, Any]],
    start: date,
    end: date,
    *,
    order_type: str | None,
    captured_at: str,
    file: str,
) -> list[Post]:
    if not rows:
        return []
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError(f"{file}: a {dataset} period longer than {MAX_PERIOD_DAYS} days")
    return [
        Post(
            dataset,
            _body(rows[i : i + MAX_ROWS], start, end, "period", order_type, captured_at),
            file,
        )
        for i in range(0, len(rows), MAX_ROWS)
    ]


def _body(
    rows: list[dict[str, Any]],
    start: date,
    end: date,
    granularity: str,
    order_type: str | None,
    captured_at: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "file",
        "source_version": SOURCE_VERSION,
        "captured_at": captured_at,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "granularity": granularity},
        "rows": rows,
    }
    if order_type is not None:
        body["order_type"] = order_type
    return body


# -- shop-stats --------------------------------------------------------------------------


def _sheet_order_type(name: str) -> str | None:
    lowered = name.lower()
    for fragment, order_type in _SHEET_ORDER_TYPE:
        if fragment in lowered:
            return order_type
    return None


def _shop_overview(sheet: Rows, order_type: str, captured_at: str, file: str) -> list[Post]:
    rows: list[dict[str, Any]] = []
    columns: list[Column | None] | None = None
    for row in sheet:
        if _blank(row):
            continue
        if row[0] == "Ngày":
            columns = _columns(row, SHOP_OVERVIEW)
            continue
        if columns is None or not _is_day(row[0]):
            continue  # the export's own period-total row
        rows.append({"date": day(str(row[0])).isoformat(), **_values(row, columns, None)})
    return _daily_posts(
        "shop_overview", rows, order_type=order_type, captured_at=captured_at, file=file
    )


def _source_blocks(
    sheet: Rows, parsed: Parsed, file: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(day rows, period-total rows) of a ``(đơn …)Theo nguồn lưu lượng`` sheet."""
    daily: list[dict[str, Any]] = []
    totals: list[dict[str, Any]] = []
    group: str | None = None
    columns: list[Column | None] | None = None
    label_row: dict[str, Any] | None = None
    first_label = False
    for row in sheet:
        if _blank(row):
            continue
        cells = [c for c in row if c not in (None, "")]
        if len(cells) == 1 and str(row[0]).strip() in L1_GROUPS:
            group, columns, label_row = L1_GROUPS[str(row[0]).strip()], None, None
            continue
        if group is None:
            continue
        if row[0] == "Nguồn lưu lượng":
            columns, first_label = _columns(row, SOURCE_METRICS), True
            continue
        if columns is None:
            continue
        label = str(row[0]).strip()
        if _is_day(label):
            if label_row is None:
                raise ValueError(f"{file}: a day row before any source label")
            values = _values(row, columns, None)
            if values:
                daily.append({"date": day(label).isoformat(), **label_row, **values})
            continue
        group_name = next(name for name, code in L1_GROUPS.items() if code == group)
        is_total = first_label and label == group_name
        first_label = False
        label_row = {"source": group}
        if not is_total:
            label_row["sub_source"] = label
        values = _values(row, columns, None)
        if values:
            totals.append({**label_row, **values})
        else:
            parsed.notes[f"{file}: source total with no values"] += 1
    return daily, totals


def _items_by_source(sheet: Rows) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    group: str | None = None
    columns: list[Column | None] | None = None
    for row in sheet:
        if _blank(row):
            continue
        cells = [c for c in row if c not in (None, "")]
        if len(cells) == 1 and str(row[0]).strip() in L1_GROUPS:
            group, columns = L1_GROUPS[str(row[0]).strip()], None
            continue
        if group is None:
            continue
        if row[0] == "Mã sản phẩm":
            # Columns 0-2 are the item (id, name, status); the later "Sản phẩm" is units.
            columns = [None, None, None, *_columns(row[3:], SOURCE_METRICS)]
            continue
        if columns is None or not str(row[0]).strip().isdigit():
            continue
        values = _values(row, columns, None)
        if not values:
            continue
        item: dict[str, Any] = {"item_id": str(row[0]).strip(), "source": group}
        if row[1]:
            item["item_name"] = str(row[1]).strip()[:500]
        if len(row) > 2 and row[2]:
            item["item_status"] = str(row[2]).strip()[:64]
        rows.append({**item, **values})
    return rows


def parse_shop_stats(path: Path, parsed: Parsed) -> None:
    start, end = _file_period(path)
    captured = _captured_at(path)
    file = path.name
    for name, sheet in read_workbook(path).items():
        if name in SHOP_OVERVIEW_SHEETS:
            parsed.posts += _shop_overview(sheet, SHOP_OVERVIEW_SHEETS[name], captured, file)
            continue
        order_type = _sheet_order_type(name)
        if name.startswith("(") and "Theo ngu" in name and order_type:
            daily, totals = _source_blocks(sheet, parsed, file)
            parsed.posts += _daily_posts(
                "traffic_overview", daily, order_type=order_type, captured_at=captured, file=file
            )
            parsed.posts += _period_post(
                "traffic_overview_period",
                totals,
                start,
                end,
                order_type=order_type,
                captured_at=captured,
                file=file,
            )
        elif name.startswith("Theo sản phẩm") and order_type:
            parsed.posts += _period_post(
                "item_by_source_period",
                _items_by_source(sheet),
                start,
                end,
                order_type=order_type,
                captured_at=captured,
                file=file,
            )
        else:
            parsed.notes[f"{file}: sheet not loaded (summary): {name}"] += 1


# -- parentskudetail ---------------------------------------------------------------------


def _id(cell: str | None) -> str:
    text = (cell or "").strip()
    return "" if text in ("", "-") else text


def parse_products(path: Path, parsed: Parsed) -> None:
    start, end = _file_period(path)
    captured = _captured_at(path)
    file = path.name
    sheets = read_workbook(path)
    if PRODUCTS_SHEET in sheets:
        sheet = sheets[PRODUCTS_SHEET]
        header = [str(c or "").strip() for c in sheet[0]]
        columns = _columns(
            [None if name in _PRODUCT_IDENTITY else name for name in header], PRODUCT_PERIOD
        )
        for order_type in (PLACED, CONFIRMED):
            rows: list[dict[str, Any]] = []
            for row in sheet[1:]:
                if _blank(row):
                    continue
                cell = dict(zip(header, row, strict=False))
                item_id, variation_id = (
                    _id(cell.get("Mã sản phẩm")),
                    _id(cell.get("Mã phân loại hàng")),
                )
                if not item_id.isdigit() or (variation_id and not variation_id.isdigit()):
                    parsed.notes[f"{file}: product row without numeric ids"] += 1
                    continue
                values = _values(row, columns, order_type)
                out: dict[str, Any] = {"item_id": item_id, "variation_id": variation_id}
                identity = {
                    "item_name": (cell.get("Sản phẩm"), 500),
                    "item_status": (cell.get("Tình trạng sản phẩm hiện tại"), 64),
                    "variation_name": (cell.get("Tên Phân Loại"), 255),
                    "variation_status": (cell.get("Trạng thái phân loại sản phẩm hiện tại"), 64),
                    "seller_sku": (
                        cell.get("SKU phân loại") if variation_id else cell.get("SKU sản phẩm"),
                        100,
                    ),
                }
                for key, (text, width) in identity.items():
                    if text and str(text).strip() not in ("", "-"):
                        out[key] = str(text).strip()[:width]
                rows.append({**out, **values})
            parsed.posts += _period_post(
                "product_period",
                rows,
                start,
                end,
                order_type=order_type,
                captured_at=captured,
                file=file,
            )
    flags: list[dict[str, Any]] = []
    for name, sheet in sheets.items():
        flag = next((code for prefix, code in FLAG_SHEETS if name.startswith(prefix)), None)
        if flag is None:
            continue
        seen: set[str] = set()
        for row in sheet[1:]:
            item_id = _id(row[0] if row else None)
            if item_id.isdigit() and item_id not in seen:
                seen.add(item_id)
                flags.append({"item_id": item_id, "flag": flag})
    parsed.posts += _period_post(
        "product_flags", flags, start, end, order_type=None, captured_at=captured, file=file
    )


# -- discount ----------------------------------------------------------------------------


def _promotion_columns(header: list[str | None]) -> list[Column | None]:
    kept = [
        None
        if (cell or "").strip().startswith(_PROMOTION_IGNORED_PREFIXES)
        or (cell or "").strip()
        in ("Tên chương trình", "Thời gian diễn ra chương trình", "Trạng thái")
        else cell
        for cell in header
    ]
    return _columns(kept, PROMOTION)


def _run(text: str) -> tuple[str, str]:
    match = _RUN.match(text.strip())
    if match is None:
        raise ValueError(f"not a promotion run: {text!r}")
    h1, m1, d1, mo1, y1, h2, m2, d2, mo2, y2 = (int(part) for part in match.groups())
    return (
        datetime(y1, mo1, d1, h1, m1).isoformat(),
        datetime(y2, mo2, d2, h2, m2).isoformat(),
    )


def parse_discount(path: Path, parsed: Parsed) -> None:
    start, end = _file_period(path)
    captured = _captured_at(path)
    file = path.name
    sheets = read_workbook(path)
    chart = sheets.get("Biểu đồ", [])
    programs = sheets.get("Danh sách hiệu suất", [])
    for order_type in (PLACED, CONFIRMED):
        if chart:
            columns = _promotion_columns(chart[0])
            rows = [
                {
                    "date": day(str(r[0])).isoformat(),
                    "promo_type": str(r[1]).strip(),
                    **_values(r, columns, order_type),
                }
                for r in chart[1:]
                if not _blank(r) and _is_day(r[0])
            ]
            parsed.posts += _daily_posts(
                "promotion_daily", rows, order_type=order_type, captured_at=captured, file=file
            )
        if programs:
            columns = _promotion_columns(programs[0])
            seen: Counter[tuple[str, str, str]] = Counter()
            program_rows: list[dict[str, Any]] = []
            for r in programs[1:]:
                if _blank(r):
                    continue
                name, promo_type = str(r[0]).strip(), str(r[1]).strip()
                starts_at, ends_at = _run(str(r[2]))
                twin = (promo_type, name, starts_at)
                program_rows.append(
                    {
                        "program_name": name[:255],
                        "promo_type": promo_type,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "ordinal": seen[twin],
                        "status": str(r[3]).strip()[:64] if r[3] else None,
                        **_values(r, columns, order_type),
                    }
                )
                seen[twin] += 1
            parsed.posts += _period_post(
                "promotions",
                program_rows,
                start,
                end,
                order_type=order_type,
                captured_at=captured,
                file=file,
            )


# -- productoverview, traffic_overview ---------------------------------------------------


def _simple_daily(
    sheet: Rows, table: dict[str, Column], order_type: str | None, fixed: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    columns: list[Column | None] | None = None
    for row in sheet:
        if _blank(row):
            continue
        if row[0] == "Ngày":
            columns = _columns(row, table)
            continue
        if columns is None or not _is_day(row[0]):
            continue
        rows.append(
            {"date": day(str(row[0])).isoformat(), **fixed, **_values(row, columns, order_type)}
        )
    return rows


def parse_product_overview(path: Path, parsed: Parsed) -> None:
    captured = _captured_at(path)
    sheet = read_workbook(path).get("overview", [])
    for order_type in (PLACED, CONFIRMED):
        rows = _simple_daily(sheet, PRODUCT_OVERVIEW, order_type, {})
        parsed.posts += _daily_posts(
            "product_overview", rows, order_type=order_type, captured_at=captured, file=path.name
        )


def parse_shop_traffic(path: Path, parsed: Parsed) -> None:
    captured = _captured_at(path)
    rows: list[dict[str, Any]] = []
    for name, sheet in read_workbook(path).items():
        device = SHOP_TRAFFIC_SHEETS.get(name)
        if device is None:
            raise UnknownColumn(f"sheet {name}")
        rows += _simple_daily(sheet, SHOP_TRAFFIC, None, {"device": device})
    parsed.posts += _daily_posts(
        "shop_traffic", rows, order_type=None, captured_at=captured, file=path.name
    )


# -- folder ------------------------------------------------------------------------------

#: File name pattern → parser. Nothing else in the folder is opened.
PARSERS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"\.shopee-shop-stats\.\d{8}-\d{8}\.xlsx$"), parse_shop_stats),
    (re.compile(r"^parentskudetail\.\d{8}_\d{8}\.xlsx$"), parse_products),
    (re.compile(r"^discount_\d{8}-\d{8}\.xlsx$"), parse_discount),
    (re.compile(r"^productoverview\d{8}-\d{8}\.xlsx$"), parse_product_overview),
    (re.compile(r"^traffic_overview_\d{8}_\d{8}\.xlsx$"), parse_shop_traffic),
)


def parse_folder(folder: Path) -> Parsed:
    parsed = Parsed()
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        parser = next((fn for pattern, fn in PARSERS if pattern.search(path.name)), None)
        if parser is None:
            parsed.skipped_files.append(path.name)
            continue
        parser(path, parsed)
    return parsed
