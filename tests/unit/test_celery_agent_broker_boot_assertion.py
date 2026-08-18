"""Fail-closed boot assertion for the agent Celery broker (#1129, ADR-074 d.4, "the trap").

`celery_app.py`'s broker defaults to `os.getenv("CELERY_BROKER_URL", "memory://")`
with no assertion. That default is the trap: an agent-enabled deployment can boot
green on `memory://` and silently run a non-durable agent path. Tested both ways
per the issue's explicit instruction ("a one-sided test here is worse than none"):

- crashes when agent-enabled and the broker resolves to `memory://`
  (unset OR explicit) -> test_*_crashes_*
- does NOT crash when agent-enabled and the broker is a real URL -> test_*_does_not_crash_*
- does NOT crash when not agent-enabled, whatever the broker (incl. the unit-test
  default) -> test_*_not_agent_enabled_*
- the real `celery_app.py` module wiring, exercised in a subprocess so this suite
  never mutates the shared `celery_app` singleton every other unit test imports
  -> test_real_celery_app_boot_*
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from juli_backend.workers.agent_broker_guard import (
    AGENT_WORKFLOWS_ENABLED_ENV_VAR,
    agent_workflows_enabled,
    assert_agent_broker_is_durable,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"


# ---------------------------------------------------------------------------
# Pure function: both directions, no process boundary needed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("broker_url", ["memory://", "memory://transport"])
def test_assertion_crashes_when_agent_enabled_and_broker_is_memory(broker_url):
    with pytest.raises(RuntimeError, match="memory://"):
        assert_agent_broker_is_durable(broker_url, enabled=True)


def test_assertion_does_not_crash_when_agent_enabled_and_broker_is_real():
    # Must not raise.
    assert_agent_broker_is_durable("redis://localhost:6379/0", enabled=True)


@pytest.mark.parametrize("broker_url", ["memory://redis", "memory://?redis=1"])
def test_assertion_crashes_on_memory_transport_even_when_url_contains_redis(broker_url):
    """Pin the check as a `memory://` *prefix* test, not a `"redis" not in url` substring test.

    A broker URL can merely *mention* "redis" (query param, path segment, a sloppy
    copy-paste) while still being the in-memory kombu transport underneath —
    `memory://redis` and `memory://?redis=1` are both still `memory://`. A substring
    check (`"redis" not in broker_url`) would wrongly treat either as durable and
    silently defeat the entire assertion this module exists for. Mutating
    `assert_agent_broker_is_durable`'s `broker_url.startswith(MEMORY_BROKER_PREFIX)`
    check to `"redis" not in broker_url` makes this exact test fail (verified by
    hand during review follow-up for #1129) — the other tests in this file do not
    catch that mutation because none of them exercise a `memory://` URL that also
    contains a durable-broker substring.
    """
    with pytest.raises(RuntimeError, match="memory://"):
        assert_agent_broker_is_durable(broker_url, enabled=True)


@pytest.mark.parametrize("broker_url", ["memory://", "redis://localhost:6379/0"])
def test_assertion_does_not_crash_when_not_agent_enabled(broker_url):
    # Gated to agent-enabled deployments only (issue text) -- disabled must never raise,
    # whatever the broker, or the existing non-agent unit-test suite's boot would break.
    assert_agent_broker_is_durable(broker_url, enabled=False)


# ---------------------------------------------------------------------------
# agent_workflows_enabled(): the env-var discriminator itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on"])
def test_agent_workflows_enabled_true_for_truthy_values(monkeypatch, value):
    monkeypatch.setenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, value)
    assert agent_workflows_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "garbage"])
def test_agent_workflows_enabled_false_for_everything_else(monkeypatch, value):
    monkeypatch.setenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, value)
    assert agent_workflows_enabled() is False


def test_agent_workflows_enabled_false_when_unset(monkeypatch):
    monkeypatch.delenv(AGENT_WORKFLOWS_ENABLED_ENV_VAR, raising=False)
    assert agent_workflows_enabled() is False


# ---------------------------------------------------------------------------
# Real `celery_app.py` module wiring, exercised via subprocess.
#
# A fresh Python process per case is deliberate: `celery_app.py` runs its
# startup check as module-level code on import. Reimporting/reloading it
# in-process would replace the one `celery_app` singleton every other unit
# test in this suite imports `Task`/`beat_schedule`/routing off of --
# corrupting shared state for tests that run later in the same session.
# subprocess isolates each "boot" completely, at the cost of one extra
# process per case (a handful across this file, not per-test).
# ---------------------------------------------------------------------------


def _run_boot_in_subprocess(
    env_overrides: dict[str, str], code: str
) -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env.pop("CELERY_BROKER_URL", None)
    env.pop(AGENT_WORKFLOWS_ENABLED_ENV_VAR, None)
    env.update(env_overrides)
    env["PYTHONPATH"] = str(BACKEND_SRC)
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_real_celery_app_boot_crashes_on_memory_default_when_agent_enabled():
    result = _run_boot_in_subprocess(
        {AGENT_WORKFLOWS_ENABLED_ENV_VAR: "1"},
        "from juli_backend.workers.celery_app import celery_app",
    )
    assert result.returncode != 0, (
        f"boot must crash; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "RuntimeError" in result.stderr
    assert "memory://" in result.stderr


def test_real_celery_app_boot_crashes_on_explicit_memory_broker_when_agent_enabled():
    result = _run_boot_in_subprocess(
        {AGENT_WORKFLOWS_ENABLED_ENV_VAR: "1", "CELERY_BROKER_URL": "memory://"},
        "from juli_backend.workers.celery_app import celery_app",
    )
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr


def test_real_celery_app_boot_does_not_crash_on_real_broker_when_agent_enabled():
    result = _run_boot_in_subprocess(
        {
            AGENT_WORKFLOWS_ENABLED_ENV_VAR: "1",
            "CELERY_BROKER_URL": "redis://localhost:6379/0",
        },
        "from juli_backend.workers.celery_app import celery_app; print('booted')",
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "booted" in result.stdout


def test_real_celery_app_boot_does_not_crash_when_not_agent_enabled_on_memory_default():
    """The existing non-agent unit-test suite's Celery boot must be unaffected."""
    result = _run_boot_in_subprocess(
        {},
        "from juli_backend.workers.celery_app import celery_app; print(celery_app.conf.broker_url)",
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "memory://" in result.stdout
