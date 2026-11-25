"""C9: one combo counts once (E150) and the seller's voucher is what the settlement took (E151).

Synthetic orders only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import update

from juli_backend.models.ingest import IngestRawPayload
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.repositories import ShopeeOrderLinesRepo
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.shopee_analytics.engine import ShopLine, attach_income
from juli_backend.services.shopee_analytics.order_consistency import day_consistency
from juli_backend.services.shopee_profit.income import IncomeOrder, decide_seller_voucher
from juli_backend.services.shopee_profit.order_profit import line_profit
from tests.unit.test_ingest_order_discounts_1124a import (
    _income,
    _ingest,
    _line,
    _lines,
    _lines_body,
)
from tests.unit.test_shopee_file_datasets import _shop
from tests.unit.test_shopee_profit import COST, SCHEDULE, line

DAY = date(2026, 11, 2)
T = "2026-11-05T02:0{}:00Z"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _body(rows, hour: int, **over):
    return _lines_body(rows, captured_at=T.format(hour), **over)


def _parent(price: int, **over):
    """get_one_order's collapsed combo: one line, no SKU, the whole combo price."""
    row = _line(0, price, promo_kind="bundle", status="in_transit", paid_at="2026-11-02T09:00:00")
    del row["variation_sku"]
    return {**row, **over}


def _split(second_qty: int = 1, first_qty: int = 2, unit: int = 90_000):
    return [
        _line(
            n,
            unit,
            qty=qty,
            promo_kind="bundle",
            bundle_discount=10_000 * qty,
            status="in_transit",
            paid_at="2026-11-02T09:00:00",
            variation_sku=f"SKU-{n}",
        )
        for n, qty in ((0, first_qty), (1, second_qty))
    ]


async def _item(session, shop):
    await session.execute(
        update(ShopeeOrderLine).where(ShopeeOrderLine.shop_id == shop.id).values(item_id="7001")
    )


async def _corrupt(session, shop):
    """The stored state found 25/11: the split, then line 0 replaced by the collapsed parent."""
    await _ingest(session, shop, "order_lines", _body(_split(), 1))
    await _item(session, shop)
    body = _body([_parent(270_000, status="delivered")], 2)
    raw_before = {ln.raw_payload_id for ln in await _lines(session, shop)}
    await _ingest(session, shop, "order_lines", body)
    from sqlalchemy import select

    raws = (await session.execute(select(IngestRawPayload.id))).scalars().all()
    (new_raw,) = set(raws) - raw_before
    await session.execute(
        update(ShopeeOrderLine)
        .where(ShopeeOrderLine.shop_id == shop.id, ShopeeOrderLine.line_no == 0)
        .values(
            qty=1,
            deal_price=270_000,
            original_price=270_000,
            bundle_discount=0,
            raw_payload_id=new_raw,
        )
    )


# -- the writer ------------------------------------------------------------------------------------


async def test_a_collapsed_re_post_keeps_the_combo_lines_and_moves_every_lines_status(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _body([_parent(270_000)], 1))
    await _ingest(session, shop, "order_lines", _body(_split(), 2))
    await _item(session, shop)
    done = _parent(270_000, status="delivered", completed_at="2026-11-04T09:00:00")
    await _ingest(session, shop, "order_lines", _body([done], 3))
    lines = await _lines(session, shop)
    assert [(ln.qty, ln.deal_price, ln.bundle_discount) for ln in lines] == [
        (2, D(90_000), D(20_000)),
        (1, D(90_000), D(10_000)),
    ]
    assert {ln.status for ln in lines} == {"delivered"}
    assert all(ln.completed_at is not None for ln in lines)


async def test_a_parent_named_by_one_page_line_is_still_collapsed(session):
    """0.3.36 could post the parent under the only page line drawn so far: fewer combo lines."""
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _body(_split(), 1))
    await _item(session, shop)
    await _ingest(session, shop, "order_lines", _body([_parent(270_000, variation_sku="SKU-0")], 2))
    assert sum(ln.deal_price * ln.qty for ln in await _lines(session, shop)) == D(270_000)


