"""P91 D-12: the income export parser (``scripts/shopee_exports/income.py``).

Synthetic workbooks in the real layout (``tests/unit/income_workbooks.py``): the real header
rows, every value invented, the buyer's columns carrying CANARIES. Checks:

- a header allowlist: no buyer / payment / tax-code / product-name / voucher / courier value is
  decoded or reaches any post, summary, note or error; the Summary sheet's account lines are
  never decoded; an unknown header stops the load;
- the order id becomes the SAME keyed hash as the order export's (same key path);
- signs: a cost is posted positive, the Order row is the authority (return shipping is negative
  on an Order row and positive on its Sku rows), net shipping and the fee parts;
- ``Phí Dịch Vụ`` includes ``Phí hạ tầng`` (either spelling, summed) and ``Voucher Xtra``;
- the per-product split (Sku rows) adds up to the order's product price;
- the posts pass the gateway's own validation; the loader reports matched vs unmatched orders and
  the monthly reconciliation against the Summary sheet.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from scripts import load_shopee_exports
from scripts.shopee_exports import income, parse
from tests.unit.income_workbooks import (
    CANARIES,
    HEADER,
    order_row,
    sku_row,
    write_income,
)

KEY = b"synthetic-order-ref-key"
A, B, C, D, E = "TESTORD-A01", "TESTORD-B02", "TESTORD-C03", "TESTORD-D04", "TESTORD-E05"


def _scenario(tmp_path, **kwargs):
    orders = [
        # A: a normal order, two products, Xtra + infrastructure fee
        order_row(
            A,
            **{
                "Giá sản phẩm": 200000,
                "Phí vận chuyển Người mua trả": 15000,
                "Phí vận chuyển thực tế": -30000,
                "Phí vận chuyển được trợ giá từ Shopee": 12000,
                "Phí cố định": -27400,
                "Phí Dịch Vụ": -14000,
                "Phí xử lý giao dịch": -12000,
                "Phí hoa hồng Tiếp thị liên kết": -5000,
            },
        ),
        sku_row(A, "1001", "Combo 3 hộp", 120000, **{"Phí cố định": -16440}),
        sku_row(A, "1002", "-", 80000, **{"Phí cố định": -10960}),
        # B: a refund with return shipping (Order negative, Sku positive) and a PiShip refund
        order_row(
            B,
            **{
                "Giá sản phẩm": 90000,
                "Số tiền hoàn lại": -90000,
                "Phí vận chuyển thực tế": -20000,
                "Phí vận chuyển được trợ giá từ Shopee": 8000,
                "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)": -18000,
                "Phí vận chuyển được hoàn bởi PiShip": 18000,
                "Phí dịch vụ PiShip": -1500,
                "Phí cố định": -12330,
                "Phí Dịch Vụ": -3000,
            },
        ),
        sku_row(
            B,
            "1003",
            "-",
            90000,
            **{"Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)": 18000},
        ),
        # C: a lost parcel, compensated; a failed delivery's return shipping
        order_row(
            C,
            **{
                "Giá sản phẩm": 50000,
                "Đền bù đơn mất hàng": 50000,
                "Phí vận chuyển thực tế": -15000,
                "Phí vận chuyển trả hàng (đơn giao không thành công)": -9000,
                "Phí Dịch Vụ": -3000,
            },
        ),
        sku_row(C, "1004", "-", 50000),
        # D: a household seller: VAT and PIT withheld, and NTTD + trade-in
        order_row(
            D,
            **{
                "Giá sản phẩm": 100000,
                "Thuế GTGT": -1000,
                "Thuế TNCN": -500,
                "Phí dịch vụ hiển thị NTTD (từ doanh thu đơn hàng)": -300,
                "Trade-in Bonus by Seller": -700,
                "Phí Dịch Vụ": -3000,
            },
        ),
        sku_row(D, "1005", "-", 100000),
        # E: vouchers and coins the seller bore
        order_row(
            E,
            **{
                "Giá sản phẩm": 80000,
                "Mã ưu đãi do Người Bán chịu": -4000,
                "Mã ưu đãi Đồng Tài Trợ do Người Bán chịu": -1000,
                "Mã hoàn xu do Người Bán chịu": -2000,
                "Mã hoàn xu Đồng Tài Trợ do Người Bán chịu": -500,
                "Phí Dịch Vụ": -3000,
            },
        ),
        sku_row(E, "1006", "-", 80000),
    ]
    fees = [(A, -3000, -11000), (C, -3000, 0), (D, -3000, 0), (E, -3000, 0)]  # B has none
    return write_income(tmp_path, orders, fees=fees, **kwargs)


def _read(tmp_path, **kwargs):
    path = _scenario(tmp_path, **kwargs)
    return path, income.read_income(path, KEY)


def _row(file: income.IncomeFile, order_id: str) -> dict:
    return file.orders[parse.order_ref(order_id, KEY)]


# ------------------------------------------------------------------------------ privacy


def test_no_canary_in_any_post_summary_note_error_or_repr(tmp_path):
    path = _scenario(tmp_path)
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    read = income.read_income(path, KEY)
    everything = (
        json.dumps([p.body for p in parsed.posts], ensure_ascii=False)
        + load_shopee_exports.summary(parsed)
        + load_shopee_exports.income_report(parsed)
        + json.dumps(dict(parsed.notes), ensure_ascii=False)
        + repr(read.orders)
        + repr(read.products)
        + repr(read.recon)
    )
    for canary in (*CANARIES, A, B, C, D, E):
        assert canary not in everything
    assert [p.dataset for p in parsed.posts] == ["order_income"]


def test_buyer_columns_are_never_decoded(tmp_path):
    _, read = _read(tmp_path)
    assert read.value_columns_read.isdisjoint(income.BUYER_HEADERS)
    assert read.value_columns_read <= set(income.READ)
    assert read.ignored_headers >= income.BUYER_HEADERS - {"Mã yêu cầu hoàn tiền"} | {"Người Mua"}
    # every header of the real file is known: nothing is "unknown"
    assert set(HEADER) <= set(income.READ) | income.IGNORED


def test_an_unknown_header_stops_before_any_value_is_read(tmp_path):
    with pytest.raises(parse.UnknownColumn, match="Email người mua") as stopped:
        _scenario(tmp_path, header=[*HEADER, "Email người mua"])
        parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert not any(c in str(stopped.value) for c in CANARIES)


def test_a_missing_required_header_stops_the_load(tmp_path):
    header = [h for h in HEADER if h != "Tổng tiền đã thanh toán"]
    _scenario(tmp_path, header=header)
    with pytest.raises(parse.UnknownColumn, match="Tổng tiền đã thanh toán"):
        parse.parse_folder(tmp_path, order_ref_key=KEY)


def test_a_cell_that_is_not_a_number_names_the_column_never_the_value(tmp_path):
    orders = [order_row(A, **{"Phí cố định": CANARIES[0], "Giá sản phẩm": 1})]
    write_income(tmp_path, orders, fees=[(A, -3000, 0)])
    with pytest.raises(income.IncomeLayoutError) as stopped:
        parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert "Phí cố định" in str(stopped.value) and CANARIES[0] not in str(stopped.value)


def test_the_order_id_is_the_order_exports_keyed_hash(tmp_path):
    _, read = _read(tmp_path)
    assert set(read.orders) == {parse.order_ref(i, KEY) for i in (A, B, C, D, E)}
    # trimmed and upper-cased, like the order export and the browser module
    assert parse.order_ref(f"  {A.lower()} ", KEY) == parse.order_ref(A, KEY)


def test_the_loader_key_path_is_shared_with_the_order_export(tmp_path, monkeypatch):
    _scenario(tmp_path)
    monkeypatch.setenv("JULI_ORDER_REF_KEY", "env-key")
    first = parse.parse_folder(tmp_path)
    second = parse.parse_folder(tmp_path, order_ref_key=b"env-key")
    assert [r["order_ref"] for r in first.posts[0].body["rows"]] == [
        r["order_ref"] for r in second.posts[0].body["rows"]
    ]


# ----------------------------------------------------------------------- amounts and signs


def test_a_normal_order_posts_costs_as_positive_amounts(tmp_path):
    _, read = _read(tmp_path)
    a = _row(read, A)
    assert a["product_price"] == 200000
    assert (a["fee_fixed"], a["fee_service"], a["fee_payment"]) == (27400, 14000, 12000)
    assert a["affiliate_commission"] == 5000
    assert a["ordered_on"] == "2026-09-28" and a["paid_on"] == "2026-10-03"
    assert a["transaction_fee_rate"] == pytest.approx(0.06)
    # 200000 + 15000 - 30000 + 12000 - 27400 - 14000 - 12000 - 5000
    assert a["payout"] == 138600
    assert income.PAYOUT_PARTS  # the identity below is checked on every order
    assert read.unreconciled == 0


def test_net_shipping_is_actual_minus_shopee_buyer_and_pishiip_shares(tmp_path):
    _, read = _read(tmp_path)
    a, b = _row(read, A), _row(read, B)
    assert (a["ship_actual_cost"], a["ship_shopee_subsidy"], a["ship_buyer_paid"]) == (
        30000,
        12000,
        15000,
    )
    assert a["net_shipping_cost"] == 3000  # 30000 - 12000 - 15000
    assert b["net_shipping_cost"] == 20000 - 8000 - 0 - 18000 == -6000  # PiShip paid more back


def test_seller_support_is_a_reference_value_outside_net_shipping(tmp_path):
    orders = [
        order_row(
            A,
            **{
                "Giá sản phẩm": 100,
                "Phí vận chuyển thực tế": -50,
                "Phí vận chuyển - Người bán hỗ trợ": -20,
            },
        )
    ]
    write_income(tmp_path, orders, fees=[(A, 0, 0)])
    read = income.read_income(next(tmp_path.glob("Income*")), KEY)
    row = _row(read, A)
    assert row["net_shipping_cost"] == 50 and row["ship_seller_support"] == 20
    assert read.unreconciled == 0  # the payout does not contain it


def test_return_shipping_comes_from_the_order_row_whose_sign_differs_from_the_sku_rows(tmp_path):
    _, read = _read(tmp_path)
    b, c = _row(read, B), _row(read, C)
    assert b["return_ship_refund"] == 18000  # Order row -18000 -> a cost of 18000
    assert b["return_ship_failed"] == 0
    assert c["return_ship_failed"] == 9000 and c["return_ship_refund"] == 0
    assert b["refund_amount"] == 90000
    assert b["fee_piship"] == 1500 and b["ship_piship_refund"] == 18000


def test_lost_parcel_compensation_is_income_and_withheld_taxes_are_costs(tmp_path):
    _, read = _read(tmp_path)
    c, d = _row(read, C), _row(read, D)
    assert c["lost_compensation"] == 50000
    assert (d["vat_withheld"], d["pit_withheld"]) == (1000, 500)
    assert (d["fee_nttd"], d["trade_in_bonus_seller"]) == (300, 700)


def test_vouchers_and_coins_the_seller_bore_include_the_cofunded_ones(tmp_path):
    _, read = _read(tmp_path)
    e = _row(read, E)
    assert (e["seller_voucher_borne"], e["seller_coin_borne"]) == (5000, 2500)


def test_phi_dich_vu_includes_the_infrastructure_and_xtra_parts(tmp_path):
    _, read = _read(tmp_path)
    a, b = _row(read, A), _row(read, B)
    assert (a["fee_infra"], a["fee_voucher_xtra"]) == (3000, 11000)
    assert a["fee_infra"] + a["fee_voucher_xtra"] == a["fee_service"]
    assert "fee_infra" not in b and read.without_fee_details == 1  # no Service Fee Details row


def test_the_infrastructure_fee_under_either_spelling_is_summed(tmp_path):
    orders = [order_row(A, **{"Giá sản phẩm": 100000, "Phí Dịch Vụ": -9000})]
    write_income(tmp_path, orders, fees=[(A, -3000, -6000)], spellings=2)
    read = income.read_income(next(tmp_path.glob("Income*")), KEY)
    row = _row(read, A)
    assert (row["fee_infra"], row["fee_voucher_xtra"]) == (3000, 6000)


def test_a_payout_that_is_not_the_sum_of_its_parts_is_counted(tmp_path):
    orders = [order_row(A, **{"Giá sản phẩm": 100000, "Tổng tiền đã thanh toán": 99999})]
    write_income(tmp_path, orders, fees=[(A, 0, 0)])
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert parsed.income_files[0].unreconciled == 1
    assert any("not the sum of their parts" in note for note in parsed.notes)


def test_sku_rows_split_the_order_per_product_and_add_up(tmp_path):
    _, read = _read(tmp_path)
    ref = parse.order_ref(A, KEY)
    products = read.products[ref]
    assert products == [("1001", "Combo 3 hộp", Decimal(120000)), ("1002", "-", Decimal(80000))]
    assert sum(p[2] for p in products) == read.orders[ref]["product_price"]
    assert read.order_rows == 5 and read.sku_rows == 6


def test_an_order_stated_twice_is_summed(tmp_path):
    orders = [
        order_row(A, **{"Giá sản phẩm": 100, "Phí cố định": -10}),
        order_row(A, **{"Giá sản phẩm": 50, "Phí cố định": -5}),
    ]
    write_income(tmp_path, orders, fees=[(A, 0, 0)])
    read = income.read_income(next(tmp_path.glob("Income*")), KEY)
    row = _row(read, A)
    assert (row["product_price"], row["fee_fixed"], row["payout"]) == (150, 15, 135)


# -------------------------------------------------------------------- reconciliation, posts


def test_the_month_reconciles_with_the_summary_sheet(tmp_path):
    _, read = _read(tmp_path)
    assert read.recon and all(r.diff == 0 for r in read.recon)
    labels = {r.label for r in read.recon}
    assert {"Phí cố định", "Phí Dịch Vụ", "3. Tổng số tiền"} <= labels


def test_a_summary_that_disagrees_is_reported_by_label(tmp_path):
    _, read = _read(tmp_path, summary_override={"Phí cố định": -1})
    off = [r for r in read.recon if r.diff != 0]
    assert [r.label for r in off] == ["Phí cố định"]
    report = load_shopee_exports.income_report(
        parse.parse_folder(tmp_path, order_ref_key=KEY), None
    )
    assert "DIFF Phí cố định" in report


def test_the_posts_pass_the_gateways_own_validation(tmp_path):
    _scenario(tmp_path)
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    now = datetime.now(UTC).replace(tzinfo=None)
    assert load_shopee_exports.validate(parsed, now) == []
    body = parsed.posts[0].body
    assert body["period"] == {"start": "2026-10-01", "end": "2026-10-31", "granularity": "period"}
    assert len(body["rows"]) == 5
    assert {"order_ref", "payout", "fee_fixed"} <= set(body["rows"][0])


def test_the_loader_reports_matched_and_unmatched_orders(tmp_path):
    _scenario(tmp_path)
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    stored = {parse.order_ref(A, KEY), parse.order_ref(B, KEY), parse.order_ref(C, KEY)}
    text = load_shopee_exports.income_report(parsed, stored)
    assert "5 orders, 3 matched (60.0%), 2 not in the order lines" in text
    assert "and the database" in text
    assert "payout = sum of parts on 5/5 orders" in text
    assert "lines add up" in text
    # without a database only this run's order exports count: none here
    assert "0 matched" in load_shopee_exports.income_report(parsed, None)


def test_a_month_is_split_into_posts_of_at_most_a_thousand_orders(tmp_path):
    orders = [order_row(f"BULK-{i:05d}", **{"Giá sản phẩm": 1000}) for i in range(1001)]
    write_income(tmp_path, orders, fees=[])
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert [len(p.body["rows"]) for p in parsed.posts] == [1000, 1]
