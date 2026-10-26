"""The ingest gateway (D31.3): validate, keep the raw body, upsert the normalized days.

One call = one POST of one dataset for one shop. In order:

0. the shop must hold an open ``service`` consent (ADR-116 §4, D8) -- otherwise
   ``consent_required`` (403) and nothing is stored;
1. the dataset must exist for the platform; rows are validated strictly against
   its row model; the period, the rows' dates, the order type and duplicate
   keys are checked (``IngestRejected`` → 422 with the first errors);
2. a dataset the extension reported as drifted is refused for the SAME
   ``source_version`` (409) until a new version posts or the drift is cleared;
3. the body is stored append-only in ``ingest_raw_payloads`` -- reduced to the
   dataset's field allowlist (``services/privacy/payload_allowlist.py``) --
   deduplicated on a content hash of (platform, dataset, period, order type, rows) -- a re-post of
   the same data, at any ``captured_at``, changes nothing and answers
   ``duplicate: true``;
4. normalized rows are upserted into ``platform_daily_metrics`` -- a row is only
   replaced by a source of the same or higher rank (vendor < extension = file <
   api);
5. ``ingest_dataset_status`` records the last ingest; one ``ingest_accepted``
   log line is the audit record.

The caller holds the shop's tenant scope; nothing here commits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import (
    DRIFT_DRIFT,
    SOURCE_CONFIDENCE,
    SOURCE_RANK,
    IngestDatasetStatus,
    IngestRawPayload,
    PlatformDailyMetric,
)
from juli_backend.services.consent import ConsentRequired, require_consent
from juli_backend.services.ingest.mapping import (
    KPI_COLUMNS,
    DatasetSpec,
    dataset_spec,
    effective_order_type,
    normalize_rows,
)
from juli_backend.services.ingest.schemas import IngestBody, RowBase
from juli_backend.services.privacy.payload_allowlist import allowlist_payload, ingest_endpoint

logger = logging.getLogger(__name__)

#: Seller Centre's calendar (Shopee VN) is GMT+7.
PLATFORM_UTC_OFFSET = timedelta(hours=7)
#: A ``captured_at`` this far in the future is a broken clock, not data.
CLOCK_SKEW = timedelta(minutes=10)
MAX_REPORTED_ERRORS = 20
UPSERT_CHUNK = 500

_KEY_COLUMNS = (
    "shop_id",
    "platform",
    "dataset",
    "day",
    "item_id",
    "stream",
    "segment",
    "order_type",
)


class IngestRejected(Exception):
    def __init__(self, code: str, errors: list[dict[str, Any]] | None = None, status: int = 422):
        super().__init__(code)
        self.code = code
        self.errors = errors or []
        self.status = status


@dataclass(frozen=True)
class IngestResult:
    raw_payload_id: uuid.UUID
    duplicate: bool
    rows: int
    content_hash: str

    def to_json(self) -> dict[str, Any]:
        return {
            "raw_payload_id": str(self.raw_payload_id),
            "duplicate": self.duplicate,
            "rows": self.rows,
            "content_hash": self.content_hash,
        }


def platform_today(now: datetime) -> date:
    """``now`` (naive UTC) as the platform's calendar day."""
    return (now + PLATFORM_UTC_OFFSET).date()


