"""Single-use production write authorizations (``repositories/production_write.py``, #1335).

Acceptance criteria this module proves:

1. issuing goes through ``verify_capability_binding`` and refuses a mis-bound credential;
2. ``lookup`` misses for each of six reasons, and hits otherwise;
3. ``consume`` claims exactly once;
4. ``expires_at`` defaults from the documented 24h setting and is never null;
5. ``revoke`` keeps the row for audit;
6. rows are scoped by ``shop_id`` directly (#1328);
7. no ``/v1/*`` route can issue one.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from juli_backend.database import NotFound
from juli_backend.models.models import ProductionWriteAuthorization
from juli_backend.repositories import ProductionWriteAuthorizationsRepo
from juli_backend.services.operations.production_write_authorizations_service import (
    ProductionWriteAuthorizationService,
)
from juli_backend.services.tiktok.credential_binding import CredentialBindingError
from tests.support.builders import make_tenant, utc_now_naive

PRODUCT = "product_123"
MUTATION = "listing.optimize_product"
VERIFY_BINDING = (
    "juli_backend.services.operations.production_write_authorizations_service"
    ".verify_capability_binding"
)


@pytest.fixture
def repo(session):
    return ProductionWriteAuthorizationsRepo(session)


async def issue(repo, shop, **overrides):
    values = dict(
        shop_id=shop.id,
        tiktok_product_id=PRODUCT,
        mutation_kind=MUTATION,
        authorized_by="operator@example.com",
        expires_at=utc_now_naive() + timedelta(hours=24),
    )
    values.update(overrides)
    return await repo.issue(**values)


class TestIssuing:
    async def test_service_verifies_the_binding_then_persists_through_the_real_repo(
        self, session, shop
    ):
        """The real service calls the real repository; only the vendor check is stubbed.

        A fake repository would hide a signature drift between the two."""
        service = ProductionWriteAuthorizationService(session)

        with patch(VERIFY_BINDING, new_callable=AsyncMock) as verify:
            authorization = await service.issue(
                shop_id=shop.id,
                tiktok_product_id=PRODUCT,
                mutation_kind=MUTATION,
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher_sandbox",
                authorized_by="operator@example.com",
                reason="why",
                ttl_hours=24,
            )

        verify.assert_awaited_once_with(
            session, capability="sandbox_write", shop_cipher="ROW_test_cipher_sandbox"
        )
        assert authorization.shop_id == shop.id
        assert (authorization.tiktok_product_id, authorization.mutation_kind) == (PRODUCT, MUTATION)
        assert authorization.reason == "why"
        assert authorization.consumed_at is None

    async def test_service_refuses_a_misbound_credential_and_writes_nothing(self, session, shop):
        service = ProductionWriteAuthorizationService(session)

        with patch(VERIFY_BINDING, new_callable=AsyncMock) as verify:
            verify.side_effect = CredentialBindingError("bound to a different shop")
            with pytest.raises(CredentialBindingError):
                await service.issue(
                    shop_id=shop.id,
                    tiktok_product_id=PRODUCT,
                    mutation_kind=MUTATION,
                    capability="production_read",
                    shop_cipher="ROW_different_shop_cipher",
                    authorized_by="operator@example.com",
                )

        rows = await session.execute(
            select(ProductionWriteAuthorization).where(
                ProductionWriteAuthorization.shop_id == shop.id
            )
        )
        assert rows.scalars().first() is None

    async def test_repo_issue_is_pure_persistence(self, repo, shop):
        authorization = await issue(repo, shop, reason=None)

        assert authorization.id is not None
        assert authorization.reason is None
        assert (authorization.consumed_at, authorization.consumed_by_run_id) == (None, None)
        assert authorization.revoked_at is None


class TestLookup:
    async def test_finds_the_live_authorization(self, repo, shop):
        authorization = await issue(repo, shop)

        found = await repo.lookup(shop.id, PRODUCT, MUTATION)

        assert found is not None and found.id == authorization.id

    @pytest.mark.parametrize(
        "make_miss",
        [
            pytest.param(
                lambda: {"expires_at": utc_now_naive() - timedelta(hours=1)}, id="expired"
            ),
            pytest.param(lambda: {"tiktok_product_id": "product_999"}, id="different-product"),
            pytest.param(lambda: {"mutation_kind": "inventory.replenish"}, id="different-mutation"),
        ],
    )
    async def test_misses_when_a_scoping_field_or_expiry_does_not_match(
        self, repo, shop, make_miss
    ):
        await issue(repo, shop, **make_miss())

        assert await repo.lookup(shop.id, PRODUCT, MUTATION) is None

    async def test_misses_a_consumed_authorization(self, repo, shop):
        authorization = await issue(repo, shop)
        await repo.consume(authorization.id, run_id=uuid.uuid4())

        assert await repo.lookup(shop.id, PRODUCT, MUTATION) is None

    async def test_misses_a_revoked_authorization(self, repo, shop):
        authorization = await issue(repo, shop)
        await repo.revoke(authorization.id, reason="no longer needed")

        assert await repo.lookup(shop.id, PRODUCT, MUTATION) is None

    async def test_misses_another_shops_authorization(self, repo, session, shop):
        _, other_shop = await make_tenant(session)
        await issue(repo, shop)

        assert await repo.lookup(other_shop.id, PRODUCT, MUTATION) is None


class TestConsume:
    async def test_stamps_consumed_at_and_the_run(self, repo, session, shop):
        authorization = await issue(repo, shop)
        run_id = uuid.uuid4()

        consumed = await repo.consume(authorization.id, run_id=run_id)

        assert consumed.consumed_at is not None
        assert consumed.consumed_by_run_id == run_id
        await session.refresh(authorization)
        assert authorization.consumed_by_run_id == run_id

    async def test_second_claim_loses_with_not_found(self, repo, shop):
        """The loser of the race sees the same signal as a missing row."""
        authorization = await issue(repo, shop)
        await repo.consume(authorization.id, run_id=uuid.uuid4())

        with pytest.raises(NotFound, match="already consumed"):
            await repo.consume(authorization.id, run_id=uuid.uuid4())

    async def test_unknown_id_is_not_found(self, repo):
        with pytest.raises(NotFound, match="not found"):
            await repo.consume(uuid.uuid4(), run_id=uuid.uuid4())


class TestExpiry:
    async def test_service_defaults_expires_at_to_the_documented_24_hours(self, session, shop):
        service = ProductionWriteAuthorizationService(session)
        before = utc_now_naive()

        with patch(VERIFY_BINDING, new_callable=AsyncMock):
            authorization = await service.issue(
                shop_id=shop.id,
                tiktok_product_id=PRODUCT,
                mutation_kind=MUTATION,
                capability="sandbox_write",
                shop_cipher="ROW_test_cipher_sandbox",
                authorized_by="operator@example.com",
            )

        expires_at = authorization.expires_at.replace(tzinfo=None)
        assert before + timedelta(hours=23, minutes=59) <= expires_at
        assert expires_at <= utc_now_naive() + timedelta(hours=24, minutes=1)

    async def test_row_cannot_be_persisted_without_expires_at(self, session, shop):
        session.add(
            ProductionWriteAuthorization(
                shop_id=shop.id,
                tiktok_product_id=PRODUCT,
                mutation_kind=MUTATION,
                authorized_by="operator@example.com",
                expires_at=None,
            )
        )

        with pytest.raises(Exception, match="NOT NULL|IntegrityError|null"):
            await session.flush()


class TestRevoke:
    async def test_keeps_the_row_with_its_reason(self, repo, session, shop):
        authorization = await issue(repo, shop)

        revoked = await repo.revoke(authorization.id, reason="No longer needed")

        assert revoked.revoked_at is not None
        assert revoked.revoke_reason == "No longer needed"
        assert await session.get(ProductionWriteAuthorization, authorization.id) is not None


class TestInheritedShopScoping:
    """The repo is a ``ShopScopedRepo``; ``list``/``get`` work and respect the tenant.

    Regression: the class used to declare ``model`` instead of ``_model``, so the
    inherited ``list`` and ``get`` raised ``AttributeError``."""

    async def test_list_and_get_are_scoped_to_the_shop(self, repo, session, shop):
        _, other_shop = await make_tenant(session)
        mine = await issue(repo, shop)
        await issue(repo, other_shop)

        assert await repo.list(shop.id) == [mine]
        assert (await repo.get(shop.id, mine.id)) is mine
        with pytest.raises(NotFound):
            await repo.get(other_shop.id, mine.id)


def test_no_v1_route_can_issue_an_authorization():
    """Structural: no ``/v1/*`` endpoint's source mentions the repo or calls ``.issue(``."""
    from juli_backend.api.app import create_app

    def endpoints(routes, prefix=""):
        for route in routes:
            sub_app = getattr(route, "app", None)
            if sub_app is not None and hasattr(sub_app, "routes"):
                yield from endpoints(sub_app.routes, prefix + route.path)
            elif hasattr(route, "path") and getattr(route, "endpoint", None) is not None:
                yield prefix + route.path, route.endpoint

    offenders = []
    for path, endpoint in endpoints(create_app().routes):
        if not path.startswith("/v1/"):
            continue
        try:
            source = inspect.getsource(endpoint)
        except (OSError, TypeError):
            continue
        if "ProductionWriteAuthorizationsRepo" in source or ".issue(" in source:
            offenders.append(path)

    assert offenders == []
