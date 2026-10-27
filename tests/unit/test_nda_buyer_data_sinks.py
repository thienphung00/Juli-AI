"""Buyer data never reaches a sink: each persistence path, fed a stuffed payload (D16).

Owner decision D16 (2026-10-27; ADR-116 §4, fast track D76): buyer personal data
from TikTok Shop API responses and webhooks is filtered IN MEMORY before ANY
persistence. Every test below feeds one synthetic payload stuffed with buyer fields
(e-mail, message, name, nickname, avatar, phone, address, raw ``buyer_id`` /
``user_id``, free text) into one sink and reads back what the sink kept:

- ``workflow_webhook_signals.payload`` (``DatabaseWebhookSideEffects``);
- ``webhook_raw_events.raw_body`` / ``event_id`` (``DatabaseRawWebhookEventRecorder``),
  authenticated (``buyer_id`` pseudonymised) and not (dropped);
- the ETL DLQ envelope and its ``etl_dlq`` log line;
- ``shop_ingestion_state.last_error`` and ``tiktok_sync_state.last_error``;
- the shop diagnosis snapshot's ``orders.json`` (temp dir or ``~/.juli-shop-snapshots``);
- the Connector ingest row's ``extra`` (and its raw copy);
- the exception texts those columns are built from (``TikTokSchemaError``, a
  SQLAlchemy error under ``hide_parameters``);
- the operator clean-up of rows stored before all this.

SQLite schema. The Postgres twin (``juli_app`` role, RLS, the owner clean-up) is
``tests/integration/test_nda_buyer_data_db.py``; the static guard against new raw
stores is ``tests/unit/test_no_raw_buyer_stores.py``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.core.privacy import error_label, relabel_stored_error
from juli_backend.database.database import create_engine
from juli_backend.integrations.tiktok import TikTokAPIError
from juli_backend.integrations.tiktok.schemas import TikTokSchemaError, validate_data
from juli_backend.models.ingest import IngestRawPayload, PlatformDailyMetric
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import (
    TikTokSyncState,
    WebhookRawEvent,
    WorkflowWebhookSignal,
)
from juli_backend.repositories import ShopIngestionStateRepo, TikTokSyncStateRepo
from juli_backend.services import ingest as ingest_service
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.privacy.payload_allowlist import (
    FORBIDDEN_FRAGMENT_EXCEPTIONS,
    FORBIDDEN_KEY_FRAGMENTS,
)
from juli_backend.services.privacy.payload_cleanup import (
    clean_raw_events,
    clean_shop,
    scrub_event_id,
)
from juli_backend.services.privacy.pseudonym import buyer_pseudonym, shop_pseudonym_key
from juli_backend.services.shop_diagnosis_daily.fetch import fetch_orders
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from juli_backend.services.tiktok.webhook_raw_log import DatabaseRawWebhookEventRecorder
from juli_backend.workers.services.polling import ingestion as ingestion_module
from juli_backend.workers.services.polling.sync import _StepRun
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

MARK = "NDA_BUYER"
RAW_BUYER = "7494011223344556677"
TIKTOK_SHOP = "7000000000000016"
NOW = datetime(2026, 10, 27, 3, 0)
DAY = date(2026, 10, 26)


def _buyer_fields() -> dict[str, Any]:
    """Every kind of buyer field D16 names, each value carrying ``MARK``."""
    return {
        "buyer_email": f"{MARK}@example.invalid",
        "buyer_message": f"{MARK} please call before delivery",
        "buyer_nickname": f"{MARK}_nick",
        "buyer_avatar": f"https://example.invalid/{MARK}.png",
        "buyer_name": f"{MARK} Nguyen Van A",
        "user_id": f"{RAW_BUYER}",
        "note": f"{MARK} seller note",
        "comment": f"{MARK} free text",
        "reason": f"{MARK} free text reason",
        "recipient_address": {
            "name": f"{MARK} Nguyen Van A",
            "phone_number": f"{MARK} (+84)900000000",
            "full_address": f"{MARK} 12 Ly Thuong Kiet, Ha Noi",
            "region_code": f"{MARK}_VN",
            "district_info": [{"address_name": f"{MARK} Hoan Kiem"}],
        },
    }


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for child in value.values():
            found |= _keys(child)
        return found
    if isinstance(value, list):
        out: set[str] = set()
        for item in value:
            out |= _keys(item)
        return out
    return set()


def _assert_clean(stored: Any) -> None:
    """No marker, no raw buyer id, no buyer-shaped key -- at any depth."""
    rendered = stored if isinstance(stored, str) else json.dumps(stored, ensure_ascii=False)
    assert MARK not in rendered, rendered
    assert RAW_BUYER not in rendered, rendered
    parsed = stored
    if isinstance(stored, str):
        try:
            parsed = json.loads(stored)
        except ValueError:
            return
    for key in _keys(parsed):
        if key in FORBIDDEN_FRAGMENT_EXCEPTIONS:
            continue
        assert not any(f in key.lower() for f in FORBIDDEN_KEY_FRAGMENTS), key


def _order_webhook(**data: Any) -> dict[str, Any]:
    return {
        "type": "ORDER_STATUS_CHANGE",
        "shop_id": TIKTOK_SHOP,
        "timestamp": 1761530000,
        "tts_notification_id": "ttsn-1",
        "data": {
            "order_id": "576461413038785752",
            "order_status": "AWAITING_SHIPMENT",
            "update_time": 1761530000,
            "buyer_id": RAW_BUYER,
            **_buyer_fields(),
            **data,
        },
    }


# -- workflow_webhook_signals.payload ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_webhook_signal_stores_listed_ids_and_the_pseudonym_only(session):
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    event = TikTokWebhookPayload.from_dict(_order_webhook())
    entry = resolve_catalog_entry(event.type)
    assert entry is not None

    await DatabaseWebhookSideEffects(session).on_catalog_event(entry=entry, event=event)

    signal = (await session.execute(select(WorkflowWebhookSignal))).scalar_one()
    _assert_clean(signal.payload)
    _assert_clean(signal.event_id)
    stored = json.loads(signal.payload or "{}")
    key = await shop_pseudonym_key(session, shop.id)
    assert stored["data"] == {
        "order_id": "576461413038785752",
        "order_status": "AWAITING_SHIPMENT",
        "update_time": 1761530000,
        "buyer_id": buyer_pseudonym(key, RAW_BUYER),
    }
    assert stored["type"] == "ORDER_STATUS_CHANGE" and stored["shop_id"] == TIKTOK_SHOP
    assert stored["timestamp"] == 1761530000 and stored["tts_notification_id"] == "ttsn-1"


@pytest.mark.asyncio
async def test_a_signal_without_a_known_id_keys_its_event_id_on_the_reduced_data(session):
    """``extract_event_id`` falls back to the whole ``data``: it must be the reduced one."""
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    event = TikTokWebhookPayload.from_dict(
        {
            "type": "UPCOMING_AUTHORIZATION_EXPIRATION",
            "shop_id": TIKTOK_SHOP,
            "timestamp": 1,
            "data": {"expiration_time": 1762000000, **_buyer_fields()},
        }
    )
    entry = resolve_catalog_entry(event.type)
    assert entry is not None

    await DatabaseWebhookSideEffects(session).on_catalog_event(entry=entry, event=event)

    signal = (await session.execute(select(WorkflowWebhookSignal))).scalar_one()
    _assert_clean(signal.payload)
    _assert_clean(signal.event_id)
    assert '"expiration_time": 1762000000' in signal.event_id
    assert shop.id == signal.shop_id


# -- webhook_raw_events.raw_body ------------------------------------------------------------


async def _record(session, body: dict[str, Any], *, http_status: int) -> WebhookRawEvent:
    await DatabaseRawWebhookEventRecorder(session).record(
        body=json.dumps(body).encode(),
        signature="sig",
        http_status=http_status,
        processing_status="order_status_change" if http_status == 200 else "invalid_signature",
        event=None,
        headers={"Content-Type": "application/json", "X-Buyer": MARK},
    )
    rows = (await session.execute(select(WebhookRawEvent))).scalars().all()
    return rows[-1]


@pytest.mark.asyncio
async def test_an_authenticated_raw_event_stores_the_shops_pseudonym(session):
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)

    row = await _record(session, _order_webhook(), http_status=200)

    _assert_clean(row.raw_body)
    _assert_clean(row.headers)
    _assert_clean(row.event_id or "")
    key = await shop_pseudonym_key(session, shop.id)
    stored = json.loads(row.raw_body or "{}")
    assert stored["data"]["buyer_id"] == buyer_pseudonym(key, RAW_BUYER)
    assert stored["data"]["order_id"] == "576461413038785752"


@pytest.mark.asyncio
async def test_an_unauthenticated_or_unknown_shop_raw_event_drops_the_buyer_id(session):
    await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    unsigned = await _record(session, _order_webhook(), http_status=401)
    unknown = await _record(
        session, {**_order_webhook(), "shop_id": "7999999999999999"}, http_status=200
    )

    for row in (unsigned, unknown):
        _assert_clean(row.raw_body)
        assert "buyer_id" not in json.loads(row.raw_body or "{}")["data"]


@pytest.mark.asyncio
async def test_a_deferred_message_webhook_keeps_the_envelope_only(session):
    row = await _record(
        session,
        {
            "type": "NEW_MESSAGE",
            "shop_id": TIKTOK_SHOP,
            "timestamp": 2,
            "data": {"conversation_id": "c1", "content": f"{MARK} hello", **_buyer_fields()},
        },
        http_status=200,
    )

    _assert_clean(row.raw_body)
    _assert_clean(row.event_id or "")
    assert json.loads(row.raw_body or "{}") == {
        "type": "NEW_MESSAGE",
        "shop_id": TIKTOK_SHOP,
        "timestamp": 2,
    }


# -- the ETL DLQ envelope and its log line ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("known_shop", [True, False])
async def test_a_dlq_envelope_and_log_carry_no_payload(session, caplog, known_shop):
    await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    sent: list[dict[str, Any]] = []

    async def dlq(channel: str, shop_key: str, value: bytes) -> None:
        sent.append(json.loads(value))

    payload = {
        "order_id": "o-1",
        "update_time": f"{MARK} not a time",
        "buyer_id": RAW_BUYER,
        **_buyer_fields(),
    }
    consumer = EtlConsumer(session=session, dlq_handoff=dlq)
    caplog.set_level(logging.WARNING)
    outcome = await consumer.ingest(
        IngestRecord(
            channel="tiktok.orders.raw",
            shop_key=TIKTOK_SHOP if known_shop else "7999999999999999",
            value=json.dumps(payload).encode(),
        )
    )

    assert outcome == ProcessOutcome.DLQ
    (envelope,) = sent
    assert set(envelope) == {"original_channel", "shop_key", "error"}
    _assert_clean(envelope)
    for record in caplog.records:
        _assert_clean(record.getMessage())
        _assert_clean(str(getattr(record, "error", "")))
    if known_shop:
        assert envelope["error"] == "ValueError: invalid datetime"  # TransformError


# -- last_error columns ------------------------------------------------------------------------


def _leaky_errors() -> list[BaseException]:
    class _Order(BaseModel):
        id: int

    try:
        validate_data(_Order, {"id": f"{MARK} {RAW_BUYER}", **_buyer_fields()})
    except TikTokSchemaError as exc:
        schema_error = exc
    return [
        TikTokAPIError(code=105001, message=f"{MARK} echo of buyer_email", request_id="r1"),
        ValueError(f"{MARK} Nguyen Van A, (+84)900000000"),
        schema_error,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1, 2])
async def test_shop_ingestion_state_last_error_is_a_label(session, index):
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    error = _leaky_errors()[index]
    run = SimpleNamespace(
        session=session, state_repo=ShopIngestionStateRepo(session), shop_id=shop.id
    )

    await ingestion_module._mark_failed(run, phase="fast", error=error)

    state = await session.get(ShopIngestionState, shop.id)
    assert state is not None and state.status == "failed"
    _assert_clean(state.last_error or "")
    assert state.last_error == error_label(error)


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1, 2])
async def test_tiktok_sync_state_last_error_is_a_label(session, index):
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    error = _leaky_errors()[index]
    step = _StepRun("orders", str(shop.id), backfill=False, handoff_fn=_never)

    outcome = step.outcome(error=error)
    await TikTokSyncStateRepo(session).record_outcomes(shop.id, [outcome])

    row = (await session.execute(select(TikTokSyncState))).scalar_one()
    _assert_clean(row.last_error or "")
    assert row.last_error == error_label(error)


async def _never(channel: str, shop_key: str, value: bytes) -> None:
    raise AssertionError("no handoff expected")


def test_error_label_keeps_class_and_numeric_code_only():
    api, plain, schema = _leaky_errors()
    assert error_label(api) == "TikTokAPIError code=105001"
    assert error_label(plain) == "ValueError"
    assert error_label(schema) == "TikTokSchemaError"
    # The schema error's own text names the field and the failure, never the input.
    _assert_clean(str(schema))
    assert "id: int_parsing" in str(schema)
    assert schema.__cause__ is None and schema.__suppress_context__


def test_relabel_stored_error_rewrites_an_older_repr():
    assert relabel_stored_error(f"TikTokAPIError(code=105001, message='{MARK}')") == (
        "TikTokAPIError code=105001"
    )
    assert relabel_stored_error(f"scoring: ValueError('{MARK}')") == "scoring: ValueError"
    assert relabel_stored_error("TikTokAPIError code=105001") == "TikTokAPIError code=105001"
    assert relabel_stored_error(None) is None


@pytest.mark.asyncio
async def test_a_database_error_never_echoes_its_bound_values(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'hp.db'}")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
            await conn.execute(text("INSERT INTO t VALUES (1, 'x')"))
        with pytest.raises(IntegrityError) as info:
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO t VALUES (:id, :v)"), {"id": 1, "v": f"{MARK} buyer"}
                )
        assert MARK not in str(info.value)
        assert "hide_parameters" in str(info.value)
    finally:
        await engine.dispose()


# -- the shop diagnosis snapshot's orders.json --------------------------------------------------


class _Orders:
    def search_all(self, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "576461413038785752",
                "status": "COMPLETED",
                "create_time": 1761400000,
                "update_time": 1761403600,
                "buyer_id": RAW_BUYER,
                **_buyer_fields(),
                "payment": {"currency": "VND", "sub_total": "300000", "total_amount": "315000"},
                "line_items": [
                    {
                        "id": "l1",
                        "product_id": "p1",
                        "sku_id": "k1",
                        "sale_price": "150000",
                        "platform_discount": "0",
                        "seller_discount": "10000",
                        "is_gift": False,
                        "buyer_note": f"{MARK} gift message",
                    }
                ],
            }
        ]


def test_the_diagnosis_orders_file_holds_only_what_the_report_reads(tmp_path: Path):
    record = fetch_orders(
        SimpleNamespace(orders=_Orders()), tmp_path, "2026-10-20", "2026-10-27", sleep_s=0
    )

    assert record["status"] == "ok" and record["orders"] == 1
    written = (tmp_path / "orders.json").read_text("utf-8")
    _assert_clean(written)
    (order,) = json.loads(written)["orders"]
    assert order == {
        "id": "576461413038785752",
        "status": "COMPLETED",
        "create_time": 1761400000,
        "update_time": 1761403600,
        "payment": {"currency": "VND", "sub_total": "300000", "total_amount": "315000"},
        "line_items": [
            {
                "id": "l1",
                "product_id": "p1",
                "sku_id": "k1",
                "sale_price": "150000",
                "platform_discount": "0",
                "seller_discount": "10000",
                "is_gift": False,
            }
        ],
    }


# -- the Connector ingest row's extra ---------------------------------------------------------


@pytest.mark.asyncio
async def test_an_ingest_rows_extra_keeps_no_string(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    body = {
        "source": "extension",
        "source_version": "0.1.0",
        "captured_at": "2026-10-27T09:30:00+07:00",
        "period": {"start": DAY.isoformat(), "end": DAY.isoformat(), "granularity": "day"},
        "order_type": "confirmed",
        "rows": [
            {
                "date": DAY.isoformat(),
                "item_id": "123",
                "item_name": "Áo thun",
                "source": "psd_label_product_card",
                "sales": 100000,
                "orders": 1,
                "extra": {
                    "sales_ratio": 0.2,
                    "flag": True,
                    "none": None,
                    "buyer": f"{MARK} Nguyen Van A",
                    "chat": f"{MARK} call 0900000000",
                },
            }
        ],
    }

    result = await ingest_service.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="item_by_source",
        body=ingest_service.IngestBody.model_validate(body),
        token_id=None,
        now=NOW,
    )

    metric = (await session.execute(select(PlatformDailyMetric))).scalar_one()
    _assert_clean(metric.extra)
    assert metric.extra["sales_ratio"] == 0.2 and metric.extra["flag"] is True
    assert metric.extra["item_name"] == "Áo thun"  # a declared product field, not extra
    raw = await session.get(IngestRawPayload, result.raw_payload_id)
    _assert_clean(raw.payload)


# -- the operator clean-up of rows stored before the allowlist --------------------------------


@pytest.mark.asyncio
async def test_the_clean_up_reduces_old_signals_errors_and_raw_events(session, engine):
    _, shop = await make_tenant(session, tiktok_shop_id=TIKTOK_SHOP)
    leaky_data = json.dumps(_buyer_fields(), sort_keys=True)
    session.add_all(
        [
            WorkflowWebhookSignal(
                shop_id=shop.id,
                tiktok_shop_id=TIKTOK_SHOP,
                catalog_id=1,
                event_type="ORDER_STATUS_CHANGE",
                workflow_keys="[]",
                intent="workflow_gate",
                event_id=f"wh:{TIKTOK_SHOP}:SELLER_DEAUTHORIZATION:1:{leaky_data}",
                payload=json.dumps(_order_webhook(), sort_keys=True),
            ),
            ShopIngestionState(
                shop_id=shop.id,
                status="failed",
                history_chunks_done=0,
                history_empty_chunks=0,
                last_error=f"ValueError('{MARK} Nguyen Van A')",
            ),
            TikTokSyncState(
                id=uuid.uuid4(),
                shop_id=shop.id,
                endpoint="orders",
                last_update_time=0,
                last_error=f"TikTokAPIError(code=105001, message='{MARK}')",
            ),
            WebhookRawEvent(
                tiktok_shop_id=TIKTOK_SHOP,
                event_type="1",
                event_id=f"wh:{TIKTOK_SHOP}:ORDER_STATUS_CHANGE:1:{leaky_data[:120]}",
                raw_body=json.dumps(_order_webhook()),
                http_status=200,
                processing_status="order_status_change",
            ),
        ]
    )
    await session.commit()

    first = await clean_shop(session, shop.id)
    assert first["public.workflow_webhook_signals"].changed == 1
    assert first["public.shop_ingestion_state"].changed == 1
    assert first["public.tiktok_sync_state"].changed == 1
    await session.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dry = await clean_raw_events(factory, apply=False)
    assert dry.changed == 1
    raw_events = await clean_raw_events(factory, apply=True)
    assert raw_events.scanned == 1 and raw_events.changed == 1

    async with factory() as check:
        signal = (await check.execute(select(WorkflowWebhookSignal))).scalar_one()
        state = await check.get(ShopIngestionState, shop.id)
        sync = (await check.execute(select(TikTokSyncState))).scalar_one()
        raw = (await check.execute(select(WebhookRawEvent))).scalar_one()
        key = await shop_pseudonym_key(check, shop.id)
    for stored in (signal.payload, signal.event_id, raw.raw_body, raw.event_id):
        _assert_clean(stored or "")
    assert json.loads(signal.payload or "{}")["data"]["buyer_id"] == buyer_pseudonym(key, RAW_BUYER)
    assert "buyer_id" not in json.loads(raw.raw_body or "{}")["data"]
    assert state is not None and state.last_error == "ValueError"
    assert sync.last_error == "TikTokAPIError code=105001"

    second = await clean_shop(session, shop.id)
    assert all(count.changed == 0 for count in second.values())
    again = await clean_raw_events(factory, apply=True)
    assert again.changed == 0


def test_an_event_id_the_current_writers_produce_is_left_alone():
    reduced = 'wh:s:UPCOMING_AUTHORIZATION_EXPIRATION:1:{"expiration_time": 1}'
    assert scrub_event_id(reduced, "UPCOMING_AUTHORIZATION_EXPIRATION") == reduced
    leaky = 'wh:s:UPCOMING_AUTHORIZATION_EXPIRATION:1:{"buyer_message": "x"}'
    scrubbed = scrub_event_id(leaky, "UPCOMING_AUTHORIZATION_EXPIRATION")
    assert scrubbed is not None and scrubbed.startswith(
        "wh:s:UPCOMING_AUTHORIZATION_EXPIRATION:1:d:"
    )
    assert "buyer_message" not in scrubbed
    assert scrub_event_id("ttsn:1", None) == "ttsn:1"
