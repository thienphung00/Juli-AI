"""Issue #1968 — the dedup ledger gains an epoch so lost rows can be re-ingested.

`processed_events` was a permanent, unbounded ledger with no epoch. When the
destination table lost its rows, the ledger still claimed those events were
processed, so they could never be re-ingested: the reference shop showed
`orders` = 0 while the vendor API served 3,581 orders. A poll run moved
`processed_events` from 283 to 774 and left `orders` at 0.

Every assertion here is made against the *destination table's row count*, not
against the dedup function's return value — the whole defect was that the
dedup verdict and the persisted data disagreed.

Assertions (release evidence plan, issue #1968):

AC1 → test_duplicate_under_current_epoch_leaves_destination_count_unchanged
AC2 → test_advancing_the_epoch_lets_the_same_event_id_repopulate_the_table
AC3 → test_advancing_one_channel_does_not_re_ingest_another_channels_ids
AC4 → test_importing_the_etl_package_creates_no_epoch_row
AC4 → test_schema_application_and_startup_leave_the_epoch_unchanged
AC4 → test_no_runtime_module_advances_an_epoch
AC5 → test_migration_060_is_expand_only
AC5 → test_migration_060_writes_no_rows
AC5 → test_a_pre_epoch_ledger_row_still_counts_as_processed
AC6 → test_a_failed_persist_leaves_no_claim_in_the_ledger
AC6 → test_the_id_a_failed_persist_released_is_ingestable_afterwards
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from juli_backend.models.models import Order, OrderItem, Shop, User
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.persistence.ingest import (
    IngestDedupEpoch,
    IngestDedupEpochsRepo,
    ProcessedEvent,
    ProcessedEventsRepo,
)
from juli_backend.services.etl.record import IngestRecord

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src" / "juli_backend"
MIGRATION_PATH = (
    BACKEND_SRC / "database" / "migrations" / "versions" / "060_processed_events_dedup_epoch.py"
)

TIKTOK_SHOP_ID = "7000000000001968"
ORDERS_CHANNEL = "tiktok.orders.raw"
ORDER_ITEMS_CHANNEL = "tiktok.order_items.raw"

OPERATOR = "ops@juli.ai"
REASON = "issue #1968 — recover orders lost to the 2026-07-30 wipe"


@pytest.fixture
def dlq_messages() -> list[dict]:
    return []


@pytest.fixture
def publish_dlq(dlq_messages):
    async def _publish(topic: str, key: str, value: bytes) -> None:
        dlq_messages.append({"topic": topic, "key": key, "value": json.loads(value.decode())})

    return _publish


@pytest_asyncio.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+84901968000")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Epoch Shop",
        tiktok_shop_id=TIKTOK_SHOP_ID,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


def _order_record(*, order_id: str = "o-1968", event_id: str = "evt-1968-order") -> IngestRecord:
    payload = {
        "order_id": order_id,
        "status": "AWAITING_SHIPMENT",
        "total_amount": "150.00",
        "currency": "VND",
        "update_time": 1_700_000_100,
        "event_id": event_id,
    }
    return IngestRecord(
        channel=ORDERS_CHANNEL,
        shop_key=TIKTOK_SHOP_ID,
        value=json.dumps(payload).encode(),
    )


def _order_item_record(
    *,
    order_id: str = "o-1968",
    sku_id: str = "sku-1968",
    event_id: str = "evt-1968-line",
) -> IngestRecord:
    payload = {
        "tiktok_order_id": order_id,
        "product_id": "prod-1968",
        "sku_id": sku_id,
        "quantity": 1,
        "unit_price": "150.00",
        "line_total": "150.00",
        "update_time": 1_700_000_100,
        "event_id": event_id,
    }
    return IngestRecord(
        channel=ORDER_ITEMS_CHANNEL,
        shop_key=TIKTOK_SHOP_ID,
        value=json.dumps(payload).encode(),
    )


async def _count(session, model, shop_id) -> int:
    result = await session.execute(
        select(func.count()).select_from(model).where(model.shop_id == shop_id)
    )
    return int(result.scalar_one())


async def _lose_the_rows(session, model, shop_id) -> None:
    """Reproduce the production state: destination emptied, ledger untouched."""
    await session.execute(delete(model).where(model.shop_id == shop_id))
    await session.commit()


# ---------------------------------------------------------------------------
# AC1 / AC2 — the ledger blocks re-ingest until an epoch advances
# ---------------------------------------------------------------------------


async def test_duplicate_under_current_epoch_leaves_destination_count_unchanged(
    session, shop, publish_dlq
):
    """The defect, asserted on the table: ledger hit ⇒ the row never comes back."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer.ingest(_order_record()) == ProcessOutcome.PROCESSED
    await session.commit()
    assert await _count(session, Order, shop.id) == 1

    await _lose_the_rows(session, Order, shop.id)
    assert await _count(session, Order, shop.id) == 0

    replay = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await replay.ingest(_order_record()) == ProcessOutcome.DUPLICATE
    await session.commit()

    assert await _count(session, Order, shop.id) == 0


