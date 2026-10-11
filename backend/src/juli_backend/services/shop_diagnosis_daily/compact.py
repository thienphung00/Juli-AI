"""The compact daily tables behind Ops "Mô phỏng" (fast track P18, D27.2).

When the diagnosis report is built, its per-day stream counts
(``report.daily_streams``) and per-product counts (``report.daily_products``)
are upserted one row per shop × stream × day (``shop_daily_streams``) and per
shop × stream × product × day (``shop_daily_products``, with the row's title
and seller SKU). The simulation reads these instead of merging every stored
report's JSON (``services/ops/simulation.py::load_history``).

Newer wins: reports are applied oldest first, and an upsert replaces a stored
day. Rows are never deleted -- the history keeps growing past the report's 60
days as the daily job runs. Every read and write runs under the caller's shop
scope (RLS, migration 085).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_diagnosis import (
    DAILY_STREAMS,
    ShopDailyProduct,
    ShopDailyStream,
    ShopDiagnosisReport,
)
from juli_backend.repositories._base import utc_now_naive

#: Rows per INSERT statement (well under Postgres' and SQLite's bind limits).
CHUNK = 500
_COUNT_COLUMNS = ("impressions", "clicks", "orders", "gmv")

Counts = tuple[Decimal, Decimal, Decimal | None, Decimal]


def _day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> Decimal:
    return Decimal(str(round(float(value or 0), 2)))


def _counts(row: Any) -> Counts | None:
    if not isinstance(row, list | tuple) or len(row) < 4:
        return None
    impressions, clicks, orders, gmv = row[:4]
    try:
        return (
            _num(impressions),
            _num(clicks),
            None if orders is None else _num(orders),
            _num(gmv),
        )
    except (TypeError, ValueError, ArithmeticError):
        return None


def collect(
    reports: Iterable[Mapping[str, Any]],
) -> tuple[
    dict[tuple[str, date], Counts],
    dict[tuple[str, str, date], Counts],
    dict[str, str],
    dict[str, str],
]:
    """Stream days, product days, titles and seller SKUs of ``reports`` (oldest first)."""
    streams: dict[tuple[str, date], Counts] = {}
    products: dict[tuple[str, str, date], Counts] = {}
    titles: dict[str, str] = {}
    skus: dict[str, str] = {}
    for report in reports:
        for stream, by_day in (report.get("daily_streams") or {}).items():
            if stream not in DAILY_STREAMS or not isinstance(by_day, Mapping):
                continue
            for raw, row in by_day.items():
                day, counts = _day(raw), _counts(row)
                if day is not None and counts is not None:
                    streams[(stream, day)] = counts
        for stream, by_product in (report.get("daily_products") or {}).items():
            if stream not in DAILY_STREAMS or not isinstance(by_product, Mapping):
                continue
            for pid, by_day in by_product.items():
                if not isinstance(by_day, Mapping):
                    continue
                for raw, row in by_day.items():
                    day, counts = _day(raw), _counts(row)
                    if day is not None and counts is not None:
                        products[(stream, str(pid)[:100], day)] = counts
        titles.update({str(k): str(v) for k, v in (report.get("titles") or {}).items() if v})
        skus.update({str(k): str(v) for k, v in (report.get("seller_skus") or {}).items() if v})
    return streams, products, titles, skus


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


async def _upsert(
    session: AsyncSession,
    model: type[ShopDailyStream] | type[ShopDailyProduct],
    keys: Sequence[str],
    rows: list[dict[str, Any]],
) -> None:
    insert = _insert(session)
    for start in range(0, len(rows), CHUNK):
        stmt = insert(model).values(rows[start : start + CHUNK])
        updated = {c: stmt.excluded[c] for c in rows[0] if c not in keys}
        await session.execute(stmt.on_conflict_do_update(index_elements=list(keys), set_=updated))


async def write_report_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    reports: Iterable[Mapping[str, Any]],
    *,
    written_at: datetime | None = None,
) -> int:
    """Upsert every day of ``reports`` (oldest first) for the shop; returns rows written."""
    streams, products, titles, skus = collect(reports)
    moment = written_at or utc_now_naive()
    stream_rows = [
        {
            "shop_id": shop_id,
            "stream": stream,
            "day": day,
            **dict(zip(_COUNT_COLUMNS, counts, strict=True)),
            "updated_at": moment,
        }
        for (stream, day), counts in sorted(streams.items())
    ]
    product_rows = [
        {
            "shop_id": shop_id,
            "stream": stream,
            "product_id": pid,
            "day": day,
            **dict(zip(_COUNT_COLUMNS, counts, strict=True)),
            "title": titles[pid][:500] if pid in titles else None,
            "seller_sku": skus[pid][:200] if pid in skus else None,
            "updated_at": moment,
        }
        for (stream, pid, day), counts in sorted(products.items())
    ]
    if stream_rows:
        await _upsert(session, ShopDailyStream, ("shop_id", "stream", "day"), stream_rows)
    if product_rows:
        await _upsert(
            session, ShopDailyProduct, ("shop_id", "stream", "product_id", "day"), product_rows
        )
    await session.flush()
    return len(stream_rows) + len(product_rows)


async def rebuild_from_stored_reports(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    since: date | None = None,
    latest_only: bool = False,
    written_at: datetime | None = None,
) -> int:
    """Re-derive the compact rows from the shop's stored report JSON.

    ``latest_only``: only the newest end date's reports ("Làm mới"); otherwise
    every report ending on or after ``since``, oldest first (the one-time fill
    for a shop whose reports predate migration 085).
    """
    stmt = select(ShopDiagnosisReport.report, ShopDiagnosisReport.end_date).where(
        ShopDiagnosisReport.shop_id == shop_id
    )
    if since is not None:
        stmt = stmt.where(ShopDiagnosisReport.end_date >= since)
    stmt = stmt.order_by(ShopDiagnosisReport.end_date.asc(), ShopDiagnosisReport.built_at.asc())
    rows = (await session.execute(stmt)).all()
    if latest_only and rows:
        last = rows[-1][1]
        rows = [r for r in rows if r[1] == last]
    reports = [r[0] for r in rows if isinstance(r[0], Mapping)]
    if not reports:
        return 0
    return await write_report_days(session, shop_id, reports, written_at=written_at)
