"""Deployment-surface wiring for AGENT_WORKFLOWS_ENABLED (Issue #1164).

#1129's fail-closed broker assertion (agent_broker_guard.py, ADR-074 decision 4) reads
AGENT_WORKFLOWS_ENABLED from the environment at Celery import time, but until this issue the
flag appeared in no deployment surface -- no env example, no systemd unit -- so a real VPS
deployment could never carry it and the assertion could never fire. These tests pin the flag's
literal name into every surface a real deployment reads: infra/scripts/env/api.env.example (the
source of the VPS's /etc/juli/api.env) and the three systemd unit templates that source that
file via EnvironmentFile= (API, Celery worker, Celery beat), so the wiring cannot silently
regress the way the original #1129 gap did.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from juli_backend.workers.agent_broker_guard import (  # noqa: E402
    AGENT_WORKFLOWS_ENABLED_ENV_VAR,
)

ENV_EXAMPLE = REPO_ROOT / "infra" / "scripts" / "env" / "api.env.example"
API_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-api.service"
WORKER_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-celery-worker.service"
BEAT_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-celery-beat.service"

DEPLOYMENT_SURFACES = (ENV_EXAMPLE, API_UNIT, WORKER_UNIT, BEAT_UNIT)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment surface: {path}"
    return path.read_text(encoding="utf-8")


def test_flag_name_matches_the_guard_module():
    """Guard the test itself against drifting from the literal agent_broker_guard.py reads."""
    assert AGENT_WORKFLOWS_ENABLED_ENV_VAR == "AGENT_WORKFLOWS_ENABLED"


def test_flag_appears_in_every_deployment_surface():
    """The literal env var name must be present in the env example and all three unit files.

    A real VPS deployment sources /etc/juli/api.env (generated from api.env.example) via each
    unit's EnvironmentFile= directive. If the flag's name is absent from any of these four
    files, a real deployment cannot set it, and #1129's fail-closed assertion can never fire on
    a real box -- exactly the gap #1164 closes.
    """
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in DEPLOYMENT_SURFACES
        if AGENT_WORKFLOWS_ENABLED_ENV_VAR not in _read(path)
    ]
    assert not missing, f"AGENT_WORKFLOWS_ENABLED missing from: {missing}"


def test_env_example_defaults_the_flag_off():
    """Default-off: an operator must opt in explicitly, never inherit an enabled state."""
    env_text = _read(ENV_EXAMPLE)
    assert "AGENT_WORKFLOWS_ENABLED=false" in env_text, (
        "api.env.example must set AGENT_WORKFLOWS_ENABLED=false explicitly (default off) so a "
        "fresh deployment never silently boots agent-enabled"
    )


def test_env_example_documents_the_fail_closed_contract():
    """The comment must state the actual contract, not just carry the bare key=value."""
    env_text = _read(ENV_EXAMPLE).lower()
    idx = env_text.index("agent_workflows_enabled=false")
    window = env_text[max(0, idx - 800) : idx]
    assert "redis" in window, "comment above the flag must name the real Redis broker requirement"
    assert "refuse" in window or "require" in window, (
        "comment above the flag must state the fail-closed contract (refuses to start / "
        "requires a real broker)"
    )


def test_unit_files_reference_the_broker_guard_contract():
    """Each unit's comment should point at agent_broker_guard.py/ADR-074, not just the bare var."""
    for path in (API_UNIT, WORKER_UNIT, BEAT_UNIT):
        text = _read(path)
        assert AGENT_WORKFLOWS_ENABLED_ENV_VAR in text
        assert "agent_broker_guard" in text or "ADR-074" in text, (
            f"{path.name} references AGENT_WORKFLOWS_ENABLED but not the guard module/ADR that "
            "explains why -- add context so an operator reading the unit understands the flag"
        )
