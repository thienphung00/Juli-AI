"""P70 (E15): one order-status vocabulary, and the poll completes a webhook-created order.

Production 2026-10-27, sandbox shop: a buyer cancelled an order while ON_HOLD. The
ORDER_STATUS_CHANGE webhook (``order_status: CANCEL``) created the ``silver.orders`` row
as ``status='cancel'`` with ``tiktok_created_at`` NULL -- the ETL map knew only
``CANCELLED`` and stored anything else lower-cased. The next polls fetched the order
(Order Search: ``CANCELLED``, ``create_time`` set) but the upsert refused it: its
``update_time`` equalled the webhook's, and an equal ``update_time`` counted as stale.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.models.models import Order, Shop, User
from juli_backend.models.order_status import (
    CANONICAL_ORDER_STATUSES,
    UNKNOWN_ORDER_STATUS,
    canonical_order_status,
)
from juli_backend.repositories.repos import OrdersRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.order_status_repair import run_repair
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.etl.transform import transform_for_channel
from juli_backend.services.shop_diagnosis_daily import refresh

pytestmark = pytest.mark.asyncio

NUMERIC_SHOP_ID = "7000000000000070"
ORDER_ID = "577000000000070"
CREATED = 1_761_541_740  # 2025-10-27 05:09 UTC
CANCELLED_AT = 1_761_541_860  # 05:11 UTC
WEBHOOK_CHANNEL = "tiktok.order_status_change"
POLL_CHANNEL = "tiktok.orders.raw"


def _naive(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC).replace(tzinfo=None)


def _webhook(status: object, *, update_time: int = CANCELLED_AT, order_id: str = ORDER_ID):
    return {
        "type": 1,
        "tts_notification_id": f"n-{uuid.uuid4().hex[:8]}",
        "shop_id": NUMERIC_SHOP_ID,
        "timestamp": update_time + 5,
        "data": {
            "order_id": order_id,
            "order_status": status,
            "is_on_hold_order": True,
            "update_time": update_time,
        },
    }


def _poll_order(status: str = "CANCELLED", *, update_time: int = CANCELLED_AT) -> dict:
    """Order Search's whole order, as ``sync_orders`` hands it off (after normalize_order)."""
    return {
        "id": ORDER_ID,
        "order_id": ORDER_ID,
        "status": status,
        "order_status": status,
        "create_time": CREATED,
        "update_time": update_time,
        "payment": {"total_amount": "120000", "currency": "VND"},
        "currency": "VND",
        "cancel_reason": "buyer_cancel",
        "cancellation_initiator": "BUYER",
    }


@pytest.fixture
def dlq():
    return []


@pytest.fixture
def dlq_handoff(dlq):
    async def _handoff(channel: str, key: str, value: bytes) -> None:
        dlq.append(json.loads(value))

    return _handoff


@pytest_asyncio.fixture
async def shop(session, user_id):
    session.add(User(id=user_id, phone="+84907000070"))
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="P70 sandbox",
        tiktok_shop_id=NUMERIC_SHOP_ID,
    )
    session.add(shop)
    await session.commit()
    await session.refresh(shop)
    return shop


async def _ingest(session, dlq_handoff, channel: str, payload: dict, **consumer_kwargs):
    consumer = EtlConsumer(session=session, dlq_handoff=dlq_handoff, **consumer_kwargs)
    outcome = await consumer.ingest(
        IngestRecord(channel=channel, shop_key=NUMERIC_SHOP_ID, value=json.dumps(payload).encode())
    )
    await session.commit()
    return outcome


async def _the_order(session, shop) -> Order:
    stmt = select(Order).where(Order.shop_id == shop.id).execution_options(populate_existing=True)
    return (await session.execute(stmt)).scalar_one()


# --- the shared vocabulary ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["CANCEL", "CANCELLED", "CANCELED", "cancel", "cancelled", "Cancelled", " canceled ", 140],
)
async def test_every_cancel_spelling_is_cancelled(raw):
    assert canonical_order_status(raw) == "cancelled"


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("UNPAID", "pending"),
        ("ON_HOLD", "on_hold"),
        ("on hold", "on_hold"),
        ("AWAITING_SHIPMENT", "confirmed"),
        ("PARTIALLY_SHIPPING", "confirmed"),
        ("AWAITING_COLLECTION", "confirmed"),
        ("IN_TRANSIT", "shipped"),
        ("DELIVERED", "delivered"),
        ("COMPLETED", "delivered"),
        ("RETURNED", "returned"),
        ("111", "confirmed"),
        (122, "delivered"),
    ],
)
async def test_tiktok_statuses_map_to_the_canonical_vocabulary(raw, canonical):
    assert canonical_order_status(raw) == canonical


async def test_canonical_values_are_fixed_points():
    for value in CANONICAL_ORDER_STATUSES:
        assert canonical_order_status(value) == value


