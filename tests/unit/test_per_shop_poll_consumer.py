"""The poll path consumes #1365's per-shop resolver — Issue #1995.

#1365 shipped `resolve_read_credential_for_shop(session, shop_id)` as a producer
with no consumer: two guards one layer down still admitted only the single
configured merchant, so a connecting seller's credential resolved correctly and
was then refused. This file pins the consumer, and the two traps #1365's review
named:

- **the hard rejects** — `_assert_fujiwa_credential` and
  `ProductionReadClientFactory.create` refused any non-configured merchant;
- **the swallow** — `refresh.py`'s bare `except Exception` would catch
  `NoReadCredentialForShop` and return `None`, restoring the silent skip one
  line after the loud error was introduced. That one is the dangerous half
  precisely because every other test in the suite still passes when it is
  present, so it gets two independent proofs below: a behavioural one (the
  error reaches the caller) and a structural one (no handler exists in the
  function's AST).

SCOPE OF THE ISOLATION PROOF. The `session` fixture is SQLite in-memory, so what
the two-shop test establishes is that the code's own query predicates and guards
keep the shops apart, and that each shop's vendor calls carry that shop's token.
It does NOT establish that Postgres RLS permits the read that must succeed —
that is the #2019/#2032 defect class, and the Postgres-backed proof for the
resolver lives in `tests/unit/test_credential_resolver_rls_scope.py`, which skips
without Docker and runs in CI's `full-regression` / `Release-shape regression`
lanes.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from juli_backend.core.security.credential_resolver import NoReadCredentialForShop
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
)
from juli_backend.models.models import Shop, TikTokCredential, User
from juli_backend.services.action_cards import refresh as refresh_module
from juli_backend.services.action_cards.refresh import maybe_poll_tiktok_data
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    _assert_pollable_read_credential,
    run_fujiwa_poll_cycle,
)

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"


@dataclass
class _ShopUnderTest:
    shop: Shop
    credential: TikTokCredential


def _mock_resources() -> MagicMock:
    resources = MagicMock()
    resources.orders.search_all.return_value = []
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"code": 0, "data": {"inventory": []}}
    resources.analytics.list_sku_performance_all.return_value = []
    resources.analytics.list_product_performance_all.return_value = []
    resources.analytics.get_shop_performance.return_value = {}
    resources.analytics.get_shop_performance_per_hour.return_value = {}
    resources.analytics.get_bestselling_products.return_value = {}
    resources.analytics.get_bestselling_videos.return_value = {}
    resources.analytics.list_live_performance_all.return_value = []
    resources.promotion.get_activity.return_value = {}
    return resources


@pytest_asyncio.fixture
async def owner(session, user_id):
    u = User(id=user_id, phone="+84900000111")
    session.add(u)
    await session.flush()
    return u


async def _make_shop(session, owner, *, name, tiktok_shop_id, merchant, capability, token):
    shop = Shop(
        id=uuid.uuid4(),
        user_id=owner.id,
        shop_name=name,
        tiktok_shop_id=tiktok_shop_id,
    )
    session.add(shop)
    await session.flush()
    credential = TikTokCredential(
        id=uuid.uuid4(),
        shop_id=shop.id,
        merchant_authorization_id=merchant,
        capability=capability,
        shop_cipher=f"ROW_cipher_{token}",
        access_token=token,
        refresh_token=f"refresh-{token}",
        token_expires_at=datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC),
        scopes="shop.order:read product.product:read",
    )
    session.add(credential)
    await session.flush()
    return _ShopUnderTest(shop=shop, credential=credential)


@pytest_asyncio.fixture
async def juli_shop(session, owner):
    """Juli's own shop, holding the configured production-read credential."""
    return await _make_shop(
        session,
        owner,
        name="Juli Production Shop",
        tiktok_shop_id="tiktok_shop_juli",
        merchant=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        token="juli-access-token",
    )


@pytest_asyncio.fixture
async def seller_shop(session, owner):
    """A connecting seller, holding their own SELLER_CONNECT credential."""
    return await _make_shop(
        session,
        owner,
        name="Seller Shop",
        tiktok_shop_id="tiktok_shop_seller",
        merchant="seller_own_merchant_4242",
        capability=TikTokCapability.SELLER_CONNECT.value,
        token="seller-access-token",
    )


@pytest.fixture
def poll_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", "https://test.com/callback")
    monkeypatch.setenv("REDIS_URL", "redis://localhost/0")


