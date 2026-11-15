"""Platform capabilities (``services/capabilities``, doc §8, owner decision T9)."""

from __future__ import annotations

import pytest

from juli_backend.services.capabilities import CAPABILITIES, Capability, Route, can

DOC_CAPABILITIES = (
    "read_orders",
    "read_shop_totals",
    "read_ads",
    "write_price",
    "write_listing",
    "write_stock",
    "promo_discount",
    "promo_flash_sale",
    "voucher",
    "bundle",
    "affiliate_commission",
    "ads_campaign",
    "live_schedule",
    "shop_tab",
)
SHOPEE_READS = ("read_orders", "read_shop_totals", "read_ads")
SHOPEE_FILLS = (
    "write_price",
    "write_listing",
    "promo_discount",
    "promo_flash_sale",
    "voucher",
    "bundle",
    "affiliate_commission",
    "ads_campaign",
)


def test_capability_ids_are_the_doc_list() -> None:
    assert CAPABILITIES == DOC_CAPABILITIES


@pytest.mark.parametrize("capability", SHOPEE_READS)
def test_shopee_reads_come_through_the_connector(capability: str) -> None:
    assert can("shopee", capability).route is Route.connector


@pytest.mark.parametrize("capability", SHOPEE_FILLS)
def test_shopee_writes_are_a_connector_fill_the_seller_saves(capability: str) -> None:
    got = can("shopee", capability)
    assert got.route is Route.connector
    assert "Lưu" in got.reason


SHOPEE_NONE = {
    "write_stock": "no Connector form map yet",
    "live_schedule": "not offered on Shopee VN seller flows in Juli",
    "shop_tab": "not offered yet",
}


def test_shopee_none_rows_are_explicit_with_a_reason() -> None:
    assert set(SHOPEE_NONE) == set(DOC_CAPABILITIES) - set(SHOPEE_READS) - set(SHOPEE_FILLS)
    for capability, reason in SHOPEE_NONE.items():
        assert can("shopee", capability) == Capability(Route.none, reason)


@pytest.mark.parametrize("capability", DOC_CAPABILITIES)
def test_tiktok_rows_are_not_declared_yet(capability: str) -> None:
    assert can("tiktok", capability) == Capability(Route.none, "not declared")


def test_unknown_capability_is_an_error() -> None:
    with pytest.raises(KeyError) as unknown:
        can("shopee", "write_everything")
    assert "write_everything" in str(unknown.value)
