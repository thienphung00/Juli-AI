"""Phase 2 webhook catalog tests — issue #354 (one behavior per catalog type)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import ShopsRepo, WorkflowWebhookSignalsRepo
from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.schemas import TikTokWebhookPayload
from juli_backend.services.tiktok.webhook import resolve_ingest_channel
from juli_backend.services.tiktok.webhook_catalog import (
    PHASE2_CATALOG_IDS,
    is_deferred_webhook_type,
    resolve_catalog_entry,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
WEBHOOKS_DOC = REPO_ROOT / "docs/integrations/tiktok_api/webhooks.md"

CATALOG_FIXTURES: list[tuple[int, str, str, str]] = [
    (1, "ORDER_STATUS_CHANGE", "order_status_change", "tiktok.order_status_change"),
    (2, "REVERSE_STATUS_UPDATE", "reverse_status_update", "tiktok.reverse_status_update"),
    (3, "RECIPIENT_ADDRESS_UPDATE", "recipient_address_update", "tiktok.recipient_address_update"),
    (4, "PACKAGE_UPDATE", "package_update", "tiktok.package_update"),
    (5, "PRODUCT_STATUS_CHANGE", "product_status_change", "tiktok.product_status_change"),
    (6, "SELLER_DEAUTHORIZATION", "seller_deauthorization", "tiktok.account.lifecycle"),
    (7, "UPCOMING_AUTHORIZATION_EXPIRATION", "auth_expiration_warning", "tiktok.account.lifecycle"),
    (11, "CANCELLATION_STATUS_CHANGE", "cancellation_status_change", "tiktok.cancellation_status_change"),
    (12, "RETURN_STATUS_CHANGE", "return_status_change", "tiktok.returns.raw"),
    (21, "INBOUND_FBT_ORDER_STATUS_CHANGE", "inbound_fbt_order_status", "tiktok.inbound_fbt_order_status"),
    (24, "FBT_INVENTORY_UPDATE", "fbt_inventory_update", "tiktok.fbt_inventory_update"),
    (27, "INVENTORY_STATUS_CHANGE", "inventory_status_change", "tiktok.inventory_status_change"),
    (37, "PRODUCT_AUDIT_STATUS_CHANGE", "product_audit_status_change", "tiktok.product_audit_status_change"),
    (39, "ACTIVITY_STATUS_CHANGE", "activity_status_change", "tiktok.activity_status_change"),
    (58, "FBT_MCF_ORDER_STATUS", "fbt_mcf_order_status", "tiktok.fbt_mcf_order_status"),
    (64, "AFTERSALES_REQUEST_STATUS_UPDATE", "aftersales_request_status", "tiktok.aftersales_request_status"),
    (65, "RMA_STATUS_UPDATE", "rma_status_update", "tiktok.rma_status_update"),
    (67, "REFUND_SUCCESS", "refund_success", "tiktok.refund_success"),
    (68, "INVENTORY_CHANGED", "inventory_changed", "tiktok.inventory.raw"),
]


class TestPhase2CatalogRegistry:
    def test_registered_phase2_catalog_webhooks_match_execution_layer(self):
        assert sorted(PHASE2_CATALOG_IDS) == sorted(
            [
                1,
                2,
                3,
                4,
                5,
                6,
                7,
                11,
                12,
                21,
                24,
                27,
                37,
                39,
                58,
                64,
                65,
                67,
                68,
            ]
        )

    @pytest.mark.parametrize(
        ("catalog_id", "event_type", "handler_name", "channel"),
        CATALOG_FIXTURES,
        ids=[str(item[0]) for item in CATALOG_FIXTURES],
    )
    def test_catalog_entry_resolves_type_handler_and_channel(
        self, catalog_id, event_type, handler_name, channel
    ):
        entry = resolve_catalog_entry(event_type)
        assert entry is not None
        assert entry.catalog_id == catalog_id
        assert entry.handler_name == handler_name
        assert entry.etl_channel == channel

    @pytest.mark.parametrize(
        ("catalog_id", "event_type", "handler_name", "_channel"),
        CATALOG_FIXTURES,
        ids=[f"dispatch-{item[0]}" for item in CATALOG_FIXTURES],
    )
    @pytest.mark.asyncio
    async def test_dispatcher_routes_catalog_type(
        self, catalog_id, event_type, handler_name, _channel
    ):
        dispatcher = TikTokWebhookDispatcher()
        event = TikTokWebhookPayload(
            type=event_type,
            shop_id="7658073774813611784",
            data={"order_id": "1", "return_id": "2", "product_id": "3"},
        )
        assert await dispatcher.dispatch(event) == handler_name

    @pytest.mark.parametrize(
        ("catalog_id", "event_type", "_handler", "channel"),
        CATALOG_FIXTURES,
        ids=[f"channel-{item[0]}" for item in CATALOG_FIXTURES],
    )
    def test_resolve_ingest_channel_uses_catalog(self, catalog_id, event_type, _handler, channel):
        assert resolve_ingest_channel(event_type) == channel


class TestDeferredWebhookTypes:
    @pytest.mark.parametrize(
        "event_type",
        [
            "AFFILIATE_COMMISSION_CHANGE",
            "CREATOR_AFFILIATE_LINK",
            "LIVESTREAM_SESSION_END",
            "SETTLEMENT_COMPLETED",
            "NEW_CONVERSATION",
            "NEW_MESSAGE",
        ],
    )
    def test_deferred_types_not_in_phase2_catalog(self, event_type):
        assert is_deferred_webhook_type(event_type) is True
        assert resolve_catalog_entry(event_type) is None

    @pytest.mark.asyncio
    async def test_out_of_scope_webhook_types_not_routed_in_phase2_paths(self):
        dispatcher = TikTokWebhookDispatcher()
        event = TikTokWebhookPayload(type="AFFILIATE_COMMISSION_CHANGE", shop_id="s1")
        assert await dispatcher.dispatch(event) == "deferred_out_of_scope"


class TestWorkflowSignals:
    @pytest.mark.asyncio
    async def test_catalog_handler_emits_workflow_signal(self, session, user_id):
        user = User(id=user_id, phone="+84901234567")
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="Fujiwa",
            tiktok_shop_id="7658073774813611784",
        )
        session.add_all([user, shop])
        await session.flush()

        from juli_backend.services.tiktok.webhook_handlers import (
            DatabaseWebhookSideEffects,
        )

        effects = DatabaseWebhookSideEffects(session)
        dispatcher = TikTokWebhookDispatcher(side_effects=effects)
        event = TikTokWebhookPayload(
            type="ORDER_STATUS_CHANGE",
            shop_id="7658073774813611784",
            timestamp=1700000000,
            data={"order_id": "577000000000001", "order_status": "AWAITING_SHIPMENT"},
        )
        await dispatcher.dispatch(event)
        await session.flush()

        repo = WorkflowWebhookSignalsRepo(session)
        signals = await repo.list_for_shop(shop.id)
        assert len(signals) == 1
        assert signals[0].catalog_id == 1
        assert signals[0].event_type == "ORDER_STATUS_CHANGE"
        assert "process_order" in signals[0].workflow_keys


class TestAccountLifecycleWebhooks:
    @pytest.mark.asyncio
    async def test_seller_deauthorization_pauses_matching_shop_only(
        self, session, user_id, other_user_id
    ):
        user_a = User(id=user_id, phone="+84901111111")
        user_b = User(id=other_user_id, phone="+84902222222")
        shop_a = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="Fujiwa",
            tiktok_shop_id="7658073774813611784",
            is_active=True,
        )
        shop_b = Shop(
            id=uuid.uuid4(),
            user_id=other_user_id,
            shop_name="Other",
            tiktok_shop_id="7658096633384781588",
            is_active=True,
        )
        session.add_all([user_a, user_b, shop_a, shop_b])
        await session.flush()

        from juli_backend.services.tiktok.webhook_handlers import (
            DatabaseWebhookSideEffects,
        )

        effects = DatabaseWebhookSideEffects(session)
        dispatcher = TikTokWebhookDispatcher(side_effects=effects)
        event = TikTokWebhookPayload(
            type="SELLER_DEAUTHORIZATION",
            shop_id="7658073774813611784",
            data={"reason": "seller_revoked"},
        )
        await dispatcher.dispatch(event)
        await session.flush()

        shops = ShopsRepo(session)
        refreshed_a = await shops.get_by_tiktok_id("7658073774813611784")
        refreshed_b = await shops.get_by_tiktok_id("7658096633384781588")
        assert refreshed_a is not None and refreshed_a.is_active is False
        assert refreshed_b is not None and refreshed_b.is_active is True

        signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(shop_a.id)
        assert len(signals) == 1
        assert signals[0].intent == "pause_automation"

    @pytest.mark.asyncio
    async def test_auth_expiration_emits_reauth_intent(self, session, user_id):
        user = User(id=user_id, phone="+84903333333")
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name="Fujiwa",
            tiktok_shop_id="7658073774813611784",
        )
        session.add_all([user, shop])
        await session.flush()

        from juli_backend.services.tiktok.webhook_handlers import (
            DatabaseWebhookSideEffects,
        )

        effects = DatabaseWebhookSideEffects(session)
        dispatcher = TikTokWebhookDispatcher(side_effects=effects)
        event = TikTokWebhookPayload(
            type="UPCOMING_AUTHORIZATION_EXPIRATION",
            shop_id="7658073774813611784",
            data={"expires_in_seconds": 86400},
        )
        await dispatcher.dispatch(event)
        await session.flush()

        signals = await WorkflowWebhookSignalsRepo(session).list_for_shop(shop.id)
        assert len(signals) == 1
        assert signals[0].catalog_id == 7
        assert signals[0].intent == "re_auth_required"


class TestWebhookDedupEventId:
    def test_webhook_payload_dedupe_via_etl_event_id_path(self):
        from juli_backend.services.etl.event_id import extract_event_id

        payload = {
            "type": "ORDER_STATUS_CHANGE",
            "shop_id": "7658073774813611784",
            "timestamp": 1700000000,
            "data": {"order_id": "577000000000001"},
        }
        first = extract_event_id(
            channel="tiktok.order_status_change",
            shop_key="7658073774813611784",
            payload=payload,
        )
        second = extract_event_id(
            channel="tiktok.order_status_change",
            shop_key="7658073774813611784",
            payload=payload,
        )
        assert first == second
        assert first.startswith("wh:")


class TestWebhookDocsContract:
    def test_webhooks_md_confirmed_or_unknown_event_type_names(self):
        text = WEBHOOKS_DOC.read_text(encoding="utf-8")
        assert "ORDER_STATUS_CHANGE" in text
        assert "**UNKNOWN**" in text
        assert "Phase 2 catalog" in text

    def test_webhooks_md_documented_polling_coexistence(self):
        text = WEBHOOKS_DOC.read_text(encoding="utf-8")
        assert "Webhook vs polling" in text
        assert "authoritative reconciliation" in text
        assert "polling remains the backstop" in text.lower() or "backstop" in text