async def test_advancing_the_epoch_lets_the_same_event_id_repopulate_the_table(
    session, shop, publish_dlq
):
    """After a recorded operator advance, the same id is accepted and the row appears."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer.ingest(_order_record()) == ProcessOutcome.PROCESSED
    await session.commit()
    await _lose_the_rows(session, Order, shop.id)

    epochs = IngestDedupEpochsRepo(session)
    new_epoch = await epochs.advance(
        shop_id=shop.id, channel=ORDERS_CHANNEL, operator=OPERATOR, reason=REASON
    )
    await session.commit()
    assert new_epoch == 1

    replay = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await replay.ingest(_order_record()) == ProcessOutcome.PROCESSED
    await session.commit()

    assert await _count(session, Order, shop.id) == 1


async def test_advancing_one_channel_does_not_re_ingest_another_channels_ids(
    session, shop, publish_dlq
):
    """An epoch is per (shop, channel): advancing orders must not unlock order_items."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await consumer.ingest(_order_record()) == ProcessOutcome.PROCESSED
    await session.commit()
    assert await consumer.ingest(_order_item_record()) == ProcessOutcome.PROCESSED
    await session.commit()

    await _lose_the_rows(session, OrderItem, shop.id)
    assert await _count(session, OrderItem, shop.id) == 0

    epochs = IngestDedupEpochsRepo(session)
    await epochs.advance(shop_id=shop.id, channel=ORDERS_CHANNEL, operator=OPERATOR, reason=REASON)
    await session.commit()

    replay = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await replay.ingest(_order_item_record()) == ProcessOutcome.DUPLICATE
    await session.commit()

    assert await _count(session, OrderItem, shop.id) == 0
    assert await epochs.current(shop_id=shop.id, channel=ORDER_ITEMS_CHANNEL) == 0


# ---------------------------------------------------------------------------
# AC4 — the epoch never advances on its own
# ---------------------------------------------------------------------------


async def test_importing_the_etl_package_creates_no_epoch_row(session, shop):
    """Import is not an operator action: loading the code writes nothing."""
    importlib.import_module("juli_backend.services.etl")
    importlib.import_module("juli_backend.services.etl.consumer")
    importlib.import_module("juli_backend.services.etl.persistence.ingest")

    rows = await session.execute(select(func.count()).select_from(IngestDedupEpoch))
    assert int(rows.scalar_one()) == 0

    epochs = IngestDedupEpochsRepo(session)
    assert await epochs.current(shop_id=shop.id, channel=ORDERS_CHANNEL) == 0
    rows = await session.execute(select(func.count()).select_from(IngestDedupEpoch))
    assert int(rows.scalar_one()) == 0, "reading an epoch must not create one"


async def test_schema_application_and_startup_leave_the_epoch_unchanged(
    session, shop, publish_dlq, engine
):
    """A deploy must not re-ingest all history.

    Deploy shape covered here: re-apply the schema (``Base.metadata.create_all``,
    the in-process stand-in for ``alembic upgrade head``), construct the consumer
    a worker builds at startup, and run a full ingest. None may move the epoch.
    The migration half of the claim is proved statically by
    ``test_migration_060_writes_no_rows`` and by the additive gate, which refuses
    any row-writing statement outright.
    """
    epochs = IngestDedupEpochsRepo(session)
    await epochs.advance(shop_id=shop.id, channel=ORDERS_CHANNEL, operator=OPERATOR, reason=REASON)
    await session.commit()
    assert await epochs.current(shop_id=shop.id, channel=ORDERS_CHANNEL) == 1

    from juli_backend.database.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    await consumer.ingest(_order_record(order_id="o-after-deploy", event_id="evt-after-deploy"))
    await session.commit()

    assert await epochs.current(shop_id=shop.id, channel=ORDERS_CHANNEL) == 1
    assert await _count(session, Order, shop.id) == 1


def test_no_runtime_module_advances_an_epoch():
    """`advance` is an operator action — defined once, called nowhere."""
    sources = {
        path.relative_to(BACKEND_SRC).as_posix(): path.read_text(encoding="utf-8")
        for path in BACKEND_SRC.rglob("*.py")
    }

    definers = {rel for rel, text in sources.items() if "async def advance(" in text}
    assert definers == {"services/etl/persistence/ingest/repo.py"}, (
        f"the epoch advance entry point must exist exactly once: {sorted(definers)}"
    )

    callers = {rel for rel, text in sources.items() if ".advance(" in text}
    assert callers == set(), f"runtime code advances a dedup epoch: {sorted(callers)}"

    assert "self._epochs.current(" in sources["services/etl/consumer.py"], (
        "the consumer must read the epoch, not manage it"
    )


