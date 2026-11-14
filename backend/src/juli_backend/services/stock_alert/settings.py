"""Shop settings and the per-variation "Theo dõi" switch of the stock alert (Part S).

Shop settings live where the shop's settings live today, ``shop_rules`` (shop-wide rows, set by
``team``): ``stock_alert_status`` ``off`` | ``preview`` | ``on`` (default ``off``; ``preview`` sends
to the Ops address only) and ``stock_alert_days`` (N, default 7). Neither is in
``shop_rules.RULE_KEYS``, so the seller rules API can neither read nor write them: the Ops script
(``scripts/stock_alert_status.py``) is the one writer. The reviewer's sample shop is always ``off``.

"Theo dõi" (``shopee_sku_tracking``): with no row the variation is on when it is eligible, off
otherwise; the daily job stores that default (``set_by = 'default'``). A default-off variation that
becomes eligible turns on by itself; a default-on one stays on; a member's own setting
(``set_by`` = their user id) never changes by itself.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop
from juli_backend.models.run_changes import ShopRule
from juli_backend.models.stock_alert import SET_BY_DEFAULT, ShopeeSkuTracking
from juli_backend.services.stock_alert.eligibility import DEFAULT_ALERT_DAYS

logger = logging.getLogger(__name__)

STATUS_KEY = "stock_alert_status"
DAYS_KEY = "stock_alert_days"
STATUS_OFF = "off"
STATUS_PREVIEW = "preview"
STATUS_ON = "on"
STATUSES = (STATUS_OFF, STATUS_PREVIEW, STATUS_ON)
MIN_DAYS, MAX_DAYS = 1, 60


@dataclass(frozen=True)
class ShopSettings:
    status: str = STATUS_OFF
    days: int = DEFAULT_ALERT_DAYS
    sample: bool = False

    @property
    def sends(self) -> bool:
        return not self.sample and self.status in (STATUS_PREVIEW, STATUS_ON)


def is_sample_shop(shop: Shop | None) -> bool:
    """The reviewer's synthetic sample shop: a reserved Seller Centre id or a listed sample pin."""
    if shop is None:
        return False
    from juli_backend.services.reviewer.config import reviewer_sample_shop_ids
    from juli_backend.services.sample_shop.catalog import in_reserved_range

    return in_reserved_range(shop.shopee_shop_id) or shop.id in reviewer_sample_shop_ids()


async def load_settings(session: AsyncSession, shop_id: uuid.UUID) -> ShopSettings:
    shop = await session.get(Shop, shop_id)
    sample = is_sample_shop(shop)
    rows = (
        await session.execute(
            select(ShopRule.rule_key, ShopRule.value).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key.in_([STATUS_KEY, DAYS_KEY]),
                ShopRule.scope_ref == "",
            )
        )
    ).all()
    values = {r.rule_key: r.value for r in rows}
    status = values.get(STATUS_KEY)
    days = values.get(DAYS_KEY)
    return ShopSettings(
        status=STATUS_OFF if sample or status not in STATUSES else str(status),
        days=int(days)
        if isinstance(days, int) and not isinstance(days, bool) and MIN_DAYS <= days <= MAX_DAYS
        else DEFAULT_ALERT_DAYS,
        sample=sample,
    )


async def _set_rule(
    session: AsyncSession, shop_id: uuid.UUID, key: str, value: object, now: datetime
) -> None:
    row = await session.scalar(
        select(ShopRule).where(
            ShopRule.shop_id == shop_id, ShopRule.rule_key == key, ShopRule.scope_ref == ""
        )
    )
    if row is None:
        session.add(
            ShopRule(
                shop_id=shop_id,
                rule_key=key,
                scope_ref="",
                value=value,
                set_by="team",
                set_by_user_id=None,
                set_at=now,
            )
        )
    else:
        row.value = value
        row.set_by = "team"
        row.set_at = now
    await session.flush()


