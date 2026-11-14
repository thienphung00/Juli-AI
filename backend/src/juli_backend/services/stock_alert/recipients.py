"""Who gets a shop's stock e-mail (Part S).

Every ACTIVE shop member (``shop_members``, ``removed_at`` NULL) whose account has a verified
e-mail (``users.email``, the verified Google address) and who has not unsubscribed from this
shop; the pre-backfill owner ("owner without a row", ``shop_team``'s access rule) too. Juli team
accounts (``@app-juli.com``) are not seller members and get no copy as a member. Ops gets a BCC for
the first 14 days the shop's e-mail goes out (``preview`` sends to the Ops address only):
``STOCK_ALERT_OPS_EMAIL``, default ``lienhe@app-juli.com``.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, ShopMember, User
from juli_backend.models.stock_alert import ShopeeStockAlertUnsubscribe
from juli_backend.services.ops.access import ops_role
from juli_backend.services.shop_team import is_team_email

DEFAULT_OPS_EMAIL = "lienhe@app-juli.com"
OPS_BCC_DAYS = 14


def ops_email() -> str:
    return os.environ.get("STOCK_ALERT_OPS_EMAIL", "").strip() or DEFAULT_OPS_EMAIL


@dataclass(frozen=True)
class Recipient:
    user_id: uuid.UUID
    email: str


async def members(session: AsyncSession, shop_id: uuid.UUID) -> list[Recipient]:
    async with ops_role(session):
        rows = (
            await session.execute(
                select(ShopMember.user_id, ShopMember.removed_at, User.email)
                .join(User, User.id == ShopMember.user_id)
                .where(ShopMember.shop_id == shop_id)
            )
        ).all()
        owner = (
            await session.execute(
                select(Shop.user_id, User.email)
                .join(User, User.id == Shop.user_id)
                .where(Shop.id == shop_id)
            )
        ).first()
        gone = set(
            (
                await session.execute(
                    select(ShopeeStockAlertUnsubscribe.user_id).where(
                        ShopeeStockAlertUnsubscribe.shop_id == shop_id
                    )
                )
            )
            .scalars()
            .all()
        )
    found: dict[uuid.UUID, str] = {
        r.user_id: r.email for r in rows if r.removed_at is None and r.email
    }
    has_row = {r.user_id for r in rows}
    if owner is not None and owner.user_id not in has_row and owner.email:
        found[owner.user_id] = owner.email
    out = [
        Recipient(uid, email.strip().lower())
        for uid, email in found.items()
        if uid not in gone and not is_team_email(email) and "@" in email
    ]
    return sorted(out, key=lambda r: r.email)


__all__ = ["OPS_BCC_DAYS", "Recipient", "members", "ops_email"]
