"""TDD tests for env-configured TikTok merchant IDs (#1234, AGT-W4A).

Owner decision, 2026-08-19: "I don't want hardcoded functionality" -- a new
deployment should not need a code edit to onboard its own production/sandbox
merchants. `_KNOWN_MERCHANTS` is deleted; `PRODUCTION_AUTH_ID` / `SANDBOX_AUTH_ID`
now come from `TIKTOK_PRODUCTION_MERCHANT_ID` / `TIKTOK_SANDBOX_MERCHANT_ID`.

Acceptance criteria covered here:
- Configured production merchant ID -> PRODUCTION_READ
- Configured sandbox merchant ID -> SANDBOX_WRITE
- Unknown open_id -> SELLER_CONNECT
- Behaviour when the env vars are unset
- `_KNOWN_MERCHANTS` no longer exists
"""

from __future__ import annotations

import importlib

import pytest

import juli_backend.integrations.tiktok.merchant as merchant

# Not a secret and not a new ID -- this is the literal already committed in
# merchant.py before this change; used only to assert the documented
# fallback-default behaviour when env vars are unset.
_JULI_DEFAULT_PRODUCTION_AUTH_ID = "7658073774813611784"
_JULI_DEFAULT_SANDBOX_AUTH_ID = "7658096633384781588"


@pytest.fixture(autouse=True)
def _restore_merchant_module():
    """Env-driven module globals must not leak reloaded state across tests."""
    yield
    importlib.reload(merchant)


def _reload_with_env(monkeypatch, *, production_id: str | None, sandbox_id: str | None):
    if production_id is None:
        monkeypatch.delenv("TIKTOK_PRODUCTION_MERCHANT_ID", raising=False)
    else:
        monkeypatch.setenv("TIKTOK_PRODUCTION_MERCHANT_ID", production_id)
    if sandbox_id is None:
        monkeypatch.delenv("TIKTOK_SANDBOX_MERCHANT_ID", raising=False)
    else:
        monkeypatch.setenv("TIKTOK_SANDBOX_MERCHANT_ID", sandbox_id)
    importlib.reload(merchant)


class TestKnownMerchantsDictRemoved:
    def test_known_merchants_dict_no_longer_exists(self):
        assert not hasattr(merchant, "_KNOWN_MERCHANTS")


class TestConfiguredMerchantIds:
    def test_configured_production_id_resolves_production_read(self, monkeypatch):
        _reload_with_env(
            monkeypatch,
            production_id="test_prod_merchant_1",
            sandbox_id="test_sandbox_merchant_1",
        )

        auth_id, capability = merchant.resolve_merchant_context("test_prod_merchant_1")

        assert auth_id == "test_prod_merchant_1"
        assert capability == merchant.TikTokCapability.PRODUCTION_READ
        assert merchant.PRODUCTION_AUTH_ID == "test_prod_merchant_1"

    def test_configured_sandbox_id_resolves_sandbox_write(self, monkeypatch):
        _reload_with_env(
            monkeypatch,
            production_id="test_prod_merchant_1",
            sandbox_id="test_sandbox_merchant_1",
        )

        auth_id, capability = merchant.resolve_merchant_context("test_sandbox_merchant_1")

        assert auth_id == "test_sandbox_merchant_1"
        assert capability == merchant.TikTokCapability.SANDBOX_WRITE
        assert merchant.SANDBOX_AUTH_ID == "test_sandbox_merchant_1"

    def test_unknown_open_id_falls_back_to_seller_connect(self, monkeypatch):
        _reload_with_env(
            monkeypatch,
            production_id="test_prod_merchant_1",
            sandbox_id="test_sandbox_merchant_1",
        )

        auth_id, capability = merchant.resolve_merchant_context("some_other_seller_open_id")

        assert auth_id == "some_other_seller_open_id"
        assert capability == merchant.TikTokCapability.SELLER_CONNECT

    def test_is_cross_merchant_lookup_uses_configured_ids(self, monkeypatch):
        _reload_with_env(
            monkeypatch,
            production_id="test_prod_merchant_1",
            sandbox_id="test_sandbox_merchant_1",
        )

        assert merchant.is_cross_merchant_lookup(
            "test_prod_merchant_1", merchant.TikTokCapability.SANDBOX_WRITE
        )
        assert not merchant.is_cross_merchant_lookup(
            "test_prod_merchant_1", merchant.TikTokCapability.PRODUCTION_READ
        )


class TestEnvVarsUnset:
    def test_both_unset_falls_back_to_documented_default_literals(self, monkeypatch):
        """No env vars set -> falls back to Juli's own already-committed IDs
        (unchanged behaviour for this deployment). A new deployment MUST set
        both env vars to onboard its own merchants -- see module docstring.
        """
        _reload_with_env(monkeypatch, production_id=None, sandbox_id=None)

        assert merchant.PRODUCTION_AUTH_ID == _JULI_DEFAULT_PRODUCTION_AUTH_ID
        assert merchant.SANDBOX_AUTH_ID == _JULI_DEFAULT_SANDBOX_AUTH_ID

        auth_id, capability = merchant.resolve_merchant_context(_JULI_DEFAULT_PRODUCTION_AUTH_ID)
        assert capability == merchant.TikTokCapability.PRODUCTION_READ

    def test_unset_still_falls_back_to_seller_connect_for_unknown_id(self, monkeypatch):
        _reload_with_env(monkeypatch, production_id=None, sandbox_id=None)

        auth_id, capability = merchant.resolve_merchant_context("unrecognized_open_id")

        assert auth_id == "unrecognized_open_id"
        assert capability == merchant.TikTokCapability.SELLER_CONNECT
