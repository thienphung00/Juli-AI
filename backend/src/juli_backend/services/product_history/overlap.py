"""External changes overlapping a measurement window (D30.4: "bị ảnh hưởng bởi thay đổi khác").

``external_changes_overlapping`` lists the changes to a product -- and the
shop-level ones (a promotion with no product list) -- that happened inside a
window, excluding Juli's own writes. ``measurement_external_changes`` derives
the window of a run's day-7 / day-14 measurement body (the 14 pre days before
day 0 through the last measured day) and returns the seller-facing
``[{kind, fields, occurred_at, source}]``. It annotates only: the verdict is
computed elsewhere and is not touched.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.history import ExternalChange
from juli_backend.models.models import Product
from juli_backend.services.product_history.normalize import local_midnight_utc

#: The pre window the measurement compares against (``measure_run``: 14 days).
PRE_DAYS = 14


@dataclass(frozen=True)
class OverlappingChange:
    kind: str
    fields: list[str]
    occurred_at: datetime
    source: str
    tiktok_product_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "fields": list(self.fields),
            "occurred_at": self.occurred_at.isoformat(),
            "source": self.source,
        }


async def external_changes_overlapping(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_id: str,
    start: datetime,
    end: datetime,
) -> list[OverlappingChange]:
    """Non-Juli changes to ``product_id`` (or the shop) with ``start <= occurred_at < end``."""
    rows = (
        await session.execute(
            select(ExternalChange)
            .where(
                ExternalChange.shop_id == shop_id,
                or_(
                    ExternalChange.tiktok_product_id == product_id,
                    ExternalChange.tiktok_product_id.is_(None),
                ),
                ExternalChange.juli_write.is_(False),
                ExternalChange.occurred_at >= start,
                ExternalChange.occurred_at < end,
            )
            .order_by(ExternalChange.occurred_at, ExternalChange.id)
        )
    ).scalars()
    return [
        OverlappingChange(
            kind=row.kind,
            fields=list(row.fields or []),
            occurred_at=row.occurred_at,
            source=row.source,
            tiktok_product_id=row.tiktok_product_id,
        )
        for row in rows
    ]


def measurement_window(body: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    """[day0 - 14 days, end of the last measured day) from a measurement body's ``dates``."""
    dates = body.get("dates") if isinstance(body.get("dates"), Mapping) else None
    if not dates or not dates.get("day7") or not dates.get("day14"):
        return None
    try:
        day7 = date.fromisoformat(str(dates["day7"]))
        day14 = date.fromisoformat(str(dates["day14"]))
    except ValueError:
        return None
    day0 = day7 - timedelta(days=7)
    last = day14 if body.get("stage") == "final" else day7
    return local_midnight_utc(day0 - timedelta(days=PRE_DAYS)), local_midnight_utc(
        last + timedelta(days=1)
    )


async def measurement_external_changes(
    session: AsyncSession, shop_id: uuid.UUID, run: Any, body: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The ``external_changes`` field of a run's measurement body (``[]`` when not derivable)."""
    window = measurement_window(body)
    product_uuid = getattr(run, "product_id", None)
    if window is None or product_uuid is None:
        return []
    product = await session.get(Product, product_uuid)
    if product is None or product.shop_id != shop_id:
        return []
    changes = await external_changes_overlapping(
        session, shop_id, product.tiktok_product_id, window[0], window[1]
    )
    return [change.to_json() for change in changes]


__all__ = [
    "OverlappingChange",
    "external_changes_overlapping",
    "measurement_external_changes",
    "measurement_window",
]
