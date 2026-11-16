"""P101 W2: TikTok order / statement payloads -> canonical rows. Synthetic payloads in the
TikTok shapes the repo already reads (order search 202309, price_detail 202407, finance
statement_transactions 202501); no real shop, order or amount."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from juli_backend.services.ingest.canonical import profit_order_lines
from juli_backend.services.ingest.tiktok_mapper import (
    WARN_PRO_RATA,
    WARN_VOUCHER,
    map_order,
    map_statement,
    map_status,
)
from juli_backend.services.shopee_profit.order_profit import SkuCost, line_profit
from tests.support.canonical_writer import InMemoryCanonicalWriter

SHOP = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
RAW = uuid.UUID("00000000-0000-4000-8000-0000000000bb")
RAW_STATEMENT = uuid.UUID("00000000-0000-4000-8000-0000000000cc")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CREATED = 1_790_000_000  # 2026-09-21 14:13:20 UTC
D = Decimal


def _order(**over: Any) -> dict[str, Any]:
    order: dict[str, Any] = {
        "id": "900000000000000001",
        "status": "COMPLETED",
        "create_time": CREATED,
        "paid_time": CREATED + 60,
        "delivery_time": CREATED + 86_400,
        "payment": {
            "currency": "VND",
            "sub_total": "250000",
            "shipping_fee": "20000",
            "seller_discount": "30000",
            "platform_discount": "20000",
        },
        "recipient_address": {"name": "PII_MARKER_name", "phone_number": "PII_MARKER_phone"},
        "buyer_email": "PII_MARKER_mail",
        "line_items": [
            {
                "id": "800000000000000020",
                "product_id": "700000000000000002",
                "sku_id": "600000000000000002",
                "sku_name": "Xanh / L",
                "seller_sku": "SYN-B",
                "original_price": "100000",
                "sale_price": "80000",
                "seller_discount": "10000",
                "platform_discount": "10000",
                "currency": "VND",
                "display_status": "COMPLETED",
            },
            {
                "id": "800000000000000010",
                "product_id": "700000000000000001",
                "sku_id": "600000000000000001",
                "sku_name": "Do / M",
                "seller_sku": "SYN-A",
                "original_price": "200000",
                "sale_price": "170000",
                "seller_discount": "20000",
                "platform_discount": "10000",
                "currency": "VND",
                "display_status": "COMPLETED",
            },
        ],
    }
    order.update(over)
    return order


def _price_detail() -> dict[str, Any]:
    return {
        "currency": "VND",
        "line_items": [
            {
                "id": "800000000000000010",
                "voucher_deduction_seller": "5000",
                "voucher_deduction_platform": "4000",
            },
            {
                "id": "800000000000000020",
                "voucher_deduction_seller": "0",
                "voucher_deduction_platform": "0",
            },
        ],
    }


def _statement(**fee_over: str) -> dict[str, Any]:
    fees = {
        "platform_commission_amount": "-24000",
        "transaction_fee_amount": "-6000",
        "voucher_xtra_service_fee_amount": "-3000",
        "vn_fix_infrastructure_fee": "-1000",
        "sfp_service_fee_amount": "-2500",
        "affiliate_ads_commission_amount": "-1500",
        "affiliate_commission_amount": "-8000",
        "affiliate_commission_deposit": "-8000",
        **fee_over,
    }
    return {
        "order_id": "900000000000000001",
        "order_create_time": CREATED,
        "currency": "VND",
        "revenue_amount": "270000",
        "fee_and_tax_amount": "-47500",
        "shipping_cost_amount": "-12000",
        "settlement_amount": "210500",
        "sku_transactions": [
            {
                "sku_id": "600000000000000001",
                "statement_id": "500000000000000001",
                "quantity": "1",
                "settlement_amount": "140000",
                "revenue_amount": "180000",
                "revenue_breakdown": {
                    "subtotal_before_discount_amount": "200000",
                    "seller_discount_amount": "-20000",
                    "refund_subtotal_before_discount_amount": "0",
                },
                "fee_tax_breakdown": {
                    "fee": fees,
                    "tax": {"vat_amount": "-1800", "pit_amount": "-900"},
                },
                "shipping_cost_amount": "-12000",
                "shipping_cost_breakdown": {
                    "actual_shipping_fee_amount": "-32000",
                    "customer_paid_shipping_fee_amount": "15000",
                    "shipping_fee_discount_amount": "5000",
                    "supplementary_component": {"platform_shipping_fee_discount_amount": "5000"},
                },
            },
            {
                "sku_id": "600000000000000002",
                "statement_id": "500000000000000002",
                "quantity": "1",
                "settlement_amount": "70500",
                "revenue_amount": "90000",
                "revenue_breakdown": {
                    "subtotal_before_discount_amount": "100000",
                    "seller_discount_amount": "-10000",
                },
                "fee_tax_breakdown": {"fee": {"platform_commission_amount": "-9000"}},
                "shipping_cost_amount": "0",
            },
        ],
    }


# -- lines ----------------------------------------------------------------------------------


def test_multi_line_order_maps_discounts_vouchers_and_identity() -> None:
    mapped = map_order(_order(), shop_id=SHOP, raw_payload_id=RAW, price_detail=_price_detail())

    assert mapped.warnings == ()
    first, second = mapped.lines
    # Sorted by line item id: ...010 before ...020, whatever order TikTok listed them in.
    assert (first.line_no, first.variation_sku, second.line_no) == (0, "SYN-A", 1)
    assert (first.platform, first.order_ref, first.raw_payload_id) == (
        "tiktok",
        "900000000000000001",
        RAW,
    )
    assert (first.item_id, first.variation_id, first.variation_name) == (
        "700000000000000001",
        "600000000000000001",
        "Do / M",
    )
    assert first.status == "delivered" and first.qty == 1
    assert first.original_price == D("200000")
    # seller discount 20000 = 5000 voucher + 15000 promotion; deal price after the promotion.
    assert (first.shop_voucher_share, first.seller_subsidy, first.deal_price) == (
        D("5000"),
        D("15000"),
        D("185000"),
    )
    assert (first.platform_voucher_share, first.platform_subsidy) == (D("4000"), D("6000"))
    assert first.buyer_paid == D("180000")  # original - all seller-funded
    assert first.promo_kind == "discount"
    assert (second.seller_subsidy, second.platform_subsidy, second.shop_voucher_share) == (
        D("10000"),
        D("10000"),
        D("0"),
    )
    # Order-level buyer shipping split by line value (200000 : 100000).
    assert (first.buyer_shipping_fee, second.buyer_shipping_fee) == (D("13333.33"), D("6666.67"))
    assert (first.source, first.source_version) == ("api", "tiktok:order/202309")


def test_timestamps_are_aware_utc() -> None:
    line = map_order(_order(), shop_id=SHOP).lines[0]

    assert line.ordered_at == datetime(2026, 9, 21, 14, 13, 20, tzinfo=UTC)
    assert line.paid_at == datetime(2026, 9, 21, 14, 14, 20, tzinfo=UTC)
    assert line.completed_at == datetime(2026, 9, 22, 14, 13, 20, tzinfo=UTC)
    assert line.ordered_at.utcoffset() is not None


def test_line_no_is_stable_across_refetch_order() -> None:
    order = _order()
    shuffled = copy.deepcopy(order)
    shuffled["line_items"].reverse()

    a = map_order(order, shop_id=SHOP).lines
    b = map_order(shuffled, shop_id=SHOP).lines

    assert [(ln.line_no, ln.variation_id) for ln in a] == [
        (ln.line_no, ln.variation_id) for ln in b
    ]


def test_no_buyer_field_reaches_a_line() -> None:
    mapped = map_order(_order(), shop_id=SHOP, statement=_statement())

    assert "PII_MARKER" not in repr(mapped)


def test_order_without_per_line_split_is_allocated_pro_rata_by_line_value() -> None:
    order = _order()
    for item in order["line_items"]:
        del item["seller_discount"], item["platform_discount"]

    mapped = map_order(order, shop_id=SHOP)

    assert WARN_PRO_RATA in mapped.warnings
    first, second = mapped.lines
    assert (first.seller_subsidy, second.seller_subsidy) == (D("20000.00"), D("10000.00"))
    assert (first.platform_subsidy, second.platform_subsidy) == (D("13333.33"), D("6666.67"))
    assert first.seller_subsidy + second.seller_subsidy == D("30000")


def test_voucher_type_codes_are_not_read_as_amounts() -> None:
    """The repo's doc-example price detail carries ``1020000``-style codes in the voucher fields."""
    detail = json.loads(
        (FIXTURES / "tiktok_order_costs" / "price_detail_response.json").read_text()
    )["response"]["data"]
    order = _order()
    order["line_items"][0]["id"] = detail["line_items"][0]["id"]

    mapped = map_order(order, shop_id=SHOP, price_detail=detail)

    assert WARN_VOUCHER in mapped.warnings
    assert all(ln.shop_voucher_share == 0 and ln.platform_voucher_share == 0 for ln in mapped.lines)
    assert sorted(ln.seller_subsidy for ln in mapped.lines) == [D("10000"), D("20000")]


