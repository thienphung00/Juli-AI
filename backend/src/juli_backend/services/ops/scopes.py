"""Permission status (D25.15): which TikTok scopes the shop's grant carries.

The scopes Juli's reads use, per resource it calls (docs/integrations/tiktok_api/
endpoints.md, contracts p14-rules-and-cost.md). Partner Center scope NAMES are
not all documented in this repo: ``seller.order.info`` and
``seller.finance.info`` are (P14-C); the others are UNVERIFIED names taken from
TikTok Shop's Partner Center catalogue and can be replaced without a deploy via
``TIKTOK_REQUIRED_SCOPES`` (comma-separated) once checked (DEBT).

Status per shop, from ``tiktok_credentials.scopes`` (now written on every
authorisation AND every token refresh):
- ``complete`` -- every needed scope is granted;
- ``missing`` -- some are not (listed); the seller sees "Kết nối lại TikTok Shop
  để cấp quyền mới";
- ``unknown`` -- no scope list stored yet (authorised before #1714 and not
  refreshed since).

P101 W2a (contract §2.4, §6): a missing scope or an expired authorisation is a CONNECTION
state, ``needs_reauth`` ("Cần cấp lại quyền TikTok"), never a capability difference. It is
derived here for display only: it never writes ``tiktok_credentials.status`` and never stops
the reads the granted scopes still allow (the fan-outs keep running on the live credential).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import TikTokCredential

#: scope → what Juli uses it for (Ops shows the purpose next to a missing scope).
DEFAULT_REQUIRED_SCOPES: dict[str, str] = {
    "seller.order.info": "đơn hàng, chi tiết giá",
    "seller.finance.info": "giao dịch tài chính theo đơn",
    "data.shop_analytics.public.read": "số liệu Phân tích",
    "seller.product.basic": "sản phẩm",
    "seller.promotion.info": "khuyến mãi đang chạy",
    # P101 W2a: the scopes the TikTok capability rows need (p101-w0-probe-docs.md §A).
    "seller.product.write": "sửa sản phẩm, giá, tồn kho",
    "seller.promotion.write": "tạo và sửa khuyến mãi",
    "seller.affiliate_collaboration.read": "hoa hồng tiếp thị liên kết",
    "seller.affiliate_collaboration.write": "đặt hoa hồng tiếp thị liên kết",
}

#: P101 W2a: capability id (contract §2.4) -> the TikTok scopes it needs. A shop missing one is
#: ``needs_reauth`` for that capability only; every other capability keeps working.
SCOPES_BY_CAPABILITY: dict[str, tuple[str, ...]] = {
    "read_orders": ("seller.order.info",),
    "read_shop_totals": ("data.shop_analytics.public.read",),
    "write_price": ("seller.product.basic", "seller.product.write"),
    "write_listing": ("seller.product.basic", "seller.product.write"),
    "write_stock": ("seller.product.basic", "seller.product.write"),
    "promo_discount": ("seller.promotion.info", "seller.promotion.write"),
    "promo_flash_sale": ("seller.promotion.info", "seller.promotion.write"),
    "voucher": ("seller.promotion.info",),
    "affiliate_commission": (
        "seller.affiliate_collaboration.read",
        "seller.affiliate_collaboration.write",
    ),
}

#: The seller-facing label of the ``needs_reauth`` connection state.
REAUTH_LABEL = "Cần cấp lại quyền TikTok"

ACTIVE = "active"
NEEDS_REAUTH = "needs_reauth"
REASON_MISSING_SCOPES = "missing_scopes"
REASON_AUTHORIZATION_EXPIRED = "authorization_expired"

COMPLETE = "complete"
MISSING = "missing"
UNKNOWN = "unknown"
NOT_CONNECTED = "not_connected"


def required_scopes() -> dict[str, str]:
    raw = os.environ.get("TIKTOK_REQUIRED_SCOPES", "").strip()
    if not raw:
        return dict(DEFAULT_REQUIRED_SCOPES)
    names = [s.strip() for s in raw.split(",") if s.strip()]
    return {name: DEFAULT_REQUIRED_SCOPES.get(name, "") for name in names}


def capabilities_missing_scopes(missing: tuple[str, ...]) -> tuple[str, ...]:
    """The capability ids a missing-scope list blocks (contract §2.4), in registry order."""
    gaps = set(missing)
    return tuple(cap for cap, needs in SCOPES_BY_CAPABILITY.items() if gaps.intersection(needs))


@dataclass(frozen=True)
class ScopeStatus:
    status: str
    missing: tuple[str, ...]
    #: P101 W2a: every credential of the shop is ``needs_reauth`` (expired / revoked / Ops
    #: disconnect). Kept apart from ``status`` so the Ops reading of ``not_connected`` holds.
    authorization_expired: bool = False

    @property
    def connection_state(self) -> str:
        """``needs_reauth`` | ``active`` | ``not_connected`` (contract §6, display only)."""
        if self.authorization_expired or self.status == MISSING:
            return NEEDS_REAUTH
        return NOT_CONNECTED if self.status == NOT_CONNECTED else ACTIVE

    @property
    def reauth_reason(self) -> str | None:
        if self.authorization_expired:
            return REASON_AUTHORIZATION_EXPIRED
        return REASON_MISSING_SCOPES if self.status == MISSING else None

    def to_json(self) -> dict[str, Any]:
        needed = required_scopes()
        reauth = self.connection_state == NEEDS_REAUTH
        return {
            "status": self.status,
            "missing": [{"scope": s, "used_for": needed.get(s, "")} for s in self.missing],
            "needs_reconnect": reauth,
            "connection_state": self.connection_state,
            "needs_reauth": reauth,
            "reauth_reason": self.reauth_reason,
            "reauth_label": REAUTH_LABEL if reauth else None,
            "capabilities_needing_reauth": list(capabilities_missing_scopes(self.missing)),
        }


def status_of(scopes: str | None, *, connected: bool = True) -> ScopeStatus:
    if not connected:
        return ScopeStatus(NOT_CONNECTED, ())
    granted = {s.strip() for s in (scopes or "").split(",") if s.strip()}
    if not granted:
        return ScopeStatus(UNKNOWN, ())
    missing = tuple(s for s in required_scopes() if s not in granted)
    return ScopeStatus(MISSING if missing else COMPLETE, missing)


async def shop_scope_status(session: AsyncSession, shop_id: uuid.UUID) -> ScopeStatus:
    """From the shop's usable credential (caller holds the shop's scope)."""
    rows = (
        await session.execute(
            select(TikTokCredential.scopes, TikTokCredential.status).where(
                TikTokCredential.shop_id == shop_id
            )
        )
    ).all()
    return status_from_credentials([(scopes, status) for scopes, status in rows])


def status_from_credentials(rows: list[tuple[str | None, str]]) -> ScopeStatus:
    """``shop_scope_status`` from already-read ``(scopes, status)`` credential rows."""
    live = [scopes for scopes, status in rows if status != "needs_reauth"]
    if not live:
        # P101 W2a: credentials that all lapsed are an expired authorisation (needs_reauth),
        # not a shop that never connected.
        return ScopeStatus(NOT_CONNECTED, (), authorization_expired=bool(rows))
    best = max(live, key=lambda s: len(s or ""))
    return status_of(best)
