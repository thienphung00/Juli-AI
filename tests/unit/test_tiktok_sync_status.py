"""P101 W2 B-4 / B-5: the shop's sync status (state, backfill n/90, data-through, late).

Pure derivation tests plus the HTTP route, and the pause / resume state of a
credential that fails its refresh and is re-authorised.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from juli_backend.models.ingestion import (
    BOOTSTRAP_FAILED,
    BOOTSTRAP_HISTORY_DONE,
    BOOTSTRAP_HISTORY_RUNNING,
    ShopIngestionState,
)
from juli_backend.models.models import User
from juli_backend.repositories import ShopIngestionStateRepo, TikTokCredentialRepo
from juli_backend.services.tiktok_sync_status import build_sync_status, shop_sync_status
from tests.unit.test_onboarding_speed import _client, app  # noqa: F401  (fixture re-export)
from tests.unit.test_shop_ingestion import _make_shop

# 10:00 Asia/Ho_Chi_Minh on 20 Nov 2026 -> yesterday is 19 Nov.
AFTER_NINE = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
BEFORE_NINE = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)  # 03:00 VN, 20 Nov


def _state(
    *,
    status: str = BOOTSTRAP_HISTORY_DONE,
    through: date | None = date(2026, 11, 19),
    earliest: date | None = date(2026, 8, 1),
    history_done_at: datetime | None = None,
) -> ShopIngestionState:
    return ShopIngestionState(
        shop_id=None,
        status=status,
        fast_done_at=datetime(2026, 10, 1),
        history_earliest_date=earliest,
        analytics_through_date=through,
        history_done_at=history_done_at,
    )


def test_a_shop_without_a_credential_is_disconnected():
    assert build_sync_status([], None, now=AFTER_NINE).state == "disconnected"


def test_a_walk_under_90_days_is_backfilling_with_the_day_count():
    state = _state(
        status=BOOTSTRAP_HISTORY_RUNNING, through=date(2026, 11, 19), earliest=date(2026, 10, 1)
    )
    status = build_sync_status(["active"], state, now=AFTER_NINE)
    assert status.state == "backfilling" and status.backfilling
    assert (status.history_days_done, status.history_days_total) == (50, 90)
    assert status.data_through == date(2026, 11, 19) and not status.late


def test_a_new_shop_with_no_ingestion_row_backfills_from_zero():
    status = build_sync_status(["active"], None, now=AFTER_NINE)
    assert status.state == "backfilling" and status.history_days_done == 0


def test_the_count_stops_at_90_and_the_shop_is_active():
    status = build_sync_status(["active"], _state(earliest=date(2026, 1, 1)), now=AFTER_NINE)
    assert status.history_days_done == 90 and status.state == "active" and not status.backfilling


def test_a_walk_that_ended_early_is_not_a_backfill():
    state = _state(earliest=date(2026, 11, 1), history_done_at=datetime(2026, 11, 2))
    status = build_sync_status(["active"], state, now=AFTER_NINE)
    assert status.state == "active" and not status.backfilling


def test_yesterday_missing_is_late_only_after_nine_in_vietnam():
    stale = _state(through=date(2026, 11, 18), earliest=date(2026, 1, 1))
    assert build_sync_status(["active"], stale, now=AFTER_NINE).late
    assert build_sync_status(["active"], stale, now=AFTER_NINE).state == "degraded"
    assert not build_sync_status(["active"], stale, now=BEFORE_NINE).late
    fresh = _state(through=date(2026, 11, 19), earliest=date(2026, 1, 1))
    assert not build_sync_status(["active"], fresh, now=AFTER_NINE).late


def test_a_failed_ingestion_is_degraded_and_a_reauth_credential_wins():
    failed = _state(status=BOOTSTRAP_FAILED, earliest=date(2026, 1, 1))
    assert build_sync_status(["active"], failed, now=AFTER_NINE).state == "degraded"
    assert build_sync_status(["active", "needs_reauth"], failed, now=AFTER_NINE).state == (
        "needs_reauth"
    )


@pytest.mark.asyncio
async def test_a_failed_refresh_reads_needs_reauth_and_reauth_resumes_it(session):
    shop = await _make_shop(session, label="b4pause")
    repo = TikTokCredentialRepo(session)
    credential = await repo.get_by_shop(shop.id)
    assert (await shop_sync_status(session, shop.id, now=AFTER_NINE)).state == "backfilling"

    await repo.mark_needs_reauth(credential.id, "refresh failed")
    await session.commit()
    paused = await shop_sync_status(session, shop.id, now=AFTER_NINE)
    assert paused.state == "needs_reauth" and not paused.backfilling

    # The OAuth callback re-activates the row (core/security/tiktok_oauth.py).
    credential.status = "active"
    await session.commit()
    assert (await shop_sync_status(session, shop.id, now=AFTER_NINE)).state == "backfilling"


@pytest.mark.asyncio
async def test_the_route_returns_progress_and_data_through(app, session):  # noqa: F811
    shop = await _make_shop(session, label="b5route")
    await ShopIngestionStateRepo(session).update(
        shop.id,
        fast_done_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        history_earliest_date=date(2026, 10, 1),
        analytics_through_date=date(2026, 11, 19),
        status=BOOTSTRAP_HISTORY_RUNNING,
    )
    await session.commit()
    user = await session.get(User, shop.user_id)
    async with _client(app, user, shop) as client:
        resp = await client.get("/v1/shops/me/sync-status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "backfilling" and body["backfilling"] is True
    assert (body["history_days_done"], body["history_days_total"]) == (50, 90)
    assert body["data_through"] == "2026-11-19"
    assert set(body) == {
        "state",
        "backfilling",
        "history_days_done",
        "history_days_total",
        "data_through",
        "late",
    }


@pytest.mark.asyncio
async def test_the_route_needs_a_signed_in_shop(app):  # noqa: F811
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/shops/me/sync-status")
    assert resp.status_code in (401, 403, 422)
