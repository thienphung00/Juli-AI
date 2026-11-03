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
4. normalized rows are upserted into ``platform_daily_metrics`` -- or, for the
   ADR-117 period datasets, ``platform_period_metrics`` (+ ``platform_items``),
   ``platform_product_flags`` or ``platform_promotions`` -- a row is only replaced by
   a source of the same or higher rank (vendor < extension = file < api), and every
   row records the ``mapper_version`` that produced it;
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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import (
    DRIFT_DRIFT,
    ORDER_TYPE_NONE,
    SOURCE_CONFIDENCE,
    SOURCE_RANK,
    IngestDatasetStatus,
    IngestRawPayload,
    PlatformDailyMetric,
)
from juli_backend.models.platform_data import (
    ITEM_LEVEL_VARIATION,
    PlatformItem,
    PlatformPeriodMetric,
    PlatformProductFlag,
    PlatformPromotion,
)
from juli_backend.services.consent import ConsentRequired, require_consent
from juli_backend.services.ingest.mapping import (
    KPI_COLUMNS,
    MAPPER_VERSION,
    SHOPEE_PROMO_TYPES,
    WRITE_DAILY,
    WRITE_FLAGS,
    WRITE_ITEMS,
    WRITE_PERIOD,
    WRITE_PROMOTIONS,
    DatasetSpec,
    dataset_spec,
    effective_order_type,
    normalize_rows,
)
from juli_backend.services.ingest.schemas import (
    DatasetRow,
    IngestBody,
    RowBase,
    ShopeeItemBySourcePeriodRow,
    ShopeeItemCatalogRow,
    ShopeeProductFlagRow,
    ShopeeProductPeriodRow,
    ShopeePromotionRow,
    ShopeeVoucherSettingRow,
)
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
_PERIOD_KEY_COLUMNS = (
    "shop_id",
    "platform",
    "dataset",
    "period_start",
    "period_end",
    "item_id",
    "variation_id",
    "stream",
    "segment",
    "order_type",
)
_ITEM_KEY_COLUMNS = ("shop_id", "platform", "item_id", "variation_id")
_FLAG_KEY_COLUMNS = ("shop_id", "platform", "item_id", "period_start", "period_end", "flag")
_PROMOTION_KEY_COLUMNS = (
    "shop_id",
    "platform",
    "promo_type",
    "program_name",
    "starts_at",
    "ordinal",
    "period_start",
    "period_end",
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


def validate_rows(spec: DatasetSpec, body: IngestBody, now: datetime) -> list[DatasetRow]:
    """The validated rows, or ``IngestRejected`` naming what is wrong."""
    if body.period.granularity != spec.granularity:
        raise IngestRejected("granularity_mismatch")
    if spec.has_order_type and body.order_type is None:
        raise IngestRejected("order_type_required")
    if not spec.has_order_type and body.order_type is not None:
        raise IngestRejected("order_type_not_allowed")
    captured = body.captured_at.astimezone(UTC).replace(tzinfo=None)
    if captured > now + CLOCK_SKEW:
        raise IngestRejected("captured_at_in_future")
    if body.period.end > platform_today(now):
        raise IngestRejected("period_in_future")
    if (body.period.end - body.period.start).days + 1 > spec.max_period_days:
        raise IngestRejected("period_too_long")
    rows: list[DatasetRow] = []
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
        if isinstance(row, RowBase) and not body.period.start <= row.date <= body.period.end:
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


async def _upsert(
    session: AsyncSession,
    model: Any,
    key_columns: tuple[str, ...],
    values: list[dict[str, Any]],
) -> None:
    """Insert, or replace a row of the same or lower ``source_rank`` on the same key."""
    if not values:
        return
    insert = _insert(session)
    table = model.__table__
    for start in range(0, len(values), UPSERT_CHUNK):
        stmt = insert(model).values(values[start : start + UPSERT_CHUNK])
        updated = {
            column: stmt.excluded[column]
            for column in values[0]
            if column not in key_columns and column not in ("id", "created_at")
        }
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=list(key_columns),
                set_=updated,
                where=table.c.source_rank <= stmt.excluded.source_rank,
            )
        )


async def _upsert_metrics(session: AsyncSession, values: list[dict[str, Any]]) -> None:
    await _upsert(session, PlatformDailyMetric, _KEY_COLUMNS, values)


