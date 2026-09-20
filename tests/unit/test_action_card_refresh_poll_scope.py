"""Poll scope in action card refresh — Issue #1293, inverted by #1995.

#1293's contract was: only the shop owning the single configured production-read
credential polls; every other shop logs `shop_has_no_pollable_credential` and
skips. That was right while one merchant was the only merchant Juli could reach.
It is wrong now, and it is the exact silent no-op #1365/#1995 exist to remove —
a connecting seller got scored over an empty database with nothing raised
anywhere (ADR-103 d.11: "A seller who connected and got nothing is a bug, never
a quiet zero").

The contract this file now pins:

1. A shop holding its own read credential polls, under its OWN credential —
   whether that credential is `PRODUCTION_READ` (Juli's configured merchant) or
   `SELLER_CONNECT` (a seller who has just finished OAuth).
2. A shop holding NO read credential raises `NoReadCredentialForShop`. It does
   not skip, does not log a skip reason, and does not return `None`.
3. An unconfigured deployment (no TikTok/Redis env) still skips, and still
   must: that is a deployment state, not a claim about this shop's data.

Cross-shop isolation and the not-swallowed proof live in
`tests/unit/test_per_shop_poll_consumer.py`.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from juli_backend.core.security.credential_resolver import NoReadCredentialForShop
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
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
    """The shop that owns the configured production-read credential."""
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
async def seller_shop(session, local_user):
    """A connecting seller's shop — its own merchant, its own credential."""
    s = Shop(
        id=uuid.uuid4(),
        user_id=local_user.id,
        shop_name="Seller Shop",
        tiktok_shop_id="tiktok_shop_seller",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def credential_free_shop(session, local_user):
    """A shop holding nothing read-capable."""
    s = Shop(
        id=uuid.uuid4(),
        user_id=local_user.id,
        shop_name="No Credential Shop",
        tiktok_shop_id="tiktok_shop_none",
    )
    session.add(s)
    await session.flush()
    return s


async def _add_credential(session, shop, *, merchant, capability, token):
    cred = TikTokCredential(
        id=uuid.uuid4(),
        shop_id=shop.id,
        merchant_authorization_id=merchant,
        capability=capability,
        shop_cipher=f"cipher-{token}",
        access_token=token,
        refresh_token=f"refresh-{token}",
        token_expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
        scopes="shop.order:read product.product:read",
    )
    session.add(cred)
    await session.flush()
    return cred


@pytest_asyncio.fixture
async def production_credential(session, production_shop):
    return await _add_credential(
        session,
        production_shop,
        merchant=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        token="production-token",
    )


@pytest_asyncio.fixture
async def seller_credential(session, seller_shop):
    return await _add_credential(
        session,
        seller_shop,
        merchant="seller_own_merchant_4242",
        capability=TikTokCapability.SELLER_CONNECT.value,
        token="seller-token",
    )


@pytest.fixture
def poll_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-secret")
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://test.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")


@pytest.mark.asyncio
async def test_shop_without_a_read_credential_raises_rather_than_skipping(
    session, credential_free_shop, poll_env, caplog
):
    """AC2. The behaviour #1995 exists to install.

    RED before #1995: `maybe_poll_tiktok_data` returned `None` and logged
    `shop_has_no_pollable_credential`, so the refresh carried on and scored the
    shop over an empty database.
    """
    mock_poll_cycle = AsyncMock()

    with patch("juli_backend.workers.services.polling.run_fujiwa_poll_cycle", mock_poll_cycle):
        with caplog.at_level(logging.INFO):
            with pytest.raises(NoReadCredentialForShop):
                await maybe_poll_tiktok_data(session, credential_free_shop.id)

    mock_poll_cycle.assert_not_called()
    skip_logs = [
        r
        for r in caplog.records
        if r.name == "juli_backend.services.action_cards.refresh"
        and "action_card_refresh_poll_skipped" in (r.msg or "")
    ]
    assert skip_logs == [], (
        "the refusal must not also be logged as a skip -- a skip line is what made "
        f"this silent in the first place; got {[r.msg for r in skip_logs]}"
    )


@pytest.mark.asyncio
async def test_configured_production_shop_still_polls(
    session, production_shop, production_credential, poll_env
):
    """AC1, unchanged half: Juli's own merchant keeps polling exactly as before."""
    mock_poll_cycle = AsyncMock()

    with patch("juli_backend.workers.services.polling.run_fujiwa_poll_cycle", mock_poll_cycle):
        await maybe_poll_tiktok_data(session, production_shop.id)

    mock_poll_cycle.assert_called_once()
    assert mock_poll_cycle.call_args.kwargs["shop_id"] == production_shop.id


@pytest.mark.asyncio
async def test_a_connecting_seller_now_polls_too(session, seller_shop, seller_credential, poll_env):
    """AC1, the half that was impossible before #1995.

    RED before #1995: the shop-id comparison against the configured merchant's
    credential returned `None` here, so no seller could ever poll.
    """
    mock_poll_cycle = AsyncMock()

    with patch("juli_backend.workers.services.polling.run_fujiwa_poll_cycle", mock_poll_cycle):
        await maybe_poll_tiktok_data(session, seller_shop.id)

    mock_poll_cycle.assert_called_once()
    assert mock_poll_cycle.call_args.kwargs["shop_id"] == seller_shop.id


@pytest.mark.asyncio
async def test_unconfigured_deployment_still_skips(
    session, credential_free_shop, monkeypatch, caplog
):
    """AC3. The one remaining skip, and the reason it is still a skip."""
    for key in ("TIKTOK_APP_KEY", "TIKTOK_APP_SECRET", "TIKTOK_REDIRECT_URI", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)

    mock_poll_cycle = AsyncMock()

    with patch("juli_backend.workers.services.polling.run_fujiwa_poll_cycle", mock_poll_cycle):
        with caplog.at_level(logging.INFO):
            assert await maybe_poll_tiktok_data(session, credential_free_shop.id) is None

    mock_poll_cycle.assert_not_called()
    reasons = [
        getattr(r, "reason", None)
        for r in caplog.records
        if "action_card_refresh_poll_skipped" in (r.msg or "")
    ]
    assert "missing_tiktok_or_redis_env" in reasons