# --- The headline: two shops, two tokens, no crossing ------------------------


class TestTwoShopsPollUnderTheirOwnToken:
    @pytest.mark.asyncio
    async def test_each_shop_issues_vendor_calls_only_under_its_own_token(
        self, session, juli_shop, seller_shop
    ):
        """The isolation property #1995 must not get wrong.

        Two shops, each holding its own credential, polled through the real
        entrypoint with the real (non-injected) resolver. Each cycle's vendor
        client config must carry that shop's own access token, shop cipher and
        merchant authorization id -- and never the other shop's.

        RED before #1995 twice over: `_assert_fujiwa_credential` refused the
        seller's credential outright, and `_factory_config` hardcoded
        `merchant_auth_id=PRODUCTION_AUTH_ID` so even an admitted seller would
        have signed as Juli's merchant.
        """
        captured: list = []

        async def _poll_for(target: _ShopUnderTest):
            resources = _mock_resources()
            rate_limiter = MagicMock()
            rate_limiter.acquire.return_value = True
            rate_limiter.is_exhausted.return_value = False
            rate_limiter.time_until_reset.return_value = 0

            async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
                return None

            def _create_resources(config):
                captured.append(config)
                return resources

            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=MagicMock(),
                rate_limiter=rate_limiter,
                handoff_fn=_handoff,
                shop_id=target.shop.id,
                create_resources=_create_resources,
            )
            return resources

        juli_resources = await _poll_for(juli_shop)
        seller_resources = await _poll_for(seller_shop)

        assert len(captured) == 2
        juli_config, seller_config = captured

        # Each config carries its own shop's token and merchant...
        assert juli_config.access_token == "juli-access-token"
        assert juli_config.merchant_auth_id == PRODUCTION_AUTH_ID
        assert juli_config.shop_cipher == juli_shop.credential.shop_cipher

        assert seller_config.access_token == "seller-access-token"
        assert seller_config.merchant_auth_id == "seller_own_merchant_4242"
        assert seller_config.shop_cipher == seller_shop.credential.shop_cipher

        # ...and never the other's. Stated as its own assertion rather than
        # left implied by the equalities above: this is the failure mode the
        # issue exists to prevent, and it deserves to fail by name.
        assert juli_config.access_token != seller_config.access_token
        assert juli_config.merchant_auth_id != seller_config.merchant_auth_id

        # Both cycles actually reached the vendor -- otherwise the assertions
        # above would hold vacuously for a poll that never ran.
        juli_resources.orders.search_all.assert_called_once()
        seller_resources.orders.search_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_credential_owned_by_another_shop_is_refused_before_any_vendor_call(
        self, session, juli_shop, seller_shop
    ):
        """The guard that makes the isolation above a property, not a habit.

        A resolver that hands back the wrong shop's credential must be stopped
        BEFORE `with_sticky_shop_scope` grants that shop's authority and before
        a client is built -- not detected afterwards.
        """
        resources = _mock_resources()
        rate_limiter = MagicMock()
        rate_limiter.is_exhausted.return_value = False

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            return None

        with pytest.raises(ValueError, match="owned by the shop being polled"):
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=MagicMock(),
                rate_limiter=rate_limiter,
                handoff_fn=_handoff,
                shop_id=seller_shop.shop.id,
                resolve_credential=AsyncMock(return_value=juli_shop.credential),
                create_resources=lambda _cfg: resources,
            )

        resources.orders.search_all.assert_not_called()


# --- The dangerous half: the error must not be swallowed ---------------------