async def test_unknown_status_falls_back_and_warns(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.models.order_status")

    assert canonical_order_status("PENDING_REVIEW_X<script>") == UNKNOWN_ORDER_STATUS

    records = [r for r in caplog.records if r.message == "order_status_unrecognised"]
    assert len(records) == 1
    assert records[0].raw_status == "PENDING_REVIEW_Xscript"
    assert records[0].stored_as == UNKNOWN_ORDER_STATUS


async def test_missing_status_is_unknown_without_a_warning(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.models.order_status")
    assert canonical_order_status(None) == UNKNOWN_ORDER_STATUS
    assert canonical_order_status("") == UNKNOWN_ORDER_STATUS
    assert not [r for r in caplog.records if r.message == "order_status_unrecognised"]


# --- the transform -----------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["CANCEL", "CANCELLED", "CANCELED", "140"])
async def test_webhook_transform_maps_each_cancel_variant(raw):
    kind, kwargs = transform_for_channel(WEBHOOK_CHANNEL, _webhook(raw))

    assert kind == "order"
    assert kwargs["status"] == "cancelled"
    # A status event carries no amount, buyer or create time: it must not invent them.
    assert set(kwargs) == {"tiktok_order_id", "status", "update_time"}
    assert kwargs["update_time"] == _naive(CANCELLED_AT)


async def test_webhook_and_poll_produce_the_same_status():
    _, from_webhook = transform_for_channel(WEBHOOK_CHANNEL, _webhook("CANCEL"))
    _, from_poll = transform_for_channel(POLL_CHANNEL, _poll_order("CANCELLED"))
    assert from_webhook["status"] == from_poll["status"] == "cancelled"
    assert from_poll["tiktok_created_at"] == _naive(CREATED)


async def test_webhook_transform_unknown_status_is_canonical_fallback(caplog):
    caplog.set_level(logging.WARNING, logger="juli_backend.models.order_status")
    _, kwargs = transform_for_channel(WEBHOOK_CHANNEL, _webhook("SOMETHING_NEW"))
    assert kwargs["status"] == UNKNOWN_ORDER_STATUS
    assert any(r.message == "order_status_unrecognised" for r in caplog.records)


# --- consumer + repository ---------------------------------------------------------------


@pytest.mark.parametrize("raw", ["CANCEL", "CANCELLED", "CANCELED"])
async def test_webhook_order_status_change_stores_cancelled(session, shop, dlq_handoff, raw):
    outcome = await _ingest(
        session, dlq_handoff, WEBHOOK_CHANNEL, _webhook(raw), scope_to_resolved_shop=True
    )

    assert outcome is ProcessOutcome.PROCESSED
    order = await _the_order(session, shop)
    assert order.status == "cancelled"
    assert order.tiktok_created_at is None  # the webhook does not know it
    assert order.total_amount == Decimal("0")  # placeholder until the poll fills it
    assert order.order_value is None


async def test_webhook_first_then_poll_with_the_same_update_time_completes_the_row(
    session, shop, dlq_handoff
):
    """The production sequence: webhook at 05:11, poll at 05:16 with the same update_time."""
    await _ingest(
        session, dlq_handoff, WEBHOOK_CHANNEL, _webhook("CANCEL"), scope_to_resolved_shop=True
    )
    outcome = await _ingest(session, dlq_handoff, POLL_CHANNEL, _poll_order())

    assert outcome is ProcessOutcome.PROCESSED
    order = await _the_order(session, shop)
    assert order.status == "cancelled"
    assert order.tiktok_created_at == _naive(CREATED)
    assert order.total_amount == Decimal("120000")
    assert order.order_value == Decimal("120000")
    assert order.update_time == _naive(CANCELLED_AT)


async def test_poll_older_than_the_webhook_still_fills_the_gaps(session, shop, dlq_handoff):
    """Webhook strictly newer: its status stands, the poll still fills created_at / amounts."""
    await _ingest(
        session, dlq_handoff, WEBHOOK_CHANNEL, _webhook("CANCEL"), scope_to_resolved_shop=True
    )
    await _ingest(
        session,
        dlq_handoff,
        POLL_CHANNEL,
        _poll_order("ON_HOLD", update_time=CANCELLED_AT - 60),
    )

    order = await _the_order(session, shop)
    assert order.status == "cancelled"
    assert order.tiktok_created_at == _naive(CREATED)
    assert order.total_amount == Decimal("120000")
    assert order.update_time == _naive(CANCELLED_AT)


async def test_newer_webhook_after_poll_changes_status_and_blanks_nothing(
    session, shop, dlq_handoff
):
    await _ingest(
        session, dlq_handoff, POLL_CHANNEL, _poll_order("ON_HOLD", update_time=CREATED + 10)
    )
    await _ingest(
        session, dlq_handoff, WEBHOOK_CHANNEL, _webhook("CANCEL"), scope_to_resolved_shop=True
    )

    order = await _the_order(session, shop)
    assert order.status == "cancelled"
    assert order.update_time == _naive(CANCELLED_AT)
    assert order.tiktok_created_at == _naive(CREATED)
    assert order.total_amount == Decimal("120000")
    assert order.cancel_reason is not None


async def test_webhook_with_the_same_update_time_does_not_override_the_poll(
    session, shop, dlq_handoff
):
    await _ingest(session, dlq_handoff, POLL_CHANNEL, _poll_order("CANCELLED"))
    await _ingest(
        session, dlq_handoff, WEBHOOK_CHANNEL, _webhook("ON_HOLD"), scope_to_resolved_shop=True
    )
    assert (await _the_order(session, shop)).status == "cancelled"


async def test_unknown_webhook_status_never_replaces_a_known_one(session, shop, dlq_handoff):
    await _ingest(
        session, dlq_handoff, POLL_CHANNEL, _poll_order("AWAITING_SHIPMENT", update_time=CREATED)
    )
    await _ingest(
        session,
        dlq_handoff,
        WEBHOOK_CHANNEL,
        _webhook("BRAND_NEW_STATUS"),
        scope_to_resolved_shop=True,
    )
    order = await _the_order(session, shop)
    assert order.status == "confirmed"
    assert order.update_time == _naive(CANCELLED_AT)


async def test_stale_poll_heals_a_legacy_unrecognised_status(session, shop):
    """A row stored before P70 with a value the map does not know is a gap the poll fills."""
    session.add(
        Order(
            id=uuid.uuid4(),
            shop_id=shop.id,
            tiktok_order_id=ORDER_ID,
            status="weird_legacy",
            total_amount=Decimal("0"),
            currency="VND",
            update_time=_naive(CANCELLED_AT + 100),
        )
    )
    await session.commit()

    await OrdersRepo(session).upsert(
        shop_id=shop.id,
        full_snapshot=True,
        **transform_for_channel(POLL_CHANNEL, _poll_order())[1],
    )
    await session.commit()

    order = await _the_order(session, shop)
    assert order.status == "cancelled"
    assert order.tiktok_created_at == _naive(CREATED)


async def test_report_refresh_hook_sees_the_merged_row(session, shop, dlq_handoff):
    """B12: the hook gets the stored status and the poll's create time, not the raw write."""
    seen: list[dict] = []

    async def hook(_session, _shop_id, change):
        seen.append(change)

    await _ingest(
        session, dlq_handoff, POLL_CHANNEL, _poll_order("ON_HOLD", update_time=CREATED + 10)
    )
    await _ingest(
        session,
        dlq_handoff,
        WEBHOOK_CHANNEL,
        _webhook("CANCEL"),
        scope_to_resolved_shop=True,
        after_order_change=hook,
    )

    assert seen[-1]["status"] == "cancelled"
    assert seen[-1]["tiktok_created_at"] == _naive(CREATED)


@pytest.mark.parametrize(
    ("status", "qualifies"),
    [
        ("cancelled", True),
        ("cancel", True),
        ("CANCEL", True),
        ("canceled", True),
        ("refunded", True),
        ("returned", True),
        ("on_hold", True),
        ("confirmed", True),
        ("AWAITING_SHIPMENT", True),
        ("pending", False),
        ("unknown", False),
        (None, False),
    ],
)
async def test_report_refresh_recognises_every_spelling(status, qualifies):
    assert refresh._qualifies(status) is qualifies


# --- the repair command ------------------------------------------------------------------


async def _seed_repair_rows(session, shop) -> None:
    rows = [
        ("o-cancel", "cancel", None),
        ("o-legacy", "AWAITING_SHIPMENT", CREATED),
        ("o-ok", "cancelled", CREATED),
        ("o-weird", "weird_legacy", CREATED),
    ]
    for order_id, status, created in rows:
        session.add(
            Order(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_order_id=order_id,
                status=status,
                total_amount=Decimal("0"),
                currency="VND",
                tiktok_created_at=_naive(created) if created else None,
                update_time=_naive(CANCELLED_AT),
            )
        )
    await session.commit()


async def _statuses(factory) -> dict[str, str]:
    async with factory() as check:
        rows = (await check.execute(select(Order.tiktok_order_id, Order.status))).all()
    return dict(rows)


async def test_repair_dry_run_reports_and_writes_nothing(session, engine, shop):
    await _seed_repair_rows(session, shop)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    report = await run_repair(factory, apply=False)

    [result] = report.shops
    assert result.scanned == 4
    assert result.normalised == {("AWAITING_SHIPMENT", "confirmed"): 1, ("cancel", "cancelled"): 1}
    assert result.unrecognised == {"weird_legacy": 1}
    assert result.missing_created_at == 1
    rendered = report.render(applied=False)
    assert "DRY RUN" in rendered and "would change 2" in rendered
    assert "o-cancel" not in rendered  # counts only, never order ids
    assert (await _statuses(factory))["o-cancel"] == "cancel"


async def test_repair_apply_normalises_and_is_idempotent(session, engine, shop):
    await _seed_repair_rows(session, shop)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    applied = await run_repair(factory, apply=True, only=[shop.id])
    assert applied.shops[0].changed == 2
    assert await _statuses(factory) == {
        "o-cancel": "cancelled",
        "o-legacy": "confirmed",
        "o-ok": "cancelled",
        "o-weird": "weird_legacy",  # unrecognised: left for the map to learn it
    }

    again = await run_repair(factory, apply=True)
    assert again.shops[0].changed == 0
    assert again.shops[0].missing_created_at == 1  # reported, never written
