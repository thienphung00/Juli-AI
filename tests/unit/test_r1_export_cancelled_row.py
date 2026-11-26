"""Owner #103 10a: the Tổng quan export's product sheet gives the cancelled-after-confirmation
share its own row, so "Cả shop" carries only what no product and no cancelled order owns."""

from __future__ import annotations

from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import with_cancelled_row


def _rest(gmv: float, orders: float) -> tq.ProductRow:
    return tq.ProductRow(
        tq.SHOP_ROW_LABEL,
        tq.SHOP_ROW_NAME,
        tq.Figures(gmv=gmv, orders=orders),
        tq.Figures(gmv=gmv, orders=orders),
    )


def test_the_cancelled_share_leaves_the_shop_row_and_gets_its_own():
    rows = with_cancelled_row(_rest(300_000, 6), (275_000, 1), (0, 0))
    cancelled, rest = rows
    assert (rest.now.gmv, rest.now.orders) == (25_000, 5)
    assert cancelled.name == tq.CANCELLED_ROW_NAME == "Đơn hủy sau xác nhận"
    assert (cancelled.now.gmv, cancelled.now.orders) == (275_000, 1)
    # the sheet still sums to the shop
    assert rest.now.gmv + cancelled.now.gmv == 300_000


def test_a_zero_share_adds_no_row():
    rows = with_cancelled_row(_rest(300_000, 6), (0, 0), (0, 0))
    assert len(rows) == 1 and rows[0].now.gmv == 300_000


def test_the_sheet_writes_the_row_with_its_label():
    from openpyxl import Workbook

    rows = with_cancelled_row(_rest(300_000, 6), (275_000, 1), (0, 0))
    wb = Workbook()
    data = tq.TongQuanData(
        shop_name="s",
        start=__import__("datetime").date(2026, 11, 1),
        end=__import__("datetime").date(2026, 11, 7),
        prev_start=__import__("datetime").date(2026, 10, 25),
        prev_end=__import__("datetime").date(2026, 10, 31),
        now=tq.Figures(gmv=300_000),
        prev=tq.Figures(gmv=300_000),
        products=rows,
    )
    tq._products(wb, data)
    ws = wb[tq.SHEET_PRODUCT]
    labels = [ws.cell(r, 2).value for r in range(4, 4 + len(rows))]
    assert "Đơn hủy sau xác nhận" in labels
