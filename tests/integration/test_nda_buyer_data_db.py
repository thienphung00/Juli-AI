"""Buyer data never lands on real Postgres: webhooks as ``juli_app``, the clean-up as owner (D16).

Owner decision D16 (ADR-116 §4, fast track D76). The SQLite proofs per sink are in
``tests/unit/test_nda_buyer_data_sinks.py``; this module covers what only Postgres
can show:

- a catalog webhook stuffed with buyer fields, handled as ``juli_app`` (the shop
  resolved through migration 102's definer function, the pseudonym key created
  under the shop's RLS scope), stores a ``workflow_webhook_signals.payload`` and a
  ``webhook_raw_events.raw_body`` with none of them, its ``buyer_id`` as tenant A's
  pseudonym -- and tenant B's key is untouched;
- the same delivery for an unknown shop stores the raw event with the buyer id
  dropped;
- the clean-up command: ``juli_app`` may not apply it; as the owner a dry run
  writes nothing, ``--apply`` reduces old signals, raw events and ``last_error``
  values and free-text silver reasons (decision A), and a second apply changes
  nothing.

It records into the shared ``webhook_raw_events`` archive and cleans all of it, so it
is in ``tests/conftest.py::_SHARED_STATE_MODULES`` and gets a database of its own.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.services.privacy.payload_cleanup import _can_update, run_cleanup
from juli_backend.services.privacy.pseudonym import buyer_pseudonym, shop_pseudonym_key
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from juli_backend.services.tiktok.webhook_raw_log import DatabaseRawWebhookEventRecorder
from tests.integration.two_tenant import RUNTIME_ROLE, seed_tenant

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres]

MARK = "NDA_BUYER"
RAW_BUYER = "7494011223344556677"


def _async_url() -> str:
    from juli_backend.core.config.runtime import async_database_url

    return async_database_url(os.environ["DATABASE_URL"])


@asynccontextmanager
async def app_session():
    """A ``juli_app`` session with NO scope, as the webhook receives a delivery."""
    engine = create_async_engine(
        _async_url(), connect_args={"server_settings": {"role": RUNTIME_ROLE}}
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@asynccontextmanager
async def scoped_app_session(shop_id: uuid.UUID):
    """A ``juli_app`` session scoped to one shop, to read its pseudonym key."""
    engine = create_async_engine(_async_url())
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(
                text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                    v=str(shop_id)
                )
            )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


def _stuffed(shop_key: str, *, order_id: str) -> dict:
    return {
        "type": "ORDER_STATUS_CHANGE",
        "shop_id": shop_key,
        "timestamp": 1761530000,
        "tts_notification_id": f"n-{uuid.uuid4().hex[:8]}",
        "data": {
            "order_id": order_id,
            "order_status": "AWAITING_SHIPMENT",
            "update_time": 1761530000,
            "buyer_id": RAW_BUYER,
            "user_id": RAW_BUYER,
            "buyer_email": f"{MARK}@example.invalid",
            "buyer_message": f"{MARK} please call",
            "buyer_nickname": f"{MARK}_nick",
            "buyer_avatar": f"https://example.invalid/{MARK}.png",
            "note": f"{MARK} note",
            "recipient_address": {
                "name": f"{MARK} Nguyen Van A",
                "phone_number": f"{MARK} 0900000000",
                "full_address": f"{MARK} 12 Ly Thuong Kiet",
            },
        },
    }


async def _deliver(body: dict) -> None:
    """Side effects + raw record in one request-scoped ``juli_app`` session, then commit."""
    async with app_session() as session:
        event = TikTokWebhookPayload.from_dict(body)
        entry = resolve_catalog_entry(event.type)
        assert entry is not None
        await DatabaseWebhookSideEffects(session).on_catalog_event(entry=entry, event=event)
        await DatabaseRawWebhookEventRecorder(session).record(
            body=json.dumps(body).encode(),
            signature="sig",
            http_status=200,
            processing_status=entry.handler_name,
            event=event,
            headers={"Content-Type": "application/json"},
        )
        await session.commit()


def _assert_clean(stored: str | None) -> None:
    assert stored is not None
    assert MARK not in stored and RAW_BUYER not in stored, stored
    for fragment in ("email", "message", "nickname", "avatar", "recipient", "user_id"):
        assert fragment not in stored, (fragment, stored)


def _one(owner_engine, sql: str, **params):
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), params).one()


def _key_count(owner_engine, shop_id: uuid.UUID) -> int:
    return _one(
        owner_engine,
        "SELECT count(*) FROM public.shop_pseudonym_keys WHERE shop_id = :s",
        s=str(shop_id),
    )[0]


@pytest.mark.asyncio
async def test_a_webhook_handled_as_juli_app_stores_no_buyer_field(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    order_id = f"57{uuid.uuid4().int % 10**16:016d}"
    await _deliver(_stuffed(tenant_a.tiktok_shop_key, order_id=order_id))

    signal_payload, signal_event_id = _one(
        owner_engine,
        "SELECT payload, event_id FROM public.workflow_webhook_signals WHERE shop_id = :s",
        s=str(tenant_a.shop_id),
    )
    raw_body, raw_event_id = _one(
        owner_engine,
        "SELECT raw_body, event_id FROM public.webhook_raw_events "
        "WHERE tiktok_shop_id = :k ORDER BY received_at DESC LIMIT 1",
        k=tenant_a.tiktok_shop_key,
    )
    for stored in (signal_payload, signal_event_id, raw_body, raw_event_id):
        _assert_clean(stored)

    async with scoped_app_session(tenant_a.shop_id) as session:
        key = await shop_pseudonym_key(session, tenant_a.shop_id)
    pseudonym = buyer_pseudonym(key, RAW_BUYER)
    assert json.loads(signal_payload)["data"]["buyer_id"] == pseudonym
    assert json.loads(raw_body)["data"]["buyer_id"] == pseudonym
    assert json.loads(raw_body)["data"]["order_id"] == order_id
    assert _key_count(owner_engine, tenant_b.shop_id) == 0


@pytest.mark.asyncio
async def test_an_unknown_shop_delivery_drops_the_buyer_id(owner_engine):
    unknown = f"79{uuid.uuid4().int % 10**16:016d}"
    async with app_session() as session:
        body = _stuffed(unknown, order_id="1")
        await DatabaseRawWebhookEventRecorder(session).record(
            body=json.dumps(body).encode(),
            signature="sig",
            http_status=200,
            processing_status="order_status_change",
            event=TikTokWebhookPayload.from_dict(body),
            headers=None,
        )
        await session.commit()

    (raw_body,) = _one(
        owner_engine,
        "SELECT raw_body FROM public.webhook_raw_events WHERE tiktok_shop_id = :k",
        k=unknown,
    )
    _assert_clean(raw_body)
    assert "buyer_id" not in json.loads(raw_body)["data"]


def _seed_legacy(owner_engine, tenant) -> None:
    """Rows as the previous release wrote them: full payloads, ``repr`` errors."""
    leaky = _stuffed(tenant.tiktok_shop_key, order_id="legacy-1")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.workflow_webhook_signals (id, shop_id, tiktok_shop_id, "
                " catalog_id, event_type, workflow_keys, intent, event_id, payload) "
                "VALUES (:id, :shop, :key, 1, 'ORDER_STATUS_CHANGE', '[]', 'workflow_gate', "
                " :eid, :payload)"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop": str(tenant.shop_id),
                "key": tenant.tiktok_shop_key,
                "eid": f"legacy-{uuid.uuid4().hex}",
                "payload": json.dumps(leaky, sort_keys=True),
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.webhook_raw_events (id, tiktok_shop_id, event_type, "
                " event_id, raw_body, http_status, processing_status, parse_version) "
                "VALUES (:id, :key, 'ORDER_STATUS_CHANGE', :eid, :body, 200, "
                " 'order_status_change', 1)"
            ),
            {
                "id": str(uuid.uuid4()),
                "key": tenant.tiktok_shop_key,
                "eid": "wh:x:NEW_MESSAGE:1:" + json.dumps({"content": f"{MARK} hi"}),
                "body": json.dumps(leaky),
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_sync_state (id, shop_id, endpoint, "
                " last_update_time, last_error) VALUES (:id, :shop, 'orders', 0, :err)"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop": str(tenant.shop_id),
                "err": f"TikTokAPIError(code=105001, message='{MARK} buyer echo')",
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.shop_ingestion_state (shop_id, status, last_error, "
                " history_chunks_done, history_empty_chunks) "
                "VALUES (:shop, 'failed', :err, 0, 0) "
                "ON CONFLICT (shop_id) DO UPDATE SET last_error = EXCLUDED.last_error"
            ),
            {"shop": str(tenant.shop_id), "err": f"ValueError('{MARK} Nguyen Van A')"},
        )
        # Decision A: a free-text reason in silver becomes "other".
        conn.execute(
            text(
                "INSERT INTO silver.orders (id, shop_id, tiktok_order_id, status, total_amount, "
                " currency, cancel_reason, update_time) "
                "VALUES (:id, :shop, 'legacy-order-1', 'cancelled', 1, 'VND', :reason, now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop": str(tenant.shop_id),
                "reason": f"{MARK} gọi lại cho tôi nhé",
            },
        )


def _legacy(owner_engine, tenant) -> tuple[str, str, str, str]:
    signal = _one(
        owner_engine,
        "SELECT payload FROM public.workflow_webhook_signals "
        "WHERE shop_id = :s AND event_id LIKE 'legacy-%'",
        s=str(tenant.shop_id),
    )[0]
    raw = _one(
        owner_engine,
        "SELECT raw_body || ' ' || event_id FROM public.webhook_raw_events "
        "WHERE tiktok_shop_id = :k AND event_id NOT LIKE 'ttsn:%' "
        "AND raw_body LIKE '%legacy-1%'",
        k=tenant.tiktok_shop_key,
    )[0]
    sync = _one(
        owner_engine,
        "SELECT last_error FROM public.tiktok_sync_state WHERE shop_id = :s",
        s=str(tenant.shop_id),
    )[0]
    state = _one(
        owner_engine,
        "SELECT last_error FROM public.shop_ingestion_state WHERE shop_id = :s",
        s=str(tenant.shop_id),
    )[0]
    return signal, raw, sync, state


@pytest.mark.asyncio
async def test_cleanup_is_refused_to_juli_app_and_dry_run_then_apply_as_owner(owner_engine):
    tenant = seed_tenant(owner_engine, label="tenant-nda-cleanup")
    _seed_legacy(owner_engine, tenant)

    async with scoped_app_session(tenant.shop_id) as session:
        assert await _can_update(session) is False

    engine = create_async_engine(_async_url())
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        dry = await run_cleanup(factory, apply=False)
        assert dry.tables["public.workflow_webhook_signals"].changed >= 1
        assert dry.tables["public.webhook_raw_events"].changed >= 1
        assert dry.tables["public.tiktok_sync_state"].changed == 1
        assert dry.tables["public.shop_ingestion_state"].changed == 1
        assert all(MARK in stored for stored in _legacy(owner_engine, tenant))

        applied = await run_cleanup(factory, apply=True)
        assert applied.tables["public.webhook_raw_events"].changed >= 1
        signal, raw, sync, state = _legacy(owner_engine, tenant)
        for stored in (signal, raw):
            _assert_clean(stored)
        assert sync == "TikTokAPIError code=105001" and state == "ValueError"
        assert "buyer_id" not in raw  # an archived delivery cannot prove its shop
        reason = _one(
            owner_engine,
            "SELECT cancel_reason FROM silver.orders "
            "WHERE shop_id = :s AND tiktok_order_id = 'legacy-order-1'",
            s=str(tenant.shop_id),
        )[0]
        assert reason == "other"

        again = await run_cleanup(factory, apply=True)
        assert all(count.changed == 0 for count in again.tables.values())
    finally:
        await engine.dispose()

    async with scoped_app_session(tenant.shop_id) as session:
        key = await shop_pseudonym_key(session, tenant.shop_id)
    assert json.loads(signal)["data"]["buyer_id"] == buyer_pseudonym(key, RAW_BUYER)
