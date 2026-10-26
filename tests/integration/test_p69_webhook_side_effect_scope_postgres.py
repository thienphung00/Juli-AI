"""Real Postgres, as `juli_app` under RLS: webhook side effects find their shop (P69, E12).

E11 fixed the order path; the other side-effect paths still read `shops` with no tenant scope,
and as `juli_app` that read returns nothing. The risky one is the seller deauthorization: the
webhook was acknowledged and automation was never paused. These tests run the side effects as
the deployed role and read the result back as the owner. Seeding mirrors
`test_p68_webhook_numeric_shop_id_postgres.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.services.cdp_speed import SharedComputeResult
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from juli_backend.services.webhook.material_worker import run_material_analytics_compute
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres]


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _numeric() -> str:
    return str(7_000_000_000_000_000_000 + uuid.uuid4().int % 1_000_000_000_000_000_000)


def _user(engine) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1557{user_id.hex[:7]}", "now": now},
        )
    return user_id


def _shop(engine, *, connect_id: str, numeric: str) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    shop_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, "
                " tiktok_numeric_shop_id, is_active, created_at, updated_at) "
                "VALUES (:id, :u, :n, :t, :num, true, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(_user(engine)),
                "n": f"shop-{shop_id.hex[:6]}",
                "t": connect_id,
                "num": numeric,
                "now": now,
            },
        )
    return shop_id


def _is_active(engine, shop_id: uuid.UUID) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT is_active FROM public.shops WHERE id = :s"), {"s": str(shop_id)}
            ).scalar_one()
        )


def _intents(engine, shop_id: uuid.UUID) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT intent FROM public.workflow_webhook_signals WHERE shop_id = :s"),
                {"s": str(shop_id)},
            ).scalars()
        )


def _two_shops() -> tuple[uuid.UUID, uuid.UUID, dict[str, str]]:
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        mine = _shop(engine, connect_id=f"TaFc-{t}", numeric=numeric)
        other = _shop(engine, connect_id=f"other-{t}", numeric=_numeric())
    return mine, other, {"numeric": numeric, "connect": f"TaFc-{t}"}


async def _deliver(event: TikTokWebhookPayload) -> None:
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        dispatcher = TikTokWebhookDispatcher(side_effects=DatabaseWebhookSideEffects(session))
        await dispatcher.dispatch(event)
        await session.commit()


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_deauthorization_webhook_pauses_the_right_shop_as_juli_app(key):
    mine, other, keys = _two_shops()

    await _deliver(TikTokWebhookPayload(type="SELLER_DEAUTHORIZATION", shop_id=keys[key]))

    with owner_sync_engine() as engine:
        assert _is_active(engine, mine) is False
        assert _is_active(engine, other) is True
        assert _intents(engine, mine) == ["pause_automation"]
        assert _intents(engine, other) == []


async def test_deauthorization_webhook_for_an_unknown_shop_does_nothing():
    mine, other, _keys = _two_shops()

    await _deliver(TikTokWebhookPayload(type="SELLER_DEAUTHORIZATION", shop_id=f"nope-{_tag()}"))

    with owner_sync_engine() as engine:
        assert (_is_active(engine, mine), _is_active(engine, other)) == (True, True)
        assert _intents(engine, mine) == [] and _intents(engine, other) == []


async def test_catalog_signal_is_recorded_for_the_right_shop_as_juli_app():
    mine, other, keys = _two_shops()

    await _deliver(
        TikTokWebhookPayload(
            type="UPCOMING_AUTHORIZATION_EXPIRATION",
            shop_id=keys["numeric"],
            timestamp=1_700_000_000,
            data={"expires_in_seconds": 86400},
        )
    )

    with owner_sync_engine() as engine:
        assert _intents(engine, mine) == ["re_auth_required"]
        assert _intents(engine, other) == []
        assert _is_active(engine, mine) is True


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_material_compute_resolves_the_shop_as_juli_app(key):
    mine, _other, keys = _two_shops()
    seen: list[uuid.UUID] = []

    async def compute(_session, job):
        seen.append(job.shop_id)
        return SharedComputeResult(bronze_appended=0, silver_promoted=0, gold_written=False)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        result = await run_material_analytics_compute(
            session,
            shop_key=keys[key],
            enqueue_reason="webhook_catalog",
            idempotency_key=f"p69-{_tag()}",
            compute_hook=compute,
        )

    assert result is not None
    assert seen == [mine]
