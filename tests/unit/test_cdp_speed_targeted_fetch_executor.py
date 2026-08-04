"""Unit tests for targeted fetch executor shop-scoped credential isolation (#627)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import Shop, TikTokCredential, User
from juli_backend.services.cdp_speed.targeted_fetch_executor import (
    BRONZE_SUPPORTED_RESOURCE_ATTRS,
    PartnerFetchEnv,
    credential_belongs_to_job,
    execute_targeted_fetch_to_bronze,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import plan_targeted_fetch


def _credential(*, shop_id: uuid.UUID) -> TikTokCredential:
    return TikTokCredential(
        id=uuid.uuid4(),
        shop_id=shop_id,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        access_token="token",
        refresh_token="refresh",
        token_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


@pytest_asyncio.fixture
async def shop_session():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        execution_options={
            "schema_translate_map": {
                "ops": None,
                "bronze": None,
                "gold": None,
                "silver": None,
            }
        },
    )
    async with eng.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[User.__table__, Shop.__table__],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84901234628", display_name="Credential Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Credential Test Shop",
            tiktok_shop_id="shop_cred_627",
        )
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


class TestCredentialBelongsToJob:
    def test_accepts_matching_production_read_credential(self):
        shop_id = uuid.uuid4()
        assert credential_belongs_to_job(_credential(shop_id=shop_id), shop_id) is True

    def test_rejects_credential_for_different_shop(self):
        assert credential_belongs_to_job(_credential(shop_id=uuid.uuid4()), uuid.uuid4()) is False

    def test_rejects_non_production_read_capability(self):
        shop_id = uuid.uuid4()
        cred = _credential(shop_id=shop_id)
        cred.capability = TikTokCapability.SANDBOX_WRITE.value
        assert credential_belongs_to_job(cred, shop_id) is False


@pytest.mark.asyncio
async def test_execute_skips_when_resolved_credential_shop_mismatch(shop_session):
    session, shop = shop_session
    other_shop_id = uuid.uuid4()
    fetch_plan = plan_targeted_fetch(
        event_type="ORDER_STATUS_CHANGE",
        shop_id=shop.tiktok_shop_id,
    )

    async def wrong_shop_credential(sess, shop_id):
        del sess, shop_id
        return _credential(shop_id=other_shop_id)

    tracker = await execute_targeted_fetch_to_bronze(
        session,
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        fetch_plan=fetch_plan,
        idempotency_key="cred-mismatch-test",
        env=PartnerFetchEnv(
            app_key="test_key",
            app_secret="test_secret",
            redirect_uri="https://example.com/callback",
            redis_url="redis://localhost:6379/0",
        ),
        resolve_credential=wrong_shop_credential,
    )

    assert tracker.appended_count == 0


@pytest.mark.asyncio
async def test_execute_skips_when_refreshed_credential_shop_mismatch(shop_session, monkeypatch):
    session, shop = shop_session
    fetch_plan = plan_targeted_fetch(
        event_type="ORDER_STATUS_CHANGE",
        shop_id=shop.tiktok_shop_id,
    )
    job_cred = _credential(shop_id=shop.id)
    other_cred = _credential(shop_id=uuid.uuid4())

    async def matching_resolver(sess, shop_id):
        del sess, shop_id
        return job_cred

    oauth_mock = MagicMock()
    oauth_mock.refresh_merchant_tokens = AsyncMock(return_value=other_cred)
    monkeypatch.setattr(
        "juli_backend.services.cdp_speed.targeted_fetch_executor.TikTokOAuthService",
        lambda **kwargs: oauth_mock,
    )

    env = PartnerFetchEnv(
        app_key="k",
        app_secret="s",
        redirect_uri="https://example.com/cb",
        redis_url="redis://localhost:6379/0",
    )

    tracker = await execute_targeted_fetch_to_bronze(
        session,
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        fetch_plan=fetch_plan,
        idempotency_key="refresh-mismatch-test",
        env=env,
        resolve_credential=matching_resolver,
    )

    assert tracker.appended_count == 0
    oauth_mock.refresh_merchant_tokens.assert_awaited_once_with(
        PRODUCTION_AUTH_ID,
        TikTokCapability.PRODUCTION_READ,
    )


def test_executor_module_does_not_import_workers():
    import juli_backend.services.cdp_speed.targeted_fetch_executor as executor

    source = open(executor.__file__, encoding="utf-8").read()
    assert "workers" not in source
    assert "core.security.tiktok_oauth" not in source


def test_bronze_supported_resources_are_orders_and_returns_only():
    assert BRONZE_SUPPORTED_RESOURCE_ATTRS == frozenset({"orders", "returns"})


def test_executor_module_does_not_instantiate_quota_guarded_resources_in_plan():
    """Quota guards prevent A-38/A-39 and A-31/A-33 from reaching the executor."""
    from juli_backend.services.cdp_speed.quota_guard import QUOTA_GUARDED_RESOURCE_NAMES
    from juli_backend.services.cdp_speed.targeted_fetch_planner import plan_targeted_fetch

    # For all material events, verify no guarded resources are in the fetch plan
    material_events = [
        "ORDER_STATUS_CHANGE",
        "REVERSE_STATUS_UPDATE",
        "PRODUCT_STATUS_CHANGE",
        "RETURN_STATUS_CHANGE",
        "INVENTORY_STATUS_CHANGE",
        "ACTIVITY_STATUS_CHANGE",
        "REFUND_SUCCESS",
        "INVENTORY_CHANGED",
    ]

    for event_type in material_events:
        plan = plan_targeted_fetch(
            event_type=event_type,
            shop_id="test_shop",
            payload_hints={"activity_id": "test-act"}
            if event_type == "ACTIVITY_STATUS_CHANGE"
            else None,
        )
        plan_names = frozenset(step.name for step in plan.resources)
        assert plan_names.isdisjoint(QUOTA_GUARDED_RESOURCE_NAMES), (
            f"Event {event_type} plan contains guarded resources: "
            f"{plan_names & QUOTA_GUARDED_RESOURCE_NAMES}"
        )
