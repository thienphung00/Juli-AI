"""Ops "Huỷ kết nối" (D25.13): Admin disconnects a shop, idempotently, audited.

TikTok Shop has NO token-revoke endpoint in its Open API (a seller revokes an
app in Seller Center; we then receive the deauthorization webhook, which only
pauses the shop -- ``ShopsRepo.pause_automation``). So Juli revokes on its own
side, the strongest thing it can do:

1. every stored credential of the shop: tokens overwritten with a non-token
   marker (unusable, never decryptable), status ``needs_reauth`` -- the poll
   (``enumerate_pollable_shops``) and the credential resolver skip it, so no
   read and no write can reach TikTok any more;
2. the shop: ``is_active = False`` (the same switch the deauthorization webhook
   uses) -- polling, and with it card generation, stops;
3. pending runs (queued / running / waiting_*): ``cancel_requested`` (the
   seller's own cancel path);
4. history, cards, rules, measurements are kept. Reconnecting (the normal
   TikTok connect) writes fresh tokens over the same credential row and sets the
   shop active again (``core/security/tiktok_oauth.py``), so everything resumes;
5. the owner is e-mailed (``mailer.send_notice``; logged when SMTP is not set).

Runs under the shop's own tenant scope (shop + owner GUCs), as ``juli_app``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import _apply_tenant_context_to_session
from juli_backend.models.models import Shop, TikTokCredential, WorkflowRun
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops.mailer import get_mailer
from juli_backend.services.ops.overview import ShopListing

logger = logging.getLogger(__name__)

#: Written over both tokens: not a token, not ciphertext -- unusable by design.
REVOKED_TOKEN = "revoked-by-juli-ops"
NEEDS_REAUTH = "needs_reauth"
PENDING_RUN_STATUSES = ("queued", "running", "waiting_approval", "waiting_external")
REASON_MAX = 300


class DisconnectError(ValueError):
    pass


@dataclass(frozen=True)
class DisconnectResult:
    already: bool
    credentials_revoked: int
    runs_cancelled: int
    email_sent: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "already_disconnected": self.already,
            "credentials_revoked": self.credentials_revoked,
            "runs_cancelled": self.runs_cancelled,
            "email_sent": self.email_sent,
            "tiktok_revoke": "not_available",
        }


def disconnect_notice(shop_name: str, reason: str) -> str:
    return (
        f"Chào bạn,\n\nĐội ngũ Juli đã huỷ kết nối shop “{shop_name}” với Juli.\n"
        f"Lý do: {reason}\n\nJuli đã thu hồi quyền truy cập đã lưu, ngừng lấy dữ liệu và tạo thẻ, "
        "và không ghi gì thêm lên TikTok. Lịch sử, Quy tắc và kết quả đo được giữ lại; "
        "kết nối lại trong Juli sẽ dùng tiếp.\n\n— Juli"
    )


async def disconnect_shop(
    session: AsyncSession,
    actor: audit.Actor,
    listing: ShopListing,
    *,
    reason: str,
    confirm_name: str,
) -> DisconnectResult:
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise DisconnectError("reason is required")
    if len(clean_reason) > REASON_MAX:
        raise DisconnectError(f"reason is longer than {REASON_MAX} characters")
    if confirm_name.strip() != listing.shop_name.strip():
        raise DisconnectError("type the shop name to confirm")
    await _apply_tenant_context_to_session(session, listing.shop_id, listing.owner_user_id)
    shop = await session.get(Shop, listing.shop_id)
    if shop is None:
        raise DisconnectError("shop not found")
    credentials = list(
        (
            await session.execute(
                select(TikTokCredential).where(TikTokCredential.shop_id == listing.shop_id)
            )
        )
        .scalars()
        .all()
    )
    live = [c for c in credentials if c.status != NEEDS_REAUTH or c.access_token != REVOKED_TOKEN]
    already = not shop.is_active and not live
    now = utc_now_naive()
    for credential in live:
        credential.access_token = REVOKED_TOKEN
        credential.refresh_token = REVOKED_TOKEN
        credential.token_expires_at = now
        credential.status = NEEDS_REAUTH
        credential.last_refresh_error = "disconnected by Juli Ops"
    shop.is_active = False
    pending = list(
        (
            await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.shop_id == listing.shop_id,
                    WorkflowRun.status.in_(PENDING_RUN_STATUSES),
                    WorkflowRun.cancel_requested.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    for run in pending:
        run.cancel_requested = True
    cancelled = len(pending)
    await session.flush()
    sent = False
    if not already and listing.owner_email:
        sent = await get_mailer().send_notice(
            to=listing.owner_email,
            subject=f"Juli đã huỷ kết nối shop {listing.shop_name}",
            body=disconnect_notice(listing.shop_name, clean_reason),
        )
    result = DisconnectResult(
        already=already,
        credentials_revoked=len(live),
        runs_cancelled=int(cancelled),
        email_sent=sent,
    )
    await audit.record(
        session,
        actor,
        "shop_disconnect",
        shop_id=listing.shop_id,
        before={"is_active": not already or shop.is_active},
        after={"reason": clean_reason, **result.to_json()},
    )
    logger.info(
        "ops_shop_disconnected",
        extra={"shop_id": str(listing.shop_id), "already": already, "runs": result.runs_cancelled},
    )
    return result


__all__ = ["DisconnectError", "DisconnectResult", "disconnect_shop"]
