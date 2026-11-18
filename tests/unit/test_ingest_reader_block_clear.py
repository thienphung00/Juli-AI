"""B3: an accepted extension ingest clears the blocked reader of its dataset (t2-backend)."""

from __future__ import annotations

from datetime import datetime

from juli_backend.models.shopee_connector import ShopeeConnectorState
from tests.unit.test_ingest_gateway import _body, _ingest, _shopee_tenant, _source_row

BLOCKS_AT = datetime(2026, 10, 12, 0, 0)
BLOCK = {"section": "phan_tich_ban_hang", "reason": "password_recheck", "readers": ["traffic"]}
OTHER = {"section": "seller_centre", "reason": "login", "readers": ["orders"]}


async def _blocked(session, shop, blocks):
    session.add(
        ShopeeConnectorState(shop_id=shop.id, reader_blocks=blocks, reader_blocks_at=BLOCKS_AT)
    )
    await session.flush()


async def _blocks(session, shop):
    row = await session.get(ShopeeConnectorState, shop.id)
    await session.refresh(row)
    return row.reader_blocks


async def test_an_extension_ingest_of_the_readers_dataset_clears_it(session):
    _, shop = await _shopee_tenant(session)
    await _blocked(session, shop, [BLOCK, OTHER])
    rows = [_source_row("psd_label_product_card")]
    await _ingest(session, shop, "traffic_overview", _body(rows))
    assert await _blocks(session, shop) == [OTHER]


async def test_a_duplicate_with_a_later_capture_clears_too(session):
    _, shop = await _shopee_tenant(session)
    rows = [_source_row("psd_label_product_card")]
    await _ingest(session, shop, "traffic_overview", _body(rows))
    await _blocked(session, shop, [BLOCK])
    again = await _ingest(
        session, shop, "traffic_overview", _body(rows, captured_at="2026-10-12T09:45:00+07:00")
    )
    assert again.duplicate is True
    assert await _blocks(session, shop) == []


async def test_a_capture_before_the_block_or_another_dataset_leaves_it(session):
    _, shop = await _shopee_tenant(session)
    await _blocked(session, shop, [BLOCK])
    rows = [_source_row("psd_label_product_card")]
    old = _body(rows, captured_at="2026-10-11T09:30:00+07:00")
    await _ingest(session, shop, "traffic_overview", old)
    assert await _blocks(session, shop) == [BLOCK]


async def test_a_shop_without_a_state_row_gets_none_created(session):
    _, shop = await _shopee_tenant(session)
    await _ingest(session, shop, "traffic_overview", _body([_source_row("psd_label_product_card")]))
    assert await session.get(ShopeeConnectorState, shop.id) is None