def test_cancelled_order_from_the_privacy_fixture() -> None:
    order = json.loads((FIXTURES / "tiktok_privacy" / "order_search_202309_order.json").read_text())

    mapped = map_order(order, shop_id=SHOP)

    assert [ln.status for ln in mapped.lines] == ["cancelled", "cancelled"]
    assert all(ln.completed_at is None for ln in mapped.lines)
    assert [ln.variation_sku for ln in mapped.lines] == ["AT-W-M", None]
    assert "PII_MARKER" not in repr(mapped)
    out = profit_order_lines(list(mapped.lines))
    assert line_profit(out[0], None).excluded_reason == "no_fee_no_profit"


def test_partially_cancelled_line_takes_its_display_status() -> None:
    order = _order(status="AWAITING_SHIPMENT")
    order["line_items"][0]["display_status"] = "CANCELLED"

    by_sku = {ln.variation_sku: ln.status for ln in map_order(order, shop_id=SHOP).lines}

    assert by_sku == {"SYN-B": "cancelled", "SYN-A": "in_transit"}


def test_status_vocabulary() -> None:
    assert map_status("COMPLETED") == ("delivered", None)
    assert map_status("DELIVERED") == ("delivered", None)
    assert map_status("UNPAID") == ("in_transit", None)
    assert map_status("ON_HOLD") == ("in_transit", None)
    assert map_status("CANCEL") == ("cancelled", None)


