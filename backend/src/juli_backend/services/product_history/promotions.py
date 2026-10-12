"""Promotion activities persisted in tables (D30.1b), webhook 63 / 39 parsing (D30.4).

- ``upsert_activity`` -- one Search Activities row or Get Activity body into
  ``promotion_activities`` (any status, incl. EXPIRED / DEACTIVATED).
- ``upsert_activity_products`` -- a Get Activity body's products / SKUs with
  their activity price or discount into ``promotion_activity_products``; a
  product the body no longer lists gets ``removed_at``.
- ``parse_activity_change`` -- webhook 63 ``Activity change`` (``change_type``
  CREATE / UPDATE / DEACTIVATE, ``product_update_list`` /
  ``product_remove_list``) and 39 ``Activity status change`` into one
  :class:`ActivityChange`.
- ``is_juli_activity`` -- the activity is the one a Juli promotion card's run
  found after the seller applied it (``run_lever_flows.found`` carries its
  fingerprint), so it is Juli's change, not an external one.

Every function takes the caller's session and shop; nothing commits.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.history import PromotionActivity, PromotionActivityProduct
from juli_backend.models.lever_flows import FLOW_PROMOTION, RunLeverFlow
from juli_backend.services.product_history.normalize import epoch_to_naive_utc

#: Every status, so expired and deactivated activities are kept too.
ACTIVITY_STATUSES: tuple[str, ...] = ("ONGOING", "NOT_START", "EXPIRED", "DEACTIVATED")
DEACTIVATED = "DEACTIVATED"
CHANGE_CREATE = "CREATE"
CHANGE_UPDATE = "UPDATE"
CHANGE_DEACTIVATE = "DEACTIVATE"


def activity_id_of(raw: Mapping[str, Any]) -> str:
    return str(raw.get("id") or raw.get("activity_id") or "")


def _money(value: object) -> tuple[Decimal | None, str | None]:
    currency: str | None = None
    if isinstance(value, Mapping):
        currency = str(value.get("currency") or "") or None
        value = value.get("amount")
    if value is None or value == "":
        return None, currency
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None, currency
    return (amount if amount > 0 else None), currency


def _percent(value: object) -> Decimal | None:
    if isinstance(value, Mapping):
        value = value.get("value") or value.get("discount")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number > 0 else None


def _short(value: object, limit: int) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


async def upsert_activity(
    session: AsyncSession, shop_id: uuid.UUID, raw: Mapping[str, Any], *, now: datetime
) -> PromotionActivity | None:
    """Insert or refresh one activity; ``None`` when ``raw`` has no id."""
    activity_id = activity_id_of(raw)
    if not activity_id:
        return None
    row = (
        await session.execute(
            select(PromotionActivity).where(
                PromotionActivity.shop_id == shop_id,
                PromotionActivity.activity_id == activity_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = PromotionActivity(
            shop_id=shop_id, activity_id=activity_id, first_seen_at=now, refreshed_at=now
        )
        session.add(row)
    status = _short(raw.get("status"), 30)
    updated = epoch_to_naive_utc(raw.get("update_time"))
    for attr, value in (
        ("activity_type", _short(raw.get("activity_type"), 50)),
        ("title", _short(raw.get("title"), 500)),
        ("status", status),
        ("product_level", _short(raw.get("product_level"), 30)),
        ("begin_time", epoch_to_naive_utc(raw.get("begin_time"))),
        ("end_time", epoch_to_naive_utc(raw.get("end_time"))),
        ("tiktok_create_time", epoch_to_naive_utc(raw.get("create_time"))),
        ("tiktok_update_time", updated),
    ):
        if value is not None:
            setattr(row, attr, value)
    if status == DEACTIVATED and row.deactivated_at is None:
        row.deactivated_at = updated or now
    row.refreshed_at = now
    await session.flush()
    return row


def _entries(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``[{product_id, sku_id, price, currency, discount}]`` of a Get Activity body."""
    out: list[dict[str, Any]] = []
    for product in detail.get("products") or []:
        if not isinstance(product, Mapping):
            continue
        pid = str(product.get("id") or product.get("product_id") or "")
        if not pid:
            continue
        skus = [s for s in product.get("skus") or [] if isinstance(s, Mapping)]
        price, currency = _money(product.get("activity_price"))
        if price is not None or _percent(product.get("discount")) is not None or not skus:
            out.append(
                {
                    "product_id": pid,
                    "sku_id": "",
                    "price": price,
                    "currency": currency,
                    "discount": _percent(product.get("discount")),
                }
            )
        for sku in skus:
            sku_id = str(sku.get("id") or sku.get("sku_id") or "")
            if not sku_id:
                continue
            sku_price, sku_currency = _money(sku.get("activity_price"))
            out.append(
                {
                    "product_id": pid,
                    "sku_id": sku_id,
                    "price": sku_price,
                    "currency": sku_currency,
                    "discount": _percent(sku.get("discount")),
                }
            )
    return out


