"""``can(platform, capability) -> Capability(route, reason)`` (doc §8, owner decision T9).

A platform row that is not declared is ``Route.none`` with reason ``"not declared"``: the
TikTok session fills the TikTok rows. Shopee today: reads come through the Connector (Seller
Centre pages); writes are a Connector fill the seller confirms with Lưu.

``promo_bmsm`` is Buy More Save More (tiered discount, Shopee "Combo khuyến mãi"); ``bundle``
is the fixed-price Bundle Deal (Shopee "Listing combo mới"). TikTok facts verified in the
sandbox (probe 2026-11-15); the ``Capability`` type has no constraint field, so they live here:

- BMSM is only MINIMAL_ITEM_QUANTITY + PERCENTAGE_OFF, PRODUCT level, at most 2 tiers,
  integer percent.
- A FLASHSALE product cannot also be in a BMSM, and vice versa (exclusive). Flash sale plus a
  direct discount or a fixed price on the same product is accepted.
- An activity cannot be edited after deactivation.
- Ads (``read_ads``, ``ads_campaign``) need the separate TikTok Business API OAuth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class Route(StrEnum):
    api = "api"
    connector = "connector"
    none = "none"


@dataclass(frozen=True)
class Capability:
    route: Route
    reason: str


CAPABILITIES: tuple[str, ...] = (
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
    "unsettled_orders",
)

NOT_DECLARED = Capability(Route.none, "not declared")
_FILL = "Connector fill, seller presses Lưu"

_SHOPEE: Mapping[str, Capability] = MappingProxyType(
    {
        "read_orders": Capability(Route.connector, "Connector reads the order pages"),
        "read_shop_totals": Capability(Route.connector, "Connector reads shop_overview"),
        "read_ads": Capability(Route.connector, "Connector reads the ads pages"),
        "write_price": Capability(Route.connector, _FILL),
        "write_listing": Capability(Route.connector, _FILL),
        "promo_discount": Capability(Route.connector, _FILL),
        "promo_flash_sale": Capability(Route.connector, _FILL),
        "promo_bmsm": Capability(Route.connector, _FILL),
        "voucher": Capability(Route.connector, _FILL),
        "bundle": Capability(Route.connector, _FILL),
        "affiliate_commission": Capability(Route.connector, _FILL),
        "ads_campaign": Capability(Route.connector, _FILL),
        "write_stock": Capability(Route.none, "no Connector form map yet"),
        "live_schedule": Capability(Route.none, "not offered on Shopee VN seller flows in Juli"),
        "shop_tab": Capability(Route.none, "not offered yet"),
        "unsettled_orders": Capability(
            Route.connector, "Connector reads the income (settlement) pages"
        ),
    }
)

_NO_BUSINESS = "Shop chưa cấp quyền TikTok Business API"
_API = Capability(Route.api, "TikTok Shop Open API")

_TIKTOK: Mapping[str, Capability] = MappingProxyType(
    {
        "read_orders": _API,
        "read_shop_totals": _API,
        "read_ads": Capability(Route.api, "TikTok Business API (OAuth riêng)"),
        "write_price": _API,
        "write_listing": _API,
        "write_stock": _API,
        "promo_discount": _API,
        "promo_flash_sale": _API,
        "promo_bmsm": _API,
        "affiliate_commission": _API,
        "voucher": Capability(Route.connector, "TikTok Shop không có API tạo voucher của shop."),
        "bundle": Capability(Route.connector, "TikTok Shop không có API tạo Bundle Deal."),
        "ads_campaign": Capability(Route.connector, _NO_BUSINESS),
        "live_schedule": Capability(Route.none, "TikTok Shop chưa có API đặt lịch LIVE cho shop."),
        "shop_tab": Capability(Route.connector, "TikTok Shop không có API chỉnh tab Shop."),
        "unsettled_orders": Capability(
            Route.none, "no settlement read for TikTok Shop in Juli yet"
        ),
    }
)

#: ``ads_campaign`` is ``api`` once the shop grants the Business API scope; until then the
#: row above (connector, ``_NO_BUSINESS``) is what ``can`` returns.
_ROWS: Mapping[str, Mapping[str, Capability]] = MappingProxyType(
    {"shopee": _SHOPEE, "tiktok": _TIKTOK}
)


def can(platform: str, capability: str) -> Capability:
    """The route for one capability on one platform; undeclared is ``Route.none``."""
    if capability not in CAPABILITIES:
        raise KeyError(f"unknown capability {capability!r}")
    return _ROWS.get(platform, {}).get(capability, NOT_DECLARED)