def content_hash(platform: str, dataset: str, body: IngestBody) -> str:
    canonical = json.dumps(
        {
            "platform": platform,
            "dataset": dataset,
            "period": body.period.model_dump(mode="json"),
            "order_type": body.order_type,
            "rows": body.rows,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _errors(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors(include_url=False, include_input=False)[:MAX_REPORTED_ERRORS]
    ]


def validate_rows(spec: DatasetSpec, body: IngestBody, now: datetime) -> list[RowBase]:
    """The validated rows, or ``IngestRejected`` naming what is wrong."""
    if spec.has_order_type and body.order_type is None:
        raise IngestRejected("order_type_required")
    if not spec.has_order_type and body.order_type is not None:
        raise IngestRejected("order_type_not_allowed")
    captured = body.captured_at.astimezone(UTC).replace(tzinfo=None)
    if captured > now + CLOCK_SKEW:
        raise IngestRejected("captured_at_in_future")
    if body.period.end > platform_today(now):
        raise IngestRejected("period_in_future")
    rows: list[RowBase] = []
    problems: list[dict[str, Any]] = []
    for index, raw in enumerate(body.rows):
        try:
            rows.append(spec.row_model.model_validate(raw))
        except ValidationError as exc:
            problems.extend({**err, "loc": ["rows", index, *err["loc"]]} for err in _errors(exc))
        if len(problems) >= MAX_REPORTED_ERRORS:
            raise IngestRejected("invalid_rows", problems[:MAX_REPORTED_ERRORS])
    if problems:
        raise IngestRejected("invalid_rows", problems)
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows):
        if not body.period.start <= row.date <= body.period.end:
            problems.append({"loc": ["rows", index, "date"], "msg": "date outside period"})
        key = row.key()
        if key in seen:
            problems.append({"loc": ["rows", index], "msg": "duplicate row key"})
        seen.add(key)
        if len(problems) >= MAX_REPORTED_ERRORS:
            break
    if problems:
        raise IngestRejected("invalid_rows", problems)
    return rows


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


async def _store_raw(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    dataset: str,
    body: IngestBody,
    order_type: str,
    hashed: str,
    token_id: uuid.UUID | None,
    now: datetime,
) -> tuple[uuid.UUID, bool]:
    """(raw id, duplicate). A concurrent identical post resolves to the first row."""
    insert = _insert(session)
    raw_id = uuid.uuid4()
    stmt = (
        insert(IngestRawPayload)
        .values(
            id=raw_id,
            shop_id=shop_id,
            platform=platform,
            dataset=dataset,
            source=body.source,
            source_version=body.source_version,
            captured_at=body.captured_at.astimezone(UTC).replace(tzinfo=None),
            received_at=now,
            period_start=body.period.start,
            period_end=body.period.end,
            granularity=body.period.granularity,
            order_type=order_type,
            content_hash=hashed,
            row_count=len(body.rows),
            token_id=token_id,
            payload=allowlist_payload(
                platform, ingest_endpoint(dataset), body.model_dump(mode="json")
            ),
        )
        .on_conflict_do_nothing(index_elements=["shop_id", "content_hash"])
        .returning(IngestRawPayload.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    if inserted is not None:
        return inserted, False
    existing = (
        await session.execute(
            select(IngestRawPayload.id).where(
                IngestRawPayload.shop_id == shop_id, IngestRawPayload.content_hash == hashed
            )
        )
    ).scalar_one()
    return existing, True


async def _upsert_metrics(session: AsyncSession, values: list[dict[str, Any]]) -> None:
    if not values:
        return
    insert = _insert(session)
    table = PlatformDailyMetric.__table__
    for start in range(0, len(values), UPSERT_CHUNK):
        stmt = insert(PlatformDailyMetric).values(values[start : start + UPSERT_CHUNK])
        updated = {
            column: stmt.excluded[column]
            for column in values[0]
            if column not in _KEY_COLUMNS and column not in ("id", "created_at")
        }
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=list(_KEY_COLUMNS),
                set_=updated,
                where=table.c.source_rank <= stmt.excluded.source_rank,
            )
        )


async def _record_status(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    dataset: str,
    body: IngestBody,
    raw_id: uuid.UUID,
    now: datetime,
) -> None:
    insert = _insert(session)
    values = {
        "last_ingest_at": now,
        "last_captured_at": body.captured_at.astimezone(UTC).replace(tzinfo=None),
        "last_period_start": body.period.start,
        "last_period_end": body.period.end,
        "last_row_count": len(body.rows),
        "last_source": body.source,
        "last_source_version": body.source_version,
        "last_raw_payload_id": raw_id,
        "updated_at": now,
    }
    stmt = insert(IngestDatasetStatus).values(
        id=uuid.uuid4(), shop_id=shop_id, platform=platform, dataset=dataset, **values
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["shop_id", "platform", "dataset"],
            set_={k: stmt.excluded[k] for k in values},
        )
    )


async def ingest(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    dataset: str,
    body: IngestBody,
    token_id: uuid.UUID | None,
    now: datetime,
) -> IngestResult:
    try:
        await require_consent(session, shop_id, "service")
    except ConsentRequired:
        raise IngestRejected("consent_required", status=403) from None
    spec = dataset_spec(platform, dataset)
    if spec is None:
        raise IngestRejected("unknown_dataset", status=404)
    rows = validate_rows(spec, body, now)
    order_type = effective_order_type(spec, body.order_type)

    status = (
        await session.execute(
            select(IngestDatasetStatus).where(
                IngestDatasetStatus.shop_id == shop_id,
                IngestDatasetStatus.platform == platform,
                IngestDatasetStatus.dataset == dataset,
            )
        )
    ).scalar_one_or_none()
    if (
        status is not None
        and status.drift_state == DRIFT_DRIFT
        and status.drift_source_version == body.source_version
    ):
        raise IngestRejected("dataset_in_drift", status=409)

    hashed = content_hash(platform, dataset, body)
    raw_id, duplicate = await _store_raw(
        session,
        shop_id=shop_id,
        platform=platform,
        dataset=dataset,
        body=body,
        order_type=order_type,
        hashed=hashed,
        token_id=token_id,
        now=now,
    )
    normalized = normalize_rows(spec, rows)
    if not duplicate:
        captured = body.captured_at.astimezone(UTC).replace(tzinfo=None)
        values = []
        for row in normalized:
            value: dict[str, Any] = {
                "id": uuid.uuid4(),
                "shop_id": shop_id,
                "platform": platform,
                "dataset": dataset,
                "day": row.day,
                "item_id": row.item_id,
                "stream": row.stream,
                "segment": row.segment,
                "order_type": order_type,
                "platform_source": row.platform_source,
                "extra": row.extra,
                "source": body.source,
                "source_rank": SOURCE_RANK[body.source],
                "source_version": body.source_version,
                "confidence": SOURCE_CONFIDENCE[body.source],
                "raw_payload_id": raw_id,
                "captured_at": captured,
                "updated_at": now,
            }
            # Every KPI column on every row, so a later post can clear a value.
            value.update({column: row.kpis.get(column) for column in KPI_COLUMNS})
            values.append(value)
        await _upsert_metrics(session, values)
    await _record_status(
        session,
        shop_id=shop_id,
        platform=platform,
        dataset=dataset,
        body=body,
        raw_id=raw_id,
        now=now,
    )
    logger.info(
        "ingest_accepted",
        extra={
            "shop_id": str(shop_id),
            "platform": platform,
            "dataset": dataset,
            "source": body.source,
            "source_version": body.source_version,
            "order_type": order_type,
            "period_start": body.period.start.isoformat(),
            "period_end": body.period.end.isoformat(),
            "rows": len(normalized),
            "duplicate": duplicate,
            "content_hash": hashed[:16],
            "token_id": str(token_id) if token_id else None,
            "raw_payload_id": str(raw_id),
        },
    )
    return IngestResult(
        raw_payload_id=raw_id, duplicate=duplicate, rows=len(normalized), content_hash=hashed
    )