async def _upsert_items(session: AsyncSession, values: list[dict[str, Any]]) -> None:
    """``platform_items``: names / SKU / status from the newest post; the seen range widens."""
    if not values:
        return
    insert = _insert(session)
    table = PlatformItem.__table__
    postgres = session.get_bind().dialect.name == "postgresql"
    least, greatest = (func.least, func.greatest) if postgres else (func.min, func.max)
    for start in range(0, len(values), UPSERT_CHUNK):
        stmt = insert(PlatformItem).values(values[start : start + UPSERT_CHUNK])
        updated: dict[str, Any] = {
            column: func.coalesce(stmt.excluded[column], table.c[column])
            for column in ("name", "variation_name", "seller_sku", "status")
        }
        updated.update(
            {
                column: stmt.excluded[column]
                for column in (
                    "source",
                    "source_rank",
                    "source_version",
                    "mapper_version",
                    "raw_payload_id",
                    "captured_at",
                    "updated_at",
                )
            }
        )
        updated["first_seen_on"] = least(table.c.first_seen_on, stmt.excluded.first_seen_on)
        updated["last_seen_on"] = greatest(table.c.last_seen_on, stmt.excluded.last_seen_on)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=list(_ITEM_KEY_COLUMNS),
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


def _metric_values(
    spec: DatasetSpec,
    rows: list[DatasetRow],
    body: IngestBody,
    order_type: str,
    provenance: dict[str, Any],
) -> list[dict[str, Any]]:
    values = []
    period = spec.writes == WRITE_PERIOD
    for row in normalize_rows(spec, rows):
        value: dict[str, Any] = {
            "id": uuid.uuid4(),
            **provenance,
            "dataset": spec.name,
            "item_id": row.item_id,
            "stream": row.stream,
            "segment": row.segment,
            "order_type": order_type,
            "platform_source": row.platform_source,
            "extra": row.extra,
            "confidence": SOURCE_CONFIDENCE[body.source],
        }
        if period:
            value.update(
                period_start=body.period.start,
                period_end=body.period.end,
                variation_id=row.variation_id,
            )
        else:
            value["day"] = row.day
        # Every KPI column on every row, so a later post can clear a value.
        value.update({column: row.kpis.get(column) for column in KPI_COLUMNS})
        values.append(value)
    return values


def _item_values(
    rows: list[DatasetRow], body: IngestBody, provenance: dict[str, Any]
) -> list[dict[str, Any]]:
    """One ``platform_items`` row per item / variation the period rows describe."""
    items: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, ShopeeProductPeriodRow):
            variation, name, sku, status = (
                row.variation_id,
                row.variation_name,
                row.seller_sku,
                row.variation_status if row.variation_id else row.item_status,
            )
            item_name = row.item_name
        elif isinstance(row, ShopeeItemBySourcePeriodRow):
            variation, name, sku, status = ITEM_LEVEL_VARIATION, None, None, row.item_status
            item_name = row.item_name
        elif isinstance(row, ShopeeItemCatalogRow):
            variation, name, sku, status = (
                row.variation_id,
                row.variation_name,
                row.seller_sku,
                row.status,
            )
            item_name = row.item_name
        else:
            continue
        items[(row.item_id, variation)] = {
            "id": uuid.uuid4(),
            **provenance,
            "item_id": row.item_id,
            "variation_id": variation,
            "name": item_name,
            "variation_name": name,
            "seller_sku": sku,
            "status": status,
            "first_seen_on": body.period.start,
            "last_seen_on": body.period.end,
            "extra": {},
        }
    return list(items.values())


def _promotion_extra(row: ShopeePromotionRow) -> dict[str, Any]:
    extra: dict[str, Any] = dict(row.extra)
    if row.sales_per_buyer is not None:
        extra["sales_per_buyer"] = float(row.sales_per_buyer)
    return extra


def _voucher_extra(row: ShopeeVoucherSettingRow) -> dict[str, Any]:
    """The voucher's numbers and flags (D16: no string reaches ``extra``; the code stays in
    the raw copy)."""
    extra: dict[str, Any] = {"voucher_id": int(row.voucher_id)}
    for name in (
        "discount_amount",
        "discount_percent",
        "max_value",
        "min_spend",
        "usage_limit",
        "current_usage",
        "distributed_count",
        "usage_limit_per_user",
        "item_count",
    ):
        value = getattr(row, name)
        if value is not None:
            extra[name] = float(value) if value != value.to_integral_value() else int(value)
    for name in ("use_type", "reward_type", "purpose", "is_seller_absorbed"):
        value = getattr(row, name)
        if value is not None:
            extra[name] = value
    return extra


