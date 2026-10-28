"""P72: two production 500s (live release 9766d963, 2026-10-28), SQLite shape tests.

1. ``audit_reviewer_run_action`` flushes the route's pending writes BEFORE ``audit.record``
   opens ``ops_role``. On Postgres that block runs as ``juli_ops`` and flushes on the way
   out, so the Hoàn tác route's pending ``close_card`` UPDATE went out as ``juli_ops``:
   ``permission denied for table action_cards``. SQLite has no roles; the test proves the
   ordering (nothing is pending when the audit starts). The RLS proof is
   ``tests/integration/test_p72_revert_and_webhook_dup_postgres.py``.
2. ``WorkflowWebhookSignalsRepo.record_if_new`` is one ``INSERT ... ON CONFLICT DO NOTHING``:
   a duplicate ``event_id`` returns ``False`` and raises nothing, and the webhook handler then
   neither re-pauses a deauthorized shop nor re-enqueues the history read.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.api import reviewer as reviewer_api
from juli_backend.models.models import ActionCard, Shop, User
from juli_backend.repositories.repos import WorkflowWebhookSignalsRepo
from juli_backend.services import decision_reasons
from juli_backend.services.ops import audit
from juli_backend.services.tiktok import webhook_handlers
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload

pytestmark = pytest.mark.asyncio


async def _shop(session, *, connect: str = "TaFc-p72", numeric: str = "7494751643546977072"):
    user = User(id=uuid.uuid4(), phone=f"+849069{uuid.uuid4().int % 10**5:05d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="p72",
        tiktok_shop_id=connect,
        tiktok_numeric_shop_id=numeric,
        is_active=True,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


# -- 1. the reviewer audit flushes the route's writes first ----------------------------------


async def test_reviewer_audit_flushes_the_routes_pending_card_close_before_ops_role(
    session, monkeypatch
):
    shop = await _shop(session)
    card = ActionCard(
        id=uuid.uuid4(), shop_id=shop.id, workflow_key="optimize_product_2",
        subject_type="product", subject_id=str(uuid.uuid4()), revision=1, priority=0,
        severity="medium", title="t", description="", recommendation_payload="{}",
        status="approved",
    )  # fmt: skip
    session.add(card)
    await session.flush()
    decision_reasons.close_card(card)
    assert card in session.dirty  # what the Hoàn tác route holds when it audits

    pending_at_audit: list[Any] = []

    async def _record(session_arg, actor, action, **kwargs):
        pending_at_audit.append(list(session_arg.dirty) + list(session_arg.new))

    monkeypatch.setattr(audit, "record", _record)
    context = SimpleNamespace(account=SimpleNamespace(actor="reviewer"), platform="shopee")
    monkeypatch.setattr(reviewer_api, "reviewer_context", lambda request: context)

    await reviewer_api.audit_reviewer_run_action(
        session, object(), audit.ACTION_REVIEWER_SANDBOX_REVERT, shop_id=shop.id, after={}
    )

    assert pending_at_audit == [[]]
    await session.refresh(card)
    assert card.status == "dismissed" and card.dismissed_at is not None


async def test_a_sellers_request_writes_no_audit_and_flushes_nothing(session, monkeypatch):
    """No reviewer context: the helper is a no-op (the route's commit flushes as juli_app)."""
    shop = await _shop(session)
    calls: list[Any] = []
    monkeypatch.setattr(audit, "record", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(reviewer_api, "reviewer_context", lambda request: None)

    await reviewer_api.audit_reviewer_run_action(
        session, object(), audit.ACTION_REVIEWER_SANDBOX_REVERT, shop_id=shop.id, after={}
    )

    assert calls == []


# -- 2. duplicate webhook delivery -----------------------------------------------------------


def _signal(shop: Shop, event_id: str) -> dict[str, Any]:
    return {
        "shop_id": shop.id,
        "tiktok_shop_id": shop.tiktok_shop_id,
        "catalog_id": 7,
        "event_type": "UPCOMING_AUTHORIZATION_EXPIRATION",
        "workflow_keys": ["account_platform"],
        "intent": "re_auth_required",
        "event_id": event_id,
        "payload_json": "{}",
    }


async def test_record_if_new_stores_once_and_reports_a_duplicate(session):
    shop = await _shop(session)
    repo = WorkflowWebhookSignalsRepo(session)

    first = await repo.record_if_new(**_signal(shop, "wh:p72:dup"))
    second = await repo.record_if_new(**_signal(shop, "wh:p72:dup"))
    other = await repo.record_if_new(**_signal(shop, "wh:p72:other"))

    assert (first, second, other) == (True, False, True)
    stored = await repo.list_for_shop(shop.id)
    assert sorted(s.event_id for s in stored) == ["wh:p72:dup", "wh:p72:other"]


async def _dispatch(session, event: TikTokWebhookPayload) -> None:
    dispatcher = TikTokWebhookDispatcher(
        side_effects=webhook_handlers.DatabaseWebhookSideEffects(session)
    )
    await dispatcher.dispatch(event)
    await session.flush()


async def test_a_redelivered_deauthorization_does_not_pause_again(session):
    shop = await _shop(session)
    deauth = TikTokWebhookPayload(
        type="SELLER_DEAUTHORIZATION", shop_id=shop.tiktok_shop_id, timestamp=1_700_000_456
    )

    await _dispatch(session, deauth)
    await session.refresh(shop)
    paused = shop.is_active
    shop.is_active = True  # the seller re-authorized before TikTok's retry arrived
    await session.flush()
    await _dispatch(session, deauth)

    await session.refresh(shop)
    assert paused is False
    assert shop.is_active is True
    assert len(await WorkflowWebhookSignalsRepo(session).list_for_shop(shop.id)) == 1


async def test_a_deauthorization_without_any_identity_still_pauses_every_time(session):
    """No timestamp, no notification id: a later real deauthorization keys the same."""
    shop = await _shop(session)
    deauth = TikTokWebhookPayload(type="SELLER_DEAUTHORIZATION", shop_id=shop.tiktok_shop_id)

    await _dispatch(session, deauth)
    shop.is_active = True
    await session.flush()
    await _dispatch(session, deauth)

    await session.refresh(shop)
    assert shop.is_active is False


async def test_a_redelivered_product_event_enqueues_the_history_read_once(session, monkeypatch):
    shop = await _shop(session)
    enqueued: list[Any] = []
    monkeypatch.setattr(
        webhook_handlers.DatabaseWebhookSideEffects,
        "_enqueue_history",
        staticmethod(lambda shop_id, entry, event: enqueued.append(shop_id)),
    )
    event = TikTokWebhookPayload(
        type="PRODUCT_INFORMATION_CHANGE",
        shop_id=shop.tiktok_shop_id,
        timestamp=1_700_000_789,
        data={"product_id": "1730000000000000072"},
        notification_id="ttsn-p72",
    )

    await _dispatch(session, event)
    await _dispatch(session, event)

    assert enqueued == [shop.id]
