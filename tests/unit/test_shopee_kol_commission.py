"""P91 D-9: the KOL on an affiliate order line, and which report column is the commission (G-15).

SYNTHETIC fixtures that mirror the real header set of ``SellerConversionReport`` and
``ValidationBill`` (every value invented). The reconciliation test is the method the owner
repeats on one real month; here it proves the code reads the rule the docstring states.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from juli_backend.services.ingest import affiliate_commission as rule
from juli_backend.services.ingest.kol_key import kol_key, normal_handle, short_hash
from juli_backend.services.ingest.mapping import dataset_spec, normalize_rows
from juli_backend.services.ingest.schemas import (
    ShopeeAffiliateOrderLineRow,
    ShopeeAffiliatePartnerPeriodRow,
)
from juli_backend.services.ingest.writers import _kol_columns
from scripts.shopee_exports import parse
from tests.unit.test_shopee_affiliate_loader import _validates
from tests.unit.test_shopee_export_loader import _write_csv

KEY = b"synthetic-test-key"

#: The full real header set (every column the parser knows), in the report's order.
FULL_HEADER = list(parse.CONVERSION_COLUMNS)


def _line(order: str, item: str, handle: str, cost: str, xtra: str, **over: str) -> list[str]:
    cells = dict.fromkeys(FULL_HEADER, "")
    cells.update(
        {
            "Mã đơn hàng": order,
            "Trạng thái đơn hàng": "Hoàn thành",
            "Trạng thái gian lận": "Hợp lệ",
            "Thời gian đặt hàng": "2026-10-12 10:00:00",
            "Mã sản phẩm": item,
            "Model id": "9900",
            "Giá(₫)": "50000",
            "Số lượng": "2",
            "Tài khoản Tiếp thị liên kết": handle,
            "Loại chiến dịch": "Chiến dịch mở rộng",
            "Giá trị đặt hàng(₫)": "100000",
            "Kênh": "Shopee Video",
            "Chi phí(₫)": cost,
            "Hoa hồng Xtra trên sản phẩm(₫)": xtra,
        }
    )
    cells.update(over)
    return [cells[h] for h in FULL_HEADER]


BILL_HEADER = [
    "Mã đối soát",
    "Tháng đối soát",
    "Hoa hồng hằng tháng(₫)",
    "Số tiền thuế(₫)",
    "Chi phí hàng tháng(₫)",
    "Trạng thái khấu trừ",
]


def _month_fixture(tmp_path: Path) -> tuple[parse.Parsed, list[ShopeeAffiliateOrderLineRow]]:
    # Three valid lines of October (costs 10_000 + 7_500 + 2_500) and one invalid line.
    rows = [
        FULL_HEADER,
        _line("ORD0001", "1001", "kol_alpha", "10000", "3000"),
        _line("ORD0002", "1002", "kol_beta", "7500", "0"),
        _line("ORD0003", "1001", "kol_alpha", "2500", "800", **{"Kênh": "Facebook"}),
        _line("ORD0004", "1001", "kol_gamma", "999", "0", **{"Trạng thái gian lận": "Gian lận"}),
    ]
    _write_csv(tmp_path / "SellerConversionReport_202611022133.csv", rows)
    # The bill of the month: commission = Σ Chi phí of the valid lines; cost adds 8 % tax.
    _write_csv(
        tmp_path / "ValidationBill202611022134.csv",
        [BILL_HEADER, ['="1000000000000001"', "2026-10", "20000", "1600", "21600", "Completed"]],
    )
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    _validates(parsed)
    lines = [
        ShopeeAffiliateOrderLineRow.model_validate(r)
        for p in parsed.posts
        if p.dataset == "affiliate_order_lines"
        for r in p.body["rows"]
    ]
    return parsed, lines


def test_the_kol_key_is_the_partner_segment_hash():
    spec = dataset_spec("shopee", "affiliate_partner_period")
    assert spec is not None
    (partner,) = normalize_rows(
        spec, [ShopeeAffiliatePartnerPeriodRow(affiliate_id="1234567", account="Kol_Alpha")]
    )
    assert kol_key("1234567") == partner.segment == short_hash("a", "1234567")
    assert kol_key("  Kol_Alpha ") == kol_key("kol_alpha")
    assert len(kol_key("anything")) == 13
    assert normal_handle("@Kol_Alpha ") == "kol_alpha"


def test_a_line_keeps_its_kol_channel_campaign_type_and_mcn_flag_never_the_raw_id():
    row = ShopeeAffiliateOrderLineRow(
        order_ref="a" * 32,
        item_id="1001",
        ordered_at="2026-10-12T10:00:00",
        affiliate_account="Kol_Alpha",
        channel="Facebook",
        campaign_type="Chiến dịch mục tiêu",
        mcn="Agency X",
        cost=Decimal(1000),
    )
    cols = _kol_columns(row)
    assert cols == {
        "kol_key": kol_key("Kol_Alpha"),
        "kol_handle": "Kol_Alpha",
        "affiliate_channel": "Facebook",
        "affiliate_campaign_type": "Chiến dịch mục tiêu",
        "affiliate_mcn": True,
    }
    assert "Agency X" not in repr(cols)
    none = ShopeeAffiliateOrderLineRow(
        order_ref="b" * 32, item_id="1", ordered_at="2026-10-12T10:00:00"
    )
    assert _kol_columns(none) == {}


def test_the_full_header_set_parses_and_carries_the_kol_fields(tmp_path):
    parsed, lines = _month_fixture(tmp_path)
    assert len(lines) == 4
    first = lines[0]
    assert (first.affiliate_account, first.channel) == ("kol_alpha", "Shopee Video")
    assert first.campaign_type == "Chiến dịch mở rộng" and first.cost == Decimal(10000)
    assert lines[3].valid is False


def test_the_commission_rule_reconciles_with_the_bill_and_xtra_does_not(tmp_path):
    parsed, lines = _month_fixture(tmp_path)
    (bill,) = [p for p in parsed.posts if p.dataset == "affiliate_bill_period"]
    extra = bill.body["rows"][0]
    result = rule.reconcile_month(
        "2026-10",
        lines,
        bill_commission=Decimal(str(extra["commission"])),
        bill_cost=Decimal(str(extra["cost"])),
    )
    assert result.lines == 3  # the invalid line is not counted
    assert result.sum_cost == Decimal(20000)
    assert result.sum_xtra == Decimal(3800)
    assert result.matches == {
        "cost~bill.commission": True,
        "cost~bill.cost": False,
        "xtra~bill.commission": False,
    }
    assert result.rule_field == "cost" and rule.RULE_COLUMN == "Chi phí(₫)"
    assert result.confirmed is False  # waits for one real month


def test_a_month_that_does_not_reconcile_names_no_rule(tmp_path):
    _, lines = _month_fixture(tmp_path)
    result = rule.reconcile_month(
        "2026-10", lines, bill_commission=Decimal(50000), bill_cost=Decimal(60000)
    )
    assert result.rule_field is None and not any(result.matches.values())


def test_seller_commission_is_the_cost_column_only():
    row = ShopeeAffiliateOrderLineRow(
        order_ref="c" * 32,
        item_id="1",
        ordered_at="2026-10-12T10:00:00",
        xtra_product_commission=Decimal(900),
    )
    assert rule.seller_commission(row) is None  # Xtra is never promoted to the commission
    assert rule.xtra_total(row) == Decimal(900)
