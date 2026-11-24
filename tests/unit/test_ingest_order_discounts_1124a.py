"""batch-1124-a Track S (S1): order lines carry the discounts the order used.

- The Connector's contract posts (``apps/connector/test/fixtures/contract/order_lines.body.json``
  and ``order_income.body.json``): a combo + Mua Kèm order and its order page income, whose
  buyer-payment vouchers (P-S3 capture, 24/11) are split onto the order's lines.
- Rule B (owner 2026-11-24): the income split overwrites only a 0 a Connector line post wrote;
  never a file import's value; a later Connector line post's 0 keeps the split amount.
- The buyer-side shop voucher is never the seller's cost (``seller_voucher_borne``).

Synthetic orders only: combo, voucher + Chương Trình Của Shop, Shopee voucher, affiliate order with
voucher.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services import ingest as svc
from juli_backend.services.ingest.income import _shares
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.unit.test_shopee_file_datasets import _rows, _shop

CONTRACT = Path(__file__).resolve().parents[2] / "apps/connector/test/fixtures/contract"
REF = "0123456789abcdef0123456789abcdef"
NOW = datetime(2026, 11, 5, 3, 0)


async def _ingest(session, shop, dataset: str, body: dict[str, Any]):
    return await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset=dataset,
        body=svc.IngestBody.model_validate(body),
        token_id=None,
        now=NOW,
    )


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _contract(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((CONTRACT / name).read_text("utf-8"))
    return body


def _lines_body(rows: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    body = copy.deepcopy(_contract("order_lines.body.json"))
    body["rows"] = rows
    body.update(over)
    return body


def _line(n: int, deal: int, **over: Any) -> dict[str, Any]:
    return {
        "order_ref": REF,
        "line_no": n,
        "ordered_at": "2026-11-02T09:00:00",
        "status": "delivered",
        "qty": 1,
        "original_price": deal,
        "deal_price": deal,
        "variation_sku": f"SKU-{n}",
        **over,
    }


def _income(buyer_shop: int | None = None, buyer_platform: int | None = None, **over: Any):
    body = copy.deepcopy(_contract("order_income.body.json"))
    row = {"order_ref": REF, "payout": 100_000, "product_price": 130_000, **over}
    if buyer_shop is not None:
        row["order_shop_voucher"] = buyer_shop
    if buyer_platform is not None:
        row["order_platform_voucher"] = buyer_platform
    body["rows"] = [row]
    return body


async def _lines(session, shop) -> list[ShopeeOrderLine]:
    return sorted(await _rows(session, ShopeeOrderLine, shop), key=lambda r: r.line_no)


async def test_the_connector_contract_posts_land_combo_add_on_and_split_vouchers(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _contract("order_lines.body.json"))
    await _ingest(session, shop, "order_income", _contract("order_income.body.json"))
    lines = await _lines(session, shop)
    assert [(ln.promo_kind, ln.bundle_discount) for ln in lines] == [
        # batch-1124-b CONN (owner Q4): (list 100.000 - combo share 95.000) x 1 per line
        ("bundle", Decimal(5_000)),
        ("bundle", Decimal(5_000)),
        ("add_on", Decimal(0)),
    ]
    # buyer vouchers 10.000 (shop) and 20.000 (Shopee) split by line value 95k / 95k / 30k
    assert [ln.shop_voucher_share for ln in lines] == [
        Decimal("4318.18"),
        Decimal("4318.18"),
        Decimal("1363.64"),
    ]
    assert sum(ln.platform_voucher_share for ln in lines) == Decimal(20_000)
    (settlement,) = await _rows(session, ShopeeOrderIncome, shop)
    # the buyer-side shop voucher is not the seller's cost; Voucher Xtra is a fee
    assert settlement.seller_voucher_borne is None
    assert settlement.fee_voucher_xtra == Decimal(5_500)


async def test_shopee_voucher_on_a_programme_price_order_fills_only_the_platform_share(session):
    shop = await _shop(session)
    # Chương Trình Của Shop: the programme price is already the line's deal price
    lines = [_line(0, 80_000, original_price=100_000, seller_subsidy=20_000, promo_kind="discount")]
    await _ingest(session, shop, "order_lines", _lines_body(lines))
    await _ingest(session, shop, "order_income", _income(buyer_platform=15_000))
    (line,) = await _lines(session, shop)
    assert (line.platform_voucher_share, line.shop_voucher_share) == (Decimal(15_000), Decimal(0))
    assert (line.seller_subsidy, line.promo_kind) == (Decimal(20_000), "discount")


async def test_shop_voucher_plus_programme_on_an_affiliate_order(session):
    shop = await _shop(session)
    lines = [_line(0, 60_000, original_price=75_000, seller_subsidy=15_000, promo_kind="discount")]
    await _ingest(session, shop, "order_lines", _lines_body(lines))
    affiliate = {
        "order_ref": REF,
        "line_no": 0,
        "item_id": "9001",
        "price": 60_000,
        "qty": 1,
        "cost": 6_000,
        "ordered_at": "2026-11-02T09:00:00",
    }
    await _ingest(session, shop, "affiliate_order_lines", _lines_body([affiliate]))
    await _ingest(session, shop, "order_income", _income(buyer_shop=5_000, buyer_platform=3_000))
    (line,) = await _lines(session, shop)
    assert line.affiliate is True
    assert (line.shop_voucher_share, line.platform_voucher_share) == (
        Decimal(5_000),
        Decimal(3_000),
    )
    assert (line.seller_subsidy, line.promo_kind) == (Decimal(15_000), "discount")


async def test_a_two_line_order_splits_each_voucher_by_line_value(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _lines_body([_line(0, 60_000), _line(1, 40_000)]))
    await _ingest(session, shop, "order_income", _income(buyer_shop=5_000, buyer_platform=3_000))
    first, second = await _lines(session, shop)
    assert (first.shop_voucher_share, second.shop_voucher_share) == (Decimal(3_000), Decimal(2_000))
    assert (first.platform_voucher_share, second.platform_voucher_share) == (
        Decimal(1_800),
        Decimal(1_200),
    )


async def test_rule_b_a_file_import_value_is_never_overwritten(session):
    shop = await _shop(session)
    file_lines = _lines_body(
        [_line(0, 50_000, shop_voucher_share=7_000)],
        source="file",
        source_version="seller-centre-xlsx-1",
    )
    await _ingest(session, shop, "order_lines", file_lines)
    await _ingest(session, shop, "order_income", _income(buyer_shop=9_000, buyer_platform=4_000))
    (line,) = await _lines(session, shop)
    # the file line is not a Connector 0: neither voucher moves
    assert (line.shop_voucher_share, line.platform_voucher_share) == (Decimal(7_000), Decimal(0))


async def test_rule_b_a_non_zero_connector_value_is_never_overwritten(session):
    shop = await _shop(session)
    await _ingest(
        session, shop, "order_lines", _lines_body([_line(0, 50_000, shop_voucher_share=2_000)])
    )
    await _ingest(session, shop, "order_income", _income(buyer_shop=9_000))
    (line,) = await _lines(session, shop)
    assert line.shop_voucher_share == Decimal(2_000)


async def test_rule_b_a_later_connector_line_post_keeps_the_split_voucher(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _lines_body([_line(0, 50_000)]))
    await _ingest(session, shop, "order_income", _income(buyer_shop=9_000, buyer_platform=4_000))
    reread = _lines_body([_line(0, 50_000)], captured_at="2026-11-04T03:00:00.000Z")
    await _ingest(session, shop, "order_lines", reread)
    (line,) = await _lines(session, shop)
    assert (line.shop_voucher_share, line.platform_voucher_share) == (
        Decimal(9_000),
        Decimal(4_000),
    )


async def test_an_income_post_from_a_file_splits_nothing(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _lines_body([_line(0, 50_000)]))
    await _ingest(
        session,
        shop,
        "order_income",
        _income(buyer_shop=9_000, buyer_platform=4_000)
        | {"source": "file", "source_version": "seller-centre-xlsx-1"},
    )
    (line,) = await _lines(session, shop)
    assert (line.shop_voucher_share, line.platform_voucher_share) == (Decimal(0), Decimal(0))


def test_shares_add_up_to_the_amount_to_the_cent():
    parts = _shares(Decimal(10_000), [Decimal(100_000), Decimal(90_000), Decimal(30_000)])
    assert parts == [Decimal("4545.45"), Decimal("4090.91"), Decimal("1363.64")]
    assert sum(parts) == Decimal(10_000)
    assert _shares(Decimal(1), []) == []


async def test_owner_49_the_income_voucher_code_fills_null_codes_only(session):
    shop = await _shop(session)
    file_lines = _lines_body(
        [_line(0, 50_000), _line(1, 30_000)], source="file", source_version="seller-centre-xlsx-1"
    )
    await _ingest(session, shop, "order_lines", file_lines)
    file_income = _income(voucher_code="SHOPXMAS10") | {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
    }
    await _ingest(session, shop, "order_income", file_income)
    assert [ln.voucher_code for ln in await _lines(session, shop)] == ["SHOPXMAS10", "SHOPXMAS10"]
    # a later income with another code never replaces a stored one
    await _ingest(session, shop, "order_income", _income(voucher_code="OTHER20"))
    assert {ln.voucher_code for ln in await _lines(session, shop)} == {"SHOPXMAS10"}


@pytest.mark.parametrize("code", ["shopxmas10", "A-B", "X" * 65])
def test_owner_49_a_non_code_voucher_value_is_refused_at_the_gateway(code):
    from pydantic import ValidationError

    from juli_backend.services.ingest.schemas import ShopeeOrderIncomeRow

    with pytest.raises(ValidationError) as refused:
        ShopeeOrderIncomeRow.model_validate({"order_ref": REF, "voucher_code": code})
    assert "voucher_code" in str(refused.value)


async def test_a_combo_split_after_the_voucher_split_re_splits_the_order_totals(session):
    """batch-1124-b CONN (verifier): the income split ran on the combo parent (line 0) alone; the
    order page then splits it into lines 0 and 1. Each voucher total is split again over the
    order's current lines by line value, the totals unchanged."""
    shop = await _shop(session)
    parent = _line(0, 190_000, variation_sku=None, promo_kind="bundle")
    await _ingest(session, shop, "order_lines", _lines_body([parent]))
    await _ingest(session, shop, "order_income", _income(buyer_shop=10_000, buyer_platform=3_001))
    (line,) = await _lines(session, shop)
    assert (line.shop_voucher_share, line.platform_voucher_share) == (
        Decimal(10_000),
        Decimal(3_001),
    )
    split = [
        _line(0, 95_000, promo_kind="bundle", bundle_discount=5_000),
        _line(1, 95_000, promo_kind="bundle", bundle_discount=5_000),
    ]
    await _ingest(
        session, shop, "order_lines", _lines_body(split, captured_at="2026-11-04T03:00:00Z")
    )
    lines = await _lines(session, shop)
    assert [ln.shop_voucher_share for ln in lines] == [Decimal(5_000), Decimal(5_000)]
    assert [ln.platform_voucher_share for ln in lines] == [Decimal("1500.50"), Decimal("1500.50")]


async def test_a_file_line_in_the_order_blocks_the_re_split(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _lines_body([_line(0, 100_000)]))
    await _ingest(session, shop, "order_income", _income(buyer_shop=10_000))
    await _ingest(
        session,
        shop,
        "order_lines",
        _lines_body([_line(1, 100_000)], source="file", source_version="t"),
    )
    lines = await _lines(session, shop)
    assert [ln.shop_voucher_share for ln in lines] == [Decimal(10_000), Decimal(0)]
