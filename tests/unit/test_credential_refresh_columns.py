"""TDD tests for #1230 (AGT-W4A-DP, ADR-081 decision 7) — five additive
``tiktok_credentials`` columns plus three ``TikTokCredentialRepo`` methods.

Pure persistence: no beat, no lazy trigger, no reactive layer. Those land in
#1231/#1232. This file only proves the schema and the three new repo methods
behave as ADR-081 decision 7 specifies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import TikTokCredential, User
from juli_backend.repositories.repos import ShopsRepo, TikTokCredentialRepo

pytestmark = pytest.mark.asyncio


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


_shop_counter = 0


async def _seed_shop(session) -> object:
    global _shop_counter
    _shop_counter += 1
    user = User(id=uuid.uuid4(), phone=f"+8490111{_shop_counter:04d}")
    session.add(user)
    await session.flush()
    shop = await ShopsRepo(session).create(user.id, "Credential Columns Test Shop")
    return shop


async def _create_credential(
    session,
    *,
    shop_id,
    token_expires_at: datetime,
    access_token: str = "access-token",
    refresh_token: str = "refresh-token",
) -> TikTokCredential:
    return await TikTokCredentialRepo(session).create(
        shop_id=shop_id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=token_expires_at,
    )


class TestNewColumnDefaults:
    async def test_orm_insert_without_status_reads_back_active(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(days=7)
        )

        assert credential.status == "active"

        fetched = await session.get(TikTokCredential, credential.id)
        assert fetched.status == "active"

    async def test_refresh_count_defaults_to_zero_not_null(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(days=7)
        )

        assert credential.refresh_count == 0
        assert credential.refresh_count is not None

    async def test_pre_migration_shaped_row_reads_back_none_not_synthesized(self, session, user_id):
        """A row inserted with only the pre-#1230 column set (no new columns
        named at all) must read back None for the three nullable additions --
        never a synthesized value -- while status/refresh_count still pick up
        their table-level defaults."""
        shop = await _seed_shop(session)
        credential_id = uuid.uuid4()
        expires_at = _utc_now() + timedelta(days=7)

        await session.execute(
            text(
                """
                INSERT INTO tiktok_credentials
                    (id, shop_id, access_token, refresh_token, token_expires_at)
                VALUES
                    (:id, :shop_id, :access_token, :refresh_token, :token_expires_at)
                """
            ),
            {
                "id": credential_id.hex,
                "shop_id": shop.id.hex,
                "access_token": "raw-access-token",
                "refresh_token": "raw-refresh-token",
                "token_expires_at": expires_at,
            },
        )
        await session.flush()

        result = await session.execute(
            select(TikTokCredential).where(TikTokCredential.id == credential_id)
        )
        row = result.scalar_one()

        assert row.last_refreshed_at is None
        assert row.last_refresh_error is None
        assert row.refresh_token_expires_at is None
        assert row.status == "active"
        assert row.refresh_count == 0


class TestMarkRefreshed:
    async def test_mark_refreshed_sets_token_triad_and_health_signal(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        new_expiry = _utc_now() + timedelta(days=7)

        updated = await TikTokCredentialRepo(session).mark_refreshed(
            credential.id,
            "new-access-token",
            "new-refresh-token",
            new_expiry,
        )

        assert updated.access_token == "new-access-token"
        assert updated.refresh_token == "new-refresh-token"
        assert updated.token_expires_at == new_expiry
        assert updated.last_refreshed_at is not None
        assert updated.refresh_count == 1

    async def test_mark_refreshed_increments_refresh_count_by_exactly_one_per_call(
        self, session, user_id
    ):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )

        repo = TikTokCredentialRepo(session)
        first = await repo.mark_refreshed(credential.id, "t1", "r1", _utc_now() + timedelta(days=1))
        assert first.refresh_count == 1

        second = await repo.mark_refreshed(
            credential.id, "t2", "r2", _utc_now() + timedelta(days=1)
        )
        assert second.refresh_count == 2

        third = await repo.mark_refreshed(credential.id, "t3", "r3", _utc_now() + timedelta(days=1))
        assert third.refresh_count == 3

    async def test_mark_refreshed_clears_previously_set_last_refresh_error(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        repo = TikTokCredentialRepo(session)
        await repo.mark_needs_reauth(credential.id, "vendor 105002 expired")

        refreshed = await repo.mark_refreshed(
            credential.id, "t1", "r1", _utc_now() + timedelta(days=1)
        )

        assert refreshed.last_refresh_error is None

    async def test_mark_refreshed_opportunistically_sets_refresh_token_expires_at(
        self, session, user_id
    ):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        refresh_token_expiry = _utc_now() + timedelta(days=30)

        updated = await TikTokCredentialRepo(session).mark_refreshed(
            credential.id,
            "t1",
            "r1",
            _utc_now() + timedelta(days=1),
            refresh_token_expires_at=refresh_token_expiry,
        )

        assert updated.refresh_token_expires_at == refresh_token_expiry

    async def test_mark_refreshed_without_vendor_expiry_leaves_column_untouched(
        self, session, user_id
    ):
        """Omitting refresh_token_expires_at (the common case -- the vendor
        rarely sends refresh_token_expire_in) must not clobber a
        previously-captured value with NULL."""
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )
        repo = TikTokCredentialRepo(session)
        captured_expiry = _utc_now() + timedelta(days=30)
        await repo.mark_refreshed(
            credential.id,
            "t1",
            "r1",
            _utc_now() + timedelta(days=1),
            refresh_token_expires_at=captured_expiry,
        )

        updated = await repo.mark_refreshed(
            credential.id, "t2", "r2", _utc_now() + timedelta(days=1)
        )

        assert updated.refresh_token_expires_at == captured_expiry

    async def test_mark_refreshed_raises_not_found_for_unknown_credential(self, session):
        with pytest.raises(NotFound):
            await TikTokCredentialRepo(session).mark_refreshed(
                uuid.uuid4(), "t", "r", _utc_now() + timedelta(days=1)
            )


class TestMarkNeedsReauth:
    async def test_mark_needs_reauth_sets_status_and_error(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session, shop_id=shop.id, token_expires_at=_utc_now() + timedelta(hours=1)
        )

        updated = await TikTokCredentialRepo(session).mark_needs_reauth(
            credential.id, "vendor 105002 expired"
        )

        assert updated.status == "needs_reauth"
        assert updated.last_refresh_error == "vendor 105002 expired"

    async def test_mark_needs_reauth_does_not_touch_token_triad(self, session, user_id):
        shop = await _seed_shop(session)
        credential = await _create_credential(
            session,
            shop_id=shop.id,
            token_expires_at=_utc_now() + timedelta(hours=1),
            access_token="untouched-access",
            refresh_token="untouched-refresh",
        )
        original_expiry = credential.token_expires_at

        updated = await TikTokCredentialRepo(session).mark_needs_reauth(
            credential.id, "vendor 105002 expired"
        )

        assert updated.access_token == "untouched-access"
        assert updated.refresh_token == "untouched-refresh"
        assert updated.token_expires_at == original_expiry

    async def test_mark_needs_reauth_raises_not_found_for_unknown_credential(self, session):
        with pytest.raises(NotFound):
            await TikTokCredentialRepo(session).mark_needs_reauth(uuid.uuid4(), "boom")


class TestListExpiringWithin:
    async def test_gap_6_regression_24h_window_returns_1h_and_20h_not_48h(self, session, user_id):
        """The gap-6 regression (ADR-081 decision 9): three credentials at
        1h, 20h and 48h to expiry, scanned with a 24h window, must return
        exactly the 1h and 20h rows.

        This assertion would have FAILED against the old, pre-ADR-081
        ``REFRESH_BUFFER = timedelta(minutes=30)`` constant
        (``core/security/tiktok_oauth.py``): a scan actually gated by a
        30-minute window would exclude the 1h-to-expiry row too (60 minutes
        > 30 minutes), returning zero of the two rows this test requires.
        Only a genuine 24h-wide predicate — the one ``list_expiring_within``
        is called with here — passes.
        """
        shop = await _seed_shop(session)
        now = _utc_now()
        repo = TikTokCredentialRepo(session)

        cred_1h = await _create_credential(
            session, shop_id=shop.id, token_expires_at=now + timedelta(hours=1)
        )
        cred_20h = await _create_credential(
            session, shop_id=shop.id, token_expires_at=now + timedelta(hours=20)
        )
        cred_48h = await _create_credential(
            session, shop_id=shop.id, token_expires_at=now + timedelta(hours=48)
        )

        results = await repo.list_expiring_within(timedelta(hours=24), now=now)
        result_ids = {c.id for c in results}

        assert cred_1h.id in result_ids
        assert cred_20h.id in result_ids
        assert cred_48h.id not in result_ids
        assert result_ids == {cred_1h.id, cred_20h.id}

    async def test_excludes_needs_reauth_row_even_when_inside_window(self, session, user_id):
        shop = await _seed_shop(session)
        now = _utc_now()
        repo = TikTokCredentialRepo(session)

        cred_active = await _create_credential(
            session, shop_id=shop.id, token_expires_at=now + timedelta(hours=2)
        )
        cred_needs_reauth = await _create_credential(
            session, shop_id=shop.id, token_expires_at=now + timedelta(hours=3)
        )
        await repo.mark_needs_reauth(cred_needs_reauth.id, "vendor 105002 expired")

        results = await repo.list_expiring_within(timedelta(hours=24), now=now)
        result_ids = {c.id for c in results}

        assert cred_active.id in result_ids
        assert cred_needs_reauth.id not in result_ids
