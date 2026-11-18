"""``DbCanonicalWriter``: canonical rows -> ``order_lines`` / ``order_settlements`` (P101 W2, M3).

The DB implementation of :class:`~juli_backend.services.ingest.canonical.CanonicalWriter`. It
writes through the SAME upserts the gateway uses (``writers.upsert_line_values``,
``income.upsert_settlement_values``), so the precedence is one rule everywhere
(``rank_guard.ranked_set``, owner 2026-11-18 + R7): API > Connector > file; a post of a higher
rank replaces with its non-null values, an equal rank too unless its raw payload's capture is
older (then it is ignored), a lower one only fills the stored row's NULL columns and leaves the
provenance with the higher writer; a NULL never clears a stored value; a rerun is the same rows
(a row without a raw payload has no capture, which does not block an equal rank). No tax is
calculated: the reported ``vat_withheld`` / ``pit_withheld`` are stored as given.

Times: a mapper emits aware UTC; the column is ``timestamptz``, so the instant is kept. ``day`` is
the VN calendar day of ``ordered_at`` (a 03:00 VN order is the previous UTC date but its own VN
day).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_RANK, effective_rank
from juli_backend.models.shopee_profit import (
    ShopeeOrderIncome,
    ShopeeOrderLine,
    as_vn,
    vn_day,
)
from juli_backend.services.ingest.canonical import (
    OrderLine,
    OrderSettlement,
    check_scope,
    replaces,
)
from juli_backend.services.ingest.income import STATED_COLUMNS, upsert_settlement_values
from juli_backend.services.ingest.writers import canonical_status, upsert_line_values

#: ``OrderLine`` fields copied to the column of the same name (the rest are set below).
_LINE_FIELDS: tuple[str, ...] = (
    "shop_id",
    "platform",
    "order_ref",
    "line_no",
    "item_id",
    "variation_id",
    "variation_name",
    "sku",
    "variation_sku",
    "qty",
    "returned_qty",
    "original_price",
    "deal_price",
    "shop_voucher_share",
    "platform_voucher_share",
    "bundle_discount",
    "seller_subsidy",
    "platform_subsidy",
    "promo_kind",
    "voucher_code",
    "buyer_shipping_fee",
    "bank_promo",
    "traffic_source",
    "ad_attributed",
    "affiliate",
    "commission",
    "kol_key",
    "kol_handle",
    "affiliate_channel",
    "affiliate_campaign_type",
    "affiliate_mcn",
    "fee_fixed",
    "fee_service",
    "fee_payment",
    "fee_other",
    "payout",
    "source",
    "source_version",
    "raw_payload_id",
)
_LINE_TIMES: tuple[str, ...] = ("ordered_at", "paid_at", "completed_at")
_SETTLEMENT_PROVENANCE = frozenset({"source", "source_rank", "source_version", "raw_payload_id"})


def line_values(line: OrderLine, now: datetime) -> dict[str, Any]:
    """The ``order_lines`` row of a canonical line: its fields, the canonical status, the
    aware times, ``day`` (VN date) and ``source_rank = SOURCE_RANK[source]``."""
    value: dict[str, Any] = {name: getattr(line, name) for name in _LINE_FIELDS}
    for name in _LINE_TIMES:
        value[name] = as_vn(getattr(line, name))
    value["day"] = vn_day(line.ordered_at)
    value["status"] = canonical_status(line.status, paid=line.paid_at is not None)
    value["id"] = uuid.uuid4()
    value["source_rank"] = SOURCE_RANK.get(line.source, 0)
    value["updated_at"] = now
    return value


def settlement_values(row: OrderSettlement, now: datetime) -> dict[str, Any]:
    """The ``order_settlements`` row of a canonical settlement (every stated column + the post's
    provenance)."""
    value: dict[str, Any] = {name: getattr(row, name) for name in STATED_COLUMNS}
    value.update(
        {
            "id": uuid.uuid4(),
            "shop_id": row.shop_id,
            "platform": row.platform,
            "order_ref": row.order_ref,
            "source": row.source,
            "source_rank": row.source_rank,
            "source_version": row.source_version,
            "raw_payload_id": row.raw_payload_id,
            "updated_at": now,
        }
    )
    return value


def _unique(rows: Sequence[Any]) -> list[Any]:
    """The last row of each key: one statement cannot touch a key twice."""
    return list({row.key: row for row in rows}.values())


class DbCanonicalWriter:
    """Writes canonical rows into the canonical tables on ``session`` (the caller commits and
    scopes the shop, as for the gateway)."""

    def __init__(self, session: AsyncSession, *, now: Callable[[], datetime] | None = None) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

    async def upsert_order_lines(
        self, shop_id: uuid.UUID, platform: str, lines: Sequence[OrderLine]
    ) -> int:
        check_scope(shop_id, platform, lines)
        rows = _unique(lines)
        if not rows:
            return 0
        stored = await self._stored(ShopeeOrderLine, shop_id, platform, rows)
        written = sum(1 for row in rows if _line_changes(stored.get(row.key), row))
        now = self._now()
        await upsert_line_values(self._session, [line_values(row, now) for row in rows])
        return written

    async def upsert_settlements(
        self, shop_id: uuid.UUID, platform: str, rows: Sequence[OrderSettlement]
    ) -> int:
        check_scope(shop_id, platform, rows)
        unique = _unique(rows)
        if not unique:
            return 0
        stored = await self._stored(ShopeeOrderIncome, shop_id, platform, unique)
        written = sum(1 for row in unique if _settlement_changes(stored.get(row.key), row))
        now = self._now()
        await upsert_settlement_values(self._session, [settlement_values(r, now) for r in unique])
        return written

    async def _stored(
        self, model: Any, shop_id: uuid.UUID, platform: str, rows: Sequence[Any]
    ) -> dict[tuple[object, ...], Any]:
        """The stored rows on the posted order refs, keyed like the canonical rows."""
        refs = sorted({row.order_ref for row in rows})
        found = await self._session.execute(
            select(model)
            .where(
                model.shop_id == shop_id,
                model.platform == platform,
                model.order_ref.in_(refs),
            )
            .execution_options(populate_existing=True)
        )
        by_key: dict[tuple[object, ...], Any] = {}
        for stored in found.scalars():
            key: tuple[object, ...] = (stored.shop_id, stored.platform, stored.order_ref)
            if model is ShopeeOrderLine:
                key = (*key, stored.line_no)
            by_key[key] = stored
        return by_key


def _line_changes(stored: ShopeeOrderLine | None, line: OrderLine) -> bool:
    """Whether the post inserts, replaces or fills a gap (a lower rank that adds nothing: no)."""
    if stored is None:
        return True
    if replaces(effective_rank(stored.source, stored.source_rank), SOURCE_RANK.get(line.source, 0)):
        return True
    incoming = {n: getattr(line, n) for n in (*_LINE_FIELDS, *_LINE_TIMES)}
    return _fills(stored, incoming)


def _settlement_changes(stored: ShopeeOrderIncome | None, row: OrderSettlement) -> bool:
    if stored is None:
        return True
    if replaces(
        effective_rank(stored.source, stored.source_rank),
        effective_rank(row.source, row.source_rank),
    ):
        return True
    return _fills(stored, {name: getattr(row, name) for name in STATED_COLUMNS})


def _fills(stored: Any, incoming: dict[str, Any]) -> bool:
    return any(
        getattr(stored, name, None) is None and value is not None
        for name, value in incoming.items()
        if name not in _SETTLEMENT_PROVENANCE
    )


__all__ = ["DbCanonicalWriter", "line_values", "settlement_values"]
