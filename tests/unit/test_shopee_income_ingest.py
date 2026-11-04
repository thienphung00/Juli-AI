"""P91 D-12: the ``order_income`` dataset through the ingest gateway (SQLite) and the order
lines' variation name.

- the parser's posts land in ``shopee_order_income``, one row per order, keyed by the same hashed
  ref as the order lines (so the two join);
- a later post of the same order replaces the row (same rank), a field it does not state never
  erases a stored one; a Connector (extension) post never replaces a file row;
- the row model has no field for a buyer: an extra field is refused; the raw copy keeps only the
  allowlisted numbers;
- variations that share one SKU are told apart by the line's variation name.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest import mapping
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.privacy.payload_allowlist import allowlist_payload, ingest_endpoint
from scripts import load_shopee_exports
from scripts.shopee_exports import parse
from tests.unit.income_workbooks import order_row, sku_row, write_income
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop

KEY = b"synthetic-order-ref-key"
A, B = "TESTORD-A01", "TESTORD-B02"
REF_A = parse.order_ref(A, KEY)
CAPTURED = "2026-10-29T09:30:00+07:00"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _income_post(tmp_path, orders=None, fees=None):
    orders = orders or [
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
            },
        ),
        sku_row(A, "1001", "Combo 3 hộp", 200000),
        order_row(B, **{"Giá sản phẩm": 50000, "Phí Dịch Vụ": -3000}),
    ]
    write_income(
        tmp_path, orders, fees=fees if fees is not None else [(A, -3000, -11000), (B, -3000, 0)]
    )
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    (post,) = parsed.posts
    # the gateway's clock in these tests is 2026-10-30: end the period on a day that has passed
    period = {**post.body["period"], "end": "2026-10-28"}
    return {**post.body, "captured_at": CAPTURED, "period": period}


async def test_income_rows_land_one_per_order_keyed_by_the_order_ref(session, tmp_path):
    shop = await _shop(session)
    await _ingest(session, shop, "order_income", _income_post(tmp_path))
    stored = {r.order_ref: r for r in await _rows(session, ShopeeOrderIncome, shop)}
    assert set(stored) == {REF_A, parse.order_ref(B, KEY)}
    a = stored[REF_A]
    assert a.platform == "shopee" and a.source == "file" and a.source_rank == 3
    assert (a.fee_fixed, a.fee_service, a.fee_infra, a.fee_voucher_xtra) == (
        Decimal(27400),
        Decimal(14000),
        Decimal(3000),
        Decimal(11000),
    )
    assert a.net_shipping_cost == Decimal(3000) and a.payout == Decimal(143600)
    assert (a.ordered_on, a.paid_on) == (date(2026, 9, 28), date(2026, 10, 3))
    assert a.transaction_fee_rate == Decimal("0.06")


async def test_the_income_row_joins_the_order_lines_on_the_order_ref(session, tmp_path):
    shop = await _shop(session)
    session.add(
        ShopeeOrderLine(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            order_ref=REF_A,
            line_no=0,
            ordered_at=datetime(2026, 9, 28, 10),
            status="delivered",
            item_id="sku:X",
            qty=1,
            original_price=Decimal(1),
            deal_price=Decimal(1),
            source="file",
            source_version="t",
        )
    )
    await _ingest(session, shop, "order_income", _income_post(tmp_path))
    joined = (
        await session.execute(
            select(ShopeeOrderLine.order_ref, ShopeeOrderIncome.payout).join(
                ShopeeOrderIncome,
                (ShopeeOrderIncome.shop_id == ShopeeOrderLine.shop_id)
                & (ShopeeOrderIncome.order_ref == ShopeeOrderLine.order_ref),
            )
        )
    ).all()
    assert joined == [(REF_A, Decimal(143600))]


async def test_a_later_post_replaces_the_row_but_never_erases_a_stated_field(session, tmp_path):
    shop = await _shop(session)
    await _ingest(session, shop, "order_income", _income_post(tmp_path))
    # the same month again, now without the Service Fee Details row of A (infra / Xtra unknown)
    (tmp_path / "again").mkdir()
    again = _income_post(tmp_path / "again", fees=[])
    again["captured_at"] = "2026-10-29T09:40:00+07:00"
    await _ingest(session, shop, "order_income", again)
    a = next(r for r in await _rows(session, ShopeeOrderIncome, shop) if r.order_ref == REF_A)
    assert (a.fee_infra, a.fee_voucher_xtra) == (Decimal(3000), Decimal(11000))  # kept
    assert a.fee_fixed == Decimal(27400)


async def test_the_same_post_twice_is_a_duplicate_and_writes_nothing(session, tmp_path):
    shop = await _shop(session)
    body = _income_post(tmp_path)
    first = await _ingest(session, shop, "order_income", body)
    second = await _ingest(session, shop, "order_income", body)
    assert (first.duplicate, second.duplicate) == (False, True)
    assert len(await _rows(session, ShopeeOrderIncome, shop)) == 2


async def test_a_connector_post_never_replaces_a_file_row(session, tmp_path):
    shop = await _shop(session)
    await _ingest(session, shop, "order_income", _income_post(tmp_path))
    rows = [{"order_ref": REF_A, "payout": 1, "fee_fixed": 1}]
    body = {
        "source": "extension",
        "source_version": "connector-1",
        "captured_at": "2026-10-30T09:30:00+07:00",
        "period": {"start": "2026-10-01", "end": "2026-10-28", "granularity": "period"},
        "rows": rows,
    }
    await _ingest(session, shop, "order_income", body)
    a = next(r for r in await _rows(session, ShopeeOrderIncome, shop) if r.order_ref == REF_A)
    assert (a.source, a.fee_fixed) == ("file", Decimal(27400))


async def test_a_file_post_replaces_a_connector_row(session, tmp_path):
    shop = await _shop(session)
    body = {
        "source": "extension",
        "source_version": "connector-1",
        "captured_at": "2026-10-28T09:30:00+07:00",
        "period": {"start": "2026-10-01", "end": "2026-10-28", "granularity": "period"},
        "rows": [{"order_ref": REF_A, "payout": 1, "fee_fixed": 1}],
    }
    await _ingest(session, shop, "order_income", body)
    await _ingest(session, shop, "order_income", _income_post(tmp_path))
    a = next(r for r in await _rows(session, ShopeeOrderIncome, shop) if r.order_ref == REF_A)
    assert (a.source, a.fee_fixed) == ("file", Decimal(27400))


def test_the_row_model_has_no_field_for_a_buyer():
    spec = mapping.dataset_spec("shopee", "order_income")
    assert spec is not None and spec.writes == mapping.WRITE_ORDER_INCOME
    fields = set(spec.row_model.model_fields)
    personal = ("name", "phone", "address", "recipient", "tax_code", "payment_method")
    assert not {f for f in fields if f.startswith("buyer") or any(w in f for w in personal)}
    with pytest.raises(Exception, match="buyer_name|Extra"):
        spec.row_model.model_validate({"order_ref": "a" * 32, "buyer_name": "x"})
    with pytest.raises(Exception, match="order_ref|pattern"):
        spec.row_model.model_validate({"order_ref": "TESTORD-A01"})  # a raw id is refused


def test_the_raw_copy_keeps_only_the_allowlisted_fields(tmp_path):
    body = _income_post(tmp_path)
    body["rows"][0]["buyer_name"] = "CANARY"
    kept = allowlist_payload("shopee", ingest_endpoint("order_income"), body)
    assert "buyer_name" not in kept["rows"][0] and "payout" in kept["rows"][0]


def test_the_loader_validates_the_income_posts(tmp_path):
    _income_post(tmp_path)
    parsed = parse.parse_folder(tmp_path, order_ref_key=KEY)
    assert load_shopee_exports.validate(parsed, datetime.now(UTC).replace(tzinfo=None)) == []


# ------------------------------------------------------------------ the variation name


def _variation(shop, variation_id: str, name: str, sku: str = "G500001") -> PlatformItem:
    return PlatformItem(
        id=uuid.uuid4(),
        shop_id=shop.id,
        platform="shopee",
        item_id="9001",
        variation_id=variation_id,
        variation_name=name,
        seller_sku=sku,
        source="file",
        source_rank=3,
        source_version="t",
        mapper_version=1,
        captured_at=datetime(2026, 10, 29),
        updated_at=datetime(2026, 10, 29),
        first_seen_on=date(2026, 10, 1),
        last_seen_on=date(2026, 10, 28),
        extra={},
    )


def _line(ref: str, no: int, name: str | None, sku: str = "G500001") -> dict:
    row = {
        "order_ref": ref,
        "line_no": no,
        "ordered_at": "2026-10-05T10:15:00",
        "status": "delivered",
        "qty": 1,
        "original_price": 300000,
        "deal_price": 300000,
        "sku": "G500001",
        "variation_sku": sku,
        "paid_at": "2026-10-05T10:20:00",
    }
    if name:
        row["variation_name"] = name
    return row


def _order_post(rows: list[dict]) -> dict:
    return {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
        "captured_at": CAPTURED,
        "period": {"start": "2026-10-05", "end": "2026-10-05", "granularity": "period"},
        "rows": rows,
    }


async def test_variations_that_share_a_sku_resolve_by_the_variation_name(session):
    shop = await _shop(session)
    for variation_id, name in (
        ("v3", "Combo 3 hộp"),
        ("v5", "Combo 5 hộp"),
        ("v10", "Combo 10 hộp"),
    ):
        session.add(_variation(shop, variation_id, name))
    await session.flush()
    refs = ["1" * 32, "2" * 32, "3" * 32]
    rows = [
        _line(refs[0], 0, "Combo 10 hộp"),
        _line(refs[1], 0, "combo 5 hộp "),  # case and spaces do not matter
        _line(refs[2], 0, None),  # no name: the first variation, as before
    ]
    await _ingest(session, shop, "order_lines", _order_post(rows))
    stored = {r.order_ref: r for r in await _rows(session, ShopeeOrderLine, shop)}
    assert stored[refs[0]].variation_id == "v10"
    assert stored[refs[1]].variation_id == "v5"
    assert stored[refs[2]].variation_id == "v10"  # twins in item / variation order: v10 < v3 < v5
    assert stored[refs[0]].variation_name == "Combo 10 hộp"


async def test_a_reload_without_the_name_keeps_the_stored_one(session):
    shop = await _shop(session)
    ref = "4" * 32
    await _ingest(session, shop, "order_lines", _order_post([_line(ref, 0, "Combo 3 hộp")]))
    later = _order_post([_line(ref, 0, None)])
    later["captured_at"] = "2026-10-29T09:40:00+07:00"
    await _ingest(session, shop, "order_lines", later)
    (line,) = await _rows(session, ShopeeOrderLine, shop)
    assert line.variation_name == "Combo 3 hộp"
