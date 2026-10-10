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
}

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


@dataclass(frozen=True)
class ScopeStatus:
    status: str
    missing: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        needed = required_scopes()
        return {
            "status": self.status,
            "missing": [{"scope": s, "used_for": needed.get(s, "")} for s in self.missing],
            "needs_reconnect": self.status == MISSING,
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
    live = [scopes for scopes, status in rows if status != "needs_reauth"]
    if not live:
        return status_of(None, connected=False)
    best = max(live, key=lambda s: len(s or ""))
    return status_of(best)
