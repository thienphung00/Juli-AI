"""The seller's data export, ``GET /v1/me/export`` (P50-B, D60.6, contract §export).

What it holds: the account row (no internal id but the user id), the privacy
preferences, the seller's shops (name, platform, connected_at, active) and, per
shop, the data the seller already sees in the product -- products, action cards
and the shop's rules. Each table is capped at ``EXPORT_ROW_LIMIT`` rows and says
``truncated`` when the cap bit.

What it never holds: TikTok / ingest tokens or any credential row, staff, audit,
reviewer or Ops rows, other shops' rows, buyer contact data (Juli does not store
it). Shop rows are read under each shop's own ``with_shop_scope``, so RLS is the
second fence behind the ``shop_id`` filter.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.models import ActionCard, Product, Shop
from juli_backend.models.run_changes import ShopRule
from juli_backend.repositories.identity import ShopsRepo, UsersRepo
from juli_backend.services.privacy.prefs import PrivacyState, iso_utc
from juli_backend.services.privacy.terms import EXPORT_ROW_LIMIT

FORMAT_VERSION = 1

#: (model, exported columns, order) per seller-visible table.
_PRODUCT_COLUMNS = (
    "tiktok_product_id",
    "title",
    "name",
    "category",
    "price",
    "price_currency",
    "inventory",
    "status",
    "revenue",
    "units_sold",
    "created_at",
)
_CARD_COLUMNS = (
    "workflow_key",
    "title",
    "description",
    "severity",
    "status",
    "created_at",
    "approved_at",
    "executed_at",
    "dismissed_at",
)
_RULE_COLUMNS = ("rule_key", "scope_ref", "value", "set_by", "set_at")


def export_json_default(value: Any) -> Any:
    """JSON for the types the export reads (UTC instants as ``…Z``)."""
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _row(obj: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    return {column: export_json_default(getattr(obj, column)) for column in columns}


async def _table(
    session: AsyncSession, model: Any, shop_id: uuid.UUID, columns: tuple[str, ...], order: Any
) -> dict[str, Any]:
    stmt = select(model).where(model.shop_id == shop_id).order_by(order).limit(EXPORT_ROW_LIMIT + 1)
    rows = list((await session.execute(stmt)).scalars())
    return {
        "rows": [_row(r, columns) for r in rows[:EXPORT_ROW_LIMIT]],
        "truncated": len(rows) > EXPORT_ROW_LIMIT,
    }


async def _shop_entry(session: AsyncSession, shop: Shop) -> dict[str, Any]:
    async with with_shop_scope(session, shop.id):
        data = {
            "products": await _table(session, Product, shop.id, _PRODUCT_COLUMNS, Product.id),
            "action_cards": await _table(
                session, ActionCard, shop.id, _CARD_COLUMNS, ActionCard.created_at
            ),
            "rules": await _table(session, ShopRule, shop.id, _RULE_COLUMNS, ShopRule.rule_key),
        }
    return {
        "name": shop.shop_name,
        "platform": shop.platform or "tiktok",
        "connected_at": export_json_default(shop.created_at),
        "is_active": bool(shop.is_active),
        "data": data,
    }


async def build_export(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    user = await UsersRepo(session).get_own(user_id)
    account = {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "phone": user.phone,
        "created_at": export_json_default(user.created_at),
        "staff_access_consent_at": export_json_default(user.staff_access_consent_at),
    }
    shops = sorted(
        await ShopsRepo(session).list_for_authorization(user_id),
        key=lambda s: (s.created_at or now.replace(tzinfo=None), str(s.id)),
    )
    return {
        "format_version": FORMAT_VERSION,
        "exported_at": iso_utc(now),
        "account": account,
        "privacy": PrivacyState.of(user).to_json(),
        "shops": [await _shop_entry(session, shop) for shop in shops],
        "limits": {"rows_per_table": EXPORT_ROW_LIMIT},
    }


__all__ = ["FORMAT_VERSION", "build_export", "export_json_default"]