def test_unknown_status_is_kept_raw_and_flagged() -> None:
    mapped = map_order(_order(status="AWAITING-MOON landing!"), shop_id=SHOP)

    assert mapped.warnings == ("status_unrecognised:awaiting_moon_landing",)
    assert {ln.status for ln in mapped.lines} == {"awaiting_moon_landing"}
    assert all(ln.completed_at is None for ln in mapped.lines)


def test_non_vnd_order_is_skipped() -> None:
    order = _order()
    order["payment"]["currency"] = "USD"

    mapped = map_order(order, shop_id=SHOP, statement=_statement())

    assert mapped.lines == () and mapped.settlement is None
    assert mapped.warnings == ("currency_not_vnd:usd",)


def test_ref_of_replaces_the_order_id() -> None:
    mapped = map_order(
        _order(), shop_id=SHOP, statement=_statement(), ref_of=lambda i: f"h:{i[-4:]}"
    )

    assert {ln.order_ref for ln in mapped.lines} == {"h:0001"}
    assert mapped.settlement is not None and mapped.settlement.order_ref == "h:0001"


# -- settlement -----------------------------------------------------------------------------


def test_statement_maps_fees_shipping_and_tax_with_positive_costs() -> None:
    mapped = map_order(
        _order(),
        shop_id=SHOP,
        statement=_statement(),
        statement_raw_payload_id=RAW_STATEMENT,
        statement_times={"500000000000000001": CREATED + 5 * 86_400, "500000000000000002": 0},
    )

    s = mapped.settlement
    assert s is not None
    assert (s.platform, s.order_ref, s.source, s.source_rank) == (
        "tiktok",
        "900000000000000001",
        "api",
        4,
    )
    assert s.raw_payload_id == RAW_STATEMENT
    assert (s.ordered_on, s.paid_on) == (date(2026, 9, 21), date(2026, 9, 26))
    assert (s.payout, s.product_price, s.refund_amount) == (D("210500"), D("300000"), D("0"))
    assert (s.fee_fixed, s.fee_payment, s.fee_service) == (D("33000"), D("6000"), D("4000"))
    assert s.affiliate_commission == D("8000")
    assert s.fee_other == D("4000")
    assert mapped.fee_other_breakdown == {
        "affiliate_ads_commission_amount": D("1500"),
        "sfp_service_fee_amount": D("2500"),
    }
    assert (s.ship_actual_cost, s.ship_buyer_paid, s.ship_platform_subsidy) == (
        D("32000"),
        D("15000"),
        D("5000"),
    )
    assert s.net_shipping_cost == D("12000")
    assert (s.vat_withheld, s.pit_withheld) == (D("1800"), D("900"))


