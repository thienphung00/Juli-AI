"""Webhook / worker side-effect paths resolve the shop, then act under its scope (P69, E12).

A webhook or Celery task carries no tenant context, and as ``juli_app`` an unscoped ``shops``
read returns nothing, so these paths silently found no shop in production: catalog-event
signals and the deauthorization pause (``DatabaseWebhookSideEffects``), the material
Shared Compute worker, and the history replay. Each now resolves through
``ShopsRepo.resolve_id_by_tiktok_key`` (migration 102 on PostgreSQL) and does every further
read/write inside that shop's scope. SQLite has no RLS, so these tests prove the shape: the
right shop is resolved by EITHER TikTok identifier, the scope entered names that shop, and
the other tenant is untouched. The RLS proof is the Postgres-marked twin
(``tests/integration/test_p69_webhook_side_effect_scope_postgres.py``).
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from juli_backend.database import tenant_context
from juli_backend.models.models import Shop, User, WebhookRawEvent
from juli_backend.repositories.repos import WorkflowWebhookSignalsRepo
from juli_backend.services.cdp_speed import SharedComputeResult
from juli_backend.services.product_history import replay as replay_module
from juli_backend.services.tiktok import webhook_handlers
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry
from juli_backend.services.webhook import material_worker

pytestmark = pytest.mark.asyncio

CONNECT_A, NUMERIC_A = "TaFcAAAA-p69", "7494751643546977001"
CONNECT_B, NUMERIC_B = "TaFcBBBB-p69", "7494751643546977002"
KEYS = {"numeric": NUMERIC_A, "connect": CONNECT_A}


async def _two_tenants(session) -> tuple[Shop, Shop]:
    user_a, user_b = (
        User(id=uuid.uuid4(), phone="+84906900001"),
        User(id=uuid.uuid4(), phone="+84906900002"),
    )
    shop_a = Shop(
        id=uuid.uuid4(),
        user_id=user_a.id,
        shop_name="A",
        tiktok_shop_id=CONNECT_A,
        tiktok_numeric_shop_id=NUMERIC_A,
        is_active=True,
    )
    shop_b = Shop(
        id=uuid.uuid4(),
        user_id=user_b.id,
        shop_name="B",
        tiktok_shop_id=CONNECT_B,
        tiktok_numeric_shop_id=NUMERIC_B,
        is_active=True,
    )
    session.add_all([user_a, user_b, shop_a, shop_b])
    await session.flush()
    return shop_a, shop_b


def _recording(real: Any, log: list[tuple[str, Any]], name: str) -> Any:
    """Wrap a scope context manager so the test sees which shop (and user) it named."""

    @asynccontextmanager
    async def wrapper(session, shop_id, *args, **kwargs):
        log.append((name, shop_id, *args))
        async with real(session, shop_id, *args, **kwargs):
            yield

    return wrapper


@pytest.fixture
def scopes(monkeypatch) -> list[tuple[str, Any]]:
    log: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        webhook_handlers,
        "with_shop_scope",
        _recording(tenant_context.with_shop_scope, log, "shop"),
    )
    monkeypatch.setattr(
        webhook_handlers,
        "with_tenant_scope",
        _recording(tenant_context.with_tenant_scope, log, "tenant"),
    )
    monkeypatch.setattr(
        replay_module,
        "with_shop_scope",
        _recording(tenant_context.with_shop_scope, log, "replay_shop"),
    )
    monkeypatch.setattr(
        material_worker,
        "with_sticky_shop_scope",
        _recording(tenant_context.with_sticky_shop_scope, log, "sticky"),
    )
    return log


# -- DatabaseWebhookSideEffects: deauthorization ---------------------------------------------


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_deauthorization_pauses_only_the_resolved_shop_under_its_scope(session, scopes, key):
    shop_a, shop_b = await _two_tenants(session)
    dispatcher = TikTokWebhookDispatcher(
        side_effects=webhook_handlers.DatabaseWebhookSideEffects(session)
    )

    await dispatcher.dispatch(
        TikTokWebhookPayload(type="SELLER_DEAUTHORIZATION", shop_id=KEYS[key], data={})
    )
    await session.flush()

    await session.refresh(shop_a)
    await session.refresh(shop_b)
    assert shop_a.is_active is False
    assert shop_b.is_active is True
    # The shop's own scope for the whole unit, the (shop, owner) pair for the UPDATE --
    # `shops`' UPDATE policy is user-keyed, so a shop scope alone would match zero rows.
    assert scopes == [("shop", shop_a.id), ("tenant", shop_a.id, shop_a.user_id)]
    signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(shop_a.id)
    assert [s.intent for s in signals] == ["pause_automation"]
    assert await WorkflowWebhookSignalsRepo(session).list_for_shop(shop_b.id) == []


async def test_deauthorization_for_an_unknown_shop_does_nothing(session, scopes, caplog):
    shop_a, shop_b = await _two_tenants(session)
    effects = webhook_handlers.DatabaseWebhookSideEffects(session)
    entry = resolve_catalog_entry("SELLER_DEAUTHORIZATION")
    assert entry is not None

    with caplog.at_level("WARNING", logger=webhook_handlers.__name__):
        await effects.on_catalog_event(
            entry=entry,
            event=TikTokWebhookPayload(type="SELLER_DEAUTHORIZATION", shop_id="nobody-p69"),
        )
    await session.flush()

    await session.refresh(shop_a)
    await session.refresh(shop_b)
    assert (shop_a.is_active, shop_b.is_active) == (True, True)
    assert scopes == []  # no scope entered, and no unscoped fallback either
    assert [r.message for r in caplog.records] == ["webhook_shop_not_found"]


# -- DatabaseWebhookSideEffects: workflow signals --------------------------------------------


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_catalog_signal_is_recorded_for_the_resolved_shop_under_its_scope(
    session, scopes, key
):
    shop_a, shop_b = await _two_tenants(session)
    dispatcher = TikTokWebhookDispatcher(
        side_effects=webhook_handlers.DatabaseWebhookSideEffects(session)
    )

    await dispatcher.dispatch(
        TikTokWebhookPayload(
            type="UPCOMING_AUTHORIZATION_EXPIRATION",
            shop_id=KEYS[key],
            timestamp=1_700_000_000,
            data={"expires_in_seconds": 86400},
        )
    )
    await session.flush()

    assert scopes == [("shop", shop_a.id)]  # no user scope: nothing here updates `shops`
    signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(shop_a.id)
    assert [(s.intent, s.tiktok_shop_id) for s in signals] == [("re_auth_required", KEYS[key])]
    assert await WorkflowWebhookSignalsRepo(session).list_for_shop(shop_b.id) == []
    await session.refresh(shop_a)
    assert shop_a.is_active is True


# -- material_worker.run_material_analytics_compute ------------------------------------------


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_material_compute_runs_for_the_resolved_shop_under_its_sticky_scope(
    session, scopes, key
):
    shop_a, _shop_b = await _two_tenants(session)
    seen: list[tuple[uuid.UUID, str]] = []

    async def compute(_session, job):
        seen.append((job.shop_id, job.shop_key))
        return SharedComputeResult(bronze_appended=0, silver_promoted=0, gold_written=False)

    result = await material_worker.run_material_analytics_compute(
        session,
        shop_key=KEYS[key],
        event_type="INVENTORY_CHANGED",
        enqueue_reason="webhook_catalog",
        idempotency_key=f"p69-{key}",
        compute_hook=compute,
    )

    assert result is not None
    assert seen == [(shop_a.id, KEYS[key])]
    assert scopes == [("sticky", shop_a.id)]


async def test_material_compute_for_an_unknown_shop_stops(session, scopes, caplog):
    await _two_tenants(session)
    called: list[object] = []

    async def compute(_session, job):
        called.append(job)
        raise AssertionError("must not run")

    with caplog.at_level("WARNING", logger=material_worker.__name__):
        result = await material_worker.run_material_analytics_compute(
            session,
            shop_key="nobody-p69",
            enqueue_reason="webhook_catalog",
            idempotency_key="p69-unknown",
            compute_hook=compute,
        )

    assert result is None
    assert called == []
    assert scopes == []
    assert [r.message for r in caplog.records] == ["material_analytics_unknown_shop"]


# -- product_history replay ------------------------------------------------------------------


class _RecordingEffects:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def on_catalog_event(self, *, entry, event) -> None:
        self.events.append(event.shop_id)


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_replay_resolves_the_shop_and_replays_under_its_scope(session, scopes, key):
    shop_a, _shop_b = await _two_tenants(session)
    for shop_key in (KEYS[key], "nobody-p69"):
        body = {
            "type": 15,
            "tts_notification_id": f"p69-{shop_key}",
            "shop_id": shop_key,
            "timestamp": 1,
            "data": {"product_id": "p1", "changed_fields": ["title"]},
        }
        session.add(
            WebhookRawEvent(
                tiktok_shop_id=shop_key,
                event_type="15",
                raw_body=json.dumps(body),
                http_status=200,
                processing_status="unknown_event",
            )
        )
    await session.flush()
    effects = _RecordingEffects()

    result = await replay_module.replay_raw_events(session, side_effects=effects)

    assert (result.scanned, result.replayed, result.unknown_shop) == (2, 1, 1)
    assert effects.events == [KEYS[key]]
    assert scopes == [("replay_shop", shop_a.id)]