async def upsert_activity_products(
    session: AsyncSession,
    shop_id: uuid.UUID,
    activity_id: str,
    detail: Mapping[str, Any],
    *,
    now: datetime,
) -> list[str]:
    """Upsert the detail's products / SKUs; mark the ones it no longer lists removed.

    Returns the product ids the detail lists. A detail without a ``products``
    list (not fetched, or a shop-level activity) changes nothing.
    """
    if not isinstance(detail.get("products"), list):
        return []
    entries = _entries(detail)
    existing = {
        (row.tiktok_product_id, row.tiktok_sku_id): row
        for row in (
            await session.execute(
                select(PromotionActivityProduct).where(
                    PromotionActivityProduct.shop_id == shop_id,
                    PromotionActivityProduct.activity_id == activity_id,
                )
            )
        ).scalars()
    }
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["product_id"], entry["sku_id"])
        seen.add(key)
        row = existing.get(key)
        if row is None:
            row = PromotionActivityProduct(
                shop_id=shop_id,
                activity_id=activity_id,
                tiktok_product_id=key[0],
                tiktok_sku_id=key[1],
                added_at=now,
                updated_at=now,
            )
            session.add(row)
            existing[key] = row
        row.activity_price = entry["price"]
        row.currency = entry["currency"]
        row.discount_pct = entry["discount"]
        row.updated_at = now
        row.removed_at = None
    for key, row in existing.items():
        if key not in seen and row.removed_at is None:
            row.removed_at = now
    activity = (
        await session.execute(
            select(PromotionActivity).where(
                PromotionActivity.shop_id == shop_id,
                PromotionActivity.activity_id == activity_id,
            )
        )
    ).scalar_one_or_none()
    if activity is not None:
        activity.detail_fetched_at = now
    await session.flush()
    return sorted({entry["product_id"] for entry in entries})


async def mark_products_removed(
    session: AsyncSession,
    shop_id: uuid.UUID,
    activity_id: str,
    product_ids: Sequence[str],
    *,
    now: datetime,
) -> int:
    """Webhook 63's ``product_remove_list``: set ``removed_at`` on those products' rows."""
    if not product_ids:
        return 0
    rows = (
        await session.execute(
            select(PromotionActivityProduct).where(
                PromotionActivityProduct.shop_id == shop_id,
                PromotionActivityProduct.activity_id == activity_id,
                PromotionActivityProduct.tiktok_product_id.in_(list(product_ids)),
                PromotionActivityProduct.removed_at.is_(None),
            )
        )
    ).scalars()
    count = 0
    for row in rows:
        row.removed_at = now
        count += 1
    await session.flush()
    return count


def needs_detail(row: PromotionActivity, *, listed_update: datetime | None) -> bool:
    """Read the activity's products: never read, or TikTok updated it since."""
    if row.detail_fetched_at is None:
        return True
    return listed_update is not None and listed_update > row.detail_fetched_at