async def test_a_late_older_read_does_not_move_the_order_back(session):
    shop = await _shop(session)
    split = [{**r, "status": "delivered"} for r in _split()]
    await _ingest(session, shop, "order_lines", _body(split, 3))
    await _item(session, shop)
    await _ingest(session, shop, "order_lines", _body([_parent(270_000)], 4))
    await _ingest(session, shop, "order_lines", _body([_parent(270_000, status="cancelled")], 1))
    assert {ln.status for ln in await _lines(session, shop)} == {"delivered"}


async def test_a_combo_whose_products_are_not_known_yet_is_still_stored(session):
    shop = await _shop(session)
    await _ingest(session, shop, "order_lines", _body([_parent(270_000)], 1))
    await _ingest(session, shop, "order_lines", _body([_parent(270_000, status="delivered")], 2))
    (stored,) = await _lines(session, shop)
    assert (stored.deal_price, stored.status) == (D(270_000), "delivered")


async def test_a_later_full_split_heals_the_stored_parent(session):
    shop = await _shop(session)
    await _corrupt(session, shop)
    await _ingest(
        session, shop, "order_lines", _body([{**r, "status": "delivered"} for r in _split()], 5)
    )
    assert [ln.qty for ln in await _lines(session, shop)] == [2, 1]


# -- the read guard --------------------------------------------------------------------------------


async def _counted(session, shop):
    return await ShopeeOrderLinesRepo(session).in_window(shop.id, DAY, DAY)


async def test_a_stored_parent_takes_back_its_own_line_from_the_split_post(session):
    shop = await _shop(session)
    await _corrupt(session, shop)
    counted = await _counted(session, shop)
    assert [(ln.qty, ln.deal_price, ln.bundle_discount) for ln in counted] == [
        (2, D(90_000), D(20_000)),
        (1, D(90_000), D(10_000)),
    ]
    # the stored rows are not touched
    await session.flush()
    stored = await _lines(session, shop)
    assert (stored[0].qty, stored[0].deal_price) == (1, D(270_000))
    assert len(stored) == 2


async def test_without_the_post_the_settlement_proves_the_total(session):
    shop = await _shop(session)
    await _corrupt(session, shop)
    await session.execute(update(ShopeeOrderLine).values(raw_payload_id=None))
    unproven = await _counted(session, shop)
    assert [ln.qty for ln in unproven] == [1, 1]  # not certain: as stored
    await _ingest(session, shop, "order_income", _income(product_price=270_000))
    counted = await _counted(session, shop)
    assert [(ln.qty, ln.deal_price) for ln in counted] == [(2, D(90_000)), (1, D(90_000))]


async def test_a_settlement_of_both_lines_leaves_them(session):
    shop = await _shop(session)
    await _corrupt(session, shop)
    await _ingest(session, shop, "order_income", _income(product_price=360_000))
    counted = await _counted(session, shop)
    assert sum(ln.deal_price * ln.qty for ln in counted) == D(360_000)


async def test_a_rest_that_is_no_whole_unit_is_left(session):
    shop = await _shop(session)
    await _corrupt(session, shop)
    await session.execute(update(ShopeeOrderLine).values(raw_payload_id=None))
    await session.execute(
        update(ShopeeOrderLine).where(ShopeeOrderLine.line_no == 0).values(deal_price=250_000)
    )
    await _ingest(session, shop, "order_income", _income(product_price=250_000))
    assert [ln.qty for ln in await _counted(session, shop)] == [1, 1]


async def test_a_normal_split_and_plain_lines_are_never_touched(session):
    shop = await _shop(session)
    rows = [*_split(), _line(2, 30_000)]
    await _ingest(session, shop, "order_lines", _body(rows, 1))
    counted = await _counted(session, shop)
    assert [(ln.qty, ln.deal_price) for ln in counted] == [
        (2, D(90_000)),
        (1, D(90_000)),
        (1, D(30_000)),
    ]


# -- the seller's voucher --------------------------------------------------------------------------

