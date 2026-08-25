"""Poll scope in action card refresh — Issue #1293.

The refresh path should only poll for shops that own the production-read
credential. A refresh for any other shop should skip polling (with a named
log reason) and proceed straight to scoring.

This ensures manual refreshes don't waste TikTok rate-limit budget on
unscoped polling, and don't monopolize worker slots for ~25 minutes doing
another shop's ingest.

Acceptance criteria:
1. A refresh for a shop with NO pollable credential does NOT invoke
   run_fujiwa_poll_cycle — it skips with reason 'shop_has_no_pollable_credential'
   and still reaches run_daily_scoring_for_shop.
2. A refresh for the shop that OWNS the production-read credential invokes
   run_fujiwa_poll_cycle (preserves today's behavior).
3. The poll decision is resolved from the DB (resolve_production_read_credential),
   not hardcoded.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from juli_backend.models.models import Shop, TikTokCredential, User
from juli_backend.services.action_cards.refresh import maybe_poll_tiktok_data


@pytest_asyncio.fixture
async def local_user(session, user_id):
    u = User(id=user_id, phone="+849305008990")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def production_shop(session, local_user):
    """The shop that owns the production-read credential."""
    s = Shop(
        id=uuid.uuid4(),
        user_id=local_user.id,
        shop_name="Production Shop",
        tiktok_shop_id="tiktok_shop_prod",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def sandbox_shop(session, local_user):
    """A different shop with no production-read credential."""
    s = Shop(
        id=uuid.uuid4(),
        user_id=local_user.id,
        shop_name="Sandbox Shop",
        tiktok_shop_id="tiktok_shop_sandbox",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def production_credential(session, production_shop):
    """Production-read credential for the production shop."""
    from datetime import datetime

    from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability

    cred = TikTokCredential(
        id=uuid.uuid4(),
        shop_id=production_shop.id,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher="test-cipher",
        access_token="test-token",
        refresh_token="test-refresh",
        token_expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
        scopes="shop.order:read product.product:read",
    )
    session.add(cred)
    await session.flush()
    return cred


# --- AC1: refresh for a shop with no pollable credential skips polling -------


@pytest.mark.asyncio
async def test_refresh_for_non_production_shop_skips_poll(
    session, sandbox_shop, caplog, monkeypatch
):
    """A refresh for a shop that doesn't own the production credential
    should NOT invoke run_fujiwa_poll_cycle. It should log a skip reason
    and return without raising.

    RED: This test fails on pre-#1293 code because maybe_poll_tiktok_data
    doesn't check shop_id and tries to run the poll even for non-production shops.
    """
    # Set up env vars so poll prerequisites look satisfied.
    # The poll would run, EXCEPT the shop doesn't own the production credential.
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://test.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")

    # Mock run_fujiwa_poll_cycle so we can assert it wasn't called.
    mock_poll_cycle = AsyncMock()

    with patch(
        "juli_backend.workers.services.polling.run_fujiwa_poll_cycle",
        mock_poll_cycle,
    ):
        with caplog.at_level(logging.INFO):
            await maybe_poll_tiktok_data(session, sandbox_shop.id)

    # The poll runner should NOT have been called because sandbox_shop
    # doesn't own the production-read credential.
    mock_poll_cycle.assert_not_called()

    # A skip reason should be logged with the action_card_refresh_poll_skipped key.
    log_records = [
        r for r in caplog.records if r.name == "juli_backend.services.action_cards.refresh"
    ]
    skip_logs = [
        r
        for r in log_records
        if hasattr(r, "msg") and "action_card_refresh_poll_skipped" in (r.msg or "")
    ]
    assert len(skip_logs) > 0, (
        f"Expected 'action_card_refresh_poll_skipped' log, got: {[r.msg for r in log_records]}"
    )


@pytest.mark.asyncio
async def test_refresh_for_production_shop_invokes_poll(
    session, production_shop, production_credential, monkeypatch
):
    """A refresh for the shop that owns the production credential
    should still invoke run_fujiwa_poll_cycle. This preserves today's
    behavior for the intended polling shop."""
    # Set up env vars for poll prerequisites.
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://test.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")

    # Mock the dependencies that run_fujiwa_poll_cycle needs.
    mock_poll_cycle = AsyncMock()

    with patch(
        "juli_backend.workers.services.polling.run_fujiwa_poll_cycle",
        mock_poll_cycle,
    ):
        await maybe_poll_tiktok_data(session, production_shop.id)

    # run_fujiwa_poll_cycle should have been called for the production shop.
    mock_poll_cycle.assert_called_once()


@pytest.mark.asyncio
async def test_poll_credential_resolved_from_db(
    session, production_shop, production_credential, local_user, monkeypatch
):
    """The poll decision is resolved from the DB, not hardcoded.

    The function should call resolve_production_read_credential to get
    the production-read credential and compare its shop_id to the
    requested shop_id. This proves the decision is DB-driven, not
    environment-driven. A shop with a different id should not poll,
    even though the production credential exists."""
    # Create another shop that definitely doesn't own the production credential.
    other_shop = Shop(
        id=uuid.uuid4(),
        user_id=local_user.id,
        shop_name="Other Shop",
        tiktok_shop_id="tiktok_shop_other",
    )
    session.add(other_shop)
    await session.flush()

    # Set up env vars so poll prerequisites appear satisfied.
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://test.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")

    mock_poll_cycle = AsyncMock()

    with patch(
        "juli_backend.workers.services.polling.run_fujiwa_poll_cycle",
        mock_poll_cycle,
    ):
        # Call for the other_shop, not the production_shop.
        await maybe_poll_tiktok_data(session, other_shop.id)

    # run_fujiwa_poll_cycle should NOT have been called because other_shop
    # is not the shop that owns the production-read credential.
    mock_poll_cycle.assert_not_called()
