"""``TikTokCredentialRepo`` (``repositories/tiktok_credentials.py``).

Three concerns: tokens are encrypted at rest and merchant lookups can never
cross the Fujiwa/SANDBOX_VN boundary (#296, #1234); ``get_by_shop*`` always
picks the newest row; and the refresh health columns added by ADR-081
decision 7 (#1230) behave exactly as that decision specifies.

Merchant-*context* resolution (``resolve_merchant_context``,
``is_cross_merchant_lookup`` against configured env ids) belongs to
``test_tiktok_merchant_config.py``; the capability resolvers' isolation to
``test_credential_resolver_isolation.py`` and their lazy-refresh wiring to
``test_credential_resolver_lazy_refresh.py``. ``TikTokOAuthService.refresh_merchant_tokens`` is a
thin ``get_by_merchant`` + ``credential_refresh.refresh_credential``
composition; the former's isolation guarantee is proven directly below and
the latter's rotation behaviour by ``test_tiktok_oauth.py``'s
``TestTokenRefresh``, so re-proving the composition here would only restate
those two already-covered facts.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from juli_backend.database.exceptions import NotFound
from juli_backend.database.token_crypto import decrypt_token
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, SANDBOX_AUTH_ID, TikTokCapability
from juli_backend.models.models import TikTokCredential
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.builders import make_credential, next_unique, utc_now_naive


async def _issue_credential(session, shop, **overrides):
    """A credential written through the repo -- tokens land encrypted."""
    values = dict(
        access_token=next_unique("access"),
        refresh_token=next_unique("refresh"),
        token_expires_at=utc_now_naive() + timedelta(days=7),
    )
    values.update(overrides)
    return await TikTokCredentialRepo(session).create(shop_id=shop.id, **values)


class TestCreate:
    async def test_encrypts_tokens_at_rest(self, session, shop):
        created = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="plain-access",
            refresh_token="plain-refresh",
            token_expires_at=utc_now_naive() + timedelta(days=7),
        )

        assert (created.access_token, created.refresh_token) == ("plain-access", "plain-refresh")
        raw_access, raw_refresh = (
            await session.execute(
                select(TikTokCredential.access_token, TikTokCredential.refresh_token).where(
                    TikTokCredential.id == created.id
                )
            )
        ).one()
        assert raw_access != "plain-access"
        assert raw_refresh != "plain-refresh"
        assert decrypt_token(raw_access) == "plain-access"
        assert decrypt_token(raw_refresh) == "plain-refresh"

    async def test_new_credential_starts_active_with_zero_refresh_count(self, session, shop):
        created = await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token="a",
            refresh_token="r",
            token_expires_at=utc_now_naive() + timedelta(days=7),
        )

        assert (created.status, created.refresh_count) == ("active", 0)
        fetched = await session.get(TikTokCredential, created.id)
        assert (fetched.status, fetched.refresh_count) == ("active", 0)

    async def test_rejects_a_cross_merchant_capability_pair(self, session, shop):
        with pytest.raises(ValueError, match="do not match"):
            await TikTokCredentialRepo(session).create(
                shop_id=shop.id,
                access_token="t",
                refresh_token="r",
                token_expires_at=utc_now_naive() + timedelta(days=7),
                merchant_authorization_id=PRODUCTION_AUTH_ID,
                capability=TikTokCapability.SANDBOX_WRITE.value,
            )

    async def test_pre_migration_shaped_row_reads_back_none_for_new_nullable_columns(
        self, session, shop
    ):
        """#1230: a row inserted with only the pre-migration column set reads back
        ``None`` for the three additive columns -- never a synthesized value --
        while ``status``/``refresh_count`` still pick up their table defaults."""
        credential_id = uuid.uuid4()
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
                "token_expires_at": utc_now_naive() + timedelta(days=7),
            },
        )
        await session.flush()

        row = await session.get(TikTokCredential, credential_id)

        assert (row.last_refreshed_at, row.last_refresh_error, row.refresh_token_expires_at) == (
            None,
            None,
            None,
        )
        assert (row.status, row.refresh_count) == ("active", 0)


class TestGetByMerchant:
    """Cross-merchant lookups are refused before the database is even queried (#296)."""

    async def test_returns_the_matching_credential(self, session, shop):
        created = await _issue_credential(
            session,
            shop,
            merchant_authorization_id=PRODUCTION_AUTH_ID,
            capability=TikTokCapability.PRODUCTION_READ.value,
            access_token="fujiwa-access",
        )

        found = await TikTokCredentialRepo(session).get_by_merchant(
            PRODUCTION_AUTH_ID, TikTokCapability.PRODUCTION_READ
        )

        assert found.id == created.id
        assert found.access_token == "fujiwa-access"

    @pytest.mark.parametrize(
        ("merchant_id", "stored_capability", "queried_capability"),
        [
            pytest.param(
                PRODUCTION_AUTH_ID,
                TikTokCapability.PRODUCTION_READ,
                TikTokCapability.SANDBOX_WRITE,
                id="production-merchant-queried-as-sandbox",
            ),
            pytest.param(
                SANDBOX_AUTH_ID,
                TikTokCapability.SANDBOX_WRITE,
                TikTokCapability.PRODUCTION_READ,
                id="sandbox-merchant-queried-as-production",
            ),
        ],
    )
    async def test_refuses_a_mismatched_merchant_capability_pair(
        self, session, shop, merchant_id, stored_capability, queried_capability
    ):
        await _issue_credential(
            session,
            shop,
            merchant_authorization_id=merchant_id,
            capability=stored_capability.value,
        )

        with pytest.raises(NotFound, match="No credentials for merchant"):
            await TikTokCredentialRepo(session).get_by_merchant(merchant_id, queried_capability)


class TestGetByShop:
    async def test_returns_the_newest_credential_for_the_shop(self, session, shop):
        older = await _issue_credential(session, shop)
        newer = await _issue_credential(session, shop)
        newer.created_at = older.created_at + timedelta(seconds=1)
        await session.flush()

        found = await TikTokCredentialRepo(session).get_by_shop(shop.id)

        assert found.id == newer.id

    async def test_raises_not_found_when_the_shop_has_no_credential(self, session, shop):
        with pytest.raises(NotFound, match=f"No credentials found for shop {shop.id}"):
            await TikTokCredentialRepo(session).get_by_shop(shop.id)


class TestGetByShopAndCapability:
    async def test_returns_the_newest_matching_capability(self, session, shop):
        older = await _issue_credential(session, shop, capability="sandbox_write")
        newer = await _issue_credential(session, shop, capability="sandbox_write")
        newer.created_at = older.created_at + timedelta(seconds=1)
        await _issue_credential(session, shop, capability="production_read")
        await session.flush()

        found = await TikTokCredentialRepo(session).get_by_shop_and_capability(
            shop.id, TikTokCapability.SANDBOX_WRITE
        )

        assert found.id == newer.id

    async def test_raises_not_found_for_an_unmatched_capability(self, session, shop):
        await _issue_credential(session, shop, capability="production_read")

        with pytest.raises(NotFound, match="with capability sandbox_write"):
            await TikTokCredentialRepo(session).get_by_shop_and_capability(
                shop.id, TikTokCapability.SANDBOX_WRITE
            )


class TestUpdateTokens:
    async def test_rotates_the_token_triad_and_encrypts_at_rest(self, session, shop):
        credential = await _issue_credential(session, shop)
        new_expiry = utc_now_naive() + timedelta(days=7)

        updated = await TikTokCredentialRepo(session).update_tokens(
            credential.id, "new-access", "new-refresh", new_expiry
        )

        assert (updated.access_token, updated.refresh_token) == ("new-access", "new-refresh")
        assert updated.token_expires_at == new_expiry
        raw_access = (
            await session.execute(
                select(TikTokCredential.access_token).where(TikTokCredential.id == credential.id)
            )
        ).scalar_one()
        assert raw_access != "new-access"
        assert decrypt_token(raw_access) == "new-access"

    async def test_raises_not_found_for_unknown_credential(self, session):
        with pytest.raises(NotFound, match="not found"):
            await TikTokCredentialRepo(session).update_tokens(
                uuid.uuid4(), "t", "r", utc_now_naive() + timedelta(days=1)
            )


class TestMarkRefreshed:
    """ADR-081 decision 7 (#1230): a successful rotation stamps the health columns."""

    async def test_sets_token_triad_and_health_signal(self, session, shop):
        credential = await make_credential(
            session, shop, token_expires_at=utc_now_naive() + timedelta(hours=1)
        )
        new_expiry = utc_now_naive() + timedelta(days=7)

        updated = await TikTokCredentialRepo(session).mark_refreshed(
            credential.id, "new-access-token", "new-refresh-token", new_expiry
        )

        assert (updated.access_token, updated.refresh_token) == (
            "new-access-token",
            "new-refresh-token",
        )
        assert updated.token_expires_at == new_expiry
        assert updated.last_refreshed_at is not None
        assert updated.refresh_count == 1

    async def test_increments_refresh_count_by_exactly_one_per_call(self, session, shop):
        credential = await make_credential(session, shop)
        repo = TikTokCredentialRepo(session)

        counts = [
            (
                await repo.mark_refreshed(
                    credential.id, f"t{i}", f"r{i}", utc_now_naive() + timedelta(days=1)
                )
            ).refresh_count
            for i in range(3)
        ]

        assert counts == [1, 2, 3]

    async def test_clears_a_previously_set_refresh_error(self, session, shop):
        credential = await make_credential(session, shop)
        repo = TikTokCredentialRepo(session)
        await repo.mark_needs_reauth(credential.id, "vendor 105002 expired")

        refreshed = await repo.mark_refreshed(
            credential.id, "t1", "r1", utc_now_naive() + timedelta(days=1)
        )

        assert refreshed.last_refresh_error is None

    async def test_opportunistically_sets_refresh_token_expires_at(self, session, shop):
        credential = await make_credential(session, shop)
        refresh_token_expiry = utc_now_naive() + timedelta(days=30)

        updated = await TikTokCredentialRepo(session).mark_refreshed(
            credential.id,
            "t1",
            "r1",
            utc_now_naive() + timedelta(days=1),
            refresh_token_expires_at=refresh_token_expiry,
        )

        assert updated.refresh_token_expires_at == refresh_token_expiry

    async def test_omitting_refresh_token_expiry_leaves_the_column_untouched(self, session, shop):
        """The common case -- the vendor rarely sends ``refresh_token_expire_in`` --
        must not clobber a previously captured value with ``None``."""
        credential = await make_credential(session, shop)
        repo = TikTokCredentialRepo(session)
        captured_expiry = utc_now_naive() + timedelta(days=30)
        await repo.mark_refreshed(
            credential.id,
            "t1",
            "r1",
            utc_now_naive() + timedelta(days=1),
            refresh_token_expires_at=captured_expiry,
        )

        updated = await repo.mark_refreshed(
            credential.id, "t2", "r2", utc_now_naive() + timedelta(days=1)
        )

        assert updated.refresh_token_expires_at == captured_expiry

    async def test_raises_not_found_for_unknown_credential(self, session):
        with pytest.raises(NotFound, match="not found"):
            await TikTokCredentialRepo(session).mark_refreshed(
                uuid.uuid4(), "t", "r", utc_now_naive() + timedelta(days=1)
            )


class TestMarkNeedsReauth:
    async def test_sets_status_and_error(self, session, shop):
        credential = await make_credential(session, shop)

        updated = await TikTokCredentialRepo(session).mark_needs_reauth(
            credential.id, "vendor 105002 expired"
        )

        assert (updated.status, updated.last_refresh_error) == (
            "needs_reauth",
            "vendor 105002 expired",
        )

    async def test_does_not_touch_the_token_triad(self, session, shop):
        credential = await make_credential(
            session, shop, access_token="untouched-access", refresh_token="untouched-refresh"
        )
        original_expiry = credential.token_expires_at

        updated = await TikTokCredentialRepo(session).mark_needs_reauth(
            credential.id, "vendor 105002 expired"
        )

        assert (updated.access_token, updated.refresh_token) == (
            "untouched-access",
            "untouched-refresh",
        )
        assert updated.token_expires_at == original_expiry

    async def test_raises_not_found_for_unknown_credential(self, session):
        with pytest.raises(NotFound, match="not found"):
            await TikTokCredentialRepo(session).mark_needs_reauth(uuid.uuid4(), "boom")


class TestListExpiringWithin:
    """ADR-081 decision 9: the refresh beat's scan predicate."""

    async def test_returns_only_rows_inside_the_window(self, session, shop):
        """Regression: the pre-ADR-081 ``REFRESH_BUFFER = 30 minutes`` constant
        would have excluded the 1h-to-expiry row too (60 minutes > 30); only a
        genuine 24h-wide predicate returns both the 1h and 20h rows here."""
        now = utc_now_naive()
        repo = TikTokCredentialRepo(session)
        near = await make_credential(session, shop, token_expires_at=now + timedelta(hours=1))
        mid = await make_credential(session, shop, token_expires_at=now + timedelta(hours=20))
        far = await make_credential(session, shop, token_expires_at=now + timedelta(hours=48))

        results = await repo.list_expiring_within(timedelta(hours=24), now=now)
        result_ids = {c.id for c in results}

        assert result_ids == {near.id, mid.id}
        assert far.id not in result_ids

    async def test_excludes_a_needs_reauth_row_even_when_inside_the_window(self, session, shop):
        now = utc_now_naive()
        repo = TikTokCredentialRepo(session)
        active = await make_credential(session, shop, token_expires_at=now + timedelta(hours=2))
        needs_reauth = await make_credential(
            session, shop, token_expires_at=now + timedelta(hours=3)
        )
        await repo.mark_needs_reauth(needs_reauth.id, "vendor 105002 expired")

        results = await repo.list_expiring_within(timedelta(hours=24), now=now)

        assert {c.id for c in results} == {active.id}
