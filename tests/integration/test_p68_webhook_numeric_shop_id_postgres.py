"""Real Postgres, as `juli_app` under RLS: a webhook resolves its shop by numeric id (P68, E11).

Two facts made every production order webhook an "unknown shop": the numeric shop id TikTok
sends was never stored, and the webhook request holds no tenant scope, so as `juli_app` an
unscoped `shops` read returns nothing at all. Migration 102 adds the column and two
`SECURITY DEFINER` functions (the resolve, and the own-shop-only write); these tests prove
both under the deployed role. Seeding and read-back run as the owner.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from juli_backend.core.security import VerifiedShopCipher
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import TikTokAuth
from juli_backend.repositories.repos import OrdersRepo, ShopsRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
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
            {"id": str(user_id), "phone": f"+1556{user_id.hex[:7]}", "now": now},
        )
    return user_id


def _shop(engine, user_id: uuid.UUID, *, connect_id: str, numeric: str | None = None):
    now = datetime.now(UTC).replace(tzinfo=None)
    shop_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, "
                " tiktok_numeric_shop_id, created_at, updated_at) "
                "VALUES (:id, :u, :n, :t, :num, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(user_id),
                "n": f"shop-{shop_id.hex[:6]}",
                "t": connect_id,
                "num": numeric,
                "now": now,
            },
        )
    return shop_id


def _numeric_of(engine, shop_id: uuid.UUID) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT tiktok_numeric_shop_id FROM public.shops WHERE id = :s"),
            {"s": str(shop_id)},
        ).scalar_one()


async def _orders_of(shop_id: uuid.UUID) -> list[str]:
    """Read back through the ORM as `juli_app` under the shop's scope (the same table and
    search path the consumer wrote with)."""
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            return [o.tiktok_order_id for o in await OrdersRepo(session).list(shop_id)]


def _order(shop_key: str, order_id: str) -> IngestRecord:
    payload = {
        "order_id": order_id,
        "status": "AWAITING_SHIPMENT",
        "total_amount": "150.00",
        "currency": "VND",
        "update_time": 1_700_000_100,
        "event_id": f"evt-{order_id}",
    }
    return IngestRecord(
        channel="tiktok.orders.raw", shop_key=shop_key, value=json.dumps(payload).encode()
    )


async def test_unscoped_resolve_finds_the_shop_by_either_identifier():
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        shop = _shop(engine, _user(engine), connect_id=f"TaFc-{t}", numeric=numeric)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        repo = ShopsRepo(session)
        # The defect's second half: unscoped, RLS hides the row from an ordinary read.
        assert await repo.get_by_tiktok_id(numeric) is None
        assert await repo.resolve_id_by_tiktok_key(numeric) == shop
        assert await repo.resolve_id_by_tiktok_key(f"TaFc-{t}") == shop
        assert await repo.resolve_id_by_tiktok_key(f"nope-{t}") is None


@pytest.mark.parametrize("key", ["numeric", "connect"])
async def test_webhook_consumer_persists_under_the_resolved_shops_scope(key):
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        shop = _shop(engine, _user(engine), connect_id=f"TaFc-{t}", numeric=numeric)
    shop_key = numeric if key == "numeric" else f"TaFc-{t}"
    dlq: list[bytes] = []

    async def handoff(_channel: str, _key: str, value: bytes) -> None:
        dlq.append(value)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        consumer = EtlConsumer(session=session, dlq_handoff=handoff, scope_to_resolved_shop=True)
        outcome = await consumer.ingest(_order(shop_key, f"o-{t}"))
        await session.commit()

    assert outcome is ProcessOutcome.PROCESSED
    assert dlq == []
    assert await _orders_of(shop) == [f"o-{t}"]


async def test_webhook_for_an_unknown_shop_still_dlqs():
    dlq: list[bytes] = []

    async def handoff(_channel: str, _key: str, value: bytes) -> None:
        dlq.append(value)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        consumer = EtlConsumer(session=session, dlq_handoff=handoff, scope_to_resolved_shop=True)
        outcome = await consumer.ingest(_order(f"unknown-{_tag()}", f"o-{_tag()}"))

    assert outcome is ProcessOutcome.DLQ
    assert len(dlq) == 1
    assert json.loads(dlq[0])["error"].startswith("unknown shop tiktok_shop_id=")


async def test_record_writes_only_the_scoped_shop():
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        user = _user(engine)
        mine = _shop(engine, user, connect_id=f"mine-{t}")
        other = _shop(engine, _user(engine), connect_id=f"other-{t}")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        repo = ShopsRepo(session)
        async with with_shop_scope(session, mine):
            assert await repo.record_tiktok_numeric_shop_id(other, numeric) is False
            assert await repo.record_tiktok_numeric_shop_id(mine, numeric) is True
            assert await repo.record_tiktok_numeric_shop_id(mine, numeric) is False
        await session.commit()

    with owner_sync_engine() as engine:
        assert _numeric_of(engine, mine) == numeric
        assert _numeric_of(engine, other) is None


async def test_record_refuses_a_numeric_id_another_shop_holds():
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        _shop(engine, _user(engine), connect_id=f"holder-{t}", numeric=numeric)
        second = _shop(engine, _user(engine), connect_id=f"second-{t}")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, second):
            changed = await ShopsRepo(session).record_tiktok_numeric_shop_id(second, numeric)
        await session.commit()

    assert changed is False
    with owner_sync_engine() as engine:
        assert _numeric_of(engine, second) is None


async def test_oauth_connect_as_juli_app_stores_the_numeric_id():
    t, numeric = _tag(), _numeric()
    with owner_sync_engine() as engine:
        seller = _user(engine)

    async def verifier(_session, *, capability, access_token):
        return VerifiedShopCipher(f"C{t}", tiktok_shop_id=numeric)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        service = TikTokOAuthService(
            tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
            session=session,
            redirect_uri="https://example.test/cb",
            app_secret="s",
            binding_verifier=verifier,
        )
        shop = await service.provision_shop_and_credentials(
            {
                "open_id": f"open-{t}",
                "access_token": "a",
                "refresh_token": "r",
                "seller_name": "P68",
                "access_token_expire_in": 604800,
            },
            user_id=seller,
        )
        shop_id = shop.id
        await session.commit()

    with owner_sync_engine() as engine:
        assert _numeric_of(engine, shop_id) == numeric
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert await ShopsRepo(session).resolve_id_by_tiktok_key(numeric) == shop_id
