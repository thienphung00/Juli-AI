"""Scripts deploy.sh runs are given an interpreter that can import them.

THE OUTAGE THIS PREVENTS. #1555 added the additive migration gate to the API
lane and invoked it with bare `python3`. The gate lazily imports
`alembic.config` and `safe_alembic_helpers`
(`migration_additive_gate.py:727-731`), and the VPS's system python3 has
neither — so from the moment it merged, every production deploy died with:

    ADDITIVE-ONLY: ERROR
      No module named 'alembic'

The failure named the gate rather than the interpreter, so it read as "this
release has a non-additive migration" when nothing was wrong with the release
at all. Production sat 15 commits behind main until someone deployed and read
the log. The `current-revision` call immediately above it already used the
release venv, so the two lines disagreed about their own interpreter.

A `python3` heredoc using only json/sys is fine and stays fine — this checks
only invocations of a .py FILE under infra/scripts, which are the ones with
third-party imports.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "infra" / "scripts" / "deploy.sh"

#: Matches an invocation of a .py file under infra/scripts, capturing whatever
#: token launched it. Tolerates the line continuation deploy.sh uses.
_INVOCATION = re.compile(
    r"(?P<interpreter>\S+)\s*(?:\\\s*\n\s*)?\"\$\{CANONICAL_ROOT\}/infra/scripts/(?P<script>[\w.]+\.py)\""
)


def _invocations() -> list[tuple[str, str]]:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    stripped = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return [(m.group("interpreter"), m.group("script")) for m in _INVOCATION.finditer(stripped)]


def test_deploy_sh_invokes_helper_scripts_with_the_release_interpreter():
    """Every infra/scripts/*.py deploy.sh runs must use the release venv."""
    found = _invocations()

    assert found, (
        "no infra/scripts/*.py invocations found in deploy.sh — the regex has gone "
        "stale against the file it guards, so this test is no longer checking anything"
    )

    wrong = [(i, s) for i, s in found if ".venv/bin/python" not in i]
    assert not wrong, (
        "deploy.sh runs these with an interpreter that cannot import their "
        f'dependencies: {wrong}. Use "${{release_dir}}/.venv/bin/python" — the VPS\'s '
        "system python3 has neither alembic nor the backend package, and the "
        "resulting error names the gate rather than the interpreter."
    )


def test_the_additive_gate_specifically_is_covered():
    """Name the script that actually caused the outage, so a regex drift is loud."""
    scripts = {s for _, s in _invocations()}

    assert "migration_additive_gate.py" in scripts, (
        "migration_additive_gate.py is no longer matched as a deploy.sh invocation; "
        f"matched: {sorted(scripts)}"
    )
