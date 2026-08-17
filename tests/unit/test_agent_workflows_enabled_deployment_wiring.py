"""Deployment-surface wiring for AGENT_WORKFLOWS_ENABLED (Issue #1164).

#1129's fail-closed broker assertion (agent_broker_guard.py, ADR-074 decision 4) reads
AGENT_WORKFLOWS_ENABLED from the environment at Celery import time, but until this issue the
flag appeared in no deployment surface -- no env example, no systemd unit, no runbook entry --
so a real VPS deployment could never carry it and the assertion could never fire.

The real production chain, per Review's #1164 finding: AWS Secrets Manager
(`juli/api/production`) -> infra/scripts/fetch-secrets.sh / refresh-secrets.sh -> the
generated /etc/juli/api.env that each systemd unit's EnvironmentFile= sources. NEITHER script
reads infra/scripts/env/api.env.example -- that file only documents the required-keys contract
and provisions the Celery-less App Review VPS (provision-backend.sh). So the flag's name must
appear in both: the env example (documentation + App Review VPS) and, as the actual source of
truth for a real deployment's secret contents, the "Secret inventory" table in
docs/runbooks/app-review-runbook.md (the durable pattern test_biz_oauth_ops_docs.py's
REQUIRED_ENV_KEYS establishes for other juli/api/production keys). These tests pin the flag's
literal name into all of: the runbook's Secret inventory table, the env example, and the three
systemd unit templates (API, Celery worker, Celery beat) whose EnvironmentFile= reads the file
that chain produces -- so the wiring cannot silently regress the way the original #1129 gap did.
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
APP_REVIEW_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "app-review-runbook.md"

DEPLOYMENT_SURFACES = (ENV_EXAMPLE, API_UNIT, WORKER_UNIT, BEAT_UNIT, APP_REVIEW_RUNBOOK)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing deployment surface: {path}"
    return path.read_text(encoding="utf-8")


def test_flag_name_matches_the_guard_module():
    """Guard the test itself against drifting from the literal agent_broker_guard.py reads."""
    assert AGENT_WORKFLOWS_ENABLED_ENV_VAR == "AGENT_WORKFLOWS_ENABLED"


def test_flag_appears_in_every_deployment_surface():
    """The literal env var name must be present in the runbook, env example, and all unit files.

    A real VPS deployment's /etc/juli/api.env is generated from AWS Secrets Manager secret
    juli/api/production by fetch-secrets.sh / refresh-secrets.sh -- NOT from api.env.example,
    which neither script reads. docs/runbooks/app-review-runbook.md's "Secret inventory" table
    is the authoritative, operator-facing list of what that secret must contain, so the flag
    must be documented there for an operator to ever set it in Secrets Manager in the first
    place. Each systemd unit's EnvironmentFile= then sources the /etc/juli/api.env that chain
    produces. If the flag's name is absent from any of these five files, a real deployment
    cannot carry it, and #1129's fail-closed assertion can never fire on a real box -- exactly
    the gap #1164 closes.
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


# AC (Review rework, #1164): the runbook's "Secret inventory" table is the actual source of
# truth for juli/api/production -- mirrors test_biz_oauth_ops_docs.py's
# test_env_var_names_and_required_vps_secrets_manager_keys_are_documented pattern for the same
# secret/table, applied to this flag.
def test_flag_documented_in_authoritative_secret_inventory():
    """The runbook's Secret inventory table -- not api.env.example -- is what an operator reads
    before running `aws secretsmanager put-secret-value --secret-id juli/api/production`. If the
    flag is absent from that table it does not exist as far as a real deployment is concerned,
    however correct the env example and unit-file comments are.
    """
    runbook_text = _read(APP_REVIEW_RUNBOOK)
    assert AGENT_WORKFLOWS_ENABLED_ENV_VAR in runbook_text
    assert "juli/api/production" in runbook_text


def test_runbook_states_the_default_and_fail_closed_contract():
    """The runbook entry must state default-off and the real-broker requirement, not just the
    bare key -- an operator deciding whether to flip this needs the contract in front of them,
    not a pointer to source code.
    """
    lowered = _read(APP_REVIEW_RUNBOOK).lower()
    idx = lowered.index("agent_workflows_enabled")
    window = lowered[idx : idx + 900]
    assert "false" in window, "runbook must state the default is false"
    assert "redis" in window or "broker" in window, "runbook must name the real-broker requirement"
    assert "refuse" in window or "require" in window, (
        "runbook must state the fail-closed contract (refuses to start / requires a real broker)"
    )


def test_runbook_documents_the_operator_enable_action():
    """Enabling is an operator action via Secrets Manager, not an env-example edit -- the
    runbook entry must point at that flow (put-secret-value/console + refresh) so an operator
    does not mistake editing api.env.example for actually enabling the flag in production.
    """
    lowered = _read(APP_REVIEW_RUNBOOK).lower()
    idx = lowered.index("agent_workflows_enabled")
    window = lowered[idx : idx + 900]
    assert "secretsmanager" in window or "secrets manager" in window, (
        "runbook must state that enabling is a Secrets Manager operator action"
    )
    assert "refresh-secrets" in window or "fetch-secrets" in window, (
        "runbook must point at the refresh/fetch-secrets flow that actually propagates the "
        "updated secret to /etc/juli/api.env"
    )
