"""P61-G (D71.6, owner 2026-10-21): merchant identity comes from the connect flow, not env/code.

Every invariant the old ``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID`` constants enforced is
proved here from credential rows alone, with NO env var set. The PostgreSQL twin (RLS, the
migration-099 function, two production shops plus the sandbox shop) is
``tests/integration/test_p61g_merchant_identity_two_shop_postgres.py``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest

from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    NoWriteCredentialForShop,
    SandboxCredentialRefused,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
    resolve_write_credential_for_shop,
    sandbox_write_merchant_ids,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionWriteClientFactory,
    SandboxWriteClientFactory,
    TikTokCapability,
)
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.builders import make_tenant, utc_now_naive

SRC = Path(__file__).resolve().parents[2] / "backend" / "src" / "juli_backend"


@pytest.fixture(autouse=True)
def _no_merchant_env(monkeypatch):
    monkeypatch.delenv("TIKTOK_PRODUCTION_MERCHANT_ID", raising=False)
    monkeypatch.delenv("TIKTOK_SANDBOX_MERCHANT_ID", raising=False)


async def _issue(session, shop, capability, merchant, *, cipher=None, token="tok"):
    return await TikTokCredentialRepo(session).create(
        shop.id,
        token,
        f"{token}-refresh",
        utc_now_naive() + timedelta(days=30),
        merchant_authorization_id=merchant,
        capability=capability.value,
        shop_cipher=cipher,
    )


async def _shop(session):
    _user, shop = await make_tenant(session)
    return shop


def _cfg(**kw):
    base = {"app_key": "k", "app_secret": "s", "access_token": "t", "merchant_auth_id": "m-1"}
    base.update(kw)
    return ClientFactoryConfig(**base)


class TestNothingIsConfiguredOrHardcoded:
    def test_no_code_reads_a_merchant_id_env_var_or_names_the_old_constants(self):
        offenders = []
        for path in SRC.rglob("*.py"):
            if "database/migrations" in path.as_posix():
                continue  # migrations 061 / 074 mention them historically
            text = path.read_text(encoding="utf-8")
            for token in ("PRODUCTION_AUTH_ID", "SANDBOX_AUTH_ID", "MerchantIdNotConfigured"):
                if token in text and path.name != "merchant.py":
                    offenders.append((path.name, token))
            if re.search(r"""getenv\(\s*["']TIKTOK_\w*MERCHANT_ID""", text) or re.search(
                r"""environ\W+["']TIKTOK_\w*MERCHANT_ID""", text
            ):
                offenders.append((path.name, "env read"))
        assert offenders == []

    def test_no_literal_merchant_id_in_backend_src(self):
        long_numeric = re.compile(r"""["']\d{16,20}["']""")
        offenders = [
            path.name
            for path in SRC.rglob("*.py")
            if "database/migrations" not in path.as_posix()
            and long_numeric.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_the_removed_names_are_not_importable(self):
        import juli_backend.integrations.tiktok as tiktok
        import juli_backend.integrations.tiktok.merchant as merchant

        for name in (
            "PRODUCTION_AUTH_ID",
            "SANDBOX_AUTH_ID",
            "require_production_auth_id",
            "require_sandbox_auth_id",
            "MerchantIdNotConfigured",
            "resolve_merchant_context",
            "is_cross_merchant_lookup",
        ):
            assert not hasattr(tiktok, name) and not hasattr(merchant, name)


class TestFactoriesDecideFromTheCredential:
    def test_sandbox_factory_requires_the_sandbox_write_capability(self):
        for capability in (None, "seller_connect", "production_read"):
            with pytest.raises(ValueError, match="sandbox_write credential"):
                SandboxWriteClientFactory().create(_cfg(credential_capability=capability))
        SandboxWriteClientFactory().create(_cfg(credential_capability="sandbox_write"))

    def test_sandbox_factory_refuses_an_empty_merchant(self):
        with pytest.raises(ValueError, match="merchant auth ID"):
            SandboxWriteClientFactory().create(
                _cfg(merchant_auth_id="", credential_capability="sandbox_write")
            )

    def test_sandbox_factory_refuses_a_merchant_a_production_credential_carries(self):
        with pytest.raises(ValueError, match="never reach a production merchant"):
            SandboxWriteClientFactory().create(
                _cfg(
                    credential_capability="sandbox_write",
                    production_merchant_auth_ids=frozenset({"m-1"}),
                )
            )

    @pytest.mark.parametrize("factory", [ProductionReadClientFactory, ProductionWriteClientFactory])
    def test_production_factories_refuse_sandbox_credentials_and_merchants(self, factory):
        with pytest.raises(ValueError, match="sandbox_write"):
            factory().create(_cfg(credential_capability="sandbox_write"))
        with pytest.raises(ValueError, match="carries"):
            factory().create(_cfg(sandbox_merchant_auth_ids=frozenset({"m-1"})))
        with pytest.raises(ValueError, match="empty"):
            factory().create(_cfg(merchant_auth_id=""))
        assert factory().create(_cfg(credential_capability="seller_connect")) is not None


class TestResolversFromCredentialsAlone:
    async def test_sandbox_is_found_by_capability_and_production_shops_by_their_own_rows(
        self, session
    ):
        sbx, a, b = await _shop(session), await _shop(session), await _shop(session)
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "sbx-1", cipher="C-S")
        await _issue(session, a, TikTokCapability.SELLER_CONNECT, "prod-a", cipher="C-A")
        await _issue(session, b, TikTokCapability.PRODUCTION_READ, "prod-b", cipher="C-B")

        assert (await resolve_sandbox_write_credential(session)).shop_id == sbx.id
        assert (
            await resolve_read_credential_for_shop(session, a.id)
        ).merchant_authorization_id == "prod-a"
        assert (
            await resolve_read_credential_for_shop(session, b.id)
        ).merchant_authorization_id == "prod-b"
        assert (await resolve_write_credential_for_shop(session, a.id)).shop_id == a.id
        assert await sandbox_write_merchant_ids(session) == frozenset({"sbx-1"})
        with pytest.raises(NoReadCredentialForShop):
            await resolve_read_credential_for_shop(session, sbx.id)
        with pytest.raises(NoWriteCredentialForShop):
            await resolve_write_credential_for_shop(session, sbx.id)

    async def test_no_sandbox_row_is_not_found_never_a_production_fallback(self, session):
        a = await _shop(session)
        await _issue(session, a, TikTokCapability.PRODUCTION_READ, "prod-a", cipher="C-A")
        with pytest.raises(NotFound):
            await resolve_sandbox_write_credential(session)

    async def test_2026_08_18_sandbox_row_resolving_to_the_production_shop_is_refused(
        self, session
    ):
        prod, sbx = await _shop(session), await _shop(session)
        await _issue(session, prod, TikTokCapability.PRODUCTION_READ, "prod-a", cipher="SAME")
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "sbx-1", cipher="SAME")
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)

    async def test_shared_merchant_id_is_refused_too(self, session):
        prod, sbx = await _shop(session), await _shop(session)
        await _issue(session, prod, TikTokCapability.SELLER_CONNECT, "shared", cipher="C-1")
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "shared", cipher="C-2")
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)

    async def test_same_shop_seller_connect_sharing_the_cipher_is_not_a_collision(self, session):
        """Production fact 2026-10-21 (D71.6a): the sandbox shop holds sandbox_write (merchant A)
        AND seller_connect (open_id B) with one shop_cipher -- the same shop, so usable."""
        sbx = await _shop(session)
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "sbx-A", cipher="C-SBX")
        await _issue(session, sbx, TikTokCapability.SELLER_CONNECT, "oauth-B", cipher="C-SBX")
        credential = await resolve_sandbox_write_credential(session)
        assert credential.merchant_authorization_id == "sbx-A"
        assert credential.shop_id == sbx.id

    async def test_another_shops_credential_sharing_cipher_still_refused_beside_same_shop_row(
        self, session
    ):
        sbx, prod = await _shop(session), await _shop(session)
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "sbx-A", cipher="C-SBX")
        await _issue(session, sbx, TikTokCapability.SELLER_CONNECT, "oauth-B", cipher="C-SBX")
        await _issue(session, prod, TikTokCapability.SELLER_CONNECT, "prod-1", cipher="C-SBX")
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)

    async def test_a_sandbox_row_with_no_merchant_is_refused(self, session):
        sbx = await _shop(session)
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, None, cipher="C-S")
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)

    async def test_a_read_or_write_row_holding_the_sandbox_merchant_is_refused(self, session):
        sbx, mislabelled = await _shop(session), await _shop(session)
        await _issue(session, sbx, TikTokCapability.SANDBOX_WRITE, "sbx-1", cipher="C-S")
        await _issue(session, mislabelled, TikTokCapability.SELLER_CONNECT, "sbx-1", cipher="C-M")
        with pytest.raises(NoReadCredentialForShop):
            await resolve_read_credential_for_shop(session, mislabelled.id)
        with pytest.raises(NoWriteCredentialForShop):
            await resolve_write_credential_for_shop(session, mislabelled.id)