async def set_status(
    session: AsyncSession,
    shop_id: uuid.UUID,
    status: str,
    *,
    now: datetime,
    days: int | None = None,
) -> ShopSettings:
    """The Ops switch (no commit). The sample shop refuses anything but ``off``."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {list(STATUSES)}")
    if days is not None and not MIN_DAYS <= days <= MAX_DAYS:
        raise ValueError(f"days must be between {MIN_DAYS} and {MAX_DAYS}")
    if status != STATUS_OFF and is_sample_shop(await session.get(Shop, shop_id)):
        raise ValueError("the reviewer's sample shop never gets the stock alert")
    await _set_rule(session, shop_id, STATUS_KEY, status, now)
    if days is not None:
        await _set_rule(session, shop_id, DAYS_KEY, days, now)
    return await load_settings(session, shop_id)


# ---------------------------------------------------------------------------- Theo dõi


def sku_key(item_id: str, model_id: str) -> str:
    return f"{item_id}:{model_id}" if model_id else item_id


def split_key(key: str) -> tuple[str, str]:
    item, _, model = key.partition(":")
    return item, model


async def tracking_rows(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, ShopeeSkuTracking]:
    rows = (
        (
            await session.execute(
                select(ShopeeSkuTracking).where(ShopeeSkuTracking.shop_id == shop_id)
            )
        )
        .scalars()
        .all()
    )
    return {sku_key(r.item_id, r.model_id): r for r in rows}


def effective(row: ShopeeSkuTracking | None, eligible: bool) -> bool:
    if row is None:
        return eligible
    if row.set_by == SET_BY_DEFAULT and not row.tracked and eligible:
        return True
    return bool(row.tracked)


async def sync_defaults(
    session: AsyncSession,
    shop_id: uuid.UUID,
    keys: Iterable[str],
    eligible: set[str],
    *,
    now: datetime,
) -> dict[str, bool]:
    """Store the default state of every variation in ``keys``; returns key -> tracked."""
    rows = await tracking_rows(session, shop_id)
    out: dict[str, bool] = {}
    for key in keys:
        row = rows.get(key)
        state = effective(row, key in eligible)
        if row is None:
            item, model = split_key(key)
            session.add(
                ShopeeSkuTracking(
                    shop_id=shop_id,
                    item_id=item,
                    model_id=model,
                    tracked=state,
                    set_by=SET_BY_DEFAULT,
                    set_at=now,
                )
            )
        elif row.set_by == SET_BY_DEFAULT and row.tracked != state:
            row.tracked = state
            row.set_at = now
        out[key] = state
    await session.flush()
    return out


async def set_tracked(
    session: AsyncSession,
    shop_id: uuid.UUID,
    key: str,
    tracked: bool,
    *,
    user_id: uuid.UUID,
    now: datetime,
) -> ShopeeSkuTracking:
    """A member's own switch (no commit); logged with who and when."""
    item, model = split_key(key)
    row = await session.get(ShopeeSkuTracking, (shop_id, item, model))
    if row is None:
        row = ShopeeSkuTracking(
            shop_id=shop_id,
            item_id=item,
            model_id=model,
            tracked=tracked,
            set_by=str(user_id),
            set_at=now,
        )
        session.add(row)
    else:
        row.tracked = tracked
        row.set_by = str(user_id)
        row.set_at = now
    await session.flush()
    logger.info(
        "stock_alert_sku_tracking_set",
        extra={"shop_id": str(shop_id), "user_id": str(user_id), "tracked": tracked},
    )
    return row


async def untracked_keys(session: AsyncSession, shop_id: uuid.UUID) -> set[str]:
    """Variations a member switched off ("Ngừng theo dõi"). A variation that is off only by default
    (not eligible for an alert, e.g. it sold nothing lately) is not "stopped": its cards are
    generated and kept as before."""
    rows = await tracking_rows(session, shop_id)
    return {k for k, r in rows.items() if not r.tracked and r.set_by != SET_BY_DEFAULT}


__all__ = [
    "STATUSES",
    "ShopSettings",
    "effective",
    "is_sample_shop",
    "load_settings",
    "set_status",
    "set_tracked",
    "sku_key",
    "split_key",
    "sync_defaults",
    "tracking_rows",
    "untracked_keys",
]
