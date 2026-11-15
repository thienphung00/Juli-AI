"""``can(platform, capability) -> Capability(route, reason)`` (doc §8, owner decision T9).

A platform row that is not declared is ``Route.none`` with reason ``"not declared"``: the
TikTok session fills the TikTok rows. Shopee today: reads come through the Connector (Seller
Centre pages); writes are a Connector fill the seller confirms with Lưu.
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
    "voucher",
    "bundle",
    "affiliate_commission",
    "ads_campaign",
    "live_schedule",
    "shop_tab",
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
        "voucher": Capability(Route.connector, _FILL),
        "bundle": Capability(Route.connector, _FILL),
        "affiliate_commission": Capability(Route.connector, _FILL),
        "ads_campaign": Capability(Route.connector, _FILL),
    }
)

_ROWS: Mapping[str, Mapping[str, Capability]] = MappingProxyType({"shopee": _SHOPEE})


def can(platform: str, capability: str) -> Capability:
    """The route for one capability on one platform; undeclared is ``Route.none``."""
    if capability not in CAPABILITIES:
        raise KeyError(f"unknown capability {capability!r}")
    return _ROWS.get(platform, {}).get(capability, NOT_DECLARED)
