"""TDD regression + end-to-end tests for #1246 (AGT-W4A).

#1234 made ``merchant.py``'s ``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID``
environment-configurable, but ``capabilities.py`` held its own independent
literal copies of the same two names, and ``factories.py`` hard-compared
against ``capabilities.py``'s literals. A new deployment following #1234's
own onboarding docs (set the two env vars) got correct classification out of
``merchant.resolve_merchant_context`` but a hard ``ValueError`` out of
``ProductionReadClientFactory`` / ``SandboxWriteClientFactory``, because the
transport guards never saw the env config.

This file proves:
- ``capabilities.py`` contains no literal merchant ID (source-text check).
- Setting ``TIKTOK_PRODUCTION_MERCHANT_ID`` / ``TIKTOK_SANDBOX_MERCHANT_ID``
  changes what ``capabilities.py`` / ``factories.py`` compare against,
  proven via module reload (not a value frozen at the original import).
- ``ProductionReadClientFactory`` / ``SandboxWriteClientFactory`` build a
  client for a non-Juli, env-configured merchant instead of raising.
- The guard still fails closed: a merchant ID that does not match the
  (possibly reconfigured) expected ID still raises ``ValueError``.

The reload-and-restore fixture mirrors ``test_tiktok_merchant_config.py``'s
pattern for the same reason: ``merchant.PRODUCTION_AUTH_ID`` is only
env-configured at import/reload time, and ``factories.py``'s ``create()``
methods look up their module's ``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID``
globals fresh on every call -- so a test that reloads these modules and does
not restore them would leak mutated globals into every other test in the
suite that constructs a client via these factories.
"""

from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path

import pytest

import juli_backend.integrations.tiktok.capabilities as capabilities
import juli_backend.integrations.tiktok.factories as factories
import juli_backend.integrations.tiktok.merchant as merchant

# Juli's own already-committed IDs (the documented fallback defaults) -- not
# secrets, used only to assert unset-env behaviour is unchanged.
_JULI_DEFAULT_PRODUCTION_AUTH_ID = "7658073774813611784"
_JULI_DEFAULT_SANDBOX_AUTH_ID = "7658096633384781588"

_NEW_DEPLOYMENT_PRODUCTION_ID = "new_deployment_prod_merchant_999"
_NEW_DEPLOYMENT_SANDBOX_ID = "new_deployment_sandbox_merchant_999"


@pytest.fixture(autouse=True)
def _restore_reloaded_modules():
    """Guarantee capabilities/factories globals are back to defaults.

    ``factories.py``'s ``create()`` methods resolve ``PRODUCTION_AUTH_ID`` /
    ``SANDBOX_AUTH_ID`` as module globals at call time, not at import time.
    A reload performed by a test in this file mutates the (shared, cached)
    module object in place, so leaving it reloaded with a non-default env
    would break unrelated tests elsewhere in the suite that build clients
    via these factories and expect Juli's default IDs.
    """
    yield
    os.environ.pop("TIKTOK_PRODUCTION_MERCHANT_ID", None)
    os.environ.pop("TIKTOK_SANDBOX_MERCHANT_ID", None)
    importlib.reload(merchant)
    importlib.reload(capabilities)
    importlib.reload(factories)


def _reload_chain_with_env(monkeypatch, *, production_id: str, sandbox_id: str) -> None:
    monkeypatch.setenv("TIKTOK_PRODUCTION_MERCHANT_ID", production_id)
    monkeypatch.setenv("TIKTOK_SANDBOX_MERCHANT_ID", sandbox_id)
    importlib.reload(merchant)
    importlib.reload(capabilities)
    importlib.reload(factories)


class TestCapabilitiesModuleHasNoLiteralMerchantId:
    def test_capabilities_source_contains_no_hardcoded_merchant_id(self):
        source_path = Path(inspect.getfile(capabilities))
        source_text = source_path.read_text(encoding="utf-8")

        assert _JULI_DEFAULT_PRODUCTION_AUTH_ID not in source_text
        assert _JULI_DEFAULT_SANDBOX_AUTH_ID not in source_text


