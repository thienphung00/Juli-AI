"""Real Postgres (P70, E15): webhook-first then poll completes the order as `juli_app`;
the repair command normalises statuses as the owner, per shop under its scope.

Seeding and read-back run as the owner (`owner_sync_engine`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.order_status_repair import run_repair
from juli_backend.services.etl.record import IngestRecord
from tests.support.postgres import (
    database_url,
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres]

CREATED = 1_761_541_740
CANCELLED_AT = 1_761_541_860


def _seed_shop(engine) -> tuple[uuid.UUID, str]:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    numeric = str(7_100_000_000_000_000_000 + uuid.uuid4().int % 10**18)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1557{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, "
                " tiktok_numeric_shop_id, created_at, updated_at) "
                "VALUES (:id, :u, :n, :t, :num, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(user_id),
                "n": f"p70-{shop_id.hex[:6]}",
                "t": f"TaFc-{shop_id.hex[:8]}",
                "num": numeric,
                "now": now,
            },
        )
    return shop_id, numeric


def _row(engine, shop_id: uuid.UUID, order_id: str):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status, tiktok_created_at, total_amount FROM silver.orders "
                "WHERE shop_id = :s AND tiktok_order_id = :o"
            ),
            {"s": str(shop_id), "o": order_id},
        ).one()


async def _ingest(channel: str, shop_key: str, payload: dict):
    """As `juli_app`; the resolve + scope stands in for the poll's sticky shop scope too."""

    async def dlq(_channel: str, _key: str, _value: bytes) -> None:
        raise AssertionError("unexpected DLQ")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        consumer = EtlConsumer(session=session, dlq_handoff=dlq, scope_to_resolved_shop=True)
        outcome = await consumer.ingest(
            IngestRecord(channel=channel, shop_key=shop_key, value=json.dumps(payload).encode())
        )
        await session.commit()
    return outcome


async def test_webhook_first_then_poll_completes_the_order_under_rls():
    with owner_sync_engine() as engine:
        shop_id, numeric = _seed_shop(engine)
    order_id = f"o-{uuid.uuid4().hex[:10]}"
    webhook = {
        "type": 1,
        "shop_id": numeric,
        "timestamp": CANCELLED_AT + 5,
        "data": {"order_id": order_id, "order_status": "CANCEL", "update_time": CANCELLED_AT},
    }
    poll = {
        "id": order_id,
        "order_id": order_id,
        "status": "CANCELLED",
        "create_time": CREATED,
        "update_time": CANCELLED_AT,
        "payment": {"total_amount": "120000", "currency": "VND"},
    }

    assert await _ingest("tiktok.order_status_change", numeric, webhook) is ProcessOutcome.PROCESSED
    with owner_sync_engine() as engine:
        status, created, _ = _row(engine, shop_id, order_id)
    assert status == "cancelled" and created is None

    assert await _ingest("tiktok.orders.raw", numeric, poll) is ProcessOutcome.PROCESSED
    with owner_sync_engine() as engine:
        status, created, total = _row(engine, shop_id, order_id)
    assert status == "cancelled"
    assert created == datetime.fromtimestamp(CREATED, tz=UTC).replace(tzinfo=None)
    assert int(total) == 120000


async def test_repair_normalises_as_owner_and_is_idempotent():
    with owner_sync_engine() as engine:
        shop_id, _ = _seed_shop(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO silver.orders (id, shop_id, tiktok_order_id, status, "
                    " total_amount, currency, update_time) "
                    "VALUES (:id, :s, :o, 'cancel', 0, 'VND', now())"
                ),
                {"id": str(uuid.uuid4()), "s": str(shop_id), "o": f"o-{shop_id.hex[:8]}"},
            )

    engine = create_async_engine(async_database_url(database_url()))
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        dry = await run_repair(factory, apply=False, only=[shop_id])
        assert dry.shops[0].normalised == {"cancel": 1}
        assert dry.shops[0].missing_created_at == 1
        applied = await run_repair(factory, apply=True, only=[shop_id])
        assert applied.shops[0].changed == 1
        again = await run_repair(factory, apply=True, only=[shop_id])
        assert again.shops[0].changed == 0
    finally:
        await engine.dispose()

    with owner_sync_engine() as sync_engine:
        status, _, _ = _row(sync_engine, shop_id, f"o-{shop_id.hex[:8]}")
    assert status == "cancelled"
