"""Fail-closed startup assertion for the agent-workflow Celery broker.

ADR-074 decision 4, "the trap": ``celery_app.py``'s broker defaults to
``os.getenv("CELERY_BROKER_URL", "memory://")`` with no assertion today. An
agent-enabled deployment can boot green on ``memory://`` and silently run a
non-durable agent path — events still replay correctly because Postgres is
the replay authority (ADR-074 decision 1), but the *queue's* real
concurrency/redelivery semantics do not exist under ``memory://``: a worker
restart silently evaporates every queued or in-flight ``run_agent_workflow``
task, with no error anywhere.

``AGENT_WORKFLOWS_ENABLED`` is the discriminator this module introduces (no
prior flag of this shape existed in the repo — see ``run_agent_broker_startup_check``
callers for how it gates). It is intentionally **separate** from
``CELERY_BROKER_URL`` itself: the assertion must fire only for deployments
that actually run agent workflows, never for the unit-test default or a
deployment that has not opted into the agent stack yet (ADR-071's
"key-assertion pattern" — see ``core/config/runtime.py::require_env`` for the
sibling case, `OPENAI_API_KEY`).

``memory://`` stays the default broker and the unit-test default
unconditionally — this module only ever *reads* the resolved broker URL, it
never changes what ``celery_app.py`` defaults to.
"""

from __future__ import annotations

import os

MEMORY_BROKER_PREFIX = "memory://"
AGENT_WORKFLOWS_ENABLED_ENV_VAR = "AGENT_WORKFLOWS_ENABLED"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def agent_workflows_enabled() -> bool:
    """Whether this deployment is agent-enabled.

    Unset (or any non-truthy value) means "not agent-enabled" — the same
    fail-safe-by-omission shape as ``core/config/runtime.py::_environment``:
    a forgotten variable can never silently flip a deployment into the
    stricter path by accident, only ever leave it in the permissive one.
    """
    raw = os.environ.get(AGENT_WORKFLOWS_ENABLED_ENV_VAR, "").strip().lower()
    return raw in _TRUTHY


def assert_agent_broker_is_durable(broker_url: str, *, enabled: bool) -> None:
    """Raise ``RuntimeError`` iff ``enabled`` and ``broker_url`` is ``memory://``.

    Pure function, no environment reads — the boundary the tests exercise
    directly in both directions (crash / no-crash) without needing to
    reimport ``celery_app`` or touch process environment. ``enabled=False``
    always returns silently, whatever the broker: this is exactly what keeps
    ``memory://`` safe as the unit-test default and for non-agent
    deployments (ADR-074 decision 4).
    """
    if not enabled:
        return
    if broker_url.startswith(MEMORY_BROKER_PREFIX):
        raise RuntimeError(
            "Agent workflows are enabled "
            f"({AGENT_WORKFLOWS_ENABLED_ENV_VAR}=1) but CELERY_BROKER_URL resolves to "
            f"the in-memory transport ({broker_url!r}). memory:// has no real queue "
            "durability, concurrency, or redelivery semantics: every queued or "
            "in-flight run_agent_workflow/resume_agent_workflow task evaporates on "
            "worker restart, silently. Set CELERY_BROKER_URL to a real broker (e.g. "
            "redis://...) before enabling agent workflows."
        )


def run_agent_broker_startup_check(broker_url: str) -> None:
    """The actual boot-time call: reads ``AGENT_WORKFLOWS_ENABLED`` from the
    environment and asserts the resolved broker against it.

    Called unconditionally at the bottom of ``celery_app.py`` on every import
    (worker boot, beat boot, and every test that imports the module) —
    cheap and side-effect-free whenever the deployment is not agent-enabled,
    which is what keeps the existing non-agent unit-test suite unaffected.
    """
    assert_agent_broker_is_durable(broker_url, enabled=agent_workflows_enabled())