def test_shopee_only_settlement_fields_stay_none() -> None:
    s = map_order(_order(), shop_id=SHOP, statement=_statement()).settlement

    assert s is not None
    assert [
        s.fee_infra,
        s.fee_voucher_xtra,
        s.fee_piship,
        s.fee_nttd,
        s.ship_piship_refund,
        s.seller_coin_borne,
        s.trade_in_bonus_seller,
        s.lost_compensation,
        s.transaction_fee_rate,
        s.seller_voucher_borne,
        s.paid_on,
    ] == [None] * 11


def test_unsettled_statement_is_no_settlement_not_a_zero_row() -> None:
    zero = _statement()
    for key in (
        "revenue_amount",
        "fee_and_tax_amount",
        "shipping_cost_amount",
        "settlement_amount",
    ):
        zero[key] = "0"
    for tx in zero["sku_transactions"]:
        for key in ("settlement_amount", "revenue_amount", "shipping_cost_amount"):
            tx[key] = "0"
        tx["revenue_breakdown"] = {"subtotal_before_discount_amount": "0"}
        tx["fee_tax_breakdown"] = {"fee": {"platform_commission_amount": "0"}}
        tx.pop("shipping_cost_breakdown", None)

    zeroed = map_order(_order(), shop_id=SHOP, statement=zero)
    empty = map_statement({"currency": "VND", "sku_transactions": []}, shop_id=SHOP, order_ref="r")
    absent = map_order(_order(), shop_id=SHOP)

    assert zeroed.settlement is None and zeroed.fee_other_breakdown == {}
    assert len(zeroed.lines) == 2
    assert empty.settlement is None
    assert absent.settlement is None


def test_repo_statement_fixture_maps_commission_and_fee_other_zero() -> None:
    data = json.loads(
        (FIXTURES / "tiktok_order_costs" / "statement_transactions_response.json").read_text()
    )["response"]["data"]

    mapped = map_statement(data, shop_id=SHOP, order_ref="ref-fixture")

    s = mapped.settlement
    assert s is not None
    assert (s.fee_fixed, s.fee_payment, s.fee_service) == (D("35200"), D("8800"), D("8800"))
    assert s.affiliate_commission is None  # stated as "" -> not stated
    assert (s.fee_other, mapped.fee_other_breakdown) == (
        D("0"),
        {"flash_sales_service_fee_amount": D("0")},
    )
    assert (s.payout, s.net_shipping_cost, s.ship_actual_cost) == (
        D("380200"),
        D("7000"),
        D("37000"),
    )
    assert s.ship_platform_subsidy == D("15000")  # nested platform value, not counted twice


def test_non_vnd_statement_is_skipped() -> None:
    data = _statement()
    data["currency"] = "THB"

    mapped = map_statement(data, shop_id=SHOP, order_ref="r")

    assert mapped.settlement is None
    assert mapped.warnings == ("currency_not_vnd:thb",)


# -- end to end through the writer and the compute input -----------------------------------


async def test_mapped_order_writes_idempotently_and_computes_profit() -> None:
    writer = InMemoryCanonicalWriter()
    mapped = map_order(_order(), shop_id=SHOP, statement=_statement())
    assert mapped.settlement is not None

    for _ in range(2):
        assert await writer.upsert_order_lines(SHOP, "tiktok", mapped.lines) == 2
        assert await writer.upsert_settlements(SHOP, "tiktok", [mapped.settlement]) == 1

    assert len(writer.lines) == 2 and len(writer.settlements) == 1
    out = profit_order_lines(list(writer.lines.values()), mapped.settlement)
    first = line_profit(out[0], SkuCost(sku="SYN-A", cogs=D("50000"), packaging=D("2000")))
    assert first.fee_source == "income"
    # Line SYN-A (buyer paid 180000 of 270000) carries 2/3 of every settled amount:
    # fees 2/3 x (33000 + 6000 + 4000 + 4000) = 31333.34 (cent rounding) and commission 5333.33,
    # net shipping 8000; tax is never charged.
    assert first.fees_total == D("31333.34")
    assert first.commission == D("5333.33")
    assert first.contribution == D("180000") - D("31333.34") - D("50000") - D("2000") - D(
        "5333.33"
    ) - D("8000")
