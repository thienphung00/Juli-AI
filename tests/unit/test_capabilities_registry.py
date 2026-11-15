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
    "promo_bmsm",
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
    "promo_bmsm",
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


def test_shopee_rows_are_pinned() -> None:
    fill = Capability(Route.connector, "Connector fill, seller presses Lưu")
    assert can("shopee", "promo_bmsm") == fill
    assert can("shopee", "bundle") == fill
    assert can("shopee", "read_orders") == Capability(
        Route.connector, "Connector reads the order pages"
    )


TIKTOK_API = (
    "read_orders",
    "read_shop_totals",
    "read_ads",
    "write_price",
    "write_listing",
    "write_stock",
    "promo_discount",
    "promo_flash_sale",
    "promo_bmsm",
    "affiliate_commission",
)
TIKTOK_OTHER = {
    "voucher": Capability(Route.connector, "TikTok Shop không có API tạo voucher của shop."),
    "bundle": Capability(Route.connector, "TikTok Shop không có API tạo Bundle Deal."),
    "ads_campaign": Capability(Route.connector, "Shop chưa cấp quyền TikTok Business API"),
    "live_schedule": Capability(Route.none, "TikTok Shop chưa có API đặt lịch LIVE cho shop."),
    "shop_tab": Capability(Route.connector, "TikTok Shop không có API chỉnh tab Shop."),
}


@pytest.mark.parametrize("capability", TIKTOK_API)
def test_tiktok_api_rows(capability: str) -> None:
    assert can("tiktok", capability).route is Route.api


@pytest.mark.parametrize("capability", sorted(TIKTOK_OTHER))
def test_tiktok_non_api_rows_carry_their_reason(capability: str) -> None:
    assert can("tiktok", capability) == TIKTOK_OTHER[capability]


def test_every_capability_is_declared_for_tiktok() -> None:
    assert set(TIKTOK_API) | set(TIKTOK_OTHER) == set(DOC_CAPABILITIES)


def test_bundle_and_bmsm_are_two_capabilities() -> None:
    assert "promo_bmsm" in CAPABILITIES and "bundle" in CAPABILITIES
    assert can("tiktok", "promo_bmsm").route is not can("tiktok", "bundle").route


def test_unknown_capability_is_an_error() -> None:
    with pytest.raises(KeyError) as unknown:
        can("shopee", "write_everything")
    assert "write_everything" in str(unknown.value)
