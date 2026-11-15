"""P100 B.1: product names. The Connector's product list (``item_catalog``) names the product:
its newest name wins over a file-sourced ``platform_items.name``; Shopee's deleted-product
placeholder never overwrites a real name; a raw product-list status code is stored as its label.

SQLite through the ingest gateway; every value is synthetic.
"""

from __future__ import annotations

import pytest

from juli_backend.models.platform_data import PlatformItem
from juli_backend.services.ingest.gateway import DELETED_PRODUCT_NAME, item_status_label
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.unit.test_shopee_file_datasets import OCTOBER, _body, _ingest, _product, _rows, _shop
from tests.unit.test_shopee_reader_datasets import _post


@pytest.fixture(autouse=True)
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


async def _items(session, shop):
    return {(i.item_id, i.variation_id): i for i in await _rows(session, PlatformItem, shop)}


async def test_the_connector_product_list_name_replaces_a_file_name(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "product_period",
        _body([_product("1001", item_name="Găng tay cũ")], period=OCTOBER),
    )
    assert (await _items(session, shop))[("1001", "")].name == "Găng tay cũ"
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post(
            [{"item_id": "1001", "item_name": "[Deal 15.11] Găng tay mới"}], "2026-10-30", "period"
        ),
    )
    item = (await _items(session, shop))[("1001", "")]
    assert item.name == "[Deal 15.11] Găng tay mới"
    # the file still owns the rest of the row (rank): its status is kept
    assert item.status == "Đang hoạt động"


async def test_the_deleted_product_placeholder_never_overwrites_a_real_name(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post([{"item_id": "1001", "item_name": "Găng tay"}], "2026-10-29", "period"),
    )
    await _ingest(
        session,
        shop,
        "product_period",
        _body([_product("1001", item_name=DELETED_PRODUCT_NAME)], period=OCTOBER),
    )
    assert (await _items(session, shop))[("1001", "")].name == "Găng tay"
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post([{"item_id": "1001", "item_name": DELETED_PRODUCT_NAME}], "2026-10-30", "period"),
    )
    assert (await _items(session, shop))[("1001", "")].name == "Găng tay"


async def test_a_product_known_only_as_deleted_has_no_name(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "product_period",
        _body([_product("1002", item_name=DELETED_PRODUCT_NAME)], period=OCTOBER),
    )
    assert (await _items(session, shop))[("1002", "")].name is None


async def test_a_raw_status_code_is_stored_as_its_label(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post(
            [{"item_id": "1001", "item_name": "Găng tay", "status": "1"}], "2026-10-30", "period"
        ),
    )
    assert (await _items(session, shop))[("1001", "")].status == "Đang hoạt động"


def test_status_labels():
    assert item_status_label("1") == "Đang hoạt động"
    assert item_status_label("Đang hoạt động") == "Đang hoạt động"
    assert item_status_label("7") == "7"  # an unknown code is kept as read
    assert item_status_label(None) is None


# -- Shopee's deleted-listing name is not an active listing (Chrome check 2026-11-15) ---------


def test_the_deleted_listing_name_is_never_an_active_listing():
    """ORY's Sản phẩm footer listed two "Không thể lấy thông tin sản phẩm do bị xóa" rows as
    active listings without orders: older catalogue rows with that name and no status."""
    from types import SimpleNamespace

    from juli_backend.services.ingest import gateway
    from juli_backend.services.shopee_analytics import catalog as sa_catalog
    from juli_backend.services.shopee_analytics.catalog import ItemInfo
    from juli_backend.services.shopee_analytics.compute import _active_items
    from juli_backend.services.shopee_builder.catalogue import is_active

    assert sa_catalog.DELETED_PRODUCT_NAME == gateway.DELETED_PRODUCT_NAME
    assert not is_active(None, DELETED_PRODUCT_NAME)
    assert not is_active("NORMAL", f"  {DELETED_PRODUCT_NAME} ")
    assert is_active(None, "Nước rửa chén Ory 500ml") and is_active(None)
    assert not is_active("UNLIST", "Nước rửa chén Ory 500ml")

    items = {
        "1": ItemInfo("1", name="Nước rửa chén Ory 500ml"),
        "2": ItemInfo("2", name=DELETED_PRODUCT_NAME),
        "3": ItemInfo("3", name=DELETED_PRODUCT_NAME, status="NORMAL"),
        "4": ItemInfo("4", name="Túi vải đay", status="UNLIST"),
    }
    catalog = SimpleNamespace(items=items, name=lambda i: items[i].name or i)
    ctx = SimpleNamespace(catalog=catalog, rules=SimpleNamespace(excluded=frozenset()))
    assert _active_items(ctx) == {"1": "Nước rửa chén Ory 500ml"}