async def test_advance_requires_a_recorded_operator_and_reason(session, shop):
    """An unattributed advance is not an operator action — it must be refused."""
    epochs = IngestDedupEpochsRepo(session)

    with pytest.raises(ValueError):
        await epochs.advance(shop_id=shop.id, channel=ORDERS_CHANNEL, operator="", reason=REASON)
    with pytest.raises(ValueError):
        await epochs.advance(
            shop_id=shop.id, channel=ORDERS_CHANNEL, operator=OPERATOR, reason="   "
        )

    assert await epochs.current(shop_id=shop.id, channel=ORDERS_CHANNEL) == 0


async def test_advance_records_who_advanced_it_and_why(session, shop):
    epochs = IngestDedupEpochsRepo(session)
    await epochs.advance(shop_id=shop.id, channel=ORDERS_CHANNEL, operator=OPERATOR, reason=REASON)
    await session.commit()

    row = (
        await session.execute(
            select(IngestDedupEpoch).where(
                IngestDedupEpoch.shop_id == shop.id,
                IngestDedupEpoch.channel == ORDERS_CHANNEL,
            )
        )
    ).scalar_one()

    assert row.epoch == 1
    assert row.advanced_by == OPERATOR
    assert row.reason == REASON
    assert row.advanced_at is not None


# ---------------------------------------------------------------------------
# AC5 — migration 060 is expand-only
# ---------------------------------------------------------------------------


def test_migration_060_is_expand_only():
    """ADR-027: the stable release keeps running against this schema."""
    sys.path.insert(0, str(REPO_ROOT / "infra" / "scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION_PATH])
    assert result.accepted, result.report()


def test_migration_060_writes_no_rows():
    """The epoch must not move on migration — so the migration writes no epoch."""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    lowered = upgrade.lower()

    assert "insert into" not in lowered
    assert "update " not in lowered or "set epoch" not in lowered
    assert "server_default" in upgrade, "the new column must reproduce today's behaviour"
    assert "def downgrade()" in source


def test_the_runtime_role_cannot_move_an_epoch():
    """Least privilege backs the code guarantee: juli_app may read, never write.

    `EtlConsumer` reads an epoch on every ingest, so the runtime role needs
    SELECT. It must not hold INSERT or UPDATE: advancing an epoch is an operator
    action run as the owner, and a role that cannot write the table cannot move
    an epoch on deploy even through a bug.
    """
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    granted = [line.strip() for line in source.splitlines() if 'op.execute(f"GRANT' in line]
    assert granted == ['op.execute(f"GRANT SELECT ON public.{EPOCH_TABLE} TO {ROLE_NAME}")'], (
        granted
    )


def test_migration_060_carries_the_number_meta_assigned():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "060_processed_events_epoch"' in source


async def test_a_pre_epoch_ledger_row_still_counts_as_processed(session, shop):
    """Expand-only: a row written before 060 resolves to the current epoch."""
    legacy = ProcessedEvent(event_id="evt-written-before-060", shop_id=shop.id)
    session.add(legacy)
    await session.flush()
    await session.commit()

    epochs = IngestDedupEpochsRepo(session)
    current = await epochs.current(shop_id=shop.id, channel=ORDERS_CHANNEL)
    assert current == 0
    assert legacy.epoch == current

    processed = ProcessedEventsRepo(session)
    assert (
        await processed.claim(event_id="evt-written-before-060", shop_id=shop.id, epoch=current)
        is False
    )


# ---------------------------------------------------------------------------
# AC6 — a failed persist cannot leave an id marked processed
# ---------------------------------------------------------------------------


async def _ledger_rows_for(session, event_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
    )
    return int(result.scalar_one())


async def test_a_failed_persist_leaves_no_claim_in_the_ledger(
    session, shop, publish_dlq, dlq_messages
):
    """The exact shape that lost 3,581 orders: marked processed, never persisted."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)

    orphan = _order_item_record(order_id="no-such-order", event_id="evt-orphan-line")
    assert await consumer.ingest(orphan) == ProcessOutcome.DLQ
    await session.commit()

    assert len(dlq_messages) == 1
    assert await _count(session, OrderItem, shop.id) == 0
    assert await _ledger_rows_for(session, "evt-orphan-line") == 0


async def test_the_id_a_failed_persist_released_is_ingestable_afterwards(
    session, shop, publish_dlq
):
    """Releasing the claim is only useful if the retry actually lands the row."""
    consumer = EtlConsumer(session=session, publish_dlq=publish_dlq)
    orphan = _order_item_record(order_id="o-1968", event_id="evt-retry-line")
    assert await consumer.ingest(orphan) == ProcessOutcome.DLQ
    await session.commit()

    assert await consumer.ingest(_order_record()) == ProcessOutcome.PROCESSED
    await session.commit()

    retry = EtlConsumer(session=session, publish_dlq=publish_dlq)
    assert await retry.ingest(orphan) == ProcessOutcome.PROCESSED
    await session.commit()

    assert await _count(session, OrderItem, shop.id) == 1
