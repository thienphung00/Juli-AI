"""P72: two production 500s, reproduced on real Postgres as ``juli_app`` under RLS.

1. "Hoàn tác" by the partner reviewer on the sandbox pin (P70) failed with
   ``permission denied for table action_cards``: the route closed the card in memory, then
   ``audit_reviewer_run_action`` opened ``ops_role`` (``SET LOCAL ROLE juli_ops``) and that
   block's closing ``flush()`` sent the card UPDATE as ``juli_ops``, which has no UPDATE on
   ``action_cards``. A seller's request writes no audit row, so its flush runs as ``juli_app``.
2. A duplicate TikTok catalog delivery hit ``workflow_webhook_signals_event_id_key`` (500); it
   must be a no-op.

Through the real app (reviewer and seller tokens, real ``get_current_user``), one connection as
``juli_app`` per request, exactly as ``test_reviewer_sandbox_live_postgres.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from juli_backend.models.models import ActionCard, ActionCardApproval, WorkflowRun
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import catalog as reviewer_catalog
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from tests.integration.test_reviewer_sandbox_live_postgres import (
    PRODUCT_ID,
    SECRET,
    _client,
    _headers,
    app,
    world,
)
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

__all__ = ["app", "world"]  # fixtures re-used from the P64 module

ORIGINAL_TITLE = "Sandbox áo thun"
JULI_TITLE = "Áo thun cotton Juli viết"
REASON = {"reason_code": "metrics_dropped"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _owner_of(shop_id: uuid.UUID) -> uuid.UUID:
    with owner_sync_engine() as engine, engine.connect() as conn:
        return conn.execute(
            text("SELECT user_id FROM public.shops WHERE id = :s"), {"s": shop_id}
        ).scalar_one()


def _seed_written_run(shop_id: uuid.UUID, card_id: uuid.UUID, approved_by: uuid.UUID) -> uuid.UUID:
    """A completed listing run on the card (approved by ``approved_by``) that wrote a title."""
    with owner_sync_engine() as engine, Session(engine) as session:
        product_id = session.execute(
            text("SELECT id FROM public.products WHERE shop_id = :s AND tiktok_product_id = :t"),
            {"s": shop_id, "t": PRODUCT_ID},
        ).scalar_one()
        card = session.get(ActionCard, card_id)
        assert card is not None
        card.status = "approved"
        card.approved_at = _now()
        session.add(
            ActionCardApproval(
                action_card_id=card_id,
                approved_by_user_id=approved_by,
                approved_at=_now(),
                card_snapshot={},
            )
        )
        run = WorkflowRun(
            shop_id=shop_id, product_id=product_id, action_card_id=card_id,
            workflow_key="optimize_product_2", subject_type="product",
            subject_ref=f"{product_id}#1", state={}, status="completed",
            stop_reason="final_response", prompt_version="v", prompt_sha256="a" * 64,
            write_mode="live", completed_at=_now(),
        )  # fmt: skip
        session.add(run)
        session.flush()
        session.add(
            RunWriteValue(
                shop_id=shop_id,
                workflow_run_id=run.id,
                tool_call_id="call_w1",
                tool_name="update_product_listing",
                tiktok_product_id=PRODUCT_ID,
                field="title",
                before_value=ORIGINAL_TITLE,
                after_value=JULI_TITLE,
                after_source="read_back",
            )
        )
        session.commit()
        return run.id


def _seller_headers(user_id: uuid.UUID, shop_id: uuid.UUID) -> dict[str, str]:
    token = pyjwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}", "X-Shop-Id": str(shop_id)}


@pytest.fixture
def revert_app(app, monkeypatch):
    """The P64 app with the TikTok live read and the Celery enqueue faked."""
    from juli_backend.api.routes import demo_run_changes

    queued: list[Any] = []

    async def _live(session, shop_id, tiktok_product_id, write_mode=None):
        return {"id": tiktok_product_id, "title": JULI_TITLE}

    app.dependency_overrides[demo_run_changes.get_live_product_reader] = lambda: _live
    monkeypatch.setattr(
        demo_run_changes,
        "_enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-revert",
    )
    app.state.queued = queued
    yield app
    reviewer_sandbox.forget_sync_slots()
    reviewer_accounts.forget_cached()
    reviewer_catalog.forget_cached()


def _assert_revert_landed(response, original: uuid.UUID, card_id: uuid.UUID, queued) -> None:
    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["reverts_run_id"] == str(original)
    assert data["status"] == "queued" and data["fields"] == ["title"]
    assert [str(r) for r in queued] == [data["run_id"]]
    with owner_sync_engine() as engine, engine.connect() as conn:
        revert = conn.execute(
            text(
                "SELECT status, action_card_id, reverts_run_id FROM public.workflow_runs "
                "WHERE id = :r"
            ),
            {"r": data["run_id"]},
        ).one()
        card = conn.execute(
            text("SELECT status, dismissed_at FROM public.action_cards WHERE id = :c"),
            {"c": card_id},
        ).one()
        reasons = conn.execute(
            text(
                "SELECT count(*) FROM public.decision_reasons "
                "WHERE action = 'revert' AND action_card_id = :c"
            ),
            {"c": card_id},
        ).scalar_one()
    assert revert.status == "queued" and revert.reverts_run_id == original
    assert revert.action_card_id == card_id
    # The card UPDATE that 500'd in production (P72): closed, as juli_app.
    assert card.status == "dismissed" and card.dismissed_at is not None
    assert reasons == 1


async def test_a_reviewer_reverts_its_own_run_on_the_sandbox_pin_as_juli_app(revert_app, world):
    async with await _client(revert_app) as client:
        # The reviewer's first request provisions its users row, which the approval names.
        me = await client.get("/v1/reviewer/me", headers=_headers(world["reviewer"]))
        assert me.status_code == 200, me.text
        original = _seed_written_run(world["sandbox"], world["card"], world["reviewer"])
        response = await client.post(
            f"/v1/demo/runs/{original}/revert",
            json=REASON,
            headers=_headers(world["reviewer"], world["sandbox"]),
        )

    assert set(revert_app.state.test_roles) == {"juli_app"}
    _assert_revert_landed(response, original, world["card"], revert_app.state.queued)
    with owner_sync_engine() as engine, engine.connect() as conn:
        audited = conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log "
                "WHERE action = 'reviewer_sandbox_revert' AND shop_id = :s"
            ),
            {"s": world["sandbox"]},
        ).scalar_one()
    assert audited == 1


async def test_b_a_seller_reverts_its_own_run_as_juli_app(revert_app, world):
    shop_id = world["production"]
    owner = _owner_of(shop_id)
    card_id = _seed_seller_card(shop_id)
    original = _seed_written_run(shop_id, card_id, owner)

    async with await _client(revert_app) as client:
        response = await client.post(
            f"/v1/demo/runs/{original}/revert",
            json=REASON,
            headers=_seller_headers(owner, shop_id),
        )

    assert set(revert_app.state.test_roles) == {"juli_app"}
    _assert_revert_landed(response, original, card_id, revert_app.state.queued)


def _seed_seller_card(shop_id: uuid.UUID) -> uuid.UUID:
    """The P64 world's product + card, on the seller's (production) shop."""
    from tests.integration.test_reviewer_sandbox_live_postgres import _seed_card

    with owner_sync_engine() as engine:
        return _seed_card(engine, shop_id)


# -- 2. duplicate catalog webhook ---------------------------------------------------------


def _webhook_shop() -> tuple[uuid.UUID, str]:
    numeric = str(7_100_000_000_000_000_000 + uuid.uuid4().int % 10**18)
    now = _now()
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("INSERT INTO public.users (id, phone) VALUES (:id, :phone)"),
            {"id": user_id, "phone": f"+1556{user_id.hex[:7]}"},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id, "
                " tiktok_numeric_shop_id, is_active, created_at, updated_at) "
                "VALUES (:id, :u, 'dup', :t, :num, true, :now, :now)"
            ),
            {
                "id": shop_id,
                "u": user_id,
                "t": f"dup-{shop_id.hex[:8]}",
                "num": numeric,
                "now": now,
            },
        )
    return shop_id, numeric


def _signals(shop_id: uuid.UUID) -> list[str]:
    with owner_sync_engine() as engine, engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT event_id FROM public.workflow_webhook_signals WHERE shop_id = :s"),
                {"s": shop_id},
            ).scalars()
        )


async def _deliver(event: TikTokWebhookPayload) -> None:
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "juli_app"
        dispatcher = TikTokWebhookDispatcher(side_effects=DatabaseWebhookSideEffects(session))
        await dispatcher.dispatch(event)
        await session.commit()


def _expiring(numeric: str) -> TikTokWebhookPayload:
    return TikTokWebhookPayload(
        type="UPCOMING_AUTHORIZATION_EXPIRATION",
        shop_id=numeric,
        timestamp=1_700_000_123,
        data={"expires_in_seconds": 86400},
    )


async def test_c_a_redelivered_catalog_webhook_is_a_no_op_as_juli_app():
    shop_id, numeric = _webhook_shop()

    await _deliver(_expiring(numeric))
    await _deliver(_expiring(numeric))

    assert len(_signals(shop_id)) == 1


async def test_c_concurrent_deliveries_of_one_event_store_one_signal_as_juli_app():
    """Both sessions pass the old read-then-insert check before either commits."""
    shop_id, numeric = _webhook_shop()

    await asyncio.gather(*(_deliver(_expiring(numeric)) for _ in range(4)))

    assert len(_signals(shop_id)) == 1


async def test_c_a_redelivered_deauthorization_does_not_pause_again_as_juli_app():
    """A retry of the deauthorization after the seller re-authorized must not re-pause."""
    shop_id, numeric = _webhook_shop()
    deauth = TikTokWebhookPayload(
        type="SELLER_DEAUTHORIZATION", shop_id=numeric, timestamp=1_700_000_456
    )

    await _deliver(deauth)
    with owner_sync_engine() as engine, engine.begin() as conn:
        paused = conn.execute(
            text("SELECT is_active FROM public.shops WHERE id = :s"), {"s": shop_id}
        ).scalar_one()
        conn.execute(text("UPDATE public.shops SET is_active = true WHERE id = :s"), {"s": shop_id})
    await _deliver(deauth)

    with owner_sync_engine() as engine, engine.connect() as conn:
        active = conn.execute(
            text("SELECT is_active FROM public.shops WHERE id = :s"), {"s": shop_id}
        ).scalar_one()
    assert paused is False
    assert active is True
    assert len(_signals(shop_id)) == 1
