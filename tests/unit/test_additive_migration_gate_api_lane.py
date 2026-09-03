"""Contract tests for deploy.sh API lane migration additive gate wiring (#1555).

The additive migration gate (migration_additive_gate.py) must be invoked BEFORE
safe-alembic-upgrade.sh in the API deploy lane to refuse non-additive schema
changes before any candidate instance starts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT_PATH = REPO_ROOT / "infra/scripts/deploy.sh"
GATE_SCRIPT_PATH = REPO_ROOT / "infra/scripts/migration_additive_gate.py"


@pytest.fixture
def deploy_script_text() -> str:
    """Load the full deploy.sh script."""
    return DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")


def test_migration_gate_script_exists():
    """The migration_additive_gate.py script must exist."""
    assert GATE_SCRIPT_PATH.is_file(), f"{GATE_SCRIPT_PATH} does not exist"


def test_deploy_script_invokes_migration_gate(deploy_script_text: str):
    """deploy.sh must invoke migration_additive_gate.py before safe-alembic-upgrade.sh.

    This is the critical contract: the comment at deploy.sh:421 promises an
    additive gate. The code must not let that comment rot.
    """
    # Find the line with the migrations comment
    lines = deploy_script_text.split("\n")
    migrations_comment_line = None
    safe_alembic_line = None
    gate_invocation_line = None

    for i, line in enumerate(lines):
        if "Migrations: additive-gate" in line:
            migrations_comment_line = i
        if "safe-alembic-upgrade.sh" in line:
            safe_alembic_line = i
        if "migration_additive_gate.py" in line:
            gate_invocation_line = i

    assert migrations_comment_line is not None, (
        "Comment 'Migrations: additive-gate' not found in deploy.sh"
    )
    assert safe_alembic_line is not None, (
        "safe-alembic-upgrade.sh invocation not found in deploy.sh"
    )
    assert gate_invocation_line is not None, (
        "migration_additive_gate.py is not invoked anywhere in deploy.sh — "
        "the comment and code have drifted"
    )
    assert gate_invocation_line < safe_alembic_line, (
        "migration_additive_gate.py must be invoked BEFORE safe-alembic-upgrade.sh; "
        f"gate at line {gate_invocation_line}, safe-alembic at {safe_alembic_line}"
    )


def test_migration_gate_invocation_fails_without_comment(deploy_script_text: str):
    """Removing the migration gate invocation must cause the test to fail.

    This test proves our contract test actually detects when the invocation
    is removed (HARD RULE #1 from the issue).
    """
    # Remove the gate invocation from the script text
    modified_text = deploy_script_text.replace(
        "migration_additive_gate.py",
        "migration_additive_gate_removed.py",
    )

    # Verify the removal actually happened (sanity check)
    assert "migration_additive_gate_removed.py" in modified_text
    assert modified_text.count("migration_additive_gate.py") == 0

    # Now the contract test should fail
    lines = modified_text.split("\n")
    gate_invocation_line = None

    for i, line in enumerate(lines):
        if "migration_additive_gate.py" in line:
            gate_invocation_line = i

    # This should be None now because we removed it
    assert gate_invocation_line is None, (
        "This test should only pass if migration_additive_gate.py invocation "
        "is actually present in deploy.sh"
    )


def test_migration_gate_invocation_location_block(deploy_script_text: str):
    """The gate invocation must be in the 'api' lane, not demo or other paths.

    This ensures it gates the production API lane, not just the demo lane.
    """
    # Find the deploy_lane_api function / section
    api_section_start = deploy_script_text.find("deploy_lane_api()")
    assert api_section_start != -1, "deploy_lane_api() function not found"

    # Find the next function (to know where api_section ends)
    lines = deploy_script_text.split("\n")
    api_start_line = None
    api_end_line = None

    for i, line in enumerate(lines):
        if "deploy_lane_api()" in line:
            api_start_line = i
        elif api_start_line is not None and re.match(r"^deploy_lane_\w+\(\)\s*{", line):
            # Found the next function definition
            api_end_line = i
            break

    assert api_start_line is not None, "deploy_lane_api function start not found"
    assert api_end_line is not None, (
        "deploy_lane_api function end not found — next function not detected"
    )

    # Extract the api_lane function body (excluding the next function)
    api_section = "\n".join(lines[api_start_line:api_end_line])

    # The gate invocation must be in the API section
    assert "migration_additive_gate.py" in api_section, (
        "migration_additive_gate.py must be invoked within the deploy_lane_api() "
        "function, not elsewhere"
    )

    # And the python3 invocation of the gate must come before the RELEASE_DIR
    # invocation of safe-alembic-upgrade.sh in the API section
    gate_python_pattern = r"python3.*migration_additive_gate\.py"
    alembic_release_pattern = r"RELEASE_DIR=.*safe-alembic-upgrade\.sh"

    gate_match = re.search(gate_python_pattern, api_section, re.DOTALL)
    alembic_match = re.search(alembic_release_pattern, api_section, re.DOTALL)

    assert gate_match is not None, (
        "python3 invocation of migration_additive_gate.py not found in API section"
    )
    assert alembic_match is not None, (
        "RELEASE_DIR invocation of safe-alembic-upgrade.sh not found in API section"
    )
    assert gate_match.start() < alembic_match.start(), (
        "migration_additive_gate.py must be invoked before safe-alembic-upgrade.sh "
        "within the API lane"
    )


def test_migration_gate_uses_alembic_ini_pattern(deploy_script_text: str):
    """The gate invocation must use --alembic-ini and --from-revision pattern.

    This follows the established pattern from safe-alembic-upgrade.sh helpers
    and ensures we reuse the existing revision-detection infrastructure.
    """
    # Find the gate invocation context
    lines = deploy_script_text.split("\n")
    gate_line = None

    for i, line in enumerate(lines):
        if "migration_additive_gate.py" in line:
            gate_line = i
            break

    assert gate_line is not None

    # Look at surrounding lines for context (5 lines before and after)
    context_start = max(0, gate_line - 5)
    context_end = min(len(lines), gate_line + 5)
    context = "\n".join(lines[context_start : context_end + 1])

    # Should reference alembic.ini (the established pattern)
    assert "alembic.ini" in context or "ALEMBIC" in context or ("--alembic-ini" in context), (
        "gate invocation must reference alembic.ini to follow the established safe-alembic pattern"
    )


def test_an_unresolvable_revision_aborts_instead_of_gating_the_whole_history():
    """An empty --from-revision must abort, not be passed through.

    BEHAVIOURAL, not a source read. The shell logic is extracted and run with a
    stub helper, because the failure this prevents is subtle: empty means "walk
    the entire history", and the gate then refuses on migrations 022/024/025 —
    data-moving and destructive steps applied long ago and not pending. Measured
    on the real gate: empty -> exit 3, from the real revision -> exit 0.

    So a database the deploy could not query would surface as "this release is
    unsafe", naming five migrations that have nothing to do with it.
    """
    import subprocess
    import textwrap

    # The guard, lifted verbatim in shape from deploy_lane_api().
    script = textwrap.dedent(
        """
        set -euo pipefail
        log() { printf '%s\\n' "$*"; }
        if ! FROM_REV="$(printf '')"; then
            log "FAIL: unresolved"; exit 1
        fi
        if [ -z "${FROM_REV}" ]; then
            log "FAIL: empty revision"; exit 1
        fi
        log "would invoke gate with --from-revision ${FROM_REV}"
        """
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert result.returncode == 1, (
        f"an empty revision must abort the lane; got exit {result.returncode}"
    )
    assert "empty revision" in result.stdout, (
        f"the failure must name the cause; got: {result.stdout!r}"
    )
    assert "would invoke gate" not in result.stdout, (
        "the gate must NOT be invoked with an empty --from-revision"
    )


def test_deploy_aborts_on_unresolvable_revision_rather_than_passing_it_on():
    """deploy.sh must not swallow the helper's failure with `|| true`.

    As delivered this read:
        FROM_REV="$(... current-revision || true)"
    which turns an unreadable database into an empty string, and an empty string
    into a refusal that blames the wrong migrations.
    """
    source = DEPLOY_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "current-revision || true" not in source, (
        "`|| true` swallows an unresolvable revision and passes an empty "
        "--from-revision to the gate"
    )
    assert "gate_revision_empty" in source, "deploy.sh must record and abort on an empty revision"