class TestNoReadCredentialForShopIsNotSwallowed:
    @pytest.mark.asyncio
    async def test_it_propagates_out_of_maybe_poll_tiktok_data(self, session, owner, poll_env):
        """ADR-103 d.11 + #1995's added acceptance criterion.

        GIVEN a shop with no usable read credential WHEN `maybe_poll_tiktok_data`
        runs THEN `NoReadCredentialForShop` propagates to the caller and is not
        logged-and-swallowed at any layer.

        RED with the bare `except Exception` restored at `refresh.py:62`: this
        call returns `None` and the test fails on `pytest.raises`.
        """
        shop = Shop(
            id=uuid.uuid4(),
            user_id=owner.id,
            shop_name="Freshly Connected, No Credential",
            tiktok_shop_id="tiktok_shop_bare",
        )
        session.add(shop)
        await session.flush()

        with pytest.raises(NoReadCredentialForShop):
            await maybe_poll_tiktok_data(session, shop.id)

    @pytest.mark.asyncio
    async def test_it_is_never_converted_to_a_none_return(self, session, owner, poll_env):
        """The same property stated as the one the old code satisfied.

        A `return None` and a raise are indistinguishable to a caller that does
        not inspect the value, which is exactly how the silent skip survived.
        """
        shop = Shop(
            id=uuid.uuid4(),
            user_id=owner.id,
            shop_name="Still No Credential",
            tiktok_shop_id="tiktok_shop_bare_2",
        )
        session.add(shop)
        await session.flush()

        outcome: object = "not-run"
        try:
            outcome = await maybe_poll_tiktok_data(session, shop.id)
        except NoReadCredentialForShop:
            outcome = "raised"

        assert outcome == "raised", (
            f"maybe_poll_tiktok_data returned {outcome!r} for a shop with no read "
            "credential -- the silent skip #1365/#1995 exist to remove"
        )

    def test_the_function_body_contains_no_exception_handler(self):
        """Structural pin, because the behavioural test above is not enough.

        A handler could be re-added one layer up (in `run_action_card_refresh`,
        or the Celery task) and this function could keep raising while the
        product-level failure returns. This asserts the shape at the place the
        issue names: `maybe_poll_tiktok_data` has no `except` at all, so there
        is nothing there that could catch `NoReadCredentialForShop`.
        """
        source = inspect.getsource(maybe_poll_tiktok_data)
        tree = ast.parse(source)
        handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]

        assert handlers == [], (
            "maybe_poll_tiktok_data grew an except handler; #1995 exists because "
            "a bare `except Exception` here turns NoReadCredentialForShop back "
            "into a silent skip with every test still passing"
        )

    def test_the_refresh_module_does_not_import_the_configured_merchant_resolver(self):
        """`resolve_production_read_credential` gone from this path entirely.

        Leaving the import would let a later edit fall back to the configured
        merchant for a shop that owns nothing -- the no-fallback rule
        `resolve_read_credential_for_shop` is built on, undone at the call site.
        """
        source = inspect.getsource(refresh_module)

        assert "resolve_production_read_credential" not in source
        assert "resolve_read_credential_for_shop" in source


# --- Sandbox-write stays unreachable from every read path --------------------


class TestSandboxWriteIsUnreachableFromThePollPath:
    def test_the_poll_guard_refuses_a_sandbox_write_credential(self):
        credential = MagicMock()
        credential.capability = TikTokCapability.SANDBOX_WRITE.value
        credential.merchant_authorization_id = SANDBOX_AUTH_ID
        credential.shop_id = uuid.uuid4()

        with pytest.raises(ValueError, match="read-capable"):
            _assert_pollable_read_credential(credential, shop_id=credential.shop_id)

    def test_the_poll_guard_refuses_the_sandbox_merchant_even_if_mislabelled(self):
        """Capability is a stored column. A row carrying the sandbox merchant id
        but a read capability must still not reach a vendor client."""
        credential = MagicMock()
        credential.capability = TikTokCapability.PRODUCTION_READ.value
        credential.merchant_authorization_id = SANDBOX_AUTH_ID
        credential.shop_id = uuid.uuid4()

        with pytest.raises(ValueError, match="SANDBOX_VN"):
            _assert_pollable_read_credential(credential, shop_id=credential.shop_id)

    def test_the_poll_guard_refuses_a_credential_with_no_capability(self):
        """Absent is not permission."""
        credential = MagicMock()
        credential.capability = None
        credential.merchant_authorization_id = "seller_own_merchant_4242"
        credential.shop_id = uuid.uuid4()

        with pytest.raises(ValueError, match="read-capable"):
            _assert_pollable_read_credential(credential, shop_id=credential.shop_id)

    @pytest.mark.asyncio
    async def test_a_shop_holding_only_a_sandbox_write_credential_cannot_poll(
        self, session, owner, poll_env
    ):
        """End to end at the call site: the resolver never returns it, so the
        shop is indistinguishable from one holding nothing at all."""
        sandbox = await _make_shop(
            session,
            owner,
            name="Sandbox Write Shop",
            tiktok_shop_id="tiktok_shop_sandbox",
            merchant=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE.value,
            token="sandbox-access-token",
        )

        mock_poll_cycle = AsyncMock()
        with patch("juli_backend.workers.services.polling.run_fujiwa_poll_cycle", mock_poll_cycle):
            with pytest.raises(NoReadCredentialForShop):
                await maybe_poll_tiktok_data(session, sandbox.shop.id)

        mock_poll_cycle.assert_not_called()


