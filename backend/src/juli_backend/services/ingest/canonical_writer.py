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

Counting (P101 W2 t1, S-3): a post counts only when it inserts a row or changes a stored value
(a stated value that differs, a gap it fills, or the provenance of a higher writer); a re-post of
the same values is NOT counted and its day is not touched. ``write_order_lines`` /
``write_settlements`` return the count and the VN days of the rows that changed (both the stored
and the posted day, when a post moves an order), for the day rebuild (S-4).

Times: a mapper emits aware UTC; the column is ``timestamptz``, so the instant is kept. ``day`` is
the VN calendar day of ``ordered_at`` (a 03:00 VN order is the previous UTC date but its own VN
day).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
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


@dataclass(frozen=True)
class WriteResult:
    """What one write changed: the row count and the VN days of the changed rows."""

    written: int = 0
    days: frozenset[date] = frozenset()


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
        return (await self.write_order_lines(shop_id, platform, lines)).written

    async def upsert_settlements(
        self, shop_id: uuid.UUID, platform: str, rows: Sequence[OrderSettlement]
    ) -> int:
        return (await self.write_settlements(shop_id, platform, rows)).written

    async def write_order_lines(
        self, shop_id: uuid.UUID, platform: str, lines: Sequence[OrderLine]
    ) -> WriteResult:
        """As :meth:`upsert_order_lines`, with the VN days of the lines that changed."""
        check_scope(shop_id, platform, lines)
        rows = _unique(lines)
        if not rows:
            return WriteResult()
        stored = await self._stored(ShopeeOrderLine, shop_id, platform, rows)
        changed = [row for row in rows if _line_changes(stored.get(row.key), row)]
        if not changed:
            return WriteResult()
        now = self._now()
        await upsert_line_values(self._session, [line_values(row, now) for row in changed])
        days = {vn_day(row.ordered_at) for row in changed}
        days |= {s.day for row in changed if (s := stored.get(row.key)) is not None and s.day}
        return WriteResult(len(changed), frozenset(days))

    async def write_settlements(
        self, shop_id: uuid.UUID, platform: str, rows: Sequence[OrderSettlement]
    ) -> WriteResult:
        """As :meth:`upsert_settlements`, with the order days (``ordered_on``) that changed."""
        check_scope(shop_id, platform, rows)
        unique = _unique(rows)
        if not unique:
            return WriteResult()
        stored = await self._stored(ShopeeOrderIncome, shop_id, platform, unique)
        changed = [row for row in unique if _settlement_changes(stored.get(row.key), row)]
        if not changed:
            return WriteResult()
        now = self._now()
        await upsert_settlement_values(self._session, [settlement_values(r, now) for r in changed])
        days = {row.ordered_on for row in changed if row.ordered_on is not None}
        days |= {
            s.ordered_on
            for row in changed
            if (s := stored.get(row.key)) is not None and s.ordered_on is not None
        }
        return WriteResult(len(changed), frozenset(days))

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
    """Whether the post inserts, changes or fills a gap (a re-post of the same values: no)."""
    if stored is None:
        return True
    if replaces(effective_rank(stored.source, stored.source_rank), SOURCE_RANK.get(line.source, 0)):
        stated = {n: getattr(line, n) for n in _LINE_FIELDS}
        stated.update({n: as_vn(getattr(line, n)) for n in _LINE_TIMES})
        stated["status"] = canonical_status(line.status, paid=line.paid_at is not None)
        stated["source_rank"] = SOURCE_RANK.get(line.source, 0)
        return _differs(stored, stated)
    incoming = {n: getattr(line, n) for n in (*_LINE_FIELDS, *_LINE_TIMES)}
    return _fills(stored, incoming)


def _settlement_changes(stored: ShopeeOrderIncome | None, row: OrderSettlement) -> bool:
    if stored is None:
        return True
    if replaces(
        effective_rank(stored.source, stored.source_rank),
        effective_rank(row.source, row.source_rank),
    ):
        stated: dict[str, Any] = {name: getattr(row, name) for name in STATED_COLUMNS}
        stated.update({name: getattr(row, name) for name in _SETTLEMENT_PROVENANCE})
        return _differs(stored, stated)
    return _fills(stored, {name: getattr(row, name) for name in STATED_COLUMNS})


def _differs(stored: Any, stated: dict[str, Any]) -> bool:
    """A stated (non-null) value the stored row does not hold. A NULL never clears a stored
    value, so a NULL is never a change."""
    return any(
        value is not None and getattr(stored, name, None) != value for name, value in stated.items()
    )


def _fills(stored: Any, incoming: dict[str, Any]) -> bool:
    return any(
        getattr(stored, name, None) is None and value is not None
        for name, value in incoming.items()
        if name not in _SETTLEMENT_PROVENANCE
    )


__all__ = ["DbCanonicalWriter", "WriteResult", "line_values", "settlement_values"]