def _voucher_values(
    rows: list[ShopeeVoucherSettingRow], body: IngestBody, provenance: dict[str, Any]
) -> list[dict[str, Any]]:
    """``platform_promotions`` rows for voucher settings. Twins (same name and start) get an
    ``ordinal`` by voucher id, so the key is stable between snapshots."""
    ordinals: dict[tuple[str, datetime], int] = {}
    values = []
    for row in sorted(rows, key=lambda r: int(r.voucher_id)):
        starts_at = row.starts_at.replace(tzinfo=None)
        twin = (row.program_name, starts_at)
        ordinal = ordinals.get(twin, 0)
        ordinals[twin] = ordinal + 1
        values.append(
            {
                "id": uuid.uuid4(),
                **provenance,
                "promo_type": SHOPEE_PROMO_TYPES["Voucher"],
                "program_name": row.program_name,
                "starts_at": starts_at,
                "ends_at": row.ends_at.replace(tzinfo=None) if row.ends_at else None,
                "ordinal": ordinal,
                "period_start": body.period.start,
                "period_end": body.period.end,
                "status": row.status,
                "order_type": ORDER_TYPE_NONE,
                "gmv": None,
                "orders": None,
                "units": None,
                "buyers": None,
                "extra": _voucher_extra(row),
            }
        )
    return values


async def _write(
    session: AsyncSession,
    spec: DatasetSpec,
    rows: list[DatasetRow],
    body: IngestBody,
    order_type: str,
    provenance: dict[str, Any],
) -> None:
    if spec.writes == WRITE_DAILY:
        await _upsert_metrics(session, _metric_values(spec, rows, body, order_type, provenance))
    elif spec.writes == WRITE_PERIOD:
        await _upsert(
            session,
            PlatformPeriodMetric,
            _PERIOD_KEY_COLUMNS,
            _metric_values(spec, rows, body, order_type, provenance),
        )
        await _upsert_items(session, _item_values(rows, body, provenance))
    elif spec.writes == WRITE_ITEMS:
        await _upsert_items(session, _item_values(rows, body, provenance))
    elif spec.writes == WRITE_FLAGS:
        flags = [
            {
                "id": uuid.uuid4(),
                **provenance,
                "item_id": row.item_id,
                "period_start": body.period.start,
                "period_end": body.period.end,
                "flag": row.flag,
                "extra": dict(row.extra),
            }
            for row in rows
            if isinstance(row, ShopeeProductFlagRow)
        ]
        await _upsert(session, PlatformProductFlag, _FLAG_KEY_COLUMNS, flags)
    elif spec.writes == WRITE_PROMOTIONS:
        promotions = [
            {
                "id": uuid.uuid4(),
                **provenance,
                "promo_type": SHOPEE_PROMO_TYPES[row.promo_type],
                "program_name": row.program_name,
                "starts_at": row.starts_at.replace(tzinfo=None),
                "ends_at": row.ends_at.replace(tzinfo=None) if row.ends_at else None,
                "ordinal": row.ordinal,
                "period_start": body.period.start,
                "period_end": body.period.end,
                "status": row.status,
                "order_type": order_type,
                "gmv": row.sales,
                "orders": row.orders,
                "units": row.units,
                "buyers": row.buyers,
                "extra": _promotion_extra(row),
            }
            for row in rows
            if isinstance(row, ShopeePromotionRow)
        ]
        promotions += _voucher_values(
            [row for row in rows if isinstance(row, ShopeeVoucherSettingRow)], body, provenance
        )
        await _upsert(session, PlatformPromotion, _PROMOTION_KEY_COLUMNS, promotions)
    else:
        raise ValueError(f"unknown write target {spec.writes}")


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
    if not duplicate:
        provenance: dict[str, Any] = {
            "shop_id": shop_id,
            "platform": platform,
            "source": body.source,
            "source_rank": SOURCE_RANK[body.source],
            "source_version": body.source_version,
            "mapper_version": MAPPER_VERSION,
            "raw_payload_id": raw_id,
            "captured_at": body.captured_at.astimezone(UTC).replace(tzinfo=None),
            "updated_at": now,
        }
        await _write(session, spec, rows, body, order_type, provenance)
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
            "rows": len(rows),
            "duplicate": duplicate,
            "content_hash": hashed[:16],
            "token_id": str(token_id) if token_id else None,
            "raw_payload_id": str(raw_id),
        },
    )
    return IngestResult(
        raw_payload_id=raw_id, duplicate=duplicate, rows=len(rows), content_hash=hashed
    )
