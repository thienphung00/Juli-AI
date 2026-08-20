"""`capabilities.py` sources its merchant IDs from `merchant.py` (#1246).

#1234 moved `PRODUCTION_AUTH_ID` / `SANDBOX_AUTH_ID` into environment
configuration, but only in `merchant.py`. `capabilities.py` kept its own
independent literals, and `factories.py` imports *those* and hard-compares
them -- so a deployment that configured its own merchants got correct
classification from `merchant.resolve_merchant_context` and then a guard that
still measured against Juli's compiled-in IDs.

## Why these tests run in subprocesses

The re-export is `from ... import PRODUCTION_AUTH_ID as PRODUCTION_AUTH_ID`,
which binds **at import time**. That is correct for production, where the
environment is set before the process starts -- but it means the wiring cannot
be exercised by mutating a live module:

- `importlib.reload` propagates the value, but mutates the shared module
  objects in place and hands every class in them (including `factories`'
  `ProductionReadResources` / `SandboxWriteResources` dataclasses) a **new
  class identity**, breaking `isinstance` in any test module that already
  imported the originals. Reproduced against `test_layer1_read_resources.py`
  and `test_layer2_sandbox_write_contract.py`.
- `monkeypatch.setattr` on `capabilities` / `factories` avoids that, but
  pre-seeds the very values the assertions then check. It proves the
  monkeypatch harness worked, not that `capabilities` reads from `merchant`:
  with the production fix reverted, six of nine tests still passed.

A subprocess sets the environment **before** the interpreter imports anything,
which is exactly how production resolves these, and cannot touch this
interpreter's module cache. Slower, but it tests the real path and nothing
else. Verified to fail with the production fix reverted -- see
`test_configured_env_reaches_the_transport_guard`.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import juli_backend.integrations.tiktok.capabilities as capabilities
import juli_backend.integrations.tiktok.merchant as merchant

# Juli's own already-committed IDs (the documented fallback defaults) -- not
# secrets, used only to assert unset-env behaviour is unchanged.
_JULI_DEFAULT_PRODUCTION_AUTH_ID = "7658073774813611784"
_JULI_DEFAULT_SANDBOX_AUTH_ID = "7658096633384781588"

_NEW_DEPLOYMENT_PRODUCTION_ID = "new_deployment_prod_merchant_999"
_NEW_DEPLOYMENT_SANDBOX_ID = "new_deployment_sandbox_merchant_999"

# parents[3] is `backend/src`. parents[4] is `backend/`, which would leave
# `juli_backend` unimportable from PYTHONPATH -- and because the package is
# also pip-installed, the subprocess would silently fall back to the INSTALLED
# copy and test main's code instead of this worktree's. Verified by printing
# the resolved path rather than counting directories by eye.
_BACKEND_SRC = str(Path(inspect.getfile(merchant)).parents[3])


def _run_with_env(snippet: str, **env_overrides: str) -> str:
    """Import the chain in a fresh interpreter with the given environment.

    Returns stdout. Raises with the child's stderr attached on failure, so a
    broken assertion inside the subprocess surfaces as a readable message
    rather than an empty-output mystery.
    """
    env = {**os.environ, **env_overrides, "PYTHONPATH": _BACKEND_SRC}
    for key in ("TIKTOK_PRODUCTION_MERCHANT_ID", "TIKTOK_SANDBOX_MERCHANT_ID"):
        if key not in env_overrides:
            env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"subprocess failed (exit {result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return result.stdout.strip()


class TestCapabilitiesHasNoLiteralAndSourcesFromMerchant:
    """Structural checks -- no interpreter state involved, so no isolation risk."""

    def test_capabilities_source_contains_no_hardcoded_merchant_id(self):
        source_text = Path(inspect.getfile(capabilities)).read_text(encoding="utf-8")

        assert _JULI_DEFAULT_PRODUCTION_AUTH_ID not in source_text
        assert _JULI_DEFAULT_SANDBOX_AUTH_ID not in source_text

    def test_capabilities_imports_both_names_from_merchant(self):
        """The names must be imported from `merchant`, not merely absent.

        A same-valued literal defined some other way would pass the source-text
        check above; this pins the actual wiring in the AST.
        """
        tree = ast.parse(Path(inspect.getfile(capabilities)).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "merchant" in node.module:
                imported.update(alias.name for alias in node.names)

        assert "PRODUCTION_AUTH_ID" in imported
        assert "SANDBOX_AUTH_ID" in imported


class TestConfiguredEnvReachesTheTransportGuard:
    """The end-to-end property #1246 exists to guarantee.

    Each test starts a fresh interpreter with the environment already set, so
    the import-time binding resolves the way it does in production.
    """

    def test_configured_env_reaches_the_transport_guard(self):
        """With the fix reverted, capabilities keeps Juli's literal and this fails."""
        out = _run_with_env(
            """
            import juli_backend.integrations.tiktok.capabilities as c
            import juli_backend.integrations.tiktok.factories as f
            print(c.PRODUCTION_AUTH_ID, c.SANDBOX_AUTH_ID, f.PRODUCTION_AUTH_ID, f.SANDBOX_AUTH_ID)
            """,
            TIKTOK_PRODUCTION_MERCHANT_ID=_NEW_DEPLOYMENT_PRODUCTION_ID,
            TIKTOK_SANDBOX_MERCHANT_ID=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert out.split() == [
            _NEW_DEPLOYMENT_PRODUCTION_ID,
            _NEW_DEPLOYMENT_SANDBOX_ID,
            _NEW_DEPLOYMENT_PRODUCTION_ID,
            _NEW_DEPLOYMENT_SANDBOX_ID,
        ]

    def test_production_factory_builds_client_for_configured_merchant(self):
        out = _run_with_env(
            """
            import juli_backend.integrations.tiktok.factories as f
            config = f.ClientFactoryConfig(
                app_key="app-key",
                app_secret="app-secret",
                access_token="access-token",
                merchant_auth_id="new_deployment_prod_merchant_999",
                shop_cipher="ROW_cipher1234567890",
            )
            f.ProductionReadClientFactory().create(config)
            print("BUILT")
            """,
            TIKTOK_PRODUCTION_MERCHANT_ID=_NEW_DEPLOYMENT_PRODUCTION_ID,
            TIKTOK_SANDBOX_MERCHANT_ID=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert out == "BUILT"

    def test_sandbox_factory_builds_client_for_configured_merchant(self):
        out = _run_with_env(
            """
            import juli_backend.integrations.tiktok.factories as f
            config = f.ClientFactoryConfig(
                app_key="app-key",
                app_secret="app-secret",
                access_token="access-token",
                merchant_auth_id="new_deployment_sandbox_merchant_999",
                shop_cipher="ROW_cipher1234567890",
            )
            f.SandboxWriteClientFactory().create(config)
            print("BUILT")
            """,
            TIKTOK_PRODUCTION_MERCHANT_ID=_NEW_DEPLOYMENT_PRODUCTION_ID,
            TIKTOK_SANDBOX_MERCHANT_ID=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert out == "BUILT"


class TestGuardStillFailsClosedAfterEnvReconfiguration:
    """The half of the defect #1245's review missed.

    Pre-#1246, a client carrying Juli's *old* ID was silently ACCEPTED by a
    deployment configured for different merchants, because the guard still
    compared against the frozen literal. Not a loud ValueError -- a silent
    cross-merchant acceptance.
    """

    def test_juli_old_id_is_rejected_once_another_merchant_is_configured(self):
        out = _run_with_env(
            f"""
            import juli_backend.integrations.tiktok.factories as f
            config = f.ClientFactoryConfig(
                app_key="app-key",
                app_secret="app-secret",
                access_token="access-token",
                merchant_auth_id="{_JULI_DEFAULT_PRODUCTION_AUTH_ID}",
                shop_cipher="ROW_cipher1234567890",
            )
            try:
                f.ProductionReadClientFactory().create(config)
            except ValueError:
                print("REJECTED")
            else:
                print("ACCEPTED")
            """,
            TIKTOK_PRODUCTION_MERCHANT_ID=_NEW_DEPLOYMENT_PRODUCTION_ID,
            TIKTOK_SANDBOX_MERCHANT_ID=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert out == "REJECTED"

    def test_cross_merchant_still_rejected_between_the_configured_ids(self):
        out = _run_with_env(
            """
            import juli_backend.integrations.tiktok.factories as f
            config = f.ClientFactoryConfig(
                app_key="app-key",
                app_secret="app-secret",
                access_token="access-token",
                merchant_auth_id="new_deployment_sandbox_merchant_999",
                shop_cipher="ROW_cipher1234567890",
            )
            try:
                f.ProductionReadClientFactory().create(config)
            except ValueError:
                print("REJECTED")
            else:
                print("ACCEPTED")
            """,
            TIKTOK_PRODUCTION_MERCHANT_ID=_NEW_DEPLOYMENT_PRODUCTION_ID,
            TIKTOK_SANDBOX_MERCHANT_ID=_NEW_DEPLOYMENT_SANDBOX_ID,
        )

        assert out == "REJECTED"


class TestUnsetEnvKeepsJuliDefaults:
    @pytest.mark.skipif(
        bool(os.getenv("TIKTOK_PRODUCTION_MERCHANT_ID"))
        or bool(os.getenv("TIKTOK_SANDBOX_MERCHANT_ID")),
        reason="merchant IDs are configured here; this asserts the unset-default path",
    )
    def test_unset_env_stays_byte_identical_to_juli_defaults(self):
        out = _run_with_env(
            """
            import juli_backend.integrations.tiktok.capabilities as c
            import juli_backend.integrations.tiktok.factories as f
            print(c.PRODUCTION_AUTH_ID, c.SANDBOX_AUTH_ID, f.PRODUCTION_AUTH_ID, f.SANDBOX_AUTH_ID)
            """
        )

        assert out.split() == [
            _JULI_DEFAULT_PRODUCTION_AUTH_ID,
            _JULI_DEFAULT_SANDBOX_AUTH_ID,
            _JULI_DEFAULT_PRODUCTION_AUTH_ID,
            _JULI_DEFAULT_SANDBOX_AUTH_ID,
        ]
