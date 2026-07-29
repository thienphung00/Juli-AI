"""CI mode contract for audit_cycles.py (MMU-3 / #556)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "agent-runtime/scripts/ci/audit_cycles.py"


def test_audit_cycles_ci_mode_passes_when_no_cycles() -> None:
    result = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--ci"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dependency_cycles: PASS" in result.stdout
