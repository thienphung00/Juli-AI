"""R7 on SQLite: at an equal rank the newer capture wins, whatever the upload order. Values are
synthetic. The same statements run on Postgres in the gate."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import update

from juli_backend.models.ingest import IngestDatasetStatus
from juli_backend.models.shopee_profit import ShopeeOrderIncome
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.unit.income_workbooks import order_row, sku_row
from tests.unit.test_ingest_precedence import _from, _gmv, _traffic
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop
from tests.unit.test_shopee_income_ingest import REF_A, A, B, _income_post

NEWER = "2026-10-29T09:40:00+07:00"
OLDER = "2026-10-29T09:20:00+07:00"


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


def _at(source: str, gmv: int, captured: str) -> dict[str, Any]:
    body = _from(source, [_traffic(gmv)])
    body["captured_at"] = captured
    return body


async def test_an_older_capture_uploaded_after_a_newer_one_does_not_overwrite(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("extension", 950, NEWER))
    await _ingest(session, shop, "traffic_overview", _at("extension", 900, OLDER))
    assert await _gmv(session, shop) == [Decimal("950")]


async def test_a_newer_capture_overwrites_an_older_one(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("extension", 900, OLDER))
    await _ingest(session, shop, "traffic_overview", _at("extension", 950, NEWER))
    assert await _gmv(session, shop) == [Decimal("950")]


async def test_a_higher_rank_row_is_kept_whatever_the_capture_time(session):
    # owner 2026-11-18: the Connector (extension) outranks a file
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("extension", 1000, OLDER))
    await _ingest(session, shop, "traffic_overview", _at("file", 900, NEWER))
    assert await _gmv(session, shop) == [Decimal("1000")]


async def test_a_higher_rank_replaces_a_lower_one_even_when_older(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("file", 900, NEWER))
    await _ingest(session, shop, "traffic_overview", _at("extension", 1000, OLDER))
    assert await _gmv(session, shop) == [Decimal("1000")]


async def test_the_dataset_status_only_moves_forward(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("extension", 950, NEWER))
    await _ingest(session, shop, "traffic_overview", _at("extension", 900, OLDER))
    (status,) = await _rows(session, IngestDatasetStatus, shop)
    assert (status.last_captured_at.hour, status.last_captured_at.minute) == (2, 40)
    assert status.last_row_count == 1


async def test_a_status_without_a_capture_time_takes_the_incoming_one(session):
    shop = await _shop(session)
    await _ingest(session, shop, "traffic_overview", _at("extension", 950, NEWER))
    await session.execute(update(IngestDatasetStatus).values(last_captured_at=None))
    await _ingest(session, shop, "traffic_overview", _at("extension", 900, OLDER))
    (status,) = await _rows(session, IngestDatasetStatus, shop)
    assert status.last_captured_at is not None and status.last_captured_at.minute == 20


def _orders(service_fee: int) -> list[dict[str, Any]]:
    return [
        order_row(A, **{"Giá sản phẩm": 200000, "Phí Dịch Vụ": -service_fee}),
        sku_row(A, "1001", "Combo 3 hộp", 200000),
        order_row(B, **{"Giá sản phẩm": 50000, "Phí Dịch Vụ": -3000}),
    ]


async def test_order_income_an_older_post_uploaded_late_does_not_overwrite(session, tmp_path):
    shop = await _shop(session)
    (tmp_path / "n").mkdir()
    (tmp_path / "o").mkdir()
    newer = {**_income_post(tmp_path / "n", orders=_orders(14000)), "captured_at": NEWER}
    older = {**_income_post(tmp_path / "o", orders=_orders(9000)), "captured_at": OLDER}
    await _ingest(session, shop, "order_income", newer)
    await _ingest(session, shop, "order_income", older)
    a = next(r for r in await _rows(session, ShopeeOrderIncome, shop) if r.order_ref == REF_A)
    assert a.fee_service == Decimal(14000)


async def test_order_income_a_newer_post_overwrites(session, tmp_path):
    shop = await _shop(session)
    (tmp_path / "n").mkdir()
    (tmp_path / "o").mkdir()
    older = {**_income_post(tmp_path / "o", orders=_orders(9000)), "captured_at": OLDER}
    newer = {**_income_post(tmp_path / "n", orders=_orders(14000)), "captured_at": NEWER}
    await _ingest(session, shop, "order_income", older)
    await _ingest(session, shop, "order_income", newer)
    a = next(r for r in await _rows(session, ShopeeOrderIncome, shop) if r.order_ref == REF_A)
    assert a.fee_service == Decimal(14000)


async def test_order_lines_an_older_post_uploaded_late_does_not_overwrite(session, tmp_path):
    from juli_backend.models.shopee_profit import ShopeeOrderLine
    from tests.unit.test_shopee_orders_parser import ORDER_A, _line, _posts

    shop = await _shop(session)
    (tmp_path / "n").mkdir()
    (tmp_path / "o").mkdir()
    (newer,) = _posts(tmp_path / "n", [_line(ORDER_A, **{"Giá gốc": "100000.00"})]).posts
    (older,) = _posts(tmp_path / "o", [_line(ORDER_A, **{"Giá gốc": "70000.00"})]).posts
    await _ingest(session, shop, "order_lines", {**newer.body, "captured_at": NEWER})
    await _ingest(session, shop, "order_lines", {**older.body, "captured_at": OLDER})
    (line,) = await _rows(session, ShopeeOrderLine, shop)
    assert line.original_price == Decimal(100000)
