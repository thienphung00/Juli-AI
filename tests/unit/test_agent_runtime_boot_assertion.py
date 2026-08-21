"""ADR-075 decision 3: the consolidated `assert_agent_runtime_config()` boot
assertion -- issue #1217 / AGT-W5B.

Six individually-named checks, called at both API and worker boot:

1. `OPENAI_API_KEY` present
2. A real broker, never `memory://` (absorbs the existing #1129 broker guard
   -- `workers/agent_broker_guard.py` -- unchanged, never duplicated)
3. The banned-patterns source loads and compiles
4. Sandbox-write guard config resolvable for every registered WRITE tool
5. `SUPABASE_JWT_SECRET` present -- **unconditional**, independent of
   `AGENT_WORKFLOWS_ENABLED`
6. Structural backstop: a production-write-capable deployment (proxied by
   `is_production()`, the same discriminator that already gates `/docs`)
   exposes zero unauthenticated routes in the `agent-runs` route group

Checks 1, 2, 3, 4, 6 stay no-ops when `AGENT_WORKFLOWS_ENABLED` is unset --
the same fail-safe-by-omission shape `agent_broker_guard.py` already
established for check 2 alone, now covering the whole consolidated
function. Check 5 is the one exception: it fires regardless, matching its
existing unconditional wiring in `api/main.py`'s lifespan (#902 / ADR-061).

AC -> test map:
- "each of the six checks, individually unmet, fails boot with a message
  naming that check" -> the six `Test*IndividuallyUnmet` classes below
- "an empty SUPABASE_JWT_SECRET crashes at boot rather than verifying
  everything" -> test_check5_fires_even_when_every_other_check_would_fail
- "the existing memory:// assertion keeps its current behaviour and
  message" -> test_check2_message_is_the_unmodified_broker_guard_message
- "a deployment with AGENT_WORKFLOWS_ENABLED unset is unaffected" ->
  Test*NoOpsWhenAgentWorkflowsDisabled
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI

from juli_backend.core.security import get_current_user
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent.sanitize import banned_patterns as banned_patterns_module
from juli_backend.workers.agent_broker_guard import AGENT_WORKFLOWS_ENABLED_ENV_VAR
from juli_backend.workers.agent_runtime_boot import (
    AGENT_RUN_ROUTE_TAG,
    assert_agent_runtime_config,
)

# ---------------------------------------------------------------------------
# Shared "everything is fine" baseline -- each individually-unmet test
# starts here and breaks exactly one dimension.
# ---------------------------------------------------------------------------


def _set_valid_baseline_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-key")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-tiktok-app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-tiktok-app-secret")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "test-supabase-jwt-secret")
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def _authenticated_agent_app() -> FastAPI:
    app = FastAPI()

    @app.get("/v1/demo/runs/{run_id}/events", tags=[AGENT_RUN_ROUTE_TAG])
    async def _events(run_id: str, user=Depends(get_current_user)) -> dict:
        return {"run_id": run_id}

    return app


def _unauthenticated_agent_app() -> FastAPI:
    app = FastAPI()

    @app.get("/v1/demo/runs/{run_id}/events", tags=[AGENT_RUN_ROUTE_TAG])
    async def _events(run_id: str) -> dict:
        return {"run_id": run_id}

    return app


# ---------------------------------------------------------------------------
# Success: every check passes, function returns None, raises nothing.
# ---------------------------------------------------------------------------


def test_all_six_checks_pass_returns_none(monkeypatch):
    _set_valid_baseline_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert assert_agent_runtime_config(app=_authenticated_agent_app()) is None


def test_passes_with_no_app_and_no_broker_url_args_supplied_worker_style(monkeypatch):
    """Worker boot never has a FastAPI app -- check 6 must simply be skipped,
    never crash for lack of one."""
    _set_valid_baseline_env(monkeypatch)
    assert assert_agent_runtime_config() is None


# ---------------------------------------------------------------------------
# Check 1 -- OPENAI_API_KEY present
# ---------------------------------------------------------------------------


class TestCheck1IndividuallyUnmet:
    def test_missing_openai_api_key_fails_boot_naming_that_key(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            assert_agent_runtime_config()

    def test_no_ops_when_agent_workflows_disabled(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert assert_agent_runtime_config() is None


# ---------------------------------------------------------------------------
# Check 2 -- real broker, never memory://. Absorbed from agent_broker_guard,
# unmodified message/behaviour.
# ---------------------------------------------------------------------------


class TestCheck2IndividuallyUnmet:
    def test_memory_broker_fails_boot_naming_memory_transport(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
        with pytest.raises(RuntimeError, match="memory://"):
            assert_agent_runtime_config()

    def test_message_is_the_unmodified_broker_guard_message(self, monkeypatch):
        """AC: this slice absorbs the existing assertion rather than
        duplicating it -- the raised message must be byte-identical to
        `assert_agent_broker_is_durable`'s own, unwrapped."""
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
        with pytest.raises(RuntimeError) as exc_info:
            assert_agent_runtime_config()
        assert "Agent workflows are enabled" in str(exc_info.value)
        assert "has no real queue durability" in str(exc_info.value)

    def test_broker_url_argument_overrides_env_var(self, monkeypatch):
        """`celery_app.py` passes its own resolved `celery_app.conf.broker_url`
        explicitly rather than relying on the env-var default."""
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
        with pytest.raises(RuntimeError, match="memory://"):
            assert_agent_runtime_config(broker_url="memory://")

    def test_no_ops_when_agent_workflows_disabled(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.setenv("CELERY_BROKER_URL", "memory://")
        assert assert_agent_runtime_config() is None


# ---------------------------------------------------------------------------
# Check 3 -- banned-patterns source loads and compiles
# ---------------------------------------------------------------------------


class TestCheck3IndividuallyUnmet:
    def test_unreadable_banned_patterns_source_fails_boot(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setattr(
            banned_patterns_module,
            "BANNED_PATTERNS_JSON_PATH",
            Path("/nonexistent/seller-copy-banned-patterns.json"),
        )
        banned_patterns_module.load_banned_patterns.cache_clear()
        try:
            with pytest.raises(RuntimeError, match="banned-patterns"):
                assert_agent_runtime_config()
        finally:
            banned_patterns_module.load_banned_patterns.cache_clear()

    def test_no_ops_when_agent_workflows_disabled(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.setattr(
            banned_patterns_module,
            "BANNED_PATTERNS_JSON_PATH",
            Path("/nonexistent/seller-copy-banned-patterns.json"),
        )
        banned_patterns_module.load_banned_patterns.cache_clear()
        try:
            assert assert_agent_runtime_config() is None
        finally:
            banned_patterns_module.load_banned_patterns.cache_clear()


# ---------------------------------------------------------------------------
# Check 4 -- sandbox-write guard config resolvable for every registered
# WRITE tool. No per-tool config table: one shared TIKTOK_APP_KEY /
# TIKTOK_APP_SECRET resolver behind every registered WRITE tool name.
# ---------------------------------------------------------------------------


class TestCheck4IndividuallyUnmet:
    def test_missing_tiktok_app_key_fails_boot_naming_registered_write_tools(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        write_tool_names = composition_module.measurable_write_tool_names()
        with pytest.raises(RuntimeError) as exc_info:
            assert_agent_runtime_config()
        message = str(exc_info.value)
        assert "TIKTOK_APP_KEY" in message
        for name in write_tool_names:
            assert name in message

    def test_missing_tiktok_app_secret_fails_boot(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="TIKTOK_APP_SECRET"):
            assert_agent_runtime_config()

    def test_no_ops_when_agent_workflows_disabled(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        assert assert_agent_runtime_config() is None


# ---------------------------------------------------------------------------
# Check 5 -- SUPABASE_JWT_SECRET present, UNCONDITIONAL.
# ---------------------------------------------------------------------------


class TestCheck5IndividuallyUnmet:
    def test_missing_supabase_jwt_secret_fails_boot(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
            assert_agent_runtime_config()

    def test_fires_even_when_agent_workflows_disabled(self, monkeypatch):
        """AC: an empty SUPABASE_JWT_SECRET crashes at boot rather than
        verifying everything -- this is the one check that is NOT gated
        behind AGENT_WORKFLOWS_ENABLED."""
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
            assert_agent_runtime_config()

    def test_fires_even_when_every_other_check_would_also_fail(self, monkeypatch):
        """The unconditional check must not be masked by, nor depend on,
        any of the other five."""
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
        monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
        monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
        monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="SUPABASE_JWT_SECRET"):
            assert_agent_runtime_config()


# ---------------------------------------------------------------------------
# Check 6 -- structural backstop: zero unauthenticated routes in the
# agent-runs route group, for a production-write-capable (is_production())
# deployment. Worker boot passes no `app` at all -- this check is skipped,
# never crashes for lack of one (proven above in
# test_passes_with_no_app_and_no_broker_url_args_supplied_worker_style).
# ---------------------------------------------------------------------------


class TestCheck6IndividuallyUnmet:
    def test_unauthenticated_agent_run_route_fails_boot_in_production(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(RuntimeError, match=AGENT_RUN_ROUTE_TAG):
            assert_agent_runtime_config(app=_unauthenticated_agent_app())

    def test_names_the_offending_route_path(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(RuntimeError, match=r"/v1/demo/runs/\{run_id\}/events"):
            assert_agent_runtime_config(app=_unauthenticated_agent_app())

    def test_authenticated_agent_run_route_passes_in_production(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert assert_agent_runtime_config(app=_authenticated_agent_app()) is None

    def test_no_op_outside_production_even_when_unauthenticated(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        assert assert_agent_runtime_config(app=_unauthenticated_agent_app()) is None

    def test_no_op_when_no_app_supplied_even_in_production(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert assert_agent_runtime_config(app=None) is None

    def test_no_ops_when_agent_workflows_disabled_even_in_production(self, monkeypatch):
        _set_valid_baseline_env(monkeypatch)
        monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert assert_agent_runtime_config(app=_unauthenticated_agent_app()) is None