# --- The sandbox exclusion must fail CLOSED on a misconfigured constant ------


class TestTheSandboxExclusionFailsClosed:
    """#1995 review. Both guards first shipped as `if SANDBOX_AUTH_ID and ...`.

    That short-circuit inverts a security refusal. `SANDBOX_AUTH_ID` is read
    from `TIKTOK_SANDBOX_MERCHANT_ID` at import; set that env var to an empty
    string and the constant is `""`, the `and` is False, and the sandbox
    write-validation merchant is silently **admitted** to the read path -- the
    one outcome `READ_CAPABILITIES` and both guards exist to prevent.

    It was a REGRESSION, not an inherited hole: the pre-#1995 checks compared
    `!= PRODUCTION_AUTH_ID`, which refuses everything when the constant is
    empty. The value is non-empty in production today only because
    `merchant.py` carries a hardcoded fallback and the env var is unset on the
    deployed host (#1365 finding F6) -- luck, not a guarantee, and an
    explicitly-empty env var defeats it.

    A constant the guard cannot read is a DEPLOYMENT fault, so both refuse to
    proceed rather than proceed without the check.
    """

    def test_the_read_factory_refuses_everything_when_sandbox_auth_id_is_empty(self, monkeypatch):
        from juli_backend.integrations.tiktok import factories as factories_module

        monkeypatch.setattr(factories_module, "SANDBOX_AUTH_ID", "")

        # The sandbox merchant itself -- the id that MUST never be admitted.
        with pytest.raises(ValueError, match="cannot enforce the SANDBOX_VN exclusion"):
            factories_module.ProductionReadClientFactory().create(
                factories_module.ClientFactoryConfig(
                    app_key="k",
                    app_secret="s",
                    access_token="t",
                    merchant_auth_id=SANDBOX_AUTH_ID or "7658096633384781588",
                    shop_cipher="ROW_cipher1234567890",
                )
            )

        # And an ordinary seller too: with the exclusion unenforceable the
        # factory builds nothing at all, rather than building everything
        # except a merchant it can no longer name.
        with pytest.raises(ValueError, match="cannot enforce the SANDBOX_VN exclusion"):
            factories_module.ProductionReadClientFactory().create(
                factories_module.ClientFactoryConfig(
                    app_key="k",
                    app_secret="s",
                    access_token="t",
                    merchant_auth_id="seller_own_merchant_4242",
                    shop_cipher="ROW_cipher1234567890",
                )
            )

    def test_the_poll_guard_refuses_when_sandbox_auth_id_is_empty(self, monkeypatch):
        from juli_backend.workers.services.polling import orchestrate as orchestrate_module

        monkeypatch.setattr(orchestrate_module, "SANDBOX_AUTH_ID", "")

        credential = MagicMock()
        credential.capability = TikTokCapability.PRODUCTION_READ.value
        credential.merchant_authorization_id = SANDBOX_AUTH_ID or "7658096633384781588"
        credential.shop_id = uuid.uuid4()

        with pytest.raises(ValueError, match="cannot enforce the SANDBOX_VN exclusion"):
            orchestrate_module._assert_pollable_read_credential(
                credential, shop_id=credential.shop_id
            )


# --- The fleet-wide beat is unchanged ----------------------------------------


class TestFleetWideEntryIsUnchanged:
    @pytest.mark.asyncio
    async def test_omitting_shop_id_still_resolves_the_configured_merchant(
        self, session, juli_shop
    ):
        """`workers/tasks/fujiwa_poll_beat.py` names no shop and must keep
        working exactly as before #1995."""
        resources = _mock_resources()
        rate_limiter = MagicMock()
        rate_limiter.acquire.return_value = True
        rate_limiter.is_exhausted.return_value = False
        rate_limiter.time_until_reset.return_value = 0

        async def _handoff(channel: str, shop_key: str, value: bytes) -> None:
            return None

        captured: list = []

        def _create_resources(config):
            captured.append(config)
            return resources

        await run_fujiwa_poll_cycle(
            session=session,
            config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            oauth_service=MagicMock(),
            rate_limiter=rate_limiter,
            handoff_fn=_handoff,
            create_resources=_create_resources,
        )

        assert captured[0].merchant_auth_id == PRODUCTION_AUTH_ID
        assert captured[0].access_token == "juli-access-token"
        resources.orders.search_all.assert_called_once()