#: 200.000 goods, 40.000 of fees (Phí Dịch Vụ holds Phí Hạ Tầng + Voucher Xtra)
BASE = IncomeOrder(
    "v1",
    fee_fixed=D(20_000),
    fee_service=D(14_000),
    fee_payment=D(6_000),
    product_price=D(200_000),
    payout=D(160_000),
    seller_voucher_borne=D(10_000),
)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, (D(0), False)),  # closes with no voucher
        ({"payout": D(150_000)}, (D(10_000), False)),  # closes with the stated one
        ({"payout": D(155_000)}, (None, True)),  # neither
        ({"payout": None}, (None, True)),
        ({"product_price": None}, (None, True)),
        ({"refund_amount": D(200_000)}, (None, True)),
        # every deduction the settlement names is a term
        ({"payout": D(143_000), "net_shipping_cost": D(17_000)}, (D(0), False)),
        ({"payout": D(158_000), "seller_coin_borne": D(2_000)}, (D(0), False)),
        ({"payout": D(157_000), "trade_in_bonus_seller": D(3_000)}, (D(0), False)),
        (
            {"payout": D(147_000), "withheld_from_payout": D(3_000)},
            (D(10_000), False),
        ),
        ({"payout": D(155_000), "fee_other": D(5_000)}, (D(0), False)),
        ({"payout": D(140_000), "affiliate_commission": D(20_000)}, (D(0), False)),
        # nothing stated: 0 only when the arithmetic closes, else the buyer-side rule (E-P5)
        ({"seller_voucher_borne": None}, (D(0), False)),
        ({"seller_voucher_borne": None, "payout": D(150_000)}, (None, False)),
        ({"seller_voucher_borne": D(0), "payout": None}, (D(0), False)),
    ],
)
def test_the_settlement_arithmetic_decides(changes, expected):
    assert decide_seller_voucher(replace(BASE, **changes)) == expected


def _attached(**changes):
    ln = line("v1", shop_voucher_share=D(10_000))
    (out,) = attach_income([ShopLine(ln, ln.order_date, "")], {"v1": replace(BASE, **changes)})
    return out.line


def test_a_buyer_side_voucher_the_seller_did_not_bear_is_not_charged():
    ln = _attached()
    assert (ln.seller_voucher, ln.voucher_unknown) == (D(0), False)
    assert "seller_voucher" not in line_profit(ln, COST, schedule=SCHEDULE).missing


def test_a_voucher_the_settlement_took_is_charged():
    assert _attached(payout=D(150_000)).seller_voucher == D(10_000)


def test_an_unknown_voucher_is_not_charged_and_leaves_the_profit_basis():
    ln = _attached(payout=D(155_000))
    pb = line_profit(ln, COST, schedule=SCHEDULE)
    assert (ln.seller_voucher, pb.voucher, pb.contribution) == (D(0), D(0), None)
    assert "seller_voucher" in pb.missing


def test_an_order_without_a_voucher_is_never_unknown():
    ln = line("v1")
    (out,) = attach_income(
        [ShopLine(ln, ln.order_date, "")], {"v1": replace(BASE, payout=D(155_000))}
    )
    assert out.line.voucher_unknown is False


def test_the_withheld_tax_is_still_no_cost():
    ln = _attached(payout=D(147_000), withheld_from_payout=D(3_000))
    assert ln.income is not None and ln.income.tax_withheld == 0


# -- the day check ---------------------------------------------------------------------------------


def test_the_days_lines_are_compared_with_the_confirmed_gmv():
    ln = line("v1", shop_voucher_share=D(10_000))
    ok, other = ln.order_date, date(2026, 1, 1)
    gmv = ln.order_value - D(10_000)
    (same,) = day_consistency([ln], {ok: gmv, other: D(5)})
    assert same.matches and same.difference == 0
    (off,) = day_consistency([replace(ln, voucher_unknown=True)], {ok: gmv - D(90_000)})
    assert not off.matches
    assert (off.difference, off.unknown_vouchers) == (D(90_000), 1)