class TestCapabilitiesAndFactoriesFollowMerchantEnvConfig:
    """Regression test tying capabilities.py/factories.py to merchant.py.

    Must FAIL against the pre-#1246 code: capabilities.py held its own
    independent literals unrelated to merchant.py, so reloading merchant
    (and re-reading capabilities/factories fresh) would not change what
    they compare against -- proving this test exercises the real defect,
    not a vacuous pass.
    """

    def test_setting_production_env_var_changes_capabilities_and_factories(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert merchant.PRODUCTION_AUTH_ID == _NEW_DEPLOYMENT_PRODUCTION_ID
        assert capabilities.PRODUCTION_AUTH_ID == _NEW_DEPLOYMENT_PRODUCTION_ID
        assert factories.PRODUCTION_AUTH_ID == _NEW_DEPLOYMENT_PRODUCTION_ID

    def test_setting_sandbox_env_var_changes_capabilities_and_factories(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert merchant.SANDBOX_AUTH_ID == _NEW_DEPLOYMENT_SANDBOX_ID
        assert capabilities.SANDBOX_AUTH_ID == _NEW_DEPLOYMENT_SANDBOX_ID
        assert factories.SANDBOX_AUTH_ID == _NEW_DEPLOYMENT_SANDBOX_ID

    def test_unset_env_stays_byte_identical_to_juli_defaults_after_reload(self, monkeypatch):
        monkeypatch.delenv("TIKTOK_PRODUCTION_MERCHANT_ID", raising=False)
        monkeypatch.delenv("TIKTOK_SANDBOX_MERCHANT_ID", raising=False)
        importlib.reload(merchant)
        importlib.reload(capabilities)
        importlib.reload(factories)

        assert capabilities.PRODUCTION_AUTH_ID == _JULI_DEFAULT_PRODUCTION_AUTH_ID
        assert capabilities.SANDBOX_AUTH_ID == _JULI_DEFAULT_SANDBOX_AUTH_ID
        assert factories.PRODUCTION_AUTH_ID == _JULI_DEFAULT_PRODUCTION_AUTH_ID
        assert factories.SANDBOX_AUTH_ID == _JULI_DEFAULT_SANDBOX_AUTH_ID


class TestFactoriesBuildClientsForEnvConfiguredMerchant:
    """End-to-end: a non-Juli, env-configured merchant ID must build, not raise."""

    def test_production_read_factory_builds_client_for_configured_merchant(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        config = factories.ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            shop_cipher="ROW_cipher1234567890",
        )

        client = factories.ProductionReadClientFactory().create(config)

        assert client is not None
        assert client._merchant_auth_id == _NEW_DEPLOYMENT_PRODUCTION_ID

    def test_sandbox_write_factory_builds_client_for_configured_merchant(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        config = factories.ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=_NEW_DEPLOYMENT_SANDBOX_ID,
            shop_cipher="ROW_sandboxcipher12",
        )

        client = factories.SandboxWriteClientFactory().create(config)

        assert client is not None
        assert client._merchant_auth_id == _NEW_DEPLOYMENT_SANDBOX_ID


class TestGuardStillFailsClosedAfterEnvReconfiguration:
    """A mismatched merchant must still raise ValueError -- fail closed."""

    def test_production_factory_rejects_id_not_matching_configured_merchant(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        config = factories.ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            # Juli's OLD literal, no longer the configured merchant for this
            # deployment -- must still fail closed, never silently accepted.
            merchant_auth_id=_JULI_DEFAULT_PRODUCTION_AUTH_ID,
            shop_cipher="ROW_cipher1234567890",
        )

        with pytest.raises(ValueError, match="Fujiwa"):
            factories.ProductionReadClientFactory().create(config)

    def test_sandbox_factory_rejects_id_not_matching_configured_merchant(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        config = factories.ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=_JULI_DEFAULT_SANDBOX_AUTH_ID,
            shop_cipher="ROW_sandboxcipher12",
        )

        with pytest.raises(ValueError, match="SANDBOX_VN"):
            factories.SandboxWriteClientFactory().create(config)

    def test_cross_merchant_still_rejected_between_the_two_new_ids(self, monkeypatch):
        _reload_chain_with_env(
            monkeypatch,
            production_id=_NEW_DEPLOYMENT_PRODUCTION_ID,
            sandbox_id=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        config = factories.ClientFactoryConfig(
            app_key="app-key",
            app_secret="app-secret",
            access_token="access-token",
            merchant_auth_id=_NEW_DEPLOYMENT_SANDBOX_ID,
            shop_cipher="ROW_cipher1234567890",
        )

        with pytest.raises(ValueError, match="Fujiwa"):
            factories.ProductionReadClientFactory().create(config)