@dataclass(frozen=True)
class ActivityChange:
    """One webhook 63 / 39 notification, parsed."""

    activity_id: str
    change_type: str
    status: str | None
    occurred_at: datetime | None
    updated_products: list[str] = field(default_factory=list)
    removed_products: list[str] = field(default_factory=list)
    #: ``{product_id: [sku_id, ...]}`` when the notification names SKUs.
    skus: dict[str, list[str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "change_type": self.change_type,
            "status": self.status,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "updated_products": list(self.updated_products),
            "removed_products": list(self.removed_products),
            "skus": {k: list(v) for k, v in self.skus.items()},
        }

    @classmethod
    def from_json(cls, blob: Mapping[str, Any]) -> ActivityChange:
        occurred = blob.get("occurred_at")
        return cls(
            activity_id=str(blob.get("activity_id") or ""),
            change_type=str(blob.get("change_type") or CHANGE_UPDATE),
            status=blob.get("status"),
            occurred_at=datetime.fromisoformat(occurred) if occurred else None,
            updated_products=[str(p) for p in blob.get("updated_products") or []],
            removed_products=[str(p) for p in blob.get("removed_products") or []],
            skus={str(k): [str(s) for s in v] for k, v in (blob.get("skus") or {}).items()},
        )


def _product_list(value: object, skus: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, Mapping):
            pid = str(item.get("product_id") or item.get("id") or "")
            if not pid:
                continue
            sku_ids = [
                str(s.get("sku_id") or s.get("id") or "") if isinstance(s, Mapping) else str(s)
                for s in (item.get("sku_ids") or item.get("skus") or item.get("sku_list") or [])
            ]
            sku_ids = [s for s in sku_ids if s]
            if sku_ids:
                skus.setdefault(pid, []).extend(sku_ids)
        else:
            pid = str(item or "")
        if pid and pid not in out:
            out.append(pid)
    return out


def parse_activity_change(data: Mapping[str, Any] | None, *, catalog_id: int) -> ActivityChange:
    """Webhook 63 (``Activity change``) or 39 (``Activity status change``) ``data``.

    ``ValueError`` without an activity id. 39 carries no change type: a
    DEACTIVATED / EXPIRED status reads as ``DEACTIVATE``, anything else ``UPDATE``.
    """
    body = data or {}
    activity_id = str(body.get("activity_id") or body.get("id") or "")
    if not activity_id:
        raise ValueError("activity change without an activity_id")
    status = str(body.get("status") or body.get("activity_status") or "") or None
    change_type = str(body.get("change_type") or "").upper()
    if not change_type:
        change_type = (
            CHANGE_DEACTIVATE
            if catalog_id == 39 and status in (DEACTIVATED, "EXPIRED")
            else CHANGE_UPDATE
        )
    skus: dict[str, list[str]] = {}
    updated = _product_list(body.get("product_update_list"), skus)
    removed = _product_list(body.get("product_remove_list"), {})
    occurred = epoch_to_naive_utc(body.get("update_time") or body.get("change_time"))
    return ActivityChange(
        activity_id=activity_id,
        change_type=change_type,
        status=status,
        occurred_at=occurred,
        updated_products=updated,
        removed_products=removed,
        skus=skus,
    )


#: The verb the seller UI reads from a promotion change's ``fields``.
_VERBS = {CHANGE_CREATE: "start", CHANGE_UPDATE: "update", CHANGE_DEACTIVATE: "deactivate"}


def change_fields(activity_type: object, change_type: str, status: object = None) -> list[str]:
    """``[<activity type>, <verb>]`` for a promotion change, e.g. ``["flash_sale", "start"]``.

    The verb is one of ``start`` / ``update`` / ``deactivate`` / ``expire`` (the
    seller UI prints "bắt đầu" / "thay đổi" / "kết thúc"); the type is TikTok's
    ``activity_type`` lower-cased (``FLASHSALE`` → ``flash_sale``) when known.
    """
    verb = "expire" if str(status or "") == "EXPIRED" else _VERBS.get(change_type, "update")
    kind = str(activity_type or "").strip().lower()
    kind = {"flashsale": "flash_sale"}.get(kind, kind)
    return [kind, verb] if kind else [verb]


def promotion_ref(activity_id: str) -> str:
    """The fingerprint ``agent/tools/product.py::_promotion_ref`` gives an activity."""
    return hashlib.sha256(f"promotion:{activity_id}".encode()).hexdigest()[:16]


async def is_juli_activity(session: AsyncSession, shop_id: uuid.UUID, activity_id: str) -> bool:
    """A Juli promotion card's run found this activity (the seller applied Juli's card)."""
    ref = promotion_ref(activity_id)
    flows = (
        await session.execute(
            select(RunLeverFlow.found).where(
                RunLeverFlow.shop_id == shop_id,
                RunLeverFlow.kind == FLOW_PROMOTION,
                RunLeverFlow.found.is_not(None),
            )
        )
    ).scalars()
    return any(ref in json.dumps(found, default=str) for found in flows)


async def active_promotions_for(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_product_id: str, *, at: datetime
) -> list[dict[str, Any]]:
    """The product's activities running at ``at`` with their SKU prices (one query)."""
    rows = (
        await session.execute(
            select(PromotionActivity, PromotionActivityProduct)
            .join(
                PromotionActivityProduct,
                (PromotionActivityProduct.shop_id == PromotionActivity.shop_id)
                & (PromotionActivityProduct.activity_id == PromotionActivity.activity_id),
            )
            .where(
                PromotionActivity.shop_id == shop_id,
                PromotionActivityProduct.tiktok_product_id == tiktok_product_id,
                PromotionActivityProduct.removed_at.is_(None),
                PromotionActivity.begin_time <= at,
                (PromotionActivity.end_time.is_(None)) | (PromotionActivity.end_time > at),
                (PromotionActivity.deactivated_at.is_(None))
                | (PromotionActivity.deactivated_at > at),
            )
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for activity, product in rows:
        entry = out.setdefault(
            activity.activity_id,
            {
                "activity_id": activity.activity_id,
                "activity_type": activity.activity_type,
                "title": activity.title,
                "begin_time": activity.begin_time.isoformat() if activity.begin_time else None,
                "end_time": activity.end_time.isoformat() if activity.end_time else None,
                "skus": [],
            },
        )
        entry["skus"].append(
            {
                "sku_id": product.tiktok_sku_id or None,
                "activity_price": str(product.activity_price)
                if product.activity_price is not None
                else None,
                "discount_pct": str(product.discount_pct)
                if product.discount_pct is not None
                else None,
                "currency": product.currency,
            }
        )
    return [out[key] for key in sorted(out)]


__all__ = [
    "ACTIVITY_STATUSES",
    "CHANGE_CREATE",
    "CHANGE_DEACTIVATE",
    "CHANGE_UPDATE",
    "ActivityChange",
    "active_promotions_for",
    "change_fields",
    "activity_id_of",
    "is_juli_activity",
    "mark_products_removed",
    "needs_detail",
    "parse_activity_change",
    "promotion_ref",
    "upsert_activity",
    "upsert_activity_products",
]
