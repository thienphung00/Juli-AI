"""P68 (E11): a webhook naming the shop by TikTok's NUMERIC id resolves the shop.

Production: ORDER_STATUS_CHANGE webhooks for a connected shop were DLQ'd as
``unknown shop tiktok_shop_id=7495274531001436791``. ``shops.tiktok_shop_id`` holds the
connect identifier; webhooks carry the numeric shop id, which nothing stored.

SQLite unit level (no RLS, no definer functions -- the repository's SQLite branch runs the
same predicate). The Postgres twin, as ``juli_app`` under RLS, is
``tests/integration/test_p68_webhook_numeric_shop_id_postgres.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from juli_backend.core.security import VerifiedShopCipher
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import Shop, TikTokCredential, User
from juli_backend.repositories.repos import OrdersRepo, ShopsRepo, TikTokCredentialRepo
from juli_backend.services.etl.consumer import EtlConsumer, ProcessOutcome
from juli_backend.services.etl.record import IngestRecord
from juli_backend.services.tiktok.credential_binding import (
    backfill_tiktok_numeric_shop_id,
    make_binding_verifier,
)

CONNECT_ID = "TaFcIwAAAAAA-connect-identifier"
NUMERIC_ID = "7495274531001436791"
CIPHER = "ROW_p68_cipher"
APP_KEY = "p68_app_key"
APP_SECRET = "p68_app_secret"

REPO = Path(__file__).resolve().parents[2]
MIGRATION = (
    REPO / "backend/src/juli_backend/database/migrations/versions/102_shops_tiktok_numeric_id.py"
)


@pytest.fixture
def dlq():
    return []


@pytest.fixture
def dlq_handoff(dlq):
    async def _handoff(channel: str, key: str, value: bytes) -> None:
        dlq.append({"channel": channel, "key": key, "value": json.loads(value)})

    return _handoff


@pytest_asyncio.fixture
async def shop(session, user_id):
    session.add(User(id=user_id, phone="+84906800068"))
    row = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="P68 Store",
        tiktok_shop_id=CONNECT_ID,
        tiktok_numeric_shop_id=NUMERIC_ID,
    )
    session.add(row)
    await session.flush()
    return row


def _order(shop_key: str, *, order_id: str = "p68-o1") -> IngestRecord:
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


# ---------------------------------------------------------------------------
# Resolution: numeric id, connect id, unknown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scoped", [False, True], ids=["poll_mode", "webhook_mode"])
async def test_numeric_shop_id_resolves_the_shop(session, shop, dlq_handoff, dlq, scoped):
    consumer = EtlConsumer(session=session, dlq_handoff=dlq_handoff, scope_to_resolved_shop=scoped)

    outcome = await consumer.ingest(_order(NUMERIC_ID))

    assert outcome is ProcessOutcome.PROCESSED
    assert dlq == []
    orders = await OrdersRepo(session).list(shop.id)
    assert [o.tiktok_order_id for o in orders] == ["p68-o1"]


@pytest.mark.parametrize("scoped", [False, True], ids=["poll_mode", "webhook_mode"])
async def test_connect_identifier_still_resolves_the_shop(session, shop, dlq_handoff, dlq, scoped):
    consumer = EtlConsumer(session=session, dlq_handoff=dlq_handoff, scope_to_resolved_shop=scoped)

    outcome = await consumer.ingest(_order(CONNECT_ID, order_id="p68-o2"))

    assert outcome is ProcessOutcome.PROCESSED
    assert dlq == []
    assert len(await OrdersRepo(session).list(shop.id)) == 1


@pytest.mark.parametrize("scoped", [False, True], ids=["poll_mode", "webhook_mode"])
async def test_unknown_shop_still_dlqs_and_warns(session, shop, dlq_handoff, dlq, caplog, scoped):
    consumer = EtlConsumer(session=session, dlq_handoff=dlq_handoff, scope_to_resolved_shop=scoped)

    with caplog.at_level(logging.WARNING, logger="juli_backend.services.etl.consumer"):
        outcome = await consumer.ingest(_order("9999999999999999999"))

    assert outcome is ProcessOutcome.DLQ
    assert len(dlq) == 1
    assert dlq[0]["value"]["error"] == "unknown shop tiktok_shop_id=9999999999999999999"
    warnings = [r for r in caplog.records if r.getMessage() == "etl_unknown_shop"]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING
    assert warnings[0].shop_key == "9999999999999999999"
    assert await OrdersRepo(session).list(shop.id) == []


async def test_repo_prefers_the_connect_identifier_and_resolves_ids(session, shop, user_id):
    repo = ShopsRepo(session)

    assert (await repo.get_by_tiktok_id(NUMERIC_ID)).id == shop.id
    assert (await repo.get_by_tiktok_id(CONNECT_ID)).id == shop.id
    assert await repo.get_by_tiktok_id("nope") is None
    assert await repo.resolve_id_by_tiktok_key(NUMERIC_ID) == shop.id
    assert await repo.resolve_id_by_tiktok_key(CONNECT_ID) == shop.id
    assert await repo.resolve_id_by_tiktok_key("") is None
    assert await repo.resolve_id_by_tiktok_key("nope") is None


async def test_deployed_webhook_with_numeric_shop_id_persists_the_order(session, shop, monkeypatch):
    """The production assembly end to end: signed ORDER_STATUS_CHANGE, numeric shop_id."""
    from juli_backend.services.webhook import material_dispatch
    from juli_backend.services.webhook.deployed import handle_tiktok_webhook_delivery
    from juli_backend.services.webhook.material_gate import InMemoryMaterialEnqueueGate

    dispatcher = MagicMock()
    dispatcher.enqueue.return_value = "p68-task"
    monkeypatch.setattr(material_dispatch, "_dispatcher", dispatcher)
    monkeypatch.setattr(material_dispatch, "_gate", InMemoryMaterialEnqueueGate())
    body = json.dumps(
        {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": NUMERIC_ID,
            "timestamp": 1_700_000_000,
            "data": {
                "order_id": "577000000000068",
                "order_status": "AWAITING_SHIPMENT",
                "update_time": 1_700_000_000,
                "payment": {"total_amount": "120000.00", "currency": "VND"},
            },
        }
    ).encode()
    signature = hmac.new(
        APP_SECRET.encode(), f"{APP_KEY}{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()

    result = await handle_tiktok_webhook_delivery(
        session=session,
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        body=body,
        signature=signature,
        headers={"Content-Type": "application/json"},
    )

    assert result.status_code == 200
    orders = await OrdersRepo(session).list(shop.id)
    assert [o.tiktok_order_id for o in orders] == ["577000000000068"]


# ---------------------------------------------------------------------------
# Connect stores both identifiers
# ---------------------------------------------------------------------------


def _oauth(session, verifier) -> TikTokOAuthService:
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key=APP_KEY, app_secret=APP_SECRET, base_url="https://x.test"),
        session=session,
        redirect_uri="https://x.test/cb",
        app_secret=APP_SECRET,
        binding_verifier=verifier,
    )


def _token(open_id: str = CONNECT_ID) -> dict:
    return {
        "open_id": open_id,
        "access_token": "ROW_access_p68",
        "refresh_token": "ROW_refresh_p68",
        "access_token_expire_in": 604800,
        "seller_name": "P68 Connect",
    }


async def _seller(session, user_id) -> None:
    session.add(User(id=user_id, phone="+84906800069"))
    await session.flush()


async def test_connect_stores_connect_id_cipher_and_numeric_id(session, user_id):
    await _seller(session, user_id)

    async def verifier(_session, *, capability, access_token):
        return VerifiedShopCipher(CIPHER, tiktok_shop_id=NUMERIC_ID)

    shop = await _oauth(session, verifier).provision_shop_and_credentials(_token(), user_id=user_id)

    assert shop.tiktok_shop_id == CONNECT_ID
    assert shop.tiktok_numeric_shop_id == NUMERIC_ID
    credential = await TikTokCredentialRepo(session).get_by_shop(shop.id)
    assert credential.shop_cipher == CIPHER
    assert type(credential.shop_cipher) is str
    assert await ShopsRepo(session).resolve_id_by_tiktok_key(NUMERIC_ID) == shop.id


async def test_reconnect_fills_numeric_id_on_an_existing_shop(session, user_id):
    await _seller(session, user_id)

    async def plain(_session, *, capability, access_token):
        return CIPHER

    first = await _oauth(session, plain).provision_shop_and_credentials(_token(), user_id=user_id)
    assert first.tiktok_numeric_shop_id is None

    async def verified(_session, *, capability, access_token):
        return VerifiedShopCipher(CIPHER, tiktok_shop_id=NUMERIC_ID)

    second = await _oauth(session, verified).provision_shop_and_credentials(
        _token(), user_id=user_id
    )

    assert second.id == first.id
    assert second.tiktok_numeric_shop_id == NUMERIC_ID


async def test_real_binding_verifier_carries_the_numeric_id(session, user_id, monkeypatch):
    monkeypatch.setattr(
        "juli_backend.services.tiktok.credential_binding.resolve_authorized_shop",
        lambda **_: {"id": NUMERIC_ID, "cipher": CIPHER, "name": "P68"},
    )
    await _seller(session, user_id)
    verifier = make_binding_verifier(app_key=APP_KEY, app_secret=APP_SECRET)

    shop = await _oauth(session, verifier).provision_shop_and_credentials(_token(), user_id=user_id)

    assert shop.tiktok_numeric_shop_id == NUMERIC_ID
    assert (await TikTokCredentialRepo(session).get_by_shop(shop.id)).shop_cipher == CIPHER


async def test_numeric_id_held_by_another_shop_is_refused_not_raised(
    session, shop, other_user_id, caplog
):
    session.add(User(id=other_user_id, phone="+84906800070"))
    other = Shop(id=uuid.uuid4(), user_id=other_user_id, shop_name="Other", tiktok_shop_id="x")
    session.add(other)
    await session.flush()

    with caplog.at_level(logging.WARNING, logger="juli_backend.repositories.identity"):
        changed = await ShopsRepo(session).record_tiktok_numeric_shop_id(other.id, NUMERIC_ID)

    assert changed is False
    assert any(r.getMessage() == "tiktok_numeric_shop_id_conflict" for r in caplog.records)
    assert await ShopsRepo(session).resolve_id_by_tiktok_key(NUMERIC_ID) == shop.id


# ---------------------------------------------------------------------------
# Lazy backfill on the poll (shops connected before migration 102)
# ---------------------------------------------------------------------------


async def _legacy_shop(session, user_id) -> tuple[Shop, TikTokCredential]:
    session.add(User(id=user_id, phone="+84906800071"))
    shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Legacy", tiktok_shop_id=CONNECT_ID)
    session.add(shop)
    await session.flush()
    credential = TikTokCredential(
        shop_id=shop.id,
        access_token="ROW_a",
        refresh_token="ROW_r",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1),
        capability="sandbox_write",
        shop_cipher=CIPHER,
    )
    session.add(credential)
    await session.flush()
    return shop, credential


async def test_poll_backfill_fills_a_legacy_shop_once(session, user_id):
    shop, credential = await _legacy_shop(session, user_id)
    calls = []

    def lister():
        calls.append(1)
        return [{"id": NUMERIC_ID, "cipher": CIPHER}]

    got = await backfill_tiktok_numeric_shop_id(
        session, shop, credential, list_authorized_shops=lister
    )
    again = await backfill_tiktok_numeric_shop_id(
        session, shop, credential, list_authorized_shops=lister
    )

    assert got == again == NUMERIC_ID
    assert len(calls) == 1
    assert shop.tiktok_numeric_shop_id == NUMERIC_ID
    assert await ShopsRepo(session).resolve_id_by_tiktok_key(NUMERIC_ID) == shop.id


@pytest.mark.parametrize(
    "answer",
    [
        [{"id": NUMERIC_ID, "cipher": "someone-else"}],
        [{"id": NUMERIC_ID, "cipher": CIPHER}, {"id": "2", "cipher": "c2"}],
        [],
        [{"cipher": CIPHER}],
    ],
    ids=["cipher_mismatch", "two_shops", "no_shops", "no_id"],
)
async def test_poll_backfill_stores_nothing_it_cannot_prove(session, user_id, answer):
    shop, credential = await _legacy_shop(session, user_id)

    got = await backfill_tiktok_numeric_shop_id(
        session, shop, credential, list_authorized_shops=lambda: answer
    )

    assert got is None
    assert shop.tiktok_numeric_shop_id is None


async def test_poll_backfill_swallows_a_vendor_failure(session, user_id, caplog):
    shop, credential = await _legacy_shop(session, user_id)

    def boom():
        raise RuntimeError("vendor down")

    with caplog.at_level(logging.WARNING):
        got = await backfill_tiktok_numeric_shop_id(
            session, shop, credential, list_authorized_shops=boom
        )

    assert got is None
    assert any(r.getMessage() == "tiktok_numeric_shop_id_backfill_failed" for r in caplog.records)


# ---------------------------------------------------------------------------
# Migration: deploy-gate shape (no head pinned)
# ---------------------------------------------------------------------------


def test_migration_is_additive_literal_and_short_enough():
    import re
    import sys

    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    body = MIGRATION.read_text("utf-8")
    revision = re.search(r'^revision: str = "([^"]+)"', body, re.M)
    assert revision is not None
    assert len(revision.group(1)) <= 32
    result = evaluate_migration_paths([MIGRATION])
    assert result.accepted, result.findings
    for signature in ("resolve_tiktok_shop_key(text)", "record_tiktok_numeric_shop_id(uuid, text)"):
        assert signature in body
    assert "SECURITY DEFINER" in body
    assert "FROM PUBLIC" in body
    assert "app_current_shop_id()" in body


def test_poll_backfill_lists_shops_on_a_cipher_less_client(monkeypatch):
    """P68 follow-up: the poll's client carries the shop cipher, which TikTok refuses on Get
    Authorized Shops (and sandbox write resources have no ``authorization``); the real path
    must ask on a cipher-less client built from the credential's own token."""
    from types import SimpleNamespace

    from juli_backend.workers.services.polling import ingestion

    seen: list[dict] = []

    def fake_list_all_shops(self):
        seen.append({"cipher": self._client.shop_cipher, "token": self._client.access_token})
        return [{"id": "7495274531001436791", "cipher": "cipher-x"}]

    monkeypatch.setattr(
        "juli_backend.integrations.tiktok.resources.authorization.AuthorizationResource.list_all_shops",
        fake_list_all_shops,
    )
    config = SimpleNamespace(app_key="key", app_secret="secret")
    credential = SimpleNamespace(access_token="token-x", shop_cipher="cipher-x")
    lister = ingestion._authorized_shops_lister(
        config, credential, SimpleNamespace(), injected=False
    )
    assert lister() == [{"id": "7495274531001436791", "cipher": "cipher-x"}]
    assert seen == [{"cipher": None, "token": "token-x"}]


def test_injected_resources_answer_the_backfill_themselves():
    from types import SimpleNamespace

    from juli_backend.workers.services.polling import ingestion

    resources = SimpleNamespace(
        authorization=SimpleNamespace(list_all_shops=lambda: [{"id": "1", "cipher": "c"}])
    )
    lister = ingestion._authorized_shops_lister(
        SimpleNamespace(), SimpleNamespace(), resources, injected=True
    )
    assert lister() == [{"id": "1", "cipher": "c"}]
